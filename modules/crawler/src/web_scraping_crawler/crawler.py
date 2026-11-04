"""Framework-independent crawl coordination."""

from __future__ import annotations

import ipaddress
import math
import re
import time
from collections import deque
from dataclasses import dataclass
from numbers import Real
from typing import (
    Deque,
    Generic,
    Iterable,
    Literal,
    Optional,
    Protocol,
    Set,
    Tuple,
    TypeVar,
    Union,
)
from urllib.parse import urljoin, urlsplit, urlunsplit

PageT = TypeVar("PageT")
LinkEdge = Tuple[str, str]
FailureStage = Literal["retrieve", "redirect", "discover"]
LinkScope = Literal["in_scope", "out_of_scope", "non_http"]


@dataclass(frozen=True)
class CrawlPolicy:
    """Explicit crawl scope and finite traversal limits."""

    allowed_domains: Tuple[str, ...]
    max_pages: int
    max_depth: int
    max_elapsed_time: float
    allowed_url_prefixes: Tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if isinstance(self.allowed_domains, str):
            raise ValueError("allowed_domains must be a non-empty sequence of hosts")
        try:
            domains = tuple(
                _normalize_domain(domain) for domain in self.allowed_domains
            )
        except TypeError as exc:
            raise ValueError(
                "allowed_domains must be a non-empty sequence of hosts"
            ) from exc
        if not domains:
            raise ValueError("allowed_domains must contain at least one host")
        if len(set(domains)) != len(domains):
            domains = tuple(dict.fromkeys(domains))
        object.__setattr__(self, "allowed_domains", domains)

        if isinstance(self.allowed_url_prefixes, str):
            raise ValueError("allowed_url_prefixes must be a sequence of URL prefixes")
        try:
            prefixes = tuple(
                _normalize_url_prefix(prefix) for prefix in self.allowed_url_prefixes
            )
        except TypeError as exc:
            raise ValueError(
                "allowed_url_prefixes must be a sequence of URL prefixes"
            ) from exc
        if any(urlsplit(prefix).hostname not in domains for prefix in prefixes):
            raise ValueError(
                "allowed URL prefixes must use a host in allowed_domains"
            )
        object.__setattr__(
            self, "allowed_url_prefixes", tuple(dict.fromkeys(prefixes))
        )

        if isinstance(self.max_pages, bool) or not isinstance(self.max_pages, int):
            raise ValueError("max_pages must be a positive integer")
        if self.max_pages < 1:
            raise ValueError("max_pages must be a positive integer")
        if isinstance(self.max_depth, bool) or not isinstance(self.max_depth, int):
            raise ValueError("max_depth must be a non-negative integer")
        if self.max_depth < 0:
            raise ValueError("max_depth must be a non-negative integer")
        if isinstance(self.max_elapsed_time, bool) or not isinstance(
            self.max_elapsed_time, Real
        ):
            raise ValueError("max_elapsed_time must be a finite positive number")
        try:
            elapsed = float(self.max_elapsed_time)
        except (OverflowError, TypeError, ValueError) as exc:
            raise ValueError(
                "max_elapsed_time must be a finite positive number"
            ) from exc
        if not math.isfinite(elapsed) or elapsed <= 0:
            raise ValueError("max_elapsed_time must be a finite positive number")
        object.__setattr__(self, "max_elapsed_time", elapsed)


@dataclass(frozen=True)
class RetrievalResult(Generic[PageT]):
    """A retrieved page payload and its optional final URL after redirects."""

    content: PageT
    final_url: Optional[str] = None


class Retriever(Protocol[PageT]):
    """Retrieves one URL; implementations are responsible for request timeouts."""

    def retrieve(self, url: str) -> RetrievalResult[PageT]:
        """Return the retrieved payload and optional redirect destination."""


class LinkDiscoverer(Protocol[PageT]):
    """Extracts candidate links from a retrieved payload."""

    def discover_links(
        self,
        content: PageT,
    ) -> Iterable[Union[str, "LinkReference"]]:
        """Return URL strings or categorized LinkReference values."""


@dataclass(frozen=True)
class LinkReference:
    """A URL reference found in a page, with its source element classification."""

    url: str
    category: str = "hyperlink"
    attribute: Optional[str] = None
    follow: bool = True
    base_url: Optional[str] = None


@dataclass(frozen=True)
class CrawlLinkReference:
    """A normalized page-to-URL reference and its crawl-scope classification."""

    source_url: str
    target_url: str
    category: str
    attribute: Optional[str]
    scope: LinkScope
    follow: bool


@dataclass(frozen=True)
class CrawlFailure:
    """A structured failure associated with an attempted URL."""

    url: str
    stage: FailureStage
    error_type: str
    message: str
    redirect_url: Optional[str] = None


@dataclass(frozen=True)
class CrawlResult:
    """Traversal metadata and available page titles; response bodies are not retained."""

    visited_urls: Tuple[str, ...]
    successful_urls: Tuple[str, ...]
    failed_urls: Tuple[CrawlFailure, ...]
    discovered_urls: Tuple[str, ...]
    link_edges: Tuple[LinkEdge, ...]
    click_selector_counts: Tuple[Tuple[str, str, int], ...] = ()
    load_more_click_counts: Tuple[Tuple[str, str, int], ...] = ()
    out_of_scope_urls: Tuple[str, ...] = ()
    page_titles: Tuple[Tuple[str, Optional[str]], ...] = ()
    termination_reason: Optional[str] = None
    page_timings: Tuple[Tuple[str, str, float], ...] = ()
    link_references: Tuple[CrawlLinkReference, ...] = ()

    @property
    def edge_count(self) -> int:
        """Return the number of unique directed links recorded."""
        return len(self.link_edges)


class Crawler(Generic[PageT]):
    """Coordinate bounded traversal through injected collaborators."""

    def __init__(self, policy: CrawlPolicy) -> None:
        self.policy = policy

    def crawl(
        self,
        seeds: Iterable[str],
        retriever: Retriever[PageT],
        link_discoverer: LinkDiscoverer[PageT],
    ) -> CrawlResult:
        """Traverse in-scope URLs in FIFO order and return metadata only."""
        seed_urls = []
        seed_set: Set[str] = set()
        for seed in seeds:
            normalized = _normalize_url(seed)
            if not self._is_in_scope(normalized):
                raise ValueError("seed URL is outside the configured crawl scope")
            if normalized not in seed_set:
                seed_set.add(normalized)
                seed_urls.append(normalized)

        frontier: Deque[Tuple[str, int]] = deque(
            (url, 0) for url in seed_urls
        )
        scheduled: Set[str] = set(seed_urls)
        attempted: Set[str] = set()
        successful_urls = []
        visited_urls = []
        failed_urls = []
        discovered_urls = []
        discovered_set: Set[str] = set()
        link_edges = []
        edge_set: Set[LinkEdge] = set()
        link_references = []
        link_reference_set = set()
        out_of_scope_urls = []
        out_of_scope_set: Set[str] = set()
        started = time.monotonic()
        stopped_for_time = False

        def record_reference(
            source_url: str,
            target_url: str,
            category: str,
            attribute: Optional[str],
            scope: LinkScope,
            follow: bool,
        ) -> None:
            record = CrawlLinkReference(
                source_url=source_url,
                target_url=target_url,
                category=category,
                attribute=attribute,
                scope=scope,
                follow=follow,
            )
            key = (
                record.source_url,
                record.target_url,
                record.category,
                record.attribute,
                record.scope,
                record.follow,
            )
            if key not in link_reference_set:
                link_reference_set.add(key)
                link_references.append(record)
            if scope == "out_of_scope" and target_url not in out_of_scope_set:
                out_of_scope_set.add(target_url)
                out_of_scope_urls.append(target_url)

        while frontier and len(attempted) < self.policy.max_pages:
            if self._time_limit_reached(started):
                stopped_for_time = True
                break

            url, depth = frontier.popleft()
            attempted.add(url)
            visited_urls.append(url)
            try:
                page = retriever.retrieve(url)
            except Exception as exc:
                failed_urls.append(_failure(url, "retrieve", exc))
                continue
            if not isinstance(page, RetrievalResult):
                failed_urls.append(
                    _failure(
                        url,
                        "retrieve",
                        TypeError("retriever must return a RetrievalResult"),
                    )
                )
                continue

            final_url = url
            if page.final_url is not None:
                try:
                    final_url = _normalize_url(page.final_url, base_url=url)
                except ValueError as exc:
                    failed_urls.append(_failure(url, "redirect", exc))
                    continue
                if not self._is_in_scope(final_url):
                    record_reference(
                        url,
                        final_url,
                        "redirect",
                        "location",
                        "out_of_scope",
                        False,
                    )
                    failed_urls.append(
                        CrawlFailure(
                            url=url,
                            stage="redirect",
                            error_type="OutOfScopeRedirect",
                            message="redirect destination is outside the configured crawl scope",
                            redirect_url=final_url,
                        )
                    )
                    continue

            successful_urls.append(url)
            if self._time_limit_reached(started):
                stopped_for_time = True
                continue
            try:
                links = link_discoverer.discover_links(page.content)
                if isinstance(links, str):
                    raise TypeError(
                        "link discoverer must return an iterable of strings "
                        "or LinkReference values"
                    )
                for link in links:
                    if self._time_limit_reached(started):
                        stopped_for_time = True
                        break
                    if isinstance(link, LinkReference):
                        reference = link
                    elif isinstance(link, str):
                        reference = LinkReference(link)
                    else:
                        raise TypeError(
                            "link discoverer must return strings or LinkReference values"
                        )

                    base_url = final_url
                    if reference.base_url is not None:
                        try:
                            base_url = _normalize_url(
                                reference.base_url,
                                base_url=final_url,
                            )
                        except ValueError:
                            base_url = final_url
                    try:
                        target = _normalize_url(
                            reference.url,
                            base_url=base_url,
                        )
                    except ValueError:
                        try:
                            parsed = urlsplit(reference.url)
                        except ValueError:
                            continue
                        if (
                            parsed.scheme
                            and parsed.scheme.lower() not in ("http", "https")
                            and not reference.url.lower().startswith("data:")
                        ):
                            target = reference.url
                            scope: LinkScope = "non_http"
                        else:
                            continue
                    else:
                        scope = (
                            "in_scope"
                            if self._is_in_scope(target)
                            else "out_of_scope"
                        )

                    record_reference(
                        final_url,
                        target,
                        reference.category,
                        reference.attribute,
                        scope,
                        reference.follow,
                    )
                    if scope == "out_of_scope":
                        continue
                    if scope != "in_scope" or not reference.follow:
                        continue

                    edge = (final_url, target)
                    if edge not in edge_set:
                        edge_set.add(edge)
                        link_edges.append(edge)
                    if target not in seed_set and target not in discovered_set:
                        discovered_set.add(target)
                        discovered_urls.append(target)
                    if (
                        depth < self.policy.max_depth
                        and target not in scheduled
                        and target not in attempted
                    ):
                        scheduled.add(target)
                        frontier.append((target, depth + 1))
            except Exception as exc:
                failed_urls.append(_failure(url, "discover", exc))

        if stopped_for_time:
            termination_reason = "time_limit"
        elif frontier and len(attempted) >= self.policy.max_pages:
            termination_reason = "page_limit"
        else:
            termination_reason = "frontier_exhausted"

        return CrawlResult(
            visited_urls=tuple(visited_urls),
            successful_urls=tuple(successful_urls),
            failed_urls=tuple(failed_urls),
            discovered_urls=tuple(discovered_urls),
            link_edges=tuple(link_edges),
            termination_reason=termination_reason,
            out_of_scope_urls=tuple(out_of_scope_urls),
            link_references=tuple(link_references),
        )

    def _time_limit_reached(self, started: float) -> bool:
        return time.monotonic() - started >= self.policy.max_elapsed_time

    def _is_in_scope(self, url: str) -> bool:
        return _is_url_in_scope(
            url,
            self.policy.allowed_domains,
            self.policy.allowed_url_prefixes,
        )


def _failure(url: str, stage: FailureStage, exc: Exception) -> CrawlFailure:
    return CrawlFailure(
        url=url,
        stage=stage,
        error_type=type(exc).__name__,
        message=str(exc),
    )


def _normalize_domain(domain: str) -> str:
    if not isinstance(domain, str) or not domain or domain != domain.strip():
        raise ValueError("allowed domains must be non-empty host names")
    if any(character in domain for character in "/?#@") or domain.endswith(":"):
        raise ValueError("allowed domains must be host names without URL components")
    try:
        parsed = urlsplit("//" + domain)
        port = parsed.port
    except ValueError as exc:
        raise ValueError("allowed domain is not a valid host name") from exc
    if (
        parsed.hostname is None
        or parsed.username is not None
        or parsed.password is not None
        or port is not None
        or parsed.netloc != domain
        or parsed.path
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError("allowed domains must be host names without ports")
    return _normalize_host(parsed.hostname)


def _normalize_host(host: str) -> str:
    try:
        return ipaddress.IPv6Address(host).compressed.lower()
    except ipaddress.AddressValueError:
        try:
            normalized = host.encode("idna").decode("ascii").lower()
        except UnicodeError as exc:
            raise ValueError("URL contains an invalid host name") from exc
        if (
            len(normalized) > 253
            or re.fullmatch(
                r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?"
                r"(?:\.[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?)*",
                normalized,
            )
            is None
        ):
            raise ValueError("URL contains an invalid host name")
        return normalized


def _normalize_url(url: str, base_url: Optional[str] = None) -> str:
    if not isinstance(url, str) or not url or url != url.strip():
        raise ValueError("URL must be a non-empty string without surrounding whitespace")
    resolved = urljoin(base_url, url) if base_url is not None else url
    try:
        parsed = urlsplit(resolved)
        port = parsed.port
    except ValueError as exc:
        raise ValueError("URL is malformed") from exc
    scheme = parsed.scheme.lower()
    if scheme not in ("http", "https") or parsed.hostname is None:
        raise ValueError("URL must be an absolute HTTP(S) URL")
    if parsed.netloc.endswith(":"):
        raise ValueError("URL is malformed")
    if parsed.username is not None or parsed.password is not None:
        raise ValueError("URLs containing credentials are not allowed")

    host = _normalize_host(parsed.hostname)
    if ":" in host:
        host = "[" + host + "]"
    if port is not None and not (
        (scheme == "http" and port == 80)
        or (scheme == "https" and port == 443)
    ):
        host += ":" + str(port)

    return urlunsplit((scheme, host, parsed.path, parsed.query, ""))


def _normalize_url_prefix(url: str) -> str:
    if not isinstance(url, str) or not url or url != url.strip():
        raise ValueError("URL prefixes must be non-empty absolute HTTP(S) URLs")
    try:
        parsed = urlsplit(url)
    except ValueError as exc:
        raise ValueError("URL prefix is malformed") from exc
    if (
        parsed.query
        or parsed.fragment
        or not parsed.path.startswith("/")
        or not parsed.path.endswith("/")
    ):
        raise ValueError(
            "URL prefixes must have a slash-terminated path and no query or fragment"
        )
    return _normalize_url(url)


def _is_url_in_scope(
    url: str,
    allowed_domains: Tuple[str, ...],
    allowed_url_prefixes: Tuple[str, ...] = (),
) -> bool:
    try:
        parsed = urlsplit(url)
        host = parsed.hostname
        if host is None or _normalize_host(host) not in allowed_domains:
            return False
        if not allowed_url_prefixes:
            return True
        return any(
            prefix_parts.scheme == parsed.scheme
            and prefix_parts.netloc == parsed.netloc
            and parsed.path.startswith(prefix_parts.path)
            for prefix_parts in (urlsplit(prefix) for prefix in allowed_url_prefixes)
        )
    except ValueError:
        return False
