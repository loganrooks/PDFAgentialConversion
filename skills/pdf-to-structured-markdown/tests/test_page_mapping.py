from __future__ import annotations

import sys
import unittest
from collections import Counter
from pathlib import Path


TESTS_DIR = Path(__file__).resolve().parent
WORKSPACE_ROOT = TESTS_DIR.parents[2]
if str(TESTS_DIR) not in sys.path:
    sys.path.insert(0, str(TESTS_DIR))

from helpers import load_script_module


convert_pdf = load_script_module("convert_pdf")


class PageMappingTests(unittest.TestCase):
    def test_of_grammatology_margin_candidates_prefer_outer_page_numbers(self) -> None:
        input_pdf = WORKSPACE_ROOT / "Derrida_OfGrammatology.pdf"
        doc = convert_pdf.fitz.open(input_pdf)
        self.addCleanup(doc.close)
        candidates = convert_pdf.extract_margin_page_number_candidates(
            doc[92 - 1],
            pdf_page=92,
            page_count=len(doc),
        )
        self.assertEqual([item["book_page"] for item in candidates], [6])

    def test_of_grammatology_program_maps_to_actual_body_page(self) -> None:
        input_pdf = WORKSPACE_ROOT / "Derrida_OfGrammatology.pdf"
        doc = convert_pdf.fitz.open(input_pdf)
        self.addCleanup(doc.close)
        layout_pages = convert_pdf.load_layout_pages(input_pdf, len(doc))
        toc_start, toc_end = convert_pdf.detect_toc_range(layout_pages)
        entries = convert_pdf.parse_toc_entries(layout_pages, toc_start, toc_end)
        convert_pdf.assign_pdf_pages(entries, doc, len(doc))
        by_title = {entry.title: entry for entry in entries}
        self.assertEqual(by_title["1 . The End of the Book and the Beginning of Writing"].pdf_page, 92)
        self.assertEqual(by_title["The Program"].pdf_page, 92)

    def test_of_grammatology_title_only_siblings_are_bounded_by_neighboring_entries(self) -> None:
        input_pdf = WORKSPACE_ROOT / "Derrida_OfGrammatology.pdf"
        doc = convert_pdf.fitz.open(input_pdf)
        self.addCleanup(doc.close)
        layout_pages = convert_pdf.load_layout_pages(input_pdf, len(doc))
        toc_start, toc_end = convert_pdf.detect_toc_range(layout_pages)
        entries = convert_pdf.parse_toc_entries(layout_pages, toc_start, toc_end)
        convert_pdf.assign_pdf_pages(entries, doc, len(doc))
        by_title = {entry.title: entry for entry in entries}
        self.assertIsNotNone(by_title["The Signifier and Truth"].pdf_page)
        self.assertIsNotNone(by_title["The vVritten Being/The Being Written"].pdf_page)
        self.assertIsNotNone(by_title["2. Linguistics and Grammatology"].pdf_page)
        self.assertGreater(by_title["The Signifier and Truth"].pdf_page, by_title["The Program"].pdf_page)
        self.assertGreaterEqual(
            by_title["The vVritten Being/The Being Written"].pdf_page,
            by_title["The Signifier and Truth"].pdf_page,
        )
        self.assertLess(
            by_title["The Signifier and Truth"].end_pdf_page,
            by_title["The vVritten Being/The Being Written"].pdf_page,
        )
        self.assertLess(
            by_title["2. Linguistics and Grammatology"].pdf_page,
            by_title["Nature, Culture , Writing"].pdf_page,
        )

    def test_of_grammatology_inline_subheading_cutoff_prefers_actual_inline_title(self) -> None:
        input_pdf = WORKSPACE_ROOT / "Derrida_OfGrammatology.pdf"
        doc = convert_pdf.fitz.open(input_pdf)
        self.addCleanup(doc.close)
        layout_pages = convert_pdf.load_layout_pages(input_pdf, len(doc))
        toc_start, toc_end = convert_pdf.detect_toc_range(layout_pages)
        entries = convert_pdf.parse_toc_entries(layout_pages, toc_start, toc_end)
        convert_pdf.assign_pdf_pages(entries, doc, len(doc))
        by_id = convert_pdf.get_entry_by_id(entries)
        entry = next(item for item in entries if item.title == "The Interval and the Supplement")
        previous_entry = entries[entries.index(entry) - 1]
        cutoff = convert_pdf.detect_entry_start_cutoff(entry, previous_entry, doc[entry.pdf_page - 1], by_id)
        self.assertIsNotNone(cutoff)
        self.assertGreater(cutoff, 300.0)

    def test_of_grammatology_same_page_boundary_uses_complementary_slices(self) -> None:
        input_pdf = WORKSPACE_ROOT / "Derrida_OfGrammatology.pdf"
        doc = convert_pdf.fitz.open(input_pdf)
        self.addCleanup(doc.close)
        layout_pages = convert_pdf.load_layout_pages(input_pdf, len(doc))
        toc_start, toc_end = convert_pdf.detect_toc_range(layout_pages)
        entries = convert_pdf.parse_toc_entries(layout_pages, toc_start, toc_end)
        convert_pdf.assign_pdf_pages(entries, doc, len(doc))
        convert_pdf.assign_output_paths(entries)
        page_profiles = {
            page_number: convert_pdf.analyze_page_layout(doc[page_number - 1], layout_pages[page_number - 1])
            for page_number in range(1, len(doc) + 1)
        }

        initial_entry = next(item for item in entries if item.title == "The Initial Debate and the Composition of the Essay")
        imitation_entry = next(item for item in entries if item.title == "II. Imitation")
        interval_entry = next(item for item in entries if item.title == "The Interval and the Supplement")

        _, _, _, initial_spatial = convert_pdf.render_entry_markdown(
            initial_entry,
            entries,
            doc,
            layout_pages,
            page_profiles,
            "derrida-of-grammatology",
        )
        _, _, _, imitation_spatial = convert_pdf.render_entry_markdown(
            imitation_entry,
            entries,
            doc,
            layout_pages,
            page_profiles,
            "derrida-of-grammatology",
        )
        _, _, _, interval_spatial = convert_pdf.render_entry_markdown(
            interval_entry,
            entries,
            doc,
            layout_pages,
            page_profiles,
            "derrida-of-grammatology",
        )

        assert initial_spatial is not None
        assert imitation_spatial is not None
        assert interval_spatial is not None

        self.assertEqual(
            [page["pdf_page"] for page in initial_spatial["pages"]],
            [276, 277, 278],
        )

        imitation_page = next(page for page in imitation_spatial["pages"] if page["pdf_page"] == 279)
        interval_page = next(page for page in interval_spatial["pages"] if page["pdf_page"] == 279)
        self.assertIsNotNone(imitation_page["slice_min_y"])
        self.assertIsNotNone(imitation_page["slice_max_y"])
        self.assertIsNotNone(interval_page["slice_min_y"])
        self.assertLess(imitation_page["slice_min_y"], 100.0)
        self.assertGreater(interval_page["slice_min_y"], 300.0)
        self.assertLess(imitation_page["slice_max_y"], interval_page["slice_min_y"])

    def test_monotonic_observation_selection_discards_false_early_jump(self) -> None:
        candidates = [
            {"pdf_page": 46, "book_page": 52},
            {"pdf_page": 54, "book_page": 10},
            {"pdf_page": 56, "book_page": 12},
            {"pdf_page": 57, "book_page": 13},
            {"pdf_page": 170, "book_page": 129},
            {"pdf_page": 173, "book_page": 132},
        ]
        observations = convert_pdf.select_monotonic_page_observations(candidates)
        self.assertEqual(
            [(item["pdf_page"], item["book_page"]) for item in observations],
            [(54, 10), (56, 12), (57, 13), (170, 129), (173, 132)],
        )

    def test_interpolation_handles_piecewise_page_drift(self) -> None:
        observations = [
            {"pdf_page": 54, "book_page": 10},
            {"pdf_page": 56, "book_page": 12},
            {"pdf_page": 57, "book_page": 13},
            {"pdf_page": 170, "book_page": 129},
            {"pdf_page": 173, "book_page": 132},
        ]
        self.assertEqual(
            convert_pdf.interpolate_pdf_page_from_observations(observations, 11, page_count=300),
            55,
        )
        self.assertEqual(
            convert_pdf.interpolate_pdf_page_from_observations(observations, 131, page_count=300),
            172,
        )
        self.assertEqual(
            convert_pdf.interpolate_pdf_page_from_observations(observations, 3, page_count=300),
            47,
        )

    def test_strong_global_offset_beats_sparse_noisy_observations(self) -> None:
        offset_votes = Counter({17: 364, -81: 1, -238: 1, -381: 1})
        noisy_observations = [
            {"pdf_page": 5, "book_page": 2},
            {"pdf_page": 21, "book_page": 4},
            {"pdf_page": 22, "book_page": 5},
            {"pdf_page": 23, "book_page": 6},
            {"pdf_page": 24, "book_page": 7},
        ]
        strategy = convert_pdf.choose_arabic_page_mapping_strategy(offset_votes, noisy_observations)
        self.assertEqual(strategy["mode"], "global_offset")
        self.assertEqual(strategy["arabic_offset"], 17)
        self.assertEqual(
            [(item["pdf_page"], item["book_page"]) for item in strategy["observations"]],
            [(21, 4), (22, 5), (23, 6), (24, 7)],
        )

    def test_shared_boundary_cutoff_prefers_actual_section_heading(self) -> None:
        input_pdf = WORKSPACE_ROOT / "Gibbs_WhyEthics.pdf"
        doc = convert_pdf.fitz.open(input_pdf)
        self.addCleanup(doc.close)
        layout_pages = convert_pdf.load_layout_pages(input_pdf, len(doc))
        toc_start, toc_end = convert_pdf.detect_toc_range(layout_pages)
        entries = convert_pdf.parse_toc_entries(layout_pages, toc_start, toc_end)
        convert_pdf.assign_pdf_pages(entries, doc, len(doc))
        by_id = convert_pdf.get_entry_by_id(entries)
        entry = next(item for item in entries if item.title == "B. Bodily Signifying")
        previous_entry = entries[entries.index(entry) - 1]
        cutoff = convert_pdf.detect_entry_start_cutoff(entry, previous_entry, doc[entry.pdf_page - 1], by_id)
        self.assertIsNotNone(cutoff)
        self.assertGreater(cutoff, 500.0)

    def test_top_page_heading_cutoff_stays_near_top_when_heading_is_topmost(self) -> None:
        input_pdf = WORKSPACE_ROOT / "Gibbs_WhyEthics.pdf"
        doc = convert_pdf.fitz.open(input_pdf)
        self.addCleanup(doc.close)
        layout_pages = convert_pdf.load_layout_pages(input_pdf, len(doc))
        toc_start, toc_end = convert_pdf.detect_toc_range(layout_pages)
        entries = convert_pdf.parse_toc_entries(layout_pages, toc_start, toc_end)
        convert_pdf.assign_pdf_pages(entries, doc, len(doc))
        by_id = convert_pdf.get_entry_by_id(entries)
        entry = next(item for item in entries if item.title == "Why Speak?")
        previous_entry = entries[entries.index(entry) - 1]
        cutoff = convert_pdf.detect_entry_start_cutoff(entry, previous_entry, doc[entry.pdf_page - 1], by_id)
        self.assertIsNotNone(cutoff)
        self.assertLess(cutoff, 130.0)

    def test_heading_cutoff_uses_number_stripped_heading_variants(self) -> None:
        input_pdf = WORKSPACE_ROOT / "Levinas_OtherwiseThanBeing.pdf"
        doc = convert_pdf.fitz.open(input_pdf)
        self.addCleanup(doc.close)
        layout_pages = convert_pdf.load_layout_pages(input_pdf, len(doc))
        toc_start, toc_end = convert_pdf.detect_toc_range(layout_pages)
        entries = convert_pdf.parse_toc_entries(layout_pages, toc_start, toc_end)
        convert_pdf.assign_pdf_pages(entries, doc, len(doc))
        by_id = convert_pdf.get_entry_by_id(entries)
        entry = next(item for item in entries if item.title == "8. Being and Beyond Being")
        previous_entry = entries[entries.index(entry) - 1]
        cutoff = convert_pdf.detect_entry_start_cutoff(entry, previous_entry, doc[entry.pdf_page - 1], by_id)
        self.assertIsNotNone(cutoff)
        self.assertGreater(cutoff, 500.0)

    def test_same_page_boundary_keeps_pre_heading_slice_when_previous_section_continues(self) -> None:
        input_pdf = WORKSPACE_ROOT / "Gibbs_WhyEthics.pdf"
        doc = convert_pdf.fitz.open(input_pdf)
        self.addCleanup(doc.close)
        layout_pages = convert_pdf.load_layout_pages(input_pdf, len(doc))
        toc_start, toc_end = convert_pdf.detect_toc_range(layout_pages)
        entries = convert_pdf.parse_toc_entries(layout_pages, toc_start, toc_end)
        convert_pdf.assign_pdf_pages(entries, doc, len(doc))
        convert_pdf.assign_output_paths(entries)
        page_profiles = {
            page_number: convert_pdf.analyze_page_layout(doc[page_number - 1], layout_pages[page_number - 1])
            for page_number in range(1, len(doc) + 1)
        }
        entry = next(item for item in entries if item.title == "A. The Saying")
        _, _, _, spatial_payload = convert_pdf.render_entry_markdown(
            entry,
            entries,
            doc,
            layout_pages,
            page_profiles,
            "robert-gibbs-why-ethics",
        )
        assert spatial_payload is not None
        shared_page = next(page for page in spatial_payload["pages"] if page["pdf_page"] == 67)
        self.assertIsNone(shared_page["slice_min_y"])
        self.assertIsNotNone(shared_page["slice_max_y"])

    def test_section_refinement_prefers_exact_heading_page_over_later_body_phrase(self) -> None:
        input_pdf = WORKSPACE_ROOT / "Gibbs_WhyEthics.pdf"
        doc = convert_pdf.fitz.open(input_pdf)
        self.addCleanup(doc.close)
        layout_pages = convert_pdf.load_layout_pages(input_pdf, len(doc))
        toc_start, toc_end = convert_pdf.detect_toc_range(layout_pages)
        entries = convert_pdf.parse_toc_entries(layout_pages, toc_start, toc_end)
        convert_pdf.assign_pdf_pages(entries, doc, len(doc))
        by_title = {entry.title: entry for entry in entries}
        self.assertEqual(by_title["B. Great Is Repentance"].pdf_page, 327)

    def test_same_page_boundary_drops_next_section_page_when_no_pre_heading_content_exists(self) -> None:
        input_pdf = WORKSPACE_ROOT / "Gibbs_WhyEthics.pdf"
        doc = convert_pdf.fitz.open(input_pdf)
        self.addCleanup(doc.close)
        layout_pages = convert_pdf.load_layout_pages(input_pdf, len(doc))
        toc_start, toc_end = convert_pdf.detect_toc_range(layout_pages)
        entries = convert_pdf.parse_toc_entries(layout_pages, toc_start, toc_end)
        convert_pdf.assign_pdf_pages(entries, doc, len(doc))
        convert_pdf.assign_output_paths(entries)
        page_profiles = {
            page_number: convert_pdf.analyze_page_layout(doc[page_number - 1], layout_pages[page_number - 1])
            for page_number in range(1, len(doc) + 1)
        }
        entry = next(item for item in entries if item.title == "B. Bodily Signifying")
        _, _, _, spatial_payload = convert_pdf.render_entry_markdown(
            entry,
            entries,
            doc,
            layout_pages,
            page_profiles,
            "robert-gibbs-why-ethics",
        )
        assert spatial_payload is not None
        self.assertNotIn(75, [page["pdf_page"] for page in spatial_payload["pages"]])


if __name__ == "__main__":
    unittest.main()
