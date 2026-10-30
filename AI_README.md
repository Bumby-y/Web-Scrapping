# AI Repository Guide

This document gives AI assistants and automated agents concise, repository-wide
context. Read it before proposing or making changes. Follow the relevant module
README and `skills/<module>/SKILL.md` as well.

## Mission

Build a collection of modular, publicly usable web-scraping tools that can be
installed independently and composed by scripts or future AI orchestrators.
Keep software behavior, package metadata, human documentation, and AI usage
instructions aligned and versioned together.

## Current state

- The repository is a Python monorepo with three independent module scaffolds:
  `fetcher`, `crawler`, and `html-parser`.
- Their package metadata and discovery manifests exist, but the runtime APIs
  have not been implemented.
- Current tests are package-import smoke tests, not feature tests.
- Module-local AI skills are scaffolds; they must not claim unsupported
  functionality.
- No orchestrator, workflow format, module registry, or publishing process has
  been selected yet. Do not introduce provider-specific conventions without a
  concrete requirement.
- Storage abstractions and interchangeable local/cloud adapters are design
  goals, not implemented capabilities. Do not claim storage independence until
  contracts, adapters, and tests exist.
- See [ROADMAP.md](./ROADMAP.md) for priorities and progress.

## Architecture and ownership

- `modules/<module>/src/<package>/` owns that module's executable Python code.
- `modules/<module>/tests/` owns tests for that module.
- `modules/<module>/pyproject.toml` owns package metadata and direct
  dependencies. Keep a module independently installable.
- `modules/<module>/module.json` is discovery metadata, not executable code.
  Keep it consistent with the package metadata; avoid adding fields without a
  clear consumer.
- `modules/<module>/skills/<module>/SKILL.md` teaches an AI agent when and how
  to use that module. Keep it accurate to the implemented API and do not
  duplicate runtime logic there.
- `modules/<module>/README.md` is the module's human-facing usage and API
  documentation.
- Core behavior should depend on small, stable interfaces. Provider-specific
  behavior belongs in replaceable adapters, not in core algorithms.
- Keep storage and network implementation choices configurable at composition
  boundaries. Do not make a local path, database, cloud SDK, or orchestrator a
  hidden requirement of a reusable module.
- Do not add abstraction layers without a real use case. Define the operations
  consumers need, implement a simple first adapter, and test the core against
  the interface.
- `workflows/` is reserved for runtime workflows that compose modules.
- `.github/workflows/` is reserved for GitHub Actions automation.
- `examples/` contains demonstrations; `scripts/` contains repository tooling;
  `docs/` contains guidance shared across modules.

## Module boundaries

- **Fetcher:** retrieval of individual web resources. Do not turn it into the
  crawler or HTML extraction layer.
- **Crawler:** coordination of bounded traversal: seeds, scope, frontier,
  duplicate tracking, and stopping conditions. Delegate HTTP transport to a
  retriever and HTML/link interpretation to a parser or link-discovery
  collaborator. Keep application orchestration, durable content storage, and
  infrastructure selection outside the core crawler. Keep limits and network
  permissions explicit.
- **HTML Parser:** parsing already-available HTML into structured data. Do not
  fetch pages or execute page scripts as part of parsing.

These are intended responsibilities, not implemented guarantees. Inspect code
and tests before relying on an API. Avoid adding cross-module dependencies
unless a requirement justifies them and the dependency is documented.

See [docs/ARCHITECTURE.md](./docs/ARCHITECTURE.md) for the repository's
abstraction, adapter, and storage-independence goals.

## Change guidelines

1. Inspect the target module and its existing patterns before editing.
2. Make focused changes that preserve independent packaging and module
   boundaries.
3. Add or update tests for behavior changes; do not rely on import-only tests
   when implementing features.
4. Update the module README, manifest, and skill when the public interface,
   dependencies, permissions, or supported behavior changes.
5. Keep examples executable and aligned with the actual public API.
6. Run the smallest relevant test command, then report any missing tools or
   unverified checks explicitly.
7. Update [ROADMAP.md](./ROADMAP.md) when a planned item is completed, deferred,
   or materially reprioritized.
8. When adding an adapter, test the core behavior against its contract and
   keep provider-specific dependencies optional where practical.

## Safety and reliability

- Treat HTML, URLs, responses, and downloaded content as untrusted input.
- Do not bypass authentication, access controls, CAPTCHAs, rate limits, or
  other restrictions.
- Make network permissions and target scope explicit; respect site terms,
  robots directives, and user authorization.
- Avoid live network calls in unit tests; use fixtures, mocks, or controlled
  local test servers.
- Do not add credentials, scraped personal data, or generated downloads to the
  repository.
- Surface failures clearly. Do not silently return success-shaped fallback
  values when an operation fails.

## Unknowns to resolve deliberately

Before adding platform-specific integrations or publishing automation, clarify
the target orchestrator(s), skill discovery format, distribution channel,
versioning policy, supported Python versions, and intended deployment targets.
Until then, favor portable Python packaging and plain documented interfaces.
