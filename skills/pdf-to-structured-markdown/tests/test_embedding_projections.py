from __future__ import annotations

import sys
import unittest
from pathlib import Path


TESTS_DIR = Path(__file__).resolve().parent
if str(TESTS_DIR) not in sys.path:
    sys.path.insert(0, str(TESTS_DIR))

from helpers import load_script_module


evaluate_embedding_space = load_script_module("evaluate_embedding_space")


def token_jaccard(left: str, right: str) -> float:
    tokens = evaluate_embedding_space.TOKEN_RE
    left_set = {token.lower() for token in tokens.findall(left)}
    right_set = {token.lower() for token in tokens.findall(right)}
    if not left_set and not right_set:
        return 1.0
    if not left_set or not right_set:
        return 0.0
    return len(left_set & right_set) / len(left_set | right_set)


class EmbeddingProjectionTests(unittest.TestCase):
    def test_rag_normalization_strips_passage_boilerplate(self) -> None:
        text = """---
title: "C. Re-citation"
---

# C. Re-citation

Representation: citation-first linearization for RAG.

Context: Part I: Attending the Future > Chapter 4: Why Read?

Source pages: 95-113 (PDF 112-130).

## Passage 004 (4e)
Label: 4e
Source reference: Derrida on Levinas
Source page labels: 99, 100

### Citation

One should cite with care and read with response.

### Commentary

The commentary follows the citation and not the page furniture.
"""
        normalized = evaluate_embedding_space.normalize_rag_markdown_for_embedding(text)
        self.assertIn("One should cite with care", normalized)
        self.assertIn("The commentary follows the citation", normalized)
        self.assertNotIn("## Passage", normalized)
        self.assertNotIn("Label:", normalized)
        self.assertNotIn("Source page labels:", normalized)
        self.assertNotIn("Representation:", normalized)

    def test_semantic_normalization_strips_heading_and_metadata_boilerplate(self) -> None:
        text = """---
title: "A. The Third Person"
---

# A. The Third Person

Context: Part I: Attending the Future > Chapter 2: Why Thirds?

Source pages: 52-58 (PDF 69-75).

The third person is not a metadata field. It is an interruption that bears witness.
"""
        normalized = evaluate_embedding_space.normalize_semantic_markdown_for_embedding(text)
        self.assertEqual(
            normalized,
            "The third person is not a metadata field. It is an interruption that bears witness.",
        )

    def test_spatial_contextual_omits_overloaded_supplement(self) -> None:
        document = evaluate_embedding_space.Document(
            doc_id="body/chapter-04/c-re-citation.md",
            corpus="spatial_main_plus_supplement",
            title="C. Re-citation",
            context="Part I: Attending the Future > Chapter 4: Why Read?",
            kind="section",
            body_text=" ".join(["Main body sentence."] * 80),
            supplement_text=" ".join(["Dense side annotation."] * 60),
            layout_text="",
        )
        payload = evaluate_embedding_space.build_view_payload(
            document,
            "contextual",
            evaluate_embedding_space.EMBEDDING_BODY_CHAR_LIMIT,
            normalized=True,
        )
        self.assertFalse(payload["supplement_preview_included"])
        self.assertEqual(payload["supplement_preview_chars"], 0)
        self.assertNotIn("Supplement:", payload["text"])

    def test_spatial_contextual_caps_small_supplement_preview(self) -> None:
        document = evaluate_embedding_space.Document(
            doc_id="body/chapter-05/c-commentaries.md",
            corpus="spatial_main_plus_supplement",
            title="C. Commentaries",
            context="Part I: Attending the Future > Chapter 5: Why Comment?",
            kind="section",
            body_text=" ".join(["Main body sentence."] * 140),
            supplement_text=" ".join(["Short margin gloss."] * 20),
            layout_text="",
        )
        payload = evaluate_embedding_space.build_view_payload(
            document,
            "contextual",
            evaluate_embedding_space.EMBEDDING_BODY_CHAR_LIMIT,
            normalized=True,
        )
        self.assertTrue(payload["supplement_preview_included"])
        self.assertLessEqual(
            payload["supplement_preview_chars"],
            evaluate_embedding_space.EMBEDDING_SUPPLEMENT_CHAR_LIMIT,
        )
        self.assertIn("Supplement:", payload["text"])

    def test_contextual_normalization_reduces_collision_proneness(self) -> None:
        cases = [
            {
                "name": "third-cluster",
                "left": evaluate_embedding_space.Document(
                    doc_id="body/part-01/chapter-02/a-the-third-person.md",
                    corpus="semantic_flat_clean",
                    title="A. The Third Person",
                    context="Part I: Attending the Future > Chapter 2: Why Thirds?",
                    kind="section",
                    body_text=(
                        "# A. The Third Person\n\n"
                        "Context: Part I: Attending the Future > Chapter 2: Why Thirds?\n\n"
                        "Source pages: 52-58 (PDF 69-75).\n\n"
                        "Thirdness arrives through witness, testimony, and substitution in the face."
                    ),
                    supplement_text="",
                    layout_text="",
                ),
                "right": evaluate_embedding_space.Document(
                    doc_id="body/part-01/chapter-01/a-the-third-and-justice.md",
                    corpus="semantic_flat_clean",
                    title="A. The Third and Justice",
                    context="Part I: Attending the Future > Chapter 1: Why Reason?",
                    kind="section",
                    body_text=(
                        "# A. The Third and Justice\n\n"
                        "Context: Part I: Attending the Future > Chapter 1: Why Reason?\n\n"
                        "Source pages: 8-15 (PDF 25-32).\n\n"
                        "Thirdness appears in judgment, institutions, and public comparison."
                    ),
                    supplement_text="",
                    layout_text="",
                ),
            },
            {
                "name": "judgment-cluster",
                "left": evaluate_embedding_space.Document(
                    doc_id="body/part-02/chapter-03/a-attribution.md",
                    corpus="semantic_flat_clean",
                    title="A. Attribution",
                    context="Part II: Present Judgments > Chapter 3: Why Judge?",
                    kind="section",
                    body_text=(
                        "# A. Attribution\n\n"
                        "Context: Part II: Present Judgments > Chapter 3: Why Judge?\n\n"
                        "Source pages: 201-208 (PDF 218-225).\n\n"
                        "Judgment begins with attribution, responsibility, and the irreducibility of the other."
                    ),
                    supplement_text="",
                    layout_text="",
                ),
                "right": evaluate_embedding_space.Document(
                    doc_id="body/part-02/chapter-04/c-judgment-and-the-oppressed.md",
                    corpus="semantic_flat_clean",
                    title="C. Judgment and the Oppressed",
                    context="Part II: Present Judgments > Chapter 4: Why Law?",
                    kind="section",
                    body_text=(
                        "# C. Judgment and the Oppressed\n\n"
                        "Context: Part II: Present Judgments > Chapter 4: Why Law?\n\n"
                        "Source pages: 245-252 (PDF 262-269).\n\n"
                        "Judgment becomes legal only when oppression, appeal, and institution are tested together."
                    ),
                    supplement_text="",
                    layout_text="",
                ),
            },
            {
                "name": "repeated-citation-commentary",
                "left": evaluate_embedding_space.Document(
                    doc_id="body/part-01/chapter-04/c-re-citation.md",
                    corpus="spatial_main_plus_supplement",
                    title="C. Re-citation",
                    context="Part I: Attending the Future > Chapter 4: Why Read?",
                    kind="section",
                    body_text=(
                        "Derrida reads Levinas by turning citation into a visible ethical practice. "
                        "Citation comes first, then commentary follows with care."
                    ),
                    supplement_text=" ".join(["Margin note about citation and reading."] * 25),
                    layout_text="",
                ),
                "right": evaluate_embedding_space.Document(
                    doc_id="body/part-01/chapter-05/c-commentaries.md",
                    corpus="spatial_main_plus_supplement",
                    title="C. Commentaries",
                    context="Part I: Attending the Future > Chapter 5: Why Comment?",
                    kind="section",
                    body_text=(
                        "Commentary separates and rejoins the text by way of gloss, interruption, and response. "
                        "It is not identical to citation, even when the vocabulary overlaps."
                    ),
                    supplement_text=" ".join(["Margin note about citation and reading."] * 25),
                    layout_text="",
                ),
            },
        ]

        for case in cases:
            with self.subTest(case=case["name"]):
                legacy_left = evaluate_embedding_space.build_view_payload(
                    case["left"],
                    "contextual",
                    evaluate_embedding_space.EMBEDDING_BODY_CHAR_LIMIT,
                    normalized=False,
                )["text"]
                legacy_right = evaluate_embedding_space.build_view_payload(
                    case["right"],
                    "contextual",
                    evaluate_embedding_space.EMBEDDING_BODY_CHAR_LIMIT,
                    normalized=False,
                )["text"]
                normalized_left = evaluate_embedding_space.build_view_payload(
                    case["left"],
                    "contextual",
                    evaluate_embedding_space.EMBEDDING_BODY_CHAR_LIMIT,
                    normalized=True,
                )["text"]
                normalized_right = evaluate_embedding_space.build_view_payload(
                    case["right"],
                    "contextual",
                    evaluate_embedding_space.EMBEDDING_BODY_CHAR_LIMIT,
                    normalized=True,
                )["text"]
                normalized_similarity = token_jaccard(normalized_left, normalized_right)

                self.assertLess(normalized_similarity, 0.5)
                if case["left"].corpus.startswith("semantic_"):
                    self.assertIn("Context:", legacy_left)
                    self.assertIn("Context:", legacy_right)
                    self.assertNotIn("Context:", normalized_left)
                    self.assertNotIn("Context:", normalized_right)
                    self.assertNotIn("Source pages:", normalized_left)
                    self.assertNotIn("Source pages:", normalized_right)
                else:
                    self.assertIn("Supplement:", legacy_left)
                    self.assertIn("Supplement:", legacy_right)
                    self.assertNotIn("Supplement:", normalized_left)
                    self.assertNotIn("Supplement:", normalized_right)


if __name__ == "__main__":
    unittest.main()
