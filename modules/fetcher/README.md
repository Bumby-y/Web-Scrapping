# Fetcher

Retrieves individual web resources over HTTP and returns a documented response
or failure. It is an independently packaged Python module.

> **Status:** scaffold; no runtime API is implemented. This README describes
> intended scope, not available behavior.

## Owns

- Make destination and request options explicit.
- Perform a bounded request with documented timeout and redirect behavior.
- Return documented response status, metadata, and content.
- Report transport and response failures clearly.

## Does not own

- Selecting or scheduling URLs, crawl traversal, or duplicate tracking: use
  the Crawler or calling application.
- HTML interpretation or data extraction: use the HTML Parser or caller code.
- Application orchestration, durable content storage, or infrastructure
  selection.
- Bypassing authentication, access controls, CAPTCHAs, or rate limits.

## Boundaries

- Request only resources the user is authorized to access; respect site terms,
  robots directives where applicable, rate limits, and access controls.
- Keep network access explicit. Do not silently follow redirects outside the
  caller's permitted scope; expose redirect information for caller validation.
- Document response-size, decoding, status, timeout, and retry behavior.
  Bound requests and retries; avoid logging sensitive request or response data.
- Keep transport replaceable only when needed. Define a narrow, vendor-neutral
  contract and inject implementations explicitly.
- Test with mocks, fixtures, or controlled local servers, not public websites.

## Initial implementation

Implement one bounded request to an explicit destination, with documented
configuration, response representation, redirect behavior, and clear errors.
Do not add crawl traversal, HTML parsing, or persistence. Define and test the
contract before adding retries, concurrency, caching, proxy support, or
specialized transports.

Update this README, `module.json`, and the AI skill whenever public behavior
changes. Follow [`docs/ARCHITECTURE.md`](../../docs/ARCHITECTURE.md) for shared
design principles.

## Related files

- `pyproject.toml` — package metadata and dependencies.
- `module.json` — discovery metadata.
- `src/web_scraping_fetcher/` — implementation.
- `tests/` — fetch behavior and transport contract tests.
- `skills/fetcher/SKILL.md` — AI-agent usage guidance.
