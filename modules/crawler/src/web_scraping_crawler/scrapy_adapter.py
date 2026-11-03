"""Optional Scrapy HTTP adapter for the crawler core."""

from __future__ import annotations

import asyncio
import hashlib
from collections.abc import Iterable
from types import SimpleNamespace
from typing import List, Optional, Set, Tuple
from urllib.parse import urljoin

from .crawler import (
    CrawlFailure,
    CrawlPolicy,
    CrawlResult,
    LinkDiscoverer,
    _is_url_in_scope,
    _normalize_url,
)

REQUEST_TIMEOUT_SECONDS = 15
CLICK_TIMEOUT_MILLISECONDS = 8000
CLICK_SETTLE_MILLISECONDS = 200
LOAD_MORE_WAIT_MILLISECONDS = 2000
DEFAULT_PLAYWRIGHT_CLICK_SELECTORS = (".child-card",)
RETRY_COUNT = 4
TOTAL_CONCURRENCY = 4
PER_DOMAIN_CONCURRENCY = 2
THROTTLE_START_DELAY_SECONDS = 1.0
THROTTLE_MAX_DELAY_SECONDS = 10.0


def crawl_with_scrapy(
    seeds: Iterable[str],
    policy: CrawlPolicy,
    link_discoverer: LinkDiscoverer[str],
    render_javascript: bool = False,
    render_wait_for: Optional[str] = None,
    click_selectors: Optional[Iterable[str]] = None,
    load_more_selectors: Optional[Iterable[str]] = None,
    max_load_more_clicks: int = 20,
) -> CrawlResult:
    """Run one standalone Scrapy crawl and return its traversal metadata.

    Set ``render_javascript`` to opt eligible page requests into Playwright.
    ``render_wait_for`` optionally waits for a CSS selector before extracting
    links. ``load_more_selectors`` are clicked before ``click_selectors``;
    each is limited by ``max_load_more_clicks`` per page. Browser rendering
    requires the optional ``playwright`` extra.

    This helper starts Scrapy's Twisted reactor and is intended for a normal
    synchronous script. The reactor cannot be restarted, so call this helper
    at most once in a Python process. Use a runner-based integration when
    embedding Scrapy in an application that already owns an event loop.
    """
    if not isinstance(render_javascript, bool):
        raise ValueError("render_javascript must be a bool")
    if render_wait_for is not None and (
        not isinstance(render_wait_for, str) or not render_wait_for.strip()
    ):
        raise ValueError("render_wait_for must be a non-empty CSS selector")
    if render_wait_for is not None and not render_javascript:
        raise ValueError("render_wait_for requires render_javascript=True")
    if (
        isinstance(max_load_more_clicks, bool)
        or not isinstance(max_load_more_clicks, int)
        or max_load_more_clicks < 1
    ):
        raise ValueError("max_load_more_clicks must be a positive integer")
    if click_selectors is None:
        normalized_click_selectors = (
            DEFAULT_PLAYWRIGHT_CLICK_SELECTORS if render_javascript else ()
        )
    else:
        if isinstance(click_selectors, str):
            raise ValueError("click_selectors must be a sequence of CSS selectors")
        normalized_click_selectors = tuple(click_selectors)
        if any(
            not isinstance(selector, str) or not selector.strip()
            for selector in normalized_click_selectors
        ):
            raise ValueError("click_selectors must contain non-empty CSS selectors")
        if normalized_click_selectors and not render_javascript:
            raise ValueError("click_selectors requires render_javascript=True")
        if normalized_click_selectors:
            normalized_click_selectors = tuple(
                dict.fromkeys(
                    (*DEFAULT_PLAYWRIGHT_CLICK_SELECTORS, *normalized_click_selectors)
                )
            )
    if load_more_selectors is None:
        normalized_load_more_selectors = ()
    else:
        if isinstance(load_more_selectors, str):
            raise ValueError(
                "load_more_selectors must be a sequence of CSS selectors"
            )
        normalized_load_more_selectors = tuple(load_more_selectors)
        if any(
            not isinstance(selector, str) or not selector.strip()
            for selector in normalized_load_more_selectors
        ):
            raise ValueError(
                "load_more_selectors must contain non-empty CSS selectors"
            )
        normalized_load_more_selectors = tuple(
            dict.fromkeys(normalized_load_more_selectors)
        )
        if normalized_load_more_selectors and not render_javascript:
            raise ValueError("load_more_selectors requires render_javascript=True")

    try:
        from scrapy.crawler import CrawlerProcess
        from scrapy.core.scheduler import Scheduler
        from scrapy.exceptions import IgnoreRequest
        from scrapy.spiders import Spider
        from scrapy import signals
    except ImportError as exc:
        raise ImportError(
            "Scrapy support requires the optional dependency; install "
            "'web-scraping-crawler[scrapy]'."
        ) from exc

    if render_javascript:
        try:
            from scrapy_playwright.page import PageMethod
            from scrapy_playwright._loop import _ThreadedLoopAdapter
            from scrapy_playwright.handler import ScrapyPlaywrightDownloadHandler
        except ImportError as exc:
            raise ImportError(
                "Playwright rendering requires the optional dependency; "
                "install 'web-scraping-crawler[playwright]' and run "
                "'python -m playwright install chromium'."
            ) from exc

        async def discover_clicked_urls(
            page,
            selectors,
            allowed_domains,
            allowed_url_prefixes,
            page_url,
            load_more_selectors,
            max_load_more_clicks,
        ):
            from playwright.async_api import Error as PlaywrightError
            from playwright.async_api import TimeoutError as PlaywrightTimeoutError

            discovered = []
            out_of_scope = []
            click_errors = []
            selector_counts = []
            load_more_click_counts = []
            load_more_click_totals = {
                selector: 0 for selector in load_more_selectors
            }
            source_url = _normalize_url(page_url)
            navigation_attempts = 0

            main_frame_navigation = asyncio.Event()

            def mark_main_frame_navigation(frame):
                if frame == page.main_frame:
                    main_frame_navigation.set()

            async def guard_navigation(route):
                nonlocal navigation_attempts
                request = route.request
                if (
                    request.is_navigation_request()
                    and request.frame == page.main_frame
                    and request.url != source_url
                ):
                    navigation_attempts += 1
                    try:
                        target = _normalize_url(request.url)
                    except ValueError:
                        target = None
                    if target is not None:
                        if _is_url_in_scope(
                            target, allowed_domains, allowed_url_prefixes
                        ):
                            discovered.append(target)
                        else:
                            out_of_scope.append(target)
                    await route.abort()
                    return
                await route.continue_()

            async def wait_for_click_navigation(previous_url, previous_attempts):
                deadline = (
                    asyncio.get_running_loop().time()
                    + CLICK_TIMEOUT_MILLISECONDS / 1000
                )
                while (
                    page.url == previous_url
                    and navigation_attempts == previous_attempts
                    and asyncio.get_running_loop().time() < deadline
                ):
                    await page.wait_for_timeout(50)

            await page.route("**/*", guard_navigation)
            page.on("framenavigated", mark_main_frame_navigation)

            async def restore_loaded_cards(expected_card_count):
                restore_clicks = 0
                for selector in load_more_selectors:
                    locator = page.locator(selector)
                    while restore_clicks < max_load_more_clicks:
                        previous_card_count = await page.locator(
                            ".child-card"
                        ).count()
                        if previous_card_count >= expected_card_count:
                            return
                        try:
                            await locator.first.wait_for(
                                state="visible",
                                timeout=LOAD_MORE_WAIT_MILLISECONDS,
                            )
                            if not await locator.first.is_enabled():
                                break
                            await locator.first.click(
                                timeout=CLICK_TIMEOUT_MILLISECONDS
                            )
                        except PlaywrightTimeoutError:
                            break
                        except PlaywrightError as exc:
                            click_errors.append(
                                "{} load-more restore click: {}".format(
                                    selector, exc
                                )
                            )
                            break

                        restore_clicks += 1
                        load_more_click_totals[selector] += 1
                        try:
                            await page.wait_for_function(
                                """({previousCount, selector}) =>
                                    document.querySelectorAll('.child-card').length > previousCount
                                    || !document.querySelector(selector)
                                """,
                                arg={
                                    "previousCount": previous_card_count,
                                    "selector": selector,
                                },
                                timeout=CLICK_TIMEOUT_MILLISECONDS,
                            )
                        except PlaywrightTimeoutError:
                            break
                        await page.wait_for_timeout(CLICK_SETTLE_MILLISECONDS)

                    if await page.locator(".child-card").count() >= expected_card_count:
                        return

            try:
                total_load_more_clicks = 0
                for selector in load_more_selectors:
                    locator = page.locator(selector)
                    while total_load_more_clicks < max_load_more_clicks:
                        try:
                            await locator.first.wait_for(
                                state="visible",
                                timeout=LOAD_MORE_WAIT_MILLISECONDS,
                            )
                        except PlaywrightTimeoutError:
                            break

                        try:
                            if not await locator.first.is_enabled():
                                break
                            previous_card_count = await page.locator(
                                ".child-card"
                            ).count()
                            await locator.first.click(
                                timeout=CLICK_TIMEOUT_MILLISECONDS
                            )
                        except PlaywrightError as exc:
                            click_errors.append(
                                "{} load-more click: {}".format(selector, exc)
                            )
                            break

                        load_more_click_totals[selector] += 1
                        total_load_more_clicks += 1
                        made_progress = True
                        try:
                            await page.wait_for_function(
                                """({selector, previousCount, sourceUrl}) => {
                                    const button = document.querySelector(selector);
                                    return !button
                                        || button.disabled
                                        || button.getAttribute('aria-disabled') === 'true'
                                        || window.location.href !== sourceUrl
                                        || document.querySelectorAll('.child-card').length > previousCount;
                                }""",
                                arg={
                                    "selector": selector,
                                    "previousCount": previous_card_count,
                                    "sourceUrl": source_url,
                                },
                                timeout=CLICK_TIMEOUT_MILLISECONDS,
                            )
                        except PlaywrightTimeoutError:
                            made_progress = False

                        await page.wait_for_timeout(CLICK_SETTLE_MILLISECONDS)

                        try:
                            current_url = _normalize_url(page.url)
                        except ValueError:
                            current_url = None
                        if current_url is None:
                            await page.goto(
                                source_url,
                                wait_until="domcontentloaded",
                                timeout=REQUEST_TIMEOUT_SECONDS * 1000,
                            )
                            break
                        if current_url != source_url:
                            if _is_url_in_scope(
                                current_url,
                                allowed_domains,
                                allowed_url_prefixes,
                            ):
                                discovered.append(current_url)
                            else:
                                out_of_scope.append(current_url)
                            try:
                                await page.go_back(
                                    wait_until="domcontentloaded",
                                    timeout=CLICK_TIMEOUT_MILLISECONDS,
                                )
                            except PlaywrightError:
                                await page.goto(
                                    source_url,
                                    wait_until="domcontentloaded",
                                    timeout=REQUEST_TIMEOUT_SECONDS * 1000,
                                )
                            break
                        if not made_progress:
                            break
                for selector in selectors:
                    locator = page.locator(selector)
                    try:
                        await locator.first.wait_for(
                            state="visible",
                            timeout=CLICK_TIMEOUT_MILLISECONDS,
                        )
                    except PlaywrightTimeoutError:
                        selector_counts.append((selector, 0))
                        continue
                    try:
                        count = await locator.count()
                    except PlaywrightError as exc:
                        click_errors.append("{}: {}".format(selector, exc))
                        continue
                    selector_counts.append((selector, count))
                    for index in range(count):
                        discovered_before_click = len(discovered)
                        previous_url = page.url
                        previous_navigation_attempts = navigation_attempts
                        main_frame_navigation.clear()
                        try:
                            await locator.nth(index).click(
                                timeout=CLICK_TIMEOUT_MILLISECONDS,
                                no_wait_after=True,
                            )
                        except PlaywrightError as exc:
                            if len(discovered) == discovered_before_click:
                                click_errors.append(
                                    "{}[{}]: {}".format(selector, index, exc)
                                )
                        else:
                            await wait_for_click_navigation(
                                previous_url, previous_navigation_attempts
                            )
                            await page.wait_for_timeout(CLICK_SETTLE_MILLISECONDS)

                        if navigation_attempts != previous_navigation_attempts:
                            if not main_frame_navigation.is_set():
                                try:
                                    await asyncio.wait_for(
                                        main_frame_navigation.wait(),
                                        timeout=CLICK_TIMEOUT_MILLISECONDS / 1000,
                                    )
                                except asyncio.TimeoutError:
                                    pass
                            await page.goto(
                                source_url,
                                wait_until="domcontentloaded",
                                timeout=REQUEST_TIMEOUT_SECONDS * 1000,
                            )
                            await restore_loaded_cards(count)
                            continue

                        try:
                            current_url = _normalize_url(page.url)
                        except ValueError:
                            current_url = None

                        if current_url is None:
                            await page.goto(
                                source_url,
                                wait_until="domcontentloaded",
                                timeout=REQUEST_TIMEOUT_SECONDS * 1000,
                            )
                            await restore_loaded_cards(count)
                        elif current_url != source_url:
                            if _is_url_in_scope(
                                current_url,
                                allowed_domains,
                                allowed_url_prefixes,
                            ):
                                discovered.append(current_url)
                            try:
                                await page.go_back(
                                    wait_until="domcontentloaded",
                                    timeout=CLICK_TIMEOUT_MILLISECONDS,
                                )
                            except PlaywrightError:
                                await page.goto(
                                    source_url,
                                    wait_until="domcontentloaded",
                                    timeout=REQUEST_TIMEOUT_SECONDS * 1000,
                                )
                            await restore_loaded_cards(count)
            finally:
                page.remove_listener(
                    "framenavigated", mark_main_frame_navigation
                )
                await page.unroute("**/*", guard_navigation)

            load_more_click_counts.extend(
                (selector, clicks)
                for selector, clicks in load_more_click_totals.items()
            )
            return {
                "urls": tuple(dict.fromkeys(discovered)),
                "out_of_scope_urls": tuple(dict.fromkeys(out_of_scope)),
                "errors": tuple(click_errors),
                "selector_counts": tuple(selector_counts),
                "load_more_click_counts": tuple(load_more_click_counts),
            }

        class GracefulPlaywrightDownloadHandler(ScrapyPlaywrightDownloadHandler):
            async def close(self):
                await super(ScrapyPlaywrightDownloadHandler, self).close()
                await self._maybe_future_from_coro(self._close())
                if not self.config.use_threaded_loop:
                    return

                adapter = _ThreadedLoopAdapter
                adapter._stop_events[id(self)].set()
                if all(event.is_set() for event in adapter._stop_events.values()):
                    loop = adapter._loop
                    # Wake the queue consumer so it can observe the stop event.
                    wake_item = SimpleNamespace(promise=None)
                    await asyncio.wrap_future(
                        asyncio.run_coroutine_threadsafe(
                            adapter._coro_queue.put(wake_item),
                            loop,
                        )
                    )
                    await asyncio.wrap_future(
                        asyncio.run_coroutine_threadsafe(
                            adapter._coro_queue.join(),
                            loop,
                        )
                    )
                    loop.call_soon_threadsafe(loop.stop)
                    adapter._thread.join()

    normalized_seeds = []
    seen_seeds: Set[str] = set()
    for seed in seeds:
        normalized = _normalize_url(seed)
        if not _is_url_in_scope(
            normalized,
            policy.allowed_domains,
            policy.allowed_url_prefixes,
        ):
            raise ValueError("seed URL is outside the configured crawl scope")
        if normalized not in seen_seeds:
            seen_seeds.add(normalized)
            normalized_seeds.append(normalized)

    class URLIdentityFingerprinter:
        @classmethod
        def from_crawler(cls, crawler):
            return cls()

        def fingerprint(self, request):
            try:
                identity = _normalize_url(request.url)
            except ValueError:
                identity = request.url
            return hashlib.sha256(identity.encode("utf-8")).digest()

    class BoundedScheduler(Scheduler):
        def enqueue_request(self, request):
            internal_request = (
                bool(request.meta.get("redirect_urls"))
                or "retry_times" in request.meta
            )
            if not internal_request:
                current_count = self.stats.get_value(
                    "crawler/scheduled_pages", 0
                )
                if current_count >= self.spider.policy.max_pages:
                    self.stats.inc_value("crawler/pages_rejected_limit")
                    return False

            accepted = super().enqueue_request(request)
            if accepted and not internal_request:
                self.stats.inc_value("crawler/scheduled_pages")
            return accepted

    class ScopeGuardMiddleware:
        @classmethod
        def from_crawler(cls, crawler):
            middleware = cls()
            middleware.crawler = crawler
            return middleware

        def process_request(self, request, *args):
            spider = args[0] if args else self.crawler.spider
            try:
                normalized = _normalize_url(request.url)
            except ValueError as exc:
                request.meta["_crawl_scope_rejection"] = {
                    "url": request.url,
                    "message": str(exc),
                }
                raise IgnoreRequest("redirect destination is not a valid HTTP(S) URL")

            prefixes = (
                spider.policy.allowed_url_prefixes
            )
            if not _is_url_in_scope(
                normalized,
                spider.policy.allowed_domains,
                prefixes,
            ):
                request.meta["_crawl_scope_rejection"] = {
                    "url": normalized,
                    "message": "redirect destination is outside the configured crawl scope",
                }
                raise IgnoreRequest("redirect destination is outside the configured crawl scope")

            return None

    class PolicyTimeLimitExtension:
        def __init__(self, crawler):
            self.crawler = crawler
            self.call = None

        @classmethod
        def from_crawler(cls, crawler):
            extension = cls(crawler)
            crawler.signals.connect(
                extension.spider_opened, signal=signals.spider_opened
            )
            crawler.signals.connect(
                extension.spider_closed, signal=signals.spider_closed
            )
            return extension

        def spider_opened(self, spider):
            from twisted.internet import reactor

            self.call = reactor.callLater(
                spider.policy.max_elapsed_time,
                self.close_for_time_limit,
                spider,
            )

        def close_for_time_limit(self, spider):
            engine = spider.crawler.engine
            if engine is None:
                return

            close_spider_async = getattr(engine, "close_spider_async", None)
            if close_spider_async is None:
                engine.close_spider(spider, "time_limit")
                return

            from scrapy.utils.defer import deferred_from_coro

            deferred_from_coro(close_spider_async(reason="time_limit"))

        def spider_closed(self, spider, reason):
            if self.call is not None and self.call.active():
                self.call.cancel()

    class PolicySpider(Spider):
        name = "bounded_policy_crawl"
        custom_settings = {
            "ROBOTSTXT_OBEY": False,
            "DOWNLOAD_TIMEOUT": REQUEST_TIMEOUT_SECONDS,
            "RETRY_ENABLED": True,
            "RETRY_TIMES": RETRY_COUNT,
            "CONCURRENT_REQUESTS": TOTAL_CONCURRENCY,
            "CONCURRENT_REQUESTS_PER_DOMAIN": PER_DOMAIN_CONCURRENCY,
            "DOWNLOAD_DELAY": THROTTLE_START_DELAY_SECONDS,
            "AUTOTHROTTLE_ENABLED": True,
            "AUTOTHROTTLE_START_DELAY": THROTTLE_START_DELAY_SECONDS,
            "AUTOTHROTTLE_MAX_DELAY": THROTTLE_MAX_DELAY_SECONDS,
            "AUTOTHROTTLE_TARGET_CONCURRENCY": 1.0,
            "SCHEDULER": BoundedScheduler,
            "REQUEST_FINGERPRINTER_CLASS": URLIdentityFingerprinter,
            "DOWNLOADER_MIDDLEWARES": {ScopeGuardMiddleware: 50},
            "EXTENSIONS": {PolicyTimeLimitExtension: 500},
            "LOG_LEVEL": "WARNING",
        }

        def __init__(
            self,
            policy: CrawlPolicy,
            seeds: Tuple[str, ...],
            link_discoverer: LinkDiscoverer[str],
            render_javascript: bool,
            render_wait_for: Optional[str],
            click_selectors: Tuple[str, ...],
            load_more_selectors: Tuple[str, ...],
            max_load_more_clicks: int,
            **kwargs,
        ):
            super().__init__(**kwargs)
            self.policy = policy
            self.seeds = seeds
            self.link_discoverer = link_discoverer
            self.render_javascript = render_javascript
            self.render_wait_for = render_wait_for
            self.click_selectors = click_selectors
            self.load_more_selectors = load_more_selectors
            self.max_load_more_clicks = max_load_more_clicks
            self._visited: List[str] = []
            self._visited_set: Set[str] = set()
            self._successful: List[str] = []
            self._successful_set: Set[str] = set()
            self._failures: List[CrawlFailure] = []
            self._discovered: List[str] = []
            self._discovered_set: Set[str] = set()
            self._out_of_scope_urls: List[str] = []
            self._out_of_scope_url_set: Set[str] = set()
            self._edges: List[Tuple[str, str]] = []
            self._edge_set: Set[Tuple[str, str]] = set()
            self._click_selector_counts: List[Tuple[str, str, int]] = []
            self._load_more_click_counts: List[Tuple[str, str, int]] = []

        def start_requests(self):
            for url in self.seeds:
                yield self._request(url, 0)

        async def start(self):
            for url in self.seeds:
                yield self._request(url, 0)

        def parse(self, response):
            page_url = response.meta.get("_crawl_page_url", response.url)
            self._record(self._visited, self._visited_set, page_url)

            if 300 <= response.status < 400:
                destination = self._redirect_destination(response)
                self._failures.append(
                    CrawlFailure(
                        url=page_url,
                        stage="redirect",
                        error_type="RedirectError",
                        message="redirect response could not be followed safely",
                        redirect_url=destination,
                    )
                )
                return

            if response.status >= 400:
                self._failures.append(
                    CrawlFailure(
                        url=page_url,
                        stage="retrieve",
                        error_type="HTTPStatusError",
                        message="HTTP response status {}".format(response.status),
                    )
                )
                return

            try:
                final_url = _normalize_url(response.url)
            except ValueError as exc:
                self._failures.append(
                    CrawlFailure(
                        url=page_url,
                        stage="redirect",
                        error_type=type(exc).__name__,
                        message=str(exc),
                        redirect_url=response.url,
                    )
                )
                return

            if not _is_url_in_scope(
                final_url,
                self.policy.allowed_domains,
                self.policy.allowed_url_prefixes,
            ):
                self._failures.append(
                    CrawlFailure(
                        url=page_url,
                        stage="redirect",
                        error_type="OutOfScopeRedirect",
                        message="redirect destination is outside the configured crawl scope",
                        redirect_url=final_url,
                    )
                )
                return

            self._record(self._successful, self._successful_set, page_url)
            depth = response.meta.get("_crawl_depth", 0)
            try:
                links = self.link_discoverer.discover_links(response.text)
                if isinstance(links, str):
                    raise TypeError(
                        "link discoverer must return an iterable of strings"
                    )
                candidates = list(links)
                if any(not isinstance(link, str) for link in candidates):
                    raise TypeError("link discoverer must return strings")
            except Exception as exc:
                self._failures.append(
                    CrawlFailure(
                        url=page_url,
                        stage="discover",
                        error_type=type(exc).__name__,
                        message=str(exc),
                    )
                )
                return

            if self.render_javascript:
                page_methods = response.meta.get("playwright_page_methods", ())
                click_result = next(
                    (
                        method.result
                        for method in page_methods
                        if method.method is discover_clicked_urls
                    ),
                    None,
                )
                if isinstance(click_result, dict):
                    candidates.extend(click_result.get("urls", ()))
                    for target in click_result.get("out_of_scope_urls", ()):
                        if target not in self._out_of_scope_url_set:
                            self._out_of_scope_url_set.add(target)
                            self._out_of_scope_urls.append(target)
                    self._click_selector_counts.extend(
                        (page_url, selector, count)
                        for selector, count in click_result.get(
                            "selector_counts", ()
                        )
                    )
                    self._load_more_click_counts.extend(
                        (page_url, selector, count)
                        for selector, count in click_result.get(
                            "load_more_click_counts", ()
                        )
                    )
                    click_errors = click_result.get("errors", ())
                    if click_errors:
                        self._failures.append(
                            CrawlFailure(
                                url=page_url,
                                stage="discover",
                                error_type="PlaywrightClickError",
                                message="; ".join(click_errors),
                            )
                        )

            requests = []
            for link in candidates:
                try:
                    target = _normalize_url(link, base_url=final_url)
                except ValueError:
                    continue
                if not _is_url_in_scope(
                    target,
                    self.policy.allowed_domains,
                    self.policy.allowed_url_prefixes,
                ):
                    continue

                edge = (final_url, target)
                if edge not in self._edge_set:
                    self._edge_set.add(edge)
                    self._edges.append(edge)
                if target not in seen_seeds:
                    self._record(
                        self._discovered, self._discovered_set, target
                    )
                if depth < self.policy.max_depth:
                    requests.append(self._request(target, depth + 1))

            return requests

        def errback(self, failure):
            request = failure.request
            page_url = request.meta.get("_crawl_page_url", request.url)
            self._record(self._visited, self._visited_set, page_url)
            rejection = request.meta.get("_crawl_scope_rejection")

            if rejection is not None:
                self._failures.append(
                    CrawlFailure(
                        url=page_url,
                        stage="redirect",
                        error_type="OutOfScopeRedirect",
                        message=rejection["message"],
                        redirect_url=rejection["url"],
                    )
                )
                return

            response = getattr(failure.value, "response", None)
            status = getattr(response, "status", None)
            if status is not None and 300 <= status < 400:
                self._failures.append(
                    CrawlFailure(
                        url=page_url,
                        stage="redirect",
                        error_type="RedirectError",
                        message="redirect response could not be followed safely",
                        redirect_url=self._redirect_destination(response),
                    )
                )
                return
            if status is not None:
                error_type = "HTTPStatusError"
                message = "HTTP response status {}".format(status)
            else:
                error_type = type(failure.value).__name__
                message = str(failure.value)
            self._failures.append(
                CrawlFailure(
                    url=page_url,
                    stage="retrieve",
                    error_type=error_type,
                    message=message,
                )
            )

        @property
        def result(self) -> CrawlResult:
            return CrawlResult(
                visited_urls=tuple(self._visited),
                successful_urls=tuple(self._successful),
                failed_urls=tuple(self._failures),
                discovered_urls=tuple(self._discovered),
                link_edges=tuple(self._edges),
                click_selector_counts=tuple(self._click_selector_counts),
                load_more_click_counts=tuple(self._load_more_click_counts),
                out_of_scope_urls=tuple(self._out_of_scope_urls),
            )

        def _request(self, url: str, depth: int):
            from scrapy import Request

            meta = {
                "_crawl_page_url": url,
                "_crawl_depth": depth,
            }
            if self.render_javascript:
                meta["playwright"] = True
                page_methods = []
                if self.render_wait_for is not None:
                    page_methods.append(
                        PageMethod(
                            "wait_for_selector",
                            self.render_wait_for,
                            timeout=REQUEST_TIMEOUT_SECONDS * 1000,
                        )
                    )
                if self.click_selectors or self.load_more_selectors:
                    page_methods.append(
                        PageMethod(
                            discover_clicked_urls,
                            self.click_selectors,
                            self.policy.allowed_domains,
                            self.policy.allowed_url_prefixes,
                            url,
                            self.load_more_selectors,
                            self.max_load_more_clicks,
                        )
                    )
                if page_methods:
                    meta["playwright_page_methods"] = page_methods

            return Request(
                url=url,
                callback=self.parse,
                errback=self.errback,
                meta=meta,
                dont_filter=False,
            )

        def _redirect_destination(self, response) -> Optional[str]:
            location = response.headers.get("Location")
            if location is None:
                return None
            raw_location = location.decode("latin-1")
            try:
                return _normalize_url(raw_location, base_url=response.url)
            except ValueError:
                return urljoin(response.url, raw_location)

        @staticmethod
        def _record(values, seen, value):
            if value not in seen:
                seen.add(value)
                values.append(value)

    settings = dict(PolicySpider.custom_settings)
    if render_javascript:
        settings.update(
            {
                "TWISTED_REACTOR": (
                    "twisted.internet.asyncioreactor.AsyncioSelectorReactor"
                ),
                "DOWNLOAD_HANDLERS": {
                    "http": GracefulPlaywrightDownloadHandler,
                    "https": GracefulPlaywrightDownloadHandler,
                },
                "PLAYWRIGHT_BROWSER_TYPE": "chromium",
                "PLAYWRIGHT_LAUNCH_OPTIONS": {"headless": True},
                "PLAYWRIGHT_MAX_CONTEXTS": 2,
                "PLAYWRIGHT_MAX_PAGES_PER_CONTEXT": 2,
                "PLAYWRIGHT_DEFAULT_NAVIGATION_TIMEOUT": (
                    REQUEST_TIMEOUT_SECONDS * 1000
                ),
            }
        )

    process = CrawlerProcess(settings=settings)
    crawler = process.create_crawler(PolicySpider)
    process.crawl(
        crawler,
        policy=policy,
        seeds=tuple(normalized_seeds),
        link_discoverer=link_discoverer,
        render_javascript=render_javascript,
        render_wait_for=render_wait_for,
        click_selectors=normalized_click_selectors,
        load_more_selectors=normalized_load_more_selectors,
        max_load_more_clicks=max_load_more_clicks,
    )
    process.start()

    if crawler.spider is None:
        raise RuntimeError("Scrapy did not create the policy spider")
    return crawler.spider.result
