# Entrypoints

## Canonical Local Commands

- `make test-fast`
  - compile package and wrapper code
  - run fast operator-surface and wrapper-parity tests
- `make test`
  - run the full `unittest` suite
- `make gate`
  - run the canonical `why-ethics` quality gate
  - supports overrides through `GATE_ARGS`
- `make smoke`
  - run the challenge-corpus smoke workflow in report-only mode
  - supports overrides through `SMOKE_ARGS`
- `make compare-backends`
  - run the embedding backend comparison in dry-run mode by default
  - supports overrides through `COMPARE_BACKENDS_ARGS`
- `make status`
  - render the at-a-glance project state snapshot
- `make doctor`
  - render local Apple and optional remote backend readiness
- `make map`
  - refresh `.planning/codebase/` through the GSD codebase-mapping workflow

## Stable Script Wrappers

- `skills/pdf-to-structured-markdown/scripts/convert_pdf.py`
- `skills/pdf-to-structured-markdown/scripts/run_quality_gate.py`
- `skills/pdf-to-structured-markdown/scripts/run_challenge_corpus.py`
- `skills/pdf-to-structured-markdown/scripts/evaluate_embedding_space.py`
- `skills/pdf-to-structured-markdown/scripts/evaluate_retrieval.py`
- `skills/pdf-to-structured-markdown/scripts/compare_embedding_backends.py`
- `skills/pdf-to-structured-markdown/scripts/compare_variants.py`
- `skills/pdf-to-structured-markdown/scripts/status_snapshot.py`
- `skills/pdf-to-structured-markdown/scripts/doctor.py`

## Package Module Homes

- Conversion:
  - `src/pdfmd/convert/*`
- Gates:
  - `src/pdfmd/gates/*`
- Benchmarks:
  - `src/pdfmd/benchmarks/*`
- Operator surfaces:
  - `src/pdfmd/ops/*`
- Thin compatibility entrypoints:
  - `src/pdfmd/cli/*`

## Runtime Artifact Roots

- Canonical holdout bundle:
  - `generated/why-ethics/`
- Canonical gate artifacts:
  - `generated/why-ethics/quality-gate/`
- Challenge-corpus smoke artifacts:
  - `generated/challenge-corpus/`
- Backend-comparison artifacts:
  - `generated/embedding-backend-comparison/`
