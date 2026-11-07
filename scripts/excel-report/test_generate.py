import json

from openpyxl import load_workbook

from generate import build_workbook, main, parse_prefixes


def sample_result():
    def reference(source, target, category, scope="out_of_scope", attribute="href"):
        return {
            "source_url": source,
            "target_url": target,
            "category": category,
            "scope": scope,
            "attribute": attribute,
        }

    return {
        "visited_urls": ["https://site.example/start", "https://site.example/next"],
        "successful_urls": ["https://site.example/start", "https://site.example/next"],
        "failed_urls": [],
        "link_references": [
            reference("https://site.example/start", "https://outside.example/events/1", "hyperlink"),
            reference("https://site.example/next", "https://outside.example/events/1", "hyperlink"),
            reference("https://site.example/start", "https://outside.example/other", "hyperlink"),
            reference("https://site.example/start", "https://outside.example/events/1", "script_reference", attribute="script"),
            reference("https://site.example/start", "https://site.example/image.png", "image", attribute="src"),
            reference("https://site.example/start", "https://site.example/next", "hyperlink", scope="in_scope"),
        ],
    }


def test_counts_grouping_and_live_review_links(tmp_path):
    result = sample_result()
    prefixes = parse_prefixes(
        ["outside.example|hyperlink|https://outside.example/events/"],
        result["link_references"],
    )
    workbook = build_workbook(result, "site.example", prefixes)
    path = tmp_path / "report.xlsx"
    workbook.save(path)
    workbook = load_workbook(path)
    assert workbook.sheetnames == ["External audit", "Reference review", "Where to fix"]
    summary = workbook["External audit"]
    assert [summary[f"B{i}"].value for i in range(3, 10)] == [2, 2, 1, 2, 4, 3, 5]
    assert [summary[f"B{i}"].value for i in range(13, 16)] == [2, 0, 1]
    review = workbook["Reference review"]
    assert review.max_row == 4
    assert all(row[1].value != "site.example" for row in review.iter_rows(min_row=2))
    event_row = next(row for row in review.iter_rows(min_row=2) if (row[3].value or "").endswith("/events/"))
    assert [cell.value for cell in event_row[4:7]] == [1, 2, 2]
    assert event_row[8].value == "Not reviewed"
    details = workbook["Where to fix"]
    assert details.max_row == 5
    assert details["M2"].value == event_row[0].value
    assert "MATCH($M2" in details["A2"].value
    assert "Review group missing" in details["B2"].value
    assert details["I2"].value == "Location not recorded"
    assert details["D2"].value == "Not started"
    assert details["E2"].hyperlink.target == result["link_references"][0]["source_url"]
    assert details["O2"].value == "Yes"
    assert all(row[6].value != "site.example" for row in details.iter_rows(min_row=2))
    assert details.auto_filter.ref == "A1:O5"
    assert len(details.data_validations.dataValidation) == 1


def test_longest_prefix_and_invalid_prefix():
    import pytest

    refs = sample_result()["link_references"]
    prefixes = parse_prefixes([
        "outside.example|hyperlink|https://outside.example/",
        "outside.example|hyperlink|https://outside.example/events/",
    ], refs)
    workbook = build_workbook(sample_result(), "site.example", prefixes)
    event = next(row for row in workbook["Reference review"].iter_rows(min_row=2)
                 if row[3].value.endswith("/events/"))
    assert event[4].value == 1
    with pytest.raises(ValueError, match="matches no"):
        parse_prefixes(["outside.example|image|https://outside.example/"], refs)
    with pytest.raises(ValueError, match="hostname does not match"):
        parse_prefixes(["wrong.example|hyperlink|https://outside.example/"], refs)


def test_cli_refuses_overwrite_and_invalid_input(tmp_path, capsys):
    input_path = tmp_path / "result.json"
    input_path.write_text(json.dumps(sample_result()), encoding="utf-8")
    output = tmp_path / "audit.xlsx"
    assert main([str(input_path), "--output", str(output)]) == 0
    original = output.read_bytes()
    assert main([str(input_path), "--output", str(output)]) == 1
    assert output.read_bytes() == original
    input_path.write_text('{"visited_urls": []}', encoding="utf-8")
    assert main([str(input_path), "--output", str(tmp_path / "bad.xlsx")]) == 1
    assert "must contain" in capsys.readouterr().err


def test_multi_host_requires_explicit_audited_host(tmp_path, capsys):
    result = sample_result()
    result["visited_urls"].append("https://second.example/")
    path = tmp_path / "result.json"
    path.write_text(json.dumps(result), encoding="utf-8")
    output = tmp_path / "audit.xlsx"
    assert main([str(path), "--output", str(output)]) == 1
    assert "--site-host" in capsys.readouterr().err
    assert main([str(path), "--output", str(output), "--site-host", "site.example"]) == 0


def test_internal_prefix_is_rejected(tmp_path, capsys):
    path = tmp_path / "result.json"
    path.write_text(json.dumps(sample_result()), encoding="utf-8")
    output = tmp_path / "audit.xlsx"
    assert main([
        str(path), "--output", str(output), "--group-prefix",
        "site.example|image|https://site.example/",
    ]) == 1
    assert "matches no out-of-scope references" in capsys.readouterr().err
    assert not output.exists()


def test_empty_review_and_external_in_scope():
    result = sample_result()
    result["link_references"] = [
        {"source_url": "https://site.example/start",
         "target_url": "https://outside.example/",
         "category": "hyperlink", "scope": "in_scope", "attribute": "href"},
        {"source_url": "https://site.example/start",
         "target_url": "https://site.example/resource",
         "category": "image", "scope": "out_of_scope", "attribute": "src"},
    ]
    workbook = build_workbook(result, "site.example", [])
    assert workbook["External audit"]["B7"].value == 1
    assert workbook["Reference review"].max_row == 1
    assert workbook["Where to fix"].max_row == 1
