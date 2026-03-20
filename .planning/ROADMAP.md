# ROADMAP

## Milestones

- [v1.0 Foundation, Visibility, and Gate Recovery](.planning/milestones/v1.0-ROADMAP.md) -- Phases 01-06, shipped 2026-03-16
- **v1.1 Remote Evaluation & Extraction Exploration** -- Phases 07-09 (in progress)

## v1.1 Remote Evaluation & Extraction Exploration

### Overview

This milestone turns the SSH-orchestrated embedding evaluation pipeline from dry-run infrastructure into live measured comparisons on the dionysus GPU, expands the model roster from 3 to 8, and explores GLM-OCR as a potential extraction upgrade for scholarly PDFs. Infrastructure comes first (stale pins, missing timeouts, VRAM safety), then the full embedding matrix, then OCR exploration in an isolated environment. The two workstreams -- embedding evaluation and OCR exploration -- never share a Python environment or run concurrently on the GPU.

### Phases

- [ ] **Phase 07: Infrastructure Alignment and Live Pipeline** - Fix foundation gaps and prove the pipeline works end-to-end with live GPU metrics
- [ ] **Phase 08: Expanded Embedding Evaluation** - Run all 8 models and select the best non-Apple backend for scholarly retrieval
- [ ] **Phase 09: GLM-OCR Exploration** - Evaluate vision-language extraction on representative scholarly pages

### Phase Details

#### Phase 07: Infrastructure Alignment and Live Pipeline
**Goal**: Operator can run a live embedding comparison on dionysus and get real measured metrics back, with SSH reliability and VRAM safety in place
**Depends on**: v1.0 complete (phases 01-06)
**Requirements**: INFRA-01, INFRA-02, INFRA-03, EMBED-01, EMBED-04
**Success Criteria** (what must be TRUE):
  1. `remote-embedding-requirements.txt` pins match the actual dionysus system (torch 2.9.1+cu126, sentence-transformers 5.2.0, transformers 4.51.3) and the venv installs cleanly against those pins
  2. Operator can run `make compare-backends` without `--dry-run` and get a comparison-summary.json with real metric values from at least one model (bge-small-en-v1.5)
  3. A deliberately hung or slow remote command times out and returns a clear error to the Mac orchestrator instead of blocking indefinitely
  4. VRAM state is checked between model evaluations and a model will not load if prior VRAM is not released
  5. Models requiring `trust_remote_code=True` (nomic-embed, stella) load successfully through the evaluation pipeline
**Plans**: TBD

Plans:
- [ ] 07-01: TBD
- [ ] 07-02: TBD
- [ ] 07-03: TBD

#### Phase 08: Expanded Embedding Evaluation
**Goal**: Operator has a full 8-model comparison matrix with real retrieval metrics that informs which non-Apple backend to use for dionysus-hosted RAG
**Depends on**: Phase 07
**Requirements**: EMBED-02, EMBED-03, EMBED-05, EMBED-06, RPT-01
**Success Criteria** (what must be TRUE):
  1. All 8 models (bge-small, bge-base, e5-base, bge-large, gte-large, nomic-embed, bge-m3, plus one additional from research roster) run to completion without OOM, each with its own batch size configuration
  2. Each model produces an evaluation.json containing twin cosine, hit@1, and MRR metrics across all corpus-view pairs
  3. `choose_winner` selects a best non-Apple backend from the real 8-model metric payloads and the selection is explainable from the data
  4. Historical comparison aggregator can read multiple comparison-summary.json files and show whether model rankings are stable across runs
**Plans**: TBD

Plans:
- [ ] 08-01: TBD
- [ ] 08-02: TBD
- [ ] 08-03: TBD

#### Phase 09: GLM-OCR Exploration
**Goal**: Operator has empirical evidence about whether GLM-OCR handles complex scholarly layouts better than the current PyMuPDF pipeline, informing the v2 integration decision
**Depends on**: Phase 08 (sequential GPU use; embedding evaluation must complete before OCR exploration begins)
**Requirements**: OCR-01, OCR-02, OCR-03, OCR-04
**Success Criteria** (what must be TRUE):
  1. GLM-OCR runs in an isolated venv on dionysus with transformers >= 5.3.0, completely separate from the embedding stack, and does not interfere with the embedding evaluation environment
  2. GLM-OCR loads at fp16 precision with SDPA attention fallback on the GTX 1080 Ti and produces output (no bfloat16, no Flash Attention 2)
  3. 5-10 representative scholarly pages (from why-ethics and challenge corpus, including commentary-dense and multi-column layouts) are extracted to markdown via GLM-OCR
  4. A side-by-side comparison of GLM-OCR vs existing pipeline output exists for each tested page, with enough detail to assess whether v2 integration is warranted
**Plans**: TBD

Plans:
- [ ] 09-01: TBD
- [ ] 09-02: TBD

## Progress

| Phase | Milestone | Plans Complete | Status | Completed |
|-------|-----------|----------------|--------|-----------|
| 07. Infrastructure Alignment and Live Pipeline | v1.1 | 0/TBD | Not started | - |
| 08. Expanded Embedding Evaluation | v1.1 | 0/TBD | Not started | - |
| 09. GLM-OCR Exploration | v1.1 | 0/TBD | Not started | - |
