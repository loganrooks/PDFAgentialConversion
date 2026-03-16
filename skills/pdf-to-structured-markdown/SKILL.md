---
name: pdf-to-structured-markdown
description: Convert complex, scholarly, commentary-heavy PDFs into citation-ready markdown bundles with printed-ToC-driven section files, embedding-safe semantic markdown, spatial sidecars, flat leaf exports, metadata JSON, page provenance, and audit reports. Use when handling books, monographs, front matter, indexes, multi-column commentary, Talmud-like layouts, or when the conversion workflow needs to diagnose failures and rigorously improve its own scripts and standards.
---

# PDF To Structured Markdown

Use this skill to turn a PDF book into a reproducible markdown bundle rather than a single flat transcript.

Prefer external PDF tools for extraction and inspection:
- `pdftotext` for layout-preserving text
- `pdfinfo` for source diagnostics
- `qpdf` for outline / low-level PDF inspection
- `pdftoppm` for spot-checking difficult pages visually

Use the bundled Python scripts as the coordinator that normalizes those outputs into a standard bundle and audit report.

## Workflow

1. Inspect the source PDF.
   - Confirm whether the PDF has a usable text layer.
   - Sample title pages, copyright pages, the printed table of contents, and a few difficult body pages.
   - Treat the printed table of contents as canonical structure. Do not trust PDF bookmarks unless manual inspection proves they are good.

2. Convert the PDF into the standard bundle.
   - Read [references/output-contract.md](references/output-contract.md) before running the converter.
   - Run:

   ```bash
   python3 scripts/convert_pdf.py /abs/path/to/book.pdf /abs/path/to/output-dir --force
   ```

   - The converter should produce:
     - `metadata.json`
     - `index.md`
     - `toc.md`
     - `frontmatter/`
     - `body/` split by the printed table of contents
     - `spatial/` sidecars with coordinates and region data
     - `flat/leaf-nodes/` copies for tools that cannot import nested folders
     - `rag/leaf-nodes/` citation-first linearized exports for chunking and embedding

3. Audit the result immediately.
   - Run:

   ```bash
   python3 scripts/audit_bundle.py /abs/path/to/output-dir
   ```

   - Then run the semantic artifact probe:

   ```bash
   python3 scripts/probe_artifacts.py /abs/path/to/output-dir
   ```

   - Read [references/layout-strategy.md](references/layout-strategy.md) if the audit shows a high complex-layout ratio or if pages were preserved as layout blocks more often than expected.
   - A high complex-layout ratio is a signal, not an automatic failure, on commentary-heavy or Talmud-like books.

4. Re-run known regressions whenever a failure class has been fixed before.
   - Inspect the available anchor surface first when scoping a new regression:

   ```bash
   python3 scripts/catalog_anchors.py /abs/path/to/output-dir --path-contains why-speak
   ```

   - Prefer anchor-scoped checks over whole-file checks:
     - `rag_passage` scoped by passage `label` or `index`
     - `rag_passage` plus `block` for `Citation`, `Commentary`, or `Reference Notes`
     - `semantic_page` scoped by `page_label` or `pdf_page`
     - `spatial_page` scoped by `page_label` or `pdf_page` when the regression is about `content_mode`, slice bounds, or region diagnostics
   - RAG scopes are reconstructed from passage and block headings plus `Source page labels:` lines; the leaf markdown should stay free of inline RAG HTML comments.
   - Run:

   ```bash
   python3 scripts/check_regressions.py /abs/path/to/output-dir references/why-ethics-regressions.json
   ```

   - For a new source, add a source-specific regression spec after each real bug fix so old failures do not silently return.

5. Run the local characterization suite before broad extractor edits.
   - The stdlib `unittest` suite is the first line of defense for metadata, ToC/path allocation, page-map interpolation, range overlap logic, and RAG segmentation.
   - Run:

   ```bash
   python3 -m unittest discover -s skills/pdf-to-structured-markdown/tests -v
   ```
   - Add one positive fixture and one negative fixture for every new heuristic.

6. Evaluate retrieval behavior before making claims about RAG quality.
   - Read [references/retrieval-evaluation.md](references/retrieval-evaluation.md).
   - Run:

   ```bash
   python3 scripts/evaluate_retrieval.py /abs/path/to/output-dir references/why-ethics-retrieval-benchmark.json
   ```

   - Treat retrieval as a matrix:
     - corpus variant
     - retrieval profile
     - query probe family
   - On macOS, the evaluator can also use the bundled Swift helper and Apple `NaturalLanguage` sentence embeddings as one optional retrieval signal via `--enable-apple-nl`.

7. Evaluate embedding drift with normalized projections before changing visible markdown.
   - Run:

   ```bash
   python3 scripts/evaluate_embedding_space.py /abs/path/to/output-dir references/why-ethics-retrieval-benchmark.json --reference-corpus rag_linearized --corpora rag_linearized,semantic_flat_clean,spatial_main_plus_supplement --views body,contextual
   ```

   - The evaluator now builds corpus-aware embedding projections instead of embedding raw markdown verbatim:
     - `rag_linearized`: passage bodies only, without passage headings or page-label metadata
     - `semantic_flat_clean`: prose only, without repeated title/context/source-page boilerplate
     - `spatial_main_plus_supplement`: `body` uses `main_text` only; `contextual` adds a capped supplement preview only when side material is not overwhelming the body signal
   - Inspect `representation_diagnostics_by_run` before changing generator output:
     - nearest wrong twin
     - top-3 reference neighbors
     - separation margin
     - normalized projection preview and length stats
     - legacy-vs-normalized per-doc deltas

8. Compare optional remote embedding backends without weakening the local gate.
   - The MacBook Air M4 remains the canonical `why-ethics` gate machine.
   - Remote SSH backends are experiment-only in this phase. They must never change local pass/fail status.
   - Configure remote hosts in [references/remote-backends.json](references/remote-backends.json) and keep dependencies pinned in [references/remote-embedding-requirements.txt](references/remote-embedding-requirements.txt).
   - Run:

   ```bash
   python3 scripts/compare_embedding_backends.py /abs/path/to/output-dir references/why-ethics-retrieval-benchmark.json
   ```

   - The comparison runner will:
     - run the local Apple `NaturalLanguage` baseline
     - stage only the generated bundle, benchmark, evaluator script, and requirements file to each SSH host
     - probe remote GPU/runtime readiness
     - bootstrap a venv remotely if needed
     - run one sentence-transformers evaluation per configured model
     - fetch structured artifacts and write a local comparison report under `generated/embedding-backend-comparison/`
   - Use `--dry-run` first when validating a new remote config.
   - Keep heuristic-variant comparison (`compare_variants.py`) separate from embedding-backend comparison (`compare_embedding_backends.py`).

9. Freeze and re-run the epistemic quality gate before the next heuristic wave.
   - Read [references/quality-gate-protocol.md](references/quality-gate-protocol.md).
   - Use the frozen `why-ethics` baseline config:

   ```bash
   python3 scripts/run_quality_gate.py /abs/path/to/output-dir references/why-ethics-quality-gate.json
   python3 scripts/render_review_packet.py /abs/path/to/output-dir references/why-ethics-quality-gate.json
   ```

   - The gate is responsible for:
     - audit and regression pass/fail
     - probe deltas against the frozen baseline
     - retrieval and embedding no-regression checks
     - a fixed manual review packet with target, holdout, and negative-control scopes
     - an embedding mismatch section keyed by run, with worst mismatches and cause labels
     - chunk-level diagnostics as report-only evidence
     - runtime artifacts (`gate-runtime.json`, `embedding-runtime.json`) so Apple embedding hangs are classified instead of silently wedging the session
   - During the current chapter-5 phase, the manual packet is tracked as report-only until the unresolved `7c` / `7d` class is repaired and re-reviewed.

10. Improve the skill rigorously when it hits a limit.
   - Read [references/self-improvement.md](references/self-improvement.md).
   - Do not “fix” a failure by silently rewriting the output by hand.
   - Patch the converter, the auditor, or the reference rules so the improved behavior is reusable on the next book.

11. Check out-of-sample generalization before trusting a book-specific win.
   - Read [references/challenge-corpus.md](references/challenge-corpus.md).
   - Run:

   ```bash
   python3 scripts/run_challenge_corpus.py references/challenge-corpus.json --force
   python3 scripts/run_challenge_corpus.py references/challenge-corpus.json --gate-mode hard
   ```

   - Treat the default runner as a soft gate, not a new hard baseline:
     - convert each configured book
     - run audit and probe
     - run any source-specific strict regression spec
     - record chunk diagnostics
     - compare against the frozen challenge baseline in `references/baselines/challenge-corpus/`
     - write both `smoke-report.md` and `review-packet.md`
     - emit explicit `gate_failures` for each book
     - look for layout classes that only fail off the `why-ethics` path

## Operating Rules

- Keep the markdown bundle structurally aligned to the printed table of contents.
- Preserve front matter separately from the main body.
- Create leaf markdown files for ToC leaves and index files for structural containers such as parts, chapters, or introductions.
- Treat the markdown channel as semantic-first and embedding-safe.
- Emit a separate RAG-oriented leaf export when the downstream use case needs citation and commentary serialized rather than laid out in parallel.
- Preserve exact layout, regions, and coordinates in JSON sidecars rather than in the markdown channel.
- Include contextual breadcrumbs in leaf markdown and emit flat leaf copies with structure-rich filenames.
- For commentary-heavy pages, prefer passage-oriented `Citation` then `Commentary` linearization in the RAG export over side-by-side transcription.
- For complex pages, keep the main flow readable in markdown and move exact spatial reconstruction into sidecars.
- Treat `prose`, `table`, and `index` as separate content modes in both rendering and evaluation.
- Infer Arabic page locations from observed printed page numbers plus local interpolation, not from a single global offset alone.
- When one Arabic offset dominates overwhelmingly, prefer the stable global-offset model over sparse noisy observations; use interpolation for irregular books, not for clean-offset books.
- When ToC OCR drops leading hundreds digits, normalize page labels monotonically before assigning ranges.
- When a region contains an embedded passage marker, split it into derived RAG fragments before passage assembly instead of letting the marker disappear inside a larger block.
- Split oversized anchored note/citation passages into bounded pseudo-passages when a single labeled block would exceed the hard atomic cap.
- On shared boundary pages, prefer the entry's own heading band over running headers so the previous leaf keeps the pre-heading slice and the next leaf starts at the real section heading.
- Store provenance, page ranges, and anomalies in JSON rather than bloating the markdown with machinery.
- If extraction requires repeated manual forensic work, add or improve a tool in `scripts/` instead of expanding `SKILL.md`.

## Resources

- [references/output-contract.md](references/output-contract.md): Required bundle shape and metadata expectations.
- [references/layout-strategy.md](references/layout-strategy.md): Hybrid extraction rules and layout handling.
- [references/quality-gate-protocol.md](references/quality-gate-protocol.md): Epistemic gate rules for accepting the next layout heuristic.
- [references/challenge-corpus.md](references/challenge-corpus.md): Out-of-sample smoke testing beyond the frozen baseline.
- [references/retrieval-evaluation.md](references/retrieval-evaluation.md): Multi-signal retrieval testing and interpretation.
- [references/self-improvement.md](references/self-improvement.md): Controlled self-modification protocol.
- `scripts/convert_pdf.py`: Main bundle generator.
- `scripts/audit_bundle.py`: Structural audit and failure surfacing.
- `scripts/probe_artifacts.py`: Generic semantic artifact probe for suspicious starts, ends, repeats, and sliced-page fragment risk.
- `scripts/probe_artifacts.py` emits `scope_suggestion` and `content_mode` so likely failures can be promoted directly into regression cases.
- `scripts/catalog_anchors.py`: Enumerate semantic-page and RAG passage/block anchors before writing regression checks.
- `scripts/check_regressions.py`: Deterministic regression checker against a source-specific assertion spec.
- `scripts/check_regressions.py` resolves repeated-label RAG scopes across all matching passages, so `label + block` assertions stay stable when passage ordinals shift.
- `skills/pdf-to-structured-markdown/tests/`: Local fixture-driven `unittest` suite for the extractor’s pure logic seams.
- `scripts/evaluate_retrieval.py`: Multi-profile retrieval benchmark runner.
- `scripts/evaluate_embedding_space.py`: Embedding drift and embedding-only retrieval evaluator.
- `scripts/evaluate_embedding_space.py` emits normalized projection diagnostics so embedding misses can be classified before the converter is changed.
- `scripts/compare_embedding_backends.py`: Optional SSH/GPU backend comparison runner for sentence-transformers experiments against the same frozen bundle inputs.
- `scripts/run_quality_gate.py`: Frozen-baseline gate runner for audit, probe, retrieval, embedding, and manual-sample evidence.
- `scripts/render_review_packet.py`: Fixed review-packet renderer with scope text, sidecar excerpts, and page images.
- `scripts/render_review_packet.py` appends the current embedding mismatch diagnostics when `embedding.json` is present in the gate output directory.
- `scripts/run_challenge_corpus.py`: Batch out-of-sample conversion and smoke-test runner.
- `scripts/apple_nl_similarity.swift`: Apple `NaturalLanguage` dense similarity helper for macOS.
- [references/remote-backends.json](references/remote-backends.json): Remote SSH embedding backend definitions.
- [references/remote-embedding-requirements.txt](references/remote-embedding-requirements.txt): Pinned remote experiment dependencies.
