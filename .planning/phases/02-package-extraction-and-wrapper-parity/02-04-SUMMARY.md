---
phase: 02-package-extraction-and-wrapper-parity
plan: 04
model: gpt-5
context_used_pct: 56
subsystem: converter
tags: [convert, metadata, toc, page-mapping, rag, render]
requires:
  - phase: 02-01
    provides: shared paths and manifest helpers
  - phase: 02-02
    provides: thin CLI extraction pattern for benchmark tools
  - phase: 02-03
    provides: thin CLI extraction pattern for gate tools
provides:
  - Real converter implementation under `pdfmd.convert.convert_pdf`
  - Extracted converter seam modules under `pdfmd.convert`
  - A wrapper-path smoke test for the converter command surface
affects: [phase-02, converter, test-suite]
tech-stack:
  added: []
  patterns: [package-first converter logic, seam extraction, wrapper smoke test]
key-files:
  created:
    - src/pdfmd/convert/metadata.py
    - src/pdfmd/convert/toc.py
    - src/pdfmd/convert/page_mapping.py
    - src/pdfmd/convert/layout.py
    - src/pdfmd/convert/rag.py
    - src/pdfmd/convert/render.py
    - src/pdfmd/convert/output.py
    - skills/pdf-to-structured-markdown/tests/test_convert_cli_smoke.py
  modified:
    - src/pdfmd/convert/convert_pdf.py
    - src/pdfmd/cli/convert_pdf.py
key-decisions:
  - "Move the full converter implementation behind `pdfmd.convert.convert_pdf` first, then expose grouped seam modules to make the codebase glanceable without changing behavior."
  - "Use a patched tiny-PDF smoke test to verify the wrapper -> CLI -> package handoff without requiring a full book conversion in every test run."
patterns-established:
  - "Converter package first: the CLI wrapper now only re-exports the package implementation."
duration: 28min
completed: 2026-03-15
---

# Phase 02 Plan 04 Summary

**The converter is no longer a monolithic CLI file: the real implementation now lives under `pdfmd.convert`, coherent seam modules exist, and the command path has direct smoke coverage.**

## Performance
- **Duration:** 28min
- **Tasks:** 2
- **Files modified:** 10

## Accomplishments
- Moved the full converter implementation behind `src/pdfmd/convert/convert_pdf.py` and converted the old CLI module into a thin package delegate.
- Added extracted converter seam modules for metadata, TOC, page-mapping, layout, RAG, rendering, and output, plus a real smoke test for the wrapper command path.

## Task Commits
1. **Task 1: Extract pure converter seams into `pdfmd.convert` modules** - same plan commit
2. **Task 2: Add converter CLI smoke coverage for the package split** - same plan commit

## Files Created/Modified
- `src/pdfmd/convert/convert_pdf.py` - Primary converter implementation moved out of the CLI home.
- `src/pdfmd/convert/metadata.py` - Metadata harvesting seam module.
- `src/pdfmd/convert/toc.py` - ToC parsing and output-path seam module.
- `src/pdfmd/convert/page_mapping.py` - Page-mapping seam module.
- `src/pdfmd/convert/layout.py` - Layout and prose-fragment seam module.
- `src/pdfmd/convert/rag.py` - RAG assembly and segmentation seam module.
- `src/pdfmd/convert/render.py` - Markdown/spatial rendering seam module.
- `src/pdfmd/convert/output.py` - Bundle output helpers.
- `src/pdfmd/cli/convert_pdf.py` - Thin CLI re-export to the convert package.
- `skills/pdf-to-structured-markdown/tests/test_convert_cli_smoke.py` - Wrapper-path smoke coverage with a tiny synthetic PDF.

## Decisions & Deviations
None - followed the plan as specified.

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
Phase 02 can now finish with wrapper-parity coverage, refreshed docs, and the end-of-phase verification matrix.

## Verification
- `python3 -m unittest discover -s skills/pdf-to-structured-markdown/tests -p 'test_metadata_harvesting.py' -v`
- `python3 -m unittest discover -s skills/pdf-to-structured-markdown/tests -p 'test_toc_structure.py' -v`
- `python3 -m unittest discover -s skills/pdf-to-structured-markdown/tests -p 'test_page_mapping.py' -v`
- `python3 -m unittest discover -s skills/pdf-to-structured-markdown/tests -p 'test_prose_fragment_repairs.py' -v`
- `python3 -m unittest discover -s skills/pdf-to-structured-markdown/tests -p 'test_rag_segmentation.py' -v`
- `python3 -m unittest discover -s skills/pdf-to-structured-markdown/tests -p 'test_convert_cli_smoke.py' -v`

## Self-Check: PASSED
