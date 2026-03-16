---
phase: 02-package-extraction-and-wrapper-parity
plan: 02
model: gpt-5
context_used_pct: 42
subsystem: benchmarks
tags: [embedding, retrieval, remote-backends, wrappers]
requires:
  - phase: 02-01
    provides: shared paths, manifest contract, stable operator surface
provides:
  - Real benchmark implementation modules under `pdfmd.benchmarks`
  - Thin benchmark CLI shims that preserve the existing wrapper surface
  - Compatibility aliases for existing `pdfmd.benchmarks.*` import names
affects: [phase-02, benchmarks, compare-backends, embedding-eval]
tech-stack:
  added: []
  patterns: [thin-cli wrapper, compatibility alias, package-first benchmark logic]
key-files:
  created:
    - src/pdfmd/benchmarks/embedding_space.py
    - src/pdfmd/benchmarks/retrieval.py
    - src/pdfmd/benchmarks/remote_backends.py
    - src/pdfmd/benchmarks/variant_comparison.py
    - src/pdfmd/benchmarks/calibration.py
  modified:
    - src/pdfmd/cli/evaluate_embedding_space.py
    - src/pdfmd/cli/evaluate_retrieval.py
    - src/pdfmd/cli/compare_embedding_backends.py
    - src/pdfmd/cli/compare_variants.py
    - src/pdfmd/cli/calibrate_embedding_timeout.py
key-decisions:
  - "Move the real implementations first, then leave CLI files as one-line delegates to keep wrapper behavior stable."
  - "Keep compatibility aliases for the older `pdfmd.benchmarks.evaluate_*` and related import paths so tests and downstream imports do not break during the refactor."
patterns-established:
  - "Benchmark package first: substantive logic lives in `pdfmd.benchmarks`, CLI files only re-export."
duration: 16min
completed: 2026-03-15
---

# Phase 02 Plan 02 Summary

**Benchmark and experiment code now lives under `pdfmd.benchmarks`, while the CLI and script wrappers keep the existing interface stable.**

## Performance
- **Duration:** 16min
- **Tasks:** 2
- **Files modified:** 15

## Accomplishments
- Extracted the real embedding, retrieval, backend-comparison, variant-comparison, and timeout-calibration implementations into `src/pdfmd/benchmarks/`.
- Converted the CLI benchmark entrypoints into thin delegates and kept compatibility aliases for the old package import names.

## Task Commits
1. **Task 1: Extract embedding and retrieval evaluators into benchmark modules** - same plan commit
2. **Task 2: Extract backend-comparison and calibration tools into benchmark modules** - same plan commit

## Files Created/Modified
- `src/pdfmd/benchmarks/embedding_space.py` - Primary embedding-space evaluator implementation.
- `src/pdfmd/benchmarks/retrieval.py` - Primary retrieval evaluator implementation.
- `src/pdfmd/benchmarks/remote_backends.py` - Remote embedding backend comparison orchestration.
- `src/pdfmd/benchmarks/variant_comparison.py` - Heuristic variant comparison implementation.
- `src/pdfmd/benchmarks/calibration.py` - Embedding timeout calibration implementation.
- `src/pdfmd/cli/evaluate_embedding_space.py` - Thin CLI re-export to benchmark package logic.
- `src/pdfmd/cli/evaluate_retrieval.py` - Thin CLI re-export to benchmark package logic.
- `src/pdfmd/cli/compare_embedding_backends.py` - Thin CLI re-export to benchmark package logic.
- `src/pdfmd/cli/compare_variants.py` - Thin CLI re-export to benchmark package logic.
- `src/pdfmd/cli/calibrate_embedding_timeout.py` - Thin CLI re-export to benchmark package logic.

## Decisions & Deviations
None - followed the plan as specified.

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
The gate/orchestrator layer can now move behind `pdfmd.gates` using the same thin-wrapper pattern.

## Verification
- `python3 -m unittest discover -s skills/pdf-to-structured-markdown/tests -p 'test_embedding_projections.py' -v`
- `python3 -m unittest discover -s skills/pdf-to-structured-markdown/tests -p 'test_remote_embedding_backends.py' -v`
- `make compare-backends`

## Self-Check: PASSED
