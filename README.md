# Web-Scrapping

An evolving collection of small, reusable web-scraping tools. The goal is to
make each tool independently understandable, testable, installable, and usable
by people, scripts, and AI-assisted workflows.

> **Project status:** this repository currently contains package scaffolds and
> documentation. The Fetcher, Crawler, and HTML Parser do not yet provide
> implemented runtime functionality.

## Start here

- **People:** use this README for the project overview and development layout.
- **Contributors:** read [CONTRIBUTING.md](./CONTRIBUTING.md) before making a
  change.
- **AI assistants and automation:** read [AI_README.md](./AI_README.md) before
  exploring or changing the repository.
- **Project direction and planned work:** see [ROADMAP.md](./ROADMAP.md).

## Modules

| Module | Responsibility | Current status |
| --- | --- | --- |
| [Fetcher](./modules/fetcher/) | Retrieve individual web resources over HTTP. | Scaffold |
| [Crawler](./modules/crawler/) | Coordinate traversal across permitted pages. | Scaffold |
| [HTML Parser](./modules/html-parser/) | Extract structured information from HTML. | Scaffold |

Each module is intended to be an independently packaged Python project with
its own `pyproject.toml`, source package, tests, documentation, discovery
manifest, and AI skill. Keep module-specific dependencies local so users can
install only what they need.

## Design for reuse

Modules should depend on small, documented interfaces rather than a particular
application, orchestrator, network client, or storage provider. Keep core
behavior separate from replaceable adapters so the same module can be composed
in different solutions and run locally or on cloud infrastructure.

For example, crawl coordination should not assume that state lives in a local
file or that page content is stored in one particular service. Local and cloud
implementations can be added behind the same contract when there is a concrete
need. This is a design goal, not an implemented capability yet. See
[docs/ARCHITECTURE.md](./docs/ARCHITECTURE.md) for the principles and
[ROADMAP.md](./ROADMAP.md) for planned work.

## Repository layout

```text
modules/                       Independently packaged Python tools
  <module>/
    src/                       Importable Python package
    tests/                     Module tests
    skills/<module>/SKILL.md   AI instructions for using that module
    README.md                  Module purpose, setup, and public API
    module.json                Machine-readable discovery metadata
    pyproject.toml             Python packaging and dependencies
workflows/                     Runtime workflows that compose modules
examples/                      Runnable demonstrations
docs/                          Shared architecture and contribution guidance
scripts/                       Repository maintenance helpers
.github/workflows/             GitHub Actions for checks and publishing
AI_README.md                   AI-oriented repository context
ROADMAP.md                     Tracked project direction and planned work
```

`workflows/` and `.github/workflows/` serve different purposes: the former is
for workflows executed by a future application or orchestrator; the latter is
for automating repository tasks such as testing and publishing.

## Development

Use Python 3.9 or newer. From a module directory, install its development
dependencies and run its tests:

```powershell
python -m pip install -e ".[dev]"
python -m pytest
```

For example:

```powershell
cd modules/fetcher
python -m pip install -e ".[dev]"
python -m pytest
```

The test setup is module-local by design. As shared tooling is introduced,
repository-wide checks can be added under `.github/workflows/`.

## Contributing a module

1. Give the module one clear responsibility and an independently installable
   Python package.
2. Document its purpose, setup, public interface, dependencies, and permissions
   in its README and `module.json`.
3. Add focused tests and examples for implemented behavior.
4. Add or update `skills/<module>/SKILL.md` with accurate instructions for AI
   agents. Keep executable logic in Python, not in the skill.
5. Update the module list and [ROADMAP.md](./ROADMAP.md) when project status or
   priorities change.

Prefer explicit interfaces, pinned or bounded dependencies, and documented
network behavior. Respect site terms, robots directives, rate limits, access
controls, and user authorization when building or running scraping tools.

## Documentation map

- [AI_README.md](./AI_README.md) — repository context and guidance for AI tools.
- [CONTRIBUTING.md](./CONTRIBUTING.md) — setup and contribution guidelines.
- [ROADMAP.md](./ROADMAP.md) — current status, priorities, and completion
  checklist.
- [docs/ARCHITECTURE.md](./docs/ARCHITECTURE.md) — reusable module and adapter
  design principles.
- [docs/README.md](./docs/README.md) — purpose of shared documentation.
- [modules/README.md](./modules/README.md) — conventions for module packages.
