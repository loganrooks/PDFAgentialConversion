---
phase: 05-cross-book-extractor-closure
plan: 01
model: gpt-5
context_used_pct: 41
subsystem: cross-book-characterization
tags: [phase-05, characterization, probe, regressions, of-grammatology, otherwise-than-being]
requires:
  - phase: 04-restore-the-canonical-holdout
    plan: 04
    provides: canonical why-ethics gate stability and clean negative-control baseline
provides:
  - Cross-book exact-case packet for the remaining Of Grammatology and Otherwise than Being repair surface
  - Self-describing probe case details for fixture-backed issue-key verification
  - Expanded source-specific regressions around currently clean Of Grammatology and Otherwise than Being outputs
affects: [phase-05, cross-book, probe, regressions, tests]
tech-stack:
  added: []
  patterns: [exact-case characterization packet, self-describing issue details, source-specific no-regression guards]
key-files:
  created:
    - .planning/phases/05-cross-book-extractor-closure/05-01-SUMMARY.md
    - skills/pdf-to-structured-markdown/tests/fixtures/cross_book_remaining_cases.json
  modified:
    - src/pdfmd/gates/probe.py
    - skills/pdf-to-structured-markdown/tests/test_prose_fragment_repairs.py
    - skills/pdf-to-structured-markdown/tests/test_range_normalization.py
    - skills/pdf-to-structured-markdown/references/of-grammatology-regressions.json
    - skills/pdf-to-structured-markdown/references/otherwise-than-being-regressions.json
key-decisions:
  - "Record representative exact failing cases as a tracked fixture packet instead of asserting live issue counts, so future repairs can improve the books without breaking characterization tests."
  - "Make probe case details self-describing by carrying the issue code in each grouped case payload."
  - "Strengthen only known-good source-specific regressions in this slice; do not encode any currently broken cross-book output as expected truth."
patterns-established:
  - "Cross-book failure packet: remaining repair work now starts from explicit path-and-scope examples rather than aggregate probe totals."
  - "Book-local guard rails: Of Grammatology and Otherwise than Being now have slightly broader clean-surface regressions before extractor changes begin."
duration: 21min
completed: 2026-03-15
---

# Phase 05 Plan 01 Summary

**Phase 05 now starts from an explicit cross-book failure packet and tighter no-regression controls, so the next repair slices can be evidence-driven instead of symptom-driven.**

## Performance
- **Duration:** 21min
- **Tasks:** 2
- **Files modified:** 5
- **Files created:** 2

## Accomplishments
- Added a tracked exact-case packet for the remaining `Of Grammatology` and `Otherwise than Being` failures, including the current overlap pairs plus representative lowercase-start, dangling-end, hyphen-end, and repeated-word cases.
- Made grouped probe cases self-describing by including `code` in `issue_case_details`, which keeps the new packet and the probe output aligned.
- Added fixture-driven tests that verify stable issue keys and current boundary-warning classification without freezing today’s broken outputs as future expectations.
- Expanded the source-specific regression specs to protect currently clean body, semantic-page, and RAG cases in both active books before extractor repair begins.

## Measured Current Surface
- `Of Grammatology`
  - audit: `overlapping_leaf_ranges`
  - probe: `34` issues
  - summary: `rag_block_lowercase_start=26`, `rag_block_dangling_end=5`, `rag_block_hyphen_end=1`, `repeated_adjacent_word=2`
- `Otherwise than Being`
  - audit: `overlapping_leaf_ranges`, `high_complex_layout_ratio`
  - probe: `25` issues
  - summary: `rag_block_lowercase_start=18`, `rag_block_dangling_end=3`, `rag_block_hyphen_end=1`, `repeated_adjacent_word=3`
- `why-ethics`
  - canonical gate re-ran cleanly after the characterization and regression-spec changes
- `Specters of Marx`
  - remained clean in the soft challenge-corpus run

## Task Commits
1. **Task 1: Build an exact-case packet for the remaining Of Grammatology and Otherwise than Being failures** — `3c951f5`
2. **Task 2: Tighten source-specific regression and negative-control coverage around the active repair surface** — `8fd3e06`

## Files Created/Modified
- `skills/pdf-to-structured-markdown/tests/fixtures/cross_book_remaining_cases.json` - Snapshot of the remaining cross-book repair surface with structural and probe examples.
- `src/pdfmd/gates/probe.py` - Grouped issue cases now carry their own `code`, which makes the exact-case packet self-describing.
- `skills/pdf-to-structured-markdown/tests/test_prose_fragment_repairs.py` - Added issue-key stability and phase-target fixture checks for the cross-book packet.
- `skills/pdf-to-structured-markdown/tests/test_range_normalization.py` - Added coverage for the current boundary-warning overlap pairs.
- `skills/pdf-to-structured-markdown/references/of-grammatology-regressions.json` - Expanded clean-surface guards around `The Program`.
- `skills/pdf-to-structured-markdown/references/otherwise-than-being-regressions.json` - Expanded clean-surface guards around `b. Language` and `a. Proximity and Space`.

## Decisions & Deviations
- None - this plan stayed within its characterization-only boundary.

## User Setup Required
None.

## Next Phase Readiness
Plan 05-02 can now focus on the remaining `Of Grammatology` structural residue with explicit overlap and scope fixtures already in place.

## Verification
- `python3 skills/pdf-to-structured-markdown/scripts/probe_artifacts.py generated/of-grammatology`
- `python3 skills/pdf-to-structured-markdown/scripts/probe_artifacts.py generated/otherwise-than-being`
- `python3 -m unittest discover -s skills/pdf-to-structured-markdown/tests -p 'test_prose_fragment_repairs.py' -v`
- `python3 -m unittest discover -s skills/pdf-to-structured-markdown/tests -p 'test_range_normalization.py' -v`
- `python3 skills/pdf-to-structured-markdown/scripts/check_regressions.py generated/of-grammatology skills/pdf-to-structured-markdown/references/of-grammatology-regressions.json --strict`
- `python3 skills/pdf-to-structured-markdown/scripts/check_regressions.py generated/otherwise-than-being skills/pdf-to-structured-markdown/references/otherwise-than-being-regressions.json --strict`
- `make gate`
- `make smoke`

## Self-Check: PASSED
