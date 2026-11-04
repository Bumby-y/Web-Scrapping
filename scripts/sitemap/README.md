# Sitemap generator

Generate a standard XML sitemap and a Mermaid diagram from the JSON result
written by the crawler workflow. The sitemap includes only `successful_urls`;
the graph includes the crawler's `link_edges`. Add
`--include-external-links` to group out-of-scope destinations and out-of-scope
redirect destinations as external nodes that are not crawled. These are read
from `out_of_scope_urls` and redirect URLs in `failed_urls`, covering blocked
click navigations and redirects. This is disabled by default. The crawler
stores out-of-scope URLs without their source page, so the diagram lists these
in a separate subgraph rather than inventing edges. Older crawler results
without external destination fields remain supported.

The current crawler result stores out-of-scope destinations as a flat list, so
the graph cannot associate each external destination with its originating
page. External destinations are shown in a separate subgraph rather than
inventing source-to-destination edges.

From the repository root, run:

```shell
python scripts/sitemap/generate.py crawl-result.json
```

Include external destinations in the Mermaid graph when visualizing the
broader site:

```shell
python scripts/sitemap/generate.py crawl-result.json --include-external-links
```

By default this writes `sitemap.xml` and `sitemap.mmd` to the current
directory. Choose different paths with:

```shell
python scripts/sitemap/generate.py crawl-result.json \
  --output output/site-map.xml \
  --graph-output output/site-map.mmd
```

The XML generator rejects results with multiple successful hostnames instead
of silently omitting URLs. It also fails clearly if the sitemap exceeds the
standard 50,000-URL or 50 MB uncompressed limits; it does not split files.
Create one smaller, single-host crawler result per sitemap when necessary.

The Mermaid graph is a static diagram source; view it in a Mermaid-compatible
Markdown previewer or renderer. URLs are represented by generated node IDs and
encoded labels. No network access is performed by this script.
