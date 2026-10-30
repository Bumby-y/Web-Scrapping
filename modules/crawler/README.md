# Crawler

Coordinates bounded traversal of permitted web pages: decides **what to visit
next and when to stop**. It is an independently packaged Python module.

> **Status:** scaffold; no runtime API is implemented. This README describes
> intended scope, not available behavior.

## Owns

- Accept explicit seeds, crawl scope, and finite limits.
- Schedule discovered URLs; track scheduled, completed, and failed work.
- Avoid duplicate work using a documented URL identity contract.
- Return a structured result with visited, failed, and discovered URLs.
- Coordinate retrieval and link discovery through small, explicit contracts.

## Does not own

- HTTP transport, response decoding, retries, or request errors: use the
  Fetcher or a caller-provided retriever.
- HTML parsing or link extraction: use the HTML Parser or a caller-provided
  link discoverer.
- Application orchestration, durable page-content storage, or infrastructure
  selection.
- Bypassing authentication, access controls, CAPTCHAs, robots directives, or
  rate limits.

## Boundaries

- Put crawl limits and scope in a `CrawlPolicy`, separate from crawler
  collaborators and runtime wiring.
- Require an authorized scope and finite page, depth, time, and network limits
  appropriate to the implementation.
- Validate candidate URLs against scope before scheduling. Recheck redirect
  destinations when the retriever exposes them; never silently expand scope.
- Normalize URLs consistently before scope checks and discovery, scheduling,
  and visitation lookups. Document whether fragments, query strings, trailing
  slashes, host casing, default ports, and relative URLs identify the same
  resource. Do not silently discard query parameters; they may change content.
- Make retry, rate, concurrency, and error behavior explicit and bounded.
- Keep crawl state separate from fetched content. Do not require durable state
  or a particular backend for the core scheduler.
- Introduce adapters only for demonstrated needs. Define narrow contracts,
  inject collaborators, and test with deterministic fakes.
- Use fixtures, fakes, or controlled local servers in tests, not public sites.

## Public contract

The API is not implemented. Use explicit policy and structured output rather
than hiding crawl behavior in constructor flags:

```python
policy = CrawlPolicy(
    max_depth=3,
    max_pages=100,
    same_domain_only=True,
)
result = Crawler(policy=policy).crawl(seeds, retriever, link_discoverer)
```

`CrawlPolicy` should own traversal limits and scope rules. Define validation,
defaults, and interactions between options; `same_domain_only` must not replace
explicit authorization or allowed-domain rules.

`CrawlResult` should provide at least `visited_urls`, `failed_urls`,
`discovered_urls`, and `edge_count`. Define URL normalization for every field.
Document whether failed URLs overlap visited URLs, what counts as discovered,
and whether `edge_count` counts unique directed links. Failures should retain
enough structured detail for callers to understand the URL and error.

The URL identity rules above are part of the public contract, not an
implementation detail. Cover each normalization case with deterministic
tests before treating the behavior as stable.

## Initial implementation

Implement deterministic in-memory coordination: explicit seeds and scope,
frontier management, policy validation, documented URL normalization,
duplicate avoidance, depth/page limits, and structured `CrawlResult`
outcomes. Keep network access, HTML parsing, distributed workers, and durable
storage optional.

Before adding integrations, document their contracts and test core behavior
independently. Update this README, `module.json`, and the AI skill whenever
public behavior changes. Follow [`docs/ARCHITECTURE.md`](../../docs/ARCHITECTURE.md)
for shared design principles.

## Related files

- `pyproject.toml` — package metadata and dependencies.
- `module.json` — discovery metadata.
- `src/web_scraping_crawler/` — implementation.
- `tests/` — behavior and adapter contract tests.
- `skills/crawler/SKILL.md` — AI-agent usage guidance.
