from __future__ import annotations

from pdfmd.convert.convert_pdf import *  # noqa: F401,F403

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


def normalize_title_line(line: str) -> str:
    stripped = clean_text_line(line)
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
