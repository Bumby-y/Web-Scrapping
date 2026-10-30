# Architecture and Reuse Principles

This repository aims to provide small tools that can be used repeatedly in
different applications, workflows, and deployment environments. Modules
should be independently installable and composable without requiring a single
orchestrator, storage provider, or cloud vendor.

These are design goals. The current modules are scaffolds and do not yet
provide runtime APIs or storage adapters.

## Core principles

### Keep responsibilities focused

Each module owns a cohesive capability: fetching individual resources,
coordinating crawl traversal, or parsing already-available HTML. Avoid making a
module responsible for unrelated orchestration, persistence, or application
policy.

### Depend on contracts at replacement boundaries

Core algorithms should depend on small, explicit interfaces for collaborators
that callers may need to replace. Possible boundaries include network
transport, crawl-state persistence, content storage, and parsing. Define only
the operations the consumer needs; do not create a general-purpose plugin
framework before there are real implementations to support.

An application or workflow should be able to compose a module with a chosen
adapter. For example, crawl coordination could use a local state store in a
development setup and a shared database adapter in a cloud deployment without
changing crawl policy or URL scheduling.

### Keep implementation choices explicit

Do not make a local path, SQLite database, cloud object store, database vendor,
network client, or orchestration framework a hidden requirement of core
behavior. Pass configuration and adapters at clear composition boundaries.
Provider SDKs should be isolated from the core package and optional when
practical.

### Separate state from content

When persistence is introduced, distinguish structured operational state from
large response bodies and files:

- **Crawl state** may include jobs, the URL frontier, visited items, status,
  and limits. It needs well-defined consistency and concurrency behavior.
- **Fetched content** may include response bodies and metadata. Its size and
  retention needs may call for a different storage implementation.

These categories may use different backends. Do not force them into one storage
abstraction unless the actual operations and lifecycle are genuinely shared.
Store references and metadata deliberately; document serialization, retention,
and cleanup behavior.

## Local and cloud deployment

Aim for the same module contracts to work in both local and hosted deployment
compositions:

- Local development can use lightweight adapters, such as a local database or
  filesystem, when their semantics fit the use case.
- A cloud deployment can provide managed or shared adapters when durability,
  multiple workers, or scale require them.
- Durable data must not depend on ephemeral container storage.
- Do not assume a local-only database is suitable for concurrent cloud workers.
- Keep secrets out of source, manifests, and committed workflow definitions;
  use the deployment environment's secret/configuration facilities.

The project has not selected concrete local or cloud providers. Select them
when requirements exist, document their guarantees and limitations, and avoid
making a provider mandatory for users of unrelated modules.

## Interface and adapter expectations

When introducing an interchangeable adapter:

1. Define the consumer-facing contract in terms of required operations,
   inputs, outputs, errors, and consistency guarantees.
2. Keep the contract narrow and independent of a vendor SDK.
3. Inject the implementation through a public constructor, function parameter,
   or workflow composition point; avoid hidden global configuration.
4. Test core behavior using a deterministic fake or in-memory implementation.
5. Test each real adapter against the same contract where practical.
6. Document dependencies, configuration, permissions, and operational limits.

Do not treat a fake used in tests as a production adapter. Avoid promising
substitutability if implementations do not meet the same contract.

## Reuse across solutions

Keep package APIs stable, typed, and documented. Prefer returning ordinary
data structures or documented result types over leaking framework-specific
objects. Keep workflow orchestration outside focused modules, and make
cross-module integration rely on public APIs rather than private internals.

AI skills should guide an agent to the supported package API and explicitly
describe required permissions and limits. They are documentation, not a
substitute for runtime contracts, validation, or safety controls.

## Evolution

Start with the smallest implementation that solves a concrete use case. Add a
new abstraction when there is a demonstrated need for substitution, independent
testing, or cross-solution reuse. Update module documentation, skills, tests,
and [ROADMAP.md](../ROADMAP.md) when the architecture changes.
