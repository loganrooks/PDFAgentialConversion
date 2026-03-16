# Layout Strategy

## Tool priority

Use the tool that is most reliable for the specific subproblem.

- `pdftotext -layout`: preserve spatial relations on commentary-heavy or tabular pages
- native text extraction via PyMuPDF: reflow simple prose blocks cleanly
- `pdfinfo`: source diagnostics
- `qpdf`: inspect broken outlines, page objects, and low-level structure
- `pdftoppm`: render representative pages when the text stream hides layout problems

Python is the coordinator. It should not pretend to be the only extractor.

## Two-channel rule

Always separate:
- semantic markdown for embedding and chunking
- spatial sidecars for reconstruction and provenance

If preserving layout exactly would pollute embeddings, push that exactness into the sidecar instead of the markdown.

## Canonical structure source

Use the printed table of contents as the canonical structure unless manual inspection proves it is wrong.

Treat embedded bookmarks as advisory only.

## Page-map inference

Prefer visible printed page numbers over title matching.

Why:
- title matching is vulnerable to ToC echoes and repeated headers
- printed folios produce a stable offset for the Arabic-numbered body

For front matter:
- use roman labels when recoverable
- if necessary, infer them separately from the Arabic body

## Page classification

Use at least these layout classes:
- `simple`
- `aside`
- `table`
- `multi-column`
- `blank`

The class is a routing decision:
- `simple` -> readable markdown paragraphs
- `aside` / `multi-column` -> main flow plus supplementary side material in markdown, exact geometry in sidecar
- `table` -> compact table-like semantic text in markdown, exact geometry in sidecar

## Commentary-heavy pages

When a page behaves like a glossed or Talmud-like page:
- keep exact page provenance explicit
- preserve exact geometry in the sidecar
- keep the markdown channel semantically legible, even if it means not preserving exact interleaving there

Do not linearize a complex page aggressively unless you can prove the reading order. If the reading order is uncertain, prefer:
1. main flow in markdown
2. side material grouped separately in markdown
3. exact coordinates in the sidecar

## When to add a new handler

Add or improve a handler in `scripts/` when a failure mode is:
- repeatable across pages or books
- expensive to repair manually
- structurally detectable

Examples:
- recurring side-column quotations
- recurring tables with stable geometry
- recurring line-numbered excerpts
- recurring marginal commentary zones
