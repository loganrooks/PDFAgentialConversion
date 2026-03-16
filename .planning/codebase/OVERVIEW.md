# Codebase Overview

## Runtime Shape

- `skills/pdf-to-structured-markdown/`
  - skill contract, references, wrappers, and tests
- `src/pdfmd/`
  - product package
  - `common/` for shared paths, manifests, IO, and runtime helpers
  - `convert/` for extraction, mapping, rendering, and bundle output
  - `gates/` for audit, probe, regressions, quality-gate orchestration, and review packets
  - `benchmarks/` for retrieval, embedding, calibration, backend comparison, and variant comparison
  - `ops/` for status and doctor operator surfaces
  - `cli/` for thin compatibility entrypoints only

## Current Hotspots

- `src/pdfmd/convert/convert_pdf.py`
- `src/pdfmd/gates/quality_gate.py`
- `src/pdfmd/benchmarks/embedding_space.py`
- `src/pdfmd/benchmarks/remote_backends.py`

## Operator Entry Surface

- Root commands:
  - `make test-fast`
  - `make test`
  - `make gate`
  - `make smoke`
  - `make compare-backends`
  - `make status`
  - `make doctor`
  - `make map`
- Stable wrappers:
  - `skills/pdf-to-structured-markdown/scripts/*.py`
- Compatibility package entrypoints:
  - `src/pdfmd/cli/*.py`

## Verification Surfaces

- `make test-fast`
- `make test`
- `make gate`
- `make smoke`
- `make compare-backends`
- `make status`
- `make doctor`
- `make map`
