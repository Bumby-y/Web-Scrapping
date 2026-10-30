# Crawler

Coordinates bounded traversal of permitted web pages: decides **what to visit
next and when to stop**. It is an independently packaged Python module.

> **Status:** scaffold; no runtime API is implemented. This README describes
> intended scope, not available behavior.

## Owns

- Accept explicit seeds, crawl scope, and finite limits.
- Schedule discovered URLs; track scheduled, completed, and failed work.
- Avoid duplicate work and report results, failures, and stopping conditions.
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

- Require an authorized scope and finite page, depth, time, and network limits
  appropriate to the implementation.
- Validate candidate URLs against scope before scheduling. Recheck redirect
  destinations when the retriever exposes them; never silently expand scope.
- Make retry, rate, concurrency, and error behavior explicit and bounded.
- Keep crawl state separate from fetched content. Do not require durable state
  or a particular backend for the core scheduler.
- Introduce adapters only for demonstrated needs. Define narrow contracts,
  inject collaborators, and test with deterministic fakes.
- Use fixtures, fakes, or controlled local servers in tests, not public sites.

## Initial implementation

Implement deterministic in-memory coordination: explicit seeds and scope,
frontier management, duplicate avoidance, depth/page limits, and structured
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
