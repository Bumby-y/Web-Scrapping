# Excel reference audit report

Create a three-sheet Excel workbook from a crawler result:

```shell
python -m pip install -r scripts/excel-report/requirements.txt
python scripts/excel-report/generate.py crawl-result.json --output external-reference-audit.xlsx
```

The site hostname is inferred only when all visited URLs have the same
hostname. For a multi-host crawl, specify `--site-host example.com`.
External means a target hostname different from this site hostname; the review
and follow-up sheets contain only out-of-scope HTTP(S) references to a
different hostname. Same-host references are excluded from those sheets, even
when their paths are outside the configured crawl area. The audit's separate
out-of-scope totals still include all hostnames. External references that are
in scope are included in the audit totals but not the review sheets. The
report does not verify destination availability or policy compliance.

The review sheet groups records by target hostname and reference category.
Optionally split a group by supplying an absolute HTTP(S) URL prefix:

```shell
python scripts/excel-report/generate.py crawl-result.json --output external-reference-audit.xlsx \
  --group-prefix "www.example.com|hyperlink|https://www.example.com/events/"
```

Repeat `--group-prefix` for additional groups. Prefix matching is literal,
case-sensitive and longest-match wins. Non-matching records remain in their
hostname/category group. Each prefix must have the stated hostname and match
at least one external out-of-scope record in that category. Create prefixes before
review begins: editing grouping columns in the workbook does not regroup
records, and regenerating creates a new workbook rather than migrating edits.
Existing output files are never overwritten.

On **Reference review**, edit priority, decision, remediation approach,
instructions and assignee. **Where to fix** uses Excel formulas to retrieve
these fields by group ID; leave the group IDs unchanged. Excel or another
compatible spreadsheet application must calculate the formulas when opening
the file. The fixing team can edit progress and notes independently on that
sheet. Filter by decision, priority or assignee to find relevant work; initial
decisions are `Not reviewed` and no severity is assumed. Reapply filters after
editing review values; spreadsheet applications do not necessarily refresh an
already-applied filter automatically.

The JSON does not identify a reference's exact page location or associate a
navigation record with a particular clicked selector. The workbook therefore
reports `Location not recorded`, not a guessed content, navigation or card
location. Resource labels describe what was recorded, not whether an external
resource is permitted or broken. Save review edits in the workbook and avoid
regenerating over a reviewed file.
