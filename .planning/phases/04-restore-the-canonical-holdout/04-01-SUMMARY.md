---
phase: 04-restore-the-canonical-holdout
plan: 01
model: gpt-5
context_used_pct: 39
subsystem: gate-runtime
tags: [calibration, timeout, runtime-diagnostics, why-ethics]
requires:
  - phase: 03-visibility-and-gate-reliability
    plan: 02
    provides: blocked-runtime calibration path and gate runtime metadata
  - phase: 03-visibility-and-gate-reliability
    plan: 03
    provides: operator visibility and manifest freshness surfaces
provides:
  - Provisional timeout selection from partial successful calibration runs
  - Canonical why-ethics gate execution that consumes calibrated runtime defaults automatically
  - Test coverage proving calibration beats config defaults unless explicitly overridden
affects: [phase-04, calibration, quality-gate, why-ethics, tests]
tech-stack:
  added: []
  patterns: [provisional calibration recommendation, calibrated gate timeout selection]
key-files:
  created:
    - .planning/phases/04-restore-the-canonical-holdout/04-01-SUMMARY.md
  modified:
    - src/pdfmd/benchmarks/calibration.py
    - src/pdfmd/gates/quality_gate.py
    - skills/pdf-to-structured-markdown/tests/test_project_ops.py
key-decisions:
  - "Use partial successful calibration data to derive a provisional timeout instead of discarding 4 good runs because the 5th timed out."
  - "Let the canonical gate consume the freshest calibration artifact by default while preserving explicit CLI override precedence."
  - "Verify the runtime path with a single stability run here, because the two-run proof belongs to Plan 04-04."
patterns-established:
  - "Provisional calibration artifact: runtime calibration can remain honest about a blocking failure while still surfacing a measured timeout recommendation."
  - "Calibrated canonical gate: the local why-ethics gate now reaches embedding with measured defaults instead of ad hoc timeout guessing."
duration: 34min
completed: 2026-03-15
---

# Phase 04 Plan 01 Summary

**The canonical why-ethics gate now uses measured local runtime defaults, so Phase 04 can work from a trustworthy gate path instead of a blocked timeout shortcut.**

## Performance
- **Duration:** 34min active work, plus reuse of one previously completed 5-run calibration artifact
- **Tasks:** 2
- **Files modified:** 3

## Accomplishments
- Extended calibration reporting so partial success still yields a machine-readable timeout recommendation when there is enough real runtime data to support one.
- Wired the quality gate to prefer the freshest calibration artifact by default and record whether the timeout came from CLI override, calibration, or config fallback.
- Verified the canonical why-ethics gate now reaches and completes the embedding stage with the measured timeout `461s`, leaving only real holdout regressions in probe and retrieval.

## Measured Runtime Result
- The 5-run Apple helper calibration produced 4 successful runs at `227.8009s`, `223.6204s`, `223.3915s`, and `230.3159s`.
- The 5th run timed out at `240.8715s`.
- The resulting calibration artifact is intentionally honest:
  - status: `blocked_by_runtime_failure`
  - recommendation: `provisional`
  - suggested timeout: `461s`
  - rule: `max(p95 * 2, p99 + 30s)`
- A fresh canonical gate run then completed the embedding stage successfully with:
  - timeout source: `calibration_report_provisional`
  - helper timeout: `461s`
  - embedding wall-clock: `223.7151s`

## Task Commits
1. **Task 1: Calibrate the Apple embedding timeout from real why-ethics runs** - pending commit in this plan slice
2. **Task 2: Make the canonical gate consume calibrated runtime defaults** - pending commit in this plan slice

## Files Created/Modified
- `src/pdfmd/benchmarks/calibration.py` - Calibration reports now preserve provisional timeout recommendations from partial successful runs and expose helper-report loading helpers.
- `src/pdfmd/gates/quality_gate.py` - Gate runtime now resolves the embedding timeout from calibration artifacts before falling back to config and records the timeout source in the report.
- `skills/pdf-to-structured-markdown/tests/test_project_ops.py` - Added regression coverage for calibration path resolution, provisional recommendation retention, and timeout-source precedence.
- `.planning/phases/04-restore-the-canonical-holdout/04-01-SUMMARY.md` - Captures the verified runtime slice and the controlled deviations used for this plan.

## Decisions & Deviations
- [Rule 3 - Blocking] I reused the already-completed 5-run calibration sample and rewrote it through the updated report builder instead of spending another full calibration cycle to reproduce the same measurements after the code change.
- [Rule 4 - Scope discipline] I verified the gate with `make gate GATE_ARGS='--stability-runs 1'` rather than the default two-run proof because the two-consecutive-run acceptance criterion belongs to Plan 04-04, not this runtime-calibration slice.
- The gate still fails after embedding, but only for existing holdout content metrics: probe count `25 > 22` and the remaining `spatial_main_plus_supplement` retrieval regressions.

## User Setup Required
None.

## Next Phase Readiness
Plan 04-02 can now characterize the exact probe and retrieval drift without conflating product defects with runtime blockage.

## Verification
- `python3 -m unittest discover -s skills/pdf-to-structured-markdown/tests -p 'test_project_ops.py' -v`
- `make doctor`
- `make gate GATE_ARGS='--stability-runs 1'`

## Self-Check: PASSED
