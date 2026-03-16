# Plan 06-01 Summary

## Goal

Lock the exact chapter-5 truth packet for the deferred `why-comment` repair before changing extractor behavior.

## What changed

- Extended [why-ethics-regressions.json](/Users/rookslog/Projects/PDFAgentialConversion/skills/pdf-to-structured-markdown/references/why-ethics-regressions.json) with strict target checks for:
  - `7c Citation`
  - `7c Commentary`
  - `7d Commentary`
- Chose target strings that are anchored in the current page-local evidence rather than in the already-broken linearization:
  - `7c Citation` now forbids lower-commentary spillover
  - `7c Commentary` now requires the later jurisprudence commentary and forbids the `Erubin 13b` inset quote from remaining in commentary
  - `7d Commentary` now forbids bibliography and blank-page bleed
- Updated [why-ethics-quality-gate.json](/Users/rookslog/Projects/PDFAgentialConversion/skills/pdf-to-structured-markdown/references/why-ethics-quality-gate.json) so the manual packet explicitly covers:
  - `target-7c-citation`
  - `target-7c-commentary`
  - `target-7d-commentary`
- Kept the packet composition stable at 12 entries by replacing the earlier `target-6a-citation` sample rather than growing the packet.
- Added focused guards in:
  - [test_regression_scopes.py](/Users/rookslog/Projects/PDFAgentialConversion/skills/pdf-to-structured-markdown/tests/test_regression_scopes.py)
  - [test_prose_fragment_repairs.py](/Users/rookslog/Projects/PDFAgentialConversion/skills/pdf-to-structured-markdown/tests/test_prose_fragment_repairs.py)
- Re-rendered the review packet so the generated characterization artifacts match the updated phase target set.

## Verification

- `python3 -m json.tool skills/pdf-to-structured-markdown/references/why-ethics-regressions.json` passed
- `python3 -m json.tool skills/pdf-to-structured-markdown/references/why-ethics-quality-gate.json` passed
- `python3 skills/pdf-to-structured-markdown/scripts/render_review_packet.py generated/why-ethics skills/pdf-to-structured-markdown/references/why-ethics-quality-gate.json` passed
- `python3 -m unittest discover -s skills/pdf-to-structured-markdown/tests -p 'test_regression_scopes.py' -v` passed
- `python3 -m unittest discover -s skills/pdf-to-structured-markdown/tests -p 'test_prose_fragment_repairs.py' -v` passed
- `python3 skills/pdf-to-structured-markdown/scripts/check_regressions.py generated/why-ethics skills/pdf-to-structured-markdown/references/why-ethics-regressions.json --strict` failed as intended, with only the unresolved target class red:
  - `7c Citation`: 2 failures
  - `7c Commentary`: 3 failures
  - `7d Commentary`: 2 failures

## Handoff

- Phase 06 now has executable source truth for the deferred chapter-5 repair.
- The manual packet no longer under-specifies the target set.
- The next plan can focus purely on a bounded page-local extractor repair for the `why-comment` inset-quote / note-block class.
