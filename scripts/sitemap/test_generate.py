import xml.etree.ElementTree as ET

from generate import (
    SITEMAP_NAMESPACE,
    _read_result,
    _successful_urls,
    build_mermaid,
    build_sitemap,
)


def test_external_destinations_are_shown_separately_from_sitemap(tmp_path):
    crawler_result = {
        "successful_urls": ["https://example.com/"],
        "link_edges": [["https://example.com/", "https://example.com/about"]],
        "out_of_scope_urls": ["https://video.example/watch?id=123"],
    }

    graph = build_mermaid(crawler_result)
    sitemap = build_sitemap(_successful_urls(crawler_result))

    assert 'subgraph external["Out-of-scope destinations (not crawled)"]' in graph
    assert 'url2["https://video.example/watch?id=123"]' in graph
    assert "class url2 external" in graph
    assert "url0 --> url1" in graph
    sitemap_urls = [
        item.text
        for item in ET.fromstring(sitemap).findall(
            ".//{{{}}}loc".format(SITEMAP_NAMESPACE)
        )
    ]
    assert sitemap_urls == ["https://example.com/"]

    result_path = tmp_path / "crawler-result.json"
    result_path.write_text(
        '{"successful_urls": ["https://example.com/"], "link_edges": [], '
        '"out_of_scope_urls": ["https://video.example/"]}',
        encoding="utf-8",
    )
    assert _read_result(result_path)["out_of_scope_urls"] == [
        "https://video.example/"
    ]


def test_mermaid_supports_older_results_without_external_destinations():
    graph = build_mermaid(
        {
            "successful_urls": ["https://example.com/"],
            "link_edges": [],
        }
    )

    assert "Out-of-scope destinations" not in graph
    assert 'url0["https://example.com/"]' in graph
