from __future__ import annotations

from pdfmd.convert.convert_pdf import *  # noqa: F401,F403

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


def detect_entry_heading_band(
    entry: TocEntry,
    previous_entry: TocEntry | None,
    page: fitz.Page,
    by_id: dict[str, TocEntry],
) -> tuple[float, float] | None:
    self_band = detect_heading_band(page, entry_heading_keys(entry), prefer="last")
    if self_band is not None:
        return self_band
    if (
        previous_entry
        and previous_entry.parent_id == entry.parent_id
        and (
            previous_entry.page_label == entry.page_label
            or previous_entry.pdf_page is None
        )
    ):
        sibling_band = detect_heading_band(
            page,
            entry_heading_keys(entry) | entry_heading_keys(previous_entry),
            prefer="last",
        )
        if sibling_band is not None:
            return sibling_band
    return detect_heading_band(page, heading_skip_keys(entry, by_id), prefer="first")


def detect_entry_start_cutoff(
    entry: TocEntry,
    previous_entry: TocEntry | None,
    page: fitz.Page,
    by_id: dict[str, TocEntry],
) -> float | None:
    band = detect_entry_heading_band(entry, previous_entry, page, by_id)
    return band[1] if band else None


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
    texts = [clean_text_line(region.get("raw_text", "")) for region in regions]
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
    if previous["zone"] == current["zone"]:
        return True
    if abs(previous["x0"] - current["x0"]) <= 60:
        return True
    if abs(previous["x1"] - current["x1"]) <= 120:
        return True
    return False


def y_positions_compatible(previous: dict[str, Any], current: dict[str, Any]) -> bool:
    previous_page = int(previous.get("pdf_page") or 0)
    current_page = int(current.get("pdf_page") or previous_page)
    if not previous_page:
        previous_page = current_page
    page_gap = current_page - previous_page
    if page_gap == 0:
        y_gap = current["y0"] - previous["y1"]
        return -2.0 <= y_gap <= 28.0
    if page_gap == 1:
        return previous["y1"] >= 430.0 and current["y0"] <= 90.0
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
        continuation = bool(
            previous
            and (
                previous.get("reference_note_seed")
                or previous.get("reference_note_continuation")
            )
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


def repair_passage_commentary_boundaries(passages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if len(passages) < 2:
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
                    "attach_to_next_anchor": bool(
                        next_anchor_label
                        and next_anchor_zone
                        and region["zone"] != next_anchor_zone
                        and distance_to_next_anchor is not None
                        and distance_to_next_anchor <= 18.0
                        and looks_incomplete_rag_lead(region["rag_text"])
                        and not is_reference_note_text(region["rag_text"])
                    ),
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
        if total_segment_count <= 1 and not overflow_detected:
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
        bucket = inherited_bucket
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


def detect_heading_band_from_lines(
    line_items: list[dict[str, Any]],
    skip_keys: set[str],
    *,
    prefer: str = "first",
) -> tuple[float, float] | None:
    merged = collapse_inline_fragments(
        sorted(line_items, key=lambda item: (item["y0"], item["x0"])),
        allow_title_case=True,
    )
    matches: list[tuple[float, float]] = []
    for item in merged:
        cleaned = clean_text_line(item["text"])
        if cleaned and keyify(cleaned) in skip_keys:
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
    return detect_heading_band_from_lines(line_items, skip_keys, prefer=prefer)


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

    main_regions = [region["semantic_text"].strip() for region in regions if region["role"] == "main" and region["semantic_text"].strip()]
    aside_regions = [region["semantic_text"].strip() for region in regions if region["role"] == "aside" and region["semantic_text"].strip()]

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
            boundary_page = doc[boundary_entry.pdf_page - 1]
            boundary_profile = page_profiles[boundary_entry.pdf_page]
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
                        min_y=heading_band[1],
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
                                    "min_y": heading_band[1],
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
