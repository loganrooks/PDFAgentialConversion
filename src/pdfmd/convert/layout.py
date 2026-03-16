from __future__ import annotations

from pdfmd.convert.convert_pdf import *  # noqa: F401,F403

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
