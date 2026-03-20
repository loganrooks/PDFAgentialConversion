---
phase: 07-infrastructure-alignment-and-live-pipeline
plan: 02
model: claude-sonnet-4-6
context_used_pct: 35
subsystem: remote-embedding-pipeline
tags: trust_remote_code, sentence-transformers, ssh, makefile, nomic-embed, pipeline-live
requires:
  - phase: 07-01
    provides: timeout tiers, VRAM probe, dependency pins — safe foundation for live pipeline
provides:
  - trust_remote_code support per-model via remote-backends.json config (EMBED-04)
  - Live Makefile compare-backends target (EMBED-01)
  - --trust-remote-code CLI flag in evaluate_embedding_space.py
  - 6 new unit tests covering trust_remote_code threading and config validation
affects:
  - Phase 08 (nomic-embed-text-v1.5 can now be added to models list and will load correctly)
  - Operator workflow (compare-backends runs live by default; no --dry-run needed)
tech-stack:
  added: []
  patterns:
    - "Per-model config: model_config dict in backend JSON maps model names to settings"
    - "trust_remote_code threading: JSON config -> validate_backend_entry -> build_remote_evaluation_command -> SSH CLI -> SentenceTransformer"
    - "Opt-in flag pattern: trust_remote_code=False default, only enabled for models that need it"
key-files:
  created: []
  modified:
    - skills/pdf-to-structured-markdown/references/remote-backends.json
    - src/pdfmd/benchmarks/remote_backends.py
    - src/pdfmd/benchmarks/embedding_space.py
    - Makefile
    - skills/pdf-to-structured-markdown/tests/test_remote_embedding_backends.py
key-decisions:
  - "Per-model config (not global flag): trust_remote_code is opt-in per model name in model_config dict"
  - "Makefile live by default: --dry-run removed from compare-backends; operators use COMPARE_BACKENDS_ARGS='--dry-run' to get dry-run"
  - "nomic-embed schema deferred: model_config entry for nomic established but model not added to models list until Phase 08"
patterns-established:
  - "Per-model config threading: backend JSON -> validate -> pipeline loop -> SSH command builder -> remote CLI"
duration: 3min
completed: 2026-03-20
---

# Phase 07 Plan 02: trust_remote_code Support and Live Pipeline Summary

**trust_remote_code support threaded from per-model JSON config through SSH evaluation command to SentenceTransformer constructor; compare-backends Makefile target now runs live by default.**

## Performance
- **Duration:** 3 minutes
- **Tasks:** 1 of 2 completed (Task 2 is a human-verify checkpoint)
- **Files modified:** 5

## Accomplishments
- Added optional `model_config` field to `remote-backends.json` backend entries; schema supports per-model settings with `nomic-ai/nomic-embed-text-v1.5` as the initial example (trust_remote_code=true)
- Updated `validate_backend_entry()` to validate and pass through `model_config` dict into the pipeline (critical: the function constructs an explicit return dict so model_config had to be explicitly included)
- Added `trust_remote_code: bool = False` parameter to `build_remote_evaluation_command()`; when True, appends `--trust-remote-code` to the SSH evaluation CLI before the `>` redirect
- Main pipeline loop now looks up per-model trust_remote_code from `backend.model_config.get(model_name, {}).get("trust_remote_code", False)` and passes it through
- Added `--trust-remote-code` as a `store_true` CLI argument in `embedding_space.py parse_args()`
- Added `trust_remote_code: bool = False` parameter to `load_embeddings_sentence_transformers()` and passed it to `SentenceTransformer(model_name, device=resolved_device, trust_remote_code=trust_remote_code)`
- Removed `--dry-run` from `compare-backends` Makefile target; operators who want dry-run use `make compare-backends COMPARE_BACKENDS_ARGS='--dry-run'`
- Added 6 new `TrustRemoteCodeTests` covering: command includes flag when True, excludes when False, validate_backend_entry with/without model_config, parse_args recognizes flag, default is False

## Task Commits
1. **Task 1: Add trust_remote_code support and enable live pipeline execution** - `1707585`
2. **Task 2: Verify live pipeline execution on dionysus** - awaiting human checkpoint

## Files Created/Modified
- `skills/pdf-to-structured-markdown/references/remote-backends.json` - Added `model_config` field with nomic-embed schema example (EMBED-04)
- `src/pdfmd/benchmarks/remote_backends.py` - validate_backend_entry passes model_config; build_remote_evaluation_command accepts trust_remote_code; pipeline loop looks up per-model trust_remote_code (EMBED-04)
- `src/pdfmd/benchmarks/embedding_space.py` - --trust-remote-code CLI arg; load_embeddings_sentence_transformers accepts trust_remote_code; SentenceTransformer constructor receives it (EMBED-04)
- `Makefile` - Removed --dry-run from compare-backends target (EMBED-01)
- `skills/pdf-to-structured-markdown/tests/test_remote_embedding_backends.py` - 6 new TrustRemoteCodeTests; fixed FakeSentenceTransformerModel to accept trust_remote_code kwarg

## Decisions & Deviations

### Decision: Per-model config (not global flag)
trust_remote_code is opt-in per model via the `model_config` dict rather than a global flag. Only specific models (e.g., nomic-embed) need it; always-on would be unnecessarily permissive.

### Auto-fix Deviation: FakeSentenceTransformerModel missing trust_remote_code kwarg
**[Rule 1 - Bug] Fixed FakeSentenceTransformerModel to accept trust_remote_code kwarg**
- **Found during:** Task 1 test run
- **Issue:** `FakeSentenceTransformerModel.__init__()` did not accept `trust_remote_code` keyword argument, causing `test_sentence_transformers_cpu_smoke_on_tiny_fixture_bundle` to fail with TypeError after the SentenceTransformer constructor change
- **Fix:** Added `trust_remote_code: bool = False` to FakeSentenceTransformerModel.__init__ signature
- **Files modified:** `skills/pdf-to-structured-markdown/tests/test_remote_embedding_backends.py`
- **Commit:** 1707585 (included in same task commit)

### Pre-existing failures (not caused by this plan)
2 tests (`test_hash_helpers_and_manifest_capture_input_identity`, `test_compare_harness_dry_run_writes_summary_and_manifests`) fail with `FileNotFoundError` because `PROJECT_ROOT` is hardcoded to a Mac path. Confirmed pre-existing in 07-01 and again verified via `git stash`.

## User Setup Required
**Task 2 requires human verification.** Run the live pipeline smoke test:
```bash
make compare-backends COMPARE_BACKENDS_ARGS='--backend-ids dionysus'
```
Verify `comparison-summary.json` has `dry_run: false` and at least one result with real aggregate_metrics. Report result back to resume agent.

## Next Phase Readiness
After human verification of Task 2, Phase 07 is complete. Phase 08 can proceed with:
- Adding `nomic-ai/nomic-embed-text-v1.5` to the `models` list in remote-backends.json (model_config schema already in place)
- Full live pipeline is operational and human-verified

## Self-Check: PASSED

- FOUND: Makefile (no --dry-run in compare-backends)
- FOUND: remote-backends.json (model_config schema present)
- FOUND: remote_backends.py (trust_remote_code in validate_backend_entry, build_remote_evaluation_command, pipeline loop)
- FOUND: embedding_space.py (--trust-remote-code arg, trust_remote_code parameter, SentenceTransformer call)
- FOUND: test_remote_embedding_backends.py (TrustRemoteCodeTests class with 6 tests)
- FOUND commit: 1707585 (Task 1)
- VERIFIED: 19/21 tests pass; 2 pre-existing Mac-path failures unchanged
- VERIFIED: 6 new TrustRemoteCodeTests all pass
