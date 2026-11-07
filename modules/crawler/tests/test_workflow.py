import json
import os
import runpy
import subprocess
import sys
import time
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread

import pytest
from web_scraping_crawler import CrawlProgress, CrawlResult


def test_workflow_records_crawl_wall_clock_timing(tmp_path, monkeypatch, capsys):
    run_path = Path(__file__).resolve().parents[3] / "workflows" / "crawler" / "run.py"
    main = runpy.run_path(str(run_path))["main"]
    workflow = main.__globals__
    events = []
    timestamps = iter(
        [
            datetime(2026, 11, 6, 2, 0, tzinfo=timezone.utc),
            datetime(2026, 11, 6, 1, 59, tzinfo=timezone.utc),
        ]
    )
    counters = iter([100.0, 112.5])

    class FakeDatetime:
        @staticmethod
        def now(tz):
            assert tz is timezone.utc
            events.append("timestamp")
            return next(timestamps)

    def fake_counter():
        events.append("counter")
        return next(counters)

    def fake_crawl(**kwargs):
        events.append("crawl")
        assert kwargs["seeds"] == ("https://example.com/",)
        return CrawlResult(
            visited_urls=("https://example.com/",),
            successful_urls=("https://example.com/",),
            failed_urls=(),
            discovered_urls=(),
            link_edges=(),
            termination_reason="frontier_exhausted",
        )

    monkeypatch.setitem(workflow, "datetime", FakeDatetime)
    monkeypatch.setitem(workflow, "perf_counter", fake_counter)
    monkeypatch.setitem(workflow, "crawl_with_scrapy", fake_crawl)
    output = tmp_path / "result.json"

    assert main(["https://example.com/", "-o", str(output)]) == 0

    data = json.loads(output.read_text(encoding="utf-8"))
    assert events == ["timestamp", "counter", "crawl", "counter", "timestamp"]
    assert data["crawl_timing"] == {
        "started_at": "2026-11-06T02:00:00+00:00",
        "finished_at": "2026-11-06T01:59:00+00:00",
        "elapsed_seconds": 12.5,
    }
    assert data["visited_urls"] == ["https://example.com/"]
    assert data["termination_reason"] == "frontier_exhausted"
    assert "Crawl wall-clock duration: 12.50 seconds." in capsys.readouterr().out


@pytest.mark.parametrize("interval", ["0", "-1", "nan", "inf"])
def test_workflow_rejects_invalid_snapshot_intervals(interval):
    run_path = Path(__file__).resolve().parents[3] / "workflows" / "crawler" / "run.py"
    arguments = runpy.run_path(str(run_path))["_arguments"]

    with pytest.raises(SystemExit) as exc:
        arguments(["https://example.com/", "--snapshot-interval", interval])

    assert exc.value.code == 2


def test_workflow_snapshot_defaults_and_write_failure(tmp_path, monkeypatch, caplog):
    run_path = Path(__file__).resolve().parents[3] / "workflows" / "crawler" / "run.py"
    workflow = runpy.run_path(str(run_path))
    main = workflow["main"]
    assert workflow["_arguments"](["https://example.com/"]).snapshot_interval == 600
    result = CrawlResult(
        visited_urls=(),
        successful_urls=(),
        failed_urls=(),
        discovered_urls=(),
        link_edges=(),
        termination_reason="frontier_exhausted",
    )
    progress = CrawlProgress(
        status="running",
        termination_reason=None,
        scheduled_pages=2,
        visited_urls=1,
        successful_urls=1,
        failed_urls=1,
        discovered_urls=3,
        failure_types={"TimeoutError": 1},
    )

    def fake_crawl(**kwargs):
        kwargs["progress_callback"](progress)
        return result

    monkeypatch.setitem(main.__globals__, "crawl_with_scrapy", fake_crawl)
    output = tmp_path / "custom" / "result.json"
    assert main(["https://example.com/", "-o", str(output)]) == 0
    snapshots = list((output.parent / "snapshots").glob("*/*.json"))
    assert len(snapshots) == 1
    data = json.loads(snapshots[0].read_text(encoding="utf-8"))
    assert data["counts"] == {
        "scheduled_pages": 2,
        "visited_urls": 1,
        "successful_urls": 1,
        "failed_urls": 1,
        "discovered_urls": 3,
    }
    assert data["failure_types"] == {"TimeoutError": 1}
    assert data["status"] == "running"
    assert data["termination_reason"] is None

    original_write = Path.write_text

    def fail_snapshot_write(path, *args, **kwargs):
        if path.suffix == ".tmp":
            raise OSError("disk unavailable")
        return original_write(path, *args, **kwargs)

    monkeypatch.setattr(Path, "write_text", fail_snapshot_write)
    assert main(["https://example.com/", "-o", str(output)]) == 0
    assert "Could not write crawl progress snapshot" in caplog.text
    assert "disk unavailable" in caplog.text
    assert len(list((output.parent / "snapshots").iterdir())) == 2
    assert json.loads(output.read_text(encoding="utf-8"))["termination_reason"] == (
        "frontier_exhausted"
    )


def test_workflow_writes_live_and_final_snapshots_to_default_folder(tmp_path):
    pytest.importorskip("scrapy")

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path == "/robots.txt":
                body = b"User-agent: *\nAllow: /\n"
            else:
                time.sleep(0.7)
                body = b"<html><title>Test</title></html>"
            self.send_response(200)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format_string, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    root = "http://127.0.0.1:{}/".format(server.server_port)
    repository = Path(__file__).resolve().parents[3]
    environment = os.environ.copy()
    environment["PYTHONPATH"] = os.pathsep.join(
        filter(
            None,
            [
                str(repository / "modules" / "crawler" / "src"),
                environment.get("PYTHONPATH"),
            ],
        )
    )
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    try:
        completed = subprocess.run(
            [
                sys.executable,
                str(repository / "workflows" / "crawler" / "run.py"),
                root,
                "--snapshot-interval",
                "0.2",
                "-t",
                "10",
            ],
            cwd=tmp_path,
            env=environment,
            capture_output=True,
            text=True,
            timeout=30,
        )
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)

    assert completed.returncode == 0, completed.stderr
    output_dir = tmp_path / "output" / "crawler"
    result = json.loads((output_dir / "crawl-result.json").read_text(encoding="utf-8"))
    snapshots = sorted((output_dir / "snapshots").glob("*/*.json"))
    assert len(snapshots) >= 2
    progress = [json.loads(path.read_text(encoding="utf-8")) for path in snapshots]
    assert all(item["status"] == "running" for item in progress[:-1])
    assert progress[-1]["status"] == "completed"
    assert progress[-1]["termination_reason"] == result["termination_reason"]
    assert progress[-1]["counts"]["visited_urls"] == len(result["visited_urls"])
    assert progress[-1]["counts"]["successful_urls"] == len(result["successful_urls"])
    assert progress[-1]["counts"]["scheduled_pages"] == 1
    assert progress[-1]["failure_types"] == {}
    assert all(
        item["started_at"] == result["crawl_timing"]["started_at"]
        for item in progress
    )
    assert [item["elapsed_seconds"] for item in progress] == sorted(
        item["elapsed_seconds"] for item in progress
    )
    assert all(item["snapshot_at"].endswith("+00:00") for item in progress)
    assert not list((output_dir / "snapshots").glob("*/*.tmp"))
