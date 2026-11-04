# Crawler workflow

`run.py` is the standalone crawler CLI. It extracts categorized URL references
from HTML using Scrapy by default, or can opt into Playwright Chromium to render
JavaScript applications such as Vue before discovering links. It saves crawl
metadata and discovered URLs, not response bodies.

## Install

From the repository root in PowerShell:

```powershell
python -m pip install -e "modules\crawler[scrapy,playwright]"
python -m playwright install chromium
```

## Quick start

The seed URL is positional. Its exact host is automatically used as the
allowed crawl scope, so a basic run needs no required flags:

```shell
python workflows/crawler/run.py "https://example.com/catalog/"
```

To restrict discovered links, scheduled pages, and crawl results to a URL
path, use `--allow-url-prefix` with a slash-terminated absolute URL:

```powershell
python workflows\crawler\run.py "https://train.slsnp.hkpl.gov.hk/hkrw/en/index.html" --render-javascript --allow-url-prefix "https://train.slsnp.hkpl.gov.hk/hkrw/en/" -o crawl-result.json
```

URLs must match the prefix's scheme, host, port, and path to be scheduled.
Out-of-prefix links are not crawled; rendered card-navigation destinations are
listed separately in `out_of_scope_urls`. The seed must be inside the prefix,
and each prefix's host must be the host of a seed or be explicitly allowed
with `-a`.

For JavaScript-rendered pages, opt into Playwright:

```powershell
python workflows\crawler\run.py "https://train.slsnp.hkpl.gov.hk/hkrw/en/index.html" --render-javascript -p 25 -d 2 -t 300 -o crawl-result.json
```

For pages that have a load-more button, click it before counting/clicking cards.
The crawl repeats until the button disappears, disables, or reaches the
per-expansion-pass cap (20 clicks by default). If returning from a clicked
route resets the page's loaded cards, the crawler clicks the load-more control
again to restore the previous card count before continuing:

```powershell
python workflows\crawler\run.py "https://train.slsnp.hkpl.gov.hk/hkrw/en/index.html" --render-javascript --load-more-selector ".section-more-btn" --max-load-more-clicks 20 --allow-url-prefix "https://train.slsnp.hkpl.gov.hk/hkrw/en/" -o crawl-result.json
```

For card-heavy index pages where navigating away and restoring loaded cards is
the bottleneck, use independent browser pages to click separate card subsets:

```powershell
python workflows\crawler\run.py "https://train.slsnp.hkpl.gov.hk/hkrw/en/index.html" --render-javascript --load-more-selector ".section-more-btn" --index-click-workers 6 --allow-url-prefix "https://train.slsnp.hkpl.gov.hk/hkrw/en/" -o crawl-result.json
```

Index click workers are opt-in (default: 1) with no fixed upper bound. The seed
page clicks one card subset; additional workers use their own pages to load
and expand the index, then click separate subsets. Concurrent clicks never
share a page. This can multiply index loads and load-more traffic by up to the
worker count. Use only where authorized, and choose a count appropriate for
the site's capacity and request policy. The configured worker count is
recorded in `crawl_limits`.

With Playwright enabled, the workflow waits up to two seconds for each
configured click selector to become visible, then clicks matching elements.
`.child-card` is included by default. If no match becomes visible, the report
records a zero match count without marking the page as failed. In-scope URLs
reached by Vue-style client-side navigation are recorded. Full-page navigation is captured but not followed in the browser;
in-scope URLs are queued through Scrapy, where robots and crawl-scope checks
apply, while out-of-scope destinations are reported separately and not
crawled. Clicks do not wait for an intercepted destination page to finish
loading; the crawler waits up to one second to detect navigation after each
click and up to 2.5 seconds for an intercepted full-page navigation to settle
before restoring the source page. To use additional selectors, repeat
`--click-selector`, such as
`--click-selector ".child-card" --click-selector "[role=button]"`. Generic
buttons are not clicked by default because they may trigger unrelated actions.

If links appear only after a known element is populated, also provide its
selector (for example `--render-wait-for "#app a[href]"`). The selector is
waited for on every rendered page; a timeout is recorded as a retrieval
failure.

The crawl results, including the discovered URL list, are saved to
`crawl-result.json` in your current terminal directory. Before crawling, the
terminal displays the page, depth, and time limits and a progress message. At
completion, it explains whether the eligible in-scope frontier was exhausted
or a page/time limit stopped the crawl. The defaults are 100 pages, depth 5,
and 300 seconds. Use short flags to change them or choose another
output path:

```shell
python workflows/crawler/run.py "https://example.com/catalog/" -p 25 -d 3 -t 90 -o crawl-result.json
```

## Multiple seeds and hosts

Pass any number of seed URLs positionally. Each seed's exact host is allowed
automatically. Use `-a` / `--allow-domain` to additionally authorize hosts
that may appear in links but are not seed hosts.

```powershell
python workflows\crawler\run.py "https://example.com/catalog/" "https://example.com/news/" -p 25 -d 3
```

To allow links to a subdomain, authorize it explicitly:

```shell
python workflows/crawler/run.py "https://example.com/" -a shop.example.com
```

Host matching is exact. A seed on `example.com` does not implicitly authorize
`shop.example.com`.

## Limits and output

- `-p`, `--max-pages`: maximum number of unique scheduled pages (default: 100).
- `-d`, `--max-depth`: maximum link depth from each seed (default: 5).
- `-t`, `--max-seconds`: maximum crawl duration (default: 300).
- `--render-javascript`: opt in to Playwright Chromium rendering.
- `--render-wait-for CSS`: wait for a CSS selector on each rendered page.
- `--load-more-selector CSS`: click matching controls before scanning and
  clicking cards; repeat for multiple selectors.
- `--max-load-more-clicks N`: maximum clicks across load-more selectors per
  expansion pass
  (default: 20).
- `--index-click-workers N`: number of independent browser pages clicking
  separate index-card subsets (positive integer, default: 1); requires
  `--render-javascript`.
- `--click-selector CSS`: click selector matches to discover client-side
  navigation; defaults to `.child-card` when rendering is enabled. Repeat to
  add selectors.
- `--allow-url-prefix URL`: additionally restrict pages/results to one
  slash-terminated URL prefix; repeat to allow multiple.
- `-a`, `--allow-domain`: additionally authorize an exact host; repeat as
  needed.
- `-o`, `--output`: JSON output path (default: `crawl-result.json` in the
  current directory).

The JSON file includes the page, depth, and time limits used, the termination
reason, visited and successful URLs, structured failures, in-scope discovered
URLs, categorized `link_references`, unique `out_of_scope_urls`, unique
in-scope navigation edges, and per-page counts of matches for each Playwright
click selector and load-more clicks, including re-expansion clicks used to
restore cards after navigation. References cover hyperlinks, file links,
image/media and other resources, CSS URLs, embedded resources, form actions,
metadata, citation URLs, visible-text URLs, and absolute URLs in script text.
Each reference has its source page, target, category, attribute, scope
(`in_scope`, `out_of_scope`, or `non_http`), and `follow` flag. Out-of-scope
references are recorded but never scheduled; non-page resources such as images
and file downloads are recorded with `follow: false` and are not fetched as
pages. It also includes a
`pages` array with each successful page's URL and title:

```json
{
  "pages": [
    {"url": "https://example.com/", "title": "Example"},
    {"url": "https://example.com/untitled", "title": null}
  ]
}
```

Titles are read from the downloaded HTML, or from the rendered document when
Playwright is enabled. Missing or empty titles are `null`; the URL fields and
their existing shapes remain unchanged. The terminal also prints aggregate
match/click totals. A load-more selector with no visible match records zero
clicks and is not an error. Scrapy's concurrent completion order is not
guaranteed to be deterministic.

`page_timings` contains per-page `request_total_seconds` and Playwright phase
durations, including load-more clicks/content waits, card click/navigation
detection, and returning to the source page/restoring cards. The request total
includes rendering and can overlap other requests because Scrapy is concurrent;
phase totals are diagnostic measurements, not mutually exclusive wall-clock
buckets.

Robots.txt compliance is always enabled. The adapter also uses a 15-second
request timeout, up to two retries, bounded concurrency, and AutoThrottle.
Playwright rendering is optional and uses headless Chromium with a 15-second
navigation timeout and bounded contexts/pages. Browser rendering does not
disable site restrictions or access controls. Use only authorized sites and
check the target's robots directives before crawling.

The CLI starts Scrapy's Twisted reactor. Run it as a standalone terminal
process; do not invoke multiple crawls by calling its helper repeatedly in one
process.
