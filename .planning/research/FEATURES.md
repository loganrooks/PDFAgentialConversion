# Feature Research

**Domain:** Live embedding evaluation and vision-language OCR exploration for scholarly PDF conversion
**Researched:** 2026-03-19
**Confidence:** MEDIUM (HIGH on embedding evaluation, MEDIUM on GLM-OCR feasibility due to dependency chain unknowns)

## Feature Landscape

This research covers two distinct feature domains for the v1.1 milestone:
1. **Live Embedding Backend Evaluation** -- removing the dry-run constraint, running measured comparisons on dionysus, expanding the model roster
2. **Vision-Language OCR Exploration** -- evaluating GLM-OCR (and peers) as a potential upgrade to the PaddleOCR + pdftotext extraction pipeline

### Table Stakes (Users Expect These)

Features the system must have to deliver useful live comparisons and inform backend selection.

| Feature | Why Expected | Complexity | Notes |
|---------|--------------|------------|-------|
| Live SSH evaluation cycle | Existing dry-run infrastructure builds commands but never executes. Live mode is the stated milestone goal. | LOW | Infra exists: probe/bootstrap/evaluate/fetch/tar. Remove the `--dry-run` constraint and validate the actual cycle. The `run_command` function already handles live execution; the gap is end-to-end validation with real models on dionysus. |
| Requirements file update | Pinned requirements (`torch==2.4.1`, `sentence-transformers==3.0.1`) are 18+ months stale. Dionysus has PyTorch 2.9.1+cu126, sentence-transformers 5.2.0, transformers 4.51.3. Bootstrap will fail or produce version conflicts with stale pins. | LOW | Update `remote-embedding-requirements.txt` to match actual dionysus environment. Alternatively switch to `--system-site-packages` venv strategy that inherits the conda-managed stack and skip pip install entirely. |
| Apple NL baseline on Mac | The comparison harness runs `evaluate_embedding_space.py` with `--embedding-backend apple_nl` as the local baseline. This must work from the Mac client that triggers the comparison. | LOW | Already implemented. Requires Swift + NaturalLanguage on the triggering Mac. No change needed. |
| Expanded model roster beyond BGE-small/base + E5-base | Three models is not enough to make an informed backend selection. Scholarly text is a niche domain; MTEB aggregate scores are not reliable proxies. Need at least 6-8 models spanning size tiers. | MEDIUM | Current `remote-backends.json` declares 3 models. Must add models, validate VRAM fit, and set appropriate batch sizes per model. See "Model Roster" section below for specifics. |
| Per-model batch size configuration | All models currently share `--batch-size 32`. Large models at batch 32 will exceed 11GB VRAM and OOM. Need per-model batch size or adaptive sizing. | MEDIUM | The evaluator CLI accepts `--batch-size` but the comparison harness passes one global value. The `remote-backends.json` schema needs `batch_size` per model or per model-size tier. |
| Comparison report with winner selection | Existing `choose_winner` algorithm and `render_markdown` report generator. Must work end-to-end with real metric payloads. | LOW | Already implemented with tiebreaking by runtime then model size. Needs validation with real data but no structural changes expected. |
| Manifest hash validation | Bundle and benchmark SHA256 comparison between local baseline and remote runs, ensuring identical inputs. | LOW | Already implemented in `choose_winner` which filters by `manifest_hash_match`. No changes needed. |

### Model Roster: Recommended Expansion

All models below fit in 11GB VRAM. Verified against MTEB benchmarks and VRAM profiling data.

**Current roster (3 models):**
- BAAI/bge-small-en-v1.5 (33M params, 384-dim)
- BAAI/bge-base-en-v1.5 (109M params, 768-dim)
- intfloat/e5-base-v2 (109M params, 768-dim)

**Recommended additions (5 models):**

| Model | Params | Dim | VRAM (batch=8) | Batch Size | Rationale |
|-------|--------|-----|----------------|------------|-----------|
| BAAI/bge-large-en-v1.5 | 335M | 1024 | ~2.5GB | 8 | Top of the BGE family; strong MTEB retrieval; fits easily |
| intfloat/e5-large-v2 | 335M | 1024 | ~2.5GB | 8 | E5 large variant; direct comparison with BGE-large |
| Alibaba-NLP/gte-large-en-v1.5 | 434M | 1024 | ~3.0GB | 8 | GTE family; competitive MTEB; different architecture (modernBERT-based) |
| BAAI/bge-m3 | 568M | 1024 | ~4.0GB | 4 | Multi-vector + sparse retrieval; 8192 token context; academic-length passages |
| nomic-ai/nomic-embed-text-v1.5 | 137M | 768 | ~1.5GB | 16 | Fully open (data + weights); 8192 context; Matryoshka dimensionality |

**Deferred (too large or incompatible):**
- SFR-Embedding-Mistral (7B): exceeds 11GB VRAM even at FP16
- e5-mistral-7b-instruct (7B): exceeds 11GB VRAM
- Qwen3-8b embedding: exceeds 11GB VRAM

### Differentiators (Competitive Advantage)

Features that make this system more useful than running MTEB benchmarks and picking the top scorer.

| Feature | Value Proposition | Complexity | Notes |
|---------|-------------------|------------|-------|
| Domain-specific evaluation on actual scholarly corpora | MTEB scores measure generic retrieval. Scholarly text (Levinas, Derrida) has unusual vocabulary, long sentences, commentary-dense pages. Twin cosine + hit@1 + MRR on the project's own corpora measures what matters. | LOW | Already implemented via the evaluator's multi-corpus, multi-view architecture. The existing `why-ethics` bundle and retrieval benchmark provide the domain-specific test data. |
| Multi-corpus, multi-view metric matrix | Compare embedding quality across `rag_linearized`, `semantic_flat_clean`, `spatial_main_plus_supplement` and across `body` vs `contextual` views. Reveals whether a model handles normalized scholarly text differently from contextual metadata. | LOW | Already implemented. Each comparison run produces metrics per corpus-view pair. |
| Normalized vs legacy projection comparison | The evaluator already computes both normalized (boilerplate-stripped) and legacy (raw) embeddings and reports delta metrics. Reveals whether normalization helps or hurts for each model. | LOW | Already implemented. Diagnostics include `metric_delta_vs_legacy` per document. |
| GLM-OCR extraction quality comparison | Run GLM-OCR page-by-page alongside existing extraction and compare markdown output quality for scholarly books with marginal glosses, footnotes, and complex layouts. | HIGH | This is exploration territory. GLM-OCR requires transformers >= 5.3.0 (dionysus has 4.51.3). Upgrading transformers may break sentence-transformers compatibility. Needs isolated environment or careful version management. See "GLM-OCR Exploration" section. |
| Extraction pipeline A/B comparison | Side-by-side comparison of current PyMuPDF + pdftotext + PaddleOCR extraction vs GLM-OCR extraction for the same pages, with structural diff and retrieval quality measurement. | HIGH | Requires a new comparison harness for extraction quality (not just embedding quality). Would measure: heading detection accuracy, footnote handling, margin gloss separation, table extraction, formula recognition. |
| Automatic batch size calibration per model | Run a binary-search calibration pass that finds the largest batch size that fits in 11GB VRAM for each model, store in config. Avoids OOM and maximizes throughput. | MEDIUM | `calibrate_embedding_timeout.py` already exists. Similar approach for VRAM-aware batch sizing. Could be a pre-flight step before the comparison run. |
| Historical comparison tracking | Store comparison results over time, detect whether a model's relative ranking changes as bundles evolve. | MEDIUM | Comparison runs already get timestamped run IDs. A lightweight report-over-time aggregator is the missing piece. |

### GLM-OCR Exploration: Dependency and Feasibility Analysis

**The dependency situation is the primary blocker:**

| Component | Installed on dionysus | Required by GLM-OCR | Compatible? |
|-----------|----------------------|---------------------|-------------|
| Python | 3.11+ (via conda base) | 3.12 recommended | Needs check; 3.11 may work |
| PyTorch | 2.9.1+cu126 | >= 2.0.0 | YES |
| transformers | 4.51.3 | >= 5.3.0 | NO -- major version upgrade required |
| sentence-transformers | 5.2.0 | N/A (not used by GLM-OCR) | Could break if transformers upgrades |
| CUDA | 12.6 (via PyTorch wheel) | CUDA support | YES |
| GPU VRAM | 11GB | 4-6GB at FP16 | YES |
| Compute capability | 6.1 (GTX 1080 Ti) | Not explicitly stated | UNKNOWN -- needs testing |

**Recommended approach:** Run GLM-OCR in an isolated conda environment separate from the embedding evaluation stack. This avoids destabilizing the working sentence-transformers + PyTorch setup.

**GLM-OCR capabilities relevant to scholarly PDFs:**
- Markdown output format (directly comparable to existing pipeline output)
- Table recognition and structure preservation
- Formula recognition (LaTeX output)
- 0.9B params means ~4-6GB VRAM, leaving room on 11GB GPU
- 1.86 pages/second throughput for PDF processing
- Multi-Token Prediction enables faster inference

**GLM-OCR limitations for this use case (LOW confidence, needs empirical validation):**
- Benchmarked primarily on financial documents, invoices, and standard academic papers
- Scholarly monographs with Talmud-like commentary pages, marginal glosses, and complex layout are NOT typical benchmark cases
- Table-of-contents extraction quality for book-length works is unknown
- Page-by-page processing model means cross-page structure inference (multi-page chapters) requires orchestration outside the model
- The official SDK uses PP-DocLayoutV3 for layout analysis -- this is a PaddlePaddle dependency

### Anti-Features (Commonly Requested, Often Problematic)

Features that seem good but create problems in this specific context.

| Feature | Why Requested | Why Problematic | Alternative |
|---------|---------------|-----------------|-------------|
| Replace Apple NL with the best open-source model as canonical gate | "Why maintain two systems?" | Apple NL is the stable, reproducible, Mac-local baseline. Replacing it couples the canonical gate to a GPU host, PyTorch versions, and model availability. The whole point of the comparison is to INFORM backend selection without REPLACING the canonical gate prematurely. | Keep Apple NL as canonical gate. Use comparison results to select the best dionysus-hosted backend for a separate RAG deployment path. |
| Run 7B embedding models on 11GB GPU | Largest models (SFR-Embedding-Mistral, e5-mistral-7b-instruct) top MTEB leaderboards | 7B models at FP16 require 14+ GB VRAM. Quantization to 4-bit fits but degrades embedding quality unpredictably for dense retrieval. The 11GB GPU is better utilized by running multiple well-sized models than one quantized giant. | Stick to models under 600M params. BGE-large, E5-large, GTE-large, and BGE-M3 cover the competitive range that fits in 11GB. |
| Full GLM-OCR pipeline replacement in v1.1 | "GLM-OCR is SOTA, just switch" | The existing pipeline (PyMuPDF + pdftotext + PaddleOCR) is stable, tested, and produces auditable bundles. GLM-OCR is a VLM that generates text autoregressively -- its outputs are less deterministic and require different validation. Replacing a working pipeline with an unvalidated one in the same milestone as live embedding evaluation creates too many moving parts. | Explore GLM-OCR in isolation. Run it on representative pages, compare output quality, then decide whether to integrate in a future milestone. |
| Parallel GPU evaluation of multiple models | "Run all models simultaneously to save time" | GTX 1080 Ti has 11GB. Running multiple models concurrently guarantees OOM. Even staggered loading risks memory fragmentation. | Run models sequentially. Each model load/unload cycle is fast (seconds). Total wall-clock for 8 models is still under 30 minutes for a typical bundle. |
| Remote evaluation from iPhone (orpheus) | "Trigger comparison runs from phone" | SSH tunneling works, but the comparison harness depends on local Apple NL baseline execution on Mac. The Mac must be the trigger. | Trigger from apollo (MacBook). Use phone only for monitoring. |
| Ollama-based GLM-OCR deployment | "Ollama is simpler than raw transformers" | Ollama bundles model + runtime but provides less control over inference parameters, no access to intermediate representations, and unclear whether the GGUF quantization preserves OCR quality. For evaluation/comparison purposes, direct transformers or vLLM access is better. | Use transformers or vLLM directly for evaluation. Consider Ollama only for eventual production deployment if GLM-OCR proves its worth. |

## Feature Dependencies

```
[Live SSH evaluation cycle]
    |
    +--requires--> [Requirements file update]
    |
    +--requires--> [Per-model batch size configuration]
    |
    +--requires--> [Expanded model roster]
    |
    +--enhances--> [Comparison report with winner selection]
    |
    +--enhances--> [Domain-specific evaluation on actual scholarly corpora]

[Expanded model roster]
    +--requires--> [Per-model batch size configuration]
    +--enhances--> [Automatic batch size calibration per model]

[GLM-OCR extraction quality comparison]
    +--requires--> [Isolated conda environment with transformers >= 5.3.0]
    +--conflicts--> [Requirements file update] (different transformers versions)
    +--enhances--> [Extraction pipeline A/B comparison]

[Extraction pipeline A/B comparison]
    +--requires--> [GLM-OCR extraction quality comparison]
    +--requires--> [Comparison report framework] (new, extraction-focused)

[Apple NL baseline on Mac] --independent--> [Live SSH evaluation cycle]
```

### Dependency Notes

- **Live evaluation requires requirements update:** The stale requirements.txt will cause bootstrap failures or version conflicts on dionysus. This must be fixed before any live run.
- **Expanded roster requires per-model batch sizes:** Adding BGE-large and BGE-M3 at the default batch size of 32 will OOM. Batch sizes must be configurable per model.
- **GLM-OCR conflicts with embedding stack:** GLM-OCR needs transformers >= 5.3.0; the embedding evaluation stack runs on 4.51.3. These must live in separate environments on dionysus. This is a HARD constraint -- do not upgrade the embedding environment's transformers to accommodate GLM-OCR.
- **Extraction A/B comparison requires GLM-OCR working first:** Cannot build the comparison harness until GLM-OCR runs successfully on representative scholarly pages.

## MVP Definition

### Launch With (v1.1 Core)

Minimum viable milestone -- what's needed to deliver the stated v1.1 goal of live measured comparisons.

- [ ] **Requirements file update** -- Align pinned deps with actual dionysus environment (torch 2.9.1+cu126, sentence-transformers 5.2.0, transformers 4.51.3) or switch to system-site-packages strategy
- [ ] **Per-model batch size in remote-backends.json** -- Add `batch_size` field per model entry; evaluator reads it instead of the global default
- [ ] **Expanded model roster** -- Add BGE-large, E5-large, GTE-large, BGE-M3, nomic-embed to backends config with appropriate batch sizes
- [ ] **Live evaluation end-to-end** -- Run the comparison harness without `--dry-run` and produce a real comparison-summary.json with measured metrics
- [ ] **Validated winner selection** -- Confirm `choose_winner` produces sensible results with real metric payloads from 8 models

### Add After Validation (v1.1 Extended)

Features to add once the core live comparison works.

- [ ] **Automatic batch size calibration** -- Pre-flight VRAM probing that finds optimal batch size per model, triggered by a --calibrate flag
- [ ] **GLM-OCR isolated environment setup** -- Separate conda env with transformers >= 5.3.0, PyTorch, and GLM-OCR dependencies
- [ ] **GLM-OCR page extraction smoke test** -- Run GLM-OCR on 5-10 representative pages from why-ethics and challenge corpus, produce markdown output, manual quality assessment
- [ ] **Historical comparison report** -- Lightweight aggregator that reads past comparison-summary.json files and shows model ranking stability

### Future Consideration (v2+)

Features to defer until the comparison data informs next steps.

- [ ] **Extraction pipeline A/B harness** -- Structured comparison between current pipeline and GLM-OCR extraction with automated quality metrics
- [ ] **GLM-OCR integration into conversion pipeline** -- If exploration proves GLM-OCR handles scholarly layouts better, integrate as an alternative extraction backend
- [ ] **Best-backend auto-selection for RAG deployment** -- Use comparison history to auto-configure the dionysus RAG backend
- [ ] **Cross-book model stability testing** -- Run the comparison across multiple books (not just why-ethics) to check whether model rankings are stable

## Feature Prioritization Matrix

| Feature | User Value | Implementation Cost | Priority |
|---------|------------|---------------------|----------|
| Live evaluation end-to-end | HIGH | LOW | P1 |
| Requirements file update | HIGH | LOW | P1 |
| Per-model batch size config | HIGH | LOW | P1 |
| Expanded model roster | HIGH | MEDIUM | P1 |
| Validated winner selection | HIGH | LOW | P1 |
| Automatic batch size calibration | MEDIUM | MEDIUM | P2 |
| GLM-OCR isolated environment | MEDIUM | MEDIUM | P2 |
| GLM-OCR page extraction smoke test | MEDIUM | MEDIUM | P2 |
| Historical comparison report | LOW | LOW | P2 |
| Extraction pipeline A/B harness | MEDIUM | HIGH | P3 |
| GLM-OCR pipeline integration | HIGH | HIGH | P3 |
| Cross-book model stability | MEDIUM | MEDIUM | P3 |

**Priority key:**
- P1: Must have for v1.1 milestone core
- P2: Should have, add when core is validated
- P3: Future milestone, informed by v1.1 results

## Competitor Feature Analysis

Comparison of approaches to the same problems in the ecosystem.

| Feature | MTEB Leaderboard Approach | RAGBench / Ragas Approach | Our Approach |
|---------|--------------------------|--------------------------|--------------|
| Model selection | Aggregate scores across generic benchmarks | Evaluate on synthetic Q&A over user corpus | Evaluate on hand-curated scholarly benchmark with twin cosine + retrieval metrics across multiple corpus representations |
| Evaluation corpora | Fixed benchmark datasets | User-provided or generated | Multiple corpus views (rag, semantic, spatial) of the same book, testing normalization effects |
| Baseline comparison | N/A (absolute scores) | No structured baseline | Apple NL as stable canonical baseline with delta reporting |
| Hardware awareness | Assumes cloud/API | Assumes cloud/API | Explicit 11GB GPU constraint, per-model batch sizing, SSH remote execution |
| OCR quality evaluation | N/A | N/A | Side-by-side page extraction comparison (planned) |

## Internal Tensions

| Feature | Tension Introduced | Constraint Mechanism | Residual Risk |
|---------|--------------------|---------------------|---------------|
| GLM-OCR exploration | Introduces a second Python environment with different transformers version on the same machine. Environment isolation complexity grows. | Separate conda env for GLM-OCR; never mix with embedding evaluation env. | If a future feature needs both GLM-OCR and sentence-transformers in the same process, the version split becomes a real problem. |
| Expanded model roster | More models means longer comparison wall-clock and more VRAM management complexity. | Per-model batch sizes; sequential execution; optional `--backend-ids` filter to run subsets. | If a model silently OOMs and torch catches the error, the comparison harness must handle partial failures gracefully (it currently does via `failure_stage` tracking). |
| Live evaluation replacing dry-run as default | Live runs mutate remote state (create dirs, download models, consume VRAM). Accidental live runs during development could be expensive. | Keep `--dry-run` as explicit opt-in flag; consider adding `--live` flag to make live execution intentional rather than default. | Operator muscle memory may default to live runs that take 20+ minutes. |

## Sources

- [Hugging Face: GLM-OCR model card](https://huggingface.co/zai-org/GLM-OCR) -- model architecture, requirements, inference examples
- [GitHub: zai-org/GLM-OCR](https://github.com/zai-org/GLM-OCR) -- installation tiers, dependency chain, pyproject.toml
- [MTEB Leaderboard](https://huggingface.co/spaces/mteb/leaderboard) -- model ranking, benchmark methodology
- [Hugging Face: BAAI/bge-large-en-v1.5](https://huggingface.co/BAAI/bge-large-en-v1.5) -- model specs, VRAM profiling
- [Hugging Face: BAAI/bge-m3](https://huggingface.co/BAAI/bge-m3) -- multi-vector retrieval, 8192 context
- [Snowflake Arctic Embed](https://github.com/Snowflake-Labs/arctic-embed) -- nomic-embed lineage, long context
- [VRAM batch size analysis](https://medium.com/@vici0549/it-is-crucial-to-properly-set-the-batch-size-when-using-sentence-transformers-for-embedding-models-3d41a3f8b649) -- VRAM profiling for embedding models
- [PyTorch compute capability discussion](https://discuss.pytorch.org/t/what-version-of-pytorch-is-compatible-with-nvidia-geforce-gtx-1080/222056) -- GTX 1080 Ti cu126 support status
- [vLLM GLM-OCR guide](https://docs.vllm.ai/projects/recipes/en/latest/GLM/GLM-OCR.html) -- deployment, inference configuration
- [PaddleOCR 3.0](https://github.com/PaddlePaddle/PaddleOCR) -- current PaddleOCR state, PaddleOCR-VL developments
- Verified on dionysus: PyTorch 2.9.1+cu126, CUDA working, GTX 1080 Ti compute capability 6.1 confirmed functional, sentence-transformers 5.2.0, transformers 4.51.3

---
*Feature research for: Live embedding evaluation and vision-language OCR exploration*
*Researched: 2026-03-19*
