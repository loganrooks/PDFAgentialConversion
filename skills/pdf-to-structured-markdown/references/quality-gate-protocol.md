# Quality Gate Protocol

Use this protocol before landing any new layout heuristic on a generated book bundle.

## Purpose

Freeze a known-good bundle, compare every later change against it, and refuse extractor
edits that improve one local page while silently degrading the rest of the book.

The current proving corpus is `why-ethics`. The gate operates on anchor-scoped passage
blocks and their neighboring bundle diagnostics, not on unscoped whole-file impressions.

## Epistemic Lenses

### Process Reliability (Goldman)

The process is reliable only if the same accepted bundle keeps passing the same checks.

Required evidence:
- `check_regressions.py --strict` passes.
- untouched holdout scopes do not worsen.
- `probe_artifacts.py` introduces no new issue code.
- audit warnings stay within the allowed code list.
- the embedding helper either completes within the configured runtime window or fails with a classified timeout artifact rather than wedging the session.

### Progressiveness (Lakatos)

A heuristic is progressive only if it resolves at least one target failure while adding a
new regression anchor for that repaired class.

Required evidence:
- target-scope probe counts decrease for at least one issue class when target-wave
  enforcement is enabled.
- a new or tightened anchor-scoped regression accompanies the repaired class.

### Explanatory Virtue (Lipton)

Do not accept a heuristic that only says "it seemed to help."

Before shipping a fix, state:
- layout class
- mechanism
- positive exemplars
- negative exemplars
- why the heuristic should not fire on the negative set

### Pragmatist Inquiry (Peirce / Dewey)

The point is to resolve the felt reading problem, not merely reduce a counter.

Required evidence:
- the fixed manual review packet shows the target blocks read as coherent passage units
- sidecar excerpts and page images support that judgment

### Social Epistemology (Goldman / Longino)

The gate must test the change from hostile angles, not only from the easiest query path.

Required evidence:
- adversarial retrieval slices do not regress
- table / index / simple-prose negative controls remain stable

### Information Content (Bayesian)

Claims of improvement must expose deltas, not selected wins.

Required evidence:
- report baseline vs current deltas
- show score margins where available
- treat regressions and ambiguous movement as evidence, not noise

### Empirical Adequacy (van Fraassen)

Even an inelegant heuristic is acceptable if it keeps the bundle predictions true.

Required evidence:
- audit predictions hold
- regression predictions hold
- retrieval predictions hold
- embedding predictions hold

## Operating Rules

1. Freeze the current accepted bundle into baseline summaries before the next heuristic.
2. Keep the quality gate on `why-ethics` until the target layout class is stable.
3. Keep `runtime_gates` explicit in the gate config:
   - `embedding_timeout_seconds`
   - `embedding_retries`
   - `stability_runs`
4. Treat `gate-runtime.json` and `embedding-runtime.json` as first-class evidence, not as debug leftovers.
5. Treat `Citation`, `Commentary`, and `Reference Notes` as the primary truth units.
6. Do not broaden page geometry extraction during this phase.
7. Limit the next extractor wave to the unresolved `why-comment` `7c` / `7d` inset-quote
   class and add anchored regressions before patching it.

## Gate Outcomes

- `pass`: every enforced gate passed
- `fail`: at least one enforced gate failed
- `report-only`: evidence tracked but not yet elevated to a veto

The manual review packet is currently report-only in the frozen baseline because the
unresolved `7c` / `7d` class is intentionally still present. Once that class is fixed,
promote the packet acceptance rule to an enforced gate.
