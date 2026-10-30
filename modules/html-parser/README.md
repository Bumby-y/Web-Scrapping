# HTML Parser

Parses supplied HTML into structured information. It is an independently
packaged Python module and processes content already available to the caller.

> **Status:** scaffold; no runtime API is implemented. This README describes
> intended scope, not available behavior.

## Owns

- Accept HTML through a documented input API.
- Provide focused extraction operations with stable, documented outputs.
- Define input, encoding, malformed-document, and error behavior.
- Optionally discover links if that capability is explicitly part of the API.

## Does not own

- Fetching resources, decoding HTTP responses, or network errors: use the
  Fetcher or caller code.
- Crawl scope, scheduling, frontier state, or stopping conditions: use the
  Crawler or calling application.
- Application-specific schemas, orchestration, or durable storage.
- Executing scripts, evaluating embedded code, or loading remote resources.

## Boundaries

- Treat HTML as untrusted input. Parsing must not execute page code or make
  network requests; keep the module's network permission disabled.
- Document whether inputs are text, bytes, or both; define encoding behavior,
  document/fragment support, output types, and errors.
- Return stable data structures rather than parser-library objects unless
  explicitly documented. Do not claim extracted content is trustworthy.
- Choose a parsing dependency only when requirements justify it; isolate its
  objects and behavior behind the public API.
- If link discovery is supported, return predictable candidates without
  fetching them or deciding crawl scope.
- Test with local fixtures, including malformed HTML and supported edge cases.

## Initial implementation

Parse supplied HTML and provide concrete, deterministic extraction
operations. Do not fetch pages, execute scripts, load remote resources,
coordinate crawls, or persist results. Avoid generic selector frameworks or
application-specific pipelines without a demonstrated need.

Update this README, `module.json`, and the AI skill whenever public behavior
changes. Follow [`docs/ARCHITECTURE.md`](../../docs/ARCHITECTURE.md) for shared
design principles.

## Related files

- `pyproject.toml` — package metadata and dependencies.
- `module.json` — discovery metadata.
- `src/web_scraping_html_parser/` — implementation.
- `tests/` — parsing behavior and fixture-based tests.
- `skills/html-parser/SKILL.md` — AI-agent usage guidance.
