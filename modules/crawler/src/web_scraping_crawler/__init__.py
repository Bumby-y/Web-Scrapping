"""Framework-independent crawl coordination utilities."""

from .crawler import (
    CrawlFailure,
    CrawlPolicy,
    CrawlResult,
    Crawler,
    LinkDiscoverer,
    LinkEdge,
    RetrievalResult,
    Retriever,
)
from .scrapy_adapter import crawl_with_scrapy

__all__ = [
    "CrawlFailure",
    "CrawlPolicy",
    "CrawlResult",
    "Crawler",
    "LinkDiscoverer",
    "LinkEdge",
    "RetrievalResult",
    "Retriever",
    "crawl_with_scrapy",
]
