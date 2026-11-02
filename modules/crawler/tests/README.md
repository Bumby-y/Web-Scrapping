# Tests

The core tests cover public in-memory traversal behavior, URL identity, scope
checks, collaborators, failures, and finite limits using fakes. The optional
Scrapy adapter test uses a controlled local HTTP server to verify robots
handling, redirects, retries, and crawl bounds. Install the Scrapy extra to
run it:

```shell
python -m pip install -e ".[dev,scrapy]"
python -m pytest
```

Tests do not rely on public websites.
