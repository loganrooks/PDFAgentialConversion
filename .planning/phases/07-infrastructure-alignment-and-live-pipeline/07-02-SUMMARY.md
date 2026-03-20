---
phase: 07-infrastructure-alignment-and-live-pipeline
plan: 02
model: claude-opus-4-6
context_used_pct: 65
subsystem: remote-embedding-pipeline
tags: trust-remote-code, live-pipeline, ssh-quoting, cuda, vram, makefile
requires:
  - phase: 07-01
    provides: SSH timeouts, VRAM probes, aligned dependency pins
provides:
  - trust_remote_code support through full evaluation path (EMBED-04)
  - Live pipeline execution via Makefile (EMBED-01)
  - Verified end-to-end GPU metrics from all 3 models on dionysus
affects:
  - Phase 08 (expanded embedding evaluation can now run live)
  - Phase 09 (GLM-OCR exploration benefits from proven remote execution path)
tech-stack:
  added: []
  patterns:
    - "Per-model config: model_config dict in remote-backends.json for opt-in flags"
    - "SSH command quoting: shlex.join() for multi-line bash -lc scripts"
    - "Defense-in-depth JSON parsing: extract last JSON object from noisy stdout"
    - "Self-contained remote evaluator: rsync embedding_space.py directly (no pdfmd package needed)"
key-files:
  created: []
  modified:
    - src/pdfmd/benchmarks/remote_backends.py
    - src/pdfmd/benchmarks/embedding_space.py
    - skills/pdf-to-structured-markdown/references/remote-backends.json
    - skills/pdf-to-structured-markdown/references/remote-embedding-requirements.txt
    - skills/pdf-to-structured-markdown/tests/test_remote_embedding_backends.py
    - Makefile
---

## Objective

Add trust_remote_code support for models that need it (EMBED-04) and enable live pipeline execution by removing the --dry-run default from the Makefile (EMBED-01). Verify with a live smoke test against dionysus.

## What Changed

### Task 1: trust_remote_code + Live Pipeline Enablement

**EMBED-04 (trust_remote_code):**
- `remote-backends.json`: Added optional `model_config` dict for per-model settings (e.g., `"trust_remote_code": true` for nomic-embed)
- `validate_backend_entry()`: Accepts and passes through `model_config` field
- `build_remote_evaluation_command()`: New `trust_remote_code` param appends `--trust-remote-code` to SSH command
- `embedding_space.py`: `--trust-remote-code` CLI arg, wired through to `SentenceTransformer(trust_remote_code=True)`
- Pipeline loop: Reads per-model config and threads through to evaluation command
- 6 new tests covering trust_remote_code threading and config validation

**EMBED-01 (live pipeline):**
- Makefile `compare-backends` target: Removed `--dry-run` default; operators use `COMPARE_BACKENDS_ARGS='--dry-run'` when needed

### Bugfixes Discovered During Live Verification

Five bugs were invisible during dry-run mode and only surfaced during the first live execution:

1. **SSH command quoting** (`build_ssh_command`): SSH concatenates remote args with spaces, breaking `bash -lc` scripts. The script was truncated at the first space, executing just `set` (dumping env vars) instead of the full script. Fix: `shlex.join()` to produce a single properly-quoted string.

2. **CUDA torch index URL** (`remote-embedding-requirements.txt`): `pip install torch==2.9.1` from PyPI installs CPU-only. Added `--extra-index-url https://download.pytorch.org/whl/cu126` for CUDA-linked wheel (GTX 1080 Ti uses sm_60 architecture, supported in cu126 builds).

3. **Bootstrap timeout**: `DEFAULT_TIMEOUT_BOOTSTRAP` was 120s, insufficient for downloading the ~2GB torch CUDA wheel on first run. Raised to 600s.

4. **VRAM threshold**: `VRAM_SAFETY_THRESHOLD_MIB` was 512, but GTX 1080 Ti uses ~580 MiB at idle for display driver. Raised to 1024 MiB.

5. **Remote evaluator import**: Pipeline rsynced the thin wrapper script (`scripts/evaluate_embedding_space.py`) which uses `sys.path` to find the `pdfmd` package — not available on the remote venv. Fix: rsync the self-contained `src/pdfmd/benchmarks/embedding_space.py` directly (no pdfmd imports needed).

Additionally, `parse_json_stdout` gained defense-in-depth JSON extraction from noisy stdout (SSH login shells may dump env vars before payload).

### Task 2: Live Pipeline Verification (Checkpoint)

Live run from apollo via SSH to dionysus produced real metrics from all 3 models:

| Model | twin_cosine | hit@1 | MRR | Time |
|-------|------------|-------|-----|------|
| BAAI/bge-small-en-v1.5 | 0.9758 | 0.9891 | 0.9932 | 7.3s |
| BAAI/bge-base-en-v1.5 | 0.9680 | 0.9928 | 0.9935 | 29.4s |
| intfloat/e5-base-v2 | 0.9766 | 0.9928 | 0.9945 | 28.5s |

Run ID: `20260320T085629Z`, `dry_run: false`

## Self-Check

- [x] trust_remote_code flows end-to-end from config to SentenceTransformer constructor
- [x] Makefile compare-backends runs live by default (no --dry-run)
- [x] comparison-summary.json has non-null metrics from all 3 models
- [x] Dry-run available via COMPARE_BACKENDS_ARGS
- [x] 20/20 tests pass (2 pre-existing Mac-path failures excluded)
- [x] SSH commands properly quoted for multi-line scripts
- [x] CUDA torch wheel installed via correct index URL

## Deviations

1. **Bootstrap timeout 120s → 600s**: Plan specified 120s but first-run torch download requires more time.
2. **VRAM threshold 512 → 1024 MiB**: Plan specified 512 but display-attached GPU has ~580 MiB idle usage.
3. **Remote evaluator strategy**: Plan didn't anticipate the pdfmd import issue. Fixed by rsyncing the self-contained implementation directly.
4. **SSH quoting bug**: Pre-existing in build_ssh_command, only visible during live execution. Fixed with shlex.join().
5. **CUDA index URL**: Pre-existing omission in requirements file. CPU-only torch would have been installed without it.

## Commits

- `1707585` feat(07-02): add trust_remote_code support and enable live pipeline (EMBED-04, EMBED-01)
- `f91b11f` docs(07-02): complete trust_remote_code and live pipeline plan (checkpoint reached)
- `d62dcef` fix(07-02): fix SSH command quoting, CUDA index URL, and noisy stdout parsing
- `c95a31c` fix(07-02): increase bootstrap timeout to 600s for torch CUDA wheel download
- `aa4158d` fix(07-02): raise VRAM safety threshold to 1024 MiB for display-attached GPU
- `244b020` fix(07-02): rsync self-contained evaluator for remote execution
