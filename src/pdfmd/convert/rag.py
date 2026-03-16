from __future__ import annotations

from pdfmd.convert.convert_pdf import *  # noqa: F401,F403

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
