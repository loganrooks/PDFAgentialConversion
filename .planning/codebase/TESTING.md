# Testing Patterns

**Analysis Date:** 2026-03-15

## Test Framework

- Standard-library `unittest` is the canonical automated test framework
- Fast local verification is exposed through `make test-fast`
- Full local verification is exposed through `make test`
- Runtime acceptance layers are separate from the `unittest` suite and live behind:
  - `make gate`
  - `make smoke`
  - `make compare-backends`
  - `make status`
  - `make doctor`

## Test File Organization

- Automated tests live in `skills/pdf-to-structured-markdown/tests/`
- Fixtures live in `skills/pdf-to-structured-markdown/tests/fixtures/`
- High-value structural tests include:
  - `test_project_ops.py`
  - `test_wrapper_parity.py`
  - `test_remote_embedding_backends.py`
  - `test_page_mapping.py`
  - `test_toc_structure.py`
  - `test_rag_segmentation.py`
- Tests load script wrappers with `skills/pdf-to-structured-markdown/tests/helpers.py` to verify the public command surface, not just internal package imports

## Test Structure

- Tests are class-based `unittest.TestCase` suites
- `subTest()` is used to verify repeated wrapper/module invariants
- `tempfile.TemporaryDirectory()` is used heavily for isolated filesystem tests
- Many tests assert on generated JSON or manifest payloads rather than only return codes
- The suite mixes pure helper tests, wrapper-parity checks, report-generation checks, and small CLI-smoke execution paths

## Mocking

- `unittest.mock.patch` is the standard mocking tool
- Operator and runtime probes are faked with patched helpers in tests such as `test_project_ops.py`
- Remote embedding tests use fake `torch`, CUDA, and `sentence-transformers` shims instead of requiring real GPU hardware
- Stdout capture with `redirect_stdout` is used where CLI tools emit JSON directly

## Fixtures and Factories

- JSON fixtures cover metadata harvesting, prose fragment repair, RAG segmentation, ToC cases, and remote backend config validation
- Temporary directories stand in for generated bundles and report roots
- Tests often synthesize minimal `metadata.json`, `run-manifest.json`, and report files to exercise status and gate logic

## Coverage

- Strongest coverage is around extracted seams, wrapper parity, manifest validation, status/doctor reporting, and remote-backend dry-run logic
- Coverage is weaker around the full real-world converter path inside `src/pdfmd/convert/convert_pdf.py`
- Real Apple `NaturalLanguage` behavior, real SSH hosts, and real GPU execution are not covered by automated unit tests in this repo
- No coverage-reporting tool or threshold enforcement is configured

## Test Types

- Import and wrapper-surface tests
- Pure logic tests for metadata, ranges, ToC parsing, page mapping, and passage segmentation
- Artifact/report generation tests for manifests and status summaries
- Dry-run or simulated integration tests for remote backend comparison
- Manual runtime verification through the canonical gate, challenge corpus, and backend-comparison commands

## Common Patterns

- Preserve compatibility first: add or update wrapper-parity assertions when command surfaces move
- Add one positive and one negative fixture when changing a heuristic
- Treat frozen baselines under `skills/pdf-to-structured-markdown/references/baselines/` as part of the verification surface
- Do not treat `generated/` as the source of truth; treat it as evidence that must be regenerated and inspected
- No baseline or gate-threshold change should be accepted without repeated successful runs on the intended canonical path

---

*Testing analysis: 2026-03-15*
*Update after changing test runners, baseline strategy, or verification gates*
