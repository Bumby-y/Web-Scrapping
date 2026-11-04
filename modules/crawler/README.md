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

For optional Playwright rendering (Python 3.10+), install its extra and the
Chromium browser:

```shell
python -m pip install ".[scrapy,playwright]"
python -m playwright install chromium
```

For development and all adapter tests, install the extras:

```shell
python -m pip install -e ".[dev,scrapy,playwright]"
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
`LinkDiscoverer.discover_links(content)` returns candidate URL strings or
`LinkReference` values. The crawler resolves relative links against the final
URL and checks scope before recording or scheduling them. Collaborators must
enforce their own request timeouts; the elapsed-time limit prevents starting
additional work but cannot interrupt a blocking collaborator.

Discoverers may also return `LinkReference` values to preserve the reference
category, source attribute, optional HTML `<base href>`, and whether the
reference should be followed as a page. The crawler records normalized entries
in `CrawlResult.link_references` with `in_scope`, `out_of_scope`, or `non_http`
scope, plus a `follow` flag. Out-of-scope HTTP(S) references are also collected in
`out_of_scope_urls`; resource references such as images are recorded without
being fetched as pages.

## Policy and URL identity

`CrawlPolicy` requires at least one explicit allowed host and finite positive
`max_pages`, non-negative `max_depth`, and positive `max_elapsed_time`.
Allowed hosts match exactly: a subdomain is allowed only if explicitly listed.
Optionally set `allowed_url_prefixes` to slash-terminated absolute URL prefixes
to further restrict seeds, redirects, discovered links, and scheduled pages.
Each prefix must use an allowed host; scheme, host, port, and path prefix must
match, and query strings/fragments are not allowed in the prefix.

URL identity rules:

- Only absolute HTTP(S) URLs are accepted as seeds; relative links are
  resolved against their source page.
- Scheme and host are lowercased; default ports and fragments are removed.
- Query strings, paths, and trailing slashes are preserved.
- URLs containing credentials are rejected.
- Normalized URLs are used consistently for scope checks, deduplication,
  visits, and discovered links.
- An out-of-scope seed raises `ValueError`. Invalid candidate links are
  ignored. Categorized out-of-scope HTTP(S) references are recorded but not
  traversed. Redirects outside the allowed scope become structured failures
  and link references.
- With no `allowed_url_prefixes`, only exact-host rules apply. When prefixes
  are set, URLs outside every prefix are excluded from traversal and in-scope
  link edges.

## Results and failures

`CrawlResult` contains immutable tuples:

- `visited_urls`: normalized URLs for which retrieval was attempted.
- `successful_urls`: URLs retrieved with an in-scope final destination.
  A later link-discovery failure may still be reported for a successful fetch.
- `failed_urls`: `CrawlFailure` records with URL, stage, error type, and
  message. Failed URLs are also visited URLs.
- `discovered_urls`: unique in-scope links found on retrieved pages, excluding
  seed URLs. Links are reported even when their depth prevents scheduling.
- `out_of_scope_urls`: unique HTTP(S) destinations found in any extracted
  reference or rendered navigation that are outside the configured crawl
  scope. They are reported but not scheduled for crawling.
- `link_references`: categorized page-to-URL references, including hyperlinks,
  file links, text URLs, image/media/script/style resources, embedded resources,
  form actions, citations, metadata references, and rendered JavaScript
  navigation. Each record includes category, source attribute, scope, and
  whether it is followed as a page.
- `page_titles`: available `(url, title)` pairs from the Scrapy adapter. A
  missing or empty page title is represented as `None`; the framework-
  independent core does not infer titles from arbitrary payloads.
- `termination_reason`: `frontier_exhausted`, `page_limit`, or `time_limit`.
  The Scrapy adapter reports other Scrapy closure reasons as
  `stopped:<reason>`.
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

### Optional JavaScript rendering

The Scrapy adapter uses ordinary HTTP by default. To render pages with
Playwright Chromium before link discovery, pass `render_javascript=True`.
Scrapy's scheduler, robots.txt checks, scope checks, retries, and crawl limits
continue to apply to page requests. The browser has a 15-second navigation
timeout and at most two contexts with two pages each. The same 15-second
timeout applies to an optional CSS selector wait:

```python
result = crawl_with_scrapy(
    seeds=("https://example.com/",),
    policy=CrawlPolicy(
        allowed_domains=("example.com",),
        max_pages=100,
        max_depth=3,
        max_elapsed_time=60,
    ),
    link_discoverer=HtmlLinkDiscoverer(),
    render_javascript=True,
    render_wait_for="#app a[href]",
)
```

`render_wait_for` is useful when an application populates its DOM
asynchronously; without it, Playwright waits for the page's normal load event.
Selector timeout errors are reported as retrieval failures rather than
returning a success-shaped empty page. Rendering is opt-in and requires
Python 3.10 or newer; ordinary Scrapy requests do not start a browser.
With rendering enabled, the adapter waits up to two seconds for each configured
click selector to become visible, then clicks matching elements. `.child-card`
is included by default, and in-scope URLs reached by client-side navigation
are discovered. If a selector has no visible matches, its count is recorded as
zero without marking the page as failed. The crawl result includes the number
of matched elements for each selector on each rendered page. Full-page
navigation requests are intercepted without waiting for the destination page
to finish loading. After each click, the adapter waits up to one second to
detect navigation; for an intercepted full-page navigation, it then waits up
to 2.5 seconds for the main frame to settle before restoring the source page.
Non-navigating cards do not consume the full click timeout. In-scope
destinations are queued through Scrapy under its
normal robots and scope checks; out-of-scope destinations are recorded in
`out_of_scope_urls` and are not crawled. Pass `click_selectors` to
`crawl_with_scrapy` to customize selectors. Generic buttons are not clicked
by default.

Pass `load_more_selectors` to `crawl_with_scrapy` to click known load-more
controls before card discovery. Each control is clicked repeatedly while it
remains visible and enabled, up to `max_load_more_clicks` per expansion pass
(default: 20). If navigating to a discovered route and returning resets the
loaded cards, the adapter expands again until the previous card count is
restored or the control stops making progress. The result records every click,
including those re-expansion clicks, by page and selector; a missing control
records zero clicks without failing the page.

For a card-heavy seed/index page, set `index_click_workers` (positive integer,
default: 1) to click disjoint card subsets using the seed page plus up to
`N - 1` additional Playwright pages. Additional pages load and expand the
index separately, then report their discovered destinations back to the crawl.
Pages do not share page state, but index loads and load-more clicks can
multiply site traffic by the worker count. Keep this opt-in and choose a count
appropriate for site capacity.

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
The Playwright extra adds opt-in JavaScript rendering without making a browser
a dependency of the core or ordinary Scrapy adapter. Respect site terms and
access controls.

See [ROADMAP.md](ROADMAP.md) for implementation phases and acceptance tests.
The [crawler skill](skills/crawler/SKILL.md) contains guidance for AI-agent
use. Follow [shared architecture guidance](../../docs/ARCHITECTURE.md) for
module boundaries.
