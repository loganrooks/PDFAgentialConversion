---
phase: 05-cross-book-extractor-closure
plan: 02
model: gpt-5.4
context_used_pct: 58
subsystem: of-grammatology-structural-closure
tags: [phase-05, structure, page-mapping, toc, of-grammatology, regressions]
requires:
  - phase: 05-cross-book-extractor-closure
    plan: 01
    provides: cross-book exact-case packet and strengthened source-specific regression surface
provides:
  - Audit-clean Of Grammatology structure with no overlapping leaf ranges
  - Same-page boundary handling that respects explicit and inline headings on the Initial Debate / II. Imitation / Interval handoff
  - Narrow OCR title repair for the symbolic Outside/Inside section title
  - Strict regression coverage for the repaired Of Grammatology structural cases
affects: [phase-05, cross-book, page-mapping, toc, regressions, tests]
tech-stack:
  added: []
  patterns: [explicit-heading precedence, inline subheading cutoff detection, narrow OCR title normalization]
key-files:
  created:
    - .planning/phases/05-cross-book-extractor-closure/05-02-SUMMARY.md
  modified:
    - src/pdfmd/convert/convert_pdf.py
    - skills/pdf-to-structured-markdown/tests/test_page_mapping.py
    - skills/pdf-to-structured-markdown/tests/test_toc_structure.py
    - skills/pdf-to-structured-markdown/references/of-grammatology-regressions.json
key-decisions:
  - "Treat an entry's own heading band as stronger evidence than lowercase continuation when resolving shared-page boundaries."
  - "Support inline subheading cutoffs by matching title-prefixed lines, not only exact standalone heading lines."
  - "Repair the malformed symbolic Outside/Inside title with a narrow OCR normalization rule instead of broad title rewriting."
patterns-established:
  - "Explicit-heading precedence: a real section heading on the boundary page blocks the previous section from inheriting the page by lowercase-continuation heuristics alone."
  - "Inline heading cutoff: same-page section starts can be cut at a line that begins with the section title plus following prose."
duration: 86min
completed: 2026-03-15
---

# Phase 05 Plan 02 Summary

**Of Grammatology is structurally clean now, which means Phase 05 can move on to prose-boundary repair without carrying hidden page-map or placeholder-title debt forward.**

## Performance
- **Duration:** 86min
- **Tasks:** 2
- **Files modified:** 4
- **Files created:** 1

## Accomplishments
- Removed the last `Of Grammatology` structural overlap by tightening same-page boundary handling around `The Initial Debate and the Composition of the Essay`, `II. Imitation`, and `The Interval and the Supplement`.
- Added inline heading detection so `The Interval and the Supplement` starts at its actual inline subheading instead of borrowing the top-of-page sibling band.
- Prevented explicit heading pages from being reattached to the previous section just because the first post-heading prose fragment starts lowercase.
- Repaired the malformed TOC/body title `The Outside� the Inside` to `The Outside )( the Inside` with a narrow OCR-specific normalization rule.
- Promoted the repaired `Of Grammatology` structural cases into strict regressions without broadening into prose-boundary expectations.

## Measured Current Surface
- `Of Grammatology`
  - audit: `pass` with `0` issues
  - probe: `38` issues
  - summary: `rag_block_lowercase_start=30`, `rag_block_dangling_end=4`, `rag_block_hyphen_end=2`, `repeated_adjacent_word=2`
  - max atomic chunk: `1591`
- `Specters of Marx`
  - remains clean: audit `pass`, probe `0`, max atomic `1584`
- `Otherwise than Being`
  - still active: audit `warn` with `overlapping_leaf_ranges` and `high_complex_layout_ratio`
- `why-ethics`
  - canonical gate re-ran green after the structural fixes and regression promotion

## Task Commits
1. **Task 1: Remove the remaining Of Grammatology structural residue** — `0c3ad86`
2. **Task 2: Promote the repaired Of Grammatology structural cases into strict regressions** — `667d055`

## Files Created/Modified
- `src/pdfmd/convert/convert_pdf.py` - Same-page boundary logic now prioritizes explicit and inline headings correctly, and narrow OCR normalization repairs the symbolic Outside/Inside title.
- `skills/pdf-to-structured-markdown/tests/test_page_mapping.py` - Added direct guards for inline subheading cutoffs and complementary slices across the repaired Of Grammatology boundary.
- `skills/pdf-to-structured-markdown/tests/test_toc_structure.py` - Added coverage for the symbolic OCR title normalization.
- `skills/pdf-to-structured-markdown/references/of-grammatology-regressions.json` - Expanded strict regression coverage for the repaired TOC/body/section boundary cases.

## Decisions & Deviations
- No deviation from the plan boundary: this slice stayed structural only and did not introduce broad prose-boundary repair heuristics.

## User Setup Required
None.

## Next Phase Readiness
Plan 05-03 can now focus on prose-boundary repair and variant comparison. `Of Grammatology` no longer needs structural cleanup, and `Specters of Marx` remains a clean negative control.

## Verification
- `make test-fast`
- `python3 -m unittest discover -s skills/pdf-to-structured-markdown/tests -p 'test_page_mapping.py' -v`
- `python3 -m unittest discover -s skills/pdf-to-structured-markdown/tests -p 'test_toc_structure.py' -v`
- `python3 skills/pdf-to-structured-markdown/scripts/run_challenge_corpus.py skills/pdf-to-structured-markdown/references/challenge-corpus.json --gate-mode soft --force`
- `python3 skills/pdf-to-structured-markdown/scripts/check_regressions.py generated/of-grammatology skills/pdf-to-structured-markdown/references/of-grammatology-regressions.json --strict`
- `make smoke`
- `make gate`

## Self-Check: PASSED
