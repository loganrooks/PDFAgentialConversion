---
phase: 04-restore-the-canonical-holdout
plan: 02
model: gpt-5
context_used_pct: 53
subsystem: holdout-characterization
tags: [why-ethics, probe, retrieval, fixtures, diagnostics]
requires:
  - phase: 04-restore-the-canonical-holdout
    plan: 01
    provides: trustworthy calibrated gate runtime
provides:
  - Exact probe-case diagnostics keyed to stable why-ethics holdout scopes
  - Exact retrieval miss diagnostics for the regressed spatial runs
  - Characterization fixtures that capture current holdout drift before repair
affects: [phase-04, why-ethics, probe, retrieval, tests]
tech-stack:
  added: []
  patterns: [case-key diagnostics, characterization-first fixtures]
key-files:
  created:
    - .planning/phases/04-restore-the-canonical-holdout/04-02-SUMMARY.md
    - skills/pdf-to-structured-markdown/tests/fixtures/why_ethics_holdout_cases.json
  modified:
    - src/pdfmd/gates/probe.py
    - src/pdfmd/benchmarks/retrieval.py
    - skills/pdf-to-structured-markdown/tests/test_prose_fragment_repairs.py
    - skills/pdf-to-structured-markdown/tests/test_regression_scopes.py
key-decisions:
  - "Add exact-case diagnostics without changing extractor behavior so 04-03 can repair the holdout surgically."
  - "Capture the current why-ethics drift as fixtures now, even though the outputs are still wrong, because characterization precedes repair in this phase."
  - "Keep report schemas backward-compatible by extending them with issue and miss detail instead of replacing aggregate summaries."
patterns-established:
  - "Stable issue keys: probe outputs now identify holdout failures by code, path, and scope rather than by aggregate counts alone."
  - "Run-local miss packets: retrieval outputs now expose exact case/probe misses for each corpus-profile run."
duration: 31min
completed: 2026-03-15
---

# Phase 04 Plan 02 Summary

**The why-ethics holdout drift is now explicit at the case level, so the next repair slice can target named failures instead of broad symptom classes.**

## Performance
- **Duration:** 31min
- **Tasks:** 2
- **Files modified:** 4
- **Files created:** 2

## Accomplishments
- Extended the probe report with `issue_codes`, `issues_by_code`, and stable `issue_key` values so the current holdout over-cap classes are attributable to exact paths and scopes.
- Extended the retrieval report with `run_case_diagnostics` so regressed runs expose their exact miss packets instead of only aggregate MRR and hit@1 changes.
- Added real why-ethics characterization fixtures that pin the current probe and retrieval drift before any extractor repair is attempted.

## Exact Holdout Findings
- The probe over-cap surface is now fully enumerated for the three classes that exceed the frozen baseline:
  - `repeated_adjacent_word`: `5` cases
  - `rag_block_lowercase_start`: `8` cases
  - `rag_block_dangling_end`: `5` cases
- Representative keyed probe cases now include:
  - `repeated_adjacent_word::body/introduction/d-a-map.md::...::word=the`
  - `rag_block_lowercase_start::...section-a-writing-withdrawal__pp-67-74.md::...label=1b`
  - `rag_block_dangling_end::...section-b-closure-of-philosophy__pp-89-95.md::...tail=accessible in`
- The remaining spatial retrieval regression is localized, not broad:
  - `spatial_main_plus_supplement::fielded_bm25` has exactly `2` misses
  - `spatial_main_plus_supplement::chargram_tfidf` has exactly `2` misses
  - all `4` misses come from one benchmark case, `pragmatic-social-logics-table`, across the `table-lexical` and `table-conceptual` probes
- The top wrong documents are now explicit:
  - `fielded_bm25` misroutes both probes to `body/part-04-repenting-history/chapter-01-why-repent/c-social-repentance.md`
  - `chargram_tfidf` misroutes to `body/part-02-present-judgments/chapter-02-why-mediate/a-communication-and-love.md` and `body/part-03-pragmatism-pragmatics-and-method/chapter-01-why-verify/c-pragmatism-and-pragmaticism.md`

## Files Created/Modified
- `src/pdfmd/gates/probe.py` - Added stable issue keys and grouped exact-case diagnostics while preserving the existing summary fields.
- `src/pdfmd/benchmarks/retrieval.py` - Added run-local miss diagnostics keyed by case/probe for each corpus/profile run.
- `skills/pdf-to-structured-markdown/tests/fixtures/why_ethics_holdout_cases.json` - Captures the current why-ethics probe and retrieval drift as characterization fixtures.
- `skills/pdf-to-structured-markdown/tests/test_prose_fragment_repairs.py` - Verifies the probe characterization keys and counts stay tied to the intended holdout cases.
- `skills/pdf-to-structured-markdown/tests/test_regression_scopes.py` - Verifies the retrieval characterization packets stay tied to the intended regressed runs and case ids.

## Decisions & Deviations
- No extractor behavior was changed in this plan. The work stayed diagnostic-only, even though some of the newly surfaced cases make the repair path feel obvious.
- I verified the new diagnostics by running the probe and retrieval scripts directly rather than forcing another full quality-gate run, because this plan’s objective is exact holdout attribution, not yet holdout recovery.

## User Setup Required
None.

## Next Phase Readiness
Plan 04-03 can now repair the holdout minimally against explicit case packets:
- probe repairs should target the 18 keyed non-hyphen probe cases
- retrieval repairs should target the single `pragmatic-social-logics-table` benchmark case in `spatial_main_plus_supplement`

## Verification
- `make test-fast`
- `python3 -m unittest discover -s skills/pdf-to-structured-markdown/tests -p 'test_prose_fragment_repairs.py' -v`
- `python3 -m unittest discover -s skills/pdf-to-structured-markdown/tests -p 'test_regression_scopes.py' -v`
- `python3 skills/pdf-to-structured-markdown/scripts/probe_artifacts.py generated/why-ethics`
- `python3 skills/pdf-to-structured-markdown/scripts/evaluate_retrieval.py generated/why-ethics skills/pdf-to-structured-markdown/references/why-ethics-retrieval-benchmark.json --profiles fielded_bm25,chargram_tfidf,fused_rrf`

## Self-Check: PASSED
