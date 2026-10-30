---
name: crawler
description: Guidance for selecting and using the web-scraping crawler module.
---

# Crawler skill

## When to use

Use the Crawler when a task needs bounded traversal across explicitly permitted
pages, including frontier management, duplicate avoidance, and stopping at
caller-defined limits.

Use the Fetcher or another retrieval adapter for HTTP requests. Use the HTML
Parser or another link-discovery collaborator to extract candidate links. Keep
workflow orchestration and durable page-content storage in the calling
application unless a documented crawler API explicitly provides those
capabilities.

## Current status

This module is a scaffold. Do not assume it exposes a working crawler API.
Check the package README and implementation for the current supported interface
before proposing or executing code that depends on it.

## Scope and boundaries

The Crawler coordinates what to visit and when to stop. It does not own HTTP
transport, HTML parsing, application orchestration, cloud deployment, or a
specific storage provider. Do not couple the crawler to private APIs of other
modules.

## Safety and limits

Require an explicit authorized crawl scope and finite limits. Respect site
terms, robots directives, rate limits, and access controls. Validate
discovered URLs against scope, do not silently broaden to unrelated hosts, and
do not bypass restrictions. Keep network activity and retries bounded and
explicit.

For design decisions, follow the Crawler README and
`docs/ARCHITECTURE.md`. Treat local/cloud storage adapters as future
integrations, not existing functionality.
