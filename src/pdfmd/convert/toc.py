from __future__ import annotations

from pdfmd.convert.convert_pdf import *  # noqa: F401,F403

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
