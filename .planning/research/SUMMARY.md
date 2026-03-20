# Project Research Summary

**Project:** PDFAgentialConversion v1.1 — Remote Evaluation & Extraction Exploration
**Domain:** GPU-backend embedding evaluation + vision-language OCR exploration for scholarly PDF conversion
**Researched:** 2026-03-20
**Confidence:** HIGH (embedding infrastructure and stack), MEDIUM (GLM-OCR feasibility on this specific hardware)

## Executive Summary

PDFAgentialConversion v1.1 is a research tool, not a production application — and that distinction should drive every architectural decision. The core goal is to transition the SSH-orchestrated embedding evaluation pipeline from dry-run to live, expand the model roster from 3 to 8 models, and begin empirical exploration of GLM-OCR as a potential replacement for the existing PyMuPDF + pdftotext extraction baseline. The system already has a working pipeline skeleton; what it lacks is live execution validation and current dependency alignment. The most important finding across all four research files is that the dionysus hardware has drifted significantly from its documented state — the CUDA driver is 12.6 (not 11.8 as documented), PyTorch is 2.9.1+cu126 (not 2.4.1 as pinned), and sentence-transformers is 5.2.0 (not 3.0.1 as pinned). All requirements and code must be reconciled with the actual system before any live run can produce trustworthy results.

The recommended approach is a strict sequenced progression: first fix infrastructure (requirements alignment, SSH timeouts, hardcoded path guards, SSH primitive extraction), then validate the live pipeline with a single cheap model (bge-small-en-v1.5), then expand the model roster to 8 models, and only then explore GLM-OCR in a fully isolated environment. The two-venv requirement for GLM-OCR is a hard constraint, not a preference — GLM-OCR requires transformers >=5.3.0 while the embedding evaluation stack must stay on 4.51.x. These cannot coexist in a single Python environment under any circumstances. Additionally, the GTX 1080 Ti (Pascal, compute capability 6.1) has two hardware constraints that will affect GLM-OCR: no native bfloat16 (must use fp16 explicitly), and no Flash Attention 2 (must use SDPA fallback, which increases VRAM consumption). Both are manageable but must be the first things validated when GLM-OCR work begins.

The key risk is scope creep across the two workstreams. Embedding evaluation and OCR exploration are genuinely independent, with conflicting dependency requirements. Attempting to merge them creates version conflicts and ambiguous failure modes. The research is consistent and opinionated: do not replace Apple NL as the canonical gate, do not run 7B parameter models on the 1080 Ti, do not use Ollama for GLM-OCR evaluation, and do not attempt full extraction pipeline replacement in this milestone. The milestone is complete when it produces a real comparison-summary.json with measured metrics across 8 embedding models, and when GLM-OCR runs on representative scholarly pages producing markdown output that can be assessed for quality.

## Key Findings

### Recommended Stack

The system stack is substantially more current than documented. The `--system-site-packages` bootstrap approach means the venv silently inherits system versions rather than enforcing pinned ones — the requirements file is both misleading and unenforced. Updating `remote-embedding-requirements.txt` to match system reality is the highest-priority action before any live run.

For the embedding roster expansion, 5 new models are recommended. All fit in 10.3 GB usable VRAM, all load via sentence-transformers 5.x, and they span a meaningful quality/speed tradeoff space: a size-ladder completion (bge-large), a MTEB leader with Matryoshka dims (stella), a long-context lightweight model (nomic-embed), a retrieval-optimized multilingual model (snowflake-arctic-embed), and a multi-modal retrieval model with 8192-token context (bge-m3). Two models (stella, nomic-embed) require `trust_remote_code=True` — a confirmed one-line change needed in `load_embeddings_sentence_transformers()`. The GLM-OCR venv must be created WITHOUT `--system-site-packages` to prevent it inheriting transformers 4.51.x and blocking the 5.3+ requirement.

**Core technologies:**
- PyTorch >=2.9.0,<3.0.0: GPU tensor computation — already installed, cu126 build verified working on GTX 1080 Ti sm_61
- sentence-transformers >=5.2.0,<6.0.0: Embedding model loading/inference — already installed; 5.x adds Matryoshka support and prompt-name handling required by stella
- transformers >=4.51.0,<5.0.0 (embedding venv): Embedding model backbone — already installed; must NOT be upgraded to 5.x in this environment
- transformers >=5.3.0 (GLM-OCR venv only): GLM-OCR backbone — hard requirement; incompatible with embedding stack; isolated venv mandatory
- GLM-OCR 0.9B (fp16): VLM-OCR exploration candidate — ~3.3 GB total VRAM with inference buffers, fits on 1080 Ti; purpose-built for document OCR

**What NOT to use:**
- Any 7B+ embedding model (e5-mistral, SFR-Embedding-Mistral): exceeds 10.9 GB VRAM; quantized embeddings have unpredictable quality degradation
- bf16 dtype anywhere on dionysus: GTX 1080 Ti lacks native bfloat16; use fp16
- Flash Attention 2: compute capability 6.1 is below the 8.0 minimum; PyTorch SDPA fallback is the correct choice
- Single shared venv for embedding + GLM-OCR: transformers version split makes this impossible

### Expected Features

**Must have (table stakes — v1.1 Core):**
- Requirements file update — stale 18+ months; live runs produce non-deterministic venv state until reconciled
- SSH timeout and keepalive — `run_command()` has no timeout; a hung GPU evaluation will block the orchestrator indefinitely; prerequisite for going live
- Per-model batch size in remote-backends.json — current global batch-size=32 will OOM bge-m3 and larger models
- Live evaluation end-to-end — the stated milestone goal; smoke test with one model first, then expand
- Expanded model roster (8 total) — adds bge-large, stella, nomic-embed, snowflake-arctic-embed-m-v2.0, bge-m3
- Validated winner selection — confirm `choose_winner` produces sensible results with real metric payloads

**Should have (v1.1 Extended — add after core validates):**
- GLM-OCR isolated venv setup — separate venv with transformers >=5.3.0, no system site packages
- GLM-OCR page extraction smoke test — 5-10 representative pages from why-ethics corpus, manual quality assessment
- VRAM guard between model evaluations — nvidia-smi check before each model load
- Hardcoded path guard — defensive error if `/Users/rookslog/` path is dereferenced on remote host

**Defer (v2+, informed by v1.1 results):**
- Extraction pipeline A/B harness — structured comparison with automated quality metrics; requires GLM-OCR validated first
- GLM-OCR integration into conversion pipeline — only warranted if smoke test proves value on scholarly layouts
- Automatic batch size calibration — quality-of-life improvement, not blocking
- Cross-book model stability testing — requires comparison data from multiple completed runs
- Historical comparison tracking — needs multiple runs to be meaningful
- olmOCR-2-7B-FP8 evaluation — VRAM too tight (~0.3 GB headroom) to be safe without dedicated investigation

### Architecture Approach

The architecture is a Mac-orchestrated, SSH-transport pipeline where apollo handles orchestration, Apple NL baseline, and PDF rendering; dionysus provides GPU compute for embedding inference and VLM-OCR. The two pipelines — embedding evaluation and OCR exploration — are kept completely separate: different venvs, different remote directories, different generated output subtrees, different requirements files, and different orchestrator modules. The core architectural work for v1.1 is extracting the SSH transport primitives from the 1300-line `remote_backends.py` into a reusable `ssh_transport.py` so both the embedding orchestrator and a new `remote_ocr.py` can share the same transport layer without code duplication.

**Major components:**
1. `ssh_transport.py` (NEW, extracted from remote_backends.py) — reusable SSH/rsync primitives shared by both evaluation paths
2. `remote_backends.py` (MODIFY) — embedding orchestration; imports from ssh_transport; adds VRAM guards between model evaluations; adds timeout to subprocess calls
3. `vram_budget.py` (NEW) — VRAM monitoring via remote nvidia-smi; enforces sequential-not-concurrent model loading
4. `remote_ocr.py` (NEW) — GLM-OCR exploration orchestrator; bootstraps separate ocr-venv, rsyncs page images, runs inference, fetches results
5. `ocr_comparison.py` (NEW) — diff GLM-OCR output vs PyMuPDF extraction per-page; produces exploration-summary.md
6. `remote-backends.json` (MODIFY) — add 5 new models with per-model batch sizes
7. `remote-embedding-requirements.txt` (MODIFY) — update pins to match system reality; add einops for stella

The page-image pipeline for GLM-OCR is the correct design: render PDF pages to PNG on the Mac (PyMuPDF already installed, rendering is CPU-bound), rsync images to dionysus, run GPU inference, fetch markdown results. This keeps the remote environment focused on GPU inference and avoids adding PyMuPDF as a remote dependency.

### Critical Pitfalls

1. **Stale requirements pins bypassed by system-site-packages** — The bootstrap creates venvs with `--system-site-packages` and skips pip installs if imports succeed. Pins in `remote-embedding-requirements.txt` are never enforced. Fix by updating pins to match system reality and recording the actual resolved torch version in run manifests. Address in infrastructure phase before any live run.

2. **No SSH timeout on remote evaluation commands** — `run_command()` in `remote_backends.py` calls `subprocess.run()` with no `timeout` parameter (confirmed at lines 504-541). A hung GPU evaluation blocks the Mac orchestrator indefinitely. Add stage-specific timeouts (30s probe, 300s bootstrap, 1800s evaluation) and `ServerAliveInterval 60` SSH keepalive. This is a prerequisite for going live — not optional.

3. **GLM-OCR bfloat16 incompatibility with GTX 1080 Ti** — The official GLM-OCR examples use `dtype=torch.bfloat16`. Pascal architecture (compute 6.1) emulates bfloat16 in software, producing 10-100x slowdown or garbage outputs. Must explicitly load with `dtype=torch.float16`. This is the first thing to validate when GLM-OCR work begins.

4. **Flash Attention 2 unavailable — VRAM budget changes** — GLM-OCR with SDPA fallback (no FA2) uses more VRAM than benchmarks report. For the 0.9B model in fp16 without FA2: expect ~4-6 GB VRAM including inference buffers. Still fits on 11 GB, but leaves less headroom. Do not set `attn_implementation="flash_attention_2"` — let PyTorch choose SDPA automatically.

5. **Sequential VRAM cleanup is required between models** — The current one-model-per-SSH-invocation design provides process-level VRAM isolation and must be preserved. If anyone optimizes by loading multiple models in one process, `torch.cuda.empty_cache()` alone is insufficient — the full sequence `del model; gc.collect(); torch.cuda.empty_cache()` is required, and even that fails if CUDA tensors are still referenced. The VRAM guard module should check nvidia-smi between invocations.

6. **Hardcoded macOS paths in remote-executed scripts** — `embedding_space.py` and `remote_backends.py` hardcode `PROJECT_ROOT = Path("/Users/rookslog/Projects/PDFAgentialConversion")` (confirmed at lines 19 and 20 respectively). Remote execution currently works because all paths are passed explicitly as arguments. Add a guard that raises a clear error if the hardcoded path is dereferenced on a non-Mac host.

## Implications for Roadmap

All four research files converge on the same three-phase progression. The phases are prerequisite-ordered: each phase creates the foundation the next phase depends on. Skipping any step creates debugging complexity that outweighs the time saved.

### Phase 1: Infrastructure Alignment and Live Pipeline Validation

**Rationale:** Nothing else is reliable until the foundation is correct. The stale requirements, missing SSH timeouts, and hardcoded path risks are latent failures confirmed by codebase inspection — not theoretical concerns. Fixing them first means subsequent failures are about model behavior, not plumbing. The SSH primitive extraction also belongs here because both Phase 2 and Phase 3 depend on clean, importable transport code.

**Delivers:** A live end-to-end comparison run with a single model (bge-small-en-v1.5) producing a valid comparison-summary.json, with confirmed torch version alignment, SSH timeouts in place, VRAM guards operational, and a smoke-test that proves the full pipeline (probe → bootstrap → rsync → evaluate → fetch → compare) works without --dry-run.

**Addresses:** Requirements update, SSH timeout, keepalive, hardcoded path guard, trust_remote_code support (stella/nomic), ssh_transport.py extraction, vram_budget.py creation, Makefile live target.

**Avoids:** Pitfalls 1 (stale pins), 2 (no SSH timeout), 6 (hardcoded paths). Pitfall 5 (VRAM cleanup) is documented as a code comment guard-rail against future optimization.

### Phase 2: Expanded Embedding Model Roster

**Rationale:** Phase 1 validates the pipeline with the cheapest, smallest model. Phase 2 adds the remaining 7 models to produce a meaningful comparison matrix. This is lower risk than OCR exploration because it uses the same evaluator code and same data flow — just more models. Per-model batch size configuration is required here; bge-m3 at batch 32 will OOM. The VRAM guard module from Phase 1 is the safety mechanism that makes this expansion reliable.

**Delivers:** Full 8-model comparison run with domain-specific hit@1, MRR, and twin-cosine metrics across all corpus-view pairs (rag_linearized, semantic_flat_clean, spatial_main_plus_supplement) for body and contextual views. A winner selected by `choose_winner` for the scholarly retrieval use case, informing backend selection for downstream RAG deployment.

**Uses:** All embedding stack updates from Phase 1. New models: bge-large-en-v1.5, stella_en_400M_v5, nomic-embed-text-v1.5, snowflake-arctic-embed-m-v2.0, bge-m3.

**Avoids:** Pitfall 4 (concurrent VRAM) via strict sequential execution; Pitfall 5 (VRAM cleanup) via VRAM guard checks from Phase 1.

### Phase 3: GLM-OCR Isolated Exploration

**Rationale:** GLM-OCR introduces a new runtime environment (separate venv, transformers 5.3+), a new data flow (PDF pages as images), and a new comparison methodology (text extraction quality, not retrieval quality). Attempting this before Phase 2 completes creates multiple simultaneous unknowns. Phase 3 is explicitly exploratory — the goal is empirical evidence about GLM-OCR's quality on scholarly corpora that prove difficult for PyMuPDF (commentary-dense pages, marginal glosses, multi-column layouts), not production integration.

**Delivers:** GLM-OCR running successfully on 5-10 representative pages from the why-ethics corpus at fp16 precision, producing markdown output. A per-page comparison against PyMuPDF extraction. A qualitative assessment of GLM-OCR's suitability for scholarly monographs that informs whether v2 integration is warranted.

**Uses:** GLM-OCR venv (transformers >=5.3.0, NO system site packages), new remote_ocr.py and ocr_comparison.py modules, page-image pipeline (Mac renders PNGs at 300 DPI using fitz, dionysus runs GPU inference).

**Avoids:** Pitfall 3 (bfloat16 — must load with `dtype=torch.float16` explicitly); Pitfall 4 (Flash Attention — must not set `attn_implementation="flash_attention_2"`); Pitfall 5 (concurrent VRAM — GLM-OCR runs in fully separate invocations, never alongside loaded embedding models).

### Phase Ordering Rationale

- Infrastructure before live evaluation is non-negotiable. Both the codebase inspection and live hardware probe confirmed the specific gaps — missing timeout at an exact line number, stale pins that fail silently. These are not risks to mitigate; they are known broken states to fix.
- Single-model smoke test before full roster expansion. A failure with bge-small reveals infrastructure issues; a failure with bge-m3 could be a VRAM issue masked as infrastructure. The smoke test makes failures unambiguous.
- Embedding expansion before OCR exploration. Incremental risk: same code, same data flow, more models. OCR exploration adds two new modules, a new data flow, and a new Python environment. Validating transport first reduces debugging variables when GLM-OCR work begins.
- GLM-OCR as exploration, not integration. The research is explicit: do not attempt to replace the working PyMuPDF/PaddleOCR pipeline in the same milestone as live embedding evaluation. The risk is too high and the data to justify the switch does not exist yet.

### Research Flags

Phases likely needing deeper research during planning:
- **Phase 3 (GLM-OCR):** Float16/SDPA inference speed on GTX 1080 Ti is empirically unvalidated — only T4 data exists. Scholarly monograph page types (Talmudic commentary, marginal glosses, multi-column) are not in GLM-OCR's published benchmarks. Consider a brief spike or targeted research pass before building remote_ocr.py to bound the inference speed and identify likely layout failures early.
- **Phase 2 (stella prompt-name routing):** stella uses `prompt_name="s2p_query"` for retrieval queries vs no prompt for documents. Whether this distinction meaningfully affects scholarly retrieval quality (vs. using no prompts for both) is unknown and worth a targeted spike if Phase 2 results are ambiguous.

Phases with standard patterns (skip research):
- **Phase 1 (infrastructure):** All changes are well-understood standard patterns: requirements version pinning, subprocess timeout, SSH keepalive, module extraction. No novel integration needed.
- **Phase 2 (embedding roster):** Adding models to a working evaluator is documented and low-risk. The only unknowns are empirical (which model scores best on scholarly text), not technical.

## Confidence Assessment

| Area | Confidence | Notes |
|------|------------|-------|
| Stack | HIGH | Core embedding stack (torch 2.9.1+cu126, sentence-transformers 5.2.0, transformers 4.51.3) verified on hardware. VRAM estimates for all embedding models sourced from HuggingFace model cards and discussions. GLM-OCR transformers 5.3+ requirement verified from pyproject.toml. |
| Features | HIGH (embedding) / MEDIUM (GLM-OCR) | Embedding evaluation feature set is fully defined and grounded in existing working code. GLM-OCR quality on scholarly layouts (commentary-dense pages, marginal glosses) is MEDIUM — GLM-OCR is benchmarked on financial/standard academic docs, not monographs with complex layouts. |
| Architecture | HIGH | Phase A/B/C build order is well-grounded. SSH primitive extraction, dual-venv design, and page-image pipeline all have clear precedents. The main uncertainty is GLM-OCR's actual VRAM behavior on 1080 Ti without Flash Attention — theoretically sound, empirically unvalidated. |
| Pitfalls | HIGH | All critical pitfalls sourced from direct codebase inspection (specific file and line numbers cited) and live hardware probing, not theoretical analysis. |

**Overall confidence:** HIGH for Phase 1 and Phase 2. MEDIUM for Phase 3, contingent on float16 inference working at acceptable speed on the GTX 1080 Ti without Flash Attention.

### Gaps to Address

- **GLM-OCR float16 inference speed on GTX 1080 Ti:** No empirical data on pages/second without Flash Attention on Pascal architecture. T4 discussion reported ~40s/image; 1080 Ti has comparable FP16 throughput. If inference exceeds 2 min/page, the Phase 3 smoke test scope must be reduced. Handle during Phase 3 planning by setting an explicit time budget and stopping criteria.
- **stella prompt-name routing impact:** Whether `prompt_name="s2p_query"` vs. no prompt materially affects scholarly retrieval quality is unknown. The current `model.encode()` call in the evaluator does not support prompt-name routing. Determine during Phase 2 whether to add this as a per-model config field or treat it as a Phase 2 extension.
- **bge-m3 ColBERT/sparse modes:** Initial evaluation uses dense-only mode (no code changes needed). If dense results favor bge-m3, ColBERT/sparse evaluation requires FlagEmbedding library and a different encode path. Flag as a Phase 2 extension, not a Phase 2 requirement.
- **olmOCR-2-7B-FP8 as Phase 3 fallback:** If GLM-OCR extraction quality is insufficient for scholarly layouts, olmOCR-2 (Allen AI, trained on academic papers) is the next candidate. However, FP8 at ~8-10 GB VRAM leaves ~0.3 GB headroom — too tight to be safe without dedicated investigation. Defer evaluation until GLM-OCR Phase 3 results are known.
- **CUDA documentation accuracy on dionysus:** CLAUDE.md documents CUDA 11.8, but the system has CUDA 12.6 driver with PyTorch compiled for cu126. This documentation drift caused confusion across all research files. Update CLAUDE.md after Phase 1 completes.

## Sources

### Primary (HIGH confidence — verified on hardware or official source)
- Live hardware probe on dionysus: torch 2.9.1+cu126, CUDA driver 550.163.01 (12.6), GTX 1080 Ti compute 6.1, 11264 MiB VRAM, sentence-transformers 5.2.0, transformers 4.51.3
- Codebase inspection of `remote_backends.py` lines 19, 504-541: confirmed no timeout on subprocess.run, hardcoded PROJECT_ROOT path
- Codebase inspection of `embedding_space.py` line 20: confirmed hardcoded PROJECT_ROOT path
- [GLM-OCR pyproject.toml](https://github.com/zai-org/GLM-OCR/blob/main/pyproject.toml) — transformers >=5.3.0 requirement
- [Flash Attention 2 compute capability requirement](https://huggingface.co/docs/transformers/perf_infer_gpu_one#flashattention-2) — requires compute >= 8.0
- [bfloat16 native support requires compute >= 8.0](https://discuss.pytorch.org/t/bfloat16-native-support/117155) — Pascal GPUs emulate in software
- [MTEB Leaderboard](https://huggingface.co/spaces/mteb/leaderboard) — model rankings, parameter counts, benchmark methodology
- [BAAI/bge-m3](https://huggingface.co/BAAI/bge-m3), [bge-large-en-v1.5](https://huggingface.co/BAAI/bge-large-en-v1.5), [stella_en_400M_v5](https://huggingface.co/NovaSearch/stella_en_400M_v5), [nomic-embed-text-v1.5](https://huggingface.co/nomic-ai/nomic-embed-text-v1.5) — model cards, VRAM estimates, trust_remote_code requirements
- [NVIDIA CUDA GPU compute capabilities](https://developer.nvidia.com/cuda/gpus) — GTX 1080 Ti confirmed compute 6.1

### Secondary (MEDIUM confidence — community sources, single data points)
- [GLM-OCR HuggingFace discussion #13](https://huggingface.co/zai-org/GLM-OCR/discussions/13) — ~4.4 GB VRAM on T4; single user report, not reproduced on 1080 Ti
- [olmOCR-2-7B-FP8 model card](https://huggingface.co/allenai/olmOCR-2-7B-1025-FP8) — trained on academic papers; VRAM on 1080 Ti untested
- [VRAM batch size analysis for embedding models](https://medium.com/@vici0549/it-is-crucial-to-properly-set-the-batch-size-when-using-sentence-transformers-for-embedding-models-3d41a3f8b649)
- [vLLM GLM-OCR guide](https://docs.vllm.ai/projects/recipes/en/latest/GLM/GLM-OCR.html) — deployment configuration options

### Tertiary (LOW confidence — inferred, needs empirical validation)
- GLM-OCR inference speed on GTX 1080 Ti without Flash Attention: extrapolated from T4 discussion and FP16 throughput comparisons; unvalidated
- GLM-OCR quality on scholarly monographs with marginal glosses and commentary-dense layouts: not in published benchmarks; unknown until tested on actual corpus

---
*Research completed: 2026-03-20*
*Ready for roadmap: yes*
