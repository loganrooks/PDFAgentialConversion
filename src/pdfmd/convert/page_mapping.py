from __future__ import annotations

from pdfmd.convert.convert_pdf import *  # noqa: F401,F403

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
        title_candidate = clean_text_line(page_match.group(1)) if page_match else clean_text_line(line)
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
