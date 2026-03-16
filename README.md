# PDFAgentialConversion

Infrastructure-first workspace for converting difficult scholarly PDFs into structured markdown bundles, validating the results, and benchmarking retrieval and embedding behavior.

## What This Repo Is

This repo packages the `pdf-to-structured-markdown` skill as an actual local project:
- reproducible bundle generation
- structural and semantic verification gates
- out-of-sample challenge-corpus checks
- optional remote embedding experiments
- project planning and operational state under `.planning/`

The local Mac workflow is canonical. Remote GPU runs are experiment-only.

## Top-Level Structure

```text
.
├── .planning/                     # GSD project state, roadmap, codebase map
├── generated/                     # Runtime outputs only, not source of truth
├── skills/
│   └── pdf-to-structured-markdown/
│       ├── SKILL.md               # Codex skill entrypoint
│       ├── references/            # Baselines, contracts, benchmark configs
│       ├── scripts/               # Thin CLI wrappers
│       └── tests/                 # Canonical unittest suite
├── src/
│   └── pdfmd/                     # Product code package
│       ├── common/                # Shared paths, manifests, IO, runtime helpers
│       ├── benchmarks/            # Retrieval, embedding, backend-comparison logic
│       ├── gates/                 # Audit, probe, regressions, gate orchestration
│       ├── convert/               # Converter implementation and extracted seams
│       ├── ops/                   # Doctor/status operator surfaces
│       └── cli/                   # Thin compatibility entrypoints
├── *.pdf                          # Local source PDFs used for canonical and challenge runs
└── Makefile                       # Canonical local operator surface
```

## Canonical Commands

```bash
make bootstrap
make doctor
make status
make test-fast
make test
make gate
make smoke
make compare-backends
make map
make verify-all
```

At a glance:
- `make status` tells us the latest bundle/gate/smoke/backend state from report artifacts.
- `make doctor` tells us whether the local Apple path and optional remote backend path are actually ready.

## Current Known Active Failures

- none in the tracked local gates
- `why-ethics` is green and remains the canonical local holdout gate, now with manual packet acceptance enforced
- the challenge corpus is a hard non-regression gate:
  - `Specters of Marx` is the clean negative control and remains clean
  - `Of Grammatology` passes within its accepted residual thresholds and max atomic block `1591`
  - `Otherwise than Being` passes within its accepted residual thresholds and max atomic block `1475`
- the deferred `why-comment` `7c/7d` repair is complete
- the next workflow step is milestone audit/completion, not another hidden implementation phase

Use `make status` for the current report-backed snapshot instead of trusting this file alone.

## Artifact Policy

- `generated/` is runtime output.
- Each report directory should have a `run-manifest.json` with artifact state and freshness metadata.
- Frozen compact baselines and configs live under:
  [skills/pdf-to-structured-markdown/references/baselines](/Users/rookslog/Projects/PDFAgentialConversion/skills/pdf-to-structured-markdown/references/baselines)
- Large generated bundles are regenerated as needed and are not the main audit trail.

## Planning

This repo uses GSD state only:
- [.planning/PROJECT.md](/Users/rookslog/Projects/PDFAgentialConversion/.planning/PROJECT.md)
- [.planning/config.json](/Users/rookslog/Projects/PDFAgentialConversion/.planning/config.json)
- [.planning/REQUIREMENTS.md](/Users/rookslog/Projects/PDFAgentialConversion/.planning/REQUIREMENTS.md)
- [.planning/ROADMAP.md](/Users/rookslog/Projects/PDFAgentialConversion/.planning/ROADMAP.md)
- [.planning/STATE.md](/Users/rookslog/Projects/PDFAgentialConversion/.planning/STATE.md)

## Notes

- Existing CLI paths under `skills/pdf-to-structured-markdown/scripts/` remain supported.
- The package split is now package-first: substantive code lives under `src/pdfmd/*`, and `src/pdfmd/cli/*` plus `skills/.../scripts/*` are compatibility layers.
- Shared repo path resolution and manifest writing live in `pdfmd.common`, so operator commands and report producers do not depend on ad hoc `__file__` math.
- The canonical `make gate` path prefers a runtime calibration artifact at `generated/why-ethics/quality-gate/embedding-calibration/calibration-report.json` when present; otherwise it falls back to the configured Apple-helper timeout.
