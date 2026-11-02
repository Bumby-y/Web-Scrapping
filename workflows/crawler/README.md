# Crawler workflow

`run.py` is a standalone CLI for testing the crawler module against different
seed URLs. It uses the optional Scrapy adapter and extracts anchor links from
HTML. It does not execute page scripts or save response bodies.

## Install

From the repository root in PowerShell:

```powershell
python -m pip install -e "modules\crawler[scrapy]"
```

## Quick start

The seed URL is positional. Its exact host is automatically used as the
allowed crawl scope, so a basic run needs no required flags:

```shell
python workflows/crawler/run.py "https://example.com/catalog/"
```

The crawl results, including the discovered URL list, are saved to
`crawl-result.json` in your current terminal directory. The terminal prints
only a short count summary and the output path. The defaults are 10 pages,
depth 2, and 60 seconds. Use short flags to change them or choose another
output path:

```shell
python workflows/crawler/run.py "https://example.com/catalog/" -p 25 -d 3 -t 90 -o crawl-result.json
```

## Multiple seeds and hosts

Pass any number of seed URLs positionally. Each seed's exact host is allowed
automatically. Use `-a` / `--allow-domain` to additionally authorize hosts
that may appear in links but are not seed hosts.

```powershell
python workflows\crawler\run.py "https://example.com/catalog/" "https://example.com/news/" -p 25 -d 3
```

To allow links to a subdomain, authorize it explicitly:

```shell
python workflows/crawler/run.py "https://example.com/" -a shop.example.com
```

Host matching is exact. A seed on `example.com` does not implicitly authorize
`shop.example.com`.

## Limits and output

- `-p`, `--max-pages`: maximum number of unique scheduled pages (default: 10).
- `-d`, `--max-depth`: maximum link depth from each seed (default: 2).
- `-t`, `--max-seconds`: maximum crawl duration (default: 60).
- `-a`, `--allow-domain`: additionally authorize an exact host; repeat as
  needed.
- `-o`, `--output`: JSON output path (default: `crawl-result.json` in the
  current directory).

The JSON file includes visited and successful URLs, structured failures,
discovered URLs, and unique link edges. Scrapy's concurrent completion order
is not guaranteed to be deterministic.

Robots.txt compliance is always enabled. The adapter also uses a 15-second
request timeout, up to two retries, bounded concurrency, and AutoThrottle.
The workflow does not disable site restrictions or access controls. Use only
authorized sites and check the target's robots directives before crawling.

The CLI starts Scrapy's Twisted reactor. Run it as a standalone terminal
process; do not invoke multiple crawls by calling its helper repeatedly in one
process.
