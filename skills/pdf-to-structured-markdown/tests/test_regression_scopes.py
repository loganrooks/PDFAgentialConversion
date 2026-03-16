from __future__ import annotations

import sys
import unittest
from pathlib import Path
import json


TESTS_DIR = Path(__file__).resolve().parent
if str(TESTS_DIR) not in sys.path:
    sys.path.insert(0, str(TESTS_DIR))

from helpers import load_fixture, load_script_module


check_regressions = load_script_module("check_regressions")
evaluate_retrieval = load_script_module("evaluate_retrieval")


class RegressionScopeTests(unittest.TestCase):
    def test_why_ethics_regression_spec_includes_phase06_targets(self) -> None:
        spec = json.loads(
            (
                TESTS_DIR.parent
                / "references"
                / "why-ethics-regressions.json"
            ).read_text(encoding="utf-8")
        )
        targets = {
            (check["scope"].get("label"), check["scope"].get("block"))
            for check in spec["checks"]
            if check["path"].endswith("chapter-05-why-comment__section-c-commentaries__pp-123-130.md")
        }
        self.assertIn(("7c", "Citation"), targets)
        self.assertIn(("7c", "Commentary"), targets)
        self.assertIn(("7d", "Commentary"), targets)

    def test_repeated_label_scope_resolves_requested_block(self) -> None:
        text = """## Passage 001 (1d)
Label: 1d

### Citation

Citation text.

## Passage 002 (1d)
Label: 1d

### Commentary

Commentary text.
"""
        scoped_text, scope_label = check_regressions.resolve_scope_text(
            text,
            {"kind": "rag_passage", "label": "1d", "block": "Commentary"},
        )
        self.assertEqual(scope_label, "rag_passage:{'kind': 'rag_passage', 'label': '1d', 'block': 'Commentary'}")
        self.assertEqual(scoped_text, "Commentary text.\n")

    def test_why_ethics_retrieval_characterization_cases_group_by_run(self) -> None:
        fixture = load_fixture("why_ethics_holdout_cases.json")["retrieval_drift"]["regressed_runs"]
        results = []
        for run_id, run in fixture.items():
            corpus, profile = run_id.split("::", 1)
            for case in run["cases"]:
                results.append(case | {"corpus": corpus, "profile": profile})

        diagnostics = evaluate_retrieval.build_run_case_diagnostics(results)

        self.assertEqual(set(diagnostics.keys()), set(fixture.keys()))
        for run_id, run in fixture.items():
            with self.subTest(run_id=run_id):
                diag = diagnostics[run_id]
                expected_case_keys = {f"{case['case_id']}::{case['probe_id']}" for case in run["cases"]}
                self.assertEqual(diag["miss_count"], len(run["cases"]))
                self.assertEqual(
                    {case["case_key"] for case in diag["cases"]},
                    expected_case_keys,
                )
                self.assertTrue(all(case["top_result_is_gold"] is False for case in diag["cases"]))

    def test_why_ethics_retrieval_fixture_preserves_regressed_metric_pairs(self) -> None:
        fixture = load_fixture("why_ethics_holdout_cases.json")["retrieval_drift"]["regressed_runs"]
        fielded = fixture["spatial_main_plus_supplement::fielded_bm25"]
        chargram = fixture["spatial_main_plus_supplement::chargram_tfidf"]

        self.assertLess(
            fielded["current_summary"]["mean_reciprocal_rank"],
            fielded["baseline_summary"]["mean_reciprocal_rank"],
        )
        self.assertLess(
            fielded["current_summary"]["hit_at_1"],
            fielded["baseline_summary"]["hit_at_1"],
        )
        self.assertLess(
            chargram["current_summary"]["mean_reciprocal_rank"],
            chargram["baseline_summary"]["mean_reciprocal_rank"],
        )

    def test_explicit_table_heading_augments_spatial_retrieval_context(self) -> None:
        payload = {
            "pages": [
                {
                    "regions": [
                        {"semantic_text": "- Relation"},
                        {"semantic_text": "- TABLE 2. Pragmatic Social Logics"},
                    ]
                }
            ]
        }
        heading = evaluate_retrieval.sidecar_table_heading(payload)
        self.assertEqual(heading, "TABLE 2. Pragmatic Social Logics")
        self.assertEqual(
            evaluate_retrieval.merge_retrieval_context(
                "Part 02 > Chapter 03 > E. Unjust Judgment",
                heading,
            ),
            "Part 02 > Chapter 03 > E. Unjust Judgment > TABLE 2. Pragmatic Social Logics",
        )


if __name__ == "__main__":
    unittest.main()
