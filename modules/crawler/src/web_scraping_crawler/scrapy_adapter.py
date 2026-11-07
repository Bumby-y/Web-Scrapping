"""Optional Scrapy HTTP adapter for the crawler core."""

from __future__ import annotations

import asyncio
import hashlib
import math
import time
from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass
from types import SimpleNamespace
from typing import Callable, Dict, List, Optional, Set, Tuple
from urllib.parse import urljoin, urlsplit

from .crawler import (
    CrawlFailure,
    CrawlLinkReference,
    CrawlPolicy,
    CrawlResult,
    LinkDiscoverer,
    LinkReference,
    _is_url_in_scope,
    _normalize_url,
)

REQUEST_TIMEOUT_SECONDS = 15
CLICK_TIMEOUT_MILLISECONDS = 8000
CLICK_NAVIGATION_TIMEOUT_MILLISECONDS = 1000
CLICK_ABORT_NAVIGATION_TIMEOUT_MILLISECONDS = 2500
CLICK_SETTLE_MILLISECONDS = 200
LOAD_MORE_WAIT_MILLISECONDS = 2000
DEFAULT_PLAYWRIGHT_CLICK_SELECTORS = (".child-card",)
RETRY_COUNT = 2
TOTAL_CONCURRENCY = 4
PER_DOMAIN_CONCURRENCY = 2
THROTTLE_START_DELAY_SECONDS = 1.0
THROTTLE_MAX_DELAY_SECONDS = 10.0


@dataclass(frozen=True)
class CrawlProgress:
    """Point-in-time Scrapy progress counts, not a resumable checkpoint."""

    status: str
    termination_reason: Optional[str]
    scheduled_pages: int
    visited_urls: int
    successful_urls: int
    failed_urls: int
    discovered_urls: int
    failure_types: Dict[str, int]


def crawl_with_scrapy(
    seeds: Iterable[str],
    policy: CrawlPolicy,
    link_discoverer: LinkDiscoverer[str],
    render_javascript: bool = False,
    render_wait_for: Optional[str] = None,
    click_selectors: Optional[Iterable[str]] = None,
    load_more_selectors: Optional[Iterable[str]] = None,
    max_load_more_clicks: int = 20,
    index_click_workers: int = 1,
    progress_callback: Optional[Callable[[CrawlProgress], None]] = None,
    progress_interval: float = 600.0,
) -> CrawlResult:
    """Run one standalone Scrapy crawl and return its traversal metadata.

    Set ``render_javascript`` to opt eligible page requests into Playwright.
    ``render_wait_for`` optionally waits for a CSS selector before extracting
    links. ``load_more_selectors`` are clicked before ``click_selectors``;
    each is limited by ``max_load_more_clicks`` per page. Browser rendering
    requires the optional ``playwright`` extra.

    If provided, ``progress_callback`` receives periodic progress summaries and
    a final summary when the spider closes. It runs on Scrapy's reactor thread
    and should return promptly.

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
    if (
        isinstance(index_click_workers, bool)
        or not isinstance(index_click_workers, int)
        or index_click_workers < 1
    ):
        raise ValueError("index_click_workers must be a positive integer")
    if index_click_workers > 1 and not render_javascript:
        raise ValueError("index_click_workers requires render_javascript=True")
    if progress_callback is not None and not callable(progress_callback):
        raise ValueError("progress_callback must be callable")
    if (
        isinstance(progress_interval, bool)
        or not isinstance(progress_interval, (int, float))
        or not math.isfinite(progress_interval)
        or progress_interval <= 0
    ):
        raise ValueError("progress_interval must be a finite positive number")
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
            render_wait_for,
            index_click_workers,
            card_indices,
        ):
            from playwright.async_api import Error as PlaywrightError
            from playwright.async_api import TimeoutError as PlaywrightTimeoutError

            discovered = []
            out_of_scope = []
            click_errors = []
            selector_counts = []
            load_more_click_counts = []
            timing_totals = {}
            worker_tasks = []
            load_more_click_totals = {
                selector: 0 for selector in load_more_selectors
            }
            source_url = _normalize_url(page_url)
            navigation_attempts = 0

            main_frame_navigation = asyncio.Event()

            def mark_main_frame_navigation(frame):
                if frame == page.main_frame:
                    main_frame_navigation.set()

            async def measure(phase, awaitable):
                started = time.perf_counter()
                try:
                    return await awaitable
                finally:
                    timing_totals[phase] = (
                        timing_totals.get(phase, 0.0)
                        + time.perf_counter()
                        - started
                    )

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
                    await route.fulfill(
                        status=200,
                        content_type="text/html",
                        body="",
                    )
                    return
                await route.continue_()

            async def wait_for_click_navigation(previous_url, previous_attempts):
                deadline = (
                    asyncio.get_running_loop().time()
                    + CLICK_NAVIGATION_TIMEOUT_MILLISECONDS / 1000
                )
                while (
                    page.url == previous_url
                    and navigation_attempts == previous_attempts
                    and asyncio.get_running_loop().time() < deadline
                ):
                    await page.wait_for_timeout(50)

            async def restore_source_page():
                try:
                    current_url = _normalize_url(page.url)
                except ValueError:
                    current_url = None
                if current_url == source_url:
                    await measure(
                        "page_restore_same_url_settle_seconds",
                        page.wait_for_timeout(CLICK_SETTLE_MILLISECONDS),
                    )
                    return

                try:
                    return await measure(
                        "page_restore_navigation_seconds",
                        page.goto(
                            source_url,
                            wait_until="domcontentloaded",
                            timeout=REQUEST_TIMEOUT_SECONDS * 1000,
                        ),
                    )
                except PlaywrightError as exc:
                    if "interrupted by another navigation" not in str(exc):
                        raise
                    try:
                        await measure(
                            "page_restore_inflight_wait_seconds",
                            page.wait_for_load_state(
                                "domcontentloaded",
                                timeout=CLICK_ABORT_NAVIGATION_TIMEOUT_MILLISECONDS,
                            ),
                        )
                    except PlaywrightTimeoutError:
                        pass
                    try:
                        current_url = _normalize_url(page.url)
                    except ValueError:
                        current_url = None
                    if current_url == source_url:
                        return
                    await measure(
                        "page_restore_retry_settle_seconds",
                        page.wait_for_timeout(CLICK_SETTLE_MILLISECONDS),
                    )
                    return await measure(
                        "page_restore_retry_navigation_seconds",
                        page.goto(
                            source_url,
                            wait_until="domcontentloaded",
                            timeout=REQUEST_TIMEOUT_SECONDS * 1000,
                        ),
                    )

            async def run_index_worker(worker_number, worker_card_indices):
                worker_page = None
                try:
                    worker_page = await page.context.new_page()
                    await measure(
                        "index_worker_navigation_seconds",
                        worker_page.goto(
                            source_url,
                            wait_until="domcontentloaded",
                            timeout=REQUEST_TIMEOUT_SECONDS * 1000,
                        ),
                    )
                    selectors_to_wait = (
                        (render_wait_for,)
                        if render_wait_for is not None
                        else load_more_selectors or selectors
                    )
                    if selectors_to_wait:
                        await measure(
                            "index_worker_render_wait_seconds",
                            worker_page.locator(
                                selectors_to_wait[0]
                            ).first.wait_for(
                                state="visible",
                                timeout=REQUEST_TIMEOUT_SECONDS * 1000,
                            ),
                        )
                    return await discover_clicked_urls(
                        worker_page,
                        selectors,
                        allowed_domains,
                        allowed_url_prefixes,
                        page_url,
                        load_more_selectors,
                        max_load_more_clicks,
                        render_wait_for,
                        1,
                        worker_card_indices,
                    )
                except PlaywrightError as exc:
                    return {
                        "urls": (),
                        "out_of_scope_urls": (),
                        "page_title": None,
                        "errors": (
                            "index click worker {}: {}".format(worker_number, exc),
                        ),
                        "selector_counts": (),
                        "load_more_click_counts": (),
                        "timings": (),
                    }
                finally:
                    if worker_page is not None:
                        await worker_page.close()

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
                            await measure(
                                "load_more_click_seconds",
                                locator.first.click(
                                    timeout=CLICK_TIMEOUT_MILLISECONDS
                                ),
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
                            await measure(
                                "load_more_content_wait_seconds",
                                page.wait_for_function(
                                    """({previousCount, selector}) =>
                                        document.querySelectorAll('.child-card').length > previousCount
                                        || !document.querySelector(selector)
                                    """,
                                    arg={
                                        "previousCount": previous_card_count,
                                        "selector": selector,
                                    },
                                    timeout=CLICK_TIMEOUT_MILLISECONDS,
                                ),
                            )
                        except PlaywrightTimeoutError:
                            break
                        await measure(
                            "load_more_settle_seconds",
                            page.wait_for_timeout(CLICK_SETTLE_MILLISECONDS),
                        )

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
                            await measure(
                                "load_more_click_seconds",
                                locator.first.click(
                                    timeout=CLICK_TIMEOUT_MILLISECONDS
                                ),
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
                            await measure(
                                "load_more_content_wait_seconds",
                                page.wait_for_function(
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
                                ),
                            )
                        except PlaywrightTimeoutError:
                            made_progress = False

                        await measure(
                            "load_more_settle_seconds",
                            page.wait_for_timeout(CLICK_SETTLE_MILLISECONDS),
                        )

                        try:
                            current_url = _normalize_url(page.url)
                        except ValueError:
                            current_url = None
                        if current_url is None:
                            await restore_source_page()
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
                                await measure(
                                    "page_restore_navigation_seconds",
                                    page.go_back(
                                        wait_until="domcontentloaded",
                                        timeout=CLICK_TIMEOUT_MILLISECONDS,
                                    ),
                                )
                            except PlaywrightError:
                                await restore_source_page()
                            break
                        if not made_progress:
                            break
                selector_card_counts = {}
                for selector in selectors:
                    locator = page.locator(selector)
                    try:
                        await locator.first.wait_for(
                            state="visible",
                            timeout=CLICK_TIMEOUT_MILLISECONDS,
                        )
                    except PlaywrightTimeoutError:
                        selector_counts.append((selector, 0))
                        selector_card_counts[selector] = 0
                        continue
                    try:
                        count = await locator.count()
                    except PlaywrightError as exc:
                        click_errors.append("{}: {}".format(selector, exc))
                        selector_counts.append((selector, 0))
                        selector_card_counts[selector] = 0
                        continue
                    selector_counts.append((selector, count))
                    selector_card_counts[selector] = count

                if index_click_workers > 1 and card_indices is None:
                    for worker_number in range(1, index_click_workers):
                        worker_card_indices = {
                            selector: tuple(
                                index
                                for index in range(count)
                                if index % index_click_workers == worker_number
                            )
                            for selector, count in selector_card_counts.items()
                        }
                        worker_tasks.append(
                            asyncio.create_task(
                                run_index_worker(
                                    worker_number,
                                    worker_card_indices,
                                )
                            )
                        )

                for selector in selectors:
                    locator = page.locator(selector)
                    count = selector_card_counts[selector]
                    if card_indices is not None:
                        indices_to_click = card_indices.get(selector, ())
                    elif index_click_workers > 1:
                        indices_to_click = tuple(
                            index
                            for index in range(count)
                            if index % index_click_workers == 0
                        )
                    else:
                        indices_to_click = range(count)
                    for index in indices_to_click:
                        discovered_before_click = len(discovered)
                        previous_url = page.url
                        previous_navigation_attempts = navigation_attempts
                        main_frame_navigation.clear()
                        try:
                            await locator.nth(index).wait_for(
                                state="visible",
                                timeout=LOAD_MORE_WAIT_MILLISECONDS,
                            )
                        except PlaywrightTimeoutError:
                            await measure(
                                "loaded_cards_restore_seconds",
                                restore_loaded_cards(count),
                            )
                        try:
                            await measure(
                                "card_click_seconds",
                                locator.nth(index).click(
                                    timeout=CLICK_TIMEOUT_MILLISECONDS,
                                    no_wait_after=True,
                                ),
                            )
                        except PlaywrightError as exc:
                            if len(discovered) == discovered_before_click:
                                click_errors.append(
                                    "{}[{}]: {}".format(selector, index, exc)
                                )
                        else:
                            await measure(
                                "card_navigation_detection_seconds",
                                wait_for_click_navigation(
                                    previous_url, previous_navigation_attempts
                                ),
                            )
                            await measure(
                                "card_settle_seconds",
                                page.wait_for_timeout(CLICK_SETTLE_MILLISECONDS),
                            )

                        if navigation_attempts != previous_navigation_attempts:
                            if not main_frame_navigation.is_set():
                                try:
                                    await measure(
                                        "card_navigation_event_wait_seconds",
                                        asyncio.wait_for(
                                            main_frame_navigation.wait(),
                                            timeout=(
                                                CLICK_ABORT_NAVIGATION_TIMEOUT_MILLISECONDS
                                                / 1000
                                            ),
                                        ),
                                    )
                                except asyncio.TimeoutError:
                                    pass
                            await restore_source_page()
                            await measure(
                                "loaded_cards_restore_seconds",
                                restore_loaded_cards(count),
                            )
                            continue

                        try:
                            current_url = _normalize_url(page.url)
                        except ValueError:
                            current_url = None

                        if current_url is None:
                            await restore_source_page()
                            await measure(
                                "loaded_cards_restore_seconds",
                                restore_loaded_cards(count),
                            )
                        elif current_url != source_url:
                            if _is_url_in_scope(
                                current_url,
                                allowed_domains,
                                allowed_url_prefixes,
                            ):
                                discovered.append(current_url)
                            try:
                                await measure(
                                    "page_restore_navigation_seconds",
                                    page.go_back(
                                        wait_until="domcontentloaded",
                                        timeout=CLICK_TIMEOUT_MILLISECONDS,
                                    ),
                                )
                            except PlaywrightError:
                                await restore_source_page()
                            await measure(
                                "loaded_cards_restore_seconds",
                                restore_loaded_cards(count),
                            )
                if worker_tasks:
                    for worker_result in await asyncio.gather(*worker_tasks):
                        discovered.extend(worker_result.get("urls", ()))
                        out_of_scope.extend(
                            worker_result.get("out_of_scope_urls", ())
                        )
                        click_errors.extend(worker_result.get("errors", ()))
                        for selector, clicks in worker_result.get(
                            "load_more_click_counts", ()
                        ):
                            load_more_click_totals[selector] = (
                                load_more_click_totals.get(selector, 0) + clicks
                            )
                        for phase, seconds in worker_result.get("timings", ()):
                            timing_totals[phase] = (
                                timing_totals.get(phase, 0.0) + seconds
                            )
            finally:
                for worker_task in worker_tasks:
                    if not worker_task.done():
                        worker_task.cancel()
                if worker_tasks:
                    await asyncio.gather(*worker_tasks, return_exceptions=True)
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
                "page_title": await page.title(),
                "errors": tuple(click_errors),
                "selector_counts": tuple(selector_counts),
                "load_more_click_counts": tuple(load_more_click_counts),
                "timings": tuple(timing_totals.items()),
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
            self.progress_call = None

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
            if progress_callback is not None:
                self.progress_call = reactor.callLater(
                    progress_interval, self.report_progress, spider
                )

        def report_progress(self, spider):
            from twisted.internet import reactor

            self.progress_call = reactor.callLater(
                progress_interval, self.report_progress, spider
            )
            progress_callback(spider.progress("running"))

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
            if self.progress_call is not None and self.progress_call.active():
                self.progress_call.cancel()
            rejected_for_page_limit = spider.crawler.stats.get_value(
                "crawler/pages_rejected_limit", 0
            )
            if rejected_for_page_limit:
                spider._crawl_termination_reason = "page_limit"
            elif reason == "time_limit":
                spider._crawl_termination_reason = "time_limit"
            elif reason == "finished":
                spider._crawl_termination_reason = "frontier_exhausted"
            else:
                spider._crawl_termination_reason = "stopped:{}".format(reason)
            if progress_callback is not None:
                progress_callback(spider.progress("completed"))

    class PolicySpider(Spider):
        name = "bounded_policy_crawl"
        custom_settings = {
            "ROBOTSTXT_OBEY": True,
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
            index_click_workers: int,
            **kwargs,
        ):
            super().__init__(**kwargs)
            self.policy = policy
            self.seeds = seeds
            self._scheduled_urls: Set[str] = set(seeds)
            self.link_discoverer = link_discoverer
            self.render_javascript = render_javascript
            self.render_wait_for = render_wait_for
            self.click_selectors = click_selectors
            self.load_more_selectors = load_more_selectors
            self.max_load_more_clicks = max_load_more_clicks
            self.index_click_workers = index_click_workers
            self._crawl_termination_reason: Optional[str] = None
            self._visited: List[str] = []
            self._visited_set: Set[str] = set()
            self._successful: List[str] = []
            self._successful_set: Set[str] = set()
            self._page_titles: List[Tuple[str, Optional[str]]] = []
            self._page_timings: List[Tuple[str, str, float]] = []
            self._failures: List[CrawlFailure] = []
            self._discovered: List[str] = []
            self._discovered_set: Set[str] = set()
            self._out_of_scope_urls: List[str] = []
            self._out_of_scope_url_set: Set[str] = set()
            self._edges: List[Tuple[str, str]] = []
            self._edge_set: Set[Tuple[str, str]] = set()
            self._link_references: List[CrawlLinkReference] = []
            self._link_reference_set = set()
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
                if destination is not None:
                    self._record_reference(
                        page_url,
                        destination,
                        "redirect",
                        "location",
                    )
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
                self._record_reference(
                    page_url,
                    final_url,
                    "redirect",
                    "location",
                )
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
            download_latency = response.meta.get("download_latency")
            if isinstance(download_latency, (int, float)):
                self._page_timings.append(
                    (page_url, "request_total_seconds", float(download_latency))
                )
            page_title = response.css("title::text").get()
            if isinstance(page_title, str):
                page_title = " ".join(page_title.split()) or None

            click_result = None
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
                    rendered_title = click_result.get("page_title")
                    if isinstance(rendered_title, str):
                        page_title = " ".join(rendered_title.split()) or None
                    self._page_timings.extend(
                        (page_url, phase, seconds)
                        for phase, seconds in click_result.get("timings", ())
                    )
            self._page_titles.append((page_url, page_title))

            depth = response.meta.get("_crawl_depth", 0)
            try:
                links = self.link_discoverer.discover_links(response.text)
                if isinstance(links, str):
                    raise TypeError(
                        "link discoverer must return an iterable of strings "
                        "or LinkReference values"
                    )
                candidates = list(links)
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
                if isinstance(click_result, dict):
                    candidates.extend(
                        LinkReference(
                            url=target,
                            category="javascript_navigation",
                            follow=True,
                        )
                        for target in click_result.get("urls", ())
                    )
                    for target in click_result.get("out_of_scope_urls", ()):
                        self._record_reference(
                            final_url,
                            target,
                            "javascript_navigation",
                            None,
                            follow=True,
                        )
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
            for candidate in candidates:
                if isinstance(candidate, LinkReference):
                    reference = candidate
                elif isinstance(candidate, str):
                    reference = LinkReference(candidate)
                else:
                    self._failures.append(
                        CrawlFailure(
                            url=page_url,
                            stage="discover",
                            error_type="TypeError",
                            message=(
                                "link discoverer must return strings or "
                                "LinkReference values"
                            ),
                        )
                    )
                    continue
                reference_base = final_url
                if reference.base_url is not None:
                    try:
                        reference_base = _normalize_url(
                            reference.base_url,
                            base_url=final_url,
                        )
                    except ValueError:
                        reference_base = final_url
                try:
                    target = _normalize_url(
                        reference.url,
                        base_url=reference_base,
                    )
                except ValueError:
                    try:
                        parsed_target = urlsplit(reference.url)
                    except ValueError:
                        continue
                    if (
                        parsed_target.scheme
                        and parsed_target.scheme.lower() not in ("http", "https")
                        and not reference.url.lower().startswith("data:")
                    ):
                        self._record_reference(
                            final_url,
                            reference.url,
                            reference.category,
                            reference.attribute,
                            scope="non_http",
                            follow=reference.follow,
                        )
                    continue
                is_in_scope = _is_url_in_scope(
                    target,
                    self.policy.allowed_domains,
                    self.policy.allowed_url_prefixes,
                )
                self._record_reference(
                    final_url,
                    target,
                    reference.category,
                    reference.attribute,
                    scope="in_scope" if is_in_scope else "out_of_scope",
                    follow=reference.follow,
                )
                if not is_in_scope or not reference.follow:
                    continue

                edge = (final_url, target)
                if edge not in self._edge_set:
                    self._edge_set.add(edge)
                    self._edges.append(edge)
                if target not in seen_seeds:
                    self._record(
                        self._discovered, self._discovered_set, target
                    )
                if (
                    depth < self.policy.max_depth
                    and target not in self._scheduled_urls
                ):
                    self._scheduled_urls.add(target)
                    requests.append(self._request(target, depth + 1))

            return requests

        def errback(self, failure):
            request = failure.request
            page_url = request.meta.get("_crawl_page_url", request.url)
            self._record(self._visited, self._visited_set, page_url)
            rejection = request.meta.get("_crawl_scope_rejection")

            if rejection is not None:
                self._record_reference(
                    page_url,
                    rejection["url"],
                    "redirect",
                    "location",
                )
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
                destination = self._redirect_destination(response)
                if destination is not None:
                    self._record_reference(
                        page_url,
                        destination,
                        "redirect",
                        "location",
                    )
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
                page_titles=tuple(self._page_titles),
                termination_reason=self._crawl_termination_reason,
                page_timings=tuple(self._page_timings),
                link_references=tuple(self._link_references),
            )

        def progress(self, status: str) -> CrawlProgress:
            return CrawlProgress(
                status=status,
                termination_reason=self._crawl_termination_reason,
                scheduled_pages=self.crawler.stats.get_value(
                    "crawler/scheduled_pages", 0
                ),
                visited_urls=len(self._visited),
                successful_urls=len(self._successful),
                failed_urls=len(self._failures),
                discovered_urls=len(self._discovered),
                failure_types=dict(
                    Counter(failure.error_type for failure in self._failures)
                ),
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
                page_methods.append(
                    PageMethod(
                        discover_clicked_urls,
                        self.click_selectors,
                        self.policy.allowed_domains,
                        self.policy.allowed_url_prefixes,
                        url,
                        self.load_more_selectors,
                        self.max_load_more_clicks,
                        self.render_wait_for,
                        (
                            self.index_click_workers
                            if url in self.seeds
                            else 1
                        ),
                        None,
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

        def _record_reference(
            self,
            source_url: str,
            target_url: str,
            category: str,
            attribute: Optional[str],
            scope: Optional[str] = None,
            follow: bool = False,
        ) -> None:
            if scope is None:
                try:
                    normalized_target = _normalize_url(
                        target_url,
                        base_url=source_url,
                    )
                except ValueError:
                    scope = "non_http"
                    normalized_target = target_url
                else:
                    scope = (
                        "in_scope"
                        if _is_url_in_scope(
                            normalized_target,
                            self.policy.allowed_domains,
                            self.policy.allowed_url_prefixes,
                        )
                        else "out_of_scope"
                    )
            else:
                try:
                    normalized_target = _normalize_url(
                        target_url,
                        base_url=source_url,
                    )
                except ValueError:
                    normalized_target = target_url

            reference = CrawlLinkReference(
                source_url=source_url,
                target_url=normalized_target,
                category=category,
                attribute=attribute,
                scope=scope,
                follow=follow,
            )
            key = (
                reference.source_url,
                reference.target_url,
                reference.category,
                reference.attribute,
                reference.scope,
                reference.follow,
            )
            if key not in self._link_reference_set:
                self._link_reference_set.add(key)
                self._link_references.append(reference)
            if scope == "out_of_scope":
                self._record(
                    self._out_of_scope_urls,
                    self._out_of_scope_url_set,
                    normalized_target,
                )

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
                "PLAYWRIGHT_MAX_PAGES_PER_CONTEXT": max(
                    2, index_click_workers
                ),
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
        index_click_workers=index_click_workers,
    )
    process.start()

    if crawler.spider is None:
        raise RuntimeError("Scrapy did not create the policy spider")
    return crawler.spider.result
