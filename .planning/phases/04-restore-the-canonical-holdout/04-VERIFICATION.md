---
phase: 04-restore-the-canonical-holdout
verified: 2026-03-15T07:42:33Z
status: passed
score: 6/6 planning checks verified
re_verification: false
---

# Phase 04 Planning Verification Report

**Phase Goal:** Return `why-ethics` to the frozen structural, probe, retrieval, and embedding baselines before any new extractor wave is accepted.
**Verified:** 2026-03-15
**Status:** PASSED
**Research:** Skipped — project config has `research_enabled: false`
**Runtime mode:** Sequential inline planning — Codex runtime does not support Task-tool subagents

## Planning Checks

| Check | Status | Notes |
|---|---|---|
| Phase validated against roadmap | VERIFIED | `gsd-tools init plan-phase "4"` resolved Phase 04 and `roadmap get-phase "04"` matched `Restore the canonical holdout` |
| Phase context loaded early | VERIFIED | `04-CONTEXT.md` was used as the controlling scope: restore `why-ethics` before further extractor heuristics |
| Existing plans checked | VERIFIED | Phase directory already existed with only `04-CONTEXT.md`; there were no prior Phase 04 plans to overwrite |
| Runtime reliability addressed before product repair | VERIFIED | Plan 04-01 calibrates the Apple timeout path and restores trustworthy gate completion before holdout repair begins |
| Characterization precedes repair | VERIFIED | Plan 04-02 creates exact why-ethics delta diagnostics and fixtures before Plan 04-03 changes extractor behavior |
| Plans are phase-bounded and hand off cleanly | VERIFIED | The plan set restores only the canonical why-ethics holdout, keeps cross-book closure in Phase 05, and keeps `why-comment` deferred to Phase 06 |

## Plan Set Summary

| Plan | Wave | Purpose |
|---|---:|---|
| 04-01 | 1 | Calibrate Apple embedding runtime and make the canonical gate use measured defaults |
| 04-02 | 2 | Surface exact why-ethics probe/retrieval deltas and lock them into characterization fixtures |
| 04-03 | 3 | Apply the minimal why-ethics holdout repair and promote repaired cases into strict regressions |
| 04-04 | 4 | Prove recovery with two identical successful gate runs and hand off cleanly to Phase 05 |

## Checker Verdict

No blocking issues found in the inline verification pass.

### Why the plan passes

- It respects the phase boundary:
  - Phase 04 restores the canonical why-ethics holdout
  - Phase 05 remains the cross-book closure phase
  - Phase 06 remains the deferred `why-comment` phase
- It fixes the earlier sequencing mistake by making planning and execution order explicit:
  - runtime calibration first
  - characterization second
  - repair third
  - final two-run proof last
- It stays open to alternatives without letting alternatives sprawl:
  - multiple repair routes are allowed only inside the bounded holdout slice
  - the simplest passing variant wins
  - losing toggles are removed after selection
- It keeps the negative control and phase boundary visible:
  - `Specters of Marx` must remain unchanged
  - cross-book improvement work is explicitly deferred

## Notes

- Research remained disabled, so planning and checking were done inline.
- `roadmap get-phase "4"` did not match until the phase id was normalized to `04`; the verified plan uses the padded phase id.
- The current gate is still red; this plan is specifically built to restore it before any broader extractor work resumes.

---

_Verified: 2026-03-15_  
_Verifier: Codex inline plan checker_
