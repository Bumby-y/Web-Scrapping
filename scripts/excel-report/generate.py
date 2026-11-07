"""Generate a reviewable Excel audit from a crawler result."""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Sequence
from urllib.parse import urlsplit

from openpyxl import Workbook
from openpyxl.formatting.rule import CellIsRule
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.datavalidation import DataValidation


FRIENDLY_TYPES = {
    "hyperlink": "Clickable link",
    "javascript_navigation": "Link opened by page interaction",
    "image": "Image",
    "script_resource": "Script file",
    "script_reference": "Address mentioned in a script",
    "link_stylesheet": "Page style file",
    "link_icon": "Page icon",
    "meta_resource": "Page preview resource",
    "file_link": "Download link",
    "in_text": "Address in text",
    "media_resource": "Media file",
    "embedded_resource": "Embedded content",
    "form_action": "Form destination",
    "citation": "Citation",
    "redirect": "Redirect destination",
}
AUDIT_CATEGORIES = (
    "hyperlink", "javascript_navigation", "script_reference", "image",
    "script_resource", "link_stylesheet",
)
HEADER_FILL = PatternFill("solid", fgColor="17365D")
HEADER_FONT = Font(color="FFFFFF", bold=True)
INPUT_FILL = PatternFill("solid", fgColor="FFF2CC")


def hostname(url: str, context: str) -> str:
    if not isinstance(url, str) or not url or url != url.strip():
        raise ValueError(f"{context}: expected a non-empty URL")
    try:
        parsed = urlsplit(url)
        _ = parsed.port
        host = parsed.hostname
    except ValueError as exc:
        raise ValueError(f"{context}: invalid URL {url!r}") from exc
    if parsed.scheme.lower() not in ("http", "https") or not host:
        raise ValueError(f"{context}: expected an absolute HTTP(S) URL: {url!r}")
    if parsed.username is not None or parsed.password is not None:
        raise ValueError(f"{context}: URL must not contain credentials")
    return host.lower()


def read_result(path: Path) -> dict[str, Any]:
    try:
        with path.open(encoding="utf-8") as file:
            data = json.load(file)
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"Cannot read crawl result: {exc}") from exc
    if not isinstance(data, dict):
        raise ValueError("Crawl result must be a JSON object")
    for key in ("visited_urls", "successful_urls", "failed_urls", "link_references"):
        if not isinstance(data.get(key), list):
            raise ValueError(f"Crawl result must contain a {key!r} list")
    for key in ("visited_urls", "successful_urls"):
        for index, url in enumerate(data[key]):
            hostname(url, f"{key}[{index}]")
    for index, ref in enumerate(data["link_references"]):
        if not isinstance(ref, dict):
            raise ValueError(f"link_references[{index}] must be an object")
        for field in ("source_url", "target_url", "category", "scope"):
            if not isinstance(ref.get(field), str) or not ref[field]:
                raise ValueError(f"link_references[{index}] requires {field}")
        if ref["scope"] not in ("in_scope", "out_of_scope", "non_http"):
            raise ValueError(f"link_references[{index}] has invalid scope")
        if ref.get("attribute") is not None and not isinstance(ref["attribute"], str):
            raise ValueError(f"link_references[{index}] has invalid attribute")
        hostname(ref["source_url"], f"link_references[{index}].source_url")
        if ref["scope"] != "non_http":
            hostname(ref["target_url"], f"link_references[{index}].target_url")
    return data


def parse_prefixes(values: Sequence[str], refs: list[dict[str, Any]]) -> list[tuple[str, str, str]]:
    prefixes = []
    for value in values:
        parts = value.split("|")
        if len(parts) != 3 or not all(parts):
            raise ValueError("Group prefix must have format hostname|category|URL-prefix")
        host, category, prefix = parts
        host = host.lower()
        if hostname(prefix, "group prefix") != host:
            raise ValueError(f"Group prefix hostname does not match: {value}")
        item = (host, category, prefix)
        if item in prefixes:
            raise ValueError(f"Duplicate group prefix: {value}")
        if not any(
            r["scope"] == "out_of_scope"
            and hostname(r["target_url"], "target") == host
            and r["category"] == category
            and r["target_url"].startswith(prefix)
            for r in refs
        ):
            raise ValueError(f"Group prefix matches no out-of-scope references: {value}")
        prefixes.append(item)
    return prefixes


def group_key(ref: dict[str, Any], prefixes: list[tuple[str, str, str]]) -> tuple[str, str, str]:
    host = hostname(ref["target_url"], "target")
    category = ref["category"]
    matching = [
        prefix for candidate_host, candidate_category, prefix in prefixes
        if candidate_host == host and candidate_category == category
        and ref["target_url"].startswith(prefix)
    ]
    return host, category, max(matching, key=len) if matching else ""


def text(cell: Any, value: str) -> None:
    """Keep source data as text, even when it resembles an Excel formula."""
    cell.value = value
    cell.data_type = "s"


def header(sheet: Any, row: int, values: Sequence[str]) -> None:
    for col, value in enumerate(values, 1):
        cell = sheet.cell(row, col, value)
        cell.fill = HEADER_FILL
        cell.font = HEADER_FONT
        cell.alignment = Alignment(wrap_text=True, vertical="center")
    sheet.row_dimensions[row].height = 32


def widths(sheet: Any, values: Sequence[int]) -> None:
    for index, width in enumerate(values, 1):
        sheet.column_dimensions[get_column_letter(index)].width = width


def dropdown(sheet: Any, cells: str, choices: str) -> None:
    validation = DataValidation(type="list", formula1=f'"{choices}"', allow_blank=True)
    validation.showErrorMessage = True
    validation.errorTitle = "Choose a listed value"
    validation.error = "Select a value from the list."
    sheet.add_data_validation(validation)
    validation.add(cells)


def priority_colors(sheet: Any, column: str, end_row: int) -> None:
    for value, color in (("High", "FFC7CE"), ("Medium", "FFEB9C"), ("Low", "C6EFCE")):
        sheet.conditional_formatting.add(
            f"{column}2:{column}{end_row}",
            CellIsRule(operator="equal", formula=[f'"{value}"'],
                       fill=PatternFill("solid", fgColor=color)),
        )


def build_workbook(
    result: dict[str, Any], site_host: str, prefixes: list[tuple[str, str, str]]
) -> Workbook:
    refs = result["link_references"]
    http_refs = [ref for ref in refs if ref["scope"] != "non_http"]
    external = [ref for ref in http_refs if hostname(ref["target_url"], "target") != site_host]
    outside = [ref for ref in http_refs if ref["scope"] == "out_of_scope"]
    review_refs = [ref for ref in outside if hostname(ref["target_url"], "target") != site_host]
    groups: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for ref in review_refs:
        groups[group_key(ref, prefixes)].append(ref)
    keys = sorted(groups)
    ids = {key: f"G{index:04d}" for index, key in enumerate(keys, 1)}

    book = Workbook()
    book.calculation.fullCalcOnLoad = True
    book.calculation.forceFullCalc = True
    book.calculation.calcMode = "auto"
    overview = book.active
    overview.title = "External audit"
    overview.append(["External reference audit"])
    overview["A1"].font = Font(size=16, bold=True, color="17365D")
    overview.append(["Audited site hostname", site_host])
    overview.append(["Successfully retrieved pages", len(set(result["successful_urls"]))])
    overview.append(["Pages containing external references", len({r["source_url"] for r in external})])
    overview.append(["Distinct external target hostnames", len({hostname(r["target_url"], "target") for r in external})])
    overview.append(["Distinct external target URLs", len({r["target_url"] for r in external})])
    overview.append(["External reference records", len(external)])
    overview.append(["Distinct out-of-scope target URLs (all hosts)", len({r["target_url"] for r in outside})])
    overview.append(["Out-of-scope reference records (all hosts)", len(outside)])
    overview.append(["Failed retrieval or processing records", len(result["failed_urls"])])
    overview.append([])
    header(overview, 12, ["External reference category", "Distinct target URLs", "Reference records"])
    category_counts = Counter(r["category"] for r in external)
    categories = list(AUDIT_CATEGORIES) + sorted(set(category_counts) - set(AUDIT_CATEGORIES))
    for category in categories:
        matching = [r for r in external if r["category"] == category]
        overview.append([category, len({r["target_url"] for r in matching}), len(matching)])
    overview.append([])
    notes = [
        "External means a target hostname different from the audited site hostname; subdomains count separately.",
        "References are recorded source-to-target relationships, not necessarily every occurrence in page markup.",
        "Distinct URL counts per category can overlap and should not be added together.",
        "A URL mentioned in a script is not necessarily a script file loaded by the page.",
        "Out-of-scope totals include same-host URLs outside the crawl area, but review sheets exclude same-host references.",
        "Review sheets include external out-of-scope references; external references in scope are included in audit totals only.",
        "Discovery does not establish whether URLs work, are permitted, or require remediation.",
        "Page location and the clicked element are not recorded for individual references.",
        "MO: enter priority, decision, approach, instructions and assignee in the yellow cells on Reference review.",
        "Fixing team: filter Where to fix by decision and assignee, then update the yellow progress and work notes cells.",
        "Open in Excel or a compatible spreadsheet application to calculate linked review values; reapply filters after review changes.",
    ]
    for note in notes:
        overview.append([note])
        overview.cell(overview.max_row, 1).alignment = Alignment(wrap_text=True, vertical="top")
        overview.row_dimensions[overview.max_row].height = 30
    widths(overview, [84, 25, 22])
    overview.freeze_panes = "B3"

    review = book.create_sheet("Reference review")
    header(review, 1, [
        "Group ID", "Target hostname", "Reference category", "Target URL prefix",
        "Distinct target URLs", "Affected source pages", "Reference records",
        "Priority", "MO decision", "Remediation approach",
        "Decision rationale / instructions", "Assignee",
    ])
    for key in keys:
        records = groups[key]
        row = review.max_row + 1
        values = [ids[key], *key, len({r["target_url"] for r in records}),
                  len({r["source_url"] for r in records}), len(records),
                  "", "Not reviewed", "", "", ""]
        for col, value in enumerate(values, 1):
            if isinstance(value, str):
                text(review.cell(row, col), value)
            else:
                review.cell(row, col, value)
        for col in range(8, 13):
            review.cell(row, col).fill = INPUT_FILL
    end = max(2, review.max_row)
    dropdown(review, f"H2:H{end}", "High,Medium,Low")
    dropdown(review, f"I2:I{end}", "Not reviewed,Keep,Change,Investigate")
    priority_colors(review, "H", end)
    review.auto_filter.ref = f"A1:L{end}"
    review.freeze_panes = "D2"
    widths(review, [12, 31, 25, 48, 20, 20, 19, 13, 18, 38, 45, 22])

    detail = book.create_sheet("Where to fix")
    header(detail, 1, [
        "Priority (优先级)", "MO decision (MO决定)", "Assigned to (负责人)",
        "Progress (处理进度)", "Page to check (需检查的页面)",
        "Address found (发现的地址)", "Where it points (指向的网站)",
        "How it is used (用途)", "Where on the page (页面位置)",
        "Approach (处理方法)", "MO instructions (MO处理指示)",
        "Work notes (处理备注)", "Group ID (分组编号)",
        "Address field (地址字段)", "Other website? (是否其他网站)",
    ])
    review_end = max(2, review.max_row)
    # The group ID is fixed per record; the editable review values remain live.
    for row, ref in enumerate(review_refs, 2):
        key = group_key(ref, prefixes)
        for col, review_col in ((1, "H"), (2, "I"), (3, "L"), (10, "J"), (11, "K")):
            lookup = f"INDEX('Reference review'!${review_col}$2:${review_col}${review_end},MATCH($M{row},'Reference review'!$A$2:$A${review_end},0))"
            detail.cell(row, col, f'=IFERROR(IF({lookup}="","",{lookup}),"Review group missing")')
        text(detail.cell(row, 4), "Not started")
        text(detail.cell(row, 5), ref["source_url"])
        text(detail.cell(row, 6), ref["target_url"])
        text(detail.cell(row, 7), key[0])
        text(detail.cell(row, 8), FRIENDLY_TYPES.get(ref["category"], f"Other: {ref['category']}"))
        text(detail.cell(row, 9), "Location not recorded")
        text(detail.cell(row, 13), ids[key])
        text(detail.cell(row, 14), ref.get("attribute") or "Not recorded")
        text(detail.cell(row, 15), "Yes" if key[0] != site_host else "No")
        for col in (4, 12):
            detail.cell(row, col).fill = INPUT_FILL
        for col in (5, 6):
            cell = detail.cell(row, col)
            if len(cell.value) <= 2079:
                cell.hyperlink = cell.value
                cell.style = "Hyperlink"
    detail_end = max(2, detail.max_row)
    dropdown(detail, f"D2:D{detail_end}", "Not started,In progress,Done,Stuck")
    priority_colors(detail, "A", detail_end)
    detail.auto_filter.ref = f"A1:O{detail_end}"
    detail.freeze_panes = "E2"
    widths(detail, [17, 22, 23, 22, 55, 55, 28, 35, 29, 38, 45, 40, 18, 20, 23])
    return book


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("result", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--site-host", help="Audited site hostname (required for multiple visited hosts)")
    parser.add_argument("--group-prefix", action="append", default=[], metavar="HOST|CATEGORY|URL_PREFIX")
    args = parser.parse_args(argv)
    try:
        result = read_result(args.result)
        visited_hosts = {hostname(url, "visited URL") for url in result["visited_urls"]}
        if args.site_host:
            site_host = args.site_host.lower()
            if site_host not in visited_hosts:
                raise ValueError("--site-host must match a visited hostname")
        elif len(visited_hosts) == 1:
            site_host = next(iter(visited_hosts))
        else:
            raise ValueError("Specify --site-host when visited URLs do not have exactly one hostname")
        review_candidates = [
            ref for ref in result["link_references"]
            if ref["scope"] == "out_of_scope"
            and hostname(ref["target_url"], "target") != site_host
        ]
        prefixes = parse_prefixes(args.group_prefix, review_candidates)
        book = build_workbook(result, site_host, prefixes)
        with args.output.open("xb") as file:
            book.save(file)
    except (ValueError, OSError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    print(f"Created {args.output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
