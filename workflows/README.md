# Orchestrator workflows

Put reusable workflow definitions that coordinate one or more scraping
modules here. These are runtime workflows for an application or orchestrator,
not GitHub Actions.

Keep workflow files focused on composition and configuration; module behavior
belongs in the corresponding Python package. Document the expected orchestrator,
input/output contract, required module versions, and permissions for each
workflow. Because no orchestrator has been selected yet, add provider-specific
workflow formats only when that choice is made.

## Available workflows

- [Crawler CLI](crawler/README.md): run the bounded Scrapy crawler with
  optional Playwright rendering against configurable seed URLs.
