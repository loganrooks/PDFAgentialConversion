from __future__ import annotations

import sys
import unittest
from collections import Counter
from pathlib import Path


TESTS_DIR = Path(__file__).resolve().parent
if str(TESTS_DIR) not in sys.path:
    sys.path.insert(0, str(TESTS_DIR))

from helpers import load_fixture, load_script_module


convert_pdf = load_script_module("convert_pdf")


class TocStructureTests(unittest.TestCase):
    def test_of_grammatology_title_only_toc_lines_are_retained_as_structure_entries(self) -> None:
        input_pdf = Path("/Users/rookslog/Projects/PDFAgentialConversion/Derrida_OfGrammatology.pdf")
        doc = convert_pdf.fitz.open(input_pdf)
        self.addCleanup(doc.close)
        layout_pages = convert_pdf.load_layout_pages(input_pdf, len(doc))
        toc_start, toc_end = convert_pdf.detect_toc_range(layout_pages)
        entries = convert_pdf.parse_toc_entries(layout_pages, toc_start, toc_end)
        titles = {entry.title for entry in entries}
        self.assertIn("The Signifier and Truth", titles)
        self.assertIn("The vVritten Being/The Being Written", titles)
        self.assertIn("2. Linguistics and Grammatology", titles)
        self.assertIn("The Outside and the Inside", titles)
        self.assertIn("The Hinge [La Brisure]", titles)
        self.assertIn("3- Of Grammatology as a Positive Science", titles)
        self.assertIn('"That Movement of the Wand . . . "', titles)

    def test_of_grammatology_symbolic_ocr_title_is_normalized_without_replacement_glyph(self) -> None:
        input_pdf = Path("/Users/rookslog/Projects/PDFAgentialConversion/Derrida_OfGrammatology.pdf")
        doc = convert_pdf.fitz.open(input_pdf)
        self.addCleanup(doc.close)
        layout_pages = convert_pdf.load_layout_pages(input_pdf, len(doc))
        toc_start, toc_end = convert_pdf.detect_toc_range(layout_pages)
        entries = convert_pdf.parse_toc_entries(layout_pages, toc_start, toc_end)
        titles = {entry.title for entry in entries}
        self.assertIn("The Outside )( the Inside", titles)
        self.assertNotIn("The Outside� the Inside", titles)

    def test_of_grammatology_part_markers_become_body_structure(self) -> None:
        case = next(
            item
            for item in load_fixture("toc_cases.json")["cases"]
            if item["id"] == "of-grammatology-part-markers"
        )
        entries = convert_pdf.parse_toc_entries(case["layout_pages"], case["toc_start"], case["toc_end"])
        convert_pdf.assign_output_paths(entries)
        by_title = {entry.title: entry for entry in entries}
        self.assertEqual(by_title["Writing before the Letter"].kind, "part")
        self.assertEqual(
            by_title["1 . The End of the Book and the Beginning of Writing"].kind,
            "chapter",
        )
        self.assertEqual(
            by_title["1 . The End of the Book and the Beginning of Writing"].parent_id,
            by_title["Writing before the Letter"].id,
        )
        duplicates = [path for path, count in Counter(entry.output_path for entry in entries if entry.output_path).items() if count > 1]
        self.assertEqual(duplicates, [])

    def test_otherwise_numbered_entries_do_not_fall_back_to_index(self) -> None:
        case = next(
            item
            for item in load_fixture("toc_cases.json")["cases"]
            if item["id"] == "otherwise-than-being-numbered-body"
        )
        entries = convert_pdf.parse_toc_entries(case["layout_pages"], case["toc_start"], case["toc_end"])
        convert_pdf.assign_output_paths(entries)
        by_title = {entry.title: entry for entry in entries}
        self.assertIn(by_title["THE ARGUMENT"].kind, {"part", "division"})
        self.assertEqual(by_title["2. Being and Interest"].kind, "chapter")
        self.assertNotEqual(by_title["2. Being and Interest"].output_path, "body/indexes/2-being-and-interest.md")
        self.assertEqual(by_title["a. Sensuous Lived Experience"].kind, "section")
        self.assertEqual(
            by_title["a. Sensuous Lived Experience"].parent_id,
            by_title["3. Time and Discourse"].id,
        )

    def test_truncated_hundreds_are_normalized_monotonically(self) -> None:
        case = next(
            item
            for item in load_fixture("toc_cases.json")["cases"]
            if item["id"] == "of-grammatology-truncated-hundreds"
        )
        entries = convert_pdf.parse_toc_entries(case["layout_pages"], case["toc_start"], case["toc_end"])
        by_title = {entry.title: entry for entry in entries}
        self.assertEqual(by_title["Writing and Man's Exploitation by Man"].page_label, "118")
        self.assertEqual(by_title["From/Of Blindness to the Supplement"].page_label, "144")
        self.assertEqual(by_title["The Chain of Supplements"].page_label, "152")
        self.assertEqual(by_title["The Exorbitant. Question of Method"].page_label, "157")
        self.assertEqual(by_title["Writing, Political Evil, and Linguistic Evil"].page_label, "167")
        self.assertEqual(by_title["The Initial Debate and the Composition of the Essay"].page_label, "192")

    def test_pending_chapter_uses_numbered_title_when_page_leaks_into_marker(self) -> None:
        case = next(
            item
            for item in load_fixture("toc_cases.json")["cases"]
            if item["id"] == "otherwise-pending-chapter-page-leak"
        )
        entries = convert_pdf.parse_toc_entries(case["layout_pages"], case["toc_start"], case["toc_end"])
        by_title = {entry.title: entry for entry in entries}
        self.assertEqual(by_title["1. Questioning and Allegiance to the Other"].display_title, "Chapter 1: 1. Questioning and Allegiance to the Other")
        self.assertEqual(by_title["1. Signification and the Objective Relation"].display_title, "Chapter 1: 1. Signification and the Objective Relation")
        self.assertEqual(by_title["Sensibility and Cognition"].display_title, "Chapter 61: Sensibility and Cognition")

    def test_split_quoted_titles_are_coalesced_before_toc_parsing(self) -> None:
        case = next(
            item
            for item in load_fixture("toc_cases.json")["cases"]
            if item["id"] == "split-quoted-title-page-leak"
        )
        entries = convert_pdf.parse_toc_entries(case["layout_pages"], case["toc_start"], case["toc_end"])
        titles = {entry.title for entry in entries}
        self.assertIn('"That Movement of the Wand . . . "', titles)
        self.assertIn('That "Simple Movement of the Finger." Writing and the Prohibition of Incest', titles)
        self.assertNotIn(". .", titles)
        self.assertNotIn("Prohibition of Incest", titles)
        self.assertNotIn('"That Movement of the Wand . " . .', titles)


if __name__ == "__main__":
    unittest.main()
