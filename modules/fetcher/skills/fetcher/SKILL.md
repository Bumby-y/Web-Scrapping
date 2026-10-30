---
name: fetcher
description: Guidance for selecting and using the web-scraping fetcher module.
---

# Fetcher skill

## When to use

Use this module when a task requires retrieving an individual web resource over
HTTP. For multi-page traversal, use the Crawler module to coordinate URLs;
for extracting information from HTML, use the HTML Parser module.

## Current status

This module is a scaffold. Do not assume it exposes a working fetch API. Check
the package README and implementation for the current supported interface
before proposing or executing code that depends on it.

## Safety and permissions

Only request resources the user is authorized to access. Keep destinations and
network access explicit, respect site terms and rate limits, and do not bypass
authentication, access controls, or other restrictions.
