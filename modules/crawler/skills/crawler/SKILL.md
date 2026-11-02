---
name: crawler
description: Guidance for bounded traversal with the framework-independent web-scraping crawler core.
---

# Crawler skill

## When to use

Use the Crawler when a task needs deterministic, bounded traversal of explicitly
permitted HTTP(S) URLs. The core takes seeds, a `CrawlPolicy`, a retriever, and
a link discoverer, then returns traversal metadata.

## Current API

The package exports `CrawlPolicy`, `Crawler`, `CrawlResult`, `CrawlFailure`,
`RetrievalResult`, `Retriever`, `LinkDiscoverer`, and `LinkEdge`. See the
module README for the complete public contract and example.

The core has no runtime dependencies and does not make network requests or
retain response bodies. Callers inject the retrieval and link-discovery
collaborators. Keep those integrations at the composition boundary; do not
couple the crawler core to private APIs of Fetcher or HTML Parser.

## Scope, identity, and limits

- Require explicit allowed domains and finite page, depth, and elapsed-time
  limits.
- Match allowed host names exactly; subdomains require explicit authorization.
- Only HTTP(S) URLs are accepted. Relative links resolve against the final
  page URL. Scheme/host are lowercased, default ports and fragments are
  removed, and query strings and paths are preserved.
- An out-of-scope seed is an error. Invalid or out-of-scope discovered links
  are skipped. Out-of-scope redirects are returned as structured failures.
- Collaborators must enforce their own request timeouts; the core cannot
  interrupt a blocking collaborator. The crawler does not retry failures.

## Network and access safety

The core itself performs no network access and does not fetch or enforce
robots.txt. Any future network adapter must respect robots directives, site
terms, rate limits, and access controls; it must not attempt to bypass them.
Keep retries and throttling bounded and explicit. Use controlled local fixtures
for tests rather than public websites.

## Future integrations

Scrapy HTTP retrieval and Playwright rendering are not implemented. Keep
Playwright optional and per-request if introduced; ordinary HTTP should remain
the default. Check the module README and roadmap before relying on future
adapter behavior.
