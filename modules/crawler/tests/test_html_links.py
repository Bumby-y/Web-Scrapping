import runpy
from pathlib import Path

from web_scraping_crawler import (
    CrawlLinkReference,
    CrawlPolicy,
    CrawlResult,
    HTMLLinkDiscoverer,
)


def test_extracts_categorized_html_and_text_references():
    html = """
    <base href="https://example.com/catalog/">
    <a href="book.html" ping="https://outside.example/ping">Book</a>
    <a href="/files/guide.pdf">Download guide</a>
    <a href="/files/data" download>Download file</a>
    <img src="cover.jpg" srcset="small.jpg 1x, large.jpg 2x">
    <script src="/static/app.js"></script>
    <link rel="stylesheet" href="/static/site.css">
    <iframe src="https://outside.example/embed"></iframe>
    <form action="/search"><input type="image" src="/search.png"></form>
    <video poster="/poster.jpg"><source src="/movie.mp4"></video>
    <div style="background-image: url('/inline.png')"></div>
    <style>.hero { background: url("/hero.png"); }</style>
    <style>@import "/theme.css";</style>
    <meta property="og:image" content="https://outside.example/share.png">
    <p>More details at https://outside.example/story.</p>
    <script>const scriptUrl = "https://outside.example/script-text";</script>
    """

    references = list(HTMLLinkDiscoverer().discover_links(html))
    categorized = {(item.url, item.category, item.attribute) for item in references}

    assert ("book.html", "hyperlink", "href") in categorized
    assert ("https://outside.example/ping", "pingback", "ping") in categorized
    assert ("/files/guide.pdf", "file_link", "href") in categorized
    assert ("/files/data", "file_link", "href") in categorized
    assert ("cover.jpg", "image", "src") in categorized
    assert ("small.jpg", "image", "srcset") in categorized
    assert ("large.jpg", "image", "srcset") in categorized
    assert ("/static/app.js", "script_resource", "src") in categorized
    assert ("/static/site.css", "link_stylesheet", "href") in categorized
    assert ("https://outside.example/embed", "embedded_resource", "src") in categorized
    assert ("/search", "form_action", "action") in categorized
    assert ("/search.png", "image", "src") in categorized
    assert ("/poster.jpg", "image", "poster") in categorized
    assert ("/movie.mp4", "media_resource", "src") in categorized
    assert ("/inline.png", "css_resource", "style") in categorized
    assert ('"/hero.png"', "css_resource", "style") not in categorized
    assert ("/hero.png", "css_resource", "style") in categorized
    assert ("/theme.css", "css_resource", "style") in categorized
    assert ("https://outside.example/share.png", "meta_resource", "content") in categorized
    assert ("https://outside.example/story", "in_text", "text") in categorized
    assert (
        "https://outside.example/script-text",
        "script_reference",
        "script",
    ) in categorized
    assert all(item.base_url == "https://example.com/catalog/" for item in references)


def test_navigation_flags_are_limited_to_page_links_and_text_urls():
    references = list(
        HTMLLinkDiscoverer().discover_links(
            '<a href="/detail">detail</a><img src="/cover.png">'
            '<p>https://example.com/article</p>'
        )
    )

    assert [(item.category, item.follow) for item in references] == [
        ("hyperlink", True),
        ("image", False),
        ("in_text", True),
    ]


def test_crawl_result_serializer_includes_categorized_links():
    root = "https://example.com/"
    result = CrawlResult(
        visited_urls=(root,),
        successful_urls=(root,),
        failed_urls=(),
        discovered_urls=(),
        link_edges=(),
        out_of_scope_urls=("https://outside.example/image.png",),
        link_references=(
            CrawlLinkReference(
                source_url=root,
                target_url="https://outside.example/image.png",
                category="image",
                attribute="src",
                scope="out_of_scope",
                follow=False,
            ),
        ),
    )
    run_path = Path(__file__).resolve().parents[3] / "workflows" / "crawler" / "run.py"
    serializer = runpy.run_path(str(run_path))["_result_dict"]
    policy = CrawlPolicy(
        allowed_domains=("example.com",),
        max_pages=1,
        max_depth=0,
        max_elapsed_time=1,
    )

    serialized = serializer(result, policy)

    assert serialized["out_of_scope_urls"] == [
        "https://outside.example/image.png"
    ]
    assert serialized["link_references"] == [
        {
            "source_url": root,
            "target_url": "https://outside.example/image.png",
            "category": "image",
            "attribute": "src",
            "scope": "out_of_scope",
            "follow": False,
        }
    ]
