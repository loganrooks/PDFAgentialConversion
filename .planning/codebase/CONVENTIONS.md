# Coding Conventions

**Analysis Date:** 2026-03-15

## Naming Patterns

- Modules, functions, and files use `snake_case`
- Data-holder types use `PascalCase`, for example `ProjectPaths` and `TocEntry`
- Constants use `UPPER_SNAKE_CASE`, often for regexes, paths, and thresholds
- CLI-oriented modules are named by action, such as `convert_pdf`, `run_quality_gate`, `probe_artifacts`, and `compare_embedding_backends`
- Script wrappers intentionally reuse the exact same module names as their package counterparts

## Code Style

- Nearly every Python module starts with `from __future__ import annotations`
- `pathlib.Path` is preferred over raw string paths inside the package
- Type hints are used widely, especially `Path`, `dict[str, Any]`, and `list[...]`
- JSON is usually emitted with `indent=2`, `ensure_ascii=False`, and a trailing newline
- The codebase is pragmatic rather than framework-heavy; helper functions and small dataclasses are favored over large class hierarchies

## Import Organization

- Wrapper scripts prepend `src/` to `sys.path` and then import from `pdfmd.*`
- Core modules generally keep standard-library imports first, third-party imports next, and local `pdfmd` imports last
- `src/pdfmd/cli/*.py` is intentionally thin and mostly re-exports from subsystem modules
- Shared helpers should flow through `pdfmd.common` rather than re-deriving repo paths or manifest logic in each subsystem

## Error Handling

- Subprocess-heavy code tends to return structured dictionaries describing success, exit code, stdout, stderr, timeout, and cleanup status
- Validation is explicit and fail-fast for malformed config files or invalid manifests
- CLI entrypoints generally return numeric exit codes instead of swallowing failures
- Status/reporting commands prefer incomplete-but-useful output over crashing when an artifact is missing

## Logging

- There is no centralized logging framework
- Operational commands print either JSON payloads or compact markdown/text reports to stdout
- Diagnostic richness lives in generated report files, manifest metadata, and captured stderr previews rather than log streams

## Comments

- Comments are relatively sparse
- Most explanation is carried by function names and decomposed helpers instead of heavy inline narration
- When comments appear, they are usually tactical, for example around optional runtime dependencies or wrapper behavior

## Function Design

- `parse_args()` plus `main()` is the dominant CLI pattern
- Helper names are descriptive and action-oriented: `build_report`, `load_json`, `resolve_project_root`, `write_manifest`, `run_json_command`
- Pure-ish helpers are used where possible for normalization, hashing, rendering, and report assembly so they can be tested with fixtures
- Path and config objects are usually passed explicitly instead of hidden in globals, although some older modules still keep `PROJECT_ROOT` constants

## Module Design

- The intended boundary is package-first: implementation in `src/pdfmd/*`, compatibility surfaces in `src/pdfmd/cli/*` and `skills/.../scripts/*`
- Extraction work is ongoing: some concerns are well-separated into helper modules, but the main converter and some benchmark modules are still very large
- Tests, baselines, and references remain under the skill directory because the historical command surface still matters
- GSD planning files under `.planning/` are treated as authoritative project-state artifacts, not disposable notes

---

*Convention analysis: 2026-03-15*
*Update after coding-style or command-surface shifts*
