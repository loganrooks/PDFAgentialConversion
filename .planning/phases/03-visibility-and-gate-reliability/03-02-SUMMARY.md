---
phase: 03-visibility-and-gate-reliability
plan: 02
model: gpt-5
context_used_pct: 46
subsystem: gate-runtime
tags: [calibration, timeout, runtime-diagnostics]
requires:
  - phase: 03-visibility-and-gate-reliability
    plan: 01
    provides: standardized manifests, runtime classification base
provides:
  - Calibration reporting that either yields a measured timeout or an explicit blocked-runtime result
  - Gate runtime metadata that carries calibration context forward into the quality-gate artifacts
  - Wrapper-compatible calibration CLI with positional bundle and benchmark arguments
affects: [phase-03, calibration, quality-gate, tests]
tech-stack:
  added: []
  patterns: [blocked-calibration reporting, calibration-ready gate config]
key-files:
  created: []
  modified:
    - src/pdfmd/benchmarks/calibration.py
    - src/pdfmd/gates/quality_gate.py
    - skills/pdf-to-structured-markdown/references/why-ethics-quality-gate.json
    - skills/pdf-to-structured-markdown/tests/test_project_ops.py
key-decisions:
  - "Stop calibration early on the first blocking runtime failure and record that honestly instead of wasting four more runs."
  - "Keep the configured gate timeout unchanged until calibration can complete successfully; store calibration intent and metadata without pretending the runtime is already stable."
patterns-established:
  - "Blocked calibration artifact: a failed runtime calibration now produces a useful machine-readable report instead of just exiting nonzero."
  - "Calibration-ready gate config: runtime-gate settings now carry the calibration rule and target report location."
duration: 17min
completed: 2026-03-15
---

# Phase 03 Plan 02 Summary

**The timeout-calibration path now behaves like a real runtime diagnostic: it either returns a measured recommendation or a clear blocked-runtime result, and the gate config records that calibration intent explicitly.**

## Performance
- **Duration:** 17min
- **Tasks:** 2
- **Files modified:** 4

## Accomplishments
- Made the calibration CLI wrapper-compatible by accepting positional bundle and benchmark paths while keeping the named flags.
- Reworked calibration reporting so blocked runs stop early, classify the failure, and refuse to emit a fake timeout recommendation.
- Added calibration metadata to the canonical why-ethics gate config and surfaced that calibration context in gate runtime artifacts.

## Task Commits
1. **Task 1: Calibrate Apple embedding timeout from repeated local measurements** - `dd8b97f`
2. **Task 2: Integrate runtime diagnostics and two-run stability signatures into the quality gate** - `dd8b97f`

## Files Created/Modified
- `src/pdfmd/benchmarks/calibration.py` - Calibration now supports positional args, early blocking failure exit, and explicit blocked-vs-calibrated reporting.
- `src/pdfmd/gates/quality_gate.py` - Gate runtime output now carries calibration metadata from config.
- `skills/pdf-to-structured-markdown/references/why-ethics-quality-gate.json` - Runtime gate config now records the calibration rule and report location.
- `skills/pdf-to-structured-markdown/tests/test_project_ops.py` - Added calibration parsing and report-behavior coverage.

## Decisions & Deviations
- [Rule 3 - Blocking] The current Apple embedding helper still times out on the local machine, so the calibration command was verified in blocked-runtime mode with `--helper-timeout-seconds 5`. The tool now records that blocked state explicitly instead of implying a stable recommendation exists.

## User Setup Required
None.

## Next Phase Readiness
Phase 03 can move to operator-surface polish with a calibration path that is honest about the current runtime instability.

## Verification
- `make test-fast`
- `python3 -m unittest discover -s skills/pdf-to-structured-markdown/tests -p 'test_project_ops.py' -v`
- `python3 skills/pdf-to-structured-markdown/scripts/calibrate_embedding_timeout.py generated/why-ethics skills/pdf-to-structured-markdown/references/why-ethics-retrieval-benchmark.json --runs 5 --helper-timeout-seconds 5`

## Self-Check: PASSED
