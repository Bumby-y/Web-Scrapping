# `web_scraping_crawler`

The package exports the framework-independent `CrawlPolicy`, `Crawler`,
`CrawlResult`, collaborator protocols, structured failure/result types, and
the optional `crawl_with_scrapy` helper. Scrapy is imported only when that
helper is called. See the [Crawler module README](../../README.md) for the
public contract and usage examples.
