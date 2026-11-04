"""Framework-independent crawl coordination utilities."""

from .crawler import (
    CrawlFailure,
    CrawlLinkReference,
    CrawlPolicy,
    CrawlResult,
    Crawler,
    LinkDiscoverer,
    LinkEdge,
    LinkReference,
    RetrievalResult,
    Retriever,
)
from .html_links import HTMLLinkDiscoverer
from .scrapy_adapter import crawl_with_scrapy

__all__ = [
    "CrawlFailure",
    "CrawlLinkReference",
    "CrawlPolicy",
    "CrawlResult",
    "Crawler",
    "HTMLLinkDiscoverer",
    "LinkDiscoverer",
    "LinkEdge",
    "LinkReference",
    "RetrievalResult",
    "Retriever",
    "crawl_with_scrapy",
]
