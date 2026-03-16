# Plan 06-02 Summary

## Goal

Repair the deferred `why-comment` chapter-5 inset-quote / note-block defect with one bounded page-local handler, then prove the repaired targets are green under strict regressions and the still-report-only manual packet.

## What changed

- Added a narrow `why-comment` commentaries handler in [convert_pdf.py](/Users/rookslog/Projects/PDFAgentialConversion/src/pdfmd/convert/convert_pdf.py):
  - `is_why_comment_commentaries_entry`
  - `force_region_rag_bucket`
  - `repair_why_comment_inset_quote_spatial_pages`
- Kept the repair page-local and layout-class bounded:
  - page `127`: rebuckets the `8) Erubin 13b` inset quote into `Reference Notes` while preserving the lower-left continuation as `Commentary`
  - page `128`: rebuckets footnote `9 Levinas TN 198–99/168–69` into `Reference Notes`
  - page `129`: moves only the `SUGGESTED READINGS` tail and what follows into `Reference Notes`
  - page `130`: keeps the bibliography/blank-page tail out of commentary by forcing it to `Reference Notes`
- Propagated forced bucket overrides into RAG assembly so the spatial repair actually affects the final passage blocks rather than staying sidecar-only.
- Tightened the chapter-5 regression truth in [why-ethics-regressions.json](/Users/rookslog/Projects/PDFAgentialConversion/skills/pdf-to-structured-markdown/references/why-ethics-regressions.json) to match the repaired commentary text.
- Updated the report-only manual packet in [why-ethics-quality-gate.json](/Users/rookslog/Projects/PDFAgentialConversion/skills/pdf-to-structured-markdown/references/why-ethics-quality-gate.json) so:
  - `target-7c-citation`
  - `target-7c-commentary`
  - `target-7d-commentary`
  now render as `pass`
- Added focused guards in [test_prose_fragment_repairs.py](/Users/rookslog/Projects/PDFAgentialConversion/skills/pdf-to-structured-markdown/tests/test_prose_fragment_repairs.py) for:
  - positive rebucketing on the target chapter-5 pages
  - no-op behavior on a protected holdout entry
  - repaired manual-packet expectations for `7c/7d`

## Verification

- `python3 -m unittest discover -s skills/pdf-to-structured-markdown/tests -p 'test_prose_fragment_repairs.py' -v` passed
- `python3 skills/pdf-to-structured-markdown/scripts/check_regressions.py generated/why-ethics skills/pdf-to-structured-markdown/references/why-ethics-regressions.json --strict` passed with `35` passes and `0` failures
- `python3 skills/pdf-to-structured-markdown/scripts/render_review_packet.py generated/why-ethics skills/pdf-to-structured-markdown/references/why-ethics-quality-gate.json` passed
- `python3 skills/pdf-to-structured-markdown/scripts/run_quality_gate.py generated/why-ethics skills/pdf-to-structured-markdown/references/why-ethics-quality-gate.json --stability-runs 1` passed in report-only manual mode on the repaired bundle
- `make smoke` remained green in hard mode, so the challenge corpus veto stayed intact while the chapter-5 target improved

## Outcome

- `7c Citation` is now bounded to the Hillel-Shammai citation instead of swallowing lower commentary lines.
- `7c Commentary` no longer splices the `Erubin 13b` inset quote into commentary.
- `7d Commentary` no longer carries bibliography or blank-page bleed.
- The repaired chapter-5 targets are now green under both strict regressions and the report-only review packet.

## Handoff

- Phase 06 no longer needs extractor work for the deferred chapter-5 defect.
- The next plan should promote manual packet acceptance from report-only to enforced and then re-prove the canonical `why-ethics` gate with repeated stable runs.
