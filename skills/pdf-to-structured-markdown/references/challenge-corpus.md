# Challenge Corpus

Use the challenge corpus to test whether the extractor generalizes beyond the frozen
`why-ethics` baseline.

## Purpose

The quality gate answers "did we regress the accepted baseline?" It does not answer
"does this heuristic travel to a different book?"

The challenge corpus is the second question.

## Current corpus

See [challenge-corpus.json](challenge-corpus.json).

These books are treated as out-of-sample:
- `Of Grammatology`
- `Specters of Marx`
- `Otherwise than Being`

## Workflow

Run:

```bash
python3 scripts/run_challenge_corpus.py references/challenge-corpus.json
python3 scripts/run_challenge_corpus.py references/challenge-corpus.json --gate-mode soft
```

The runner:
- converts each configured PDF into a bundle
- runs `audit_bundle.py`
- runs `probe_artifacts.py`
- runs a source-specific strict regression spec when one exists
- records chunk diagnostics
- compares against `references/baselines/challenge-corpus/smoke-report.json` when present
- writes a cross-book smoke report
- writes a report-only `review-packet.md` with one metadata sample, one ToC sample, and one largest-RAG-block sample per book
- emits per-book `gate_failures` so the same report shape works in both required `hard` mode and exploratory `soft` mode

## Interpretation

This runner is now a hard non-regression gate by default.

Use `--gate-mode soft` only when you want a report-only exploratory run for variant work or local diagnosis.

Use it to look for:
- converter crashes
- audit failures or unexpected warning patterns
- probe issue explosions on a new layout class
- chunk distributions that imply unusable RAG segmentation
- delta movement against the frozen challenge baseline
- signs that a recent heuristic only helped `why-ethics`

Do not freeze a new challenge-corpus baseline casually. Only do it when:
- the book converts stably
- its obvious local failures are understood
- there is a reason to maintain a book-specific benchmark or regression suite

## Current status

After Phase 05 cross-book closure:
- `Specters of Marx` is the clean negative control: metadata complete, audit clean, probe `0`, max atomic block `1584`.
- `Of Grammatology` is structurally clean and passes the hard gate with bounded residual probe surface: `5` total issues (`2` lowercase starts, `2` dangling ends, `1` hyphen end), max atomic block `1591`.
- `Otherwise than Being` passes the hard gate with only the expected audit warning class plus bounded residual probe surface: `6` total issues (`5` lowercase starts, `1` dangling end), max atomic block `1475`.

These residuals are accepted and enforced by the promoted hard-gate thresholds; they are visible, stable, and no longer the active project target.
