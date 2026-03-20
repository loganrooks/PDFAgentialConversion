# Phase 07: Infrastructure Alignment and Live Pipeline - Context

**Gathered:** 2026-03-20
**Status:** Ready for research

<domain>
## Phase Boundary

Fix foundation gaps in the remote embedding comparison pipeline and prove it works end-to-end with live GPU metrics on dionysus. Specifically: align stale dependency pins, add SSH subprocess timeouts, add VRAM safety checks, remove the dry-run constraint, and support `trust_remote_code` for models that need it.

**Requirements:** INFRA-01, INFRA-02, INFRA-03, EMBED-01, EMBED-04

**Not in scope:** Expanding the model roster (Phase 08), GLM-OCR (Phase 09), reporting improvements (Phase 08). The live smoke test uses the existing 3-model roster only.

</domain>

<assumptions>
## Working Model & Assumptions

**A1: Process isolation already handles most VRAM cleanup.** Each remote model evaluation is a separate SSH command launching a new Python process (`build_remote_evaluation_command` → `run_command`). When the process exits, VRAM is freed by the OS/driver. The VRAM guard (INFRA-03) is therefore about detecting failed processes that left VRAM dirty and optionally probing availability before starting the next model — not about in-process `del model + gc.collect + torch.cuda.empty_cache()`.
- *Validate by:* confirming that `nvidia-smi` shows clean VRAM between sequential SSH evaluation commands.

**A2: The `--system-site-packages` venv inherits torch from the conda base.** The bootstrap script checks `import torch` before deciding whether to install from requirements. Since dionysus has torch 2.9.1+cu126 in the base environment, the pinned `torch==2.4.1` in `remote-embedding-requirements.txt` is never installed. The venv inherits the system torch.
- *Validate by:* inspecting the bootstrap script behavior and the actual venv `pip list` after bootstrap on dionysus.

**A3: The evaluator script works on the remote host despite the hardcoded Mac path.** `embedding_space.py:20` has `PROJECT_ROOT = Path("/Users/rookslog/Projects/PDFAgentialConversion")` but this is only used for `DEFAULT_APPLE_HELPER` (the Swift embedding helper), which is irrelevant when running with `--embedding-backend sentence_transformers` on the remote host. The evaluator script is rsynced to dionysus and invoked there.
- *Validate by:* confirming the remote evaluation path never touches `PROJECT_ROOT` or `DEFAULT_APPLE_HELPER`.

</assumptions>

<decisions>
## Implementation Decisions

### Requirements alignment strategy
- Update `remote-embedding-requirements.txt` to match the actual dionysus system versions, not switch to a pure system-site-packages-only strategy. The requirements file serves as documentation and reproducibility — even if `--system-site-packages` masks the pins, the pins should be correct for when the venv needs to install packages (e.g., on a fresh host).

### Dry-run removal approach
- The Makefile (`compare-backends` target) hardcodes `--dry-run`. Remove `--dry-run` from the default target so `make compare-backends` runs live. Operators who want dry-run can pass `COMPARE_BACKENDS_ARGS='--dry-run'`.
- The live smoke test for this phase should use just one model (bge-small-en-v1.5) to validate the pipeline before Phase 08 runs all 8.

### SSH timeout pattern
- Adopt the same `timeout` parameter pattern from `src/pdfmd/common/runtime.py` into `remote_backends.py`'s `run_command()`. The existing pattern (subprocess `timeout` kwarg → `TimeoutExpired` → structured error) is proven and consistent.
- Different stages need different timeouts: probe/bootstrap commands (short, ~60s), evaluation commands (long, ~600s per model, configurable).

### Claude's Discretion
- Exact timeout values for each stage (researcher should investigate typical evaluation durations)
- VRAM probe implementation details (nvidia-smi parse vs torch.cuda query vs simple check)
- Whether to add `trust_remote_code` as a per-model config field in `remote-backends.json` or as a global pipeline setting
- Error message formatting for timeout and VRAM failure cases

</decisions>

<constraints>
## Derived Constraints

**C1: Mac orchestrates, dionysus is the SSH remote target.** Locked at milestone level. No cross-platform path changes. The comparison harness runs on Mac and issues SSH commands to dionysus.

**C2: The existing `remote_backends.py` orchestration structure stays.** This is a 1300-line file with a clean stage-based pipeline (probe → bootstrap → evaluate → fetch → compare). Phase 07 adds safety (timeouts, VRAM checks) and enables live execution — it does not restructure the pipeline.

**C3: Local Apple NL baseline runs on Mac.** The comparison always starts with a local Apple NL evaluation (`build_local_baseline_command`) before running remote models. This baseline is Mac-only and requires Swift + NaturalLanguage framework.

**C4: CUDA is 12.6 (driver 550.163.01), not 11.8.** The CLAUDE.md documentation is stale. PyTorch 2.9.1 ships with the cu126 wheel, which supports compute capability 6.1 (GTX 1080 Ti). This does not require code changes but the documentation should be corrected.

**C5: The existing 3 models stay unchanged for the Phase 07 smoke test.** BGE-small, BGE-base, E5-base. Phase 08 expands to 8 models.

**C6: Phase 08 depends on Phase 07 leaving a verified-working pipeline.** Any changes must be backward-compatible with the existing test suite (`make test-fast`, `make test`).

</constraints>

<questions>
## Open Questions

**Q1: What are typical evaluation durations per model on dionysus?**
- Type: material
- Why it matters: SSH timeout values must be long enough for normal evaluation but short enough to catch hangs. Too short → false timeouts; too long → defeat the purpose.
- Downstream decision: default timeout values per stage type
- Reversibility: HIGH (can adjust after first live run)
- Research should: run a single live evaluation of bge-small-en-v1.5 and measure wall-clock time, or review the calibration data if any exists

**Q2: Does the remote evaluation actually clean up VRAM between models?**
- Type: material
- Why it matters: If process exit doesn't release VRAM (driver bug, zombie process), the next model will OOM
- Downstream decision: whether VRAM probe is a safety check or a hard gate
- Reversibility: HIGH (can start with a warning and escalate to a gate)
- Research should: check nvidia-smi output between two sequential model evaluations on dionysus

**Q3: Where should `trust_remote_code` be injected in the evaluation pipeline?**
- Type: formal
- Why it matters: `embedding_space.py:677` calls `SentenceTransformer(model_name, device=resolved_device)` without `trust_remote_code`. Some models (nomic-embed) require it. The parameter must be passed through from the comparison harness.
- Downstream decision: whether it's a per-model config field, a CLI flag, or always-on
- Reversibility: HIGH (can change the injection point later)
- Research should: check the SentenceTransformer constructor API and determine the cleanest injection point

**Q4: Should the requirements file pin exact versions or use >= constraints?**
- Type: formal
- Why it matters: Exact pins are more reproducible but break on version drift. >= constraints are more flexible but less predictable.
- Downstream decision: contents of `remote-embedding-requirements.txt`
- Reversibility: HIGH (can change pin style later)
- Research should: check current best practice for sentence-transformers deployment and whether `--system-site-packages` makes exact pins moot

</questions>

<guardrails>
## Epistemic Guardrails

**G1: Do not assume the existing dry-run tests cover live execution paths.** The comparison harness has `if dry_run: return runtime` early exits throughout. Research should identify what code paths are untested when `--dry-run` is False.

**G2: Do not assume the evaluator script is portable without changes.** `embedding_space.py` has a hardcoded Mac `PROJECT_ROOT`. Even though it's likely only used for the Apple helper path, research must confirm no other code path depends on it when running remotely.

**G3: Do not conflate the two `run_command` functions.** `common/runtime.py` has one (with timeout). `remote_backends.py` has its own (without timeout, but with `dry_run` support and wall-clock tracking). These serve different purposes. The fix is to add timeout to the remote_backends version, not to replace it with the common version.

**G4: Verify the existing test suite still passes after changes.** `make test-fast` and `make test` are the regression gates. Any changes to `remote_backends.py` or `embedding_space.py` must not break them.

</guardrails>

<specifics>
## Specific Ideas

No specific requirements — open to standard approaches.

</specifics>

<deferred>
## Deferred Ideas

- **Per-model batch size configuration** — Phase 08 scope (EMBED-02)
- **Expanded model roster** — Phase 08 scope (EMBED-03)
- **Historical comparison tracking** — Phase 08 scope (RPT-01)
- **CUDA documentation update in CLAUDE.md** — should happen during Phase 07 but is not a tracked requirement; capture as a todo if convenient
- **Extracting SSH transport into a shared module** — Architecture research suggested `ssh_transport.py` extraction; defer unless Phase 07 planning shows clear benefit

</deferred>

---

*Phase: 07-infrastructure-alignment-and-live-pipeline*
*Context gathered: 2026-03-20*
