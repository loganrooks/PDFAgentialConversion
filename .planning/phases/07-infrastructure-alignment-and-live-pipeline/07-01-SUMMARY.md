---
phase: 07-infrastructure-alignment-and-live-pipeline
plan: 01
model: claude-sonnet-4-6
context_used_pct: 30
subsystem: remote-embedding-pipeline
tags: ssh, subprocess, timeout, vram, nvidia-smi, sentence-transformers, requirements
requires:
  - phase: 06-remote-embedding-comparison
    provides: initial remote_backends.py pipeline structure and test suite
provides:
  - Correct dependency pins for dionysus environment (INFRA-01)
  - Configurable SSH subprocess timeouts with tier constants (INFRA-02)
  - VRAM safety probe between sequential model evaluations (INFRA-03)
  - Test coverage for timeout behavior and VRAM probe parsing
affects:
  - 07-02-PLAN.md (live pipeline can now run without indefinite hangs or OOM)
  - Phase 08 (depends on Phase 07 leaving a verified-working pipeline)
tech-stack:
  added: []
  patterns:
    - "Timeout tiers: different timeouts per operation class (probe/bootstrap/stage/evaluation)"
    - "VRAM guard: skip-not-abort when dirty VRAM detected before model load"
    - "Structured error returns: TimeoutExpired maps to status=timeout dict matching failure format"
key-files:
  created: []
  modified:
    - skills/pdf-to-structured-markdown/references/remote-embedding-requirements.txt
    - src/pdfmd/benchmarks/remote_backends.py
    - skills/pdf-to-structured-markdown/tests/test_remote_embedding_backends.py
key-decisions:
  - "Exact version pins: torch==2.9.1, sentence-transformers==5.2.0, transformers==4.51.3, numpy>=1.26.4 (floor not exact)"
  - "Timeout tier values: probe=60s, bootstrap=120s, stage=120s, evaluation=600s configurable via CLI"
  - "VRAM threshold: 512 MiB as safety floor -- skip model, not abort pipeline on dirty VRAM"
  - "sync_json_to_remote acquires DEFAULT_TIMEOUT_STAGE default timeout to guard rsync calls"
patterns-established:
  - "Timeout tiers: operation-class-specific timeout constants threaded through all subprocess call sites"
  - "VRAM guard: pre-model nvidia-smi probe with skip-and-continue (not pipeline abort) on dirty state"
duration: 4min
completed: 2026-03-20
---

# Phase 07 Plan 01: Infrastructure Safety Gaps Summary

**INFRA-01/02/03 implemented: dependency pins corrected for dionysus, all SSH subprocess calls now timeout-aware with tier-appropriate defaults, VRAM probe inserted before each model evaluation.**

## Performance
- **Duration:** 4 minutes
- **Tasks:** 2 of 2 completed
- **Files modified:** 3

## Accomplishments
- Updated remote-embedding-requirements.txt to match actual dionysus package versions (torch 2.9.1 was pinned as 2.4.1; sentence-transformers 5.2.0 was 3.0.1; transformers 4.51.3 was 4.44.2)
- Added `timeout` parameter to `run_command()` with `subprocess.TimeoutExpired` handling returning structured `{"status": "timeout", ...}` dict
- Added four timeout tier constants and threaded them through all 10+ `run_command()` call sites in the pipeline (staging, probe, bootstrap, evaluation, tar, fetch, cleanup)
- Added `--evaluation-timeout` CLI argument (default 600s) for operator override of per-model evaluation timeout
- Updated `parse_json_stdout()` to handle `"timeout"` status as a distinct outcome alongside `"dry_run"` and `"failure"`
- Added `build_vram_probe_command()` and `parse_vram_probe()` helpers for nvidia-smi VRAM state queries
- Added VRAM probe before each model evaluation; models with dirty VRAM (>512 MiB in use) are skipped with `failure_stage="vram_dirty"` without aborting the backend pipeline
- Added 8 new unit tests covering all new behaviors (5 VRAM probe tests + 3 timeout tests)

## Task Commits
1. **Task 1: Align dependency pins and add configurable SSH timeouts** - `b3543e0`
2. **Task 2: Add VRAM probe between model evaluations and test coverage** - `455580d`

## Files Created/Modified
- `skills/pdf-to-structured-markdown/references/remote-embedding-requirements.txt` - Updated to actual dionysus versions (INFRA-01)
- `src/pdfmd/benchmarks/remote_backends.py` - Added timeout tiers, timeout parameter to run_command, TimeoutExpired handling, --evaluation-timeout CLI arg, parse_json_stdout timeout status, build_vram_probe_command, parse_vram_probe, VRAM_SAFETY_THRESHOLD_MIB, and VRAM probe in model evaluation loop (INFRA-02, INFRA-03)
- `skills/pdf-to-structured-markdown/tests/test_remote_embedding_backends.py` - Added VramProbeTests (5 tests) and RunCommandTimeoutTests (3 tests)

## Decisions & Deviations

### Minor Deviation: sync_json_to_remote and extract_tarball got timeout support
The plan specified threading timeouts through "all run_command() call sites in the main pipeline loop." Two helper functions (`sync_json_to_remote` and `extract_tarball`) internally call `run_command()` without timeout. Applied Rule 2 (auto-add missing critical functionality): added `timeout: int | None = DEFAULT_TIMEOUT_STAGE` to `sync_json_to_remote` and hardcoded `DEFAULT_TIMEOUT_STAGE` in `extract_tarball`. These are the same class of operation (rsync/tar) as the explicitly-listed stage calls.

### Pre-existing test failures (not caused by this plan)
Two tests (`test_hash_helpers_and_manifest_capture_input_identity`, `test_compare_harness_dry_run_writes_summary_and_manifests`) fail with `FileNotFoundError` because `PROJECT_ROOT` is hardcoded to a Mac path (`/Users/rookslog/Projects/...`) and this code runs on the Linux development server. Verified pre-existing on original code via `git stash`. Confirmed 5/7 original tests pass unchanged; all 8 new tests pass.

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
Phase 07-02 (remove --dry-run from default make target and add trust_remote_code support) can proceed. The pipeline safety foundations are in place:
- All SSH subprocess calls are now guarded against indefinite hangs
- VRAM state is probed between sequential model evaluations
- Dependency pins reflect actual dionysus environment versions

## Self-Check: PASSED

- FOUND: remote-embedding-requirements.txt
- FOUND: remote_backends.py
- FOUND: test_remote_embedding_backends.py
- FOUND: 07-01-SUMMARY.md
- FOUND commit: b3543e0 (Task 1)
- FOUND commit: 455580d (Task 2)
- VERIFIED: torch==2.9.1 pin correct
- VERIFIED: timeout constants exist
- VERIFIED: VRAM probe function exists
- VERIFIED: VRAM tests exist
