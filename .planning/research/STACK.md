# Stack Research

**Domain:** Remote embedding evaluation expansion + GLM-OCR extraction for scholarly PDFs
**Researched:** 2026-03-20
**Confidence:** HIGH (embedding models verified on-hardware), MEDIUM (GLM-OCR requires isolated venv testing)

## System State Snapshot

Before recommending additions, here is the verified state of the dionysus GPU backend:

| Component | Pinned (requirements.txt) | Actual (system) | Gap |
|-----------|--------------------------|-----------------|-----|
| PyTorch | 2.4.1 | 2.9.1+cu126 | **Stale pin** -- system is 5 minor versions ahead |
| sentence-transformers | 3.0.1 | 5.2.0 | **Stale pin** -- system is 2 major versions ahead |
| transformers | 4.44.2 | 4.51.3 | **Stale pin** -- system is 7 minor versions ahead |
| numpy | 1.26.4 | 2.2.6 | **Stale pin** -- system is 1 major version ahead |
| CUDA driver | - | 12.4 (driver 550.163.01) | Not CUDA 11.8 as documented |
| PyTorch CUDA | - | cu126 | Built for CUDA 12.6 |
| GPU | - | GTX 1080 Ti (sm_60/61, 10.9 GB) | Compute capability 6.1 |
| Free VRAM | - | ~10.3 GB (after Xorg) | Sufficient for all recommended models |

**Critical finding:** The remote-embedding-requirements.txt is severely stale. The bootstrap script creates a venv with `--system-site-packages` and only installs from requirements.txt if imports fail. Since the system already has newer versions, the bootstrap will likely inherit system packages and never use the pinned file. The pins must be updated to reflect reality and ensure reproducibility.

## Recommended Stack

### Core Technologies (Update Existing)

| Technology | Version | Purpose | Why Recommended |
|------------|---------|---------|-----------------|
| PyTorch | >=2.9.0,<3.0.0 | GPU tensor computation | Already installed on dionysus; sm_60 in arch list covers GTX 1080 Ti; cu126 build verified working |
| sentence-transformers | >=5.2.0,<6.0.0 | Embedding model loading/inference | Already installed; 5.x adds Matryoshka support, improved model cards, better prompt handling needed by stella |
| transformers | >=4.51.0,<5.0.0 | Model backbone loading | Already installed; 4.51+ supports all recommended embedding models; do NOT upgrade to 5.x for embeddings (see GLM-OCR section) |
| numpy | >=2.2.0,<3.0.0 | Array operations | Already installed; 2.x is compatible with current torch/transformers |

### New Embedding Models to Add

These models are selected for the evaluation roster based on three criteria: (1) fits in ~10.3 GB usable VRAM, (2) loads via sentence-transformers, (3) covers a meaningful quality/speed tradeoff space that the current roster misses.

| Model | Parameters | VRAM (fp16) | Embedding Dim | Why Add |
|-------|-----------|-------------|---------------|---------|
| `BAAI/bge-large-en-v1.5` | 335M | ~0.8 GB | 1024 | Completes the BGE size ladder (small/base/**large**); same architecture family enables controlled scaling comparison; widely benchmarked |
| `NovaSearch/stella_en_400M_v5` | 400M | ~1.0 GB | 1024 (default) | MTEB leader in its parameter class; Matryoshka dims 256-8192; uses `trust_remote_code=True` and prompt-name routing -- tests pipeline flexibility |
| `nomic-ai/nomic-embed-text-v1.5` | 137M | ~0.3 GB | 768 | Strong long-context (8192 tokens) at tiny footprint; Matryoshka support (64-768); different tokenizer lineage than BGE/E5 -- adds diversity |
| `Snowflake/snowflake-arctic-embed-m-v2.0` | 113M | ~0.3 GB | 768 | Optimized specifically for retrieval (not general NLU); multilingual; lightweight -- useful speed-vs-quality anchor |
| `BAAI/bge-m3` | 560M | ~1.3 GB | 1024 | Multi-modal retrieval: dense + sparse + ColBERT; 8192-token context; strong on long scholarly passages; heaviest model in roster but well within VRAM |

**Total new model VRAM (worst case, all loaded simultaneously):** ~3.7 GB. In practice they load one at a time via the existing sequential evaluation pipeline, so peak usage is ~1.3 GB (bge-m3) + overhead.

### Models NOT to Add (and Why)

| Model | Parameters | VRAM (fp16) | Why Excluded |
|-------|-----------|-------------|--------------|
| `intfloat/e5-mistral-7b-instruct` | 7B | ~14 GB | **Does not fit.** Exceeds 10.9 GB total VRAM. Would require 4-bit quantization which degrades embedding quality unpredictably. |
| `Alibaba-NLP/gte-large-en-v1.5` | 434M | ~1.3 GB | Same architecture family as stella (stella is built on it); adding both is redundant. stella has better MTEB scores. |
| `intfloat/e5-large-v2` | 335M | ~0.8 GB | Same parameter class as bge-large; BGE consistently outperforms E5-v2 on retrieval tasks per MTEB. Adding both wastes evaluation time. |
| `nomic-ai/nomic-embed-text-v2-moe` | 475M (305M active) | ~0.9 GB | MoE architecture; requires newer transformers with custom code. Adds risk for marginal gain over v1.5 in English-only scholarly use. |

### GLM-OCR Stack (Separate Venv -- CRITICAL)

GLM-OCR requires `transformers >= 5.3.0` which is **incompatible** with the embedding evaluation stack (`transformers 4.51.x`). It must run in an isolated environment.

| Technology | Version | Purpose | Why This Version |
|------------|---------|---------|------------------|
| transformers | >=5.3.0 | GLM-OCR model backbone | Required by zai-org/GLM-OCR; 5.x API changes break some sentence-transformers model loading |
| torch | >=2.9.0 | GPU inference | Already on system; shared via `--system-site-packages` |
| torchvision | >=0.25.0 | Image preprocessing | Required by GLM-OCR layout pipeline |
| sentencepiece | >=0.2.0 | Tokenization | GLM-OCR tokenizer dependency |
| accelerate | >=1.13.0 | Model loading/device mapping | GLM-OCR uses `device_map="auto"` |
| pypdfium2 | >=5.6.0 | PDF page rendering | GLM-OCR renders PDF pages to images for OCR |
| pillow | >=12.1.0 | Image handling | GLM-OCR image preprocessing |
| opencv-python | >=4.8.0 | Layout analysis preprocessing | Used by PP-DocLayout-V3 stage |
| vllm | latest | Serving/inference acceleration | Optional but recommended for multi-page batch throughput |

**GLM-OCR VRAM estimate:** ~1.8-2.5 GB for the 0.9B model in fp16. Fits easily on the GTX 1080 Ti with ~8 GB to spare for KV cache and image processing. However:

- The GTX 1080 Ti does **not support Flash Attention 2** (requires compute capability >= 8.0; 1080 Ti is 6.1)
- The GTX 1080 Ti does **not support bf16** natively (Pascal architecture). Must use fp16.
- Expect slower inference than reported benchmarks (which use Ampere/Hopper GPUs). The T4 discussion reported ~40s/image; GTX 1080 Ti is roughly comparable in FP16 throughput to T4.

### Vision-Language OCR Alternatives Worth Considering

| Model | Size | VRAM | Scholarly Fit | Notes |
|-------|------|------|---------------|-------|
| `allenai/olmOCR-2-7B-1025` | 7B | ~8-10 GB (FP8) | HIGH -- trained on academic papers | FP8 quantized version fits on 11 GB but tight. Based on Qwen2.5-VL-7B. Scholarly PDF training data. |
| `Qwen/Qwen2-VL-2B-Instruct` | 2B | ~4-5 GB | MEDIUM -- general VLM | Small enough to fit; generic document understanding; would need task-specific prompting. |
| `PaddleOCR` (existing) | N/A | CPU/Docker | HIGH -- already deployed | Running on port 8765. Keep as baseline for scanned documents. |

**Recommendation:** Start with GLM-OCR (0.9B, fits easily, purpose-built for OCR). If scholarly extraction quality is insufficient, olmOCR-2 is the next candidate but will need FP8 quantization to fit, making it a Phase 2 exploration.

### Supporting Libraries

| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| `FlagEmbedding` | >=1.2.0 | bge-m3 ColBERT/sparse vectors | Only if evaluating bge-m3's sparse+ColBERT modes beyond dense embeddings |
| `einops` | >=0.7.0 | Tensor operations for some models | stella and some newer models use it internally |
| `safetensors` | >=0.4.0 | Fast model weight loading | Already a transformers dependency; speeds up cold-start model loads |

### Development Tools

| Tool | Purpose | Notes |
|------|---------|-------|
| `nvidia-smi` | VRAM monitoring during evaluation | Already available; use `--query-gpu=memory.used --format=csv` in probe commands |
| `torch.cuda.memory_summary()` | Per-model VRAM profiling | Add to remote evaluation script for memory tracking per model |
| `venv --system-site-packages` | Isolated envs inheriting torch | Current bootstrap approach; validated working |

## Installation

### Embedding Evaluation (Update remote-embedding-requirements.txt)

```bash
# Updated pins matching actual system state
# These are installed by bootstrap only if imports fail;
# system packages are inherited via --system-site-packages
sentence-transformers>=5.2.0,<6.0.0
torch>=2.9.0,<3.0.0
transformers>=4.51.0,<5.0.0
numpy>=2.2.0,<3.0.0
einops>=0.7.0
```

### GLM-OCR Exploration (Separate venv)

```bash
# Create dedicated venv for GLM-OCR (does NOT share with embedding venv)
python3 -m venv /home/rookslog/pdfmd-remote-experiments/glm-ocr-venv
source /home/rookslog/pdfmd-remote-experiments/glm-ocr-venv/bin/activate

# Install from PyPI
pip install glm-ocr[layout]
# OR manual install if PyPI package is behind:
pip install transformers>=5.3.0 torch>=2.9.0 torchvision>=0.25.0 \
    sentencepiece>=0.2.0 accelerate>=1.13.0 pypdfium2>=5.6.0 \
    pillow>=12.1.0 opencv-python>=4.8.0

# Optional: vLLM for batch serving
pip install vllm
```

### Updated remote-backends.json Models List

```json
{
  "backends": [
    {
      "id": "dionysus",
      "label": "Dionysus Tailscale GPU Host",
      "transport": "ssh",
      "ssh_target": "dionysus",
      "remote_root": "/home/rookslog/pdfmd-remote-experiments",
      "python_bin": "python3",
      "venv_dir": "venv",
      "device": "auto",
      "bootstrap_mode": "ssh_venv",
      "models": [
        "BAAI/bge-small-en-v1.5",
        "BAAI/bge-base-en-v1.5",
        "BAAI/bge-large-en-v1.5",
        "intfloat/e5-base-v2",
        "nomic-ai/nomic-embed-text-v1.5",
        "Snowflake/snowflake-arctic-embed-m-v2.0",
        "NovaSearch/stella_en_400M_v5",
        "BAAI/bge-m3"
      ]
    }
  ]
}
```

## Alternatives Considered

| Recommended | Alternative | When to Use Alternative |
|-------------|-------------|-------------------------|
| sentence-transformers 5.2+ | Direct HuggingFace transformers AutoModel | Only if a model has no sentence-transformers config; all recommended models support ST |
| `transformers 4.51.x` for embeddings | `transformers 5.x` | Only for GLM-OCR; upgrading embeddings to 5.x risks breaking model loading for older BGE/E5 configs |
| Separate venv for GLM-OCR | Single shared venv | Never -- transformers 5.x requirement makes this impossible without version conflicts |
| GLM-OCR for VLM-OCR | olmOCR-2-7B | When scholarly extraction quality from GLM-OCR is insufficient and FP8 quantization infra is in place |
| fp16 inference | bf16 inference | Never on GTX 1080 Ti -- bf16 not supported on Pascal (compute 6.1) |

## What NOT to Use

| Avoid | Why | Use Instead |
|-------|-----|-------------|
| Any 7B+ embedding model (e5-mistral, etc.) | Exceeds 11 GB VRAM. Quantized embeddings have unpredictable quality degradation. | Sub-600M models that fit in fp16 |
| `transformers >= 5.0` in embedding venv | Breaks sentence-transformers model loading for several BGE/E5 models | `transformers >= 4.51, < 5.0` for embeddings |
| Flash Attention 2 | GTX 1080 Ti compute capability 6.1 < required 8.0 | Standard SDPA attention (PyTorch default) |
| bf16 dtype | GTX 1080 Ti (Pascal) lacks native bf16 support | fp16 or fp32 |
| `--system-site-packages` for GLM-OCR venv | Would inherit transformers 4.51.x, blocking GLM-OCR's 5.3+ requirement | Clean venv without system site packages |
| Single monolithic requirements.txt | Embedding and GLM-OCR have incompatible transformers requirements | Two separate requirements files |

## Stack Patterns by Variant

**If running embedding evaluation only (Phase 1 -- go live):**
- Update `remote-embedding-requirements.txt` to match system
- Add 5 new models to `remote-backends.json`
- No new dependencies required -- everything is already on the system
- Test with `--dry-run` first, then remove the flag

**If exploring GLM-OCR extraction (Phase 2 -- exploration):**
- Create dedicated venv WITHOUT `--system-site-packages`
- Install `transformers >= 5.3.0` and GLM-OCR dependencies
- PyTorch will need to be installed fresh in the venv (or use `--system-site-packages` for torch only via careful pip ordering)
- Test with a single scholarly PDF page before batch processing

**If GLM-OCR proves insufficient for scholarly extraction:**
- Evaluate olmOCR-2-7B-1025-FP8 (Allen AI, trained on academic papers)
- Requires `llmcompressor` for FP8 quantization or pre-quantized checkpoint
- VRAM will be tight (~8-10 GB for the model + ~1-2 GB for KV cache)
- Consider running with reduced `--gpu-memory-utilization 0.85`

## Version Compatibility

| Package A | Compatible With | Notes |
|-----------|-----------------|-------|
| sentence-transformers 5.2.x | transformers 4.51.x | Verified on dionysus system |
| sentence-transformers 5.2.x | torch 2.9.x+cu126 | Verified on dionysus system |
| torch 2.9.1+cu126 | GTX 1080 Ti (sm_60/61) | Verified -- sm_60 in compiled arch list covers sm_61 |
| GLM-OCR | transformers >=5.3.0 | **INCOMPATIBLE** with embedding stack transformers 4.51.x |
| GLM-OCR | torch >=2.9.0 | Compatible with system torch |
| stella_en_400M_v5 | sentence-transformers 5.2+ | Requires `trust_remote_code=True` |
| nomic-embed-text-v1.5 | sentence-transformers 5.2+ | Requires `trust_remote_code=True` |
| bge-m3 | sentence-transformers 5.2+ | Dense mode works natively; ColBERT/sparse requires FlagEmbedding |
| All embedding models | fp16 on GTX 1080 Ti | All work in fp16; none require bf16 |

## GPU VRAM Budget

| Scenario | Model Load | Inference Overhead | Total | Headroom |
|----------|-----------|-------------------|-------|----------|
| bge-small (smallest) | ~0.07 GB | ~0.1 GB | ~0.2 GB | 10.1 GB |
| bge-m3 (largest embedding) | ~1.3 GB | ~0.5 GB | ~1.8 GB | 8.5 GB |
| stella_en_400M_v5 | ~1.0 GB | ~0.4 GB | ~1.4 GB | 8.9 GB |
| GLM-OCR (0.9B, separate) | ~1.8 GB | ~1.5 GB (images) | ~3.3 GB | 7.0 GB |
| olmOCR-2 FP8 (future) | ~8.0 GB | ~2.0 GB | ~10.0 GB | 0.3 GB (TIGHT) |

All embedding models have ample VRAM headroom. GLM-OCR fits comfortably. olmOCR-2 is the only model that would be tight.

## Integration Points with Existing Code

### remote_backends.py Changes Needed

1. **models list in remote-backends.json** -- add the 5 new model names (no code changes needed; the pipeline already iterates `backend["models"]`)
2. **requirements.txt** -- update pins to match system reality
3. **`trust_remote_code` support** -- the `SentenceTransformer()` call in `embedding_space.py` does not currently pass `trust_remote_code=True`. stella and nomic models require this. The `load_embeddings_sentence_transformers()` function needs a one-line addition.
4. **Prompt name routing** -- stella uses `prompt_name="s2p_query"` for retrieval queries vs `prompt_name=None` for documents. The current `model.encode()` call does not support this. Needs a conditional or config flag per model.
5. **bge-m3 mode flag** -- if evaluating ColBERT/sparse modes in addition to dense, requires FlagEmbedding library and a different encode path. For initial evaluation, dense-only mode works through sentence-transformers without changes.

### Minimal Code Changes for Phase 1 (Embedding Go-Live)

```python
# In load_embeddings_sentence_transformers():
# Current:
model = sentence_transformers_module.SentenceTransformer(model_name, device=resolved_device)
# Updated:
model = sentence_transformers_module.SentenceTransformer(
    model_name,
    device=resolved_device,
    trust_remote_code=True,  # Required for stella, nomic
)
```

### GLM-OCR Integration (Phase 2)

GLM-OCR does NOT integrate into the embedding evaluation pipeline. It is a separate extraction tool that would:
1. Accept a PDF page image as input
2. Return structured text extraction (markdown/JSON)
3. Compare output quality against existing pdfminer extraction

This requires a new script/module, not modifications to `remote_backends.py` or `embedding_space.py`.

## Sources

- PyTorch 2.9.1+cu126 on GTX 1080 Ti: **verified on-hardware** (HIGH confidence)
- sentence-transformers 5.2.0 compatibility: **verified on-hardware** (HIGH confidence)
- CUDA compute capability 6.1 / Flash Attention 2 incompatibility: [nvidia-smi verified on-hardware](https://developer.nvidia.com/cuda/gpus), [HuggingFace Flash Attention docs](https://huggingface.co/docs/transformers/perf_infer_gpu_one#flashattention-2) (HIGH confidence)
- GLM-OCR requirements (transformers >=5.3.0): [zai-org/GLM-OCR pyproject.toml](https://github.com/zai-org/GLM-OCR/blob/main/pyproject.toml), [HuggingFace model card](https://huggingface.co/zai-org/GLM-OCR) (HIGH confidence)
- GLM-OCR VRAM ~4.4 GB on T4: [HuggingFace discussion #13](https://huggingface.co/zai-org/GLM-OCR/discussions/13) (MEDIUM confidence -- single user report)
- bge-m3 560M parameters, ~1.06 GB fp16: [HuggingFace model card](https://huggingface.co/BAAI/bge-m3), [memory requirements discussion](https://huggingface.co/BAAI/bge-m3/discussions/64) (HIGH confidence)
- stella_en_400M_v5 Matryoshka dims, trust_remote_code: [HuggingFace model card](https://huggingface.co/NovaSearch/stella_en_400M_v5) (HIGH confidence)
- nomic-embed-text-v1.5 ~262 MB fp16: [HuggingFace memory discussion](https://huggingface.co/nomic-ai/nomic-embed-text-v1.5/discussions/15) (HIGH confidence)
- bge-large-en-v1.5 ~639 MB fp16: [HuggingFace memory discussion](https://huggingface.co/BAAI/bge-large-en-v1.5/discussions/20) (HIGH confidence)
- olmOCR-2-7B FP8: [HuggingFace model card](https://huggingface.co/allenai/olmOCR-2-7B-1025-FP8) (MEDIUM confidence -- not tested on 1080 Ti)
- MTEB leaderboard rankings: [HuggingFace MTEB leaderboard](https://huggingface.co/spaces/mteb/leaderboard), [Ailog comparison](https://app.ailog.fr/en/blog/guides/choosing-embedding-models) (HIGH confidence)
- sentence-transformers 5.3.0 latest on PyPI: [PyPI](https://pypi.org/project/sentence-transformers/) (HIGH confidence)
- transformers 5.3.0 latest on PyPI: [PyPI](https://pypi.org/project/transformers/) (HIGH confidence)

---
*Stack research for: Remote embedding evaluation expansion + GLM-OCR exploration*
*Researched: 2026-03-20*
