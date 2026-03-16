from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path


TESTS_DIR = Path(__file__).resolve().parent
if str(TESTS_DIR) not in sys.path:
    sys.path.insert(0, str(TESTS_DIR))

from helpers import load_fixture, load_script_module


audit_bundle = load_script_module("audit_bundle")


class RangeNormalizationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.cross_book_cases = load_fixture("cross_book_remaining_cases.json")

    def write_sidecar(self, root: Path, relative_path: str, pdf_page: int, field: str) -> None:
        full_path = root / relative_path
        full_path.parent.mkdir(parents=True, exist_ok=True)
        full_path.write_text(
            json.dumps({"pages": [{"pdf_page": pdf_page, field: 120.0}]}, indent=2),
            encoding="utf-8",
        )

    def test_boundary_overlap_is_allowed_when_both_slices_are_present(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            left = {"pdf_page_end": 10, "spatial_output_path": "spatial/left.json"}
            right = {"pdf_page_start": 10, "spatial_output_path": "spatial/right.json"}
            self.write_sidecar(root, "spatial/left.json", 10, "slice_max_y")
            self.write_sidecar(root, "spatial/right.json", 10, "slice_min_y")
            self.assertTrue(audit_bundle.is_intentional_boundary_overlap(root, left, right))

    def test_identical_or_nested_overlap_is_structurally_invalid(self) -> None:
        left = {"pdf_page_start": 5, "pdf_page_end": 12}
        identical = {"pdf_page_start": 5, "pdf_page_end": 12}
        nested = {"pdf_page_start": 7, "pdf_page_end": 11}
        adjacent = {"pdf_page_start": 12, "pdf_page_end": 15}
        self.assertEqual(audit_bundle.classify_leaf_range_overlap(left, identical), "identical")
        self.assertEqual(audit_bundle.classify_leaf_range_overlap(left, nested), "nested")
        self.assertEqual(audit_bundle.classify_leaf_range_overlap(left, adjacent), "boundary")

    def test_cross_book_overlap_packet_tracks_current_boundary_warnings(self) -> None:
        for book_name, packet in self.cross_book_cases.items():
            for issue in packet["structural_issues"]:
                with self.subTest(book=book_name, left=issue["left_path"], right=issue["right_path"]):
                    self.assertEqual(issue["code"], "overlapping_leaf_ranges")
                    self.assertNotEqual(issue["left_path"], issue["right_path"])
                    self.assertEqual(
                        audit_bundle.classify_leaf_range_overlap(
                            issue["left_range"],
                            issue["right_range"],
                        ),
                        issue["expected_overlap_kind"],
                    )


if __name__ == "__main__":
    unittest.main()
