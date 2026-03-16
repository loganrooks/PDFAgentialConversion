# External Integrations

**Analysis Date:** 2026-03-15

## APIs & External Services

- Apple `NaturalLanguage` is reached indirectly through `skills/pdf-to-structured-markdown/scripts/apple_nl_embed.swift` and `skills/pdf-to-structured-markdown/scripts/apple_nl_similarity.swift`
- Optional remote embedding experiments use SSH targets declared in `skills/pdf-to-structured-markdown/references/remote-backends.json`
- The configured remote backend currently names a Tailscale-accessible host `dionysus`
- Remote model execution depends on Hugging Face model downloads such as `BAAI/bge-small-en-v1.5`, `BAAI/bge-base-en-v1.5`, and `intfloat/e5-base-v2`

## Data Storage

- Source PDFs live in the repository root, for example `Gibbs_WhyEthics.pdf` and the challenge-corpus books
- Generated bundles, reports, and manifests live under `generated/`
- Frozen baselines and reference configs live under `skills/pdf-to-structured-markdown/references/`
- Project planning state lives under `.planning/`

## Authentication & Identity

- There is no user auth, service auth, or app identity layer in the product code
- Remote experiment identity is delegated to the local SSH configuration and whatever keys or agent setup the operator already has
- No secrets manager, token broker, or credential rotation workflow exists in the repository

## Monitoring & Observability

- Every major runtime flow emits JSON artifacts, usually paired with a `run-manifest.json`
- Local health reporting is surfaced through `src/pdfmd/ops/status_snapshot.py` and `src/pdfmd/ops/doctor.py`
- Quality-gate, smoke, and backend-comparison outputs are written to stable report paths under `generated/`
- Artifact freshness and status are tracked in manifests rather than through an external observability platform

## CI/CD & Deployment

- No CI workflow or deployment config is present under `.github/`
- The repo is operated manually through `make` targets and direct script invocation
- `make map` delegates back into Codex with `codex exec`, so codebase-map refresh is also a local interactive workflow rather than automation in CI

## Environment Configuration

- Core runtime config is file-based, not environment-driven
- Reference JSON lives in `skills/pdf-to-structured-markdown/references/`
- Environment variables are limited and tactical: `PDFMD_VARIANT_ID`, `CUDA_VISIBLE_DEVICES`, and remote bootstrap markers in `src/pdfmd/benchmarks/remote_backends.py`
- Several modules still bake in the absolute project root, which is a portability concern for non-owner checkouts

## Webhooks & Callbacks

- No inbound webhooks or callback endpoints exist
- Remote comparison is pull-based over SSH and `rsync`, not event-driven
- All integrations are operator-triggered CLI workflows

---

*Integration analysis: 2026-03-15*
*Update after adding services, remote hosts, or artifact sinks*
