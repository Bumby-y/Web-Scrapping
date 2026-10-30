# Modules

This folder contains reusable tools, with one independently packaged Python
project per module. Keep each module's implementation, dependencies, tests,
metadata, usage documentation, and AI skill together so users and automation
can select, install, and use modules separately.

Each module's `skills/<module-name>/SKILL.md` describes how an AI agent should
use that package. Keep executable behavior in the Python package, not in the
skill instructions.

Design modules around explicit, small interfaces so callers can reuse and
compose them in different applications. Keep provider-specific integrations
behind adapters where it is useful to swap implementations, and keep each
module's core behavior independent of a particular storage backend or cloud
vendor. These are design principles; do not assume an adapter exists unless it
is implemented and documented. See `docs/ARCHITECTURE.md` for shared guidance.
