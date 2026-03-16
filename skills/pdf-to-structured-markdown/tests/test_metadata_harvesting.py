from __future__ import annotations

import sys
import unittest
from pathlib import Path


TESTS_DIR = Path(__file__).resolve().parent
if str(TESTS_DIR) not in sys.path:
    sys.path.insert(0, str(TESTS_DIR))

from helpers import load_fixture, load_script_module


convert_pdf = load_script_module("convert_pdf")


class MetadataHarvestingTests(unittest.TestCase):
    def test_real_book_frontmatter_cases(self) -> None:
        fixture = load_fixture("metadata_cases.json")
        for case in fixture["cases"]:
            with self.subTest(case=case["id"]):
                citation = convert_pdf.build_citation_metadata(case["layout_pages"])
                expected = case["expected"]
                self.assertEqual(citation["title"], expected["title"])
                self.assertEqual(citation["authors"], expected["authors"])
                self.assertEqual(citation["publisher"], expected["publisher"])
                self.assertEqual(citation["publication_year"], expected["publication_year"])
                contributors = [
                    {"name": item["name"], "role": item["role"]}
                    for item in citation.get("contributors", [])
                ]
                for contributor in expected["contributors"]:
                    self.assertIn(contributor, contributors)
                if "must_not_match_author_catalog_entry" in case:
                    catalog_entry = citation.get("cataloging_source", {}).get("author_catalog_entry")
                    self.assertNotEqual(
                        catalog_entry,
                        case["must_not_match_author_catalog_entry"],
                    )


if __name__ == "__main__":
    unittest.main()
