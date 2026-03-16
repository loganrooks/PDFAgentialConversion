# STATE

## Current Focus

- Milestone `v1.0` is complete and archived.
- There is no active roadmap phase; the next step is defining the next milestone.
- The canonical `why-ethics` gate remains green, enforced, and stable across repeated runs.
- The challenge corpus remains the hard non-regression baseline.
- `Specters of Marx` remains the clean negative control.
- Remote backend comparisons remain report-only and experiment-only.

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
- [Phase 05]: Use a tracked cross-book exact-case packet instead of live-count assertions for the remaining repair surface. — This keeps the characterization slice stable while allowing later repair plans to reduce issue counts without rewriting unrelated tests.
- [Phase 05]: Expand only known-good source-specific regressions in Plan 05-01. — The first cross-book slice should protect clean surfaces without encoding currently broken outputs as expected truth.
- [Phase 05]: Prefer explicit or inline heading evidence over lowercase continuation when slicing same-page boundaries. — This prevents the previous section from incorrectly inheriting a new section's heading page.
- [Phase 05]: Normalize the malformed symbolic Outside/Inside title narrowly instead of broadening title normalization. — The repair is structural and book-local, not a general title-casing policy change.
- [Phase 05]: Promote the challenge corpus as a hard non-regression gate without rebasing the canonical `why-ethics` holdout. — Cross-book protection is now enforceable, but it does not supersede the local holdout.
- [Phase 06]: Promote the repaired chapter-5 manual packet from report-only evidence into the canonical gate once strict regressions are green. — The final `why-comment` repair is now part of the real acceptance contract.

## Known Active Failures

- none in the tracked project gates
- external note: `make map` may still be blocked by Codex skill-loader YAML errors outside this repo; `.planning/codebase/` was refreshed manually as a fallback when needed

## Next Verification Gates

- `make test-fast`
- `make test`
- `make status`
- `make doctor`
- `make gate`
- `make smoke`
- `make compare-backends`

## Next Command

- `$gsdr-new-milestone`
