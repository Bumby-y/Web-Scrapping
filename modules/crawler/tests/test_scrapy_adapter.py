from html.parser import HTMLParser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread

import pytest

pytest.importorskip("scrapy")

from web_scraping_crawler import CrawlPolicy, crawl_with_scrapy


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
            HtmlLinkDiscoverer(),
        )
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)

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
