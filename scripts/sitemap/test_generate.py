import xml.etree.ElementTree as ET

from generate import (
    SITEMAP_NAMESPACE,
    _read_result,
    _successful_urls,
    build_mermaid,
    build_sitemap,
    main,
)


def test_external_destinations_are_optional_and_not_in_sitemap(tmp_path):
    crawler_result = {
        "successful_urls": ["https://example.com/"],
        "link_edges": [["https://example.com/", "https://example.com/about"]],
        "out_of_scope_urls": ["https://video.example/watch?id=123"],
        "failed_urls": [
            {"redirect_url": "https://redirect.example/destination"}
        ],
    }

    graph_without_externals = build_mermaid(crawler_result)
    assert "Out-of-scope destinations" not in graph_without_externals

    graph = build_mermaid(crawler_result, include_external_links=True)
    sitemap = build_sitemap(_successful_urls(crawler_result))

    assert 'subgraph external["Out-of-scope destinations (not crawled)"]' in graph
    assert 'url2["https://video.example/watch?id=123"]' in graph
    assert 'url3["https://redirect.example/destination"]' in graph
    assert "class url2,url3 external" in graph
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


def test_cli_can_include_external_destinations_in_graph(tmp_path):
    result_path = tmp_path / "crawler-result.json"
    result_path.write_text(
        '{"successful_urls": ["https://example.com/"], "link_edges": [], '
        '"out_of_scope_urls": ["https://external.example/page"]}',
        encoding="utf-8",
    )
    graph_path = tmp_path / "site.mmd"

    assert main(
        [
            str(result_path),
            "--output",
            str(tmp_path / "site.xml"),
            "--graph-output",
            str(graph_path),
            "--include-external-links",
        ]
    ) == 0
    assert 'url1["https://external.example/page"]' in graph_path.read_text(
        encoding="utf-8"
    )
