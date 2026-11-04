"""Run a bounded crawl using the optional Scrapy and Playwright adapters."""

from __future__ import annotations

import argparse
import json
import sys
from html.parser import HTMLParser
from pathlib import Path
from typing import Iterable, Optional, Sequence
from urllib.parse import urlsplit

from web_scraping_crawler import CrawlPolicy, CrawlResult, crawl_with_scrapy


class _AnchorParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.links: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, Optional[str]]]) -> None:
        if tag.lower() == "a":
            self.links.extend(
                value for name, value in attrs if name.lower() == "href" and value
            )

    def handle_startendtag(
        self, tag: str, attrs: list[tuple[str, Optional[str]]]
    ) -> None:
        self.handle_starttag(tag, attrs)


class HTMLAnchorLinkDiscoverer:
    """Extract anchor hrefs from downloaded HTML without executing scripts."""

    def discover_links(self, content: str) -> Iterable[str]:
        parser = _AnchorParser()
        parser.feed(content)
        parser.close()
        return parser.links


def _arguments(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Crawl authorized seeds with Scrapy. JavaScript rendering is "
            "opt-in; robots.txt compliance and bounded network settings "
            "are always enabled."
        )
    )
    parser.add_argument(
        "seed_urls",
        nargs="+",
        metavar="URL",
        help="One or more starting URLs.",
    )
    parser.add_argument(
        "-a",
        "--allow-domain",
        action="append",
        metavar="HOST",
        help=(
            "Additional exact host to allow. Seed hosts are allowed "
            "automatically; repeat for explicitly authorized linked hosts."
        ),
    )
    parser.add_argument(
        "--allow-url-prefix",
        action="append",
        metavar="URL",
        help=(
            "Restrict the crawl to this slash-terminated URL prefix, for "
            "example https://example.com/catalog/. Repeat to allow more."
        ),
    )
    parser.add_argument(
        "-p", "--max-pages", type=int, default=100, metavar="N",
        help="Maximum scheduled pages (default: 100).",
    )
    parser.add_argument(
        "-d", "--max-depth", type=int, default=5, metavar="N",
        help="Maximum link depth (default: 5).",
    )
    parser.add_argument(
        "-t", "--max-seconds", type=float, default=300, metavar="SECONDS",
        help="Maximum crawl duration (default: 300).",
    )
    parser.add_argument(
        "--render-javascript",
        action="store_true",
        help=(
            "Render each crawled page with Playwright Chromium before "
            "discovering links."
        ),
    )
    parser.add_argument(
        "--render-wait-for",
        metavar="CSS",
        help=(
            "Wait for this CSS selector on each rendered page before "
            "discovering links; requires --render-javascript."
        ),
    )
    parser.add_argument(
        "--click-selector",
        action="append",
        metavar="CSS",
        help=(
            "Click matching elements to discover Vue navigation URLs. "
            "Defaults to .child-card with Playwright; repeat to add selectors."
        ),
    )
    parser.add_argument(
        "--load-more-selector",
        action="append",
        metavar="CSS",
        help=(
            "Click matching load-more buttons before scanning/clicking cards; "
            "repeat to add selectors."
        ),
    )
    parser.add_argument(
        "--max-load-more-clicks",
        type=int,
        default=20,
        metavar="N",
        help="Maximum load-more clicks per expansion pass (default: 20).",
    )
    parser.add_argument(
        "--index-click-workers",
        type=int,
        default=1,
        metavar="N",
        help=(
            "Parallel browser pages for clicking index cards (positive integer, "
            "default: 1); "
            "requires --render-javascript."
        ),
    )
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        default=Path("crawl-result.json"),
        help="Write the JSON result to this file (default: crawl-result.json).",
    )
    args = parser.parse_args(argv)
    if args.render_wait_for is not None:
        if not args.render_wait_for.strip():
            parser.error("--render-wait-for must be a non-empty CSS selector")
        if not args.render_javascript:
            parser.error("--render-wait-for requires --render-javascript")
    if args.click_selector is not None and not args.render_javascript:
        parser.error("--click-selector requires --render-javascript")
    if args.load_more_selector is not None and not args.render_javascript:
        parser.error("--load-more-selector requires --render-javascript")
    if args.max_load_more_clicks < 1:
        parser.error("--max-load-more-clicks must be a positive integer")
    if args.index_click_workers < 1:
        parser.error("--index-click-workers must be a positive integer")
    if args.index_click_workers > 1 and not args.render_javascript:
        parser.error("--index-click-workers greater than 1 requires --render-javascript")
    return args


def _result_dict(
    result: CrawlResult,
    policy: CrawlPolicy,
    index_click_workers: int = 1,
) -> dict:
    return {
        "crawl_limits": {
            "max_pages": policy.max_pages,
            "max_depth": policy.max_depth,
            "max_elapsed_time_seconds": policy.max_elapsed_time,
            "index_click_workers": index_click_workers,
        },
        "termination_reason": result.termination_reason,
        "page_timings": [
            {"page_url": page_url, "phase": phase, "seconds": seconds}
            for page_url, phase, seconds in result.page_timings
        ],
        "visited_urls": list(result.visited_urls),
        "successful_urls": list(result.successful_urls),
        "pages": [
            {"url": url, "title": title}
            for url, title in result.page_titles
        ],
        "failed_urls": [
            {
                "url": failure.url,
                "stage": failure.stage,
                "error_type": failure.error_type,
                "message": failure.message,
                "redirect_url": failure.redirect_url,
            }
            for failure in result.failed_urls
        ],
        "discovered_urls": list(result.discovered_urls),
        "out_of_scope_urls": list(result.out_of_scope_urls),
        "link_edges": [list(edge) for edge in result.link_edges],
        "edge_count": result.edge_count,
        "click_selector_counts": [
            {
                "page_url": page_url,
                "selector": selector,
                "count": count,
            }
            for page_url, selector, count in result.click_selector_counts
        ],
        "load_more_click_counts": [
            {
                "page_url": page_url,
                "selector": selector,
                "count": count,
            }
            for page_url, selector, count in result.load_more_click_counts
        ],
    }


def _scope_hosts(seed_urls: Sequence[str], extra_hosts: Optional[Sequence[str]]) -> tuple[str, ...]:
    hosts = set(extra_hosts or ())
    for seed in seed_urls:
        try:
            host = urlsplit(seed).hostname
        except ValueError as exc:
            raise SystemExit("Invalid seed URL {!r}: {}".format(seed, exc)) from exc
        if host is None:
            raise SystemExit(
                "Invalid seed URL {!r}: expected an absolute HTTP(S) URL".format(seed)
            )
        hosts.add(host)
    return tuple(sorted(hosts))


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = _arguments(argv)
    try:
        policy = CrawlPolicy(
            allowed_domains=_scope_hosts(args.seed_urls, args.allow_domain),
            max_pages=args.max_pages,
            max_depth=args.max_depth,
            max_elapsed_time=args.max_seconds,
            allowed_url_prefixes=tuple(args.allow_url_prefix or ()),
        )
    except (TypeError, ValueError) as exc:
        raise SystemExit("Invalid crawl policy: {}".format(exc)) from exc

    print(
        "Crawl limits: pages={}, depth={}, time={} seconds.".format(
            policy.max_pages,
            policy.max_depth,
            policy.max_elapsed_time,
        )
    )
    print("Index card-click workers: {}.".format(args.index_click_workers))
    print(
        "Crawl in progress; this may take up to the configured time limit.",
        flush=True,
    )

    result = crawl_with_scrapy(
        seeds=tuple(args.seed_urls),
        policy=policy,
        link_discoverer=HTMLAnchorLinkDiscoverer(),
        render_javascript=args.render_javascript,
        render_wait_for=args.render_wait_for,
        click_selectors=(
            tuple(args.click_selector) if args.click_selector is not None else None
        ),
        load_more_selectors=(
            tuple(args.load_more_selector)
            if args.load_more_selector is not None
            else None
        ),
        max_load_more_clicks=args.max_load_more_clicks,
        index_click_workers=args.index_click_workers,
    )
    timing_totals = {}
    for _, phase, seconds in result.page_timings:
        timing_totals[phase] = timing_totals.get(phase, 0.0) + seconds
    serialized = json.dumps(
        _result_dict(result, policy, args.index_click_workers),
        indent=2,
    )
    args.output.write_text(serialized + "\n", encoding="utf-8")

    print("Crawl complete.")
    termination_messages = {
        "frontier_exhausted": (
            "Stop reason: no more eligible in-scope pages remain; the crawl "
            "frontier is exhausted (depth and scope limits apply)."
        ),
        "page_limit": "Stop reason: maximum page limit reached.",
        "time_limit": "Stop reason: maximum crawl time reached.",
    }
    print(
        termination_messages.get(
            result.termination_reason,
            "Stop reason: {}".format(result.termination_reason or "unknown"),
        )
    )
    print(
        "Visited: {} | Successful: {} | Discovered: {} | Failed: {}".format(
            len(result.visited_urls),
            len(result.successful_urls),
            len(result.discovered_urls),
            len(result.failed_urls),
        )
    )
    if timing_totals:
        print(
            "Timing totals are cumulative by page; request totals include "
            "rendering and can overlap across concurrent requests."
        )
        print(
            "Measured time by phase (seconds): {}".format(
                " | ".join(
                    "{}={:.1f}".format(phase, seconds)
                    for phase, seconds in sorted(
                        timing_totals.items(),
                        key=lambda item: item[1],
                        reverse=True,
                    )
                )
            )
        )
    if result.out_of_scope_urls:
        print(
            "Out-of-scope destinations (reported, not crawled): {}".format(
                len(result.out_of_scope_urls)
            )
        )
    selector_totals = {}
    for _, selector, count in result.click_selector_counts:
        selector_totals[selector] = selector_totals.get(selector, 0) + count
    if selector_totals:
        print(
            "Click selector matches: {}".format(
                " | ".join(
                    "{}={}".format(selector, count)
                    for selector, count in selector_totals.items()
                )
            )
        )
    load_more_totals = {}
    for _, selector, count in result.load_more_click_counts:
        load_more_totals[selector] = load_more_totals.get(selector, 0) + count
    if load_more_totals:
        print(
            "Load-more clicks: {}".format(
                " | ".join(
                    "{}={}".format(selector, count)
                    for selector, count in load_more_totals.items()
                )
            )
        )
    print(
        "Full results (including discovered links): {}".format(
            args.output.resolve()
        )
    )

    return 0


if __name__ == "__main__":
    sys.exit(main())
