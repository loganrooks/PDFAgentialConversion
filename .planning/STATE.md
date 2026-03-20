# Project State

## Project Reference

See: .planning/PROJECT.md (updated 2026-03-19)

**Core value:** Make difficult PDFs operationally legible and reproducible without sacrificing structural rigor, retrieval quality, or auditability.
**Current focus:** Phase 07 complete — ready for Phase 08

## Current Position

Phase: 07 of 09 (Infrastructure Alignment and Live Pipeline) — COMPLETE
Plan: 2 of 2 in current phase — COMPLETE
Status: Phase 07 verified with live GPU metrics from all 3 models
Last activity: 2026-03-20 -- Live pipeline smoke test passed (all 3 models produce real metrics on dionysus)

Progress: [██████████] 100%

## Performance Metrics

**Velocity:**
- Total plans completed: 2 (v1.1); 22 (v1.0)
- Average duration: 4min (code), ~30min (live debugging)
- Total execution time: ~40min

**By Phase:**

| Phase | Plans | Total | Avg/Plan |
|-------|-------|-------|----------|
| 07 | 2 | ~40min | ~20min |

**Recent Trend:**
- Last 5 plans: 4min (07-01), 3min (07-02 code) + ~30min (live debugging)
- Trend: Live execution surfaced 5 bugs invisible to dry-run testing

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
- [07-01]: SSH timeout tiers: probe=60s, bootstrap=600s, stage=120s, evaluation=600s (CLI configurable).
- [07-01]: VRAM safety threshold 1024 MiB -- dirty VRAM skips model, does not abort backend pipeline.
- [07-02]: Per-model trust_remote_code config: opt-in via model_config dict in remote-backends.json, not a global flag.
- [07-02]: Makefile compare-backends runs live by default; dry-run available via COMPARE_BACKENDS_ARGS='--dry-run'.
- [07-02]: CUDA torch requires --extra-index-url https://download.pytorch.org/whl/cu126 in requirements.
- [07-02]: SSH commands must use shlex.join() for proper quoting of multi-line scripts.
- [07-02]: Remote evaluator uses embedding_space.py directly (self-contained, no pdfmd package needed).

### Live Benchmark Results (2026-03-20)

| Model | twin_cosine | hit@1 | MRR | Time |
|-------|------------|-------|-----|------|
| bge-small-en-v1.5 | 0.9758 | 0.9891 | 0.9932 | 7.3s |
| bge-base-en-v1.5 | 0.9680 | 0.9928 | 0.9935 | 29.4s |
| e5-base-v2 | 0.9766 | 0.9928 | 0.9945 | 28.5s |

### Pending Todos

- Rethink Mac-orchestrator-only architecture — user wants to run pipeline directly from dionysus
- Update CLAUDE.md CUDA documentation (says 11.8, system has 12.6 driver)
- Fix 2 pre-existing Mac-path test failures (hardcoded /Users/rookslog paths)
- Evaluate conda removal — pip + venv covers all project needs

### Blockers/Concerns

- local-apple baseline fails (expected — no Apple hardware when running from dionysus)
- Architecture question: pipeline should be runnable from either machine, not just Mac
- GLM-OCR fp16 inference speed on GTX 1080 Ti is empirically unvalidated (only T4 data exists)

## Session Continuity

Last session: 2026-03-20
Stopped at: Phase 07 complete. Ready for Phase 08 or architecture rethink.
Resume file: None
