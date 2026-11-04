---
name: crawler
description: Guidance for bounded traversal with the framework-independent web-scraping crawler core.
---

# Crawler skill

## When to use

Use the Crawler when a task needs deterministic, bounded traversal of explicitly
permitted HTTP(S) URLs. The core takes seeds, a `CrawlPolicy`, a retriever, and
a link discoverer, then returns traversal metadata.

## Current API

The package exports `CrawlPolicy`, `Crawler`, `CrawlResult`, `CrawlFailure`,
`RetrievalResult`, `Retriever`, `LinkDiscoverer`, and `LinkEdge`. See the
module README for the complete public contract and example.

The core has no runtime dependencies and does not make network requests or
retain response bodies. Callers inject the retrieval and link-discovery
collaborators. Keep those integrations at the composition boundary; do not
couple the crawler core to private APIs of Fetcher or HTML Parser.

For optional HTTP crawling, install `web-scraping-crawler[scrapy]` and call
`crawl_with_scrapy(seeds, policy, link_discoverer)`. The helper uses Scrapy's
scheduler and returns the same `CrawlResult` shape; it accepts HTML text in
the link-discovery collaborator. It starts the Twisted reactor and can only be
called once in a normal synchronous Python process.

For JavaScript-rendered sites, install the `playwright` extra and Chromium,
then pass `render_javascript=True` to `crawl_with_scrapy`. Use
`render_wait_for="CSS selector"` when the page populates its links
asynchronously. Browser rendering is opt-in; regular Scrapy requests continue
to use HTTP. Both modes honor robots.txt, exact host scope, and crawl limits.
Playwright mode clicks `.child-card` elements by default to collect client-side
navigation URLs. Full-page navigation is intercepted without waiting for the
destination to load. In-scope destinations are scheduled through Scrapy;
out-of-scope destinations are reported in `CrawlResult.out_of_scope_urls` and
not crawled. Pass `click_selectors=(...)` to customize this; avoid generic
buttons unless their click behavior is expected and safe. Use
`load_more_selectors=(...)` to expand content before scanning cards; loaded
cards are restored after navigation when needed.
For a card-heavy seed page, `index_click_workers` can be set to any positive
integer to click disjoint card subsets using the seed page plus up to `N - 1`
additional pages. It is opt-in and may multiply index and load-more requests;
honor site rate limits and use the smallest effective count.

## Scope, identity, and limits

- Require explicit allowed domains and finite page, depth, and elapsed-time
  limits.
- Match allowed host names exactly; subdomains require explicit authorization.
- Optionally set `CrawlPolicy.allowed_url_prefixes` to further restrict pages
  to slash-terminated absolute URL prefixes; each host must already be
  authorized.
- Outside-prefix links are not scheduled. Ordinary extracted links outside the
  prefix are omitted; rendered card-navigation destinations are reported in
  `out_of_scope_urls`. Seeds and redirect destinations must also match a
  configured prefix.
- Only HTTP(S) URLs are accepted. Relative links resolve against the final
  page URL. Scheme/host are lowercased, default ports and fragments are
  removed, and query strings and paths are preserved.
- An out-of-scope seed is an error. Invalid or out-of-scope discovered links
  are skipped. Out-of-scope redirects are returned as structured failures.
- Collaborators must enforce their own request timeouts; the core cannot
  interrupt a blocking collaborator. The crawler does not retry failures.

## Network and access safety

The core itself performs no network access and does not fetch or enforce
robots.txt. Network adapters must respect robots directives, site terms, rate
limits, and access controls; they must not attempt to bypass them. Keep retries
and throttling bounded and explicit. Use controlled local fixtures for tests
rather than public websites.

## Scrapy adapter

The optional adapter enables robots.txt compliance, 15-second request
timeouts, two retries, bounded concurrency, and AutoThrottle. It enforces
configured host and URL-prefix scope on requests and redirect destinations.
The optional Playwright download handler uses headless Chromium with bounded
contexts and pages and a 15-second navigation timeout. Do not describe the
core itself as performing network access.

The standalone workflow's JSON output includes a `pages` array of URL/title
pairs. Titles come from the downloaded or rendered document; unavailable
titles are `null`.

## Integration boundary

Keep Playwright optional and ordinary HTTP as the default. Use the crawler
workflow documented in `workflows/crawler/README.md` to run a standalone
bounded crawl and save its result JSON. The CLI's `--click-selector` option
adds CSS selectors to the default `.child-card` selector. Its
`--index-click-workers` option requires `--render-javascript` and records the
configured worker count in `crawl_limits`.
