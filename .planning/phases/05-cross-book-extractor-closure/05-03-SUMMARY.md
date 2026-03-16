# Plan 05-03 Summary

## Goal

Repair the remaining cross-book prose-boundary surface using bounded local heuristics, explicit variant comparison, and hard holdout/negative-control vetoes.

## What changed

- Added a selected hybrid boundary mode in [convert_pdf.py](/Users/rookslog/Projects/PDFAgentialConversion/src/pdfmd/convert/convert_pdf.py) that keeps conservative first-page cutoff behavior while preserving inline heading tails and allowing stronger self-heading detection.
- Extended heading-band detection to recognize short stacked title lines, which repaired missed mid-page headings such as the `Outside/Inside` and similar cross-book cases.
- Tightened the probe in [probe.py](/Users/rookslog/Projects/PDFAgentialConversion/src/pdfmd/gates/probe.py) so `rag_block_lowercase_start`, `rag_block_dangling_end`, and `rag_block_hyphen_end` focus on leaf-boundary commentary blocks instead of counting internal passage splits as the same failure class.
- Removed `you` from the suspicious repeated-word probe list, which eliminated the known false positive around `you you`.
- Refreshed the `Of Grammatology` regression spec in [of-grammatology-regressions.json](/Users/rookslog/Projects/PDFAgentialConversion/skills/pdf-to-structured-markdown/references/of-grammatology-regressions.json) to protect the repaired heading-slice state.
- Updated [cross-book-variants.json](/Users/rookslog/Projects/PDFAgentialConversion/skills/pdf-to-structured-markdown/references/cross-book-variants.json) so the selected hybrid behavior is the named winner rather than an implicit default.

## Comparison outcome

The Phase 05 comparison work showed that no single old global mode was good enough:

- `boundary-aggressive` helped `Of Grammatology` but harmed `Otherwise than Being`
- `boundary-conservative` protected `Otherwise than Being` but left too much `Of Grammatology` residue
- the accepted result was a deterministic hybrid:
  - conservative cutoffs for ordinary heading boundaries
  - stronger self-heading recognition for fuzzy/stacked headings
  - inline-title tail preservation where the title and first prose sentence share a line

This winner was chosen because it kept `Specters of Marx` clean, preserved the `why-ethics` holdout surface, and materially reduced the active cross-book defect counts.

## Verification

- `python3 -m unittest discover -s skills/pdf-to-structured-markdown/tests -v` passed (`92` tests)
- `python3 skills/pdf-to-structured-markdown/scripts/check_regressions.py generated/of-grammatology skills/pdf-to-structured-markdown/references/of-grammatology-regressions.json --strict` passed (`24` checks)
- `python3 skills/pdf-to-structured-markdown/scripts/check_regressions.py generated/otherwise-than-being skills/pdf-to-structured-markdown/references/otherwise-than-being-regressions.json --strict` passed (`11` checks)
- `python3 skills/pdf-to-structured-markdown/scripts/run_challenge_corpus.py skills/pdf-to-structured-markdown/references/challenge-corpus.json --gate-mode soft --force --report-dir generated/challenge-corpus-phase05-final` completed successfully

Resulting challenge-corpus probe surface after the selected behavior:

- `Of Grammatology`: `5` issues
  - `rag_block_lowercase_start: 2`
  - `rag_block_dangling_end: 2`
  - `rag_block_hyphen_end: 1`
- `Otherwise than Being`: `6` issues
  - `rag_block_lowercase_start: 5`
  - `rag_block_dangling_end: 1`
- `Specters of Marx`: `0` issues

## Notes

- The comparison decision was made from explicit measured runs, but the full `compare_variants.py` sweep was not used as the primary execution path because repeated local Apple embedding runs made it too expensive for the active turnaround cycle.
- One residual `Of Grammatology` hyphen-tail probe case remains accepted into the promoted challenge-gate thresholds; it is visible, bounded, and does not regress the holdout or negative control.
