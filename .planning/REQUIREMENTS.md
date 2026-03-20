# Requirements: PDFAgentialConversion

**Defined:** 2026-03-19
**Core Value:** Make difficult PDFs operationally legible and reproducible without sacrificing structural rigor, retrieval quality, or auditability.

## v1.1 Requirements

Requirements for Remote Evaluation & Extraction Exploration milestone. Each maps to roadmap phases.

### Infrastructure (INFRA)

- [ ] **INFRA-01**: Remote requirements pins align with actual dionysus environment (torch 2.9.1+cu126, sentence-transformers 5.2.0, transformers 4.51.3)
  - *Motivation:* `research: stale pins are dead code masked by --system-site-packages; live runs will fail or produce version conflicts`
- [ ] **INFRA-02**: SSH subprocess calls have configurable timeouts to prevent indefinite hangs during live GPU evaluation
  - *Motivation:* `research: no timeout in remote_backends.py run_command(); GPU hang blocks Mac orchestrator indefinitely`
- [ ] **INFRA-03**: VRAM guards enforce sequential model execution with explicit unload between models on 11GB GPU
  - *Motivation:* `research: concurrent model loading guarantees OOM; sequential with cleanup is mandatory`

### Embedding Evaluation (EMBED)

- [ ] **EMBED-01**: Operator can run embedding comparison without `--dry-run` and get measured metrics from dionysus GPU
  - *Motivation:* `user: core milestone goal -- turn dry-run infrastructure into live measured comparisons`
- [ ] **EMBED-02**: Remote backends config supports per-model batch size to prevent OOM on larger models
  - *Motivation:* `research: BGE-M3 at batch 32 will OOM; per-model sizing is required`
- [ ] **EMBED-03**: Model roster expanded to 8 models: existing 3 + BGE-large, E5-large, GTE-large, BGE-M3, nomic-embed
  - *Motivation:* `user: 3 models insufficient for informed backend selection; research validated all 5 fit in 11GB`
- [ ] **EMBED-04**: Models requiring `trust_remote_code=True` are supported by the evaluation pipeline
  - *Motivation:* `research: nomic-embed and potential future models require this flag`
- [ ] **EMBED-05**: Winner selection validated with real metric payloads from full 8-model comparison
  - *Motivation:* `user: pick best non-Apple backend; existing algorithm needs real data validation`
- [ ] **EMBED-06**: Live comparison produces per-model evaluation.json with twin cosine, hit@1, and MRR across all corpora and views
  - *Motivation:* `user: quantify Apple NL vs open-source gap with real retrieval metrics`

### GLM-OCR Exploration (OCR)

- [ ] **OCR-01**: Isolated environment on dionysus with transformers >= 5.3.0 and GLM-OCR dependencies, separate from embedding stack
  - *Motivation:* `research: transformers 4.51.x / 5.3.x conflict is a hard constraint; cannot share environment`
- [ ] **OCR-02**: GLM-OCR loads at fp16 with SDPA attention fallback on GTX 1080 Ti (compute capability 6.1)
  - *Motivation:* `research: bfloat16 and Flash Attention 2 require compute >= 8.0; GTX 1080 Ti is 6.1`
- [ ] **OCR-03**: Smoke test extracts 5-10 representative scholarly pages (from why-ethics and challenge corpus) to markdown via GLM-OCR
  - *Motivation:* `user: explore what GLM-OCR can do for scholarly PDF extraction`
- [ ] **OCR-04**: Side-by-side quality comparison of GLM-OCR vs existing pipeline output for the same pages
  - *Motivation:* `user: assess whether GLM-OCR handles complex scholarly layouts better than current pipeline`

### Reporting (RPT)

- [ ] **RPT-01**: Historical comparison aggregator reads past comparison-summary.json files and shows model ranking stability over time
  - *Motivation:* `user: track whether model rankings change as bundles evolve`

## Future Requirements (v2+)

### Extraction Integration

- **EXT-01**: Full GLM-OCR pipeline integration as alternative extraction backend
- **EXT-02**: Extraction pipeline A/B harness with automated quality metrics
- **EXT-03**: Cross-book model stability testing across multiple books

### Embedding Advanced

- **EMBA-01**: BGE-M3 sparse/multi-vector retrieval mode evaluation
- **EMBA-02**: Automatic batch size calibration via VRAM probing pre-flight
- **EMBA-03**: Best-backend auto-selection for RAG deployment

## Out of Scope

| Feature | Reason |
|---------|--------|
| 7B embedding models (SFR-Embedding-Mistral, e5-mistral-7b-instruct) | Exceed 11GB VRAM even at FP16; quantization degrades embedding quality unpredictably |
| Replace Apple NL as canonical gate | Apple NL is the stable Mac-local baseline; comparison informs backend selection, not replacement |
| Cross-platform path fixes | SSH-from-Mac orchestration model preserved; dionysus is remote target only |
| Running comparisons from iPhone (orpheus) | Comparison harness depends on local Apple NL baseline on Mac; phone is monitoring only |
| Ollama-based GLM-OCR deployment | Less control over inference parameters; direct transformers access needed for evaluation |
| Full GLM-OCR pipeline replacement in v1.1 | Exploration must prove quality before committing to integration; too many moving parts |

## Traceability

| Requirement | Phase | Status |
|-------------|-------|--------|
| INFRA-01 | Phase 07 | Pending |
| INFRA-02 | Phase 07 | Pending |
| INFRA-03 | Phase 07 | Pending |
| EMBED-01 | Phase 07 | Pending |
| EMBED-02 | Phase 08 | Pending |
| EMBED-03 | Phase 08 | Pending |
| EMBED-04 | Phase 07 | Pending |
| EMBED-05 | Phase 08 | Pending |
| EMBED-06 | Phase 08 | Pending |
| OCR-01 | Phase 09 | Pending |
| OCR-02 | Phase 09 | Pending |
| OCR-03 | Phase 09 | Pending |
| OCR-04 | Phase 09 | Pending |
| RPT-01 | Phase 08 | Pending |

**Coverage:**
- v1.1 requirements: 14 total
- Mapped to phases: 14
- Unmapped: 0

---
*Requirements defined: 2026-03-19*
*Last updated: 2026-03-20 after roadmap creation (phases 07-09 mapped)*
