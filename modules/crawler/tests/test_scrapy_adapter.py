from html.parser import HTMLParser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread

import pytest

pytest.importorskip("scrapy")

from web_scraping_crawler import (
    CrawlPolicy,
    HTMLLinkDiscoverer,
    crawl_with_scrapy,
)


class LinkParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.links = []

    def handle_starttag(self, tag, attrs):
        if tag == "a":
            self.links.extend(value for name, value in attrs if name == "href")


class HtmlLinkDiscoverer:
    def discover_links(self, content):
        parser = LinkParser()
        parser.feed(content)
        return parser.links


def test_scrapy_adapter_honors_scope_robots_retries_and_page_limits():
    request_counts = {}

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            request_counts[self.path] = request_counts.get(self.path, 0) + 1
            if self.path == "/robots.txt":
                self._respond(
                    200,
                    b"User-agent: *\nDisallow: /robots-blocked\n",
                    "text/plain",
                )
                return
            if self.path == "/":
                links = (
                    "/ok",
                    "/ok#duplicate",
                    "/query?x=1",
                    "/query?x=2",
                    "/redirect-out",
                    "/robots-blocked",
                    "/retry",
                    "/redirect-in",
                    "/extra",
                    "/beyond",
                )
                body = "".join(
                    '<a href="{}">link</a>'.format(link) for link in links
                ) + (
                    '<img src="https://outside.example/assets/cover.png">'
                    '<p>Read https://outside.example/article</p>'
                )
                self._respond(200, body.encode("utf-8"))
                return
            if self.path == "/redirect-out":
                self.send_response(302)
                self.send_header(
                    "Location",
                    "http://localhost:{}/external".format(self.server.server_port),
                )
                self.end_headers()
                return
            if self.path == "/redirect-in":
                self.send_response(302)
                self.send_header("Location", "/final")
                self.end_headers()
                return
            if self.path == "/ok":
                self._respond(
                    200,
                    b'<a href="/depth-excess">deeper</a>',
                )
                return
            if self.path == "/retry":
                self._respond(503, b"temporarily unavailable")
                return
            self._respond(200, b"ok")

        def _respond(self, status, body, content_type="text/html; charset=utf-8"):
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format_string, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    root = "http://127.0.0.1:{}/".format(server.server_port)

    try:
        result = crawl_with_scrapy(
            [root],
            CrawlPolicy(
                allowed_domains=("127.0.0.1",),
                max_pages=9,
                max_depth=1,
                max_elapsed_time=30,
            ),
            HTMLLinkDiscoverer(),
        )
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)

    assert {
        (reference.category, reference.scope)
        for reference in result.link_references
    } >= {
        ("hyperlink", "in_scope"),
        ("image", "out_of_scope"),
        ("in_text", "out_of_scope"),
        ("redirect", "out_of_scope"),
    }
    assert {
        "https://outside.example/assets/cover.png",
        "https://outside.example/article",
        "http://localhost:{}/external".format(server.server_port),
    } <= set(result.out_of_scope_urls)

    assert request_counts["/robots.txt"] >= 1
    assert request_counts.get("/robots-blocked", 0) == 0
    assert request_counts.get("/external", 0) == 0
    assert request_counts.get("/beyond", 0) == 0
    assert request_counts.get("/depth-excess", 0) == 0
    assert request_counts.get("/ok", 0) == 1
    assert request_counts.get("/query?x=1", 0) == 1
    assert request_counts.get("/query?x=2", 0) == 1
    assert request_counts["/retry"] == 3

    assert root in result.visited_urls
    assert len(result.visited_urls) <= 9
    assert root in result.successful_urls
    assert "http://127.0.0.1:{}/redirect-in".format(server.server_port) in (
        result.successful_urls
    )
    assert request_counts.get("/final", 0) == 1
    assert "http://127.0.0.1:{}/beyond".format(server.server_port) in (
        result.discovered_urls
    )
    assert "http://127.0.0.1:{}/depth-excess".format(server.server_port) in (
        result.discovered_urls
    )
    assert {
        failure.stage for failure in result.failed_urls
    } >= {"redirect", "retrieve"}
    assert any(
        failure.stage == "redirect"
        and failure.redirect_url
        and failure.redirect_url.startswith("http://localhost:")
        for failure in result.failed_urls
    )


@pytest.mark.parametrize(
    ("render_javascript", "render_wait_for"),
    [
        ("yes", None),
        (False, ""),
        (False, "#app"),
    ],
)
def test_scrapy_adapter_rejects_invalid_render_options(
    render_javascript, render_wait_for
):
    with pytest.raises(ValueError):
        crawl_with_scrapy(
            [],
            CrawlPolicy(
                allowed_domains=("example.com",),
                max_pages=1,
                max_depth=0,
                max_elapsed_time=1,
            ),
            HtmlLinkDiscoverer(),
            render_javascript=render_javascript,
            render_wait_for=render_wait_for,
        )


@pytest.mark.parametrize(
    ("render_javascript", "load_more_selectors", "max_load_more_clicks"),
    [
        (False, (".section-more-btn",), 20),
        (True, ".section-more-btn", 20),
        (True, (".section-more-btn",), 0),
        (True, (".section-more-btn",), True),
    ],
)
def test_scrapy_adapter_rejects_invalid_load_more_options(
    render_javascript, load_more_selectors, max_load_more_clicks
):
    with pytest.raises(ValueError):
        crawl_with_scrapy(
            [],
            CrawlPolicy(
                allowed_domains=("example.com",),
                max_pages=1,
                max_depth=0,
                max_elapsed_time=1,
            ),
            HtmlLinkDiscoverer(),
            render_javascript=render_javascript,
            load_more_selectors=load_more_selectors,
            max_load_more_clicks=max_load_more_clicks,
        )


@pytest.mark.parametrize(
    ("render_javascript", "index_click_workers"),
    [
        (False, 2),
        (True, 0),
        (True, -1),
        (True, True),
    ],
)
def test_scrapy_adapter_rejects_invalid_index_click_worker_options(
    render_javascript, index_click_workers
):
    with pytest.raises(ValueError):
        crawl_with_scrapy(
            [],
            CrawlPolicy(
                allowed_domains=("example.com",),
                max_pages=1,
                max_depth=0,
                max_elapsed_time=1,
            ),
            HtmlLinkDiscoverer(),
            render_javascript=render_javascript,
            index_click_workers=index_click_workers,
        )
