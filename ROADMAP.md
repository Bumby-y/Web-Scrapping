# Project Roadmap

This document tracks direction and actionable work for the repository. It is
an evolving plan, not a commitment to dates. Mark a task complete only after
the relevant implementation, documentation, and validation are present.

## Direction

Create a set of small, independently installable Python packages for web
scraping, with clear interfaces and permissions. Make them usable directly by
people and composable by future scripts, orchestrators, and AI agents. Keep
each module's code, tests, documentation, metadata, and AI skill together.
Keep core behavior decoupled from replaceable infrastructure so modules can be
composed repeatedly across local and cloud solutions.

## Current baseline

- [x] Create independent package scaffolds for Fetcher, Crawler, and HTML
  Parser.
- [x] Add per-module packaging metadata, discovery manifests, tests, and
  purpose documentation.
- [x] Add module-local AI skill scaffolds.
- [x] Document the distinction between runtime workflows and GitHub Actions.
- [ ] Implement production-ready runtime APIs; all three modules are currently
  scaffolds.
- [ ] Choose an orchestrator, skill discovery convention, and distribution
  channel.
- [ ] Define and validate small adapter contracts before claiming storage or
  deployment independence.

## Priorities

### 1. Define shared module conventions

- [ ] Decide and document supported Python versions and package versioning.
- [ ] Define a lightweight module contract: public API documentation, install
  instructions, inputs/outputs, errors, permissions, and compatibility.
- [ ] Define how core code receives replaceable collaborators, such as network
  transport or persistence, without tying the contract to a vendor SDK.
- [ ] Separate crawl-state requirements from page-content storage requirements
  before choosing persistence interfaces or providers.
- [ ] Decide the minimum supported local storage behavior and its consistency
  limits; do not assume it also supports concurrent cloud workers.
- [ ] Define the supported `module.json` schema and a validation approach, or
  remove the manifest if no discovery consumer needs it.
- [ ] Document how local modules are installed and tested without making the
  repository root a required runtime dependency.
- [ ] Add reusable adapter contract tests and verify core behavior with
  deterministic fakes or in-memory implementations.

### 2. Implement the Fetcher

- [ ] Agree on the minimal public API and supported request behavior.
- [ ] Implement timeouts, response/error handling, and safe defaults.
- [ ] Make destination scope and request headers/options explicit; avoid
  restriction-bypassing behavior.
- [ ] Add deterministic unit tests using mocks or controlled local fixtures.
- [ ] Update the README, manifest, examples, and skill to match the real API.

### 3. Implement the HTML Parser

- [ ] Agree on supported HTML inputs and the shape of parsed outputs.
- [ ] Choose and justify parsing dependencies, if any.
- [ ] Implement parsing without fetching remote resources or executing scripts.
- [ ] Add representative fixture-based tests, including malformed HTML cases.
- [ ] Update the README, manifest, examples, and skill to match the real API.

### 4. Implement the Crawler

- [x] Document the crawler's goals, ownership boundaries, non-goals, and
  intended initial implementation scope.
- [ ] Define crawl inputs, outputs, scope, limits, and stopping behavior as a
  public API contract.
- [ ] Implement deterministic frontier and visited-URL coordination without
  requiring network access or durable storage.
- [ ] Define narrow persistence contracts for crawl state and, if needed,
  content references; keep backend selection outside crawl policy.
- [ ] Define retrieval and link-discovery collaborator contracts without
  embedding HTTP transport or HTML parsing into crawl coordination.
- [ ] Decide how URL normalization, duplicate tracking, and robots directives
  are handled.
- [ ] Keep network access, rate limits, and crawl bounds explicit.
- [ ] Compose with Fetcher and Parser through public interfaces, or keep those
  integrations optional.
- [ ] Add deterministic tests for scheduling and limits without relying on
  public websites.
- [ ] Update the README, manifest, examples, and skill to match the real API.

### 5. Add shared quality checks

- [ ] Add a documented local command for testing all modules.
- [ ] Add CI for module tests and metadata validation.
- [ ] Add formatting, linting, and type checking if the project adopts and
  configures those tools.
- [ ] Ensure test and validation jobs do not require live scraping or secrets.

### 6. Prepare integration and distribution

- [ ] Select the target orchestrator(s) and their skill discovery format.
- [ ] Add platform adapters or an index only after selecting the discovery
  requirements; avoid maintaining duplicate skill sources unnecessarily.
- [ ] Add cross-module examples and runtime workflow definitions under
  `workflows/` once public module APIs exist.
- [ ] Choose a public distribution approach and release/version policy for
  individual modules.
- [ ] Document installation by module and pinning a specific release.
- [ ] Add local and cloud storage adapters only after their operational
  requirements and shared contracts are defined; keep provider integrations
  optional and independently installable.

## Completion criteria

A module is ready for public use when it has a documented and stable public
interface, independent installation, meaningful automated tests, declared
dependencies and permissions, an accurate AI skill, and a versioned release
process. Do not describe a scaffold as functional before those criteria are
met.
