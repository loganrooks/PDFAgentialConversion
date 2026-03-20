# Project State

## Project Reference

See: .planning/PROJECT.md (updated 2026-03-19)

**Core value:** Make difficult PDFs operationally legible and reproducible without sacrificing structural rigor, retrieval quality, or auditability.
**Current focus:** Phase 07 - Infrastructure Alignment and Live Pipeline

## Current Position

Phase: 07 of 09 (Infrastructure Alignment and Live Pipeline)
Plan: 2 of 2 in current phase
Status: Awaiting human checkpoint (07-02 Task 2: live pipeline smoke test)
Last activity: 2026-03-20 -- Completed 07-02 Task 1: trust_remote_code support, live Makefile

Progress: [██░░░░░░░░] 20%

## Performance Metrics

**Velocity:**
- Total plans completed: 1 (v1.1); 22 (v1.0)
- Average duration: 4min
- Total execution time: 4min

**By Phase:**

| Phase | Plans | Total | Avg/Plan |
|-------|-------|-------|----------|
| 07 | 2 | 7min | 3.5min |

**Recent Trend:**
- Last 5 plans: 4min (07-01), 3min (07-02)
- Trend: --

*Updated after each plan completion*

## Accumulated Context

### Decisions

- [v1.0]: Use GSD as the only planning system.
- [v1.0]: Local M4 Apple embedding remains the canonical gate.
- [v1.0]: Remote GPU host is experiment-only, report-only.
- [v1.1]: Mac orchestrates via SSH; dionysus is always the remote GPU compute backend.
- [v1.1]: Embedding and OCR are sequential workstreams (VRAM constraint on 11GB GPU).
- [v1.1]: GLM-OCR gets its own isolated venv (transformers version conflict is a hard constraint).
- [07-01]: Dependency pins set to exact dionysus versions (torch==2.9.1, sentence-transformers==5.2.0, transformers==4.51.3, numpy>=1.26.4 floor).
- [07-01]: SSH timeout tiers: probe=60s, bootstrap=120s, stage=120s, evaluation=600s (CLI configurable).
- [07-01]: VRAM safety threshold 512 MiB -- dirty VRAM skips model, does not abort backend pipeline.
- [Phase 07]: Per-model trust_remote_code config: opt-in via model_config dict in remote-backends.json, not a global flag
- [Phase 07]: Makefile compare-backends runs live by default; dry-run available via COMPARE_BACKENDS_ARGS='--dry-run'

### Pending Todos

None yet.

### Blockers/Concerns

- dionysus CUDA documentation in CLAUDE.md says 11.8 but system has 12.6 driver -- update after Phase 07
- GLM-OCR fp16 inference speed on GTX 1080 Ti is empirically unvalidated (only T4 data exists)

## Session Continuity

Last session: 2026-03-20
Stopped at: Awaiting human-verify checkpoint for 07-02 Task 2 (live pipeline smoke test on dionysus)
Resume file: None
