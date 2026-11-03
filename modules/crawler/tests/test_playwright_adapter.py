import json
import os
import subprocess
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread

import pytest

pytest.importorskip("scrapy")
pytest.importorskip("scrapy_playwright")


def test_playwright_renders_javascript_and_discovers_image_wrapped_anchor():
    from playwright.sync_api import sync_playwright

    with sync_playwright() as playwright:
        if not Path(playwright.chromium.executable_path).is_file():
            pytest.skip(
                "Playwright Chromium is not installed; run "
                "'python -m playwright install chromium'."
            )

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            requests.append(self.path)
            if self.path == "/robots.txt":
                self._respond(
                    200,
                    b"User-agent: *\nAllow: /\n",
                    "text/plain",
                )
                return
            if self.path == "/hkrw/en/index.html":
                body = (
                    "<div id='app'>Loading...</div>"
                    "<script>"
                    "setTimeout(function () {"
                    "document.querySelector('#app').innerHTML = "
                    "\"<a href='detail'><img src='/cover.png'></a>\" + "
                    "\"<div class='child-card'>card</div>\" + "
                    "\"<button role='button'>button</button>\" + "
                    "\"<div class='child-card'>outside</div>\" + "
                    "\"<div class='child-card'>youtube navigation</div>\" + "
                    "\"<button class='section-more-btn'>More</button>\";"
                    "document.querySelector('#app').addEventListener('click', function (event) {"
                    "var card = event.target.closest('.child-card');"
                    "var button = event.target.closest('[role=button]');"
                    "var more = event.target.closest('.section-more-btn');"
                    "if (more) {"
                    "window.moreClicks = (window.moreClicks || 0) + 1;"
                    "var extra = document.createElement('div');"
                    "extra.className = 'child-card';"
                    "extra.textContent = 'loaded ' + window.moreClicks;"
                    "document.querySelector('#app').appendChild(extra);"
                    "if (window.moreClicks === 2) { more.remove(); }"
                    "} else if (card && card.textContent === 'card') {"
                    "setTimeout(function () { history.pushState({}, '', '/hkrw/en/clicked'); }, 250);"
                    "} else if (button) {"
                    "setTimeout(function () { window.location.assign('/hkrw/en/role-clicked'); }, 250);"
                    "} else if (card && card.textContent === 'youtube navigation') {"
                    "setTimeout(function () { window.location.assign('https://www.youtube.com/watch?v=fixture'); }, 250);"
                    "} else if (card && card.textContent.indexOf('loaded') === 0) {"
                    "window.resetLoadedCardsOnBack = true;"
                    "setTimeout(function () { history.pushState({}, '', '/hkrw/en/loaded-clicked'); }, 250);"
                    "} else if (card) {"
                    "setTimeout(function () { history.pushState({}, '', '/en/outside'); }, 250);"
                    "}"
                    "});"
                    "window.addEventListener('popstate', function () {"
                    "if (window.resetLoadedCardsOnBack && location.pathname.endsWith('/index.html')) {"
                    "window.resetLoadedCardsOnBack = false;"
                    "window.moreClicks = 0;"
                    "document.querySelectorAll('.child-card').forEach(function (item) {"
                    "if (item.textContent.indexOf('loaded') === 0) item.remove();"
                    "});"
                    "var more = document.createElement('button');"
                    "more.className = 'section-more-btn';"
                    "more.textContent = 'More';"
                    "document.querySelector('#app').appendChild(more);"
                    "}"
                    "});"
                    "document.body.dataset.rendered = 'true';"
                    "}, 1000);"
                    "</script>"
                ).encode("utf-8")
                self._respond(200, body)
                return
            if self.path == "/hkrw/en/detail":
                body = (
                    "<h1>Detail</h1>"
                    "<script>"
                    "setTimeout(function () {"
                    "document.body.dataset.rendered = 'true';"
                    "}, 20);"
                    "</script>"
                ).encode("utf-8")
                self._respond(200, body)
                return
            if self.path == "/hkrw/en/clicked":
                self._respond(200, b"<h1>Clicked Vue route</h1>")
                return
            if self.path == "/hkrw/en/role-clicked":
                self._respond(200, b"<h1>Role button Vue route</h1>")
                return
            self._respond(404, b"Not found")

        def _respond(self, status, body, content_type="text/html; charset=utf-8"):
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format_string, *args):
            pass

    requests = []
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    root = "http://127.0.0.1:{}/hkrw/en/index.html".format(server.server_port)
    prefix = "http://127.0.0.1:{}/hkrw/en/".format(server.server_port)
    source_dir = Path(__file__).resolve().parents[1] / "src"
    environment = os.environ.copy()
    existing_pythonpath = environment.get("PYTHONPATH")
    environment["PYTHONPATH"] = os.pathsep.join(
        path for path in (str(source_dir), existing_pythonpath) if path
    )
    script = """
import json
from parsel import Selector
from web_scraping_crawler import CrawlPolicy, crawl_with_scrapy

class LinkDiscoverer:
    def discover_links(self, content):
        return Selector(text=content).css("a::attr(href)").getall()

result = crawl_with_scrapy(
    [ROOT],
    CrawlPolicy(
        allowed_domains=("127.0.0.1",),
        max_pages=2,
        max_depth=1,
        max_elapsed_time=90,
        allowed_url_prefixes=(PREFIX,),
    ),
    LinkDiscoverer(),
    render_javascript=True,
    click_selectors=("[role=button]",),
    load_more_selectors=(".section-more-btn",),
)
print(json.dumps({
    "visited_urls": result.visited_urls,
    "discovered_urls": result.discovered_urls,
    "out_of_scope_urls": result.out_of_scope_urls,
    "click_selector_counts": result.click_selector_counts,
    "load_more_click_counts": result.load_more_click_counts,
    "failed_urls": [
        {
            "url": failure.url,
            "stage": failure.stage,
            "error_type": failure.error_type,
            "message": failure.message,
        }
        for failure in result.failed_urls
    ],
}))
""".replace("ROOT", repr(root)).replace("PREFIX", repr(prefix))

    try:
        completed = subprocess.run(
            [sys.executable, "-c", script],
            cwd=str(Path(__file__).resolve().parents[1]),
            env=environment,
            capture_output=True,
            text=True,
            timeout=120,
        )
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)

    assert completed.returncode == 0, completed.stderr
    assert "Task was destroyed but it is pending" not in completed.stderr
    assert "Queue.join was never awaited" not in completed.stderr
    result = json.loads(completed.stdout.strip().splitlines()[-1])
    assert root in result["visited_urls"]
    assert "http://127.0.0.1:{}/hkrw/en/detail".format(server.server_port) in (
        result["discovered_urls"]
    ), json.dumps(result, indent=2)
    assert "http://127.0.0.1:{}/en/outside".format(server.server_port) not in (
        result["discovered_urls"]
    )
    assert "/hkrw/en/detail" in requests
    assert "/en/outside" not in requests
    assert "http://127.0.0.1:{}/hkrw/en/clicked".format(server.server_port) in (
        result["discovered_urls"]
    )
    assert "http://127.0.0.1:{}/hkrw/en/role-clicked".format(
        server.server_port
    ) in result["discovered_urls"]
    assert "http://127.0.0.1:{}/hkrw/en/loaded-clicked".format(
        server.server_port
    ) in result["discovered_urls"]
    assert not any("youtube.com" in url for url in result["discovered_urls"])
    assert "https://www.youtube.com/watch?v=fixture" in result["out_of_scope_urls"]
    assert (
        root,
        ".child-card",
        5,
    ) in [tuple(count) for count in result["click_selector_counts"]]
    assert (
        root,
        "[role=button]",
        1,
    ) in [tuple(count) for count in result["click_selector_counts"]]
    detail_url = "http://127.0.0.1:{}/hkrw/en/detail".format(server.server_port)
    assert (
        detail_url,
        ".child-card",
        0,
    ) in [tuple(count) for count in result["click_selector_counts"]]
    assert not any(
        failure["url"] == detail_url
        and failure["error_type"] == "PlaywrightClickError"
        for failure in result["failed_urls"]
    )
    root_load_more_count = next(
        count
        for page_url, selector, count in result["load_more_click_counts"]
        if page_url == root and selector == ".section-more-btn"
    )
    assert root_load_more_count >= 6
    assert not any(
        failure["url"] == root
        and failure["error_type"] == "PlaywrightClickError"
        for failure in result["failed_urls"]
    ), result["failed_urls"]
    assert (
        detail_url,
        ".section-more-btn",
        0,
    ) in [tuple(count) for count in result["load_more_click_counts"]]
