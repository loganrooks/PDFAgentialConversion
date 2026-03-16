# Technology Stack

**Analysis Date:** 2026-03-15

## Languages

**Primary:**
- Python 3.11+ - All product code, operator commands, tests, conversion logic, gates, and benchmark tooling in `src/pdfmd/` and `skills/pdf-to-structured-markdown/tests/`

**Secondary:**
- Swift - Apple `NaturalLanguage` embedding helpers in `skills/pdf-to-structured-markdown/scripts/apple_nl_embed.swift` and `skills/pdf-to-structured-markdown/scripts/apple_nl_similarity.swift`
- Markdown - Human-facing reports, bundle outputs, skill docs, and planning state in `.planning/`
- JSON - Config, baselines, manifests, benchmark inputs, and generated reports under `skills/pdf-to-structured-markdown/references/` and `generated/`

## Runtime

**Environment:**
- Local Python interpreter invoked as `python3`
- macOS is the canonical local runtime because the accepted embedding gate path depends on Apple `NaturalLanguage`
- Optional remote Linux GPU host accessed over SSH for experiment-only `sentence-transformers` runs

**Package Manager:**
- `pip` via editable install from `make bootstrap`
- Build backend: `setuptools` from `pyproject.toml`
- Lockfile: none present

## Frameworks

**Core:**
- No web framework or application server; this is a CLI-first tooling repo
- `setuptools` package layout with source under `src/`

**Testing:**
- Standard-library `unittest` discovered from `skills/pdf-to-structured-markdown/tests/`
- `compileall` used by `make test-fast` as a cheap syntax/import sanity check

**Build/Dev:**
- `Makefile` is the canonical operator surface for local workflows
- `codex exec` is used by `make map` to refresh `.planning/codebase`

## Key Dependencies

**Critical:**
- `PyMuPDF>=1.24.0` - Layout-aware PDF parsing for body extraction and spatial diagnostics
- `pypdf>=5.0.0` - PDF metadata and document structure access
- Python standard library - `argparse`, `subprocess`, `json`, `pathlib`, `tempfile`, `unittest`, and `hashlib` are used heavily across every subsystem

**Infrastructure:**
- Apple `swift` toolchain - Executes the local embedding helpers used by retrieval and gate flows
- Remote experiment stack from `skills/pdf-to-structured-markdown/references/remote-embedding-requirements.txt` - `torch`, `transformers`, `sentence-transformers`, and `numpy` on the GPU host
- SSH, `rsync`, and `tar` - Used by `src/pdfmd/benchmarks/remote_backends.py` for remote staging and artifact retrieval

## Configuration

**Environment:**
- Default paths are mostly repo-relative through `pdfmd.common.paths`, but several benchmark and gate modules still hardcode `/Users/rookslog/Projects/PDFAgentialConversion`
- `PDFMD_VARIANT_ID` labels gate and benchmark outputs
- `CUDA_VISIBLE_DEVICES` is forwarded to remote backend bootstrap scripts

**Build:**
- `pyproject.toml` defines the package and editable-install layout
- `Makefile` defines the canonical local command surface
- JSON configs live under `skills/pdf-to-structured-markdown/references/`, especially `why-ethics-quality-gate.json`, `challenge-corpus.json`, `why-ethics-retrieval-benchmark.json`, and `remote-backends.json`

## Platform Requirements

**Development:**
- Local repo checkout with source PDFs available at the project root
- Python 3.11+ and `swift` for the canonical local gate path
- No containerized development environment or pinned lockfile

**Production:**
- No deployed service; the repo is an operator workspace and local tooling surface
- Canonical validation target is the local Mac workflow
- Remote GPU hosts are explicitly report-only and must not redefine the canonical gate outcome

---

*Stack analysis: 2026-03-15*
*Update after major dependency, runtime, or toolchain changes*
