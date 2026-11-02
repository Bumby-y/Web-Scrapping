# Crawler

The Crawler coordinates bounded traversal of explicitly permitted URLs. Its
core is framework-independent: retrieval and link extraction are supplied as
small collaborators, and the core does not make network requests or retain
page content.

## Installation

Install the framework-independent core from this directory:

```shell
python -m pip install .
```

For the optional Scrapy adapter, install its extra:

```shell
python -m pip install ".[scrapy]"
```

For development and adapter tests, install both extras:

```shell
python -m pip install -e ".[dev,scrapy]"
```

## Public API

```python
from web_scraping_crawler import (
    CrawlPolicy,
    Crawler,
    RetrievalResult,
)


class Retriever:
    def retrieve(self, url: str) -> RetrievalResult[str]:
        # Return content from the caller's authorized retrieval implementation.
        return RetrievalResult(content="", final_url=url)


class LinkDiscoverer:
    def discover_links(self, content: str) -> list[str]:
        # Parse links using caller-provided logic.
        return []


policy = CrawlPolicy(
    allowed_domains=("example.com",),
    max_pages=100,
    max_depth=3,
    max_elapsed_time=60,
)
result = Crawler(policy).crawl(
    ("https://example.com/",),
    Retriever(),
    LinkDiscoverer(),
)
```

`Retriever.retrieve(url)` returns a `RetrievalResult` containing an arbitrary
payload and optionally the final URL after redirects.
`LinkDiscoverer.discover_links(content)` returns candidate URL strings. The
crawler resolves relative links against the final URL and checks scope before
recording or scheduling them. Collaborators must enforce their own request
timeouts; the elapsed-time limit prevents starting additional work but cannot
interrupt a blocking collaborator.

## Policy and URL identity

`CrawlPolicy` requires at least one explicit allowed host and finite positive
`max_pages`, non-negative `max_depth`, and positive `max_elapsed_time`.
Allowed hosts match exactly: a subdomain is allowed only if explicitly listed.

URL identity rules:

- Only absolute HTTP(S) URLs are accepted as seeds; relative links are
  resolved against their source page.
- Scheme and host are lowercased; default ports and fragments are removed.
- Query strings, paths, and trailing slashes are preserved.
- URLs containing credentials are rejected.
- Normalized URLs are used consistently for scope checks, deduplication,
  visits, and discovered links.
- An out-of-scope seed raises `ValueError`. Invalid or out-of-scope candidate
  links are ignored. Redirects outside the allowed scope become structured
  failures and are not parsed.

## Results and failures

`CrawlResult` contains immutable tuples:

- `visited_urls`: normalized URLs for which retrieval was attempted.
- `successful_urls`: URLs retrieved with an in-scope final destination.
  A later link-discovery failure may still be reported for a successful fetch.
- `failed_urls`: `CrawlFailure` records with URL, stage, error type, and
  message. Failed URLs are also visited URLs.
- `discovered_urls`: unique in-scope links found on retrieved pages, excluding
  seed URLs. Links are reported even when their depth prevents scheduling.
- `link_edges`: unique directed `(source_url, target_url)` pairs for
  in-scope links. `edge_count` is the number of these pairs.

The core traverses URLs in FIFO order and enforces page, depth, and elapsed
time bounds. Retrieval and link-discovery exceptions are returned as
per-URL failures; the crawler does not retry them.

## Optional Scrapy HTTP adapter

The optional adapter uses Scrapy's scheduler and duplicate filter; it does not
run the core's separate in-memory frontier. It shares the core's scope and URL
identity rules and accepts the same `CrawlPolicy`. The link discoverer receives
the downloaded response body as a string.

```python
from parsel import Selector
from web_scraping_crawler import CrawlPolicy, crawl_with_scrapy


class HtmlLinkDiscoverer:
    def discover_links(self, html: str) -> list[str]:
        return Selector(text=html).css("a::attr(href)").getall()


result = crawl_with_scrapy(
    seeds=("https://example.com/",),
    policy=CrawlPolicy(
        allowed_domains=("example.com",),
        max_pages=100,
        max_depth=3,
        max_elapsed_time=60,
    ),
    link_discoverer=HtmlLinkDiscoverer(),
)
```

This helper is for a normal synchronous script: it starts and stops Scrapy's
Twisted reactor, so call it at most once per Python process and do not call it
from an already-running event loop. Applications that already own a reactor
need a runner-based integration, which is not included in this adapter.

Adapter defaults are deliberately bounded:

- Robots.txt compliance is enabled and is not disabled by this helper.
- Each download times out after 15 seconds; Scrapy retries eligible failures
  at most twice.
- Total concurrency is 4 requests, with at most 2 per domain.
- AutoThrottle is enabled with a 1-second starting delay, 10-second maximum
  delay, and target concurrency of 1.
- The policy's page limit caps unique scheduled pages (redirects and retries
  do not consume additional page slots); its depth limit prevents deeper links
  from being scheduled, and its elapsed-time limit closes the spider.
- Every request is checked against the exact allowed-domain scope before
  download. Out-of-scope redirect destinations are blocked and returned as
  structured redirect failures.

The adapter uses the same URL identity rules as the core: fragments and
default ports do not distinguish requests, while query strings and paths are
preserved. Adapter result order follows Scrapy's concurrent response/error
completion and is not guaranteed to be deterministic.

## Boundaries and future integrations

The framework-independent core does not implement HTTP transport, HTML
parsing, robots.txt retrieval, retries, throttling, persistence, distributed
workers, or browser rendering. The Scrapy extra supplies optional HTTP
retrieval with robots compliance, bounded retries, timeouts, and throttling.
Respect site terms and access controls. Playwright rendering remains a future
optional phase and is not a dependency of the core or Scrapy adapter.

See [ROADMAP.md](ROADMAP.md) for implementation phases and acceptance tests.
The [crawler skill](skills/crawler/SKILL.md) contains guidance for AI-agent
use. Follow [shared architecture guidance](../../docs/ARCHITECTURE.md) for
module boundaries.
