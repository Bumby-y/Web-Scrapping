# Scripts

Put repository maintenance and development helper scripts here, such as
commands for validating manifests or running checks across modules. Keep
module-specific runtime behavior inside the module itself.

## Sitemap generator

[`sitemap/generate.py`](sitemap/generate.py) reads a crawler result JSON file
and creates `sitemap.xml` from successfully fetched URLs plus a `sitemap.mmd`
Mermaid graph from the discovered link edges. See
[`sitemap/README.md`](sitemap/README.md) for usage and validation rules.

## Excel reference audit

[`excel-report/generate.py`](excel-report/generate.py) creates an Excel
workbook for auditing and reviewing references from a crawler result. See
[`excel-report/README.md`](excel-report/README.md) for installation, usage and
report limitations.
