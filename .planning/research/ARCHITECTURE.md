# Architecture Research

**Domain:** Scholarly PDF conversion -- remote GPU embedding evaluation and GLM-OCR extraction exploration
**Researched:** 2026-03-19
**Confidence:** HIGH (embedding expansion), MEDIUM (GLM-OCR integration)

## System Overview

```
Mac (apollo) ──SSH──> Dionysus (GTX 1080 Ti, 11GB VRAM)
     |                      |
     |  remote_backends.py  |  evaluate_embedding_space.py
     |  (orchestrator)      |  (evaluator, runs on GPU)
     |                      |
     |  rsync bundle -----> |  /home/rookslog/pdfmd-remote-experiments/
     |  rsync evaluator --> |  {run_id}/{backend_id}/
     |  rsync benchmark --> |  venv/ (sentence-transformers)
     |                      |
     |  <---- rsync results |  models/{model_slug}/evaluation.json
     |                      |
     |  compare-backends    |  PaddleOCR Docker (port 8765, CPU/GPU)
     |  (Makefile target)   |
     |                      |  [NEW] GOT-OCR2 exploration
     v                      v
  generated/embedding-backend-comparison/
```

### Current Pipeline (Dry-Run Only)

```
Mac                               Dionysus
 |                                   |
 | 1. probe (SSH python -c ...)      |
 |---------------------------------->| nvidia-smi, torch, imports
 |<----------------------------------|
 | 2. bootstrap (SSH venv setup)     |
 |---------------------------------->| create venv, install deps
 |<----------------------------------|
 | 3. rsync bundle + evaluator       |
 |---------------------------------->| /pdfmd-remote-experiments/{run}/
 | 4. evaluate (SSH python eval)     |
 |---------------------------------->| load model -> GPU -> embed -> score
 |<----------------------------------|
 | 5. tar + rsync results            |
 |<----------------------------------| evaluation.json
 | 6. compare vs local Apple NL      |
 | 7. render markdown summary        |
 v                                   |
 generated/embedding-backend-comparison/{run_id}/
```

### Expanded Pipeline (Live + GLM-OCR)

```
Mac                               Dionysus
 |                                   |
 |=== EMBEDDING EVALUATION ==========|
 | 1. probe                          |
 |---------------------------------->| (existing, unchanged)
 | 2. bootstrap                      |
 |---------------------------------->| (existing, may need updated reqs)
 | 3. rsync bundle                   |
 |---------------------------------->| (existing, unchanged)
 | 4. evaluate per-model             |
 |-- bge-small-en-v1.5 ------------>| ~250MB VRAM, fast
 |-- bge-base-en-v1.5 ------------->| ~500MB VRAM
 |-- e5-base-v2 ------------------->| ~500MB VRAM
 |-- [NEW] bge-large-en-v1.5 ------>| ~1.5GB VRAM
 |-- [NEW] e5-large-v2 ------------>| ~1.5GB VRAM
 |-- [NEW] gte-base-en-v1.5 ------->| ~500MB VRAM
 |-- [NEW] nomic-embed-text-v1.5 -->| ~550MB VRAM
 |-- [NEW] BGE-M3 ----------------->| ~2.2GB VRAM (multi-func)
 | 5. tar + fetch results            |
 | 6. compare + render               |
 |                                   |
 |=== GLM-OCR EXPLORATION ===========|
 | [NEW] 7. rsync PDF page images    |
 |---------------------------------->| /pdfmd-remote-experiments/{run}/ocr/
 | [NEW] 8. run GOT-OCR2 inference   |
 |---------------------------------->| ~4GB VRAM, sequential pages
 | [NEW] 9. fetch OCR results        |
 |<----------------------------------| page-level markdown/text output
 | [NEW] 10. compare vs PyMuPDF      |
 v                                   v
```

## Component Responsibilities

| Component | Responsibility | Status | Changes Required |
|-----------|----------------|--------|------------------|
| `remote_backends.py` | SSH orchestration: probe, bootstrap, evaluate, fetch, compare | EXISTS, dry-run only | Remove `--dry-run` default from Makefile; add VRAM guard; add OCR orchestration mode |
| `embedding_space.py` | Core evaluation: build corpora, embed, compute twin cosine/hit@1/MRR | EXISTS, stable | No changes for embedding expansion. Add OCR corpus variant for GLM extraction comparison |
| `evaluate_embedding_space.py` | Re-export from `embedding_space.py` | EXISTS, thin wrapper | Unchanged |
| `remote-backends.json` | Backend config with SSH target, models list, device config | EXISTS, 3 models | Add new models to `models` array; add optional `vram_budget_mb` field |
| `remote-embedding-requirements.txt` | Pinned Python deps for remote venv | EXISTS, pins torch 2.4.1 | Update torch version; add GOT-OCR2 deps in separate file |
| `Makefile` target `compare-backends` | Entry point for operators | EXISTS, hardcoded `--dry-run` | Remove `--dry-run`; add `compare-backends-live` and `explore-ocr` targets |
| `common/manifests.py` | Manifest schema for artifact tracking | EXISTS, stable | Add `ocr_exploration` manifest kind |
| **[NEW]** `remote_ocr.py` | GLM-OCR exploration: rsync images, run GOT-OCR2, fetch results | NEW | Build from scratch, reuse SSH primitives from `remote_backends.py` |
| **[NEW]** `ocr_comparison.py` | Compare GOT-OCR2 output vs PyMuPDF extraction per-page | NEW | Diff-based comparison reporting |
| **[NEW]** `remote-ocr-requirements.txt` | Pinned deps for GOT-OCR2 venv (separate from embedding venv) | NEW | transformers, torch, tiktoken |
| **[NEW]** `vram_budget.py` | VRAM-aware model sequencing to prevent OOM on 11GB card | NEW | Query nvidia-smi, enforce budget, serialize large models |

## Recommended Project Structure Changes

```
src/pdfmd/benchmarks/
    embedding_space.py         # EXISTING - no changes needed
    evaluate_embedding_space.py # EXISTING - thin re-export
    remote_backends.py         # EXISTING - refactor SSH primitives out
    compare_embedding_backends.py # EXISTING - thin re-export
    remote_ocr.py              # NEW - GOT-OCR2 exploration orchestrator
    ocr_comparison.py          # NEW - extraction comparison logic
    vram_budget.py             # NEW - VRAM budget guard

skills/pdf-to-structured-markdown/references/
    remote-backends.json                  # MODIFY - expand models list
    remote-embedding-requirements.txt     # MODIFY - version updates
    remote-ocr-requirements.txt           # NEW - GOT-OCR2 deps
    remote-vram-budget.json               # NEW - per-model VRAM hints

generated/
    embedding-backend-comparison/         # EXISTING - live results go here
    ocr-exploration/                      # NEW - GOT-OCR2 results
```

### Structure Rationale

- **Separate venvs for embedding vs OCR:** GOT-OCR2 has different dependency chains (tiktoken, possibly different transformers version) than sentence-transformers. Isolating them prevents version conflicts on the remote host and allows independent bootstrap/teardown.
- **`vram_budget.py` as a standalone module:** VRAM management is a cross-cutting concern shared by both embedding eval (many small models sequentially) and OCR exploration (one large model holding GPU). Centralizing it prevents the orchestrator from accidentally scheduling overlapping GPU loads.
- **OCR results in separate `generated/` subtree:** Keeps the embedding evaluation artifacts cleanly separated from the extraction exploration, which has different artifact shapes (page images in, text/markdown out vs embeddings in, metrics out).

## Architectural Patterns

### Pattern 1: Sequential Model Evaluation with VRAM Guards

**What:** Run embedding models one-at-a-time, querying `nvidia-smi` between runs to verify the previous model released its GPU memory before loading the next.

**When to use:** Always, for the embedding expansion. The GTX 1080 Ti has 11GB. No single embedding model needs more than ~2.5GB, but if a model leaks or the previous process does not exit cleanly, loading the next model can OOM.

**Trade-offs:** Slower than parallel (models run sequentially), but safe. On an 11GB card with models under 2.5GB each, the overhead of sequential execution is negligible compared to the risk of a failed run due to OOM.

**Example:**
```python
def evaluate_models_sequentially(
    backend: dict,
    models: list[str],
    vram_budget_mb: int = 10000,
    *,
    dry_run: bool = False,
) -> list[dict]:
    results = []
    for model_name in models:
        # Check VRAM is available before loading
        free_vram = query_remote_vram(backend["ssh_target"])
        model_estimate = MODEL_VRAM_HINTS.get(model_name, 2000)
        if free_vram < model_estimate + 500:  # 500MB safety margin
            results.append({"model": model_name, "status": "skipped_vram"})
            continue
        result = run_single_evaluation(backend, model_name, dry_run=dry_run)
        results.append(result)
    return results
```

### Pattern 2: SSH Primitive Extraction

**What:** Extract reusable SSH/rsync building blocks from `remote_backends.py` so both embedding evaluation and OCR exploration share the same transport layer.

**When to use:** When adding the OCR exploration path. The existing `build_ssh_command`, `build_rsync_to_remote_command`, `build_rsync_from_remote_command`, `run_command`, and `parse_json_stdout` functions are generic and should be importable by `remote_ocr.py`.

**Trade-offs:** Requires a refactor of `remote_backends.py` to separate transport from evaluation orchestration. The transport functions are already clean and stateless -- they just need to be in a module that is not also the 1300-line orchestrator.

**Implementation approach:**
```
src/pdfmd/benchmarks/
    ssh_transport.py           # Extracted: build_ssh_command, rsync helpers,
                               # run_command, parse_json_stdout, remote probe
    remote_backends.py         # Keeps orchestration, imports from ssh_transport
    remote_ocr.py              # OCR orchestration, imports from ssh_transport
```

### Pattern 3: Dual-Venv Remote Bootstrap

**What:** Maintain two separate virtual environments on the remote host -- one for sentence-transformers embedding models, one for GOT-OCR2 inference. Each has its own requirements file and bootstrap flow.

**When to use:** Always, for this project. GOT-OCR2 wants `transformers>=4.37.2` plus `tiktoken` and `verovio`, while the embedding venv wants `sentence-transformers==3.0.1` with `transformers==4.44.2`. Mixing them risks version conflicts, especially around the `transformers` library.

**Trade-offs:** Doubles the bootstrap time on first run. But bootstrapping is a one-time cost per run-id, and the isolation prevents debugging dependency hell across two unrelated model types.

**Remote directory layout:**
```
/home/rookslog/pdfmd-remote-experiments/{run_id}/{backend_id}/
    venv/                    # embedding models (sentence-transformers)
    ocr-venv/                # GOT-OCR2 (transformers + tiktoken)
    bundle/                  # shared corpus data
    models/{model_slug}/     # embedding evaluation artifacts
    ocr/{page_id}/           # OCR exploration artifacts
```

### Pattern 4: Page-Image Pipeline for GLM-OCR

**What:** For OCR exploration, render PDF pages to images on the Mac (using PyMuPDF/fitz), rsync the images to dionysus, run GOT-OCR2 inference per-page on GPU, fetch results back.

**When to use:** For the GLM-OCR exploration phase specifically. GOT-OCR2 takes images as input (1024x1024 max), not PDF bytes. The rendering can happen on the Mac where PyMuPDF is already installed, keeping the remote host focused on GPU inference.

**Trade-offs:** More data transfer (images are larger than text). But rendering on Mac keeps the remote environment minimal, and the scholarly PDFs are typically under 400 pages, so even at 2MB/page the total transfer is manageable over Tailscale.

**Data flow:**
```
Mac: PDF -> fitz.open() -> page.get_pixmap(dpi=300) -> PNG
Mac: rsync PNGs -> dionysus:/pdfmd-remote-experiments/{run}/ocr/pages/
Dionysus: GOT-OCR2 -> per-page markdown output
Dionysus: results -> /pdfmd-remote-experiments/{run}/ocr/results/
Mac: rsync results <- dionysus
Mac: compare GOT output vs PyMuPDF extraction per-page
```

## Data Flow Changes

### Existing Data Flow (Unchanged)

```
Source PDF -> convert_pdf.py -> bundle (metadata.json, markdown, RAG, sidecars)
                                  |
                                  v
                     evaluate_embedding_space.py
                     (builds corpora from bundle, embeds, scores)
```

### New Data Flow: Live Embedding Comparison

```
Mac:
  1. bundle_dir + benchmark.json (existing, generated locally)
  2. remote_backends.py orchestrates:
     - probe dionysus GPU state
     - bootstrap venv if needed
     - rsync bundle + evaluator + requirements
     - for each model in expanded list:
         - SSH: run evaluate_embedding_space.py --embedding-backend sentence_transformers
         - VRAM guard between models
     - tar + fetch evaluation.json per model
     - aggregate metrics, compute deltas vs Apple NL baseline
  3. Output: generated/embedding-backend-comparison/{run_id}/
     - comparison-summary.json (with all models)
     - comparison-summary.md (readable report)
     - per-model artifacts in {backend_id}/{model_slug}/
```

### New Data Flow: GOT-OCR2 Exploration

```
Mac:
  1. Source PDF (existing, e.g. Gibbs_WhyEthics.pdf)
  2. remote_ocr.py orchestrates:
     - render select pages to PNG (Mac-side, using fitz)
     - probe dionysus GPU state
     - bootstrap ocr-venv if needed (separate from embedding venv)
     - rsync page images to dionysus
     - SSH: run GOT-OCR2 inference per page
     - fetch per-page markdown results
  3. ocr_comparison.py:
     - load PyMuPDF extraction for same pages
     - diff GOT-OCR2 output vs PyMuPDF output
     - report: which pages GOT handles better (tables, formulas, marginal notes)
  4. Output: generated/ocr-exploration/{run_id}/
     - per-page GOT-OCR2 output
     - comparison report (GOT vs PyMuPDF vs PaddleOCR)
     - exploration-summary.json + .md
```

## Integration Points

### Existing Components That Change

| Component | Change | Risk |
|-----------|--------|------|
| `Makefile` `compare-backends` target | Remove `--dry-run` flag | LOW -- just a flag removal; add `compare-backends-dry` alias for safety |
| `remote-backends.json` | Add ~5 models to `models` array | LOW -- purely additive, existing models unchanged |
| `remote-embedding-requirements.txt` | Verify/update version pins | MEDIUM -- torch version mismatch: file pins `2.4.1`, system has `2.9.1+cu126`. Must decide which. |

### New Components

| Component | Purpose | Dependencies |
|-----------|---------|--------------|
| `ssh_transport.py` | Shared SSH/rsync primitives | Extracted from `remote_backends.py` |
| `vram_budget.py` | VRAM monitoring and model scheduling | `ssh_transport.py` for remote nvidia-smi |
| `remote_ocr.py` | GOT-OCR2 exploration orchestrator | `ssh_transport.py`, `vram_budget.py` |
| `ocr_comparison.py` | Diff GOT-OCR2 vs PyMuPDF extraction | Core text comparison logic |
| `remote-ocr-requirements.txt` | GOT-OCR2 remote deps | transformers>=4.44, torch, tiktoken, accelerate |
| `remote-vram-budget.json` | Per-model VRAM hints | Static config, updated empirically |

### Internal Boundaries

| Boundary | Communication | Notes |
|----------|---------------|-------|
| Mac orchestrator <-> dionysus GPU | SSH + rsync | Existing pattern, well-tested in dry-run mode |
| Embedding venv <-> OCR venv | None (fully isolated) | Different requirements files, different venv dirs |
| `remote_backends.py` <-> `ssh_transport.py` | Direct import | Refactor; `remote_backends.py` becomes thinner |
| `remote_ocr.py` <-> `ssh_transport.py` | Direct import | New module, same transport layer |
| `remote_backends.py` <-> `vram_budget.py` | Direct import | VRAM checks inserted between model evaluations |
| `remote_ocr.py` <-> `vram_budget.py` | Direct import | VRAM check before loading GOT-OCR2 |
| Embedding results <-> OCR results | Separate `generated/` subtrees | No cross-contamination of artifacts |

### External Services

| Service | Integration Pattern | Notes |
|---------|---------------------|-------|
| PaddleOCR Docker (port 8765) | HTTP API from Mac or local | Already running on dionysus, CPU-bound. Not modified. |
| GOT-OCR2 (HuggingFace) | Model download on first run | ~1.2GB download; cached in HF cache on dionysus |
| HuggingFace Hub | sentence-transformers model download | Models cached in ~/.cache/huggingface/ on dionysus |

## Hardware Constraints and VRAM Budget

### GTX 1080 Ti VRAM Budget (11,264 MB total)

| Model | Estimated VRAM (fp32) | Estimated VRAM (fp16) | Batch Size 32 Overhead | Total Estimate |
|-------|----------------------|----------------------|------------------------|----------------|
| bge-small-en-v1.5 (33M params) | ~130MB | ~66MB | ~200MB | ~330MB |
| bge-base-en-v1.5 (109M params) | ~440MB | ~220MB | ~400MB | ~840MB |
| bge-large-en-v1.5 (335M params) | ~1,340MB | ~670MB | ~600MB | ~1,940MB |
| e5-base-v2 (109M params) | ~440MB | ~220MB | ~400MB | ~840MB |
| e5-large-v2 (335M params) | ~1,340MB | ~670MB | ~600MB | ~1,940MB |
| gte-base-en-v1.5 (~109M params) | ~440MB | ~220MB | ~400MB | ~840MB |
| nomic-embed-text-v1.5 (~137M params) | ~550MB | ~275MB | ~400MB | ~950MB |
| BGE-M3 (~550M params) | ~2,200MB | ~1,100MB | ~800MB | ~3,000MB |
| GOT-OCR2 (580M params) | ~2,320MB | ~1,160MB | per-image | ~4,000MB |

**Key insight:** All models fit individually on the 11GB card with generous margin. The concern is not individual model size but sequential cleanup -- ensuring one model fully unloads before the next loads. This is why VRAM guards between evaluations matter.

**GOT-OCR2 note:** At ~4GB for inference, GOT-OCR2 comfortably fits on the 11GB card. It cannot run concurrently with the largest embedding models (BGE-M3 at ~3GB), but since embedding evaluation and OCR exploration are separate pipelines, this is not a conflict.

### CUDA Compatibility Note (IMPORTANT)

The remote host has a version discrepancy to resolve:
- **CUDA Toolkit installed:** 11.8 (nvcc reports 11.8, V11.8.89)
- **PyTorch installed (system):** 2.9.1+cu126 (compiled against CUDA 12.6)
- **Remote requirements pin:** torch==2.4.1 (the file `remote-embedding-requirements.txt`)
- **GOT-OCR2 repo documents:** cuda11.8+torch2.0.1
- **GPU Compute Capability:** 6.1 (GTX 1080 Ti)

The system PyTorch (2.9.1+cu126) works because the NVIDIA driver (550.163.01) supports CUDA 12.6 at the driver level even though the toolkit is 11.8. PyTorch uses the driver's runtime, not the toolkit's nvcc. **The requirements file pin of torch==2.4.1 is stale** -- the venv bootstrap will likely install its own torch version anyway due to `--system-site-packages` inheriting the system torch.

**Recommendation:** Update `remote-embedding-requirements.txt` to match the system's torch version (`2.9.1` or latest compatible), and create `remote-ocr-requirements.txt` separately. GOT-OCR2 is confirmed compatible with CUDA 11.8 environments, and the HuggingFace transformers integration (`GotOcr2ForConditionalGeneration`) works with recent transformers versions (4.44+).

## Scaling Considerations

| Scale | Architecture Adjustments |
|-------|--------------------------|
| 3-8 embedding models (current target) | Sequential evaluation with VRAM guards. ~10 min total. No changes needed. |
| 10-20 embedding models | Consider model-level parallelism if adding a second GPU. For single GPU, batch scheduling with priority (run cheapest first, gate expensive models on budget). |
| Multiple PDFs for OCR exploration | Add batch-page pipeline: render all pages first, then run GOT-OCR2 on all images sequentially. Current per-page approach is fine for <50 pages. |
| Adding more extraction models (Qwen2-VL, Florence-2) | Same dual-venv pattern; potentially a third venv if dependency conflicts arise. Or containerize each model. |

### Scaling Priorities

1. **First bottleneck:** Network transfer over Tailscale for large bundles. Mitigated by only syncing once per run (already the pattern).
2. **Second bottleneck:** Sequential model evaluation wall time. For 8 models at ~2 min each, total ~16 min. Acceptable for a nightly/manual experiment.

## Anti-Patterns

### Anti-Pattern 1: Concurrent GPU Model Loading

**What people do:** Run multiple embedding models simultaneously on the same GPU, or start OCR while an embedding model is still loaded.
**Why it is wrong:** The GTX 1080 Ti has no MIG (multi-instance GPU) support. Two models competing for 11GB VRAM will OOM unpredictably, and PyTorch's CUDA error recovery is poor -- often requiring a full process restart.
**Do this instead:** Run models strictly sequentially. Insert VRAM checks between runs. Kill the Python process between models if VRAM is not released (sentence-transformers sometimes holds GPU memory after `encode()` returns).

### Anti-Pattern 2: Shared Venv for Embedding + OCR

**What people do:** Install sentence-transformers AND GOT-OCR2 dependencies in the same venv to avoid duplication.
**Why it is wrong:** `transformers` version conflicts. sentence-transformers 3.0.1 pins transformers to a range; GOT-OCR2's trust_remote_code model may need specific transformers APIs. Debugging version conflicts remotely over SSH is painful.
**Do this instead:** Two venvs, two requirements files, two bootstrap flows. Disk is cheap; debugging time is not.

### Anti-Pattern 3: Rendering PDF Pages on the Remote Host

**What people do:** Send the entire PDF to the remote host and render pages there, requiring PyMuPDF installation on dionysus.
**Why it is wrong:** Adds a complex dependency (PyMuPDF + system libs) to the remote environment. The Mac already has PyMuPDF and a fast CPU. PDF rendering is CPU-bound, not GPU-bound.
**Do this instead:** Render on the Mac, rsync the images. Keeps the remote environment focused on GPU inference only.

### Anti-Pattern 4: Removing --dry-run Without a Smoke Test

**What people do:** Remove `--dry-run` from the Makefile and immediately run a full evaluation with all models.
**Why it is wrong:** The first live run will hit real network, real GPU, and real timing issues that dry-run mode cannot surface. First-run failures include: venv bootstrap on a fresh remote dir, SSH key timeouts, model download failures, VRAM pressure.
**Do this instead:** First live run should use `--backend-ids dionysus` with just ONE model (bge-small-en-v1.5, the cheapest). Verify end-to-end with one model, then expand.

## Suggested Build Order

The ordering below reflects technical dependencies and risk gradients:

### Phase A: Go Live with Existing Models (Foundation)

1. **Extract SSH transport primitives** -- Move `build_ssh_command`, `build_rsync_*`, `run_command`, `parse_json_stdout` from `remote_backends.py` into `ssh_transport.py`. Update imports. Run existing tests.
2. **Fix torch version pin** -- Update `remote-embedding-requirements.txt` to reflect the system torch or remove the pin (let the venv inherit system torch via `--system-site-packages`).
3. **Add VRAM guard module** -- Create `vram_budget.py` with `query_remote_vram()` (SSH nvidia-smi) and `check_vram_available()`.
4. **Remove dry-run default** -- Update Makefile to have `compare-backends` run live and `compare-backends-dry` for dry-run. Add VRAM guards to the evaluation loop in `remote_backends.py`.
5. **Smoke test with one model** -- Run live with `--backend-ids dionysus` and just `bge-small-en-v1.5`. Verify full pipeline: probe -> bootstrap -> rsync -> evaluate -> fetch -> compare.
6. **Run full existing model set** -- Evaluate all 3 existing models (bge-small, bge-base, e5-base). Verify comparison report.

### Phase B: Expand Embedding Model Set

7. **Add new models to config** -- Update `remote-backends.json` with bge-large, e5-large, gte-base, nomic-embed-text, BGE-M3.
8. **Add VRAM hints config** -- Create `remote-vram-budget.json` with per-model VRAM estimates.
9. **Run expanded evaluation** -- Evaluate all 8 models. Verify VRAM guards work (especially for BGE-M3 at ~3GB).
10. **Analyze results** -- Compare hit@1, MRR, twin cosine across all models. Identify best model for scholarly retrieval.

### Phase C: GOT-OCR2 Exploration

11. **Create OCR requirements** -- Write `remote-ocr-requirements.txt` (transformers, tiktoken, verovio, accelerate).
12. **Build page-image renderer** -- Mac-side script using fitz to render PDF pages to PNG at 300 DPI.
13. **Build `remote_ocr.py`** -- OCR exploration orchestrator using `ssh_transport.py`. Bootstrap OCR venv, rsync images, run inference, fetch results.
14. **Smoke test OCR** -- Run GOT-OCR2 on 3-5 pages from Why Ethics. Verify output quality.
15. **Build `ocr_comparison.py`** -- Compare GOT-OCR2 output vs PyMuPDF extraction per-page. Focus on tables, formulas, marginal notes.
16. **Run exploration on selected pages** -- Evaluate on pages known to be difficult for PyMuPDF (commentary-heavy, table pages, multi-column).

### Build Order Rationale

- **Phase A before Phase B:** Must prove the pipeline works end-to-end with known models before adding unknowns. A failure with bge-small (the cheapest model) reveals infrastructure issues; a failure with BGE-M3 might be a VRAM issue masked as an infrastructure issue.
- **Phase B before Phase C:** Embedding expansion is lower risk (same evaluator code, same data flow, just more models). OCR exploration introduces a new data flow (images instead of text), a new model type, and a new comparison methodology. Completing B builds confidence in the transport layer that C depends on.
- **SSH transport extraction first:** Both B and C depend on clean, importable SSH primitives. Extracting them once prevents copy-paste divergence.
- **VRAM guards before removing dry-run:** The dry-run removal is only safe if VRAM monitoring is in place. Without guards, the first live run might OOM on the second model and leave the remote host in a dirty state.

## Sources

- [GOT-OCR2 GitHub Repository](https://github.com/Ucas-HaoranWei/GOT-OCR2.0) -- confirmed CUDA 11.8 + torch 2.0.1 compatibility, 580M parameters
- [GOT-OCR2 HuggingFace Model Card](https://huggingface.co/stepfun-ai/GOT-OCR2_0) -- transformers integration, inference API
- [GOT-OCR2 Transformers Docs](https://huggingface.co/docs/transformers/en/model_doc/got_ocr2) -- `GotOcr2ForConditionalGeneration`, usage patterns
- [GOT-OCR2 Paper](https://arxiv.org/abs/2409.01704) -- 580M params, 80M encoder + 500M decoder architecture
- [Sentence-Transformers Documentation](https://sbert.net/) -- batch size, GPU encoding patterns
- [BGE-M3 HuggingFace](https://huggingface.co/BAAI/bge-m3) -- multi-functionality, ~550M params, 8192 token support
- [Top Embedding Models 2026](https://artsmart.ai/blog/top-embedding-models-in-2025/) -- MTEB leaderboard context
- [Best Open-Source Embedding Models 2026](https://www.bentoml.com/blog/a-guide-to-open-source-embedding-models) -- BGE, GTE, nomic comparison
- [Open-Source OCR Models Compared](https://modal.com/blog/8-top-open-source-ocr-models-compared) -- GOT-OCR2 vs alternatives
- Local verification: `nvidia-smi` on dionysus confirms GTX 1080 Ti, 11264 MiB, compute cap 6.1, driver 550.163.01
- Local verification: `python3 -c "import torch"` confirms torch 2.9.1+cu126, CUDA available
- Local verification: `nvcc --version` confirms CUDA toolkit 11.8 installed
- Local verification: `docker ps` confirms paddleocr-server running on port 8765

---
*Architecture research for: Remote embedding evaluation + GLM-OCR extraction exploration on scholarly PDF conversion system*
*Researched: 2026-03-19*
