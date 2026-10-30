# Contributing

Thank you for helping improve Web-Scrapping. The project is currently at an
early scaffold stage: the Fetcher, Crawler, and HTML Parser packages do not yet
provide implemented runtime functionality. Contributions can help establish
clear interfaces, dependable behavior, and useful documentation.

## Before you start

- Read the [project README](./README.md) for the repository layout and setup.
- Read [AI_README.md](./AI_README.md) for architecture, module boundaries, and
  repository-wide expectations.
- Check [ROADMAP.md](./ROADMAP.md) to understand planned work and current
  priorities.
- For a large change or a new dependency, open an issue or discussion first so
  the intended behavior can be agreed on before implementation.

## Development setup

Use Python 3.9 or newer. Each module is an independent Python project. From
the module directory you are working on, install its development dependencies
and run its tests:

```powershell
cd modules/fetcher
python -m pip install -e ".[dev]"
python -m pytest
```

Replace `fetcher` with `crawler` or `html-parser` as appropriate. Do not install
or add dependencies to unrelated modules unless the change requires it.

## Contribution guidelines

- Keep changes focused and preserve independent installation of each module.
- Give each module one clear responsibility. Use its documented public
  interface rather than reaching into another module's internal implementation.
- Prefer small, explicit APIs with documented inputs, outputs, errors, and
  permissions.
- Keep core logic independent of application frameworks, storage backends, and
  cloud vendors. Introduce an interface at a real replacement or composition
  boundary, not as speculative indirection.
- Where a behavior has interchangeable implementations, test the consumer
  against the shared contract and test each adapter's conformance separately.
- Keep provider-specific SDKs and credentials out of the core package; make
  backend selection and configuration explicit.
- Add tests for behavior changes. Use fixtures, mocks, or controlled local
  servers rather than live websites.
- Keep examples runnable and aligned with the actual public API.
- Avoid adding framework-specific orchestrator support until the project
  selects an orchestrator and its integration requirements.
- Do not add credentials, scraped personal data, generated downloads, or
  unnecessary binary files to the repository.

## Updating module documentation

When changing a module's behavior, update the relevant files together:

- `modules/<module>/README.md` for human setup, usage, and API documentation.
- `modules/<module>/module.json` for machine-readable discovery metadata.
- `modules/<module>/skills/<module>/SKILL.md` for accurate AI-agent guidance.
- Tests and examples for the implemented behavior.

Keep the skill instructional rather than executable: it should explain when
and how to use the supported package API, not duplicate its implementation.
Do not describe scaffold behavior as implemented.

If a change affects project status or priorities, update [ROADMAP.md](./ROADMAP.md).
If it changes shared conventions or module boundaries, update [AI_README.md](./AI_README.md)
and relevant shared documentation as well.

For abstraction and storage design, follow
[docs/ARCHITECTURE.md](./docs/ARCHITECTURE.md). Storage independence is a goal;
do not document or advertise it as supported until the relevant adapters and
tests are implemented.

## Responsible web access

Web scraping must be limited to resources the user is authorized to access.
Respect site terms, robots directives, rate limits, authentication, and access
controls. Do not add features intended to bypass restrictions. Make network
destinations, crawl scope, and limits explicit, and document network-related
permissions.

Parser code should treat HTML and URLs as untrusted input. Avoid executing page
scripts or fetching remote resources as a side effect of parsing.

## Pull requests

Before submitting a pull request:

1. Run the tests for every module affected by the change.
2. Review the diff for unrelated edits, generated files, secrets, and
   inconsistent documentation.
3. Ensure any new dependencies are declared in the relevant module's
   `pyproject.toml`.
4. Describe the problem, the solution, and how the change was validated.
5. Call out limitations or checks you could not run.

Keep pull requests focused and state whether the change alters a public
interface, dependency set, permission, or module behavior.
