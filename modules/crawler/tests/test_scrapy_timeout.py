import json
import os
import subprocess
import sys
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread

import pytest

pytest.importorskip("scrapy")


def test_scrapy_timeout_uses_async_spider_close_without_deprecation_warning():
    requests = []

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            requests.append(self.path)
            if self.path == "/robots.txt":
                self._respond(200, b"User-agent: *\nAllow: /\n")
                return

            time.sleep(2)
            self._respond(200, b"slow response")

        def _respond(self, status, body):
            self.send_response(status)
            self.send_header("Content-Type", "text/plain")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format_string, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    root = "http://127.0.0.1:{}/".format(server.server_port)
    source_dir = Path(__file__).resolve().parents[1] / "src"
    environment = os.environ.copy()
    existing_pythonpath = environment.get("PYTHONPATH")
    environment["PYTHONPATH"] = os.pathsep.join(
        path for path in (str(source_dir), existing_pythonpath) if path
    )
    script = """
import json
from web_scraping_crawler import CrawlPolicy, crawl_with_scrapy

class LinkDiscoverer:
    def discover_links(self, content):
        return []

result = crawl_with_scrapy(
    [ROOT],
    CrawlPolicy(
        allowed_domains=("127.0.0.1",),
        max_pages=1,
        max_depth=0,
        max_elapsed_time=0.5,
    ),
    LinkDiscoverer(),
)
print(json.dumps({"visited_urls": result.visited_urls}))
""".replace("ROOT", repr(root))

    try:
        completed = subprocess.run(
            [sys.executable, "-c", script],
            cwd=str(Path(__file__).resolve().parents[1]),
            env=environment,
            capture_output=True,
            text=True,
            timeout=15,
        )
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)

    assert completed.returncode == 0, completed.stderr
    assert "ScrapyDeprecationWarning" not in completed.stderr
    assert "/" in requests
    result = json.loads(completed.stdout.strip().splitlines()[-1])
    assert root in result["visited_urls"]
