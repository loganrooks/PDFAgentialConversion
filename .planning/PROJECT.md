# PROJECT

## Name

PDFAgentialConversion

## What This Is

A local-first system for converting complex scholarly PDFs into structured markdown bundles, validating those bundles, and benchmarking retrieval and embedding behavior across canonical and out-of-sample books.

## Core Value

Make difficult PDFs operationally legible and reproducible without sacrificing structural rigor, retrieval quality, or auditability.

## Current State

- Shipped `v1.0` with a real GSD project scaffold, canonical operator surface, and tracked milestone history.
- The implementation now lives behind `src/pdfmd`, while the existing skill scripts remain backward-compatible wrappers.
- The canonical local `why-ethics` gate is green, Apple-backed, and stable across repeated runs.
- The challenge corpus is a hard non-regression gate, with `Specters of Marx` preserved as the clean negative control.
- The remote SSH/GPU host is available for measured experiments, but it remains report-only and outside canonical pass/fail.

## Validated In v1.0

- Repo health is understandable at a glance from root docs plus `make status`.
- Script wrappers stayed compatible while product code moved into `src/pdfmd`.
- `generated/` is treated as runtime output rather than the primary tracked audit surface.
- The canonical local verification path is Mac-first and Apple-embedding-backed.
- Verification tiers are explicit and operator-friendly.
- Manifest/schema drift is guarded by explicit tests.

## Next Milestone Goals

- Decide whether the next milestone should focus on extractor-quality expansion, remote backend evaluation, or workflow/tooling cleanup.
- Turn the remote backend path from dry-run infrastructure into measured comparison runs on `dionysus`.
- Resolve the external `make map` blockage and the milestone-helper completion drift so milestone tooling stays aligned with repo state.

## Constraints

- Local Apple embedding remains the hard canonical gate once stabilized.
- Generated bundles are runtime outputs, not the primary tracked audit surface.
- Existing CLI contracts under `skills/pdf-to-structured-markdown/scripts/` must remain backward-compatible.

---
*Last updated: 2026-03-16 after v1.0 milestone*
