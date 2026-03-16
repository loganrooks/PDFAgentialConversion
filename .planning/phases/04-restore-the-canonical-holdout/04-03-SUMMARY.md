# Plan 04-03 Summary

## What changed

- Restored the `why-ethics` holdout with bounded RAG passage repairs in [convert_pdf.py](/Users/rookslog/Projects/PDFAgentialConversion/src/pdfmd/convert/convert_pdf.py):
  - prevented anchored multi-bucket passages from being split unless a bucket actually overflowed
  - added duplicate-boundary lead suppression for semantic rendering
  - tightened reference-note continuation by band, then re-added the same-baseline note-number-plus-body case needed for `why-comment 6c`
  - moved bibliography tails from commentary into reference notes when a passage already carried notes
  - added narrow next-anchor attachment for incomplete fragments immediately before embedded anchors or marker-only anchors, forcing those fragments into the next passage’s commentary bucket
  - widened that attachment rule just enough to recover short `sur- / prising` and `drawing / near` pre-anchor fragments without opening a broad new heuristic
- Restored the `spatial_main_plus_supplement` retrieval runs in [retrieval.py](/Users/rookslog/Projects/PDFAgentialConversion/src/pdfmd/benchmarks/retrieval.py) by augmenting spatial retrieval context with explicit table headings from the sidecar.
- Promoted the repaired `B. Changing the Past` case into strict regressions in [why-ethics-regressions.json](/Users/rookslog/Projects/PDFAgentialConversion/skills/pdf-to-structured-markdown/references/why-ethics-regressions.json).
- Added direct coverage in:
  - [test_prose_fragment_repairs.py](/Users/rookslog/Projects/PDFAgentialConversion/skills/pdf-to-structured-markdown/tests/test_prose_fragment_repairs.py)
  - [test_rag_segmentation.py](/Users/rookslog/Projects/PDFAgentialConversion/skills/pdf-to-structured-markdown/tests/test_rag_segmentation.py)
  - [test_regression_scopes.py](/Users/rookslog/Projects/PDFAgentialConversion/skills/pdf-to-structured-markdown/tests/test_regression_scopes.py)

## Verification

- `python3 skills/pdf-to-structured-markdown/scripts/check_regressions.py generated/why-ethics skills/pdf-to-structured-markdown/references/why-ethics-regressions.json --strict`
  - passed: `26`
  - failed: `0`
- `python3 skills/pdf-to-structured-markdown/scripts/probe_artifacts.py generated/why-ethics`
  - issue count: `9`
  - issue summary:
    - `repeated_adjacent_word`: `2`
    - `rag_block_lowercase_start`: `5`
    - `rag_block_hyphen_end`: `2`
- `python3 skills/pdf-to-structured-markdown/scripts/evaluate_retrieval.py generated/why-ethics ... --profiles fielded_bm25,chargram_tfidf,fused_rrf`
  - all gated runs matched or exceeded the frozen baseline
  - `spatial_main_plus_supplement`:
    - `fielded_bm25`: `1.0 / 1.0 / 1.0`
    - `chargram_tfidf`: `0.94 / 0.92 / 0.96`
    - `fused_rrf`: `1.0 / 1.0 / 1.0`
- `make test-fast`
  - passed
- `make smoke`
  - passed in soft-gate mode
  - `Specters of Marx` remained clean

## Outcome

Plan 04-03 restored the canonical `why-ethics` holdout content and retrieval behavior without expanding into the cross-book closure phase. The remaining work for Phase 04 is explicit gate closure: prove the restored holdout through two consecutive identical successful gate runs and then refresh roadmap/state/docs for the Phase 05 handoff.
