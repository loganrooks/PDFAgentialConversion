from __future__ import annotations

import os
import sys
import unittest
import json
from pathlib import Path
from unittest.mock import patch


TESTS_DIR = Path(__file__).resolve().parent
if str(TESTS_DIR) not in sys.path:
    sys.path.insert(0, str(TESTS_DIR))

from helpers import load_fixture, load_script_module


convert_pdf = load_script_module("convert_pdf")
probe_artifacts = load_script_module("probe_artifacts")
render_review_packet = load_script_module("render_review_packet")


class ProseFragmentRepairTests(unittest.TestCase):
    def setUp(self) -> None:
        self.cases = {
            case["id"]: case
            for case in load_fixture("prose_fragment_cases.json")["cases"]
        }
        self.holdout_cases = load_fixture("why_ethics_holdout_cases.json")
        self.cross_book_cases = load_fixture("cross_book_remaining_cases.json")

    def test_phase06_manual_packet_targets_explicitly_cover_7c_and_7d(self) -> None:
        config = json.loads(
            (
                TESTS_DIR.parent
                / "references"
                / "why-ethics-quality-gate.json"
            ).read_text(encoding="utf-8")
        )
        entries = {entry["scope_id"]: entry for entry in config["manual_sample"]["entries"]}
        self.assertIn("target-7c-citation", entries)
        self.assertIn("target-7c-commentary", entries)
        self.assertIn("target-7d-commentary", entries)
        self.assertEqual(entries["target-7c-citation"]["verdict"], "pass")
        self.assertEqual(entries["target-7c-commentary"]["verdict"], "pass")
        self.assertEqual(entries["target-7d-commentary"]["verdict"], "pass")
        self.assertIn("control-table-page-122", entries)
        self.assertIn("holdout-why-speak-1d-citation", entries)

    def test_phase06_review_packet_matches_repaired_targets(self) -> None:
        packet_path = (
            TESTS_DIR.parents[2]
            / "generated"
            / "why-ethics"
            / "quality-gate"
            / "review-packet.json"
        )
        if not packet_path.exists():
            with patch.object(
                sys,
                "argv",
                [
                    "render_review_packet.py",
                    str(TESTS_DIR.parents[2] / "generated" / "why-ethics"),
                    str(
                        TESTS_DIR.parent
                        / "references"
                        / "why-ethics-quality-gate.json"
                    ),
                ],
            ):
                render_review_packet.main()
        packet = json.loads(
            packet_path.read_text(encoding="utf-8")
        )
        by_scope_id = {sample["scope_id"]: sample for sample in packet["entries"]}
        self.assertEqual(by_scope_id["target-7c-citation"]["verdict"], "pass")
        self.assertEqual(by_scope_id["target-7c-commentary"]["verdict"], "pass")
        self.assertEqual(by_scope_id["target-7d-commentary"]["verdict"], "pass")
        self.assertEqual(by_scope_id["holdout-why-speak-1d-citation"]["verdict"], "pass")
        self.assertEqual(by_scope_id["control-table-page-122"]["verdict"], "pass")

    def test_why_comment_inset_quote_handler_rebuckets_quote_and_tail_regions(self) -> None:
        entry = convert_pdf.TocEntry(
            id="commentaries",
            kind="section",
            level=3,
            title="C. Commentaries",
            page_label="123",
            numbering="arabic",
            output_path="body/part-01-attending-the-future/chapter-05-why-comment/c-commentaries.md",
        )
        spatial_pages = [
            {
                "page_label": "127",
                "regions": [
                    {"region_id": "r31", "raw_text": "8) Erubin 13b", "bbox": {"x0": 228.0, "x1": 282.0, "y0": 323.7, "y1": 332.2}},
                    {"region_id": "r32", "raw_text": "R. Abba said that Samuel said: For three years Beth", "bbox": {"x0": 228.0, "x1": 360.1, "y0": 323.7, "y1": 342.2}},
                    {"region_id": "r38", "raw_text": "Both can be right, but THE RULING will", "bbox": {"x0": 36.0, "x1": 216.0, "y0": 358.2, "y1": 368.6}},
                    {"region_id": "r58", "raw_text": "dence. Levinas satisfies his reader with a", "bbox": {"x0": 36.0, "x1": 216.0, "y0": 478.6, "y1": 488.6}},
                    {"region_id": "r68", "raw_text": "7d) Discussion or dialectic which", "bbox": {"x0": 36.0, "x1": 167.9, "y0": 557.7, "y1": 566.2}},
                ],
            },
            {
                "page_label": "129",
                "regions": [
                    {"region_id": "r02", "raw_text": "SUGGESTED READINGS", "bbox": {"x0": 36.0, "x1": 133.6, "y0": 111.8, "y1": 122.8}},
                    {"region_id": "r03", "raw_text": "Aronowicz, Annette. “Translator’s Introduction”", "bbox": {"x0": 51.0, "x1": 360.1, "y0": 131.3, "y1": 195.3}},
                ],
            },
        ]

        repaired = convert_pdf.repair_why_comment_inset_quote_spatial_pages(entry, spatial_pages)
        page127 = {region["region_id"]: region for region in repaired[0]["regions"]}
        page129 = {region["region_id"]: region for region in repaired[1]["regions"]}

        self.assertEqual(page127["r31"]["forced_rag_bucket"], "reference")
        self.assertEqual(page127["r32"]["forced_rag_bucket"], "reference")
        self.assertEqual(page127["r38"]["forced_rag_bucket"], "commentary")
        self.assertEqual(page127["r58"]["forced_rag_bucket"], "commentary")
        self.assertEqual(page129["r02"]["forced_rag_bucket"], "reference")
        self.assertEqual(page129["r03"]["forced_rag_bucket"], "reference")

    def test_why_comment_inset_quote_handler_leaves_holdout_entries_untouched(self) -> None:
        entry = convert_pdf.TocEntry(
            id="holdout",
            kind="section",
            level=3,
            title="A. The Saying",
            page_label="48",
            numbering="arabic",
            output_path="body/part-01-attending-the-future/chapter-02-why-speak/a-the-saying.md",
        )
        spatial_pages = [
            {
                "page_label": "50",
                "regions": [
                    {"region_id": "r01", "raw_text": "The elements of this mosaic are already placed", "bbox": {"x0": 36.0, "x1": 360.0, "y0": 58.0, "y1": 90.0}},
                ],
            }
        ]
        repaired = convert_pdf.repair_why_comment_inset_quote_spatial_pages(entry, spatial_pages)
        self.assertNotIn("forced_rag_bucket", repaired[0]["regions"][0])

    def test_top_margin_filter_keeps_real_body_text(self) -> None:
        keep_case = self.cases["top-margin-body-line-control"]
        skip_case = self.cases["running-header-control"]
        late_skip_case = self.cases["running-header-late-control"]
        self.assertEqual(
            convert_pdf.should_skip_top_margin_line(
                keep_case["line"]["text"],
                keep_case["line"]["y0"],
            ),
            keep_case["expected_skip"],
        )
        self.assertEqual(
            convert_pdf.should_skip_top_margin_line(
                skip_case["line"]["text"],
                skip_case["line"]["y0"],
            ),
            skip_case["expected_skip"],
        )
        self.assertEqual(
            convert_pdf.should_skip_top_margin_line(
                late_skip_case["line"]["text"],
                late_skip_case["line"]["y0"],
            ),
            late_skip_case["expected_skip"],
        )

    def test_split_heading_band_handles_same_baseline_fragments(self) -> None:
        case = self.cases["split-heading-b-language"]
        band = convert_pdf.detect_heading_band_from_lines(case["line_items"], set(case["skip_keys"]))
        self.assertIsNotNone(band)
        assert band is not None
        self.assertAlmostEqual(band[0], case["expected_band"][0], places=1)
        self.assertAlmostEqual(band[1], case["expected_band"][1], places=1)

    def test_split_heading_band_handles_stacked_title_lines(self) -> None:
        line_items = [
            {"text": "uttered) liberates the future of a general grammatology", "x0": 54.0, "y0": 50.0, "x1": 360.0, "y1": 88.0},
            {"text": "The Outside", "x0": 258.0, "y0": 102.0, "x1": 338.0, "y1": 114.0},
            {"text": "and the Inside *", "x0": 258.0, "y0": 115.0, "x1": 352.0, "y1": 127.0},
            {"text": "On the one hand, true to the Western tradition", "x0": 54.0, "y0": 130.0, "x1": 360.0, "y1": 164.0},
        ]
        band = convert_pdf.detect_heading_band_from_lines(
            line_items,
            set(),
            prefix_variants=["The Outside and the Inside"],
            mode="hybrid",
        )
        self.assertIsNotNone(band)
        assert band is not None
        self.assertLess(band[0], 105.0)
        self.assertGreater(band[1], 126.0)

    def test_duplicate_boundary_cleanup_only_fires_for_duplicate_mode(self) -> None:
        case = self.cases["duplicate-boundary-control"]
        self.assertEqual(
            convert_pdf.join_continued_rag_text(case["left"], case["right"], "space"),
            case["expected_space"],
        )
        self.assertEqual(
            convert_pdf.join_continued_rag_text(case["left"], case["right"], "duplicate"),
            case["expected_duplicate"],
        )

    def test_duplicate_boundary_lead_suppression_preserves_non_duplicate_text(self) -> None:
        self.assertEqual(
            convert_pdf.suppress_duplicate_boundary_lead("EFFACED IN ITS OWN PRODUCTION. The", "the signified functions always already"),
            "signified functions always already",
        )
        self.assertEqual(
            convert_pdf.suppress_duplicate_boundary_lead("A complete sentence.", "Another sentence."),
            "Another sentence.",
        )

    def test_hyphenated_region_pair_is_joinable(self) -> None:
        case = self.cases["hyphen-join-positive"]
        decision = convert_pdf.assess_prose_region_join(case["previous"], case["current"], content_mode="prose")
        self.assertIsNotNone(decision)
        assert decision is not None
        self.assertEqual(decision["join_mode"], case["expected_join_mode"])

    def test_note_apparatus_pair_is_not_joined_as_prose(self) -> None:
        case = self.cases["note-apparatus-negative"]
        decision = convert_pdf.assess_prose_region_join(case["previous"], case["current"], content_mode="prose")
        self.assertIsNone(decision)

    def test_notes_page_is_reclassified_out_of_prose(self) -> None:
        case = self.cases["notes-page-reclassify"]
        mode = convert_pdf.infer_page_content_mode(
            case["entry_kind"],
            case["entry_title"],
            case["layout_kind"],
            case["regions"],
        )
        self.assertEqual(mode, case["expected_content_mode"])

    def test_clean_page_stays_prose(self) -> None:
        case = self.cases["specters-clean-page-control"]
        mode = convert_pdf.infer_page_content_mode(
            case["entry_kind"],
            case["entry_title"],
            case["layout_kind"],
            case["regions"],
        )
        self.assertEqual(mode, case["expected_content_mode"])

    def test_balanced_boundary_mode_matches_numbered_heading_line(self) -> None:
        with patch.dict(os.environ, {"PDFMD_BOUNDARY_OVERLAP_MODE": "balanced"}, clear=False):
            match = convert_pdf.classify_heading_line(
                "3. THE SELF",
                set(),
                prefix_variants=["The Self"],
            )
        self.assertIsNotNone(match)
        assert match is not None
        self.assertEqual(match["match_type"], "variant")
        self.assertEqual(match["remainder"], "")

    def test_balanced_boundary_mode_matches_fuzzy_ocr_heading_line(self) -> None:
        with patch.dict(os.environ, {"PDFMD_BOUNDARY_OVERLAP_MODE": "balanced"}, clear=False):
            match = convert_pdf.classify_heading_line(
                "d. The Responsible Subject that is not Absorbeud in Being",
                set(),
                prefix_variants=["d. The Responsible Subject that is not Absorbed in Being"],
            )
        self.assertIsNotNone(match)
        assert match is not None
        self.assertEqual(match["match_type"], "fuzzy_variant")

    def test_aggressive_boundary_mode_preserves_inline_heading_tail(self) -> None:
        with patch.dict(os.environ, {"PDFMD_BOUNDARY_OVERLAP_MODE": "aggressive"}, clear=False):
            match = convert_pdf.classify_heading_line(
                "The Interval and the Supplement. The themes of the first eleven chapters...",
                set(),
                prefix_variants=["The Interval and the Supplement"],
            )
        self.assertIsNotNone(match)
        assert match is not None
        self.assertEqual(match["match_type"], "inline_variant")
        self.assertTrue(match["remainder"].startswith("The themes of the first eleven"))

    def test_hybrid_boundary_mode_preserves_inline_heading_tail(self) -> None:
        with patch.dict(os.environ, {"PDFMD_BOUNDARY_OVERLAP_MODE": "hybrid"}, clear=False):
            match = convert_pdf.classify_heading_line(
                "The Interval and the Supplement. The themes of the first eleven chapters...",
                set(),
                prefix_variants=["The Interval and the Supplement"],
            )
        self.assertIsNotNone(match)
        assert match is not None
        self.assertEqual(match["match_type"], "inline_variant")
        self.assertTrue(match["remainder"].startswith("The themes of the first eleven"))

    def test_aggressive_boundary_mode_trims_short_leading_prelude_regions(self) -> None:
        regions = [
            {
                "region_id": "r01",
                "bbox": {"y1": 88.0},
                "raw_text": "the confusion between",
                "semantic_text": "the confusion between",
            },
            {
                "region_id": "r02",
                "bbox": {"y1": 88.0},
                "raw_text": "Being and entities, speaks of",
                "semantic_text": "Being and entities, speaks of",
            },
            {
                "region_id": "r03",
                "bbox": {"y1": 160.0},
                "raw_text": "To affirm that this mutation in the amphibology of being and entities is not to reduce the difference.",
                "semantic_text": "To affirm that this mutation in the amphibology of being and entities is not to reduce the difference.",
            },
        ]
        with patch.dict(os.environ, {"PDFMD_BOUNDARY_OVERLAP_MODE": "aggressive"}, clear=False):
            trimmed = convert_pdf.trim_leading_prelude_regions(regions)
        self.assertEqual(len(trimmed), 1)
        self.assertEqual(trimmed[0]["region_id"], "r03")

    def test_probe_limits_lowercase_and_dangling_checks_to_leaf_boundaries(self) -> None:
        blocks = [
            {
                "kind": "Commentary",
                "body": "lowercase opening on a full unsliced first page.",
                "content_mode": "prose",
                "scope_suggestion": {"kind": "rag_passage", "index": 1, "block": "Commentary"},
                "token_count": 7,
                "is_first_commentary": True,
                "is_last_commentary": False,
            },
            {
                "kind": "Commentary",
                "body": "middle passage ending in of the",
                "content_mode": "prose",
                "scope_suggestion": {"kind": "rag_passage", "index": 2, "block": "Commentary"},
                "token_count": 6,
                "is_first_commentary": False,
                "is_last_commentary": False,
            },
            {
                "kind": "Commentary",
                "body": "Final passage ending in of the",
                "content_mode": "prose",
                "scope_suggestion": {"kind": "rag_passage", "index": 3, "block": "Commentary"},
                "token_count": 6,
                "is_first_commentary": False,
                "is_last_commentary": True,
            },
        ]
        issues = probe_artifacts.rag_block_issues(
            blocks,
            "rag/example.md",
            first_page_sliced_start=False,
            last_page_sliced_end=False,
        )
        self.assertEqual(
            [issue["code"] for issue in issues],
            ["rag_block_lowercase_start", "rag_block_dangling_end"],
        )

    def test_probe_suppresses_sliced_leaf_boundary_noise_and_legitimate_you_you(self) -> None:
        blocks = [
            {
                "kind": "Commentary",
                "body": "lowercase opening on a sliced first page.",
                "content_mode": "prose",
                "scope_suggestion": {"kind": "rag_passage", "index": 1, "block": "Commentary"},
                "token_count": 7,
                "is_first_commentary": True,
                "is_last_commentary": False,
            },
            {
                "kind": "Commentary",
                "body": "Final passage ending in of the",
                "content_mode": "prose",
                "scope_suggestion": {"kind": "rag_passage", "index": 2, "block": "Commentary"},
                "token_count": 6,
                "is_first_commentary": False,
                "is_last_commentary": True,
            },
        ]
        issues = probe_artifacts.rag_block_issues(
            blocks,
            "rag/example.md",
            first_page_sliced_start=True,
            last_page_sliced_end=True,
        )
        self.assertEqual(issues, [])
        repeated = probe_artifacts.repeated_word_issues(
            "they tell you you are not there alone",
            "body/example.md",
            content_mode="prose",
            scope_suggestion={"kind": "semantic_page", "page_label": "196", "pdf_page": 280},
        )
        self.assertEqual(repeated, [])

    def test_reference_note_continuation_requires_same_band(self) -> None:
        flattened = [
            {
                "pdf_page": 109,
                "zone": "left",
                "x0": 36.0,
                "x1": 108.0,
                "y0": 539.0,
                "y1": 574.0,
                "rag_text": "sional withdrawal.3 3 Levinas OB 8/7",
            },
            {
                "pdf_page": 109,
                "zone": "center",
                "x0": 36.0,
                "x1": 360.0,
                "y0": 566.0,
                "y1": 584.0,
                "rag_text": "A methodological problem is posed here.",
            },
        ]
        annotated = convert_pdf.annotate_reference_note_continuations(flattened)
        self.assertTrue(annotated[0].get("reference_note_seed"))
        self.assertFalse(annotated[1].get("reference_note_continuation", False))

    def test_reference_note_continuation_accepts_same_baseline_note_body(self) -> None:
        flattened = [
            {
                "pdf_page": 141,
                "zone": "left",
                "x0": 46.36,
                "x1": 116.18,
                "y0": 541.3,
                "y1": 552.11,
                "rag_text": "6 Derrida WD 99/64",
            },
            {
                "pdf_page": 141,
                "zone": "center",
                "x0": 36.36,
                "x1": 360.42,
                "y0": 544.1,
                "y1": 572.11,
                "rag_text": "It concerns a certain Judaism as birth and passion of writing.",
            },
        ]
        annotated = convert_pdf.annotate_reference_note_continuations(flattened)
        self.assertTrue(annotated[0].get("reference_note_seed"))
        self.assertTrue(annotated[1].get("reference_note_continuation", False))

    def test_bibliography_tail_moves_from_commentary_into_reference_notes(self) -> None:
        passages = convert_pdf.repair_passage_commentary_boundaries(
            [
                {
                    "passage_id": "8d",
                    "label": "8d",
                    "citation_parts": ["Citation paragraph."],
                    "commentary_parts": [
                        "Commentary paragraph.",
                        "Cornell, Drucilla. The Philosophy of the Limit, 91–115. New York: Routledge, 1992. McCarthy, Thomas. Ideals and Illusions, 181–99. Cambridge, Mass.: MIT",
                        "Honneth, Axel. The Other of Justice",
                    ],
                    "reference_parts": [
                        "Postmodernism. In The Cambridge Companion to Habermas.",
                        "Press, 1991.",
                        "Minnesota Press, 1988.",
                    ],
                    "page_labels": ["154", "155"],
                    "pdf_pages": [171, 172],
                }
            ]
        )
        self.assertEqual(passages[0]["commentary_parts"], ["Commentary paragraph."])
        self.assertTrue(passages[0]["reference_parts"][0].startswith("Cornell, Drucilla."))
        self.assertTrue(passages[0]["reference_parts"][1].startswith("Honneth, Axel."))

    def test_why_ethics_probe_characterization_cases_keep_stable_issue_keys(self) -> None:
        holdout = self.holdout_cases["probe_drift"]
        grouped = probe_artifacts.summarize_issue_cases(holdout["cases"])

        self.assertEqual(
            set(grouped.keys()),
            {"rag_block_dangling_end", "rag_block_lowercase_start", "repeated_adjacent_word"},
        )

        for case in holdout["cases"]:
            with self.subTest(issue_key=case["issue_key"]):
                self.assertEqual(probe_artifacts.issue_case_key(case), case["issue_key"])
                grouped_keys = {item["issue_key"] for item in grouped[case["code"]]}
                self.assertIn(case["issue_key"], grouped_keys)

    def test_why_ethics_probe_fixture_records_only_over_cap_codes(self) -> None:
        holdout = self.holdout_cases["probe_drift"]
        baseline = holdout["baseline_issue_summary"]
        current = holdout["current_issue_summary"]

        self.assertGreater(current["repeated_adjacent_word"], baseline["repeated_adjacent_word"])
        self.assertGreater(
            current["rag_block_lowercase_start"],
            baseline["rag_block_lowercase_start"],
        )
        self.assertGreater(
            current["rag_block_dangling_end"],
            baseline["rag_block_dangling_end"],
        )
        self.assertNotIn("boundary_page_many_micro_regions", current)

    def test_cross_book_probe_cases_keep_stable_issue_keys(self) -> None:
        for book_name, packet in self.cross_book_cases.items():
            with self.subTest(book=book_name):
                grouped = probe_artifacts.summarize_issue_cases(packet["probe_cases"])
                self.assertEqual(
                    set(grouped.keys()),
                    set(packet["probe_issue_summary"].keys()),
                )
                for case in packet["probe_cases"]:
                    with self.subTest(book=book_name, issue_key=case["issue_key"]):
                        self.assertEqual(probe_artifacts.issue_case_key(case), case["issue_key"])
                        details = probe_artifacts.issue_case_details(case)
                        self.assertEqual(details["code"], case["code"])
                        grouped_keys = {item["issue_key"] for item in grouped[case["code"]]}
                        self.assertIn(case["issue_key"], grouped_keys)

    def test_cross_book_probe_fixture_tracks_only_phase05_target_codes(self) -> None:
        allowed_codes = {
            "rag_block_lowercase_start",
            "rag_block_dangling_end",
            "rag_block_hyphen_end",
            "repeated_adjacent_word",
        }
        for book_name, packet in self.cross_book_cases.items():
            with self.subTest(book=book_name):
                self.assertEqual(set(packet["probe_issue_summary"].keys()), allowed_codes)
                self.assertTrue(packet["probe_cases"])


if __name__ == "__main__":
    unittest.main()
