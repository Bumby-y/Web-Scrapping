---
name: html-parser
description: Guidance for selecting and using the web-scraping HTML parser module.
---

# HTML Parser skill

## When to use

Use this module when a task requires extracting structured information from
HTML that is already available. Use the Fetcher to retrieve an individual
resource or the Crawler to coordinate traversal across permitted pages.

## Current status

This module is a scaffold. Do not assume it exposes a working parsing API.
Check the package README and implementation for the current supported interface
before proposing or executing code that depends on it.

## Input handling

Treat HTML as untrusted input. Avoid executing scripts or loading remote
resources while parsing. Document the expected input format and output shape
when the package API is implemented.
