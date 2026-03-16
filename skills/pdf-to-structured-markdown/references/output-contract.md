# Output Contract

## Required bundle shape

```text
bundle/
  metadata.json
  index.md
  toc.md
  frontmatter/
  body/
  spatial/
  flat/
  rag/
```

## Required root files

- `metadata.json`
  - source PDF provenance
  - citation-ready bibliographic fields
  - extraction timestamp and tool version
  - page-map inference
  - layout profile summary
  - ToC tree
  - file manifest
- `index.md`
  - one-screen summary of the book and the bundle
- `toc.md`
  - markdown links to the generated files in ToC order
- `spatial/`
  - JSON sidecars parallel to markdown paths
  - exact page-region geometry, order, and raw layout text
- `flat/leaf-nodes/`
  - flat copies of leaf markdown files
  - filenames must carry enough structural context to work outside nested folders
- `rag/leaf-nodes/`
  - flat RAG-oriented leaf exports
  - passage-based linearizations that serialize citation before commentary when the layout supports that distinction

## Front matter rules

- Preserve front matter separately from the main body.
- Include a preliminary file for unlisted prelim pages when they contain useful material such as title, copyright, dedication, or prefatory matter.
- Preserve the printed table of contents as its own front matter file.
- Preserve ToC-listed front matter entries as their own markdown files when possible.

## Main body rules

- Use the printed table of contents as the structural authority.
- Allow adjacent leaves to share a source page when the later heading begins mid-page.
- In those boundary cases:
  - the earlier leaf owns the pre-heading slice
  - the later leaf owns the post-heading slice
- Create directories for structural containers:
  - introduction
  - parts
  - chapters
- Create markdown leaf files for ToC leaves:
  - lettered sections
  - epilogues without children
  - indexes
- Create `index.md` files for containers even if the container has no prose beyond navigation.
- If a container has prelude pages before its first child, put those pages in the container `index.md`.

## Markdown file contract

Each generated markdown file should contain:
- YAML frontmatter with title, kind, page span, and child list
- context path for embeddings
- links to the spatial sidecar and flat export when applicable
- link to the RAG linearized export when applicable
- a visible heading
- a visible source-page summary when the file owns actual pages
- source-page markers in HTML comments for downstream parsing
- explicit regression anchors in HTML comments

Semantic markdown page anchors:
- emit `<!-- semantic-page: page_label=50; pdf_page=67; layout=aside -->`
- keep the existing `source-page-label` marker for backwards compatibility

Regression scopes:
- `rag_passage` may include both `index` and `label` when repeated labels appear in the same leaf
- `spatial_page` may be used against the sidecar JSON when the assertion concerns `content_mode`, slice ownership, or region diagnostics
- RAG passage/block scopes should be recoverable from headings and `Source page labels:` lines without requiring inline HTML anchor comments in the leaf body

For simple pages:
- emit readable prose paragraphs

For complex pages:
- keep the markdown semantic-first
- prefer main flow text plus compact “supplementary side material” sections
- do not dump raw layout-preserved code blocks into the markdown channel unless there is no better fallback

## Spatial sidecar contract

Each sidecar should include:
- entry identity and context
- book/PDF page span
- per-page layout kind
- per-page `content_mode` as one of `prose`, `table`, or `index`
- per-page slice bounds when a page is only partially owned because of a mid-page boundary
- per-page region list
- per-region bounding box
- per-region role such as `main`, `aside`, or `table`
- per-region or per-fragment continuation diagnostics when bucket inheritance was applied
- optional derived `rag_fragments` when one extracted region contains multiple logical RAG fragments or an embedded passage marker
- raw layout text for forensic reconstruction

The sidecar is the exactness channel. The markdown is the embedding channel.

## RAG linearized export contract

Each RAG linearized leaf export should:
- preserve the same leaf-level scope as the semantic markdown file
- stay flat so external tools can import the file without nested directories
- use passage-oriented headings
- use `## Passage NNN` and `### Citation` / `### Commentary` / `### Reference Notes` headings as the public anchor surface
- mark `Citation` and `Commentary` explicitly when the page layout can support that distinction
- serialize `Citation` before `Commentary` inside each passage
- keep reference notes separate from the main commentary text
- fall back to commentary-only passages when no reliable citation/commentary split is available
- retain enough page provenance that probes can recover block `content_mode` from the sidecar instead of assuming every block is prose

## Metadata expectations

`metadata.json` should be rich enough for citation and downstream repair work.

At minimum it must include:
- title
- subtitle when present
- authors
- publisher
- publication place when recoverable
- publication year
- ISBNs when present
- subjects or classification data when present
- recommended citation string
- source filename and checksum
- PDF metadata and external tool diagnostics
- ToC hierarchy with output paths
- per-file page coverage
- spatial sidecar paths
- flat export paths
- RAG export paths

## Naming rules

- Use lowercase, hyphenated paths.
- Keep stable prefixes for ordered structural containers:
  - `part-01-...`
  - `chapter-01-...`
- For lettered sections, keep the letter prefix in the filename:
  - `a-attending-the-teacher.md`
  - `b-signs.md`
- Flat leaf exports must include:
  - book id
  - ancestor structure
  - leaf identity
  - page span when available

Example:

```text
robert-gibbs-why-ethics__part-01-attending-the-future__chapter-04-why-read__section-c-re-citation__pp-95-113.md
```

## What not to do

- Do not dump the whole book into one markdown file.
- Do not discard front matter just because it is not part of the main reading body.
- Do not trust embedded PDF bookmarks over the printed contents page.
- Do not normalize away difficult layout if that loses the page’s structure.
- Do not force exact spatial preservation into the markdown channel when it degrades embeddings.
