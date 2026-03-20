# STATE

## Current Position

Phase: Not started (defining requirements)
Plan: —
Status: Defining requirements
Last activity: 2026-03-19 — Milestone v1.1 started

## Current Focus

- Milestone `v1.1` is active: Remote Evaluation & Extraction Exploration.
- Turning the `dionysus` GPU backend from dry-run infrastructure into live measured comparisons.
- Exploring GLM-OCR as a potential extraction model for scholarly PDFs.
- Mac orchestrates via SSH; `dionysus` is the GPU compute backend.

## Decisions

- Use GSD as the only planning system.
- Treat `generated/` as runtime output.
- Keep the local M4 gate canonical.
- Keep the remote GPU host experiment-only.
- Prefer local-first automation before hosted CI.
- Use `make gate GATE_ARGS='...'` for explicit runtime verification overrides instead of editing Make targets by hand.
- Require repeated successful `why-ethics` gate runs before declaring the canonical holdout restored or promoting future baselines.
- Keep `Specters of Marx` as the clean negative control during cross-book closure work.
- Keep remote embedding/backend experiments report-only; they do not affect the canonical local gate.
- [v1.1]: Mac orchestrates, dionysus is always the remote GPU compute backend for embedding and model evaluation.
- [v1.1]: SSH-from-Mac orchestration model preserved; no cross-platform path changes needed.

## Known Active Failures

- none in the tracked project gates
- external note: `make map` may still be blocked by Codex skill-loader YAML errors outside this repo

## Next Verification Gates

- `make test-fast`
- `make test`
- `make status`
- `make doctor`
- `make gate`
- `make smoke`
- `make compare-backends`

## Next Command

- Define requirements for v1.1
