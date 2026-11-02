"""Run a bounded crawl using the optional Scrapy adapter."""

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
            "Crawl authorized seeds with Scrapy. Robots.txt compliance and "
            "bounded network settings are always enabled."
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
        "-p", "--max-pages", type=int, default=100, metavar="N",
        help="Maximum scheduled pages (default: 10).",
    )
    parser.add_argument(
        "-d", "--max-depth", type=int, default=4, metavar="N",
        help="Maximum link depth (default: 2).",
    )
    parser.add_argument(
        "-t", "--max-seconds", type=float, default=300, metavar="SECONDS",
        help="Maximum crawl duration (default: 60).",
    )
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        default=Path("crawl-result.json"),
        help="Write the JSON result to this file (default: crawl-result.json).",
    )
    return parser.parse_args(argv)


def _result_dict(result: CrawlResult) -> dict:
    return {
        "visited_urls": list(result.visited_urls),
        "successful_urls": list(result.successful_urls),
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
        "link_edges": [list(edge) for edge in result.link_edges],
        "edge_count": result.edge_count,
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
        )
    except (TypeError, ValueError) as exc:
        raise SystemExit("Invalid crawl policy: {}".format(exc)) from exc

    result = crawl_with_scrapy(
        seeds=tuple(args.seed_urls),
        policy=policy,
        link_discoverer=HTMLAnchorLinkDiscoverer(),
    )
    serialized = json.dumps(_result_dict(result), indent=2)
    args.output.write_text(serialized + "\n", encoding="utf-8")

    print("Crawl complete.")
    print(
        "Visited: {} | Successful: {} | Discovered: {} | Failed: {}".format(
            len(result.visited_urls),
            len(result.successful_urls),
            len(result.discovered_urls),
            len(result.failed_urls),
        )
    )
    print("Full results (including discovered links): {}".format(args.output.resolve()))

    return 0


if __name__ == "__main__":
    sys.exit(main())
