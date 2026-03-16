# Codebase Concerns

**Analysis Date:** 2026-03-15

## Tech Debt

- `src/pdfmd/convert/convert_pdf.py` is still the dominant hotspot at roughly 4.3k lines, which keeps conversion logic hard to reason about and hard to regression-proof
- `src/pdfmd/benchmarks/remote_backends.py`, `src/pdfmd/benchmarks/embedding_space.py`, and `src/pdfmd/gates/quality_gate.py` are also large enough to deserve further decomposition
- The repo still carries two compatibility surfaces, `skills/pdf-to-structured-markdown/scripts/` and `src/pdfmd/cli/`, which adds maintenance cost
- Several modules still hardcode `/Users/rookslog/Projects/PDFAgentialConversion` instead of resolving paths dynamically through `pdfmd.common.paths`

## Known Bugs

- The canonical `why-ethics` gate is still red on Apple embedding runtime stability, probe drift, and a small spatial retrieval regression
- `Of Grammatology` still has overlap and prose-boundary issues in challenge-corpus smoke results
- `Otherwise than Being` still has overlap and prose-boundary issues in challenge-corpus smoke results
- The repo's current status is artifact-backed, so stale outputs can hide or misstate whether a failure is still live

## Security Considerations

- Remote experimentation depends on local SSH trust and host configuration, but the repo provides no built-in secret management or credential hygiene tooling
- `skills/pdf-to-structured-markdown/references/remote-backends.json` exposes operational host metadata and should be treated as sensitive infrastructure context
- There is no automated secret scan or pre-commit guard configured in the repository
- Large generated artifacts and copied reports can accidentally preserve environment details if shared carelessly

## Performance Bottlenecks

- Full PDF conversion and layout reconstruction are CPU-heavy and still concentrated in Python-heavy heuristics
- Embedding evaluation is expensive and sensitive to helper timeouts, especially on the canonical Apple path
- Remote backend comparison hashes directories, stages artifacts, installs requirements, and runs model inference, so it will stay slow even when correct
- Re-running gates and challenge-corpus flows against large bundles can produce substantial filesystem churn under `generated/`

## Fragile Areas

- Wrapper parity is fragile because the public command surface is intentionally duplicated
- Status and doctor outputs are only as accurate as the most recent artifacts they read
- Path portability is fragile because some modules are dynamic while others still assume the owner's absolute checkout path
- The converter's heuristics are tightly coupled to difficult scholarly books, so small edits can have broad second-order effects

## Scaling Limits

- The workflow is tuned for a handful of canonical books, not a large corpus farm or multi-user service
- There is no CI-backed distributed execution for repeated gate runs or large-scale challenge-corpus expansion
- Remote comparison is configured for a small declared backend set, not fleet management
- Generated bundles and reports will keep growing in disk usage as more books and variants are added

## Dependencies at Risk

- `PyMuPDF` and `pypdf` behavior changes can affect layout parsing and metadata harvesting
- Apple `NaturalLanguage` is macOS-only, which keeps the canonical gate path platform-specific
- The remote experiment stack depends on heavyweight ML packages and GPU/runtime compatibility outside this repo's direct control
- No lockfile is present, so dependency reproduction is weaker than it would be with pinned environment captures

## Missing Critical Features

- No CI pipeline to run `make test-fast`, `make test`, `make smoke`, or gate checks automatically
- No portable environment bootstrap for the full local-plus-remote toolchain
- No first-class dashboard for historical gate, smoke, and backend comparison trends
- No single completed extraction pass that fully decomposes the remaining giant converter and benchmark modules

## Test Coverage Gaps

- Real end-to-end PDF conversion over the canonical books is not covered by fast automated unit tests
- Real Apple embedding helper hangs and runtime cleanup behavior are only partially modeled in tests
- Real SSH, `rsync`, and GPU-host execution are mostly covered through dry runs and fakes rather than live automation
- There is no coverage tool to quantify how much of the converter path is exercised

## DevOps Gaps

- No `.github/` automation for CI, releases, or scheduled verification
- No container definition, reproducible environment lock, or bootstrap script for the whole workspace
- Codebase-map refresh still relies on local Codex availability through `make map`
- Artifact retention, cleanup, and archival are manual conventions rather than enforced automation

---

*Concern analysis: 2026-03-15*
*Update after major risk reduction, CI adoption, or portability fixes*
