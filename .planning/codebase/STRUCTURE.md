# Codebase Structure

**Analysis Date:** 2026-03-15

## Directory Layout

```text
.
├── .planning/
│   ├── codebase/
│   ├── phases/
│   ├── PROJECT.md
│   ├── REQUIREMENTS.md
│   ├── ROADMAP.md
│   └── STATE.md
├── generated/
├── skills/
│   └── pdf-to-structured-markdown/
│       ├── references/
│       ├── scripts/
│       ├── tests/
│       ├── agents/
│       └── SKILL.md
├── src/
│   └── pdfmd/
│       ├── benchmarks/
│       ├── cli/
│       ├── common/
│       ├── convert/
│       ├── gates/
│       └── ops/
├── README.md
├── Makefile
└── pyproject.toml
```

## Directory Purposes

- `.planning/` stores durable project state, roadmap artifacts, phase plans, and codebase maps
- `generated/` stores runtime outputs only: converted bundles, gate reports, smoke reports, backend comparisons, and manifests
- `skills/pdf-to-structured-markdown/references/` stores frozen configs, baselines, benchmark inputs, and protocol docs
- `skills/pdf-to-structured-markdown/scripts/` stores stable wrapper scripts and Swift helpers
- `skills/pdf-to-structured-markdown/tests/` stores the canonical `unittest` suite and JSON fixtures
- `src/pdfmd/common/` stores shared path, IO, manifest, and runtime helpers
- `src/pdfmd/convert/` stores bundle-generation logic and extracted conversion seams
- `src/pdfmd/gates/` stores audits, probes, regressions, review packets, and challenge-corpus logic
- `src/pdfmd/benchmarks/` stores retrieval, embedding, calibration, remote backend, and variant-comparison logic
- `src/pdfmd/ops/` stores operator-facing health commands
- `src/pdfmd/cli/` stores thin package entrypoints that mirror the script layer

## Key File Locations

- Project metadata: `pyproject.toml`
- Canonical operator commands: `Makefile`
- Workspace overview: `README.md`
- Skill contract: `skills/pdf-to-structured-markdown/SKILL.md`
- Shared repo paths: `src/pdfmd/common/paths.py`
- Shared manifests: `src/pdfmd/common/manifests.py`
- Main converter: `src/pdfmd/convert/convert_pdf.py`
- Gate orchestrator: `src/pdfmd/gates/quality_gate.py`
- Challenge corpus runner: `src/pdfmd/gates/challenge_corpus.py`
- Remote backend harness: `src/pdfmd/benchmarks/remote_backends.py`
- Status surface: `src/pdfmd/ops/status_snapshot.py`
- Canonical wrapper-parity tests: `skills/pdf-to-structured-markdown/tests/test_wrapper_parity.py`
- Canonical project-ops tests: `skills/pdf-to-structured-markdown/tests/test_project_ops.py`

## Naming Conventions

- Python modules use `snake_case`
- Package modules are grouped by subsystem under `pdfmd.<subsystem>`
- Command modules are verb-first and mirror the operator command name, for example `run_quality_gate`, `compare_embedding_backends`, `status_snapshot`, and `convert_pdf`
- Script wrapper filenames match the corresponding package entrypoint names exactly
- Tests use `test_*.py`
- Generated bundle ids and report directories use kebab-case, for example `why-ethics` and `challenge-corpus`

## Where to Add New Code

- Add new conversion heuristics and extracted converter seams under `src/pdfmd/convert/`
- Add new artifact checks, report builders, or corpus rules under `src/pdfmd/gates/`
- Add retrieval or embedding experiments under `src/pdfmd/benchmarks/`
- Add new shared path, manifest, or runtime utilities under `src/pdfmd/common/`
- Add operator-facing summaries under `src/pdfmd/ops/`
- If a new command must preserve the historical skill surface, wire three places:
  - implementation in `src/pdfmd/<subsystem>/`
  - package entrypoint in `src/pdfmd/cli/`
  - wrapper in `skills/pdf-to-structured-markdown/scripts/`

## Special Directories

- `generated/why-ethics/` is the canonical local holdout bundle and gate output area
- `generated/challenge-corpus/` stores out-of-sample smoke artifacts
- `generated/embedding-backend-comparison/` stores timestamped local-vs-remote comparison runs
- `skills/pdf-to-structured-markdown/tests/fixtures/` holds JSON fixture cases for pure-logic tests
- `skills/pdf-to-structured-markdown/references/baselines/` holds frozen compact baselines used by gates and smoke checks
- `.planning/codebase/` is the maintained repo map used by later GSD planning steps

---

*Structure analysis: 2026-03-15*
*Update after moving directories or changing ownership rules*
