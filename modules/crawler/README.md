# Crawler

The Crawler is an independently packaged Python module for coordinating a
bounded traversal of permitted web pages. Its purpose is to decide **what to
visit next and when to stop**, while letting callers choose how pages are
retrieved, parsed, stored, and deployed.

> **Status:** scaffold. The crawler has no implemented runtime API yet. This
document defines the intended goals and boundaries; it is not a description of
currently available behavior.

## Goals

- Accept an explicit starting set and crawl scope from the caller.
- Maintain a frontier of discovered URLs and track URLs already scheduled or
  visited so work is not needlessly repeated.
- Apply explicit crawl limits and stopping conditions, such as maximum pages
  and depth.
- Coordinate collaborators through small public interfaces rather than
  depending on their implementation details.
- Return clear crawl results and failures so an application can decide what to
  do with them.
- Remain usable in different applications and local or cloud deployments
  without requiring one orchestrator, HTTP client, or storage provider.

## Owns

The Crawler is responsible for crawl coordination:

- Managing crawl inputs, frontier state, and traversal order.
- Tracking discovered, scheduled, completed, and failed URLs for a crawl.
- Applying caller-provided scope and bounded crawl policies.
- Coordinating retrieval and link discovery through injected collaborators.
- Defining when a crawl completes, reaches a limit, or reports an error.

These responsibilities should be exposed through a documented API. The Crawler
should not require callers to use a particular workflow framework.

## Does not own

- **HTTP behavior:** The Fetcher (or a caller-provided retrieval adapter)
  performs requests and owns transport details such as timeouts, response
  decoding, and request errors.
- **HTML interpretation:** The HTML Parser or a link-discovery collaborator
  extracts links from retrieved content. The Crawler should not contain a
  second, hidden HTML parsing implementation.
- **Application orchestration:** A caller or runtime workflow starts jobs,
  schedules them across processes, handles user interaction, and combines
  modules.
- **Durable page-content storage:** A caller decides whether and where to keep
  response bodies. The crawler should return content or explicit references
  according to its contract, not silently persist it.
- **Infrastructure selection:** The caller supplies any required state store,
  network adapter, or other integration. Core crawl policy must not assume a
  filesystem path, database vendor, cloud provider, or deployment platform.
- **Access-policy override:** The crawler must not bypass authentication,
  access controls, CAPTCHAs, robots directives, rate limits, or other
  restrictions.

## Safety and resource boundaries

Every crawl should have an explicit scope and finite resource limits. The
eventual API should make relevant limits visible, including page count, depth,
request rate or concurrency, and elapsed time where supported. Safe defaults
should prevent an unbounded crawl.

Only crawl resources the user is authorized to access. Respect site terms,
robots directives, rate limits, and access controls. Validate discovered URLs
against the caller's scope before scheduling them, including after redirects
when redirect information is available from the retrieval adapter. Do not
silently expand scope to unrelated hosts.

Network access, retry behavior, and error handling should be explicit and
bounded. The crawler must not disguise failed requests as successful results.
Unit tests should use fakes, fixtures, or controlled local servers rather than
public websites.

## Collaboration and storage design

Keep the core scheduler independent of concrete implementations. Introduce
narrow interfaces only for collaborators that the crawler needs, such as:

- A page retriever that accepts a URL and returns a documented result.
- A link discoverer that accepts retrieved content and returns candidate URLs.
- A crawl-state store if state must persist across runs or workers.

The crawler should be testable with an in-memory or fake implementation of
these contracts. Local and cloud adapters can be added separately when there
is a concrete use case; they must meet the same documented contract. Crawl
state and page-content storage are separate concerns and need not share one
backend.

Do not add all of these interfaces speculatively. Start with the smallest
contract required by an implemented use case, and keep provider-specific
dependencies optional where practical. See
[`docs/ARCHITECTURE.md`](../../docs/ARCHITECTURE.md) for shared design
principles.

## Initial implementation boundary

The first implementation should focus on bounded, deterministic crawl
coordination: explicit seeds and scope, frontier management, duplicate
avoidance, depth/page stopping conditions, and structured outcomes. It should
not require distributed workers, durable storage, or a specific HTTP or HTML
library in order to test the core behavior.

Before adding those integrations, define their contracts and add adapter
conformance tests. Update this document, `module.json`, and the AI skill when
the public behavior changes.

## Related files

- `pyproject.toml` — package metadata and dependencies.
- `module.json` — machine-readable module discovery metadata.
- `src/web_scraping_crawler/` — Python implementation.
- `tests/` — crawler behavior and adapter contract tests.
- `skills/crawler/SKILL.md` — AI-agent guidance for selecting and using the
  module.
