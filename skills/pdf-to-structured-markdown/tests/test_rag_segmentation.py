from __future__ import annotations

import sys
import unittest
from pathlib import Path


TESTS_DIR = Path(__file__).resolve().parent
if str(TESTS_DIR) not in sys.path:
    sys.path.insert(0, str(TESTS_DIR))

from helpers import load_fixture, load_script_module


convert_pdf = load_script_module("convert_pdf")
quality_gate_common = load_script_module("quality_gate_common")


class RagSegmentationTests(unittest.TestCase):
    def test_attach_fragment_to_next_anchor_handles_embedded_and_marker_only_cases(self) -> None:
        embedded_region = {
            "rag_text": "Horkheimer admits that the question of",
            "source_region_id": "r10",
            "zone": "center",
        }
        embedded_anchor = {
            "rag_text": "3a) Benjamin L 1332. Horkheimer",
            "source_region_id": "r10",
            "zone": "center",
        }
        marker_region = {
            "rag_text": "Horkheimer’s dialectic involves regard-",
            "source_region_id": "r23",
            "zone": "center",
        }
        short_cross_zone_region = {
            "rag_text": "It is not enough to see that in drawing",
            "source_region_id": "r03",
            "zone": "right",
        }
        marker_anchor = {
            "rag_text": "3b)",
            "source_region_id": "r24",
            "zone": "center",
        }
        clean_region = {
            "rag_text": "A complete sentence.",
            "source_region_id": "r30",
            "zone": "center",
        }
        too_long_region = {
            "rag_text": "This fragment is still incomplete but now it clearly runs too long to auto-attach",
            "source_region_id": "r40",
            "zone": "right",
        }

        self.assertEqual(
            convert_pdf.should_attach_fragment_to_next_anchor(
                embedded_region,
                embedded_anchor,
                distance_to_next_anchor=0.0,
            ),
            (True, "embedded-anchor-fragment"),
        )
        self.assertEqual(
            convert_pdf.should_attach_fragment_to_next_anchor(
                marker_region,
                marker_anchor,
                distance_to_next_anchor=1.1,
            ),
            (True, "marker-only-next-anchor"),
        )
        self.assertEqual(
            convert_pdf.should_attach_fragment_to_next_anchor(
                short_cross_zone_region,
                marker_anchor,
                distance_to_next_anchor=7.2,
            ),
            (True, "cross-zone-next-anchor"),
        )
        self.assertEqual(
            convert_pdf.should_attach_fragment_to_next_anchor(
                clean_region,
                marker_anchor,
                distance_to_next_anchor=1.1,
            ),
            (False, None),
        )
        self.assertEqual(
            convert_pdf.should_attach_fragment_to_next_anchor(
                too_long_region,
                marker_anchor,
                distance_to_next_anchor=7.2,
            ),
            (False, None),
        )

    def test_marker_only_anchor_handoff_marks_fragments_as_commentary(self) -> None:
        spatial_pages = [
            {
                "page_label": "342",
                "pdf_page": 359,
                "layout_kind": "aside",
                "content_mode": "prose",
                "regions": [
                    {
                        "region_id": "r01",
                        "role": "main",
                        "zone": "left",
                        "bbox": {"x0": 36.0, "y0": 60.0, "x1": 220.0, "y1": 78.0},
                        "raw_text": "2a) Benjamin P (N 8,1) 588–89/471 On the question of the lack of closure of history:",
                    },
                    {
                        "region_id": "r02",
                        "role": "aside",
                        "zone": "right",
                        "bbox": {"x0": 228.0, "y0": 92.0, "x1": 360.0, "y1": 210.0},
                        "raw_text": "In response to an essay by Benjamin, Horkheimer had written him a strongly supportive letter.",
                    },
                    {
                        "region_id": "r03",
                        "role": "main",
                        "zone": "center",
                        "bbox": {"x0": 48.0, "y0": 214.0, "x1": 360.0, "y1": 224.0},
                        "raw_text": "Horkheimer admits that the question of 3a) Benjamin L 1332. Horkheimer",
                    },
                    {
                        "region_id": "r04",
                        "role": "aside",
                        "zone": "right",
                        "bbox": {"x0": 228.0, "y0": 235.0, "x1": 360.0, "y1": 244.0},
                        "raw_text": "I have been pondering the question of how far the work of the past is closed for a long time.",
                    },
                    {
                        "region_id": "r05",
                        "role": "main",
                        "zone": "center",
                        "bbox": {"x0": 36.0, "y0": 394.0, "x1": 216.0, "y1": 404.0},
                        "raw_text": "Horkheimer’s dialectic involves regard-",
                    },
                    {
                        "region_id": "r06",
                        "role": "aside",
                        "zone": "center",
                        "bbox": {"x0": 228.0, "y0": 395.0, "x1": 240.0, "y1": 404.0},
                        "raw_text": "3b)",
                    },
                    {
                        "region_id": "r08",
                        "role": "aside",
                        "zone": "right",
                        "bbox": {"x0": 228.0, "y0": 401.0, "x1": 360.0, "y1": 520.0},
                        "raw_text": "The stipulation of the lack of closure is idealistic, if closure is not also admitted in it.",
                    },
                    {
                        "region_id": "r07",
                        "role": "main",
                        "zone": "left",
                        "bbox": {"x0": 36.0, "y0": 406.0, "x1": 216.0, "y1": 417.0},
                        "raw_text": "ing the past as both closed and not-closed.",
                    },
                ],
            }
        ]

        passages = convert_pdf.build_rag_passages(spatial_pages)
        by_label = {passage.get("label"): passage for passage in passages if passage.get("label")}

        self.assertNotIn("Horkheimer admits that the question of", "\n".join(by_label["2a"]["commentary_parts"]))
        self.assertIn("Horkheimer admits that the question of", "\n".join(by_label["3a"]["commentary_parts"]))
        self.assertIn(
            "Horkheimer’s dialectic involves regarding the past as both closed and not-closed.",
            convert_pdf.merge_rag_fragments(by_label["3b"]["commentary_parts"]),
        )

    def test_unanchored_commentary_is_split_into_bounded_pseudo_passages(self) -> None:
        case = next(
            item
            for item in load_fixture("rag_cases.json")["cases"]
            if item["id"] == "synthetic-unanchored-commentary"
        )
        expanded_passages = []
        for passage in case["passages"]:
            expanded_passages.append(
                {
                    **passage,
                    "commentary_parts": [
                        "\n\n".join([passage["commentary_parts"][0]] * int(case.get("repeat", 1)))
                    ],
                }
            )
        passages = convert_pdf.segment_unanchored_rag_passages(expanded_passages)
        self.assertGreater(len(passages), 1)
        for passage in passages:
            self.assertEqual(passage.get("segmentation_mode"), "pseudo-passage")
            commentary = convert_pdf.merge_rag_fragments(passage.get("commentary_parts", []))
            self.assertLessEqual(quality_gate_common.token_count(commentary), 1600)
            self.assertNotIn("<!--", commentary)

    def test_anchored_passages_are_not_resegmented(self) -> None:
        case = next(
            item
            for item in load_fixture("rag_cases.json")["cases"]
            if item["id"] == "anchored-long-citation-control"
        )
        passages = convert_pdf.segment_unanchored_rag_passages(case["passages"])
        self.assertEqual(len(passages), 1)
        self.assertEqual(passages[0].get("label"), "1a")
        self.assertIsNone(passages[0].get("segmentation_mode"))

    def test_anchored_multi_bucket_passage_stays_together_without_overflow(self) -> None:
        passages = convert_pdf.segment_unanchored_rag_passages(
            [
                {
                    "passage_id": "1b",
                    "label": "1b",
                    "source_ref": "",
                    "citation_parts": ["Citation paragraph."],
                    "commentary_parts": ["Commentary paragraph."],
                    "reference_parts": ["Levinas OB 8/7"],
                    "page_labels": ["69"],
                    "pdf_pages": [86],
                }
            ]
        )
        self.assertEqual(len(passages), 1)
        self.assertEqual(passages[0].get("label"), "1b")
        self.assertEqual(passages[0].get("citation_parts"), ["Citation paragraph."])
        self.assertEqual(passages[0].get("commentary_parts"), ["Commentary paragraph."])
        self.assertEqual(passages[0].get("reference_parts"), ["Levinas OB 8/7"])
        self.assertIsNone(passages[0].get("segmentation_mode"))

    def test_oversized_anchored_note_is_split_but_keeps_label(self) -> None:
        case = next(
            item
            for item in load_fixture("rag_cases.json")["cases"]
            if item["id"] == "anchored-oversized-note"
        )
        expanded_passages = []
        for passage in case["passages"]:
            expanded_passages.append(
                {
                    **passage,
                    "citation_parts": [
                        "\n\n".join([passage["citation_parts"][0]] * int(case.get("repeat", 1)))
                    ],
                }
            )
        passages = convert_pdf.segment_unanchored_rag_passages(expanded_passages)
        self.assertGreater(len(passages), 1)
        for passage in passages:
            self.assertEqual(passage.get("label"), "40t")
            self.assertEqual(passage.get("segmentation_mode"), "pseudo-passage")
            citation = convert_pdf.merge_rag_fragments(passage.get("citation_parts", []))
            self.assertLessEqual(quality_gate_common.token_count(citation), 1600)


if __name__ == "__main__":
    unittest.main()
