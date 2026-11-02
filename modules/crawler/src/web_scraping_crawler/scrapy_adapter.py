"""Optional Scrapy HTTP adapter for the crawler core."""

from __future__ import annotations

import hashlib
from collections.abc import Iterable
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
RETRY_COUNT = 2
TOTAL_CONCURRENCY = 4
PER_DOMAIN_CONCURRENCY = 2
THROTTLE_START_DELAY_SECONDS = 1.0
THROTTLE_MAX_DELAY_SECONDS = 10.0


def crawl_with_scrapy(
    seeds: Iterable[str],
    policy: CrawlPolicy,
    link_discoverer: LinkDiscoverer[str],
) -> CrawlResult:
    """Run one standalone Scrapy crawl and return its traversal metadata.

    This helper starts Scrapy's Twisted reactor and is intended for a normal
    synchronous script. The reactor cannot be restarted, so call this helper
    at most once in a Python process. Use a runner-based integration when
    embedding Scrapy in an application that already owns an event loop.
    """
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

    normalized_seeds = []
    seen_seeds: Set[str] = set()
    for seed in seeds:
        normalized = _normalize_url(seed)
        if not _is_url_in_scope(normalized, policy.allowed_domains):
            raise ValueError("seed URL is outside the configured allowed_domains")
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

            if not _is_url_in_scope(normalized, spider.policy.allowed_domains):
                request.meta["_crawl_scope_rejection"] = {
                    "url": normalized,
                    "message": "redirect destination is outside allowed_domains",
                }
                raise IgnoreRequest("redirect destination is outside allowed_domains")

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
            if spider.crawler.engine is not None:
                spider.crawler.engine.close_spider(spider, "time_limit")

        def spider_closed(self, spider, reason):
            if self.call is not None and self.call.active():
                self.call.cancel()

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
            **kwargs,
        ):
            super().__init__(**kwargs)
            self.policy = policy
            self.seeds = seeds
            self.link_discoverer = link_discoverer
            self._visited: List[str] = []
            self._visited_set: Set[str] = set()
            self._successful: List[str] = []
            self._successful_set: Set[str] = set()
            self._failures: List[CrawlFailure] = []
            self._discovered: List[str] = []
            self._discovered_set: Set[str] = set()
            self._edges: List[Tuple[str, str]] = []
            self._edge_set: Set[Tuple[str, str]] = set()

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

            if not _is_url_in_scope(final_url, self.policy.allowed_domains):
                self._failures.append(
                    CrawlFailure(
                        url=page_url,
                        stage="redirect",
                        error_type="OutOfScopeRedirect",
                        message="redirect destination is outside allowed_domains",
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

            requests = []
            for link in candidates:
                try:
                    target = _normalize_url(link, base_url=final_url)
                except ValueError:
                    continue
                if not _is_url_in_scope(target, self.policy.allowed_domains):
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
            )

        def _request(self, url: str, depth: int):
            from scrapy import Request

            return Request(
                url=url,
                callback=self.parse,
                errback=self.errback,
                meta={
                    "_crawl_page_url": url,
                    "_crawl_depth": depth,
                },
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

    process = CrawlerProcess(settings=PolicySpider.custom_settings)
    crawler = process.create_crawler(PolicySpider)
    process.crawl(
        crawler,
        policy=policy,
        seeds=tuple(normalized_seeds),
        link_discoverer=link_discoverer,
    )
    process.start()

    if crawler.spider is None:
        raise RuntimeError("Scrapy did not create the policy spider")
    return crawler.spider.result
