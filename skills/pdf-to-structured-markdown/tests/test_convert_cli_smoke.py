from __future__ import annotations

import importlib
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import fitz


TESTS_DIR = Path(__file__).resolve().parent
SRC_ROOT = TESTS_DIR.parents[2] / "src"
if str(TESTS_DIR) not in sys.path:
    sys.path.insert(0, str(TESTS_DIR))
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from helpers import load_script_module


convert_pdf = load_script_module("convert_pdf")
convert_impl = importlib.import_module("pdfmd.convert.convert_pdf")


class ConvertCliSmokeTests(unittest.TestCase):
    def test_wrapper_reaches_package_main_and_writes_output_skeleton(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            input_pdf = temp_root / "tiny.pdf"
            output_dir = temp_root / "bundle"

            doc = fitz.open()
            page = doc.new_page()
            page.insert_text((72, 72), "Synthetic Test PDF")
            doc.save(input_pdf)
            doc.close()

            entry = convert_impl.TocEntry(
                id="synthetic-section",
                kind="section",
                level=1,
                title="Synthetic Section",
                page_label="1",
                numbering="arabic",
                parent_id=None,
                pdf_page=1,
                end_pdf_page=1,
                output_path="body/synthetic-section.md",
                output_dir="body",
                sequence=1,
                slug="synthetic-section",
            )

            citation = {
                "title": "Synthetic Test PDF",
                "authors": ["Test Author"],
                "contributors": [{"name": "Test Author", "role": "author"}],
                "publisher": "Test Press",
                "publication_year": "2026",
                "recommended_citation": "Test Author, Synthetic Test PDF (Test Press, 2026).",
            }

            def fake_assign_pdf_pages(entries, doc_obj, page_count):
                self.assertEqual(page_count, 1)
                for current in entries:
                    current.pdf_page = 1
                    current.end_pdf_page = 1
                return {"mode": "smoke"}

            def fake_assign_output_paths(entries):
                for current in entries:
                    current.output_path = "body/synthetic-section.md"
                    current.output_dir = "body"

            def fake_analyze_page_layout(page_obj, raw_text):
                return {"kind": "single_column", "complex": False, "reasons": []}

            def fake_render_auxiliary_markdown(**kwargs):
                manifest = {
                    "entry_id": f"aux-{kwargs['title'].lower().replace(' ', '-')}",
                    "kind": "auxiliary",
                    "title": kwargs["title"],
                    "output_path": kwargs["relative_path"],
                    "flat_output_path": None,
                    "rag_output_path": None,
                    "spatial_output_path": None,
                    "context_path": None,
                    "book_page_start": "i",
                    "book_page_end": "i",
                    "pdf_page_start": kwargs["pdf_start"],
                    "pdf_page_end": kwargs["pdf_end"],
                    "complex_pdf_pages": [],
                    "child_ids": [],
                }
                return "# Aux\n", None, manifest, None

            def fake_render_entry_markdown(current_entry, entries, doc_obj, layout_pages, page_profiles, book_id):
                manifest = {
                    "entry_id": current_entry.id,
                    "kind": current_entry.kind,
                    "title": current_entry.title,
                    "output_path": current_entry.output_path,
                    "flat_output_path": "flat/leaf-nodes/synthetic-section.md",
                    "rag_output_path": "rag/leaf-nodes/synthetic-section.md",
                    "spatial_output_path": "spatial/body/synthetic-section.layout.json",
                    "context_path": None,
                    "book_page_start": "1",
                    "book_page_end": "1",
                    "pdf_page_start": 1,
                    "pdf_page_end": 1,
                    "complex_pdf_pages": [],
                    "child_ids": [],
                }
                spatial = {
                    "entry_id": current_entry.id,
                    "title": current_entry.title,
                    "kind": current_entry.kind,
                    "pages": [],
                }
                return "# Synthetic Section\n", "## Passage 001\n\n### Citation\n\nSynthetic.\n", manifest, spatial

            patches = [
                mock.patch.object(convert_impl, "detect_toc_range", return_value=(1, 1)),
                mock.patch.object(convert_impl, "parse_toc_entries", return_value=[entry]),
                mock.patch.object(convert_impl, "assign_pdf_pages", side_effect=fake_assign_pdf_pages),
                mock.patch.object(convert_impl, "assign_output_paths", side_effect=fake_assign_output_paths),
                mock.patch.object(convert_impl, "analyze_page_layout", side_effect=fake_analyze_page_layout),
                mock.patch.object(convert_impl, "build_citation_metadata", return_value=citation),
                mock.patch.object(convert_impl, "render_auxiliary_markdown", side_effect=fake_render_auxiliary_markdown),
                mock.patch.object(convert_impl, "render_entry_markdown", side_effect=fake_render_entry_markdown),
                mock.patch.object(convert_impl, "parse_pdfinfo", return_value={}),
                mock.patch.object(convert_impl, "sha256", return_value="synthetic-sha256"),
                mock.patch.object(
                    sys,
                    "argv",
                    ["convert_pdf.py", str(input_pdf), str(output_dir)],
                ),
            ]

            with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5], patches[6], patches[7], patches[8], patches[9], patches[10]:
                exit_code = convert_pdf.main()
                self.assertEqual(exit_code, 0)
                self.assertTrue((output_dir / "metadata.json").exists())
                self.assertTrue((output_dir / "index.md").exists())
                self.assertTrue((output_dir / "toc.md").exists())
                self.assertTrue((output_dir / "run-manifest.json").exists())

                metadata = json.loads((output_dir / "metadata.json").read_text(encoding="utf-8"))
                self.assertEqual(metadata["book_id"], "test-author-synthetic-test-pdf")
                self.assertTrue((output_dir / "body" / "synthetic-section.md").exists())


if __name__ == "__main__":
    unittest.main()
