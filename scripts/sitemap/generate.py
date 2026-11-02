"""Generate a standard XML sitemap and Mermaid graph from crawler JSON."""

from __future__ import annotations

import argparse
import json
import sys
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any, Optional, Sequence
from urllib.parse import quote, urlsplit

SITEMAP_NAMESPACE = "http://www.sitemaps.org/schemas/sitemap/0.9"
MAX_SITEMAP_URLS = 50_000
MAX_SITEMAP_BYTES = 50 * 1024 * 1024


def _read_result(path: Path) -> dict[str, Any]:
    try:
        with path.open(encoding="utf-8") as result_file:
            data = json.load(result_file)
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError("could not read crawler result JSON: {}".format(exc)) from exc

    if not isinstance(data, dict):
        raise ValueError("crawler result must be a JSON object")
    for key in ("successful_urls", "link_edges"):
        if not isinstance(data.get(key), list):
            raise ValueError(
                "crawler result must contain a '{}' list".format(key)
            )
    return data


def _validated_url(value: Any, source: str) -> str:
    if not isinstance(value, str) or not value or value != value.strip():
        raise ValueError("{} contains a non-empty URL string requirement".format(source))
    try:
        parsed = urlsplit(value)
        _ = parsed.port
    except ValueError as exc:
        raise ValueError("{} contains an invalid URL: {}".format(source, value)) from exc
    if (
        parsed.scheme.lower() not in ("http", "https")
        or parsed.hostname is None
        or parsed.username is not None
        or parsed.password is not None
    ):
        raise ValueError(
            "{} contains a URL that is not an absolute HTTP(S) URL: {}".format(
                source, value
            )
        )
    return value


def _successful_urls(result: dict[str, Any]) -> list[str]:
    urls = []
    seen = set()
    for value in result["successful_urls"]:
        url = _validated_url(value, "successful_urls")
        if url not in seen:
            seen.add(url)
            urls.append(url)

    if len(urls) > MAX_SITEMAP_URLS:
        raise ValueError(
            "sitemap has {} successful URLs; the maximum per sitemap is {}. "
            "Use a smaller crawl result.".format(len(urls), MAX_SITEMAP_URLS)
        )

    hosts = {urlsplit(url).hostname.lower() for url in urls}
    if len(hosts) > 1:
        raise ValueError(
            "successful_urls contains multiple hosts ({}); generate one sitemap "
            "per host.".format(", ".join(sorted(hosts)))
        )
    return urls


def build_sitemap(urls: Sequence[str]) -> bytes:
    """Build a UTF-8 sitemap XML document from a single-host URL collection."""
    root = ET.Element(
        "{{{}}}urlset".format(SITEMAP_NAMESPACE),
    )
    for url in urls:
        entry = ET.SubElement(root, "{{{}}}url".format(SITEMAP_NAMESPACE))
        ET.SubElement(entry, "{{{}}}loc".format(SITEMAP_NAMESPACE)).text = url
    ET.indent(root, space="  ")
    document = ET.tostring(
        root,
        encoding="utf-8",
        xml_declaration=True,
    )
    if len(document) > MAX_SITEMAP_BYTES:
        raise ValueError(
            "sitemap XML exceeds the 50 MB uncompressed limit; use a smaller crawl result"
        )
    return document


def build_mermaid(result: dict[str, Any]) -> str:
    """Build a Mermaid flowchart with stable node IDs and safely encoded labels."""
    successful = [
        _validated_url(value, "successful_urls")
        for value in result["successful_urls"]
    ]
    edges = []
    for index, edge in enumerate(result["link_edges"]):
        if not isinstance(edge, list) or len(edge) != 2:
            raise ValueError(
                "link_edges[{}] must be a two-element URL list".format(index)
            )
        source = _validated_url(edge[0], "link_edges")
        target = _validated_url(edge[1], "link_edges")
        edges.append((source, target))

    urls = list(dict.fromkeys(successful))
    for source, target in edges:
        if source not in urls:
            urls.append(source)
        if target not in urls:
            urls.append(target)
    node_ids = {url: "url{}".format(index) for index, url in enumerate(urls)}

    lines = ["flowchart TD"]
    for url, node_id in node_ids.items():
        label = quote(url, safe=":/?#=%-._~")
        lines.append('  {}["{}"]'.format(node_id, label))
    for source, target in edges:
        lines.append("  {} --> {}".format(node_ids[source], node_ids[target]))
    return "\n".join(lines) + "\n"


def build_argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Generate a single-host sitemap.xml and a Mermaid link graph from "
            "a crawler result JSON file."
        )
    )
    parser.add_argument("crawler_result", type=Path, help="Crawler result JSON path.")
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        default=Path("sitemap.xml"),
        help="XML sitemap output path (default: sitemap.xml).",
    )
    parser.add_argument(
        "--graph-output",
        type=Path,
        default=Path("sitemap.mmd"),
        help="Mermaid graph output path (default: sitemap.mmd).",
    )
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = build_argument_parser()
    args = parser.parse_args(argv)
    try:
        result = _read_result(args.crawler_result)
        urls = _successful_urls(result)
        sitemap = build_sitemap(urls)
        graph = build_mermaid(result)
        if args.output.resolve() == args.graph_output.resolve():
            raise ValueError("sitemap and graph outputs must use different file paths")
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.graph_output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_bytes(sitemap)
        args.graph_output.write_text(graph, encoding="utf-8")
    except (OSError, ValueError) as exc:
        parser.error(str(exc))

    print(
        "Generated {} ({} URLs) and {}".format(
            args.output,
            len(urls),
            args.graph_output,
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
