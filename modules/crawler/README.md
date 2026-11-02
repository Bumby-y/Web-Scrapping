# Crawler

The Crawler coordinates bounded traversal of explicitly permitted URLs. Its
core is framework-independent: retrieval and link extraction are supplied as
small collaborators, and the core does not make network requests or retain
page content.

## Installation

Install the package from this directory. The core has no runtime dependencies:

```shell
python -m pip install .
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

## Boundaries and future integrations

The core does not implement HTTP transport, HTML parsing, robots.txt retrieval,
retries, throttling, persistence, distributed workers, or browser rendering.
Use authorized retrieval, respect site terms and access controls, and apply
robots and rate-limit requirements in the network adapter. Scrapy and
Playwright integrations are future, optional phases; neither is a dependency
of the core.

See [ROADMAP.md](ROADMAP.md) for implementation phases and acceptance tests.
The [crawler skill](skills/crawler/SKILL.md) contains guidance for AI-agent
use. Follow [shared architecture guidance](../../docs/ARCHITECTURE.md) for
module boundaries.
