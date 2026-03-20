# Project State

## Project Reference

See: .planning/PROJECT.md (updated 2026-03-19)

**Core value:** Make difficult PDFs operationally legible and reproducible without sacrificing structural rigor, retrieval quality, or auditability.
**Current focus:** Phase 07 - Infrastructure Alignment and Live Pipeline

## Current Position

Phase: 07 of 09 (Infrastructure Alignment and Live Pipeline)
Plan: 1 of TBD in current phase
Status: In progress
Last activity: 2026-03-20 -- Completed 07-01: dependency pin alignment, SSH timeouts, VRAM probe

Progress: [█░░░░░░░░░] 10%

## Performance Metrics

**Velocity:**
- Total plans completed: 1 (v1.1); 22 (v1.0)
- Average duration: 4min
- Total execution time: 4min

**By Phase:**

| Phase | Plans | Total | Avg/Plan |
|-------|-------|-------|----------|
| 07 | 1 | 4min | 4min |

**Recent Trend:**
- Last 5 plans: 4min (07-01)
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

### Pending Todos

None yet.

### Blockers/Concerns

- dionysus CUDA documentation in CLAUDE.md says 11.8 but system has 12.6 driver -- update after Phase 07
- GLM-OCR fp16 inference speed on GTX 1080 Ti is empirically unvalidated (only T4 data exists)

## Session Continuity

Last session: 2026-03-20
Stopped at: Completed 07-01-PLAN.md (infrastructure safety gaps: INFRA-01, INFRA-02, INFRA-03)
Resume file: None
