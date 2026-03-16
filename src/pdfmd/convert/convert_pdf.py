#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import unicodedata
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import fitz
from pypdf import PdfReader

from pdfmd.common.manifests import write_manifest


SCRIPT_VERSION = "0.1.0"
PASSAGE_ANCHOR_RE = re.compile(r"^(?:[-*]\s*)?(?P<label>\d+[a-z])\)\s*(?P<rest>.*)$", re.IGNORECASE)
EMBEDDED_PASSAGE_ANCHOR_RE = re.compile(r"(?<=\s)(?P<label>\d+[a-z])\)\s*", re.IGNORECASE)
SHORT_SOURCE_REF_RE = re.compile(r"^(?:\[[^\]]+\]|(?:Levinas|Derrida)\b.*|[A-Z][A-Za-z]+(?:\s+[A-Z][A-Za-z0-9.]+){0,4})$")
LEADING_AUTHOR_SOURCE_REF_RE = re.compile(
    r"^(?P<ref>(?:Levinas|Derrida)\s+\S+\s+\S+)(?:\s+(?P<tail>.*))?$"
)
PERSON_TOKEN_PATTERN = r"[A-ZÀ-ÖØ-Þ][A-Za-zÀ-ÖØ-öø-ÿ'’.-]+"
PERSON_LINE_RE = re.compile(rf"^{PERSON_TOKEN_PATTERN}(?:\s+{PERSON_TOKEN_PATTERN}){{1,4}}$")
CATALOG_PERSON_RE = re.compile(
    rf"^(?P<last>{PERSON_TOKEN_PATTERN}),\s*(?P<first>{PERSON_TOKEN_PATTERN}(?:\s+{PERSON_TOKEN_PATTERN}){{0,3}})\.?$"
)
BYLINE_AUTHOR_RE = re.compile(
    rf"^(?:by|written by)\s+(?P<name>{PERSON_TOKEN_PATTERN}(?:\s+{PERSON_TOKEN_PATTERN}){{1,4}})\b",
    re.IGNORECASE,
)
TITLE_LINE_RE = re.compile(r"[A-Za-zÀ-ÖØ-öø-ÿ]")
CONTRIBUTOR_SPLIT_RE = re.compile(r"\s*(?:,| and | & )\s*", re.IGNORECASE)
PUBLISHER_LINE_RE = re.compile(
    r"(?P<publisher>.+?(?:University Press|Routledge|Press|Publishers?|Editions? [A-Z][A-Za-z]+|Academic Publishers(?: B\.V\.)?))",
    re.IGNORECASE,
)
RAG_TERMINAL_PUNCTUATION_RE = re.compile(r'[.!?]["”\')\]]?$')
ALPHA_TOKEN_RE = re.compile(r"[A-Za-z][A-Za-z'’-]*")
INLINE_NOTE_MARKER_RE = re.compile(r"^\d+[a-z]?\)")
SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+")
RAG_DANGLING_END_WORDS = {
    "a",
    "an",
    "and",
    "as",
    "at",
    "be",
    "by",
    "for",
    "from",
    "in",
    "into",
    "is",
    "it",
    "its",
    "of",
    "on",
    "or",
    "that",
    "the",
    "their",
    "this",
    "to",
    "what",
    "which",
    "with",
}
BOTTOM_REFERENCE_CONTINUATION_Y0 = 520.0
TARGET_UNANCHORED_PASSAGE_TOKENS = 1200
MAX_UNANCHORED_PASSAGE_TOKENS = 1600
RAG_DUPLICATE_BOUNDARY_WORDS = {
    "a",
    "also",
    "an",
    "and",
    "he",
    "i",
    "in",
    "it",
    "of",
    "on",
    "or",
    "she",
    "the",
    "they",
    "this",
    "those",
    "to",
    "we",
    "you",
}
HEADING_CONNECTOR_WORDS = {
    "a",
    "an",
    "and",
    "as",
    "at",
    "by",
    "for",
    "from",
    "in",
    "into",
    "is",
    "not",
    "of",
    "on",
    "or",
    "that",
    "the",
    "to",
    "with",
}
HEADING_MARKER_PREFIX_RE = re.compile(
    r"^(?:(?:\d+|[A-Z]|[IVXLCDM]+)\s*[.):]?\s+)+",
    re.IGNORECASE,
)


@dataclass
class TocEntry:
    id: str
    kind: str
    level: int
    title: str
    page_label: str | None
    numbering: str
    marker: str | None = None
    parent_id: str | None = None
    children: list[str] = field(default_factory=list)
    pdf_page: int | None = None
    end_pdf_page: int | None = None
    output_path: str | None = None
    output_dir: str | None = None
    sequence: int = 0
    slug: str = ""

    @property
    def display_title(self) -> str:
        if self.kind == "part" and self.marker:
            return f"{self.marker}: {self.title}"
        if self.kind == "chapter" and self.marker:
            return f"{self.marker}: {self.title}"
        if self.kind == "introduction" and self.marker:
            return f"{self.marker}: {self.title}"
        if self.kind == "epilogue" and self.marker:
            return f"{self.marker}: {self.title}"
        return self.title


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Convert a scholarly PDF into a ToC-segmented markdown bundle."
    )
    parser.add_argument("input_pdf", type=Path)
    parser.add_argument("output_dir", type=Path)
    parser.add_argument("--book-id", help="Override the output bundle identifier.")
    parser.add_argument(
        "--force",
        action="store_true",
        help="Delete the output directory first if it already exists.",
    )
    return parser.parse_args()


def normalize_unicode(text: str) -> str:
    return unicodedata.normalize("NFKC", text).replace("\ufb01", "fi").replace("\ufb02", "fl")


def clean_text_line(text: str) -> str:
    return re.sub(r"\s+", " ", normalize_unicode(text)).strip()


def keyify(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", normalize_unicode(text).lower())


def slugify(text: str) -> str:
    ascii_text = (
        unicodedata.normalize("NFKD", text)
        .encode("ascii", "ignore")
        .decode("ascii")
        .lower()
    )
    slug = re.sub(r"[^a-z0-9]+", "-", ascii_text).strip("-")
    slug = re.sub(r"-{2,}", "-", slug)
    return slug or "item"


def boundary_overlap_mode() -> str:
    mode = os.environ.get("PDFMD_BOUNDARY_OVERLAP_MODE", "hybrid").strip().lower()
    if mode in {"conservative", "balanced", "aggressive", "hybrid"}:
        return mode
    return "hybrid"


def prose_join_mode() -> str:
    mode = os.environ.get("PDFMD_PROSE_JOIN_MODE", "balanced").strip().lower()
    if mode in {"conservative", "balanced", "aggressive"}:
        return mode
    return "balanced"


def micro_region_mode() -> str:
    mode = os.environ.get("PDFMD_MICRO_REGION_MODE", "reclassify_first").strip().lower()
    if mode in {"reclassify_first", "group_first"}:
        return mode
    return "reclassify_first"


def strip_heading_marker_prefix(text: str) -> str:
    cleaned = clean_text_line(text)
    return HEADING_MARKER_PREFIX_RE.sub("", cleaned).strip()


def heading_word_tokens(text: str) -> list[str]:
    return re.findall(r"[A-Za-z][A-Za-z'’-]*", normalize_unicode(text))


def is_title_style_heading(text: str) -> bool:
    tokens = heading_word_tokens(strip_heading_marker_prefix(text) or text)
    if not tokens or len(tokens) > 14:
        return False
    titleish = sum(
        1
        for token in tokens
        if token[:1].isupper() or token.lower() in HEADING_CONNECTOR_WORDS
    )
    return titleish / max(len(tokens), 1) >= 0.7


def similar_heading_token(left: str, right: str) -> bool:
    left_norm = normalize_unicode(left).lower()
    right_norm = normalize_unicode(right).lower()
    if left_norm == right_norm:
        return True
    if len(left_norm) >= 5 and len(right_norm) >= 5 and left_norm[:5] == right_norm[:5]:
        return True
    if len(left_norm) >= 6 and len(right_norm) >= 6 and left_norm[:6] == right_norm[:6]:
        return True
    return False


def fuzzy_heading_variant_match(candidate: str, variant: str) -> bool:
    candidate_tokens = heading_word_tokens(candidate)
    variant_tokens = heading_word_tokens(variant)
    if len(candidate_tokens) < 2 or len(variant_tokens) < 2:
        return False
    aligned = min(len(candidate_tokens), len(variant_tokens))
    similar = sum(
        1
        for left, right in zip(candidate_tokens[:aligned], variant_tokens[:aligned])
        if similar_heading_token(left, right)
    )
    if aligned < 3:
        return len(candidate_tokens) == len(variant_tokens) and similar == aligned
    leading = min(3, aligned)
    if not all(
        similar_heading_token(left, right)
        for left, right in zip(candidate_tokens[:leading], variant_tokens[:leading])
    ):
        return False
    return similar >= max(leading, len(variant_tokens) - 1)


def classify_heading_line(
    text: str,
    skip_keys: set[str],
    *,
    prefix_variants: list[str] | None = None,
    mode: str | None = None,
) -> dict[str, Any] | None:
    cleaned = clean_text_line(text)
    if not cleaned:
        return None
    active_mode = mode or boundary_overlap_mode()
    if keyify(cleaned) in skip_keys:
        return {"match_type": "exact", "remainder": ""}

    variants = [clean_text_line(variant) for variant in (prefix_variants or []) if clean_text_line(variant)]
    candidates = [cleaned]
    stripped = strip_heading_marker_prefix(cleaned)
    if stripped and stripped != cleaned:
        candidates.append(stripped)

    for candidate in candidates:
        candidate_lower = normalize_unicode(candidate).lower()
        for variant in variants:
            variant_lower = normalize_unicode(variant).lower()
            if candidate_lower == variant_lower:
                return {"match_type": "variant", "remainder": ""}
            if not candidate_lower.startswith(variant_lower):
                continue
            remainder = candidate[len(variant) :].lstrip()
            trimmed_remainder = remainder.lstrip(" .:;,!?)]}\"'’-[")
            if not trimmed_remainder:
                return {"match_type": "variant", "remainder": ""}
            if active_mode in {"aggressive", "hybrid"}:
                return {"match_type": "inline_variant", "remainder": trimmed_remainder}
            return {"match_type": "inline_variant", "remainder": ""}

    if active_mode == "conservative":
        return None

    if is_title_style_heading(cleaned):
        candidate = stripped or cleaned
        for variant in variants:
            if fuzzy_heading_variant_match(candidate, strip_heading_marker_prefix(variant) or variant):
                return {"match_type": "fuzzy_variant", "remainder": ""}
    return None


def should_skip_top_margin_line(text: str, y0: float) -> bool:
    cleaned = clean_text_line(text)
    if not cleaned:
        return False
    if y0 < 30.0:
        if cleaned.isdigit() or re.fullmatch(r"[ivxlcdm]+", cleaned.lower()):
            return True
        return len(cleaned) <= 120
    if y0 > 42.0:
        return False
    if cleaned.isdigit() or re.fullmatch(r"[ivxlcdm]+", cleaned.lower()):
        return True
    if re.match(r"^(?:part|chapter|contents|translator'?s preface|preface)\b", cleaned, re.IGNORECASE):
        return len(cleaned.split()) <= 10
    if len(cleaned.split()) <= 8 and cleaned == normalize_title_line(cleaned):
        return True
    return False


def should_absorb_inline_fragment(
    current: dict[str, Any],
    candidate: dict[str, Any],
    *,
    allow_title_case: bool = False,
) -> bool:
    same_baseline = (
        abs(candidate["y0"] - current["y0"]) <= 1.5
        and abs(candidate["y1"] - current["y1"]) <= 1.5
    )
    if not same_baseline:
        return False
    gap = candidate["x0"] - current["x1"]
    if gap < 0 or gap > 16:
        return False
    current_text = clean_text_line(current["text"])
    candidate_text = clean_text_line(candidate["text"])
    if not current_text or not candidate_text:
        return False
    if current_text.endswith("-") and INLINE_NOTE_MARKER_RE.match(candidate_text):
        return False
    if current_text.endswith("-"):
        return True
    if re.match(r'^[("“‘\[]?[a-z0-9]', candidate_text):
        return True
    if not allow_title_case:
        return False
    if re.fullmatch(r"[A-Za-z]\.", current_text) and candidate_text[:1].isupper():
        return True
    if (
        current_text.isupper()
        and len(current_text.split()) <= 2
        and re.match(r"^(?:[A-Z][a-z]+|[IVXLC0-9]+)$", candidate_text)
    ):
        return True
    return False


def collapse_inline_fragments(
    raw_items: list[dict[str, Any]],
    *,
    allow_title_case: bool = False,
) -> list[dict[str, Any]]:
    if not raw_items:
        return []
    collapsed: list[dict[str, Any]] = []
    current = raw_items[0].copy()
    for item in raw_items[1:]:
        if should_absorb_inline_fragment(current, item, allow_title_case=allow_title_case):
            separator = "" if clean_text_line(current["text"]).endswith("-") else " "
            current["text"] = f"{current['text'].rstrip()}{separator}{item['text'].lstrip()}".strip()
            current["x1"] = max(current["x1"], item["x1"])
            current["y1"] = max(current["y1"], item["y1"])
            continue
        collapsed.append(current)
        current = item.copy()
    collapsed.append(current)
    return collapsed


def roman_to_int(value: str) -> int:
    numerals = {"I": 1, "V": 5, "X": 10, "L": 50, "C": 100, "D": 500, "M": 1000}
    total = 0
    prev = 0
    for char in reversed(value.upper()):
        current = numerals[char]
        if current < prev:
            total -= current
        else:
            total += current
            prev = current
    return total


def int_to_roman(value: int) -> str:
    parts = [
        (1000, "M"),
        (900, "CM"),
        (500, "D"),
        (400, "CD"),
        (100, "C"),
        (90, "XC"),
        (50, "L"),
        (40, "XL"),
        (10, "X"),
        (9, "IX"),
        (5, "V"),
        (4, "IV"),
        (1, "I"),
    ]
    remaining = value
    chunks: list[str] = []
    for number, numeral in parts:
        while remaining >= number:
            chunks.append(numeral)
            remaining -= number
    return "".join(chunks).lower()


def increment_page_label(page_label: str | None, numbering: str, offset: int) -> str | None:
    if page_label is None:
        return None
    if numbering == "arabic":
        return str(int(page_label) + offset)
    if numbering == "roman":
        return int_to_roman(roman_to_int(page_label) + offset)
    return page_label


def format_page_range(start_label: str | None, end_label: str | None) -> str:
    if not start_label:
        return "unknown"
    if not end_label or end_label == start_label:
        return start_label
    return f"{start_label}-{end_label}"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def run_command(command: list[str]) -> str | None:
    try:
        completed = subprocess.run(command, capture_output=True, text=True, check=True)
    except (subprocess.CalledProcessError, FileNotFoundError):
        return None
    return completed.stdout


def load_layout_pages(input_pdf: Path, page_count: int) -> list[str]:
    pdftotext = shutil.which("pdftotext")
    if pdftotext:
        text = run_command([pdftotext, "-layout", str(input_pdf), "-"])
        if text:
            pages = text.split("\f")
            if pages and pages[-1] == "":
                pages.pop()
            if len(pages) == page_count:
                return pages
    doc = fitz.open(input_pdf)
    return [page.get_text("text") for page in doc]


def parse_pdfinfo(input_pdf: Path) -> dict[str, Any]:
    output = run_command(["pdfinfo", str(input_pdf)])
    if not output:
        return {}
    info: dict[str, Any] = {}
    for line in output.splitlines():
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        info[slugify(key).replace("-", "_")] = value.strip()
    return info


def normalize_page_label_token(token: str) -> str:
    compact = clean_text_line(token)
    if re.fullmatch(r"[ivxlcdm]+", compact, re.IGNORECASE):
        return compact.lower()
    if re.fullmatch(r"\d(?:\s*\d){0,3}", compact):
        return compact.replace(" ", "")
    return compact


def standalone_page_label(line: str) -> str | None:
    compact = clean_text_line(line)
    if re.fullmatch(r"[ivxlcdm]+", compact, re.IGNORECASE):
        return compact.lower()
    if re.fullmatch(r"\d(?:\s*\d){0,3}", compact):
        return compact.replace(" ", "")
    return None


def likely_page_reference(line: str) -> bool:
    return bool(
        re.search(
            r"(?:\s{2,}|\s+)([ivxlcdm]+|\d(?:\s*\d){0,3})\s*$",
            line.strip(),
            re.IGNORECASE,
        )
    )


def looks_like_toc_page(page_text: str) -> bool:
    lines = [line.rstrip() for line in page_text.splitlines()]
    page_like = sum(1 for line in lines if likely_page_reference(line))
    content_key = keyify(page_text)
    return "contents" in content_key and page_like >= 4 or page_like >= 8


def detect_toc_range(layout_pages: list[str]) -> tuple[int, int]:
    start = None
    end = None
    for index, page_text in enumerate(layout_pages[:40], start=1):
        if looks_like_toc_page(page_text):
            if start is None:
                start = index
            end = index
        elif start is not None and end is not None:
            break
    if start is None or end is None:
        raise RuntimeError("Unable to detect the printed table of contents.")
    return start, end


def is_lettered_section_title(title: str) -> bool:
    return bool(re.match(r"^[A-Za-z]\.\s+", title))


def is_numbered_title(title: str) -> bool:
    return bool(re.match(r"^\d+\s*[.)-]\s+", title))


def is_all_caps_heading(title: str) -> bool:
    letters = re.sub(r"[^A-Za-zÀ-ÖØ-öø-ÿ]+", "", title)
    return bool(letters) and letters.isupper()


def is_backmatter_title(title: str) -> bool:
    return keyify(title) in {"notes", "index"}


def is_generic_part_marker(title: str) -> bool:
    compact = keyify(title)
    return compact in {"part", "pt"} or bool(re.fullmatch(r"part[ivxlcdm]+", compact))


def normalize_arabic_toc_progression(entries: list[TocEntry]) -> None:
    last_page: int | None = None
    for entry in entries:
        if entry.numbering != "arabic" or not entry.page_label or not entry.page_label.isdigit():
            continue
        original_page = int(entry.page_label)
        corrected_page = original_page
        if last_page is not None and corrected_page < last_page:
            carry = 10 ** max(len(str(last_page)) - 1, 1)
            while corrected_page < last_page:
                corrected_page += carry
        if corrected_page != original_page:
            prefix_length = len(str(corrected_page)) - len(str(original_page))
            prefix_fragment = str(corrected_page)[:prefix_length] if prefix_length > 0 else ""
            if prefix_fragment and re.search(rf"\s+{re.escape(prefix_fragment)}$", entry.title):
                entry.title = re.sub(rf"\s+{re.escape(prefix_fragment)}$", "", entry.title).strip()
                entry.slug = slugify(entry.title)
            entry.page_label = str(corrected_page)
        last_page = int(entry.page_label)


def split_toc_title_page(line: str) -> tuple[str, str] | None:
    match = re.match(
        r"^(.*?)(?:\s{2,}|\s+)([ivxlcdm]+|\d(?:\s*\d){0,3})\s*$",
        clean_text_line(line),
        re.IGNORECASE,
    )
    if not match:
        return None
    title = clean_text_line(match.group(1))
    page_label = normalize_page_label_token(match.group(2))
    if not title or not page_label:
        return None
    return title, page_label


def has_unmatched_quote(text: str) -> bool:
    compact = clean_text_line(text)
    return compact.count('"') % 2 == 1 or compact.count("“") > compact.count("”")


def should_merge_toc_title_lines(current: str, following: str) -> bool:
    current_line = clean_text_line(current)
    following_line = clean_text_line(following)
    if not current_line or not following_line:
        return False
    if standalone_page_label(current_line) is not None or standalone_page_label(following_line) is not None:
        return False
    if likely_page_reference(current_line) or likely_page_reference(following_line):
        return False
    if is_punctuation_only_title_fragment(following_line):
        return True
    if current_line.endswith(("-", "/", ":", ";")):
        return True
    if has_unmatched_quote(current_line):
        return True
    last_token = last_alpha_token(current_line)
    if last_token and last_token.lower() in {"and", "of", "the", "to", "for", "in", "on", "from"}:
        return True
    return False


def merge_toc_title_fragments(current: str, following: str) -> str:
    merged = clean_text_line(f"{current} {following}")
    merged = re.sub(
        r'([.?!])\s*"\s*((?:\.\s*){2,})$',
        lambda match: f"{match.group(1)} {' '.join('.' for _ in re.findall(r'\.', match.group(2)))} \"",
        merged,
    )
    return merged


def coalesce_toc_title_lines(lines: list[str]) -> list[str]:
    coalesced: list[str] = []
    index = 0
    while index < len(lines):
        current = lines[index].rstrip()
        current_stripped = current.strip()
        if not current_stripped:
            index += 1
            continue

        if index + 2 < len(lines):
            following = lines[index + 1].rstrip()
            trailing = lines[index + 2].strip()
            trailing_page = standalone_page_label(trailing)
            if trailing_page and should_merge_toc_title_lines(current_stripped, following):
                merged = merge_toc_title_fragments(current_stripped, following.strip())
                coalesced.append(clean_text_line(f"{merged} {trailing_page}"))
                index += 3
                continue

        if index + 1 < len(lines):
            following = lines[index + 1].rstrip()
            following_stripped = following.strip()
            split_next = split_toc_title_page(following_stripped)
            if split_next and should_merge_toc_title_lines(current_stripped, split_next[0]):
                merged = merge_toc_title_fragments(current_stripped, split_next[0])
                coalesced.append(clean_text_line(f"{merged} {split_next[1]}"))
                index += 2
                continue
            following_page = standalone_page_label(following_stripped)
            if (
                following_page
                and not likely_page_reference(current_stripped)
                and len(keyify(current_stripped)) >= 6
            ):
                coalesced.append(clean_text_line(f"{current_stripped} {following_page}"))
                index += 2
                continue

        coalesced.append(current)
        index += 1
    return coalesced


def is_punctuation_only_title_fragment(title: str) -> bool:
    compact = clean_text_line(title)
    return bool(compact) and not re.search(r"[A-Za-z0-9]", compact)


def should_merge_following_toc_title(current: TocEntry, following: TocEntry) -> bool:
    if current.kind != "section" or following.kind != "section":
        return False
    if current.parent_id != following.parent_id:
        return False
    if current.page_label is not None or following.page_label is None:
        return False
    current_title = clean_text_line(current.title)
    following_title = clean_text_line(following.title)
    if not current_title or not following_title:
        return False
    if is_punctuation_only_title_fragment(following_title):
        return True
    last_token = last_alpha_token(current_title)
    if current_title.count('"') % 2 == 1 or current_title.count("“") > current_title.count("”"):
        return True
    if current_title.endswith(("-", "/", ":", ";")):
        return True
    if last_token and last_token.lower() in {"and", "of", "the", "to", "for", "in", "on", "from"}:
        return True
    return False


def merge_fragmented_toc_entries(entries: list[TocEntry]) -> list[TocEntry]:
    if len(entries) < 2:
        return entries
    merged: list[TocEntry] = []
    index = 0
    while index < len(entries):
        current = entries[index]
        if index + 1 < len(entries):
            following = entries[index + 1]
            if should_merge_following_toc_title(current, following):
                current.title = merge_toc_title_fragments(current.title, following.title)
                current.slug = slugify(current.title)
                current.page_label = following.page_label
                current.numbering = following.numbering
                index += 2
                merged.append(current)
                continue
        merged.append(current)
        index += 1
    return merged


def parse_toc_entries(layout_pages: list[str], toc_start: int, toc_end: int) -> list[TocEntry]:
    lines: list[str] = []
    for page_text in layout_pages[toc_start - 1 : toc_end]:
        lines.extend(page_text.splitlines())
    lines = coalesce_toc_title_lines(lines)

    entries: list[TocEntry] = []
    current_part_id: str | None = None
    current_division_id: str | None = None
    current_chapter_id: str | None = None
    pending_chapter: str | None = None
    pending_division_kind: str | None = None
    pending_division_marker: str | None = None
    pending_part_marker: str | None = None
    sequence = 0
    body_started = False

    def make_entry(
        kind: str,
        level: int,
        title: str,
        page_label: str | None,
        numbering: str,
        marker: str | None = None,
        parent_id: str | None = None,
    ) -> TocEntry:
        nonlocal sequence
        sequence += 1
        slug = slugify(title)
        entry_id = f"{kind}-{sequence:03d}-{slug}"
        entry = TocEntry(
            id=entry_id,
            kind=kind,
            level=level,
            title=title,
            page_label=page_label,
            numbering=numbering,
            marker=marker,
            parent_id=parent_id,
            sequence=sequence,
            slug=slug,
        )
        entries.append(entry)
        return entry

    for raw_line in lines:
        line = raw_line.rstrip()
        if not line.strip():
            continue

        compact_key = keyify(line)
        if compact_key in {"contents", "viiicontents", "ixcontents"} or (
            "contents" in compact_key and len(compact_key) <= 12
        ):
            continue
        if compact_key == "thispageintentionallyleftblank":
            continue

        page_match = re.match(
            r"^(.*?)(?:\s{2,}|\s+)([ivxlcdm]+|\d(?:\s*\d){0,3})\s*$",
            line.strip(),
            re.IGNORECASE,
        )
        page_label = normalize_page_label_token(page_match.group(2)) if page_match else None
        title_candidate = repair_symbolic_title_ocr(
            clean_text_line(page_match.group(1) if page_match else line)
        )
        numbering = (
            "arabic"
            if page_label and page_label.isdigit()
            else "roman"
            if page_label
            else "none"
        )
        if numbering == "arabic":
            body_started = True

        if compact_key.startswith("chapter") and re.search(r"\d+$", compact_key):
            chapter_number = re.search(r"(\d+)$", compact_key).group(1)
            pending_chapter = f"Chapter {chapter_number}"
            current_chapter_id = None
            continue

        if compact_key == "introduction":
            pending_division_kind = "introduction"
            pending_division_marker = "Introduction"
            current_division_id = None
            current_part_id = None
            current_chapter_id = None
            continue

        if compact_key == "epilogue":
            pending_division_kind = "epilogue"
            pending_division_marker = "Epilogue"
            current_division_id = None
            current_part_id = None
            current_chapter_id = None
            continue

        if is_generic_part_marker(title_candidate) and page_label:
            pending_part_marker = title_candidate
            current_chapter_id = None
            continue

        part_match = re.match(
            r"^PART\s+([IVXLCDM]+)\s*:\s*(.*?)\s+([ivxlcdm]+|\d+)$",
            title_candidate + (f" {page_label}" if page_label else ""),
            re.IGNORECASE,
        )
        if part_match and page_label:
            marker = f"Part {part_match.group(1).upper()}"
            title = clean_text_line(part_match.group(2))
            part_entry = make_entry(
                kind="part",
                level=1,
                title=title,
                page_label=page_label,
                numbering=numbering,
                marker=marker,
            )
            current_part_id = part_entry.id
            current_division_id = None
            current_chapter_id = None
            continue

        if pending_part_marker and page_label:
            marker = f"Part {sum(1 for entry in entries if entry.kind == 'part') + 1}"
            part_entry = make_entry(
                kind="part",
                level=1,
                title=title_candidate,
                page_label=page_label,
                numbering=numbering,
                marker=marker,
            )
            current_part_id = part_entry.id
            current_division_id = None
            current_chapter_id = None
            pending_part_marker = None
            continue

        if pending_division_kind and page_label:
            division_entry = make_entry(
                kind=pending_division_kind,
                level=1,
                title=title_candidate,
                page_label=page_label,
                numbering=numbering,
                marker=pending_division_marker,
            )
            current_division_id = division_entry.id
            current_part_id = None
            current_chapter_id = None
            pending_division_kind = None
            pending_division_marker = None
            continue

        if pending_chapter and page_label:
            marker = pending_chapter
            numbered_match = re.match(r"^(\d+)\s*[.)]\s+", title_candidate)
            if numbered_match:
                marker = f"Chapter {numbered_match.group(1)}"
            chapter_parent = current_part_id
            chapter_entry = make_entry(
                kind="chapter",
                level=2,
                title=title_candidate,
                page_label=page_label,
                numbering=numbering,
                marker=marker,
                parent_id=chapter_parent,
            )
            current_chapter_id = chapter_entry.id
            pending_chapter = None
            continue

        if page_label and is_all_caps_heading(title_candidate) and numbering == "arabic":
            part_entry = make_entry(
                kind="part",
                level=1,
                title=title_candidate,
                page_label=page_label,
                numbering=numbering,
                marker=f"Part {sum(1 for entry in entries if entry.kind == 'part') + 1}",
            )
            current_part_id = part_entry.id
            current_division_id = None
            current_chapter_id = None
            continue

        if page_label and is_numbered_title(title_candidate):
            chapter_parent = current_part_id or current_division_id
            chapter_number = re.match(r"^(\d+)", title_candidate).group(1)
            chapter_entry = make_entry(
                kind="chapter",
                level=2,
                title=title_candidate,
                page_label=page_label,
                numbering=numbering,
                marker=f"Chapter {chapter_number}",
                parent_id=chapter_parent,
            )
            current_chapter_id = chapter_entry.id
            continue

        if not page_label and is_numbered_title(title_candidate):
            chapter_parent = current_part_id or current_division_id
            chapter_number = re.match(r"^(\d+)", title_candidate).group(1)
            chapter_entry = make_entry(
                kind="chapter",
                level=2,
                title=title_candidate,
                page_label=None,
                numbering="none",
                marker=f"Chapter {chapter_number}",
                parent_id=chapter_parent,
            )
            current_chapter_id = chapter_entry.id
            continue

        if page_label and is_lettered_section_title(title_candidate):
            parent_id = current_chapter_id or current_division_id or current_part_id
            level = 3 if current_chapter_id else 2
            make_entry(
                kind="section",
                level=level,
                title=title_candidate,
                page_label=page_label,
                numbering=numbering,
                parent_id=parent_id,
            )
            continue

        if page_label and current_chapter_id and not is_backmatter_title(title_candidate):
            make_entry(
                kind="section",
                level=3,
                title=title_candidate,
                page_label=page_label,
                numbering=numbering,
                parent_id=current_chapter_id,
            )
            continue

        if (
            not page_label
            and current_chapter_id
            and not is_backmatter_title(title_candidate)
            and len(title_candidate) >= 6
        ):
            make_entry(
                kind="section",
                level=3,
                title=title_candidate,
                page_label=None,
                numbering="none",
                parent_id=current_chapter_id,
            )
            continue

        if page_label and numbering == "roman" and not body_started:
            make_entry(
                kind="frontmatter",
                level=1,
                title=title_candidate,
                page_label=page_label,
                numbering=numbering,
            )
            current_chapter_id = None
            continue

        if page_label:
            make_entry(
                kind="index",
                level=1,
                title=title_candidate,
                page_label=page_label,
                numbering=numbering,
            )

    entries = merge_fragmented_toc_entries(entries)
    normalize_arabic_toc_progression(entries)
    by_id = {entry.id: entry for entry in entries}
    for entry in entries:
        if entry.parent_id:
            by_id[entry.parent_id].children.append(entry.id)
    return entries


def extract_margin_page_number_candidates(
    page: fitz.Page,
    *,
    pdf_page: int,
    page_count: int,
) -> list[dict[str, Any]]:
    page_width = float(page.rect.width)
    page_height = float(page.rect.height)
    candidates: list[dict[str, Any]] = []
    for block in page.get_text("blocks"):
        x0, y0, x1, y1, text = block[:5]
        lines = [clean_text_line(line) for line in normalize_unicode(text).splitlines() if clean_text_line(line)]
        if len(lines) != 1:
            continue
        line = lines[0]
        if not re.fullmatch(r"\d{1,3}", line):
            continue
        if y0 > 82.0 and y1 < page_height - 82.0:
            continue
        book_page = int(line)
        if not (1 <= book_page <= page_count):
            continue
        candidates.append(
            {
                "pdf_page": pdf_page,
                "book_page": book_page,
                "text": line,
                "bbox": {
                    "x0": round(float(x0), 2),
                    "y0": round(float(y0), 2),
                    "x1": round(float(x1), 2),
                    "y1": round(float(y1), 2),
                },
                "is_outer_margin": bool(
                    float(x0) <= page_width * 0.24 or float(x1) >= page_width * 0.76
                ),
            }
        )
    if any(candidate.get("is_outer_margin") for candidate in candidates):
        return [candidate for candidate in candidates if candidate.get("is_outer_margin")]
    return candidates


def extract_legacy_page_number_candidates(
    page: fitz.Page,
    *,
    pdf_page: int,
    page_count: int,
) -> list[dict[str, Any]]:
    lines = [clean_text_line(line) for line in page.get_text("text").splitlines() if line.strip()]
    candidates: list[dict[str, Any]] = []
    for line in lines[:3] + lines[-3:]:
        if not re.fullmatch(r"\d{1,3}", line):
            continue
        book_page = int(line)
        if not (1 <= book_page <= page_count):
            continue
        candidates.append(
            {
                "pdf_page": pdf_page,
                "book_page": book_page,
                "text": line,
                "bbox": None,
            }
        )
        break
    return candidates


def select_monotonic_page_observations(candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not candidates:
        return []
    ordered = sorted(candidates, key=lambda item: (item["pdf_page"], item["book_page"]))
    best_lengths = [1] * len(ordered)
    best_span = [0] * len(ordered)
    previous_index = [-1] * len(ordered)

    for current_index, current in enumerate(ordered):
        for candidate_index, candidate in enumerate(ordered[:current_index]):
            if candidate["pdf_page"] >= current["pdf_page"]:
                continue
            if candidate["book_page"] >= current["book_page"]:
                continue
            pdf_gap = current["pdf_page"] - candidate["pdf_page"]
            book_gap = current["book_page"] - candidate["book_page"]
            if pdf_gap > max(18, book_gap * 5):
                continue
            length = best_lengths[candidate_index] + 1
            span = best_span[candidate_index] + (current["book_page"] - candidate["book_page"])
            if length > best_lengths[current_index] or (
                length == best_lengths[current_index] and span > best_span[current_index]
            ):
                best_lengths[current_index] = length
                best_span[current_index] = span
                previous_index[current_index] = candidate_index

    best_end = max(
        range(len(ordered)),
        key=lambda index: (best_lengths[index], best_span[index], ordered[index]["pdf_page"]),
    )
    selected: list[dict[str, Any]] = []
    while best_end != -1:
        selected.append(ordered[best_end])
        best_end = previous_index[best_end]
    selected.reverse()
    return selected


def dominant_offset_stats(offset_votes: Counter[int]) -> dict[str, Any]:
    if not offset_votes:
        return {
            "offset": None,
            "count": 0,
            "second_count": 0,
            "total": 0,
            "confidence": 0.0,
            "is_strong": False,
        }
    ranked = offset_votes.most_common()
    offset, count = ranked[0]
    second_count = ranked[1][1] if len(ranked) > 1 else 0
    total = sum(offset_votes.values())
    confidence = count / total if total else 0.0
    is_strong = (
        count >= 25
        and confidence >= 0.85
        and count >= max(10, second_count * 4)
    )
    return {
        "offset": offset,
        "count": count,
        "second_count": second_count,
        "total": total,
        "confidence": round(confidence, 4),
        "is_strong": is_strong,
    }


def filter_observations_by_offset(
    observations: list[dict[str, Any]],
    offset: int | None,
    *,
    tolerance: int = 1,
) -> list[dict[str, Any]]:
    if offset is None:
        return observations[:]
    return [
        observation
        for observation in observations
        if abs((observation["pdf_page"] - observation["book_page"]) - offset) <= tolerance
    ]


def choose_arabic_page_mapping_strategy(
    offset_votes: Counter[int],
    observations: list[dict[str, Any]],
) -> dict[str, Any]:
    stats = dominant_offset_stats(offset_votes)
    filtered_observations = filter_observations_by_offset(observations, stats["offset"])
    if stats["is_strong"] and filtered_observations:
        return {
            "mode": "global_offset",
            "arabic_offset": stats["offset"],
            "observations": filtered_observations,
            "dominant_offset": stats,
        }
    return {
        "mode": "observation_interpolation",
        "arabic_offset": stats["offset"],
        "observations": observations[:],
        "dominant_offset": stats,
    }


def interpolate_pdf_page_from_observations(
    observations: list[dict[str, Any]],
    book_page: int,
    *,
    page_count: int,
) -> int | None:
    if not observations:
        return None

    for observation in observations:
        if observation["book_page"] == book_page:
            return observation["pdf_page"]

    if book_page < observations[0]["book_page"]:
        if len(observations) >= 2:
            first, second = observations[0], observations[1]
            book_delta = max(second["book_page"] - first["book_page"], 1)
            pdf_delta = max(second["pdf_page"] - first["pdf_page"], 1)
            slope = pdf_delta / book_delta
        else:
            slope = 1.0
        estimate = round(observations[0]["pdf_page"] - (observations[0]["book_page"] - book_page) * slope)
        return max(1, min(page_count, estimate))

    for previous, current in zip(observations, observations[1:]):
        if not (previous["book_page"] <= book_page <= current["book_page"]):
            continue
        if current["book_page"] == previous["book_page"]:
            return previous["pdf_page"]
        fraction = (book_page - previous["book_page"]) / (current["book_page"] - previous["book_page"])
        estimate = round(previous["pdf_page"] + fraction * (current["pdf_page"] - previous["pdf_page"]))
        return max(1, min(page_count, estimate))

    if len(observations) >= 2:
        previous, current = observations[-2], observations[-1]
        book_delta = max(current["book_page"] - previous["book_page"], 1)
        pdf_delta = max(current["pdf_page"] - previous["pdf_page"], 1)
        slope = pdf_delta / book_delta
    else:
        slope = 1.0
    estimate = round(observations[-1]["pdf_page"] + (book_page - observations[-1]["book_page"]) * slope)
    return max(1, min(page_count, estimate))


def title_search_variants(title: str) -> list[str]:
    candidates = [title]
    stripped = re.sub(r"^\d+\s*[.)]\s+", "", title).strip()
    if stripped and stripped != title:
        candidates.append(stripped)
    stripped = re.sub(r"^[A-Z]\.\s+", "", title).strip()
    if stripped and stripped != title:
        candidates.append(stripped)
    stripped = re.sub(r"^[IVXLCDM]+\.\s+", "", title, flags=re.IGNORECASE).strip()
    if stripped and stripped != title:
        candidates.append(stripped)
    stripped = re.sub(r"\s+\d+$", "", title).strip()
    if stripped and stripped != title:
        candidates.append(stripped)
    normalized_ocr = re.sub(r"\bvv(?=[a-z])", "w", title, flags=re.IGNORECASE).strip()
    if normalized_ocr and normalized_ocr != title:
        candidates.append(normalized_ocr)
    variants = []
    for candidate in candidates:
        key = keyify(candidate)
        if len(key) >= 8 and key not in variants:
            variants.append(key)
    return variants


def refine_entry_pdf_page(
    entry: TocEntry,
    doc: fitz.Document,
    approximate_pdf_page: int | None,
    *,
    max_shift: int = 12,
    window_start: int | None = None,
    window_end: int | None = None,
) -> int | None:
    if entry.kind not in {"chapter", "section"}:
        return approximate_pdf_page
    variants = title_search_variants(entry.title)
    if not variants:
        return approximate_pdf_page

    if approximate_pdf_page is None:
        window_start = max(1, window_start or 1)
        window_end = min(len(doc), window_end or len(doc))
        best_page = window_start
        reference_page = window_start
    else:
        computed_start = max(1, approximate_pdf_page - max_shift)
        computed_end = min(len(doc), approximate_pdf_page + max_shift)
        window_start = max(computed_start, window_start or 1)
        window_end = min(computed_end, window_end or len(doc))
        best_page = approximate_pdf_page
        reference_page = approximate_pdf_page
    if window_end < window_start:
        return approximate_pdf_page
    best_score = -1
    best_distance = len(doc)

    for pdf_page in range(window_start, window_end + 1):
        page = doc[pdf_page - 1]
        line_items: list[dict[str, Any]] = []
        for block in page.get_text("dict").get("blocks", []):
            if "lines" not in block:
                continue
            for line in block["lines"]:
                spans = [span.get("text", "") for span in line.get("spans", []) if span.get("text", "").strip()]
                text = clean_text_line(" ".join(spans))
                if not text:
                    continue
                line_items.append(
                    {
                        "text": text,
                        "key": keyify(text),
                        "y0": float(line.get("bbox", (0.0, 0.0, 0.0, 0.0))[1]),
                    }
                )
        if not line_items:
            fallback_lines = [
                clean_text_line(line)
                for line in page.get_text("text").splitlines()
                if clean_text_line(line)
            ]
            line_items = [{"text": line, "key": keyify(line), "y0": 0.0} for line in fallback_lines]
        if not line_items:
            continue
        line_keys = [item["key"] for item in line_items if item["key"]]
        joined_key = keyify(" ".join(item["text"] for item in line_items[:160]))
        page_score = 0
        for variant in variants:
            if any(line_key == variant for line_key in line_keys):
                page_score = max(page_score, 100)
                continue
            if any(variant in line_key for line_key in line_keys):
                page_score = max(page_score, 85)
                continue
            if variant in joined_key:
                page_score = max(page_score, 70)
        if page_score <= 0:
            continue
        distance = abs(pdf_page - reference_page)
        if page_score > best_score or (page_score == best_score and distance < best_distance):
            best_page = pdf_page
            best_score = page_score
            best_distance = distance

    return best_page if best_score > 0 else approximate_pdf_page


def update_page_slice_bounds(
    page_slices: list[dict[str, Any]],
    pdf_page: int,
    *,
    min_y: float | None = None,
    max_y: float | None = None,
    drop: bool = False,
) -> None:
    for index, page_slice in enumerate(page_slices):
        if page_slice["pdf_page"] != pdf_page:
            continue
        if drop:
            page_slices.pop(index)
            return
        if min_y is not None:
            existing_min = page_slice.get("min_y")
            page_slice["min_y"] = min_y if existing_min is None else max(existing_min, min_y)
        if max_y is not None:
            existing_max = page_slice.get("max_y")
            page_slice["max_y"] = max_y if existing_max is None else min(existing_max, max_y)
        return


def neighboring_assigned_pdf_bounds(
    entries: list[TocEntry],
    index: int,
    *,
    page_count: int,
) -> tuple[int, int]:
    lower_bound = 1
    upper_bound = page_count
    for previous in reversed(entries[:index]):
        if previous.pdf_page is not None:
            lower_bound = max(1, previous.pdf_page)
            break
    for following in entries[index + 1 :]:
        if following.pdf_page is not None:
            upper_bound = min(page_count, following.pdf_page)
            break
    return lower_bound, upper_bound


def assign_pdf_pages(entries: list[TocEntry], doc: fitz.Document, page_count: int) -> dict[str, Any]:
    offset_votes: Counter[int] = Counter()
    candidate_evidence: list[dict[str, Any]] = []

    all_candidates: list[dict[str, Any]] = []
    legacy_candidates: list[dict[str, Any]] = []
    legacy_offset_votes: Counter[int] = Counter()
    for pdf_page, page in enumerate(doc, start=1):
        page_candidates = extract_margin_page_number_candidates(page, pdf_page=pdf_page, page_count=page_count)
        all_candidates.extend(page_candidates)
        for candidate in page_candidates:
            if candidate["book_page"] > 2:
                offset_votes[candidate["pdf_page"] - candidate["book_page"]] += 1
        if len(candidate_evidence) < 80:
            candidate_evidence.extend(page_candidates[: max(0, 80 - len(candidate_evidence))])
        fallback_candidates = extract_legacy_page_number_candidates(page, pdf_page=pdf_page, page_count=page_count)
        legacy_candidates.extend(fallback_candidates)
        for candidate in fallback_candidates:
            if candidate["book_page"] > 2:
                legacy_offset_votes[candidate["pdf_page"] - candidate["book_page"]] += 1

    raw_observations = select_monotonic_page_observations(all_candidates)
    observation_source = "margin"
    if not raw_observations:
        raw_observations = select_monotonic_page_observations(legacy_candidates)
        if raw_observations:
            candidate_evidence = legacy_candidates[:80]
            observation_source = "legacy"

    active_offset_votes = offset_votes if offset_votes else legacy_offset_votes
    strategy = choose_arabic_page_mapping_strategy(active_offset_votes, raw_observations)
    observations = strategy["observations"]
    arabic_offset = strategy["arabic_offset"]

    for entry in entries:
        if entry.page_label is None:
            continue
        if entry.numbering == "arabic":
            if strategy["mode"] == "global_offset":
                if arabic_offset is None:
                    raise RuntimeError("Unable to infer Arabic page locations from the document.")
                entry.pdf_page = int(entry.page_label) + arabic_offset
            else:
                approximate_pdf_page = interpolate_pdf_page_from_observations(
                    observations,
                    int(entry.page_label),
                    page_count=page_count,
                )
                if approximate_pdf_page is None:
                    if arabic_offset is None:
                        raise RuntimeError("Unable to infer Arabic page locations from the document.")
                    approximate_pdf_page = int(entry.page_label) + arabic_offset
                entry.pdf_page = approximate_pdf_page
        elif entry.numbering == "roman":
            entry.pdf_page = roman_to_int(entry.page_label)

    for index, entry in enumerate(entries):
        if entry.kind not in {"chapter", "section"}:
            continue
        lower_bound, upper_bound = neighboring_assigned_pdf_bounds(entries, index, page_count=page_count)
        if entry.pdf_page is None and lower_bound == upper_bound:
            entry.pdf_page = lower_bound
            continue
        if entry.pdf_page is None:
            approximate_pdf_page = lower_bound if lower_bound < upper_bound else None
            entry.pdf_page = refine_entry_pdf_page(
                entry,
                doc,
                approximate_pdf_page,
                max_shift=max(12, upper_bound - lower_bound),
                window_start=lower_bound,
                window_end=upper_bound,
            )
            continue
        entry.pdf_page = refine_entry_pdf_page(
            entry,
            doc,
            entry.pdf_page,
            window_start=lower_bound,
            window_end=upper_bound,
        )

    by_id = get_entry_by_id(entries)
    for entry in entries:
        if not entry.children:
            continue
        child_pages = [
            by_id[child_id].pdf_page
            for child_id in entry.children
            if by_id[child_id].pdf_page is not None
        ]
        if child_pages and (entry.pdf_page is None or entry.pdf_page > min(child_pages)):
            entry.pdf_page = min(child_pages)

    for index, entry in enumerate(entries):
        next_entry = entries[index + 1] if index + 1 < len(entries) else None
        next_pdf_page = next_entry.pdf_page if next_entry and next_entry.pdf_page else page_count + 1
        if next_entry and next_entry.pdf_page is not None and entry.pdf_page is not None:
            if next_entry.pdf_page == entry.pdf_page:
                entry.end_pdf_page = entry.pdf_page
                continue
        entry.end_pdf_page = next_pdf_page - 1

    return {
        "mode": strategy["mode"],
        "arabic_offset": arabic_offset,
        "offset_votes": dict(offset_votes or legacy_offset_votes),
        "dominant_offset": strategy["dominant_offset"],
        "observation_source": observation_source if raw_observations else None,
        "evidence": candidate_evidence[:40],
        "page_observations": observations[:80],
    }


def looks_like_person_name(line: str) -> bool:
    compact = normalize_title_line(clean_text_line(line))
    if not PERSON_LINE_RE.fullmatch(compact):
        return False
    first_token = compact.split()[0].lower()
    if first_token in {"of", "than", "or", "otherwise", "being", "beyond", "the", "and", "in", "on", "to", "from", "by"}:
        return False
    return True


def normalize_person_name(name: str) -> str:
    compact = normalize_title_line(clean_text_line(name).strip(" .;,"))
    compact = re.sub(r"\.(?=\s|$)", "", compact)
    compact = re.sub(r"\s+", " ", compact)
    return compact


def split_person_names(text: str) -> list[str]:
    names: list[str] = []
    for part in CONTRIBUTOR_SPLIT_RE.split(clean_text_line(text)):
        candidate = normalize_person_name(part)
        if looks_like_person_name(candidate):
            names.append(candidate)
    return names


def canonical_person_key(name: str) -> str:
    ascii_text = (
        unicodedata.normalize("NFKD", normalize_person_name(name))
        .encode("ascii", "ignore")
        .decode("ascii")
        .lower()
    )
    return re.sub(r"[^a-z]+", " ", ascii_text).strip()


def append_contributor(
    contributors: list[dict[str, Any]],
    *,
    name: str,
    role: str,
    page_number: int,
    source: str,
) -> None:
    normalized_name = normalize_person_name(name)
    if not normalized_name:
        return
    if any(
        contributor["name"] == normalized_name and contributor["role"] == role
        for contributor in contributors
    ):
        return
    contributors.append(
        {
            "name": normalized_name,
            "role": role,
            "source_page": page_number,
            "source_text": clean_text_line(source),
        }
    )


def contributor_role_from_line(line: str) -> tuple[str, str] | None:
    compact = clean_text_line(line)
    lowered = compact.lower()
    patterns = [
        ("translator", r"^translated(?: from .+?)? by\s+(.+)$"),
        ("introduction", r"^with an introduction by\s+(.+)$"),
        ("foreword", r"^foreword by\s+(.+)$"),
        ("editor", r"^(?:edited by|editor)\s+(.+)$"),
    ]
    for role, pattern in patterns:
        match = re.match(pattern, lowered, re.IGNORECASE)
        if match:
            source_tail = compact[match.start(1) : match.end(1)]
            return role, source_tail
    return None


def extract_author_from_line(line: str, *, allow_plain: bool = True) -> str | None:
    compact = clean_text_line(line)
    if not compact:
        return None
    byline = BYLINE_AUTHOR_RE.match(compact)
    if byline:
        words = normalize_person_name(byline.group("name")).split()
        cleaned_words: list[str] = []
        stop_words = {"Corrected", "Edition", "Translated", "Press", "University"}
        for word in words:
            if word in stop_words:
                break
            if not re.fullmatch(PERSON_TOKEN_PATTERN, word):
                break
            cleaned_words.append(word)
        if len(cleaned_words) >= 2:
            return " ".join(cleaned_words)
        return None
    catalog = CATALOG_PERSON_RE.match(compact)
    if catalog:
        if compact.isupper():
            return None
        return normalize_person_name(f"{catalog.group('first')} {catalog.group('last')}")
    normalized = normalize_person_name(compact)
    if allow_plain and looks_like_person_name(normalized):
        return normalized
    return None


def line_is_metadata_noise(line: str) -> bool:
    key = keyify(line)
    if not key:
        return True
    blocked = (
        "contents",
        "copyright",
        "libraryofcongress",
        "cataloginginpublication",
        "isbn",
        "allrightsreserved",
        "printedinthe",
    )
    return any(token in key for token in blocked)


def line_is_publisher_candidate(line: str) -> bool:
    compact = clean_text_line(line)
    if not compact or any(char.isdigit() for char in compact):
        return False
    if compact.lower().startswith(("www", "ww.", "http")):
        return False
    return bool(PUBLISHER_LINE_RE.search(compact))


def extract_publisher_name(line: str) -> str | None:
    compact = clean_text_line(line)
    if compact.lower().startswith("published by "):
        compact = compact[13:].strip()
    lowered = compact.lower()
    if " by " in lowered:
        tail = compact[lowered.rfind(" by ") + 4 :].strip(" ,;.")
        if tail and not any(char.isdigit() for char in tail):
            tail_match = PUBLISHER_LINE_RE.search(tail)
            if tail_match:
                return normalize_title_line(tail_match.group("publisher").strip(" ,;."))
            return normalize_title_line(tail)
    match = PUBLISHER_LINE_RE.search(compact)
    if not match:
        return None
    publisher = match.group("publisher").strip(" ,;.")
    return normalize_title_line(publisher)


def infer_publication_place(line: str, publisher: str | None) -> str | None:
    compact = clean_text_line(line)
    if not compact or not publisher:
        return None
    if compact.lower().startswith("published by "):
        compact = compact[13:].strip()
    if publisher not in compact:
        return None
    remainder = compact.split(publisher, 1)[1].strip(" ,;")
    if not remainder:
        return None
    remainder = re.sub(r"\b\d{4,5}(?:-\d{4})?\b", "", remainder).strip(" ,;")
    if not remainder:
        return None
    return normalize_title_line(remainder)


def line_is_probable_title(line: str) -> bool:
    compact = clean_text_line(line)
    if not compact or not TITLE_LINE_RE.search(compact):
        return False
    word_count = len(compact.split())
    if word_count > 12:
        return False
    if word_count == 1:
        return False
    if compact.islower():
        return False
    if compact.startswith(("'", '"')) or "..." in compact or " . . " in compact:
        return False
    if line_is_metadata_noise(compact):
        return False
    if contributor_role_from_line(compact):
        return False
    if extract_author_from_line(compact):
        return False
    if line_is_publisher_candidate(compact):
        return False
    lowered = compact.lower()
    if lowered.startswith(("originally published", "first published", "published by")):
        return False
    return True


def title_score(lines: list[str], author_name: str | None, page_number: int) -> int:
    score = 0
    if author_name:
        score += 4
    score += sum(3 for line in lines if line.isupper())
    score += max(0, 4 - abs(len(lines) - 2))
    score += sum(2 for line in lines if 1 <= len(line.split()) <= 6)
    score += max(0, 6 - page_number)
    if len(lines) == 1 and len(lines[0].split()) >= 4:
        score += 6
    if len(lines) > 1 and sum(1 for line in lines if len(line.split()) == 1) >= len(lines) - 1:
        score -= 8
    if len(lines) > 1 and all(len(line.split()) <= 3 for line in lines):
        score -= 6
    return score


def collect_split_person_name(lines: list[str], start_index: int) -> tuple[str | None, int]:
    parts: list[str] = []
    index = start_index
    stop_keys = {"correctededition", "translatedby", "by", "editedby", "forewordby", "withanintroductionby"}
    while index < len(lines):
        candidate = normalize_title_line(lines[index])
        key = keyify(candidate)
        if key in stop_keys or line_is_publisher_candidate(candidate) or contributor_role_from_line(candidate):
            break
        if len(candidate.split()) > 4 or any(char.isdigit() for char in candidate):
            break
        parts.append(candidate)
        index += 1
        joined = " ".join(parts)
        if looks_like_person_name(joined):
            return joined, index
    joined = " ".join(parts)
    if looks_like_person_name(joined):
        return joined, index
    return None, start_index


def parse_title_page(layout_pages: list[str]) -> dict[str, Any]:
    best: dict[str, Any] = {}
    best_score = -1
    for page_number, page_text in enumerate(layout_pages[:10], start=1):
        raw_lines = [clean_text_line(line) for line in page_text.splitlines() if line.strip()]
        if not raw_lines:
            continue
        if page_number == 1:
            first_page_titles = [normalize_title_line(line) for line in raw_lines if line_is_probable_title(line)]
            if len(first_page_titles) == 1 and len(first_page_titles[0].split()) >= 2:
                return {
                    "title": first_page_titles[0],
                    "subtitle": None,
                    "author_line": None,
                    "page": page_number,
                }
        if sum(1 for line in raw_lines if line_is_metadata_noise(line)) >= 2:
            continue
        lines = [normalize_title_line(line) for line in raw_lines]
        for index, line in enumerate(lines):
            raw_line = raw_lines[index]
            author_name = extract_author_from_line(raw_line, allow_plain=False)
            if not author_name and looks_like_person_name(normalize_person_name(line)):
                previous_line = lines[index - 1] if index > 0 else ""
                previous_is_contributor = bool(contributor_role_from_line(previous_line)) or previous_line.lower().endswith("and")
                preceding_titles = any(
                    line_is_probable_title(item) for item in lines[max(0, index - 2) : index]
                )
                following_titles = any(
                    line_is_probable_title(item) for item in lines[index + 1 : index + 4]
                )
                if following_titles and not preceding_titles and not previous_is_contributor:
                    author_name = normalize_person_name(line)
            if not author_name:
                continue
            after = [item for item in lines[index + 1 :] if line_is_probable_title(item)]
            before = [item for item in lines[:index] if line_is_probable_title(item)]
            title_lines = after[:3] if after else before[:3]
            if not title_lines:
                continue
            title = title_lines[0]
            subtitle = " ".join(title_lines[1:]) or None
            score = title_score(title_lines, author_name, page_number)
            if score > best_score:
                best_score = score
                best = {
                    "title": title,
                    "subtitle": subtitle,
                    "author_line": author_name,
                    "page": page_number,
                }
        title_only_lines = [line for line in lines if line_is_probable_title(line)]
        if 1 <= len(title_only_lines) <= 3:
            title = title_only_lines[0]
            subtitle = " ".join(title_only_lines[1:]) or None
            score = title_score(title_only_lines, None, page_number)
            if score > best_score:
                best_score = score
                best = {
                    "title": title,
                    "subtitle": subtitle,
                    "author_line": None,
                    "page": page_number,
                }
    return best


def repair_symbolic_title_ocr(text: str) -> str:
    return re.sub(
        r"\bThe Outside\s*[^\w\s\"'.,;:!?/\-\[\]()]+\s*the Inside\b",
        "The Outside )( the Inside",
        text,
        flags=re.IGNORECASE,
    )


def normalize_title_line(line: str) -> str:
    stripped = repair_symbolic_title_ocr(clean_text_line(line))
    if stripped.isupper():
        small_words = {"a", "an", "and", "as", "at", "for", "in", "of", "on", "or", "the", "to"}
        parts = stripped.lower().split()
        normalized: list[str] = []
        for index, part in enumerate(parts):
            if index > 0 and part in small_words:
                normalized.append(part)
            else:
                normalized.append(part.capitalize())
        return " ".join(normalized)
    return stripped


def harvest_frontmatter_metadata(layout_pages: list[str]) -> dict[str, Any]:
    authors: list[str] = []
    contributors: list[dict[str, Any]] = []
    title_candidates: list[dict[str, Any]] = []
    publisher_candidates: list[dict[str, Any]] = []
    year_candidates: list[dict[str, Any]] = []

    for page_number, page_text in enumerate(layout_pages[:20], start=1):
        lines = [clean_text_line(line) for line in page_text.splitlines() if line.strip()]
        if not lines:
            continue
        probable_titles = [normalize_title_line(line) for line in lines if line_is_probable_title(line)]
        if probable_titles:
            title_candidates.append(
                {
                    "page": page_number,
                    "title": probable_titles[0],
                    "subtitle": " ".join(probable_titles[1:3]) or None,
                    "score": title_score(probable_titles[:3], None, page_number),
                }
            )

        pending_contributor_role: str | None = None
        for index, line in enumerate(lines):
            key = keyify(line)
            if key == "by":
                split_name, end_index = collect_split_person_name(lines, index + 1)
                if split_name and split_name not in authors:
                    authors.append(split_name)
                if end_index > index + 1:
                    continue
            if key == "translatedby":
                split_name, end_index = collect_split_person_name(lines, index + 1)
                if split_name:
                    append_contributor(
                        contributors,
                        name=split_name,
                        role="translator",
                        page_number=page_number,
                        source=f"{line} {split_name}",
                    )
                if end_index > index + 1:
                    continue
            if pending_contributor_role and looks_like_person_name(normalize_person_name(line)):
                append_contributor(
                    contributors,
                    name=normalize_person_name(line),
                    role=pending_contributor_role,
                    page_number=page_number,
                    source=line,
                )
                pending_contributor_role = None
                continue
            contributor_match = contributor_role_from_line(line)
            if contributor_match:
                role, source_tail = contributor_match
                source_tail = re.sub(r"\band\s*$", "", source_tail, flags=re.IGNORECASE).strip(" ,;")
                for name in split_person_names(source_tail):
                    append_contributor(
                        contributors,
                        name=name,
                        role=role,
                        page_number=page_number,
                        source=line,
                    )
                if clean_text_line(line).lower().endswith("and"):
                    pending_contributor_role = role
                continue
            author_name = extract_author_from_line(line, allow_plain=False)
            if author_name and author_name not in authors:
                authors.append(author_name)
            elif looks_like_person_name(normalize_person_name(line)):
                previous_line = lines[index - 1] if index > 0 else ""
                previous_is_contributor = bool(contributor_role_from_line(previous_line)) or previous_line.lower().endswith("and")
                next_lines = [
                    normalize_title_line(item)
                    for item in lines[index + 1 : index + 4]
                    if line_is_probable_title(item)
                ]
                if next_lines and not previous_is_contributor:
                    author_name = normalize_person_name(line)
                    if author_name not in authors:
                        authors.append(author_name)
            publisher = extract_publisher_name(line)
            if publisher:
                publisher_candidates.append(
                    {
                        "publisher": publisher,
                        "publication_place": infer_publication_place(line, publisher),
                        "page": page_number,
                        "source_text": line,
                    }
                )
            year_patterns = [
                (100, r"(?:corrected edition|first paperback edition printing|routledge classics)\D+(\d{4})"),
                (95, r"(?:first published in english|first american edition)\D+(\d{4})"),
                (90, r"(?:first published)\D+(\d{4})"),
                (80, r"copyright[^0-9]*(\d{4})(?:[^0-9]+(\d{4}))?(?:[^0-9]+(\d{4}))?"),
                (70, r"originally published[^0-9]*(\d{4})"),
            ]
            lowered = clean_text_line(line).lower()
            for priority, pattern in year_patterns:
                match = re.search(pattern, lowered, re.IGNORECASE)
                if not match:
                    continue
                years = [int(value) for value in match.groups() if value]
                if not years:
                    continue
                selected_year = max(years) if priority >= 80 else years[0]
                year_candidates.append(
                    {
                        "year": selected_year,
                        "priority": priority,
                        "page": page_number,
                        "source_text": line,
                    }
                )
                break

    title_candidates.sort(key=lambda item: (item["score"], -item["page"]), reverse=True)
    publisher_candidates.sort(key=lambda item: (-item["page"], len(item["publisher"])), reverse=True)
    year_candidates.sort(key=lambda item: (item["priority"], item["year"]), reverse=True)
    return {
        "title": title_candidates[0]["title"] if title_candidates else None,
        "subtitle": title_candidates[0]["subtitle"] if title_candidates else None,
        "title_source": title_candidates[0] if title_candidates else None,
        "authors": authors,
        "contributors": contributors,
        "publisher": publisher_candidates[0]["publisher"] if publisher_candidates else None,
        "publication_place": publisher_candidates[0]["publication_place"] if publisher_candidates else None,
        "publisher_source": publisher_candidates[0] if publisher_candidates else None,
        "publication_year": year_candidates[0]["year"] if year_candidates else None,
        "publication_year_source": year_candidates[0] if year_candidates else None,
    }


def parse_library_of_congress(layout_pages: list[str]) -> dict[str, Any]:
    joined = "\n".join(layout_pages[:20])
    loc_key = "libraryofcongresscataloginginpublicationdata"
    start = keyify(joined).find(loc_key)
    if start == -1:
        return {}
    lines = [clean_text_line(line) for line in joined.splitlines()]
    loc_start_index = None
    for index, line in enumerate(lines):
        if keyify(line) == loc_key:
            loc_start_index = index
            break
    if loc_start_index is None:
        return {}
    section: list[str] = []
    for line in lines[loc_start_index : loc_start_index + 40]:
        if (
            line.startswith("This book has been composed")
            or line.startswith("http://")
            or line.startswith("Printed in the")
            or line.startswith("Published by")
        ):
            break
        section.append(line)
    info: dict[str, Any] = {"raw_lines": section}

    citation_line = next(
        (
            line
            for line in section
            if " / " in line and not line.lower().startswith("translated by")
        ),
        None,
    )
    if citation_line:
        title_part, author_part = citation_line.split(" / ", 1)
        title_part = title_part.strip().rstrip(" ;.")
        author_part = author_part.split(";", 1)[0].strip().rstrip(".")
        if ":" in title_part:
            title, subtitle = [part.strip() for part in title_part.split(":", 1)]
            info["title"] = normalize_title_line(title)
            info["subtitle"] = normalize_title_line(subtitle)
        else:
            info["title"] = normalize_title_line(title_part)
        author_name = extract_author_from_line(author_part)
        if author_name:
            info["author"] = author_name

    author_line = next(
        (
            line
            for line in section
            if CATALOG_PERSON_RE.match(clean_text_line(line)) and not any(char.isdigit() for char in line)
        ),
        None,
    )
    if author_line:
        info["author_catalog_entry"] = extract_author_from_line(author_line)
        if not info.get("author"):
            info["author"] = info["author_catalog_entry"]

    isbn_matches = re.findall(r"ISBN\s+([0-9Xx-]+)(?:\s*\(([^)]+)\))?", "\n".join(section))
    if isbn_matches:
        info["isbns"] = [
            {"isbn": isbn.strip(), "label": label.strip() if label else None}
            for isbn, label in isbn_matches
        ]

    subjects: list[str] = []
    for line in section:
        if re.match(r"^\d+\.\s+", line):
            for match in re.finditer(r"(\d+)\.\s*(.*?)(?=(?:\s+\d+\.\s)|$)", line):
                subject = match.group(2).strip()
                subject = re.sub(r"\s+I\.\s+Title\.?$", "", subject).strip().rstrip(".")
                subject = re.sub(r"\.?\s*Title\.?$", "", subject).strip().rstrip(".")
                if subject:
                    subjects.append(subject)
    if subjects:
        info["subjects"] = subjects

    call_number = None
    for index, line in enumerate(section):
        if re.match(r"^[A-Z]{1,3}\d", line):
            call_number = line
            if index + 1 < len(section) and re.fullmatch(r"\d{4}", section[index + 1]):
                call_number = f"{call_number} {section[index + 1]}"
            break
    if call_number:
        info["loc_call_number"] = call_number

    dewey_line = None
    for index, line in enumerate(section):
        if re.search(r"\bdc\d+\b", line.lower()):
            dewey_line = line
            if index + 1 < len(section) and re.fullmatch(r"\d{2}-\d+", section[index + 1]):
                dewey_line = f"{dewey_line} {section[index + 1]}"
            break
    if dewey_line:
        info["dewey_decimal"] = dewey_line

    return info


def parse_publication_details(layout_pages: list[str]) -> dict[str, Any]:
    lines = [clean_text_line(line) for line in "\n".join(layout_pages[:20]).splitlines() if line.strip()]
    info: dict[str, Any] = {}
    for line in lines:
        lowered = line.lower()
        if lowered.startswith("copyright"):
            years = [int(match) for match in re.findall(r"(\d{4})", line)]
            if years and "publication_year_line" not in info:
                info["publication_year"] = max(years)
            info["copyright_line"] = line
        explicit_year_patterns = [
            r"(?:corrected edition|first paperback edition printing|routledge classics)\D+(\d{4})",
            r"(?:first published in english|first american edition)\D+(\d{4})",
            r"(?:first published)\D+(\d{4})",
        ]
        for pattern in explicit_year_patterns:
            match = re.search(pattern, lowered, re.IGNORECASE)
            if match:
                info["publication_year"] = int(match.group(1))
                info["publication_year_line"] = line
                break
        if lowered.startswith("published by ") or line_is_publisher_candidate(line):
            publisher_line = line.removeprefix("Published by ").strip()
            info["publisher_line"] = publisher_line
            publisher = extract_publisher_name(publisher_line)
            if not publisher:
                continue
            info["publisher"] = publisher
            address = publisher_line.split(publisher, 1)[1].strip(", ") if publisher in publisher_line else ""
            if address:
                info["publisher_address"] = address
            place = infer_publication_place(line, publisher)
            if place:
                info["publication_place"] = place
    return info


def build_citation_metadata(layout_pages: list[str]) -> dict[str, Any]:
    title_page = parse_title_page(layout_pages)
    harvested = harvest_frontmatter_metadata(layout_pages)
    loc = parse_library_of_congress(layout_pages)
    publication = parse_publication_details(layout_pages)

    title = title_page.get("title") or harvested.get("title") or loc.get("title")
    subtitle = title_page.get("subtitle") or loc.get("subtitle")
    if not subtitle and not title_page.get("title"):
        subtitle = harvested.get("subtitle")
    authors: list[str] = []
    author_keys: set[str] = set()
    primary_author_candidates = [title_page.get("author_line"), loc.get("author")]
    fallback_author_candidates = harvested.get("authors") or []
    active_author_candidates = (
        primary_author_candidates
        if any(candidate for candidate in primary_author_candidates)
        else fallback_author_candidates
    )
    for candidate in active_author_candidates:
        canonical_key = canonical_person_key(candidate) if candidate else None
        if candidate and canonical_key and canonical_key not in author_keys:
            authors.append(candidate)
            author_keys.add(canonical_key)

    contributors: list[dict[str, Any]] = []
    for author in authors:
        append_contributor(
            contributors,
            name=author,
            role="author",
            page_number=title_page.get("page") or 0,
            source=title_page.get("title") or title or author,
        )
    for contributor in harvested.get("contributors", []):
        append_contributor(
            contributors,
            name=contributor["name"],
            role=contributor["role"],
            page_number=contributor["source_page"],
            source=contributor["source_text"],
        )

    publisher = publication.get("publisher") or harvested.get("publisher")
    publication_place = publication.get("publication_place") or harvested.get("publication_place")
    publication_year = publication.get("publication_year") or harvested.get("publication_year")

    provenance = {
        "title": title_page if title_page.get("title") else harvested.get("title_source") or loc.get("raw_lines"),
        "authors": [
            contributor
            for contributor in contributors
            if contributor.get("role") == "author"
        ],
        "publisher": publication if publication.get("publisher") else harvested.get("publisher_source"),
        "publication_year": publication.get("publication_year_line")
        or publication.get("copyright_line")
        or harvested.get("publication_year_source"),
    }

    citation: dict[str, Any] = {
        "title": title,
        "subtitle": subtitle,
        "authors": authors,
        "contributors": contributors,
        "publisher": publisher,
        "publication_place": publication_place,
        "publication_year": publication_year,
        "isbns": loc.get("isbns", []),
        "subjects": loc.get("subjects", []),
        "loc_call_number": loc.get("loc_call_number"),
        "dewey_decimal": loc.get("dewey_decimal"),
        "title_page_source": title_page,
        "frontmatter_harvest": harvested,
        "cataloging_source": loc,
        "publication_source": publication,
        "metadata_provenance": provenance,
    }

    if title and authors and publisher and publication_year:
        primary_author = authors[0]
        place = publication_place
        title_bits = title
        if subtitle:
            title_bits = f"{title}: {subtitle}"
        if place:
            citation["recommended_citation"] = (
                f"{primary_author}. {title_bits}. {place}: {publisher}, {publication_year}."
            )
        else:
            citation["recommended_citation"] = (
                f"{primary_author}. {title_bits}. {publisher}, {publication_year}."
            )
    return citation


def analyze_page_layout(page: fitz.Page, raw_text: str) -> dict[str, Any]:
    lines: list[dict[str, Any]] = []
    span_sizes: list[float] = []
    blocks = page.get_text("dict").get("blocks", [])
    for block in blocks:
        if block.get("type") != 0:
            continue
        for line in block.get("lines", []):
            spans = line.get("spans", [])
            text = clean_text_line("".join(span.get("text", "") for span in spans))
            if not text:
                continue
            bbox = line.get("bbox", [0, 0, 0, 0])
            size = sum(span.get("size", 0.0) for span in spans) / max(len(spans), 1)
            span_sizes.append(size)
            lines.append(
                {
                    "text": text,
                    "x0": bbox[0],
                    "y0": bbox[1],
                    "x1": bbox[2],
                    "y1": bbox[3],
                    "size": round(size, 2),
                }
            )

    if not lines:
        return {"kind": "blank", "complex": False, "reasons": []}

    body_lines = [line for line in lines if line["y0"] >= 45]
    if not body_lines:
        body_lines = lines
    rounded_x = Counter(round(line["x0"] / 24) * 24 for line in body_lines)
    cluster_count = len([cluster for cluster, count in rounded_x.items() if count >= 2])
    short_line_ratio = sum(len(line["text"]) < 26 for line in body_lines) / max(len(body_lines), 1)
    main_size = Counter(round(size, 1) for size in span_sizes).most_common(1)[0][0]
    smaller_lines = sum(line["size"] < main_size - 0.7 for line in body_lines)
    smaller_ratio = smaller_lines / max(len(body_lines), 1)
    right_column_lines = sum(line["x0"] >= 180 for line in body_lines)
    table_like = "table " in normalize_unicode(raw_text).lower()

    reasons: list[str] = []
    kind = "simple"
    complex_layout = False

    if table_like:
        kind = "table"
        complex_layout = True
        reasons.append("contains table marker")
    elif right_column_lines >= 8 and smaller_ratio >= 0.10:
        kind = "aside"
        complex_layout = True
        reasons.append("narrow right-side text zone")
    elif cluster_count >= 3 and short_line_ratio >= 0.35:
        kind = "multi-column"
        complex_layout = True
        reasons.append("multiple x-position clusters")

    return {
        "kind": kind,
        "complex": complex_layout,
        "reasons": reasons,
        "body_line_count": len(body_lines),
        "x_clusters": dict(rounded_x),
        "main_font_size": main_size,
    }


def strip_layout_header(text: str) -> str:
    lines = [line.rstrip() for line in text.replace("\f", "").splitlines()]
    while lines and not lines[0].strip():
        lines.pop(0)
    if lines:
        first = clean_text_line(lines[0])
        if re.search(r"\b\d+\b", first) and len(first) <= 90:
            lines.pop(0)
            while lines and not lines[0].strip():
                lines.pop(0)
    while lines and not lines[-1].strip():
        lines.pop()
    return "\n".join(lines).strip()


def trim_leading_titles(lines: list[str], skip_keys: set[str]) -> list[str]:
    remaining = lines[:]
    while remaining:
        head = clean_text_line(remaining[0])
        if not head:
            remaining.pop(0)
            continue
        if keyify(head) in skip_keys or head.isdigit():
            remaining.pop(0)
            continue
        break
    return remaining


def reflow_block_text(text: str) -> str:
    lines = [clean_text_line(line) for line in normalize_unicode(text).splitlines()]
    paragraphs: list[str] = []
    current: list[str] = []

    def flush() -> None:
        if current:
            paragraphs.append(" ".join(current).strip())
            current.clear()

    for line in lines:
        if not line:
            flush()
            continue
        if current and current[-1].endswith("-") and re.match(r"^[A-Za-z0-9]", line):
            current[-1] = current[-1][:-1] + line
            continue
        if current and repeated_boundary_token(current[-1], line):
            current[-1] = join_continued_rag_text(current[-1], line, "duplicate")
            continue
        current.append(line)
    flush()
    return "\n\n".join(paragraphs).strip()


def render_simple_page(page: fitz.Page, skip_keys: set[str]) -> str:
    parts: list[str] = []
    for block in page.get_text("blocks"):
        x0, y0, x1, y1, text = block[:5]
        cleaned = reflow_block_text(text)
        if not cleaned:
            continue
        block_key = keyify(cleaned)
        if should_skip_top_margin_line(cleaned, y0):
            continue
        if block_key in skip_keys:
            continue
        if cleaned.isdigit():
            continue
        parts.append(cleaned)
    return "\n\n".join(parts).strip()


def yaml_frontmatter(data: dict[str, Any]) -> str:
    lines = ["---"]
    for key, value in data.items():
        if isinstance(value, list):
            lines.append(f"{key}:")
            for item in value:
                lines.append(f"  - {json.dumps(item, ensure_ascii=False)}")
        elif value is None:
            lines.append(f"{key}: null")
        else:
            lines.append(f"{key}: {json.dumps(value, ensure_ascii=False)}")
    lines.append("---")
    return "\n".join(lines)


def get_entry_by_id(entries: list[TocEntry]) -> dict[str, TocEntry]:
    return {entry.id: entry for entry in entries}


def assign_output_paths(entries: list[TocEntry]) -> None:
    by_id = get_entry_by_id(entries)
    part_counts = 0
    chapter_counts: dict[str, int] = Counter()

    for entry in entries:
        if entry.kind == "frontmatter":
            entry.output_path = f"frontmatter/{entry.slug}.md"
            continue
        if entry.kind == "introduction":
            entry.output_dir = "body/introduction"
            entry.output_path = "body/introduction/index.md"
            continue
        if entry.kind == "part":
            part_counts += 1
            entry.output_dir = f"body/part-{part_counts:02d}-{entry.slug}"
            entry.output_path = f"{entry.output_dir}/index.md"
            continue
        if entry.kind == "chapter":
            parent = by_id.get(entry.parent_id or "")
            chapter_counts[parent.id if parent else "root"] += 1
            chapter_number = chapter_counts[parent.id if parent else "root"]
            prefix = parent.output_dir if parent and parent.output_dir else "body"
            entry.output_dir = f"{prefix}/chapter-{chapter_number:02d}-{entry.slug}"
            entry.output_path = f"{entry.output_dir}/index.md"
            continue
        if entry.kind == "section":
            parent = by_id.get(entry.parent_id or "")
            base_dir = parent.output_dir if parent and parent.output_dir else "body"
            letter_match = re.match(r"^([A-Z])\.\s+", entry.title)
            letter_prefix = f"{letter_match.group(1).lower()}-" if letter_match else ""
            section_slug = entry.slug
            if letter_match:
                section_slug = slugify(re.sub(r"^[A-Z]\.\s+", "", entry.title))
            entry.output_path = f"{base_dir}/{letter_prefix}{section_slug}.md"
            continue
        if entry.kind == "epilogue":
            entry.output_path = f"body/epilogue-{entry.slug}.md"
            continue
        if entry.kind == "index":
            entry.output_path = f"body/indexes/{entry.slug}.md"
    seen_paths: Counter[str] = Counter(entry.output_path for entry in entries if entry.output_path)
    path_occurrence: Counter[str] = Counter()
    for entry in entries:
        if not entry.output_path or seen_paths[entry.output_path] == 1:
            continue
        original_path = entry.output_path
        path_occurrence[original_path] += 1
        path_obj = Path(original_path)
        hints = [
            slugify(entry.page_label or ""),
            f"{entry.sequence:02d}",
            f"{path_occurrence[original_path]:02d}",
        ]
        for hint in hints:
            if not hint:
                continue
            candidate = str(path_obj.with_name(f"{path_obj.stem}-{hint}{path_obj.suffix}"))
            if candidate not in seen_paths:
                entry.output_path = candidate
                seen_paths[candidate] += 1
                break


def get_ancestors(entry: TocEntry, by_id: dict[str, TocEntry]) -> list[TocEntry]:
    ancestors: list[TocEntry] = []
    current = by_id.get(entry.parent_id or "")
    while current:
        ancestors.append(current)
        current = by_id.get(current.parent_id or "")
    ancestors.reverse()
    return ancestors


def heading_skip_keys(entry: TocEntry, by_id: dict[str, TocEntry]) -> set[str]:
    keys = {
        keyify(entry.title),
        keyify(entry.display_title),
        keyify(entry.marker or ""),
    }
    parent = by_id.get(entry.parent_id or "")
    if parent:
        keys.update(
            {
                keyify(parent.title),
                keyify(parent.display_title),
                keyify(parent.marker or ""),
            }
        )
    return {key for key in keys if key}


def entry_heading_keys(entry: TocEntry) -> set[str]:
    return {
        key
        for key in {
            *title_search_variants(entry.title),
            *title_search_variants(entry.display_title),
            keyify(entry.marker or ""),
            keyify(re.sub(r"^\d+\s*[.)-]?\s*", "", entry.title).strip()),
            keyify(re.sub(r"^[A-Z]\.\s*", "", entry.title).strip()),
            keyify(re.sub(r"^[IVXLCDM]+\.\s*", "", entry.title, flags=re.IGNORECASE).strip()),
        }
        if key
    }


def entry_heading_variants(entry: TocEntry) -> list[str]:
    candidates = [entry.title, entry.display_title]
    for source in (entry.title, entry.display_title):
        candidates.extend(
            [
                re.sub(r"^\d+\s*[.)-]?\s*", "", source).strip(),
                re.sub(r"^[A-Z]\.\s*", "", source).strip(),
                re.sub(r"^[IVXLCDM]+\.\s*", "", source, flags=re.IGNORECASE).strip(),
            ]
        )
    variants: list[str] = []
    seen: set[str] = set()
    for candidate in candidates:
        cleaned = clean_text_line(candidate)
        if not cleaned:
            continue
        normalized = normalize_unicode(cleaned).lower()
        if normalized in seen:
            continue
        seen.add(normalized)
        variants.append(cleaned)
    return variants


def detect_entry_self_heading_band(entry: TocEntry, page: fitz.Page) -> tuple[float, float] | None:
    return detect_heading_band(
        page,
        entry_heading_keys(entry),
        prefer="last",
        prefix_variants=entry_heading_variants(entry),
        mode="hybrid",
    )


def detect_entry_heading_band(
    entry: TocEntry,
    previous_entry: TocEntry | None,
    page: fitz.Page,
    by_id: dict[str, TocEntry],
) -> tuple[float, float] | None:
    self_band = detect_entry_self_heading_band(entry, page)
    if self_band is not None:
        return self_band
    return detect_heading_band(page, heading_skip_keys(entry, by_id), prefer="first")


def detect_entry_start_cutoff(
    entry: TocEntry,
    previous_entry: TocEntry | None,
    page: fitz.Page,
    by_id: dict[str, TocEntry],
) -> float | None:
    band = detect_entry_heading_band(entry, previous_entry, page, by_id)
    if not band:
        return None
    if boundary_overlap_mode() in {"conservative", "hybrid"}:
        return band[1]
    return max(0.0, band[0])


def entry_context_label(entry: TocEntry, by_id: dict[str, TocEntry]) -> str | None:
    ancestors = get_ancestors(entry, by_id)
    if not ancestors:
        return None
    return " > ".join(ancestor.display_title for ancestor in ancestors)


def entry_flat_context_tokens(entry: TocEntry, by_id: dict[str, TocEntry]) -> list[str]:
    tokens: list[str] = []
    for ancestor in get_ancestors(entry, by_id):
        if ancestor.output_dir:
            tokens.append(Path(ancestor.output_dir).name)
        elif ancestor.output_path:
            tokens.append(Path(ancestor.output_path).stem)
        else:
            tokens.append(slugify(ancestor.display_title))
    if entry.kind == "section":
        letter_match = re.match(r"^([A-Z])\.\s+(.*)$", entry.title)
        if letter_match:
            tokens.append(f"section-{letter_match.group(1).lower()}-{slugify(letter_match.group(2))}")
        else:
            tokens.append(f"section-{entry.slug}")
    elif entry.output_path:
        tokens.append(Path(entry.output_path).stem)
    else:
        tokens.append(entry.slug)
    return tokens


def build_spatial_relative_path(relative_md_path: str) -> str:
    md_path = Path(relative_md_path)
    return str(Path("spatial") / md_path.parent / f"{md_path.stem}.layout.json")


def build_flat_leaf_relative_path(
    book_id: str,
    entry: TocEntry,
    by_id: dict[str, TocEntry],
    start_label: str | None,
    end_label: str | None,
) -> str:
    tokens = [book_id, *entry_flat_context_tokens(entry, by_id)]
    if start_label:
        page_span = f"pp-{start_label}" if not end_label or end_label == start_label else f"pp-{start_label}-{end_label}"
        tokens.append(slugify(page_span))
    filename = "__".join(token for token in tokens if token)
    return f"flat/leaf-nodes/{filename}.md"


def build_rag_leaf_relative_path(
    book_id: str,
    entry: TocEntry,
    by_id: dict[str, TocEntry],
    start_label: str | None,
    end_label: str | None,
) -> str:
    tokens = [book_id, *entry_flat_context_tokens(entry, by_id)]
    if start_label:
        page_span = f"pp-{start_label}" if not end_label or end_label == start_label else f"pp-{start_label}-{end_label}"
        tokens.append(slugify(page_span))
    filename = "__".join(token for token in tokens if token)
    return f"rag/leaf-nodes/{filename}.md"


def first_alpha_token(text: str) -> str | None:
    match = ALPHA_TOKEN_RE.search(clean_text_line(text))
    return match.group(0) if match else None


def last_alpha_token(text: str) -> str | None:
    tokens = ALPHA_TOKEN_RE.findall(clean_text_line(text))
    return tokens[-1] if tokens else None


def page_content_mode(entry_kind: str, layout_kind: str) -> str:
    if entry_kind == "index":
        return "index"
    if layout_kind == "table":
        return "table"
    return "prose"


def is_note_apparatus_fragment(text: str) -> bool:
    compact = clean_text_line(text)
    if not compact:
        return False
    if is_reference_note_text(compact):
        return True
    lowered = compact.lower()
    if lowered in {"chapter", "wn"}:
        return True
    if re.fullmatch(r"(?:[ivxlcdm]+|[0-9]+[.)]?)", lowered):
        return True
    if re.fullmatch(r"(?:cf\.|supra|infra|op\. cit\.)", lowered):
        return True
    if compact.startswith(".") and len(compact) <= 24:
        return True
    if compact.isupper() and len(compact.split()) <= 2:
        return True
    if len(compact) <= 18 and re.search(r"\d", compact):
        return True
    return False


def infer_page_content_mode(
    entry_kind: str,
    entry_title: str,
    layout_kind: str,
    regions: list[dict[str, Any]],
) -> str:
    content_mode = page_content_mode(entry_kind, layout_kind)
    if content_mode != "prose":
        return content_mode
    classification_regions = regions
    if micro_region_mode() == "group_first" and len(regions) >= 2:
        classification_regions = []
        pending: dict[str, Any] | None = None
        for region in regions:
            region_text = clean_text_line(region.get("raw_text", ""))
            region_bbox = region.get("bbox", {})
            if pending is None:
                pending = {
                    "raw_text": region_text,
                    "bbox": region_bbox,
                    "role": region.get("role"),
                }
                continue
            pending_bbox = pending.get("bbox") or {}
            same_role = pending.get("role") == region.get("role")
            y_gap = float(region_bbox.get("y0", 0.0)) - float(pending_bbox.get("y1", 0.0))
            if (
                same_role
                and y_gap <= 14.0
                and len(region_text.split()) <= 6
                and len(clean_text_line(pending.get("raw_text", "")).split()) <= 6
            ):
                pending["raw_text"] = clean_text_line(f"{pending['raw_text']} {region_text}")
                pending["bbox"] = {
                    "x0": min(float(pending_bbox.get("x0", 0.0)), float(region_bbox.get("x0", 0.0))),
                    "y0": min(float(pending_bbox.get("y0", 0.0)), float(region_bbox.get("y0", 0.0))),
                    "x1": max(float(pending_bbox.get("x1", 0.0)), float(region_bbox.get("x1", 0.0))),
                    "y1": max(float(pending_bbox.get("y1", 0.0)), float(region_bbox.get("y1", 0.0))),
                }
                continue
            classification_regions.append(pending)
            pending = {
                "raw_text": region_text,
                "bbox": region_bbox,
                "role": region.get("role"),
            }
        if pending is not None:
            classification_regions.append(pending)
    texts = [clean_text_line(region.get("raw_text", "")) for region in classification_regions]
    texts = [text for text in texts if text]
    if not texts:
        return content_mode
    micro_texts = [text for text in texts if len(text) <= 24 or len(text.split()) <= 4]
    note_like = sum(1 for text in texts if is_note_apparatus_fragment(text))
    title_slug = slugify(entry_title or "")
    if title_slug in {"notes", "index"} and len(micro_texts) >= 4 and note_like >= 3:
        return "index"
    if layout_kind == "aside" and len(micro_texts) >= 6 and note_like >= max(4, len(micro_texts) // 2):
        return "index"
    return content_mode


def looks_incomplete_rag_tail(text: str) -> bool:
    compact = clean_text_line(text)
    if not compact:
        return False
    if compact.endswith("-"):
        return True
    if compact.endswith((",", ";", ":", "(", "[", "—")):
        return True
    if RAG_TERMINAL_PUNCTUATION_RE.search(compact):
        return False
    tail = last_alpha_token(compact)
    if tail and tail.lower() in RAG_DANGLING_END_WORDS:
        return True
    return True


def starts_like_rag_continuation(text: str) -> bool:
    compact = clean_text_line(text)
    if not compact:
        return False
    first = compact[0]
    if first.islower():
        return True
    if first in ',;:)]}’"\'-':
        return True
    return False


def repeated_boundary_token(left: str, right: str) -> str | None:
    left_token = last_alpha_token(left)
    right_token = first_alpha_token(right)
    if not left_token or not right_token:
        return None
    if left_token.lower() != right_token.lower():
        return None
    if left_token.lower() not in RAG_DUPLICATE_BOUNDARY_WORDS:
        return None
    return right_token


def join_continued_rag_text(left: str, right: str, mode: str) -> str:
    left_text = left.rstrip()
    right_text = right.lstrip()
    if mode == "hyphen" and left_text.endswith("-"):
        return f"{left_text[:-1]}{right_text}".strip()
    duplicate = repeated_boundary_token(left_text, right_text) if mode == "duplicate" else None
    if duplicate:
        right_text = re.sub(rf"^\s*{re.escape(duplicate)}\b", "", right_text, count=1, flags=re.IGNORECASE).lstrip()
    if not right_text:
        return left_text
    return f"{left_text} {right_text}".strip()


def suppress_duplicate_boundary_lead(left: str, right: str) -> str:
    duplicate = repeated_boundary_token(left, right)
    if not duplicate:
        return right.strip()
    return re.sub(
        rf"^\s*{re.escape(duplicate)}\b",
        "",
        right,
        count=1,
        flags=re.IGNORECASE,
    ).strip()


def obvious_fragment_continuation(left: str, right: str) -> str | None:
    if clean_text_line(left).endswith("-") and re.match(r"^[A-Za-z0-9]", clean_text_line(right)):
        return "hyphen"
    if repeated_boundary_token(left, right):
        return "duplicate"
    if looks_incomplete_rag_tail(left) and (
        starts_like_rag_continuation(right)
        or len(clean_text_line(right).split()) <= 7
    ):
        return "space"
    return None


def looks_like_prose_fragment(text: str) -> bool:
    compact = clean_text_line(text)
    if not compact:
        return False
    if is_note_apparatus_fragment(compact):
        return False
    if INLINE_NOTE_MARKER_RE.match(compact):
        return False
    if re.fullmatch(r"[A-Z][A-Z .&/-]*", compact) and len(compact) <= 32:
        return False
    return True


def x_positions_compatible(previous: dict[str, Any], current: dict[str, Any]) -> bool:
    mode = prose_join_mode()
    if previous["zone"] == current["zone"]:
        return True
    x0_limit = 48.0 if mode == "conservative" else 60.0 if mode == "balanced" else 84.0
    x1_limit = 96.0 if mode == "conservative" else 120.0 if mode == "balanced" else 156.0
    if abs(previous["x0"] - current["x0"]) <= x0_limit:
        return True
    if abs(previous["x1"] - current["x1"]) <= x1_limit:
        return True
    return False


def y_positions_compatible(previous: dict[str, Any], current: dict[str, Any]) -> bool:
    mode = prose_join_mode()
    previous_page = int(previous.get("pdf_page") or 0)
    current_page = int(current.get("pdf_page") or previous_page)
    if not previous_page:
        previous_page = current_page
    page_gap = current_page - previous_page
    if page_gap == 0:
        y_gap = current["y0"] - previous["y1"]
        max_gap = 20.0 if mode == "conservative" else 28.0 if mode == "balanced" else 40.0
        return -2.0 <= y_gap <= max_gap
    if page_gap == 1:
        min_prev = 470.0 if mode == "conservative" else 430.0 if mode == "balanced" else 395.0
        max_current = 72.0 if mode == "conservative" else 90.0 if mode == "balanced" else 110.0
        return previous["y1"] >= min_prev and current["y0"] <= max_current
    return False


def evaluate_prose_region_join(
    previous: dict[str, Any],
    current: dict[str, Any],
    *,
    content_mode: str,
) -> dict[str, Any]:
    result: dict[str, Any] = {"join": False, "considered": False, "rejection_reason": None}
    if content_mode != "prose":
        result["rejection_reason"] = "non-prose-page"
        return result
    previous_text = previous.get("raw_text") or previous.get("semantic_text") or ""
    current_text = current.get("raw_text") or current.get("semantic_text") or ""
    if not clean_text_line(previous_text) or not clean_text_line(current_text):
        result["rejection_reason"] = "empty-fragment"
        return result
    page_gap = int(current.get("pdf_page") or previous.get("pdf_page") or 0) - int(previous.get("pdf_page") or current.get("pdf_page") or 0)
    if page_gap not in {0, 1}:
        result["rejection_reason"] = "page-gap"
        return result
    result["considered"] = True
    if not looks_like_prose_fragment(previous_text) or not looks_like_prose_fragment(current_text):
        result["rejection_reason"] = "non-prose-fragment"
        return result
    if not x_positions_compatible(previous, current):
        result["rejection_reason"] = "x-incompatible"
        return result
    if not y_positions_compatible(previous, current):
        result["rejection_reason"] = "y-incompatible"
        return result

    join_mode: str | None = None
    reasons: list[str] = []
    previous_compact = clean_text_line(previous_text)
    current_compact = clean_text_line(current_text)

    if previous_compact.endswith("-") and re.match(r"^[A-Za-z0-9]", current_compact):
        join_mode = "hyphen"
        reasons.append("hyphenated predecessor")
    else:
        duplicate = repeated_boundary_token(previous_text, current_text)
        if duplicate and (looks_incomplete_rag_tail(previous_text) or starts_like_rag_continuation(current_text)):
            join_mode = "duplicate"
            reasons.append(f"duplicate boundary token {duplicate.lower()}")
        elif looks_incomplete_rag_tail(previous_text) and (
            starts_like_rag_continuation(current_text)
            or len(current_compact.split()) <= 7
            or current_compact[:1] in {'"', "'", "“", "(", "["}
            or (
                prose_join_mode() == "aggressive"
                and len(current_compact.split()) <= 5
                and current_compact[:1].isupper()
            )
        ):
            join_mode = "space"
            reasons.append("incomplete predecessor")

    if not join_mode:
        result["rejection_reason"] = "no-continuation-signal"
        return result

    result.update({"join": True, "join_mode": join_mode, "reasons": reasons})
    return result


def assess_prose_region_join(
    previous: dict[str, Any],
    current: dict[str, Any],
    *,
    content_mode: str,
) -> dict[str, Any] | None:
    decision = evaluate_prose_region_join(previous, current, content_mode=content_mode)
    return decision if decision.get("join") else None


def assess_rag_continuation(previous: dict[str, Any], current: dict[str, Any]) -> dict[str, Any] | None:
    if previous.get("anchor_label") or current.get("anchor_label"):
        return None
    if previous.get("content_mode") != "prose" or current.get("content_mode") != "prose":
        return None
    if is_reference_note_text(previous["rag_text"]) or is_reference_note_text(current["rag_text"]):
        return None
    if current["pdf_page"] - previous["pdf_page"] not in {0, 1}:
        return None
    if not x_positions_compatible(previous, current):
        return None
    if not y_positions_compatible(previous, current):
        return None

    previous_text = previous["rag_text"]
    current_text = current["rag_text"]
    reasons: list[str] = []
    join_mode: str | None = None

    if clean_text_line(previous_text).endswith("-") and re.match(r"^[A-Za-z0-9]", clean_text_line(current_text)):
        join_mode = "hyphen"
        reasons.append("hyphenated predecessor")
    else:
        duplicate = repeated_boundary_token(previous_text, current_text)
        if duplicate and (looks_incomplete_rag_tail(previous_text) or starts_like_rag_continuation(current_text)):
            join_mode = "duplicate"
            reasons.append(f"duplicate boundary token {duplicate.lower()}")
        elif looks_incomplete_rag_tail(previous_text) and (
            starts_like_rag_continuation(current_text)
            or len(clean_text_line(current_text).split()) <= 7
        ):
            join_mode = "space"
            reasons.append("incomplete predecessor")

    if not join_mode:
        return None

    return {
        "join_mode": join_mode,
        "reasons": reasons,
    }


def annotate_rag_continuations(flattened: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if len(flattened) < 2:
        return flattened
    for previous, current in zip(flattened, flattened[1:]):
        decision = assess_rag_continuation(previous, current)
        if not decision:
            continue
        previous["continuation_to_next"] = decision
        current["continuation_from_prev"] = {
            **decision,
            "region_id": previous.get("region_id"),
        }
        current["inherits_bucket_from_previous"] = True
        current["continuation_join_mode"] = decision["join_mode"]
        previous_ref = previous.get("fragment_ref") or previous.get("region_ref")
        current_ref = current.get("fragment_ref") or current.get("region_ref")
        if previous_ref is not None:
            previous_ref["continuation_to_next"] = {
                "region_id": current.get("region_id"),
                "join_mode": decision["join_mode"],
                "reasons": decision["reasons"],
            }
        if current_ref is not None:
            current_ref["continuation_from_prev"] = {
                "region_id": previous.get("region_id"),
                "join_mode": decision["join_mode"],
                "reasons": decision["reasons"],
            }
            current_ref["inherits_bucket_from_previous"] = True
    return flattened


def annotate_reference_note_continuations(flattened: list[dict[str, Any]]) -> list[dict[str, Any]]:
    previous_by_page: dict[int, dict[str, Any]] = {}
    for region in flattened:
        pdf_page = int(region.get("pdf_page") or 0)
        if not pdf_page:
            continue
        seed = bool(
            is_reference_note_text(region["rag_text"])
            and region.get("y0", 0.0) >= BOTTOM_REFERENCE_CONTINUATION_Y0
        )
        previous = previous_by_page.get(pdf_page)
        inline_note_body = bool(
            previous
            and abs(float(previous.get("y0", 0.0)) - float(region.get("y0", 0.0))) <= 8.0
            and abs(float(previous.get("x0", 0.0)) - float(region.get("x0", 0.0))) <= 18.0
            and float(region.get("x1", 0.0)) - float(previous.get("x1", 0.0)) >= 120.0
        )
        same_note_band = bool(
            previous
            and (
                previous.get("zone") == region.get("zone")
                or (
                    abs(float(previous.get("x0", 0.0)) - float(region.get("x0", 0.0))) <= 18.0
                    and abs(float(previous.get("x1", 0.0)) - float(region.get("x1", 0.0))) <= 48.0
                )
                or inline_note_body
            )
        )
        continuation = bool(
            previous
            and (
                previous.get("reference_note_seed")
                or previous.get("reference_note_continuation")
            )
            and same_note_band
            and region.get("y0", 0.0) >= BOTTOM_REFERENCE_CONTINUATION_Y0
            and region.get("y0", 0.0) - previous.get("y1", 0.0) <= 20.0
        )
        if seed:
            region["reference_note_seed"] = True
        if continuation:
            region["reference_note_continuation"] = True
            diagnostic_ref = region.get("fragment_ref") or region.get("region_ref")
            if diagnostic_ref is not None:
                diagnostic_ref["reference_note_continuation"] = True
        previous_by_page[pdf_page] = region
    return flattened


def normalize_rag_region_text(region: dict[str, Any]) -> str:
    raw_text = normalize_unicode(region.get("raw_text") or region.get("semantic_text") or "")
    cleaned_lines: list[str] = []
    for line in raw_text.splitlines():
        stripped = re.sub(r"^[-*•]\s*", "", line.strip())
        cleaned = clean_text_line(stripped)
        if cleaned:
            cleaned_lines.append(cleaned)
    if not cleaned_lines:
        return ""
    return reflow_block_text("\n".join(cleaned_lines))


def split_leading_source_ref(remainder: str) -> tuple[str, str]:
    compact = clean_text_line(remainder)
    if not compact:
        return "", ""
    if compact.startswith("["):
        closing = compact.find("]")
        if closing != -1:
            source_ref = compact[: closing + 1].strip()
            tail = compact[closing + 1 :].strip()
            return source_ref, tail
    author_match = LEADING_AUTHOR_SOURCE_REF_RE.match(compact)
    if author_match:
        return clean_text_line(author_match.group("ref") or ""), clean_text_line(author_match.group("tail") or "")
    if len(compact) <= 42 and SHORT_SOURCE_REF_RE.match(compact):
        return compact, ""
    return "", compact


def parse_passage_anchor(text: str) -> tuple[str, str, str] | None:
    match = PASSAGE_ANCHOR_RE.match(text.strip())
    if not match:
        return None
    label = match.group("label").lower()
    remainder = clean_text_line(match.group("rest") or "")
    source_ref, citation_seed = split_leading_source_ref(remainder)
    return label, source_ref, citation_seed


def is_marker_only_anchor_text(text: str) -> bool:
    anchor = parse_passage_anchor(text)
    if not anchor:
        return False
    _, source_ref, citation_seed = anchor
    return not source_ref and not citation_seed


def should_attach_fragment_to_next_anchor(
    region: dict[str, Any],
    next_anchor_region: dict[str, Any] | None,
    *,
    distance_to_next_anchor: float | None,
) -> tuple[bool, str | None]:
    if next_anchor_region is None:
        return False, None
    if distance_to_next_anchor is None or distance_to_next_anchor > 18.0:
        return False, None
    if is_reference_note_text(region["rag_text"]):
        return False, None
    compact = clean_text_line(region["rag_text"])
    if not compact or not looks_incomplete_rag_lead(compact):
        return False, None
    if len(compact.split()) > 10:
        return False, None
    if region.get("source_region_id") == next_anchor_region.get("source_region_id"):
        return True, "embedded-anchor-fragment"
    if region["zone"] != next_anchor_region["zone"]:
        return True, "cross-zone-next-anchor"
    if is_marker_only_anchor_text(next_anchor_region["rag_text"]):
        return True, "marker-only-next-anchor"
    return False, None


def split_rag_region_fragments(region: dict[str, Any], rag_text: str) -> list[dict[str, Any]]:
    split_points = [
        match.start()
        for match in EMBEDDED_PASSAGE_ANCHOR_RE.finditer(rag_text)
        if match.start() > 0
    ]
    segments: list[str] = []
    start = 0
    for split_at in split_points:
        before = rag_text[start:split_at].strip()
        if before:
            segments.append(before)
        start = split_at
    tail = rag_text[start:].strip()
    if tail:
        segments.append(tail)
    if not segments:
        segments = [rag_text.strip()]

    fragment_refs: list[dict[str, Any]] = []
    for index, segment in enumerate(segments, start=1):
        anchor = parse_passage_anchor(segment)
        fragment_refs.append(
            {
                "fragment_id": f"{region.get('region_id')}.f{index:02d}",
                "rag_text": segment,
                "anchor_label": anchor[0] if anchor else None,
            }
        )
    return fragment_refs


def is_reference_note_text(text: str) -> bool:
    compact = clean_text_line(text)
    if not compact:
        return False
    if len(compact) <= 16 and re.fullmatch(r"[A-Z][A-Z .&/-]*", compact):
        return True
    if len(compact) <= 40 and re.fullmatch(r"[\[\]0-9A-Za-z .,/–—\-]+", compact) and re.search(r"\d", compact):
        return True
    if len(compact) <= 50 and re.search(r"\b(?:Levinas|Derrida)\b", compact) and re.search(r"\d", compact):
        return True
    if len(compact) <= 24 and compact.startswith("[") and compact.endswith("]"):
        return True
    return False


def looks_incomplete_rag_lead(text: str) -> bool:
    compact = clean_text_line(text)
    if not compact:
        return False
    if compact.endswith("-"):
        return True
    if compact.endswith((",", ";", ":", "(", "[", "—")):
        return True
    if re.search(r'[.!?]["”\')\]]?$', compact):
        return False
    return True


def classify_rag_region(region: dict[str, Any], citation_zone: str | None, passage_label: str | None) -> str:
    text = region["rag_text"]
    if is_reference_note_text(text) or region.get("reference_note_continuation"):
        return "reference"
    if citation_zone is None:
        return "commentary" if region["role"] in {"main", "table"} else "reference"
    if region.get("before_page_anchor") and region.get("page_first_anchor_label") and region.get("page_first_anchor_label") != passage_label:
        return "commentary"
    if region["zone"] == citation_zone:
        return "citation"
    if region["layout_kind"] in {"aside", "multi-column", "table"}:
        return "commentary"
    if citation_zone == "left" and region["zone"] == "center":
        return "commentary"
    return "commentary"


def infer_passage_citation_zone(flattened: list[dict[str, Any]], anchor_index: int, anchor_region: dict[str, Any]) -> str:
    if anchor_region["zone"] != "center":
        return anchor_region["zone"]
    anchor_text = anchor_region["rag_text"]
    anchor = parse_passage_anchor(anchor_text)
    if anchor and anchor[2]:
        return anchor_region["zone"]
    for follow in flattened[anchor_index + 1 :]:
        if follow.get("anchor_label"):
            break
        if follow.get("page_label") != anchor_region.get("page_label"):
            break
        distance = follow["y0"] - anchor_region["y0"]
        if distance > 12.0:
            break
        if follow["zone"] != anchor_region["zone"] and not is_reference_note_text(follow["rag_text"]):
            return follow["zone"]
    return anchor_region["zone"]


def is_why_comment_commentaries_entry(entry: TocEntry) -> bool:
    return (entry.output_path or "").endswith("chapter-05-why-comment/c-commentaries.md")


def force_region_rag_bucket(
    region: dict[str, Any],
    bucket: str,
    *,
    reason: str,
) -> None:
    region["forced_rag_bucket"] = bucket
    region["rag_bucket_override_reason"] = reason


def repair_why_comment_inset_quote_spatial_pages(
    entry: TocEntry,
    spatial_pages: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    if not spatial_pages or not is_why_comment_commentaries_entry(entry):
        return spatial_pages

    for page in spatial_pages:
        page_label = str(page.get("page_label") or "")
        regions = page.get("regions") or []
        if not regions:
            continue

        if page_label == "127":
            note_start_y = None
            next_anchor_y = None
            for region in regions:
                text = clean_text_line(region.get("raw_text", ""))
                if note_start_y is None and text.startswith("8) Erubin 13b"):
                    note_start_y = float(region.get("bbox", {}).get("y0", 0.0))
                if next_anchor_y is None and text.startswith("7d)"):
                    next_anchor_y = float(region.get("bbox", {}).get("y0", 0.0))

            if note_start_y is not None and next_anchor_y is not None:
                for region in regions:
                    text = clean_text_line(region.get("raw_text", ""))
                    bbox = region.get("bbox", {})
                    y0 = float(bbox.get("y0", 0.0))
                    x0 = float(bbox.get("x0", 0.0))
                    x1 = float(bbox.get("x1", 0.0))
                    if y0 < note_start_y or y0 >= next_anchor_y:
                        continue

                    if text.startswith(
                        (
                            "8) Erubin 13b",
                            "R. Abba said that Samuel said:",
                            "Shammai and Beth Hillel disputed,",
                            "they [one side] said:",
                            "according to us’ and they [the",
                            "others] said:",
                            "saying: “These and these are the",
                            "words of the living God, but the rul-",
                            "to have the ruling fixed according to",
                            "them?—Because they were kindly",
                            "and modest. They studied their own",
                            "Since, however, “These and these",
                            "words and the words of Beth",
                        )
                    ) or x0 >= 228.0:
                        force_region_rag_bucket(
                            region,
                            "reference",
                            reason="why-comment-inset-quote",
                        )
                        continue

                    if x0 <= 60.0 and x1 <= 260.0:
                        force_region_rag_bucket(
                            region,
                            "commentary",
                            reason="why-comment-lower-left-commentary",
                        )

        if page_label == "129":
            heading_y0 = None
            for region in regions:
                text = clean_text_line(region.get("raw_text", ""))
                if text == "SUGGESTED READINGS":
                    heading_y0 = float(region.get("bbox", {}).get("y0", 0.0))
                    break
            if heading_y0 is not None:
                for region in regions:
                    y0 = float(region.get("bbox", {}).get("y0", 0.0))
                    if y0 < heading_y0:
                        continue
                    force_region_rag_bucket(
                        region,
                        "reference",
                        reason="why-comment-suggested-readings-tail",
                    )
            continue

        if page_label == "130":
            for region in regions:
                force_region_rag_bucket(
                    region,
                    "reference",
                    reason="why-comment-suggested-readings-tail",
                )
            continue

        if page_label == "128":
            for region in regions:
                text = clean_text_line(region.get("raw_text", ""))
                if text == "9 Levinas TN 198–99/168–69":
                    force_region_rag_bucket(
                        region,
                        "reference",
                        reason="why-comment-footnote-nine",
                    )

    return spatial_pages


def should_move_commentary_tail_to_next(
    previous: dict[str, Any],
    current: dict[str, Any],
    *,
    aggressive: bool = False,
) -> bool:
    if not previous.get("commentary_parts") or not current.get("commentary_parts"):
        return False
    previous_tail = clean_text_line(previous["commentary_parts"][-1])
    current_head = clean_text_line(current["commentary_parts"][0])
    if not previous_tail or not current_head:
        return False
    if re.search(r'[.!?]["”\')\]]?$', previous_tail):
        return False
    split_candidate = split_trailing_commentary_fragment(previous_tail) if aggressive else None
    if not split_candidate and (len(previous_tail) > 160 or len(previous_tail.split()) > 24):
        return False
    if not re.match(r'^[a-z(\["“]', current_head):
        return False
    previous_pages = previous.get("pdf_pages") or []
    current_pages = current.get("pdf_pages") or []
    if previous_pages and current_pages and current_pages[0] - previous_pages[-1] > 1:
        return False
    return True


def has_repeated_passage_labels(passages: list[dict[str, Any]]) -> bool:
    labels = [passage.get("label") for passage in passages if passage.get("label")]
    return len(labels) != len(set(labels))


def split_trailing_commentary_fragment(text: str) -> tuple[str, str] | None:
    compact = text.strip()
    if not compact or RAG_TERMINAL_PUNCTUATION_RE.search(compact):
        return None
    split_at = None
    for match in re.finditer(r'[.!?]["”\')\]]?\s+', compact):
        split_at = match.end()
    if split_at is None:
        return None
    head = compact[:split_at].rstrip()
    tail = compact[split_at:].strip()
    if not tail:
        return None
    return head, tail


def looks_like_bibliography_tail(text: str) -> bool:
    compact = clean_text_line(text)
    if not compact:
        return False
    has_author = bool(re.search(r"\b[A-Z][A-Za-z'’.-]+,\s+[A-Z][A-Za-z'’.-]+", compact))
    has_biblio_marker = bool(
        re.search(
            r"\b(?:Press|University|Companion|Trans\.|ed\.|Routledge|Minuit|SUNY|MIT)\b",
            compact,
        )
    )
    return has_author and has_biblio_marker


def looks_like_bibliography_lead(text: str) -> bool:
    compact = clean_text_line(text)
    if not compact:
        return False
    return bool(re.match(r"^[A-Z][A-Za-z'’.-]+,\s+[A-Z][A-Za-z'’.-]+", compact))


def move_trailing_bibliography_to_reference(passages: list[dict[str, Any]]) -> None:
    for passage in passages:
        commentary_parts = passage.get("commentary_parts") or []
        reference_parts = passage.get("reference_parts") or []
        if not commentary_parts or not reference_parts:
            continue
        moved: list[str] = []
        while commentary_parts:
            candidate = commentary_parts[-1]
            if not (
                looks_like_bibliography_tail(candidate)
                or looks_like_bibliography_lead(candidate)
            ):
                break
            moved.insert(0, commentary_parts.pop())
        if moved:
            passage["reference_parts"] = [*moved, *reference_parts]


def repair_passage_commentary_boundaries(passages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if len(passages) < 2:
        move_trailing_bibliography_to_reference(passages)
        return passages
    aggressive = has_repeated_passage_labels(passages)
    for index in range(1, len(passages)):
        previous = passages[index - 1]
        current = passages[index]
        if not should_move_commentary_tail_to_next(previous, current, aggressive=aggressive):
            continue
        previous_tail = previous["commentary_parts"][-1]
        moved = previous["commentary_parts"].pop()
        if aggressive and (split := split_trailing_commentary_fragment(previous_tail)):
            head, tail = split
            moved = tail
            if head:
                previous["commentary_parts"].append(head)
        join_mode = obvious_fragment_continuation(moved, current["commentary_parts"][0]) or "space"
        current["commentary_parts"][0] = join_continued_rag_text(
            moved,
            current["commentary_parts"][0],
            join_mode,
        )
        for page_label in previous.get("page_labels", []):
            if page_label in current["page_labels"]:
                continue
            current["page_labels"].insert(0, page_label)
        for pdf_page in previous.get("pdf_pages", []):
            if pdf_page in current["pdf_pages"]:
                continue
            current["pdf_pages"].insert(0, pdf_page)
    move_trailing_bibliography_to_reference(passages)
    return passages


def flatten_rag_regions(spatial_pages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    flattened: list[dict[str, Any]] = []
    for page in spatial_pages:
        normalized_regions: list[dict[str, Any]] = []
        for region in page.get("regions", []):
            rag_text = normalize_rag_region_text(region)
            if not rag_text:
                continue
            anchor = parse_passage_anchor(rag_text)
            region["rag_text"] = rag_text
            region["anchor_label"] = anchor[0] if anchor else None
            region["content_mode"] = page.get("content_mode", "prose")
            fragment_refs = split_rag_region_fragments(region, rag_text)
            region["rag_fragments"] = fragment_refs
            for fragment_ref in fragment_refs:
                normalized_regions.append(
                    {
                        "page_label": page.get("page_label"),
                        "pdf_page": page.get("pdf_page"),
                        "layout_kind": page.get("layout_kind"),
                        "content_mode": page.get("content_mode", "prose"),
                        "region_id": fragment_ref["fragment_id"],
                        "source_region_id": region.get("region_id"),
                        "role": region.get("role"),
                        "zone": region.get("zone"),
                        "x0": float(region.get("bbox", {}).get("x0", 0.0)),
                        "y0": float(region.get("bbox", {}).get("y0", 0.0)),
                        "x1": float(region.get("bbox", {}).get("x1", 0.0)),
                        "y1": float(region.get("bbox", {}).get("y1", 0.0)),
                        "rag_text": fragment_ref["rag_text"],
                        "anchor_label": fragment_ref["anchor_label"],
                        "region_ref": region,
                        "fragment_ref": fragment_ref,
                        "forced_rag_bucket": fragment_ref.get("forced_rag_bucket")
                        or region.get("forced_rag_bucket"),
                    }
                )
        first_anchor_label = next(
            (region["anchor_label"] for region in normalized_regions if region.get("anchor_label")),
            None,
        )
        first_anchor_region = next(
            (region for region in normalized_regions if region.get("anchor_label") == first_anchor_label),
            None,
        )
        first_anchor_zone = first_anchor_region["zone"] if first_anchor_region else None
        first_anchor_y0 = first_anchor_region["y0"] if first_anchor_region else None
        anchor_regions = [
            (index, region)
            for index, region in enumerate(normalized_regions)
            if region.get("anchor_label")
        ]
        first_anchor_seen = False
        next_anchor_pointer = 0
        for index, region in enumerate(normalized_regions):
            before_page_anchor = first_anchor_label is not None and not first_anchor_seen
            if region.get("anchor_label") == first_anchor_label and first_anchor_label is not None:
                first_anchor_seen = True
            distance_to_first_anchor = (
                first_anchor_y0 - region["y0"]
                if first_anchor_y0 is not None and before_page_anchor
                else None
            )
            while (
                next_anchor_pointer < len(anchor_regions)
                and anchor_regions[next_anchor_pointer][0] <= index
            ):
                next_anchor_pointer += 1
            next_anchor = (
                anchor_regions[next_anchor_pointer]
                if next_anchor_pointer < len(anchor_regions)
                else None
            )
            next_anchor_label = next_anchor[1]["anchor_label"] if next_anchor else None
            next_anchor_zone = next_anchor[1]["zone"] if next_anchor else None
            distance_to_next_anchor = (
                next_anchor[1]["y0"] - region["y0"]
                if next_anchor is not None
                else None
            )
            attach_to_next_anchor, attach_reason = should_attach_fragment_to_next_anchor(
                region,
                next_anchor[1] if next_anchor else None,
                distance_to_next_anchor=distance_to_next_anchor,
            )
            flattened.append(
                {
                    **region,
                    "page_first_anchor_label": first_anchor_label,
                    "page_first_anchor_zone": first_anchor_zone,
                    "before_page_anchor": before_page_anchor,
                    "distance_to_first_anchor": distance_to_first_anchor,
                    "next_anchor_label": next_anchor_label,
                    "next_anchor_zone": next_anchor_zone,
                    "distance_to_next_anchor": distance_to_next_anchor,
                    "attach_to_next_anchor": attach_to_next_anchor,
                    "attach_to_next_anchor_reason": attach_reason,
                    "forced_rag_bucket": "commentary" if attach_to_next_anchor else None,
                }
            )
    flattened = annotate_rag_continuations(flattened)
    return annotate_reference_note_continuations(flattened)


def rag_token_count(text: str) -> int:
    return len(re.findall(r"[A-Za-z0-9]+", text))


def rag_paragraphs_from_parts(parts: list[str]) -> list[str]:
    paragraphs: list[str] = []
    for part in parts:
        for chunk in [segment.strip() for segment in part.split("\n\n") if segment.strip()]:
            if not paragraphs:
                paragraphs.append(chunk)
                continue
            join_mode = obvious_fragment_continuation(paragraphs[-1], chunk)
            if join_mode:
                paragraphs[-1] = join_continued_rag_text(paragraphs[-1], chunk, join_mode)
                continue
            paragraphs.append(chunk)
    return paragraphs


def split_oversized_rag_paragraph(paragraph: str) -> list[str]:
    sentences = [segment.strip() for segment in SENTENCE_SPLIT_RE.split(paragraph) if segment.strip()]
    if len(sentences) <= 1:
        words = paragraph.split()
        chunks: list[str] = []
        for start in range(0, len(words), MAX_UNANCHORED_PASSAGE_TOKENS):
            chunks.append(" ".join(words[start : start + MAX_UNANCHORED_PASSAGE_TOKENS]).strip())
        return [chunk for chunk in chunks if chunk]

    chunks: list[str] = []
    current: list[str] = []
    current_tokens = 0
    for sentence in sentences:
        sentence_tokens = rag_token_count(sentence)
        if current and current_tokens + sentence_tokens > MAX_UNANCHORED_PASSAGE_TOKENS:
            chunks.append(" ".join(current).strip())
            current = []
            current_tokens = 0
        if sentence_tokens > MAX_UNANCHORED_PASSAGE_TOKENS:
            chunks.extend(split_oversized_rag_paragraph(sentence))
            continue
        current.append(sentence)
        current_tokens += sentence_tokens
    if current:
        chunks.append(" ".join(current).strip())
    return [chunk for chunk in chunks if chunk]


def pack_rag_paragraphs(paragraphs: list[str]) -> list[str]:
    prepared: list[str] = []
    for paragraph in paragraphs:
        if rag_token_count(paragraph) > MAX_UNANCHORED_PASSAGE_TOKENS:
            prepared.extend(split_oversized_rag_paragraph(paragraph))
        else:
            prepared.append(paragraph)

    segments: list[str] = []
    current: list[str] = []
    current_tokens = 0
    for paragraph in prepared:
        paragraph_tokens = rag_token_count(paragraph)
        projected_tokens = current_tokens + paragraph_tokens
        if current and projected_tokens > MAX_UNANCHORED_PASSAGE_TOKENS:
            segments.append("\n\n".join(current).strip())
            current = []
            current_tokens = 0
        current.append(paragraph)
        current_tokens += paragraph_tokens
        if current_tokens >= TARGET_UNANCHORED_PASSAGE_TOKENS:
            segments.append("\n\n".join(current).strip())
            current = []
            current_tokens = 0
    if current:
        segments.append("\n\n".join(current).strip())
    return [segment for segment in segments if segment]


def segment_unanchored_rag_passages(passages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    segmented: list[dict[str, Any]] = []
    for passage in passages:
        bucket_order = [
            ("citation_parts", "citation"),
            ("commentary_parts", "commentary"),
            ("reference_parts", "reference"),
        ]
        bucket_segments: list[dict[str, Any]] = []
        overflow_detected = False
        for parts_key, reason_bucket in bucket_order:
            parts = passage.get(parts_key) or []
            if not parts:
                continue
            merged = merge_rag_fragments(parts)
            limit = MAX_UNANCHORED_PASSAGE_TOKENS if passage.get("label") else TARGET_UNANCHORED_PASSAGE_TOKENS
            if rag_token_count(merged) <= limit:
                bucket_segments.append(
                    {
                        "bucket": parts_key,
                        "segments": [merged],
                    }
                )
                continue
            overflow_detected = True
            paragraphs = rag_paragraphs_from_parts(parts)
            bucket_segments.append(
                {
                    "bucket": parts_key,
                    "segments": pack_rag_paragraphs(paragraphs),
                    "reason": (
                        f"anchored-{reason_bucket}-overflow"
                        if passage.get("label")
                        else f"unanchored-{reason_bucket}-overflow"
                    ),
                }
            )

        total_segment_count = sum(len(item["segments"]) for item in bucket_segments)
        bucket_split_detected = any(len(item["segments"]) > 1 for item in bucket_segments)
        if not bucket_split_detected and not overflow_detected:
            segmented.append({**passage, "segmentation_mode": None, "segmentation_reason": None})
            continue
        if not bucket_split_detected:
            segmented.append({**passage, "segmentation_mode": None, "segmentation_reason": None})
            continue
        if total_segment_count <= 1:
            segmented.append({**passage, "segmentation_mode": None, "segmentation_reason": None})
            continue

        segment_index = 0
        for bucket_segment in bucket_segments:
            for chunk in bucket_segment["segments"]:
                segment_index += 1
                segmented.append(
                    {
                        "passage_id": f"{passage['passage_id']}-seg-{segment_index:02d}",
                        "label": passage.get("label"),
                        "source_ref": passage.get("source_ref", ""),
                        "citation_parts": [chunk] if bucket_segment["bucket"] == "citation_parts" else [],
                        "commentary_parts": [chunk] if bucket_segment["bucket"] == "commentary_parts" else [],
                        "reference_parts": [chunk] if bucket_segment["bucket"] == "reference_parts" else [],
                        "page_labels": list(passage.get("page_labels") or []),
                        "pdf_pages": list(passage.get("pdf_pages") or []),
                        "segmentation_mode": "pseudo-passage",
                        "segmentation_reason": bucket_segment.get("reason", "unanchored-prose"),
                    }
                )
    return segmented


def build_rag_passages(spatial_pages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    flattened = flatten_rag_regions(spatial_pages)
    if not flattened:
        return []

    passages: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    preamble_counter = 0
    pending_for_next_anchor: list[dict[str, Any]] = []

    def start_preamble() -> dict[str, Any]:
        nonlocal preamble_counter
        preamble_counter += 1
        return {
            "passage_id": f"preamble-{preamble_counter:02d}",
            "label": None,
            "source_ref": "",
            "citation_parts": [],
            "commentary_parts": [],
            "reference_parts": [],
            "page_labels": [],
            "pdf_pages": [],
            "_last_bucket": None,
        }

    def flush_current() -> None:
        nonlocal current
        if not current:
            return
        if current["citation_parts"] or current["commentary_parts"] or current["reference_parts"]:
            current.pop("_last_bucket", None)
            passages.append(current)
        current = None

    def append_region_to_current(region: dict[str, Any]) -> None:
        nonlocal current
        if current is None:
            current = start_preamble()
        inherited_bucket = current.get("_last_bucket") if region.get("inherits_bucket_from_previous") else None
        bucket = (
            region.get("forced_rag_bucket")
            or (region.get("fragment_ref") or {}).get("forced_rag_bucket")
            or (region.get("region_ref") or {}).get("forced_rag_bucket")
            or inherited_bucket
        )
        if (
            bucket is None
            and current.get("label")
            and not current["citation_parts"]
            and not current["reference_parts"]
            and region["zone"] == "center"
            and len(clean_text_line(region["rag_text"]).split()) <= 4
            and not is_reference_note_text(region["rag_text"])
        ):
            bucket = "citation"
        if bucket is None:
            bucket = classify_rag_region(region, current.get("citation_zone"), current.get("label"))
        target_parts: list[str]
        if bucket == "citation":
            target_parts = current["citation_parts"]
        elif bucket == "reference":
            target_parts = current["reference_parts"]
        else:
            target_parts = current["commentary_parts"]
        if inherited_bucket and target_parts:
            target_parts[-1] = join_continued_rag_text(
                target_parts[-1],
                region["rag_text"],
                region.get("continuation_join_mode", "space"),
            )
        else:
            target_parts.append(region["rag_text"])
        if region.get("page_label") and region["page_label"] not in current["page_labels"]:
            current["page_labels"].append(region["page_label"])
        if region.get("pdf_page") and region["pdf_page"] not in current["pdf_pages"]:
            current["pdf_pages"].append(region["pdf_page"])
        current["_last_bucket"] = bucket
        diagnostic_ref = region.get("fragment_ref") or region.get("region_ref")
        if diagnostic_ref is not None:
            diagnostic_ref["rag_bucket"] = bucket
            diagnostic_ref["rag_bucket_inherited"] = bool(inherited_bucket)
            diagnostic_ref["rag_passage_label"] = current.get("label")
            if region.get("attach_to_next_anchor_reason"):
                diagnostic_ref["attach_to_next_anchor_reason"] = region["attach_to_next_anchor_reason"]

    for region_index, region in enumerate(flattened):
        anchor = parse_passage_anchor(region["rag_text"])
        if anchor:
            flush_current()
            label, source_ref, citation_seed = anchor
            citation_zone = infer_passage_citation_zone(flattened, region_index, region)
            current = {
                "passage_id": label,
                "label": label,
                "source_ref": source_ref,
                "citation_parts": [citation_seed] if citation_seed else [],
                "commentary_parts": [],
                "reference_parts": [],
                "page_labels": [region["page_label"]] if region.get("page_label") else [],
                "pdf_pages": [region["pdf_page"]] if region.get("pdf_page") else [],
                "anchor_zone": region["zone"],
                "citation_zone": citation_zone,
                "_last_bucket": "citation" if citation_seed else None,
            }
            diagnostic_ref = region.get("fragment_ref") or region.get("region_ref")
            if diagnostic_ref is not None:
                diagnostic_ref["rag_bucket"] = "citation" if citation_seed else None
                diagnostic_ref["rag_bucket_inherited"] = False
                diagnostic_ref["rag_passage_label"] = label
            for pending_region in pending_for_next_anchor:
                append_region_to_current(pending_region)
            pending_for_next_anchor.clear()
            continue

        if region.get("attach_to_next_anchor"):
            pending_for_next_anchor.append(region)
            continue

        append_region_to_current(region)

    flush_current()
    return segment_unanchored_rag_passages(repair_passage_commentary_boundaries(passages))


def merge_rag_fragments(parts: list[str]) -> str:
    paragraphs: list[str] = []
    for part in parts:
        for chunk in [segment.strip() for segment in part.split("\n\n") if segment.strip()]:
            if not paragraphs:
                paragraphs.append(chunk)
                continue
            join_mode = obvious_fragment_continuation(paragraphs[-1], chunk)
            if join_mode:
                paragraphs[-1] = join_continued_rag_text(paragraphs[-1], chunk, join_mode)
                continue
            paragraphs.append(chunk)
    return "\n\n".join(paragraphs).strip()


def render_rag_linearized_markdown(
    entry: TocEntry,
    context_label: str | None,
    start_label: str | None,
    end_label: str | None,
    content_start: int | None,
    content_end: int | None,
    rag_output_path: str | None,
    spatial_output_path: str | None,
    spatial_pages: list[dict[str, Any]],
) -> str | None:
    if not rag_output_path or not spatial_pages:
        return None

    spatial_pages = repair_why_comment_inset_quote_spatial_pages(entry, spatial_pages)
    passages = build_rag_passages(spatial_pages)
    frontmatter = yaml_frontmatter(
        {
            "title": entry.title,
            "display_title": entry.display_title,
            "kind": entry.kind,
            "book_page_start": start_label,
            "book_page_end": end_label,
            "pdf_page_start": content_start,
            "pdf_page_end": content_end,
            "context_path": context_label,
            "source_markdown": entry.output_path,
            "spatial_sidecar": spatial_output_path,
            "linearization": "citation-first-commentary",
            "passage_count": len(passages),
        }
    )

    sections: list[str] = [frontmatter, "", f"# {entry.title}", ""]
    sections.append("Representation: citation-first linearization for RAG.")
    if context_label:
        sections.extend(["", f"Context: {context_label}"])
    if content_start and content_end and content_end >= content_start:
        sections.extend(
            [
                "",
                f"Source pages: {format_page_range(start_label, end_label)} "
                f"(PDF {content_start}-{content_end}).",
            ]
        )

    for index, passage in enumerate(passages, start=1):
        ordinal = f"{index:03d}"
        heading = f"## Passage {index:03d}"
        if passage.get("label"):
            heading = f"## Passage {index:03d} ({passage['label']})"
        sections.extend(["", heading])
        if passage.get("label"):
            sections.append(f"Label: {passage['label']}")
        if passage.get("source_ref"):
            sections.append(f"Source reference: {passage['source_ref']}")
        if passage.get("page_labels"):
            sections.append(f"Source page labels: {', '.join(passage['page_labels'])}")
        if passage.get("citation_parts"):
            sections.extend(
                [
                    "",
                    "### Citation",
                    "",
                    merge_rag_fragments(passage["citation_parts"]),
                ]
            )
        if passage.get("commentary_parts"):
            sections.extend(
                [
                    "",
                    "### Commentary",
                    "",
                    merge_rag_fragments(passage["commentary_parts"]),
                ]
            )
        if passage.get("reference_parts"):
            sections.extend(
                [
                    "",
                    "### Reference Notes",
                    "",
                ]
            )
            for note in passage["reference_parts"]:
                sections.append(f"- {note}")

    return "\n".join(part for part in sections if part is not None).rstrip() + "\n"


def render_children_list(entry: TocEntry, by_id: dict[str, TocEntry]) -> str:
    if not entry.children:
        return ""
    lines = ["## Contents", ""]
    for child_id in entry.children:
        child = by_id[child_id]
        lines.append(f"- [{child.display_title}]({relative_link(entry.output_path, child.output_path)})")
    return "\n".join(lines)


def relative_link(from_path: str | None, to_path: str | None) -> str:
    if not from_path or not to_path:
        return ""
    return os.path.relpath(to_path, start=str(Path(from_path).parent))


def classify_region_zone(x0: float, x1: float, page_width: float) -> str:
    center = (x0 + x1) / 2
    if center <= page_width * 0.33:
        return "left"
    if center >= page_width * 0.67:
        return "right"
    return "center"


def semanticize_region_text(text: str, role: str) -> str:
    cleaned_lines = [clean_text_line(line) for line in normalize_unicode(text).splitlines() if clean_text_line(line)]
    if not cleaned_lines:
        return ""
    if role == "table":
        return "\n".join(f"- {line}" for line in cleaned_lines)
    return reflow_block_text("\n".join(cleaned_lines))


def extend_heading_candidates(line_items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    sorted_items = sorted(line_items, key=lambda item: (item["y0"], item["x0"]))
    candidates = collapse_inline_fragments(sorted_items, allow_title_case=True)
    seen: set[tuple[int, int, str]] = {
        (
            int(round(float(candidate["y0"]) * 10)),
            int(round(float(candidate["y1"]) * 10)),
            clean_text_line(candidate["text"]),
        )
        for candidate in candidates
    }

    for index, item in enumerate(sorted_items):
        first_text = clean_text_line(item["text"])
        if not first_text or len(first_text.split()) > 5 or not is_title_style_heading(first_text):
            continue
        combined_lines = [item]
        for follower in sorted_items[index + 1 : index + 3]:
            gap = float(follower["y0"]) - float(combined_lines[-1]["y1"])
            if gap < -2.0 or gap > 18.0:
                break
            if abs(float(follower["x0"]) - float(combined_lines[0]["x0"])) > 52.0:
                break
            follower_text = clean_text_line(follower["text"])
            if not follower_text or len(follower_text.split()) > 6:
                break
            combined_lines.append(follower)
            combined_text = " ".join(clean_text_line(line["text"]) for line in combined_lines)
            if not is_title_style_heading(combined_text):
                continue
            key = (
                int(round(float(combined_lines[0]["y0"]) * 10)),
                int(round(float(combined_lines[-1]["y1"]) * 10)),
                combined_text,
            )
            if key in seen:
                continue
            seen.add(key)
            candidates.append(
                {
                    "text": combined_text,
                    "x0": min(float(line["x0"]) for line in combined_lines),
                    "y0": float(combined_lines[0]["y0"]),
                    "x1": max(float(line["x1"]) for line in combined_lines),
                    "y1": float(combined_lines[-1]["y1"]),
                }
            )
    return candidates


def detect_heading_band_from_lines(
    line_items: list[dict[str, Any]],
    skip_keys: set[str],
    *,
    prefer: str = "first",
    prefix_variants: list[str] | None = None,
    mode: str | None = None,
) -> tuple[float, float] | None:
    merged = extend_heading_candidates(line_items)
    matches: list[tuple[float, float]] = []
    for item in merged:
        cleaned = clean_text_line(item["text"])
        if classify_heading_line(
            cleaned,
            skip_keys,
            prefix_variants=prefix_variants,
            mode=mode,
        ):
            matches.append((float(item["y0"]) - 2.0, float(item["y1"]) + 2.0))
    if not matches:
        return None
    if prefer == "last":
        return max(matches, key=lambda item: item[0])
    return min(matches, key=lambda item: item[0])


def detect_heading_band(
    page: fitz.Page,
    skip_keys: set[str],
    *,
    prefer: str = "first",
    prefix_variants: list[str] | None = None,
    mode: str | None = None,
) -> tuple[float, float] | None:
    raw = page.get_text("dict")
    line_items: list[dict[str, Any]] = []
    for block in raw.get("blocks", []):
        if block.get("type") != 0:
            continue
        for line in block.get("lines", []):
            spans = line.get("spans", [])
            text = normalize_unicode("".join(span.get("text", "") for span in spans)).strip()
            cleaned = clean_text_line(text)
            if not cleaned:
                continue
            bbox = line.get("bbox", [0.0, 0.0, 0.0, 0.0])
            line_items.append(
                {
                    "text": text,
                    "x0": float(bbox[0]),
                    "y0": float(bbox[1]),
                    "x1": float(bbox[2]),
                    "y1": float(bbox[3]),
                }
            )
    return detect_heading_band_from_lines(
        line_items,
        skip_keys,
        prefer=prefer,
        prefix_variants=prefix_variants,
        mode=mode,
    )


def detect_heading_cutoff(page: fitz.Page, skip_keys: set[str]) -> float | None:
    band = detect_heading_band(page, skip_keys)
    return band[1] if band else None


def merge_region_payload(
    previous: dict[str, Any],
    current: dict[str, Any],
    decision: dict[str, Any],
) -> dict[str, Any]:
    merged = previous.copy()
    merged["raw_text"] = join_continued_rag_text(previous["raw_text"], current["raw_text"], decision["join_mode"])
    merged["semantic_text"] = join_continued_rag_text(
        previous["semantic_text"],
        current["semantic_text"],
        decision["join_mode"],
    )
    merged["bbox"] = {
        "x0": round(min(previous["bbox"]["x0"], current["bbox"]["x0"]), 2),
        "y0": round(min(previous["bbox"]["y0"], current["bbox"]["y0"]), 2),
        "x1": round(max(previous["bbox"]["x1"], current["bbox"]["x1"]), 2),
        "y1": round(max(previous["bbox"]["y1"], current["bbox"]["y1"]), 2),
    }
    merged["joined_from_region_ids"] = [
        *previous.get("joined_from_region_ids", [previous["region_id"]]),
        *current.get("joined_from_region_ids", [current["region_id"]]),
    ]
    merged["join_reason"] = decision["reasons"]
    merged["ownership_inherited_from"] = previous.get("ownership_inherited_from") or previous["region_id"]
    return merged


def trim_leading_prelude_regions(regions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if boundary_overlap_mode() not in {"aggressive", "hybrid"} or len(regions) < 2:
        return regions
    drop_count = 0
    for region in regions:
        raw_text = clean_text_line(region.get("raw_text", ""))
        if len(raw_text.split()) > 7 or len(raw_text) > 56:
            break
        if float(region.get("bbox", {}).get("y1", 0.0)) > 120.0:
            break
        drop_count += 1
        if drop_count >= 3:
            break
    if not drop_count or drop_count >= len(regions):
        return regions
    next_text = clean_text_line(regions[drop_count].get("semantic_text", ""))
    if not next_text[:1].isupper():
        return regions
    return regions[drop_count:]


def repair_page_regions(
    regions: list[dict[str, Any]],
    *,
    content_mode: str,
) -> list[dict[str, Any]]:
    if content_mode != "prose" or len(regions) < 2:
        return regions
    repaired: list[dict[str, Any]] = [regions[0].copy()]
    for region in regions[1:]:
        current = region.copy()
        previous = repaired[-1]
        previous_probe = {
            "region_id": previous["region_id"],
            "role": previous["role"],
            "zone": previous["zone"],
            "x0": previous["bbox"]["x0"],
            "y0": previous["bbox"]["y0"],
            "x1": previous["bbox"]["x1"],
            "y1": previous["bbox"]["y1"],
            "pdf_page": previous.get("pdf_page"),
            "raw_text": previous["raw_text"],
            "semantic_text": previous["semantic_text"],
        }
        current_probe = {
            "region_id": current["region_id"],
            "role": current["role"],
            "zone": current["zone"],
            "x0": current["bbox"]["x0"],
            "y0": current["bbox"]["y0"],
            "x1": current["bbox"]["x1"],
            "y1": current["bbox"]["y1"],
            "pdf_page": current.get("pdf_page"),
            "raw_text": current["raw_text"],
            "semantic_text": current["semantic_text"],
        }
        decision = evaluate_prose_region_join(previous_probe, current_probe, content_mode=content_mode)
        if decision.get("join"):
            repaired[-1] = merge_region_payload(previous, current, decision)
            continue
        if decision.get("considered"):
            previous["join_rejected_reason"] = decision.get("rejection_reason")
        repaired.append(current)
    return repaired


def extract_page_regions(
    page: fitz.Page,
    profile: dict[str, Any],
    skip_keys: set[str],
    min_y: float | None = None,
    max_y: float | None = None,
    *,
    self_heading_keys: set[str] | None = None,
    self_heading_variants: list[str] | None = None,
    drop_leading_prelude: bool = False,
) -> list[dict[str, Any]]:
    page_width = page.rect.width
    raw_items: list[dict[str, Any]] = []
    raw = page.get_text("dict")
    line_index = 0
    for block in raw.get("blocks", []):
        if block.get("type") != 0:
            continue
        for line in block.get("lines", []):
            spans = line.get("spans", [])
            text = normalize_unicode("".join(span.get("text", "") for span in spans)).strip()
            cleaned = clean_text_line(text)
            if not cleaned:
                continue
            bbox = line.get("bbox", [0.0, 0.0, 0.0, 0.0])
            x0, y0, x1, y1 = bbox
            if should_skip_top_margin_line(cleaned, y0):
                continue
            if min_y is not None and y0 < min_y:
                continue
            if max_y is not None and y0 >= max_y:
                continue
            heading_match = classify_heading_line(
                cleaned,
                self_heading_keys or set(),
                prefix_variants=self_heading_variants,
            )
            if heading_match:
                remainder = clean_text_line(heading_match.get("remainder", ""))
                if not remainder:
                    continue
                text = remainder
                cleaned = remainder
            if keyify(cleaned) in skip_keys or cleaned.isdigit():
                continue
            line_index += 1
            raw_items.append(
                {
                    "line_id": f"l{line_index:03d}",
                    "x0": x0,
                    "y0": y0,
                    "x1": x1,
                    "y1": y1,
                    "text": text,
                }
            )

    raw_items.sort(key=lambda item: (item["y0"], item["x0"]))
    line_items: list[dict[str, Any]] = []
    for line_item in collapse_inline_fragments(raw_items, allow_title_case=True):
        width = line_item["x1"] - line_item["x0"]
        zone = classify_region_zone(line_item["x0"], line_item["x1"], page_width)
        role = "main"
        if profile["kind"] == "table":
            role = "table"
        elif profile["kind"] in {"aside", "multi-column"}:
            if zone == "right" and line_item["x0"] >= page_width * 0.45:
                role = "aside"
            elif line_item["x0"] >= page_width * 0.50 or (width <= page_width * 0.42 and zone != "left"):
                role = "aside"
        line_items.append({**line_item, "role": role, "zone": zone})

    if not line_items:
        return []

    regions: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    region_counter = 0

    def flush_current() -> None:
        nonlocal current, region_counter
        if not current:
            return
        region_counter += 1
        raw_text = "\n".join(current["lines"])
        role = current["role"]
        regions.append(
            {
                "region_id": f"r{region_counter:02d}",
                "role": role,
                "zone": current["zone"],
                "bbox": {
                    "x0": round(current["x0"], 2),
                    "y0": round(current["y0"], 2),
                    "x1": round(current["x1"], 2),
                    "y1": round(current["y1"], 2),
                },
                "raw_text": raw_text,
                "semantic_text": semanticize_region_text(raw_text, role),
            }
        )
        current = None

    for item in line_items:
        if current is None:
            current = {
                "role": item["role"],
                "zone": item["zone"],
                "x0": item["x0"],
                "y0": item["y0"],
                "x1": item["x1"],
                "y1": item["y1"],
                "last_y1": item["y1"],
                "last_x0": item["x0"],
                "lines": [item["text"]],
            }
            continue

        same_role = item["role"] == current["role"]
        same_zone = item["zone"] == current["zone"]
        y_gap = item["y0"] - current["last_y1"]
        x_shift = abs(item["x0"] - current["last_x0"])
        if same_role and same_zone and y_gap <= 18 and x_shift <= 36:
            current["lines"].append(item["text"])
            current["x0"] = min(current["x0"], item["x0"])
            current["x1"] = max(current["x1"], item["x1"])
            current["y1"] = max(current["y1"], item["y1"])
            current["last_y1"] = item["y1"]
            current["last_x0"] = item["x0"]
            continue

        flush_current()
        current = {
            "role": item["role"],
            "zone": item["zone"],
            "x0": item["x0"],
            "y0": item["y0"],
            "x1": item["x1"],
            "y1": item["y1"],
            "last_y1": item["y1"],
            "last_x0": item["x0"],
            "lines": [item["text"]],
        }

    flush_current()
    if drop_leading_prelude:
        regions = trim_leading_prelude_regions(regions)
    return regions


def render_semantic_page(
    page_label: str | None,
    pdf_page: int,
    profile: dict[str, Any],
    regions: list[dict[str, Any]],
    *,
    content_mode: str,
) -> str:
    lines = [
        f"<!-- source-page-label: {page_label}; pdf-page: {pdf_page}; layout: {profile['kind']} -->",
        render_anchor_comment(
            "semantic-page",
            page_label=page_label,
            pdf_page=pdf_page,
            layout=profile["kind"],
        ),
    ]
    if profile["complex"]:
        lines.append(
            f"_Source page {page_label} contains {len(regions)} layout regions; exact coordinates are in the spatial sidecar._"
        )
        lines.append("")

    if profile["kind"] == "table":
        table_text = "\n".join(region["semantic_text"] for region in regions if region["semantic_text"].strip())
        if table_text:
            lines.append(f"Table-like content from source page {page_label}:")
            lines.append(table_text)
        return "\n".join(lines).strip()

    if content_mode == "index":
        lines.append("\n".join(region["semantic_text"] for region in regions if region["semantic_text"].strip()))
        return "\n".join(lines).strip()

    main_regions: list[str] = []
    aside_regions: list[str] = []
    for region in regions:
        semantic_text = region["semantic_text"].strip()
        if not semantic_text:
            continue
        if region["role"] == "main":
            if main_regions:
                semantic_text = suppress_duplicate_boundary_lead(main_regions[-1], semantic_text)
            if semantic_text:
                main_regions.append(semantic_text)
            continue
        if region["role"] == "aside":
            if aside_regions:
                semantic_text = suppress_duplicate_boundary_lead(aside_regions[-1], semantic_text)
            if semantic_text:
                aside_regions.append(semantic_text)

    if main_regions:
        lines.append("\n\n".join(main_regions))
        lines.append("")
    if aside_regions:
        lines.append(f"Supplementary side material from source page {page_label}:")
        for aside_text in aside_regions:
            lines.append(f"- {aside_text}")
        lines.append("")

    return "\n".join(lines).strip()


def render_anchor_comment(kind: str, **fields: Any) -> str:
    rendered_fields = [f"{name}={value}" for name, value in fields.items() if value not in {None, ""}]
    return f"<!-- {kind}: {'; '.join(rendered_fields)} -->"


def render_entry_markdown(
    entry: TocEntry,
    entries: list[TocEntry],
    doc: fitz.Document,
    layout_pages: list[str],
    page_profiles: dict[int, dict[str, Any]],
    book_id: str,
) -> tuple[str, str | None, dict[str, Any], dict[str, Any] | None]:
    by_id = get_entry_by_id(entries)
    content_start = entry.pdf_page
    content_end = entry.end_pdf_page
    next_entry: TocEntry | None = None
    previous_entry: TocEntry | None = None
    for index, candidate in enumerate(entries):
        if candidate.id != entry.id:
            continue
        previous_entry = entries[index - 1] if index > 0 else None
        next_entry = entries[index + 1] if index + 1 < len(entries) else None
        break
    if entry.children:
        first_child = by_id[entry.children[0]]
        if first_child.pdf_page is not None:
            content_end = first_child.pdf_page - 1
    if content_start is not None and content_end is not None and content_end < content_start:
        content_start = None
        content_end = None

    skip_keys = heading_skip_keys(entry, by_id)
    page_slices: list[dict[str, Any]] = []
    if content_start and content_end and content_end >= content_start:
        for pdf_page in range(content_start, content_end + 1):
            page_slices.append(
                {
                    "pdf_page": pdf_page,
                    "page_label": increment_page_label(entry.page_label, entry.numbering, pdf_page - content_start),
                    "min_y": (
                        detect_entry_start_cutoff(entry, previous_entry, doc[pdf_page - 1], by_id)
                        if pdf_page == content_start
                        else None
                    ),
                    "max_y": None,
                }
            )

        boundary_entry = by_id[entry.children[0]] if entry.children else next_entry
        if boundary_entry and boundary_entry.pdf_page and content_end is not None:
            boundary_skip_keys = heading_skip_keys(boundary_entry, by_id)
            boundary_heading_keys = entry_heading_keys(boundary_entry)
            boundary_heading_variants = entry_heading_variants(boundary_entry)
            boundary_page = doc[boundary_entry.pdf_page - 1]
            boundary_profile = page_profiles[boundary_entry.pdf_page]
            boundary_self_band = detect_entry_self_heading_band(boundary_entry, boundary_page)
            heading_band = detect_entry_heading_band(boundary_entry, entry, boundary_page, by_id)
            shared_same_page = boundary_entry.pdf_page == content_end
            shared_next_page = boundary_entry.pdf_page == content_end + 1
            if heading_band is not None and (shared_same_page or shared_next_page):
                pre_heading_regions = extract_page_regions(
                    boundary_page,
                    boundary_profile,
                    skip_keys | boundary_skip_keys,
                    max_y=heading_band[0],
                )
                if pre_heading_regions:
                    shared_pdf_page = boundary_entry.pdf_page
                    if shared_same_page:
                        update_page_slice_bounds(page_slices, shared_pdf_page, max_y=heading_band[0])
                    else:
                        page_slices.append(
                            {
                                "pdf_page": shared_pdf_page,
                                "page_label": increment_page_label(
                                    entry.page_label,
                                    entry.numbering,
                                    shared_pdf_page - content_start,
                                ),
                                "min_y": None,
                                "max_y": heading_band[0],
                            }
                        )
                elif shared_same_page:
                    update_page_slice_bounds(page_slices, boundary_entry.pdf_page, drop=True)
                elif shared_next_page:
                    post_heading_regions = extract_page_regions(
                        boundary_page,
                        boundary_profile,
                        skip_keys | boundary_skip_keys,
                        min_y=heading_band[1]
                        if boundary_overlap_mode() in {"conservative", "hybrid"}
                        else heading_band[0],
                        self_heading_keys=boundary_heading_keys,
                        self_heading_variants=boundary_heading_variants,
                    )
                    if post_heading_regions:
                        next_content_mode = infer_page_content_mode(
                            boundary_entry.kind,
                            boundary_entry.title,
                            boundary_profile["kind"],
                            post_heading_regions,
                        )
                        first_post = clean_text_line(
                            post_heading_regions[0].get("semantic_text") or post_heading_regions[0].get("raw_text") or ""
                        )
                        if (
                            boundary_self_band is None
                            and
                            next_content_mode == "prose"
                            and first_post
                            and (first_post[0].islower() or first_post[0] in ',;:)]}’"\'-')
                        ):
                            shared_pdf_page = boundary_entry.pdf_page
                            page_slices.append(
                                {
                                    "pdf_page": shared_pdf_page,
                                    "page_label": increment_page_label(
                                        entry.page_label,
                                        entry.numbering,
                                        shared_pdf_page - content_start,
                                    ),
                                    "min_y": heading_band[1]
                                    if boundary_overlap_mode() in {"conservative", "hybrid"}
                                    else heading_band[0],
                                    "max_y": None,
                                }
                            )

    body_parts: list[str] = []
    complex_pages: list[int] = []
    spatial_pages: list[dict[str, Any]] = []
    if page_slices:
        for page_slice in page_slices:
            pdf_page = page_slice["pdf_page"]
            profile = page_profiles[pdf_page]
            page_label = page_slice["page_label"]
            regions = extract_page_regions(
                doc[pdf_page - 1],
                profile,
                skip_keys,
                min_y=page_slice["min_y"],
                max_y=page_slice["max_y"],
                self_heading_keys=entry_heading_keys(entry) if pdf_page == content_start else None,
                self_heading_variants=entry_heading_variants(entry) if pdf_page == content_start else None,
                drop_leading_prelude=pdf_page == content_start,
            )
            if not regions:
                continue
            for region in regions:
                region["pdf_page"] = pdf_page
                region["page_label"] = page_label
            content_mode = infer_page_content_mode(entry.kind, entry.title, profile["kind"], regions)
            regions = repair_page_regions(regions, content_mode=content_mode)
            if profile["complex"]:
                complex_pages.append(pdf_page)
            spatial_pages.append(
                {
                    "page_label": page_label,
                    "pdf_page": pdf_page,
                    "slice_min_y": page_slice["min_y"],
                    "slice_max_y": page_slice["max_y"],
                    "layout_kind": profile["kind"],
                    "content_mode": content_mode,
                    "complex": profile["complex"],
                    "reasons": profile["reasons"],
                    "regions": regions,
                    "layout_text": strip_layout_header(layout_pages[pdf_page - 1]),
                }
            )
            rendered = render_semantic_page(
                page_label,
                pdf_page,
                profile,
                regions,
                content_mode=content_mode,
            )
            if rendered:
                body_parts.append(rendered)

    actual_start_pdf_page = spatial_pages[0]["pdf_page"] if spatial_pages else None
    actual_end_pdf_page = spatial_pages[-1]["pdf_page"] if spatial_pages else None
    start_label = spatial_pages[0]["page_label"] if spatial_pages else None
    end_label = spatial_pages[-1]["page_label"] if spatial_pages else None
    context_label = entry_context_label(entry, by_id)
    spatial_output_path = build_spatial_relative_path(entry.output_path) if spatial_pages and entry.output_path else None
    flat_output_path = (
        build_flat_leaf_relative_path(book_id, entry, by_id, start_label, end_label)
        if entry.output_path and not entry.children
        else None
    )
    rag_output_path = (
        build_rag_leaf_relative_path(book_id, entry, by_id, start_label, end_label)
        if entry.output_path and not entry.children and spatial_output_path
        else None
    )

    frontmatter = yaml_frontmatter(
        {
            "title": entry.title,
            "display_title": entry.display_title,
            "kind": entry.kind,
            "marker": entry.marker,
            "book_page_start": start_label,
            "book_page_end": end_label,
            "pdf_page_start": actual_start_pdf_page,
            "pdf_page_end": actual_end_pdf_page,
            "context_path": context_label,
            "spatial_sidecar": spatial_output_path,
            "flat_export": flat_output_path,
            "rag_export": rag_output_path,
            "children": [by_id[child_id].title for child_id in entry.children],
        }
    )

    sections: list[str] = [frontmatter, "", f"# {entry.title}"]
    if entry.marker:
        sections.extend(["", f"_{entry.marker}_"])
    if context_label:
        sections.extend(["", f"Context: {context_label}"])
    if actual_start_pdf_page and actual_end_pdf_page and actual_end_pdf_page >= actual_start_pdf_page:
        sections.extend(
            [
                "",
                f"Source pages: {format_page_range(start_label, end_label)} "
                f"(PDF {actual_start_pdf_page}-{actual_end_pdf_page}).",
            ]
        )
    children_block = render_children_list(entry, by_id)
    if children_block:
        sections.extend(["", children_block])
    if body_parts:
        sections.extend(["", "\n\n".join(body_parts)])
    text = "\n".join(section for section in sections if section is not None).rstrip() + "\n"
    rag_text = render_rag_linearized_markdown(
        entry,
        context_label,
        start_label,
        end_label,
        actual_start_pdf_page,
        actual_end_pdf_page,
        rag_output_path,
        spatial_output_path,
        spatial_pages,
    )

    manifest = {
        "entry_id": entry.id,
        "kind": entry.kind,
        "title": entry.title,
        "output_path": entry.output_path,
        "flat_output_path": flat_output_path,
        "rag_output_path": rag_output_path,
        "spatial_output_path": spatial_output_path,
        "context_path": context_label,
        "book_page_start": start_label,
        "book_page_end": end_label,
        "pdf_page_start": actual_start_pdf_page,
        "pdf_page_end": actual_end_pdf_page,
        "complex_pdf_pages": complex_pages,
        "child_ids": entry.children,
    }
    spatial_payload = None
    if spatial_output_path:
        spatial_payload = {
            "entry_id": entry.id,
            "title": entry.title,
            "display_title": entry.display_title,
            "kind": entry.kind,
            "context_path": context_label,
            "book_page_start": start_label,
            "book_page_end": end_label,
            "pdf_page_start": actual_start_pdf_page,
            "pdf_page_end": actual_end_pdf_page,
            "pages": spatial_pages,
        }
    return text, rag_text, manifest, spatial_payload


def render_auxiliary_markdown(
    title: str,
    page_label_start: str | None,
    numbering: str,
    pdf_start: int,
    pdf_end: int,
    relative_path: str,
    doc: fitz.Document,
    layout_pages: list[str],
    page_profiles: dict[int, dict[str, Any]],
    book_id: str,
) -> tuple[str, str | None, dict[str, Any], dict[str, Any] | None]:
    pseudo_entry = TocEntry(
        id=f"aux-{slugify(title)}",
        kind="auxiliary",
        level=1,
        title=title,
        page_label=page_label_start,
        numbering=numbering,
        marker=None,
        pdf_page=pdf_start,
        end_pdf_page=pdf_end,
        output_path=relative_path,
        sequence=0,
        slug=slugify(title),
    )
    text, rag_text, manifest, spatial_payload = render_entry_markdown(
        pseudo_entry,
        [pseudo_entry],
        doc,
        layout_pages,
        page_profiles,
        book_id,
    )
    manifest["kind"] = "auxiliary"
    if spatial_payload:
        spatial_payload["kind"] = "auxiliary"
    return text, rag_text, manifest, spatial_payload


def write_markdown_file(base_dir: Path, relative_path: str, content: str) -> None:
    path = base_dir / relative_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def write_json_file(base_dir: Path, relative_path: str, payload: dict[str, Any]) -> None:
    path = base_dir / relative_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def build_index_markdown(metadata: dict[str, Any], file_manifest: list[dict[str, Any]]) -> str:
    citation = metadata["citation"]
    flat_count = sum(1 for item in file_manifest if item.get("flat_output_path"))
    rag_count = sum(1 for item in file_manifest if item.get("rag_output_path"))
    spatial_count = sum(1 for item in file_manifest if item.get("spatial_output_path"))
    lines = [
        f"# {citation.get('title') or metadata['source']['filename']}",
        "",
        "## Citation",
        "",
    ]
    if citation.get("recommended_citation"):
        lines.append(citation["recommended_citation"])
        lines.append("")
    lines.extend(
        [
            "## Bundle Contents",
            "",
            f"- Metadata: [metadata.json](metadata.json)",
            f"- Table of contents: [toc.md](toc.md)",
            f"- File count: {len(file_manifest)}",
            f"- Flat leaf exports: {flat_count}",
            f"- RAG linearized leaf exports: {rag_count}",
            f"- Spatial sidecars: {spatial_count}",
        ]
    )
    return "\n".join(lines).rstrip() + "\n"


def build_toc_markdown(entries: list[TocEntry]) -> str:
    lines = ["# Table of Contents", ""]
    for entry in entries:
        indent = "  " * max(entry.level - 1, 0)
        page_label = entry.page_label or "?"
        lines.append(f"{indent}- [{entry.display_title}]({entry.output_path}) ({page_label})")
    return "\n".join(lines).rstrip() + "\n"


def entries_to_tree(entries: list[TocEntry]) -> list[dict[str, Any]]:
    by_id = get_entry_by_id(entries)

    def walk(entry: TocEntry) -> dict[str, Any]:
        return {
            "id": entry.id,
            "kind": entry.kind,
            "title": entry.title,
            "display_title": entry.display_title,
            "marker": entry.marker,
            "page_label": entry.page_label,
            "numbering": entry.numbering,
            "pdf_page": entry.pdf_page,
            "end_pdf_page": entry.end_pdf_page,
            "output_path": entry.output_path,
            "children": [walk(by_id[child_id]) for child_id in entry.children],
        }

    roots = [entry for entry in entries if not entry.parent_id]
    return [walk(entry) for entry in roots]


def main() -> int:
    args = parse_args()
    input_pdf = args.input_pdf.resolve()
    output_dir = args.output_dir.resolve()

    if not input_pdf.exists():
        raise SystemExit(f"Input PDF not found: {input_pdf}")
    if output_dir.exists():
        if not args.force:
            raise SystemExit(f"Output directory already exists: {output_dir} (use --force to replace it)")
        shutil.rmtree(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    doc = fitz.open(input_pdf)
    reader = PdfReader(str(input_pdf))
    layout_pages = load_layout_pages(input_pdf, len(doc))
    toc_start, toc_end = detect_toc_range(layout_pages)
    entries = parse_toc_entries(layout_pages, toc_start, toc_end)
    page_map = assign_pdf_pages(entries, doc, len(doc))
    assign_output_paths(entries)

    page_profiles = {
        page_number: analyze_page_layout(doc[page_number - 1], layout_pages[page_number - 1])
        for page_number in range(1, len(doc) + 1)
    }

    metadata_pages = layout_pages[: toc_start - 1] if toc_start and toc_start > 1 else layout_pages[:8]
    citation = build_citation_metadata(metadata_pages)
    book_id = args.book_id or slugify(
        f"{(citation.get('authors') or [input_pdf.stem])[0]}-{citation.get('title') or input_pdf.stem}"
    )
    file_manifest: list[dict[str, Any]] = []

    first_toc_entry = entries[0]
    if first_toc_entry.pdf_page and first_toc_entry.pdf_page > 1:
        prelim_text, prelim_rag_text, prelim_manifest, prelim_spatial = render_auxiliary_markdown(
            title="Preliminaries",
            page_label_start="i",
            numbering="roman",
            pdf_start=1,
            pdf_end=toc_start - 1,
            relative_path="frontmatter/00-preliminaries.md",
            doc=doc,
            layout_pages=layout_pages,
            page_profiles=page_profiles,
            book_id=book_id,
        )
        write_markdown_file(output_dir, "frontmatter/00-preliminaries.md", prelim_text)
        if prelim_spatial and prelim_manifest.get("spatial_output_path"):
            write_json_file(output_dir, prelim_manifest["spatial_output_path"], prelim_spatial)
        if prelim_manifest.get("flat_output_path"):
            write_markdown_file(output_dir, prelim_manifest["flat_output_path"], prelim_text)
        if prelim_rag_text and prelim_manifest.get("rag_output_path"):
            write_markdown_file(output_dir, prelim_manifest["rag_output_path"], prelim_rag_text)
        file_manifest.append(prelim_manifest)

    toc_text, toc_rag_text, toc_manifest, toc_spatial = render_auxiliary_markdown(
        title="Printed Table of Contents",
        page_label_start=int_to_roman(toc_start),
        numbering="roman",
        pdf_start=toc_start,
        pdf_end=toc_end,
        relative_path="frontmatter/01-contents.md",
        doc=doc,
        layout_pages=layout_pages,
        page_profiles=page_profiles,
        book_id=book_id,
    )
    write_markdown_file(output_dir, "frontmatter/01-contents.md", toc_text)
    if toc_spatial and toc_manifest.get("spatial_output_path"):
        write_json_file(output_dir, toc_manifest["spatial_output_path"], toc_spatial)
    if toc_manifest.get("flat_output_path"):
        write_markdown_file(output_dir, toc_manifest["flat_output_path"], toc_text)
    if toc_rag_text and toc_manifest.get("rag_output_path"):
        write_markdown_file(output_dir, toc_manifest["rag_output_path"], toc_rag_text)
    file_manifest.append(toc_manifest)

    for entry in entries:
        if not entry.output_path:
            continue
        rendered, rag_rendered, manifest, spatial_payload = render_entry_markdown(
            entry,
            entries,
            doc,
            layout_pages,
            page_profiles,
            book_id,
        )
        write_markdown_file(output_dir, entry.output_path, rendered)
        if spatial_payload and manifest.get("spatial_output_path"):
            write_json_file(output_dir, manifest["spatial_output_path"], spatial_payload)
        if manifest.get("flat_output_path"):
            write_markdown_file(output_dir, manifest["flat_output_path"], rendered)
        if rag_rendered and manifest.get("rag_output_path"):
            write_markdown_file(output_dir, manifest["rag_output_path"], rag_rendered)
        file_manifest.append(manifest)

    flat_leaf_manifest = [
        {
            "entry_id": item["entry_id"],
            "title": item["title"],
            "output_path": item["output_path"],
            "flat_output_path": item["flat_output_path"],
        }
        for item in file_manifest
        if item.get("flat_output_path")
    ]
    if flat_leaf_manifest:
        write_json_file(output_dir, "flat/leaf-nodes/manifest.json", {"book_id": book_id, "files": flat_leaf_manifest})

    rag_leaf_manifest = [
        {
            "entry_id": item["entry_id"],
            "title": item["title"],
            "output_path": item["output_path"],
            "rag_output_path": item["rag_output_path"],
        }
        for item in file_manifest
        if item.get("rag_output_path")
    ]
    if rag_leaf_manifest:
        write_json_file(output_dir, "rag/leaf-nodes/manifest.json", {"book_id": book_id, "files": rag_leaf_manifest})

    metadata = {
        "book_id": book_id,
        "source": {
            "filename": input_pdf.name,
            "absolute_path": str(input_pdf),
            "sha256": sha256(input_pdf),
            "page_count": len(doc),
            "pdf_metadata": doc.metadata,
            "reader_metadata": {key[1:]: value for key, value in (reader.metadata or {}).items()},
            "pdfinfo": parse_pdfinfo(input_pdf),
        },
        "citation": citation,
        "extraction": {
            "tool": "pdf-to-structured-markdown",
            "script_version": SCRIPT_VERSION,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "toc_pdf_range": {"start": toc_start, "end": toc_end},
            "page_map": page_map,
            "channels": {
                "semantic_markdown": True,
                "spatial_sidecars": True,
                "flat_leaf_exports": True,
                "rag_linearized_leaf_exports": True,
            },
        },
        "layout_profiles": {
            "complex_pages": [
                {
                    "pdf_page": page_number,
                    **profile,
                }
                for page_number, profile in page_profiles.items()
                if profile["complex"]
            ],
            "summary": dict(Counter(profile["kind"] for profile in page_profiles.values())),
        },
        "toc": entries_to_tree(entries),
        "file_manifest": file_manifest,
        "flat_leaf_manifest_path": "flat/leaf-nodes/manifest.json" if flat_leaf_manifest else None,
        "rag_leaf_manifest_path": "rag/leaf-nodes/manifest.json" if rag_leaf_manifest else None,
    }

    (output_dir / "metadata.json").write_text(
        json.dumps(metadata, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    (output_dir / "index.md").write_text(build_index_markdown(metadata, file_manifest), encoding="utf-8")
    (output_dir / "toc.md").write_text(build_toc_markdown(entries), encoding="utf-8")
    write_manifest(
        "bundle_generation",
        output_dir / "run-manifest.json",
        {
            "generated_at": metadata["extraction"]["generated_at"],
            "book_id": metadata["book_id"],
            "source": {
                "filename": input_pdf.name,
                "absolute_path": str(input_pdf.resolve()),
                "sha256": metadata["source"]["sha256"],
                "page_count": metadata["source"]["page_count"],
            },
            "converter_version": SCRIPT_VERSION,
            "output_dir": str(output_dir.resolve()),
        },
    )

    print(json.dumps({"output_dir": str(output_dir), "book_id": metadata["book_id"]}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
