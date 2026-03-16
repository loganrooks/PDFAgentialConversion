# Self-Improvement Protocol

This skill is allowed to improve itself, but only in a controlled loop.

## Trigger

Enter the improvement loop when:
- the converter mis-segments the ToC
- citation metadata is wrong or incomplete in a repeatable way
- a layout class is overused or underused
- a page type repeatedly falls back to raw layout preservation when a better handler is feasible
- the semantic markdown channel harms embedding quality or chunk coherence
- flat filenames are too weak to support filename-based retrieval
- the auditor surfaces a real structural defect

## Required loop

1. Reproduce the failure.
   - Identify the exact PDF pages and generated file paths involved.
   - Save the failing bundle or audit output if needed.

2. Classify the failure.
   - metadata extraction
   - ToC parsing
   - page-map inference
   - simple/complex page routing
   - semantic/spatial split
   - flat export naming
   - specific layout handler gap
   - audit false positive or false negative

3. Patch the smallest reusable unit.
   - Prefer a script change over a one-off manual cleanup.
   - Prefer a rule or helper function over hard-coding one book’s title.
   - If the workflow lacks a needed utility, add a new script.
   - Add or update a local `unittest` fixture before changing a heuristic that should generalize.

4. Re-run the failing case.
   - Rebuild the bundle.
   - Re-run the local `unittest` suite when the change touched extractor logic.
   - Re-run the auditor.
   - Re-run the artifact probe.
- Re-run the quality gate when the current source has a frozen baseline config.
- If the quality gate touched embeddings, inspect `gate-runtime.json` and `embedding-runtime.json` before deciding whether the failure is runtime-only or extractor-driven.
- If the failure is embedding drift, re-run `evaluate_embedding_space.py` first and inspect the normalized projection diagnostics before changing converter output.
- If the failure is specifically about embedding backend quality rather than extractor behavior, compare the local Apple baseline against optional SSH/GPU backends with `compare_embedding_backends.py` before changing the canonical gate or visible markdown.
- If the failure is about RAG passage assembly, inspect the sidecar `content_mode` and any `rag_fragments` or continuation diagnostics before adding another heuristic.

5. Re-run a previously working case.
   - Confirm the improvement did not regress known-good behavior.
   - If the failure class has happened before, add or update an anchor-scoped regression spec entry and run the regression checker.
   - If the source has a frozen baseline gate, compare against its retrieval, embedding, and manual-review packet expectations before accepting the patch.
   - If the change claims to generalize, run the challenge corpus smoke suite and inspect the off-baseline books before accepting the claim.
   - Keep the challenge corpus in `soft` mode until the current residual failures are stable enough to freeze as thresholds.
   - Compare the smoke report against the frozen challenge baseline, not just the current run in isolation.
   - Prefer the smallest stable scope:
     - `rag_passage` by `label`
     - `rag_passage` plus `block`
     - `semantic_page` by `page_label`
     - `spatial_page` when the invariant lives in the sidecar rather than the markdown text

6. Update the skill if the operational contract changed.
   - Adjust `SKILL.md` only if the workflow changed materially.
   - Adjust the relevant reference file if the standard changed.
   - Re-run the skill validator after skill edits.

## Rigor rules

- Do not silently hand-edit generated markdown and call that a fix.
- Do not broaden heuristics without re-running the auditor.
- Do not treat table or index pages as broken prose; check `content_mode` first.
- Do not add complexity to `SKILL.md` when the right fix belongs in code.
- Do not delete an audit warning unless you can defend why it is noise.

## When to build another tool

Add a new helper script when:
- the same inspection or cleanup step has been done twice
- the step has a deterministic input/output shape
- the new tool reduces token use without reducing reliability

Good candidates:
- page-type samplers
- ToC diagnostics
- metadata extraction helpers
- layout block visualizers
- artifact probes
- regression assertion runners
- quality-gate runners
- review-packet renderers
- remote experiment runners
- semantic export cleaners
- flat filename builders
- regression diff helpers

## Current heuristics worth preserving

- Prefer monotonic ToC page-label repair over book-specific page-number patches when OCR drops leading hundreds digits.
- Prefer observed printed page numbers plus interpolation over a single global Arabic offset when the PDF omits or inserts physical pages irregularly.
- When one offset wins by overwhelming vote share, fall back to the global-offset model and treat sparse off-offset observations as noise rather than as the primary map.
- On shared boundary pages, resolve the cutoff from the entry's own heading before falling back to ancestor/running-header matches; otherwise the next leaf steals pre-heading content and regresses page overlap handling.
- For repeated RAG passage labels, regression scopes should prefer `label + block` unless the exact ordinal is the invariant being protected.
- If a labeled note/citation block exceeds the hard atomic cap, split it into bounded pseudo-passages instead of preserving one unusable giant anchor block.
- For embedding regressions, prefer evaluator-side normalized projections and diagnostic review over visible markdown edits; only add derived non-user-facing embedding projections if the normalized evaluator still fails the frozen gate.
- Keep the local Apple-backed `why-ethics` gate canonical even when optional SSH/GPU backends are being compared; remote backend failures stay report-only until they are explicitly promoted.
