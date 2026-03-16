# Architecture

**Analysis Date:** 2026-03-15

## Pattern Overview

- Package-first CLI architecture: substantive logic lives under `src/pdfmd/`, while `skills/pdf-to-structured-markdown/scripts/` preserves the historical command surface
- Transitional compatibility layer: `src/pdfmd/cli/` mirrors command names but mostly re-exports from the real subsystem modules
- Artifact-driven workflow: conversion, quality gates, smoke checks, and backend comparisons all materialize reports and manifests under `generated/`
- Planning-driven operations: `.planning/STATE.md`, `.planning/ROADMAP.md`, and `.planning/codebase/` are part of the repo's operating model, not side documentation

## Layers

- Operator layer:
  - `Makefile`
  - `skills/pdf-to-structured-markdown/SKILL.md`
  - `skills/pdf-to-structured-markdown/scripts/*.py`
- Compatibility entrypoint layer:
  - `src/pdfmd/cli/*.py`
- Core shared services:
  - `src/pdfmd/common/paths.py`
  - `src/pdfmd/common/io.py`
  - `src/pdfmd/common/manifests.py`
  - `src/pdfmd/common/runtime.py`
- Domain subsystems:
  - `src/pdfmd/convert/` for bundle generation
  - `src/pdfmd/gates/` for audit, regressions, probes, review packets, and challenge-corpus runs
  - `src/pdfmd/benchmarks/` for retrieval, embedding-space evaluation, calibration, remote comparison, and variant comparison
  - `src/pdfmd/ops/` for status and doctor reporting
- Runtime and evidence layer:
  - `generated/`
  - `skills/pdf-to-structured-markdown/references/`
  - `.planning/`

## Data Flow

- Source PDF -> `src/pdfmd/convert/convert_pdf.py` -> bundle directory with `metadata.json`, `index.md`, `toc.md`, nested markdown, flat leaf exports, RAG exports, spatial sidecars, and `run-manifest.json`
- Generated bundle -> gate helpers in `src/pdfmd/gates/` -> audit, regression, probe, retrieval, embedding, and review artifacts under `generated/<book>/quality-gate/`
- Generated bundle -> `src/pdfmd/gates/challenge_corpus.py` -> corpus-wide smoke report and review packet under `generated/challenge-corpus/`
- Generated bundle plus benchmark config -> `src/pdfmd/benchmarks/embedding_space.py` and `src/pdfmd/benchmarks/remote_backends.py` -> local and remote comparison artifacts under `generated/embedding-backend-comparison/`
- Report artifacts -> `src/pdfmd/ops/status_snapshot.py` and `src/pdfmd/ops/doctor.py` -> compact project-health summaries for operators

## Key Abstractions

- `ProjectPaths` in `src/pdfmd/common/paths.py` centralizes repo paths for planning, references, scripts, and generated artifacts
- Manifest helpers in `src/pdfmd/common/manifests.py` normalize artifact metadata across bundle generation, quality gates, challenge corpus, and backend comparison
- Runtime probes in `src/pdfmd/common/runtime.py` isolate local toolchain checks and SSH-based remote environment checks
- `TocEntry` and the large helper set in `src/pdfmd/convert/convert_pdf.py` encode the conversion pipeline's core structural model
- `pdfmd.cli.quality_gate_common` is a cross-cutting utility layer shared by gate entrypoints for chunk diagnostics, JSON IO, and reference resolution

## Entry Points

- Top-level operator commands are defined in `Makefile`
- Stable wrapper commands live in `skills/pdf-to-structured-markdown/scripts/`
- Package entrypoints live in `src/pdfmd/cli/`
- Domain implementations live in:
  - `src/pdfmd/convert/convert_pdf.py`
  - `src/pdfmd/gates/quality_gate.py`
  - `src/pdfmd/gates/challenge_corpus.py`
  - `src/pdfmd/benchmarks/embedding_space.py`
  - `src/pdfmd/benchmarks/remote_backends.py`
  - `src/pdfmd/ops/status_snapshot.py`
  - `src/pdfmd/ops/doctor.py`

## Error Handling

- Command-line tools typically return exit codes and print JSON or formatted markdown/text reports instead of using a logging framework
- Subprocess-heavy flows classify runtime failures explicitly, especially timeouts and invalid JSON from child commands
- Config validation is mostly fail-fast with `ValueError` and required-field checks
- Status surfaces tolerate missing artifacts and downgrade to `missing`, `unknown`, or manifest-derived fallbacks rather than crashing the operator workflow

## Cross-Cutting Concerns

- Wrapper parity matters: the repo maintains both `skills/.../scripts` and `src/pdfmd/cli` command surfaces, with tests asserting they stay aligned
- Artifact freshness matters: most operator UX is derived from generated JSON reports, so stale artifacts can mislead if not regenerated
- Local vs remote boundary matters: the local Apple path is canonical, while the remote GPU path is intentionally non-authoritative
- Portability is mixed: newer shared path helpers are repo-relative, but several benchmark and gate modules still embed the owner's absolute workspace path
- Extraction complexity is still concentrated in a few very large modules, especially `src/pdfmd/convert/convert_pdf.py`

---

*Architecture analysis: 2026-03-15*
*Update after major subsystem moves or entrypoint changes*
