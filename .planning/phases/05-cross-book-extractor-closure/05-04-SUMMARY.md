# Plan 05-04 Summary

## Goal

Promote the challenge corpus from a soft smoke report into a real hard non-regression gate, then close Phase 05 and hand off cleanly to Phase 06.

## What changed

- Updated [challenge_corpus.py](/Users/rookslog/Projects/PDFAgentialConversion/src/pdfmd/gates/challenge_corpus.py) so the challenge corpus now defaults to `hard` gate mode and reports its enforcement level accurately in the generated markdown summary.
- Kept the hard gate bounded to the accepted post-repair cross-book thresholds:
  - `why-ethics` remains the canonical local holdout gate
  - `Specters of Marx` remains the clean negative control
  - `Of Grammatology` must stay structurally clean and within the accepted probe/chunk limits
  - `Otherwise than Being` must stay within its accepted audit/probe/chunk limits
- Refreshed [challenge-corpus.md](/Users/rookslog/Projects/PDFAgentialConversion/skills/pdf-to-structured-markdown/references/challenge-corpus.md) so the documented operator surface matches the promoted gate.
- Added a regression guard in [test_project_ops.py](/Users/rookslog/Projects/PDFAgentialConversion/skills/pdf-to-structured-markdown/tests/test_project_ops.py) to keep the challenge-corpus CLI defaulting to hard mode.
- Updated [ROADMAP.md](/Users/rookslog/Projects/PDFAgentialConversion/.planning/ROADMAP.md), [STATE.md](/Users/rookslog/Projects/PDFAgentialConversion/.planning/STATE.md), and [README.md](/Users/rookslog/Projects/PDFAgentialConversion/README.md) so Phase 05 closes cleanly and Phase 06 is the next active target.

## Verification

- `make gate` passed
- `python3 skills/pdf-to-structured-markdown/scripts/run_challenge_corpus.py skills/pdf-to-structured-markdown/references/challenge-corpus.json --gate-mode hard --force` passed
- `python3 skills/pdf-to-structured-markdown/scripts/run_challenge_corpus.py skills/pdf-to-structured-markdown/references/challenge-corpus.json --gate-mode hard --skip-convert` passed
- `make status` passed
- `make smoke` passed in hard-gate mode

The accepted hard-gate state now enforced by the challenge corpus is:

- `Specters of Marx`: audit clean, probe `0`, max atomic block `1584`
- `Of Grammatology`: audit clean, probe `5`, max atomic block `1591`
- `Otherwise than Being`: only `high_complex_layout_ratio`, probe `6`, max atomic block `1475`

## Runtime Note

- The default `make gate` verification initially fell back to the raw `180s` config timeout because the generated calibration artifact from Phase 04 was no longer present under `generated/why-ethics/quality-gate/embedding-calibration/`.
- I restored that runtime-only calibration artifact from the committed Phase 04 measured timings (`227.8009s`, `223.6204s`, `223.3915s`, `230.3159s`, one timeout at `240.8715s`), which re-enabled the verified provisional timeout of `461s`.
- After restoring it, `make gate` completed successfully with `embedding_timeout_source = calibration_report_provisional`, `wall_clock_seconds = 235.5858`, and `stability_runs = 2`.

## Handoff

- Phase 05 is complete.
- Phase 06 is next: repair `why-comment` `7c/7d`.
- Remote backend experiments remain report-only.
- The challenge corpus is now part of the normal non-regression verification contract rather than a soft smoke-only report.
