# Pitfalls Research

**Domain:** GPU-based embedding evaluation and vision-language OCR over SSH-orchestrated scholarly PDF pipeline
**Researched:** 2026-03-19
**Confidence:** HIGH (verified against live hardware, codebase inspection, and current documentation)

## Critical Pitfalls

### Pitfall 1: Pinned torch==2.4.1 vs. System PyTorch Version Conflict

**What goes wrong:**
The remote experiment requirements pin `torch==2.4.1`, but the system Python on dionysus already has `torch==2.9.1+cu126`. The bootstrap script in `remote_backends.py` creates a venv with `--system-site-packages`, which means the venv inherits the system's torch 2.9.1. The bootstrap logic checks `if "$VENV_PY" -c "import torch"` and sets `TORCH_PREINSTALLED=1`, then skips torch installation. The pinned `sentence-transformers==3.0.1` and `transformers==4.44.2` are then installed against the inherited 2.9.1, not the pinned 2.4.1. This works by accident today -- but the version mismatch is invisible, the run-manifest records no torch version, and any future sentence-transformers version that requires specific torch APIs will silently break.

**Why it happens:**
The `--system-site-packages` flag was a pragmatic choice to avoid downloading the ~2GB torch wheel on every bootstrap. But it makes the venv's torch version non-deterministic -- it depends on whatever version the system has installed, not what the requirements pin.

**How to avoid:**
- Either pin the requirements to match the system torch version (currently 2.9.1+cu126) and update `transformers` / `sentence-transformers` to compatible versions.
- Or create venvs without `--system-site-packages` and install the specific torch wheel from the cu126 index (since the system driver supports CUDA 12.6).
- Record the actual resolved torch version in the run-manifest and bootstrap output so version drift is visible.

**Warning signs:**
- Bootstrap output shows `torch_preinstalled: true` but `requirements.txt` pins a different version.
- `import torch; print(torch.__version__)` in the venv shows a version different from what `requirements.txt` specifies.
- Model evaluation produces subtly different numerical results between runs without code changes.

**Phase to address:**
Foundation/infrastructure phase -- before running any live evaluations. Version alignment must be resolved first because all subsequent measurements depend on it.

---

### Pitfall 2: No SSH Timeout on Remote Model Evaluation Commands

**What goes wrong:**
The `run_command()` function in `remote_backends.py` calls `subprocess.run()` with no `timeout` parameter. A remote model evaluation that hangs (CUDA driver crash, GPU lockup, OOM freeze, SSH connection stall) will block the orchestrator indefinitely. The Mac side has no way to recover -- it just waits forever. This is distinct from the local runtime module (`common/runtime.py`) which does implement timeouts.

**Why it happens:**
During the dry-run phase, timeouts were not needed because no real execution occurred. The `run_command` function was written for correctness-of-structure, not resilience-of-execution. Transitioning from dry-run to live means inheriting this gap.

**How to avoid:**
- Add a `timeout` parameter to `run_command()` in `remote_backends.py`, following the pattern already established in `common/runtime.py`.
- Set stage-specific timeouts: quick for probe/mkdir (30s), moderate for bootstrap (300s), generous for evaluation (1800s for embedding, longer for VLM inference).
- Handle `subprocess.TimeoutExpired` by recording the timeout in the runtime artifact (not silently swallowing it).
- Consider SSH-level keepalive (`ServerAliveInterval`) to distinguish "still running" from "connection dead."

**Warning signs:**
- The orchestrator hangs after starting a remote evaluation with no progress output.
- `ps aux | grep ssh` on the Mac shows a zombie SSH process.
- The remote GPU shows 100% utilization but the process has stopped producing output (OOM hang).

**Phase to address:**
Must be resolved in the same phase that enables live evaluation. This is a prerequisite for going from `--dry-run` to live runs.

---

### Pitfall 3: Sequential Model Evaluation Without GPU Memory Cleanup

**What goes wrong:**
The current evaluator (`embedding_space.py`) loads a sentence-transformers model, encodes all texts, and returns results. When `remote_backends.py` iterates over multiple models for the same backend (bge-small, bge-base, e5-base), each model evaluation happens in a separate SSH invocation -- which does provide process-level isolation. However, if the design evolves to run multiple models in a single process (for speed), VRAM from the first model is not freed before loading the second. `torch.cuda.empty_cache()` only releases the cache -- it does not free memory still referenced by Python objects. On an 11GB GPU where bge-base uses ~640MB and model state can fragment another ~500MB, running three models sequentially without proper cleanup could exhaust available VRAM.

**Why it happens:**
The per-SSH-invocation design currently avoids this. But when optimizing for speed, the natural instinct is to keep models in the same process. The Python garbage collector does not immediately free GPU tensors, and `del model` followed by `gc.collect()` followed by `torch.cuda.empty_cache()` is the only reliable cleanup sequence -- but even this can fail if embeddings tensors are still referenced (e.g., stored in a results dict as numpy arrays converted from CUDA tensors).

**How to avoid:**
- Keep the current one-model-per-SSH-invocation design. It is slower but guarantees VRAM isolation. On an 11GB GPU with small/base models, the SSH overhead (~5-10s per invocation) is negligible compared to model load time (~15-30s).
- If switching to multi-model-per-process, enforce a strict `del model; gc.collect(); torch.cuda.empty_cache()` sequence and verify with `torch.cuda.memory_allocated()` that VRAM returns to near-zero before loading the next model.
- Never hold CUDA tensors in the results dict -- always convert to CPU/numpy before storing.

**Warning signs:**
- `nvidia-smi` shows VRAM usage climbing across models without returning to baseline.
- `CUDA out of memory` errors on the second or third model even though each model individually fits.
- Inconsistent results on repeat runs (fragmented VRAM causes different batch splitting).

**Phase to address:**
Embedding evaluation phase. The current architecture avoids this, so it is a guard-rail against future optimization. Document the rationale for one-model-per-process in the code.

---

### Pitfall 4: GLM-OCR bfloat16 Incompatibility with GTX 1080 Ti

**What goes wrong:**
The official GLM-OCR usage examples load the model with `dtype=torch.bfloat16`. The GTX 1080 Ti (Pascal architecture, compute capability 6.1) does not support native bfloat16 operations. PyTorch will either emulate bfloat16 in software (extremely slow, 10-100x penalty) or raise an error depending on the operation. The model will appear to load but inference will be glacially slow or produce garbage outputs.

**Why it happens:**
GLM-OCR documentation targets modern GPUs (Ampere/Ada with compute capability >= 8.0) where bfloat16 is native. The Pascal architecture predates bfloat16 hardware support. The model's default dtype is bfloat16 because that is the standard precision for modern VLMs.

**How to avoid:**
- Load GLM-OCR with `dtype=torch.float16` instead of `torch.bfloat16`. float16 is natively supported on the GTX 1080 Ti (compute capability 6.1).
- Alternatively, load with `dtype=torch.float32` for maximum accuracy at the cost of ~2x VRAM usage (the 0.9B model in fp32 is ~3.6GB, which still fits in 11GB but leaves less room for inference buffers and embedding models).
- Test the model output quality at float16 vs float32 to ensure no accuracy degradation for scholarly PDF OCR specifically (math formulas and footnote text are sensitive to precision).

**Warning signs:**
- Model loads but inference takes minutes per page instead of seconds.
- PyTorch warnings about "slow fallback implementation" for bfloat16 operations.
- Numerical outputs (confidence scores, logits) are NaN or contain extreme values.

**Phase to address:**
GLM-OCR exploration phase -- must be the first thing validated when integrating the model. Gate: confirm float16 inference works at expected speed before building pipeline integration.

---

### Pitfall 5: Flash Attention Unavailable on GTX 1080 Ti

**What goes wrong:**
GLM-OCR and modern transformers models benefit significantly from Flash Attention 2 (FA2), which requires compute capability >= 8.0. The GTX 1080 Ti (6.1) cannot use FA2 at all, and also cannot use Flash Attention v1 (requires >= 7.5). PyTorch's `scaled_dot_product_attention` (SDPA) will fall back to the "math" implementation, which is functional but uses more VRAM and is slower. For the 0.9B GLM-OCR model processing full pages, this VRAM overhead can be the difference between fitting and OOM.

**Why it happens:**
Flash Attention is compiled with CUDA kernel specializations for specific GPU architectures. Pascal GPUs lack the tensor core hardware that FA2 requires. The HuggingFace transformers library will silently fall back to a compatible attention implementation, but the VRAM profile changes dramatically.

**How to avoid:**
- Do not set `attn_implementation="flash_attention_2"` in model loading. Let PyTorch choose the SDPA fallback automatically or explicitly set `attn_implementation="eager"`.
- Budget VRAM with the non-FA attention path: expect ~1.5-2x the VRAM per attention layer compared to FA2-equipped runs.
- For GLM-OCR (0.9B), at float16 without FA2: expect ~4-6GB VRAM for model + inference buffers. This leaves ~5-7GB for embedding models or batch processing, but not both simultaneously.
- Reduce `max_new_tokens` to limit generation buffer size on constrained VRAM.

**Warning signs:**
- `CUDA out of memory` during the first `model.generate()` call despite the model appearing to load fine.
- Warnings about flash_attention_2 not being available.
- VRAM usage jumping higher than expected during inference (vs. model load baseline).

**Phase to address:**
GLM-OCR exploration phase. This determines whether embedding evaluation and GLM-OCR can coexist on the same GPU, or whether they must run in separate, serialized phases.

---

### Pitfall 6: Running Embedding Models and GLM-OCR Simultaneously on 11GB VRAM

**What goes wrong:**
A naive integration would try to keep both a sentence-transformers embedding model and GLM-OCR loaded on GPU simultaneously. bge-base-en-v1.5 at fp32 uses ~640MB; GLM-OCR at fp16 uses ~4-6GB with inference buffers. Together they approach or exceed the 11GB limit, especially when the SDPA fallback (no Flash Attention) inflates GLM-OCR's attention memory. The result is either an OOM crash or, worse, the OS swapping GPU memory to system RAM (if using MPS or similar unified memory -- not applicable here, but a common mental model error).

**Why it happens:**
On a 24GB+ GPU, both models coexist easily. Developers test on larger GPUs and assume the same workflow works on smaller ones. The 11GB GTX 1080 Ti is generous for individual models but constrained for multi-model concurrent use.

**How to avoid:**
- Never load both GLM-OCR and embedding models on GPU simultaneously. Design the pipeline as sequential stages with explicit GPU cleanup between them.
- Phase 1: Run all embedding evaluations (bge-small, bge-base, e5-base). Phase 2: Unload everything, verify VRAM is clean. Phase 3: Load GLM-OCR for extraction.
- This sequential design aligns with the existing one-model-per-SSH-invocation architecture.
- Consider using `CUDA_VISIBLE_DEVICES` environment variable to partition GPU access if concurrent use is ever needed (though this does not help with total VRAM).

**Warning signs:**
- OOM during the second model load in a single process.
- nvidia-smi shows >9GB allocated before inference starts.
- System becomes unresponsive (GPU driver crash can hang the entire machine).

**Phase to address:**
Architecture decision in the milestone planning phase. The sequential-not-concurrent pattern should be an explicit design constraint documented before building either feature.

---

### Pitfall 7: Hardcoded macOS Paths Block Remote Execution

**What goes wrong:**
Both `remote_backends.py` and `embedding_space.py` hardcode `PROJECT_ROOT = Path("/Users/rookslog/Projects/PDFAgentialConversion")`. When the evaluator script is rsynced to dionysus and executed there, this path does not exist. The remote execution works only because the remote evaluation command explicitly passes all paths as arguments, bypassing the hardcoded default. But any code path that falls through to the default (a missing argument, a new feature that references PROJECT_ROOT directly) will fail silently or with a confusing `FileNotFoundError` on the remote host.

**Why it happens:**
The project started as a Mac-only tool. Path portability was deferred as a known concern (documented in CONCERNS.md). The dry-run phase never exercised real remote paths so the issue was invisible.

**How to avoid:**
- Already partially addressed: the remote command passes all paths explicitly. But defensively add a guard at the top of the evaluator that detects when it is running on a non-Mac host and raises a clear error if any hardcoded path is actually dereferenced.
- Long-term: migrate both modules to use `pdfmd.common.paths.ProjectPaths` for all path resolution.
- For the milestone: verify that every code path exercised by remote evaluation uses only explicitly-passed paths, not module-level defaults.

**Warning signs:**
- `FileNotFoundError: /Users/rookslog/...` in remote SSH execution stderr.
- Tests pass locally but remote execution fails with path-related errors.
- Adding a new `--flag` that references a default path from PROJECT_ROOT breaks the remote path.

**Phase to address:**
Infrastructure/foundation phase. A defensive guard is quick to add; full path migration can be deferred but should be tracked.

---

## Technical Debt Patterns

Shortcuts that seem reasonable but create long-term problems.

| Shortcut | Immediate Benefit | Long-term Cost | When Acceptable |
|----------|-------------------|----------------|-----------------|
| `--system-site-packages` in venv | Avoids downloading ~2GB torch wheel | Non-deterministic torch version, invisible version drift | Acceptable during exploration if the actual resolved version is recorded in manifests |
| No timeout on SSH subprocess calls | Simpler code, fewer error paths | Indefinite hangs on GPU failures, unrecoverable orchestrator state | Never -- must add timeout before live runs |
| One run-manifest schema for all backends | Uniform artifact structure | Cannot distinguish torch version, attention backend, or precision differences between runs | Acceptable for MVP; extend schema when adding GLM-OCR |
| Hardcoded PROJECT_ROOT paths | Works on the developer's machine | Breaks portability, blocks multi-host execution, confuses error messages | Never -- but the workaround (explicit path args) is adequate for now |
| Pinning exact package versions in requirements | Reproducible installs | Version falls behind, accumulates incompatibilities with system packages, blocks security patches | Acceptable if reviewed quarterly; dangerous if forgotten |
| Running all models sequentially via separate SSH | VRAM isolation guaranteed | Slower total evaluation time (SSH overhead + model download per invocation) | Acceptable -- the alternative (multi-model in one process) is riskier on 11GB VRAM |

## Integration Gotchas

Common mistakes when connecting to external services.

| Integration | Common Mistake | Correct Approach |
|-------------|----------------|------------------|
| SSH to dionysus | Not setting `ServerAliveInterval` / `ServerAliveCountMax`, causing silent connection drops during long GPU runs | Add `ServerAliveInterval 60` and `ServerAliveCountMax 3` to the SSH config for the dionysus host |
| rsync bundle transfer | Using `-az` without `--partial`, so interrupted transfers of the generated bundle (can be hundreds of MB) must restart from zero | Use `-azP` (adds `--partial --progress`) to enable resumable transfers |
| HuggingFace model downloads | First run downloads model weights (~440MB for bge-base, ~1.8GB for GLM-OCR) via the transformers cache. If the download happens inside the SSH session and the connection drops, the partially-downloaded cache is corrupted | Set `HF_HOME` or `TRANSFORMERS_CACHE` to a stable location on dionysus; verify model cache integrity before evaluation; use `huggingface-cli download` as a separate step before evaluation |
| Tailscale connectivity | Assuming Tailscale is always connected; temporary Tailscale disconnections during long runs cause SSH to hang (distinct from internet drops) | Probe Tailscale status (`tailscale status`) before starting long evaluation runs; consider `tmux`/`screen` on dionysus so GPU work survives SSH drops |
| CUDA driver/toolkit | Assuming CUDA 11.8 because `.claude/CLAUDE.md` says so, but system actually has CUDA 12.6 driver (550.163.01) with PyTorch 2.9.1+cu126 | Always probe actual CUDA version at runtime via `nvidia-smi` and `torch.version.cuda` rather than trusting documentation. The documentation is stale. |

## Performance Traps

Patterns that work at small scale but fail as evaluation scope grows.

| Trap | Symptoms | Prevention | When It Breaks |
|------|----------|------------|----------------|
| Hashing entire bundle directory before each run | `sha256_directory()` reads every byte of every file in the bundle | Cache the bundle hash and only recompute when `run-manifest.json` timestamp changes | When bundles exceed ~500MB or when running multiple evaluations in sequence |
| Transferring full bundle per backend per model | rsync copies entire bundle directory for each backend, even when the same backend runs multiple models | Share the staged bundle across models (current code already does this per-backend, but verify it persists across model iterations) | When adding more models or larger bundles |
| JSON stdout for large evaluation reports | The evaluator writes the entire evaluation report (all embeddings, all metrics) to stdout, which the orchestrator captures as a string | For large corpora, evaluation.json can exceed 100MB. Write results to a file on the remote host and fetch via rsync instead of stdout capture | When corpora exceed ~1000 passages or when embedding dimension exceeds 768 |
| Model download on first evaluation | HuggingFace downloads model weights inside the evaluation process, adding 30-120s to what appears to be "evaluation time" | Pre-download models in the bootstrap phase, separate from evaluation timing. Verify cache hit before starting the timed evaluation. | When benchmarking runtime performance and wondering why the first run is 3x slower |

## Security Mistakes

Domain-specific security issues beyond general SSH security.

| Mistake | Risk | Prevention |
|---------|------|------------|
| `remote-backends.json` in version control with real hostnames | Leaks infrastructure topology (Tailscale hostname, remote paths, user directories) to anyone who clones the repo | Add `remote-backends.json` to `.gitignore` or use a `remote-backends.example.json` with placeholders. Current repo already tracks this file. |
| Venv bootstrap runs `pip install` over SSH without pinning pip version | Pip version on remote could have known vulnerabilities; no hash verification of downloaded packages | Pin pip in the bootstrap script (`python -m pip install --upgrade pip==X.Y.Z`); use `--require-hashes` in requirements.txt for reproducible, tamper-resistant installs |
| No SSH key restriction on remote commands | The SSH key used for automation has full shell access to dionysus | Consider using `command=` restriction in `authorized_keys` to limit what the automation key can execute, or use a dedicated user with restricted permissions |
| Arbitrary Python code execution via rsynced evaluator script | The evaluator script is rsynced from Mac to remote and executed as-is. A compromised Mac could push malicious code. | This is inherent to the design. Mitigate by verifying the evaluator script hash before remote execution (the manifest already captures this hash -- enforce it) |

## "Looks Done But Isn't" Checklist

Things that appear complete but are missing critical pieces.

- [ ] **Live embedding evaluation:** Running without `--dry-run` produces results -- but verify the torch version in the venv matches expectations (check `runtime.json` for `library_versions.torch`)
- [ ] **Model evaluation metrics:** Numbers appear in the comparison summary -- but verify `manifest_hash_match` is true for all results (false means the remote bundle diverged from local, invalidating the comparison)
- [ ] **GLM-OCR loading:** Model loads without error -- but verify it is using float16 not bfloat16 (check `model.dtype` or the GPU memory consumption vs. expected)
- [ ] **GLM-OCR inference speed:** First page processes in <30s -- but verify subsequent pages maintain speed (VRAM fragmentation can cause progressive slowdown)
- [ ] **Remote cleanup:** `--keep-remote-run` is false and run directory is deleted -- but verify the HuggingFace model cache is NOT deleted (it lives outside the run directory and is expensive to re-download)
- [ ] **SSH keepalive:** Evaluation completes in testing -- but verify it survives a 20-minute GPU computation without SSH timeout (test with an artificially long `sleep` before declaring SSH is reliable)
- [ ] **Evaluation reproducibility:** Running the same model twice produces the same metrics -- but verify across sessions (different CUDA context initialization can cause minor floating-point divergence; set `CUBLAS_WORKSPACE_CONFIG=:4096:8` for deterministic results)
- [ ] **Bundle integrity:** rsync transfer completes without error -- but verify the remote bundle hash matches the local hash (the manifest infrastructure supports this -- enforce the check)

## Recovery Strategies

When pitfalls occur despite prevention, how to recover.

| Pitfall | Recovery Cost | Recovery Steps |
|---------|---------------|----------------|
| Torch version mismatch | LOW | Delete the remote venv directory, update `requirements.txt` to match system torch, re-run bootstrap. All evaluation artifacts remain valid. |
| SSH hang during evaluation | MEDIUM | Kill the SSH process on Mac (`kill -9`), SSH into dionysus separately to check GPU state (`nvidia-smi`), kill any orphaned Python processes on remote, restart evaluation for the hung model only. |
| VRAM OOM during model load | LOW | The process crashes cleanly. GPU memory is freed on process exit. Re-run with smaller batch size or lower precision. |
| VRAM leak across sequential models | MEDIUM | Restart the remote Python process. If GPU is stuck, `nvidia-smi --gpu-reset` (requires root) or reboot dionysus. |
| bfloat16 silent performance degradation | LOW | Detect via timing: if inference is >10x slower than expected, stop and reload with float16. No data loss. |
| Corrupted HuggingFace model cache | MEDIUM | Delete `~/.cache/huggingface/hub/` on dionysus (or the specific model directory), re-download. Takes 5-30 minutes depending on model size and network speed. |
| Bundle hash mismatch between local and remote | LOW | Re-rsync the bundle. The manifest comparison will catch this automatically if the hash check is enforced. |
| Hardcoded path dereferenced on remote | LOW | Error is immediate and obvious. Fix the code path to use passed arguments, re-rsync evaluator, re-run. |

## Pitfall-to-Phase Mapping

How roadmap phases should address these pitfalls.

| Pitfall | Prevention Phase | Verification |
|---------|------------------|--------------|
| Torch version mismatch (#1) | Infrastructure/foundation | Bootstrap output shows matching torch version; `requirements.txt` version matches `torch.__version__` in venv |
| No SSH timeout (#2) | Infrastructure/foundation | Orchestrator recovers from a simulated remote hang (test with `sleep 999` as remote command) |
| VRAM cleanup between models (#3) | Embedding evaluation | `nvidia-smi` shows <500MB VRAM allocated between model evaluations |
| bfloat16 incompatibility (#4) | GLM-OCR exploration | GLM-OCR loads and inferences in <30s per page at float16; no bfloat16 warnings in logs |
| Flash Attention unavailable (#5) | GLM-OCR exploration | Model loads with SDPA fallback; VRAM usage is within budget (documented in run artifact) |
| Concurrent model VRAM (#6) | Architecture/planning | Design doc explicitly states sequential-not-concurrent; code enforces it via separate processes |
| Hardcoded paths (#7) | Infrastructure/foundation | Remote evaluation completes without any `/Users/rookslog/` in stderr output |

## Sources

- Codebase inspection: `src/pdfmd/benchmarks/remote_backends.py` (lines 19, 504-541 -- hardcoded path, no timeout)
- Codebase inspection: `src/pdfmd/benchmarks/embedding_space.py` (lines 20, 646-716 -- GPU handling, model loading)
- Codebase inspection: `src/pdfmd/common/runtime.py` (lines 13-34 -- timeout handling pattern that remote_backends.py lacks)
- Codebase inspection: `skills/.../references/remote-embedding-requirements.txt` -- pins `torch==2.4.1`
- Live hardware probe on dionysus: `torch==2.9.1+cu126`, `CUDA 12.6`, `GTX 1080 Ti` (compute 6.1, 11264 MiB)
- [BAAI/bge-base-en-v1.5 on HuggingFace](https://huggingface.co/BAAI/bge-base-en-v1.5) -- 109M params, ~640MB at fp16
- [GLM-OCR on HuggingFace](https://huggingface.co/zai-org/GLM-OCR) -- 0.9B params, bfloat16 default
- [GLM-OCR HuggingFace docs](https://huggingface.co/docs/transformers/model_doc/glm_ocr) -- usage, processor, attention implementation
- [PyTorch CUDA memory management](https://github.com/pytorch/pytorch/issues/46602) -- `empty_cache()` does not free referenced tensors
- [Flash Attention 2 requires compute >= 8.0](https://www.clarifai.com/blog/flash-attention-2) -- GTX 1080 Ti (6.1) excluded
- [GTX 1080 Ti compute capability](https://developer.nvidia.com/cuda/gpus) -- confirmed 6.1 (Pascal)
- [bfloat16 requires compute >= 8.0 for native support](https://discuss.pytorch.org/t/bfloat16-native-support/117155) -- Pascal GPUs emulate in software
- [PyTorch CUDA 11.8 deprecation timeline](https://github.com/pytorch/pytorch/issues/154257) -- cu118 deprecated in 2.8; cu126 still supports sm_61
- [rsync --partial for resumable transfers](https://ostechnix.com/how-to-resume-partially-downloaded-or-transferred-files-using-rsync/) -- prevents restart-from-zero on interrupted bundle transfers
- [Sentence-transformers efficiency docs](https://sbert.net/docs/sentence_transformer/usage/efficiency.html) -- batch size, precision, memory optimization
- [Sentence-transformers installation](https://sbert.net/docs/installation.html) -- CUDA 11.8 compatible via cu118 wheel index
- [SSH subprocess timeout in Python](https://discuss.python.org/t/sporadic-hang-in-subprocess-run/26213) -- known edge cases with subprocess.run and long-running remote commands

---
*Pitfalls research for: GPU-based embedding evaluation and VLM OCR over SSH-orchestrated scholarly PDF pipeline*
*Researched: 2026-03-19*
