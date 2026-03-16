#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from pathlib import Path
from typing import Any


REPEATED_WORD_RE = re.compile(r"\b([A-Za-z][A-Za-z'’-]{2,})\s+\1\b", re.IGNORECASE)
ANCHOR_RE = re.compile(r"^\d+[a-z]\)")
SEMANTIC_PAGE_RE = re.compile(
    r"^<!-- source-page-label: (?P<page_label>[^;]+); pdf-page: (?P<pdf_page>\d+); layout: (?P<layout>[^>]+) -->\n(?:<!-- semantic-page: [^\n]+ -->\n)?(?P<body>.*?)(?=^<!-- source-page-label: |\Z)",
    re.MULTILINE | re.DOTALL,
)
RAG_PASSAGE_RE = re.compile(
    r"^(?:<!-- rag-passage: (?P<anchor>[^\n]+) -->\n)?## Passage (?P<ordinal>\d+)(?: \((?P<label>[^)]+)\))?\n(?P<body>.*?)(?=^(?:<!-- rag-passage: [^\n]+ -->\n)?## Passage |\Z)",
    re.MULTILINE | re.DOTALL,
)
RAG_BLOCK_RE = re.compile(
    r"^(?:<!-- rag-block: (?P<anchor>[^\n]+) -->\n)?### (?P<kind>Citation|Commentary|Reference Notes)\n\n(?P<body>.*?)(?=^(?:<!-- rag-block: [^\n]+ -->\n)?### |\n## Passage |\Z)",
    re.MULTILINE | re.DOTALL,
)
SUSPICIOUS_REPEAT_WORDS = {
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
}
DANGLING_END_WORDS = {
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
    "of",
    "on",
    "or",
    "that",
    "the",
    "this",
    "to",
    "with",
    "which",
}
DANGLING_END_BIGRAMS = {
    ("and", "the"),
    ("of", "the"),
    ("to", "the"),
    ("for", "the"),
    ("in", "the"),
}
MAX_UNANCHORED_ATOMIC_BLOCK_TOKENS = 1600


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Probe a generated bundle for likely semantic artifact patterns."
    )
    parser.add_argument("bundle_dir", type=Path)
    parser.add_argument(
        "--max-issues",
        type=int,
        default=200,
        help="Cap the number of reported issues.",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Exit non-zero when any issue is found.",
    )
    return parser.parse_args()


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def parse_anchor_fields(text: str) -> dict[str, str]:
    fields: dict[str, str] = {}
    if not text:
        return fields
    for part in text.split(";"):
        if "=" not in part:
            continue
        key, value = part.split("=", 1)
        fields[key.strip()] = value.strip()
    return fields


def clean_text(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def first_alpha_token(text: str) -> str | None:
    match = re.search(r"[A-Za-z][A-Za-z'’-]*", text)
    return match.group(0) if match else None


def trailing_words(text: str, count: int = 2) -> list[str]:
    words = re.findall(r"[A-Za-z][A-Za-z'’-]*", text.lower())
    return words[-count:]


def semantic_segment_scope(page_label: str, pdf_page: int) -> dict[str, Any]:
    return {
        "kind": "semantic_page",
        "page_label": page_label,
        "pdf_page": pdf_page,
    }


def rag_block_scope(fields: dict[str, str]) -> dict[str, Any]:
    scope: dict[str, Any] = {"kind": "rag_passage"}
    if fields.get("ordinal"):
        scope["index"] = int(fields["ordinal"])
    if fields.get("label"):
        scope["label"] = fields["label"]
    if fields.get("block"):
        scope["block"] = fields["block"]
    return scope


def stable_scope_key(scope_suggestion: dict[str, Any] | None) -> str:
    if not scope_suggestion:
        return ""
    return json.dumps(scope_suggestion, sort_keys=True, ensure_ascii=False)


def issue_case_key(issue: dict[str, Any]) -> str:
    extras: list[str] = []
    if issue.get("word"):
        extras.append(f"word={str(issue['word']).lower()}")
    if issue.get("tail"):
        extras.append(f"tail={str(issue['tail']).lower()}")
    if issue.get("pdf_page") is not None:
        extras.append(f"pdf_page={issue['pdf_page']}")
    if issue.get("region_count") is not None:
        extras.append(f"region_count={issue['region_count']}")
    parts = [
        str(issue.get("code") or "unknown"),
        str(issue.get("path") or ""),
        stable_scope_key(issue.get("scope_suggestion")),
    ]
    if extras:
        parts.append("|".join(extras))
    return "::".join(part for part in parts if part)


def issue_case_details(issue: dict[str, Any]) -> dict[str, Any]:
    details = {
        "code": issue.get("code"),
        "issue_key": issue_case_key(issue),
        "path": issue.get("path"),
        "scope_suggestion": issue.get("scope_suggestion"),
        "content_mode": issue.get("content_mode"),
        "snippet": issue.get("snippet"),
    }
    for key in ("word", "tail", "pdf_page", "region_count", "examples", "block_kind"):
        if key in issue and issue.get(key) is not None:
            details[key] = issue.get(key)
    return details


def summarize_issue_cases(issues: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for issue in issues:
        code = str(issue.get("code") or "unknown")
        grouped.setdefault(code, []).append(issue_case_details(issue))
    return grouped


def passage_fields_from_body(body: str) -> dict[str, str]:
    fields: dict[str, str] = {}
    label_match = re.search(r"^Label:\s*(.+)$", body, re.MULTILINE)
    if label_match:
        fields["label"] = label_match.group(1).strip()
    source_pages_match = re.search(r"^Source page labels:\s*(.+)$", body, re.MULTILINE)
    if source_pages_match:
        fields["source_pages"] = source_pages_match.group(1).strip()
    return fields


def repeated_word_issues(
    text: str,
    path: str,
    *,
    content_mode: str,
    scope_suggestion: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    if content_mode != "prose":
        return []
    issues: list[dict[str, Any]] = []
    for match in REPEATED_WORD_RE.finditer(text):
        word = match.group(1)
        if word.lower() not in SUSPICIOUS_REPEAT_WORDS:
            continue
        issues.append(
            {
                "severity": "warn",
                "code": "repeated_adjacent_word",
                "path": path,
                "word": word,
                "content_mode": content_mode,
                "scope_suggestion": scope_suggestion,
                "snippet": clean_text(text[max(match.start() - 40, 0) : match.end() + 40]),
            }
        )
    return issues


def iter_semantic_segments(text: str, *, default_content_mode: str) -> list[dict[str, Any]]:
    segments: list[dict[str, Any]] = []
    for match in SEMANTIC_PAGE_RE.finditer(text):
        layout = match.group("layout").strip()
        content_mode = default_content_mode
        if content_mode == "prose" and layout == "table":
            content_mode = "table"
        segments.append(
            {
                "page_label": match.group("page_label").strip(),
                "pdf_page": int(match.group("pdf_page")),
                "layout": layout,
                "content_mode": content_mode,
                "body": match.group("body"),
            }
        )
    return segments


def resolve_rag_block_content_mode(
    passage_fields: dict[str, str],
    *,
    default_content_mode: str,
    page_content_modes: dict[str, str],
) -> str:
    page_labels = [
        label.strip()
        for label in (passage_fields.get("source_pages") or "").split(",")
        if label.strip()
    ]
    modes = {
        page_content_modes.get(label, default_content_mode)
        for label in page_labels
    }
    if not modes:
        return default_content_mode
    if len(modes) == 1:
        return next(iter(modes))
    if "prose" in modes:
        return "prose"
    if "table" in modes:
        return "table"
    return default_content_mode


def iter_rag_blocks(
    text: str,
    *,
    default_content_mode: str,
    page_content_modes: dict[str, str],
) -> list[dict[str, Any]]:
    blocks: list[dict[str, Any]] = []
    for passage_match in RAG_PASSAGE_RE.finditer(text):
        passage_fields = parse_anchor_fields(passage_match.group("anchor") or "")
        passage_fields.setdefault("ordinal", passage_match.group("ordinal"))
        if passage_match.group("label"):
            passage_fields.setdefault("label", passage_match.group("label"))
        passage_fields.update(passage_fields_from_body(passage_match.group("body")))
        passage_body = passage_match.group("body")
        content_mode = resolve_rag_block_content_mode(
            passage_fields,
            default_content_mode=default_content_mode,
            page_content_modes=page_content_modes,
        )
        for block_match in RAG_BLOCK_RE.finditer(passage_body):
            fields = {
                **passage_fields,
                **parse_anchor_fields(block_match.group("anchor") or ""),
                "block": block_match.group("kind"),
            }
            blocks.append(
                {
                    "kind": block_match.group("kind"),
                    "body": block_match.group("body"),
                    "content_mode": content_mode,
                    "scope_suggestion": rag_block_scope(fields),
                    "token_count": len(re.findall(r"[A-Za-z0-9]+", block_match.group("body"))),
                }
            )
    commentary_indexes = [index for index, block in enumerate(blocks) if block["kind"] == "Commentary"]
    if commentary_indexes:
        first_index = commentary_indexes[0]
        last_index = commentary_indexes[-1]
        for index in commentary_indexes:
            blocks[index]["is_first_commentary"] = index == first_index
            blocks[index]["is_last_commentary"] = index == last_index
    return blocks


def page_content_mode_map(bundle_dir: Path, spatial_path: str | None) -> dict[str, str]:
    if not spatial_path:
        return {}
    full_path = bundle_dir / spatial_path
    if not full_path.exists():
        return {}
    payload = load_json(full_path)
    return {
        str(page.get("page_label")): page.get("content_mode", "prose")
        for page in payload.get("pages", [])
        if page.get("page_label") is not None
    }


def spatial_pages(bundle_dir: Path, spatial_path: str | None) -> list[dict[str, Any]]:
    if not spatial_path:
        return []
    full_path = bundle_dir / spatial_path
    if not full_path.exists():
        return []
    payload = load_json(full_path)
    return payload.get("pages", [])


def rag_block_issues(
    blocks: list[dict[str, Any]],
    path: str,
    *,
    first_page_sliced_start: bool,
    last_page_sliced_end: bool,
) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    for block in blocks:
        block_kind = block["kind"]
        if block_kind != "Commentary":
            continue
        if block["content_mode"] != "prose":
            continue
        raw_body = re.sub(r"<!--.*?-->", " ", block["body"], flags=re.DOTALL)
        body = clean_text(raw_body)
        if not body:
            continue
        first_token = first_alpha_token(body)
        if (
            block.get("is_first_commentary")
            and not first_page_sliced_start
            and first_token
            and first_token[0].islower()
        ):
            issues.append(
                {
                    "severity": "warn",
                    "code": "rag_block_lowercase_start",
                    "path": path,
                    "block_kind": block_kind,
                    "content_mode": block["content_mode"],
                    "scope_suggestion": block["scope_suggestion"],
                    "snippet": body[:180],
                }
            )
        if block.get("is_last_commentary") and not last_page_sliced_end and body.endswith("-"):
            issues.append(
                {
                    "severity": "warn",
                    "code": "rag_block_hyphen_end",
                    "path": path,
                    "block_kind": block_kind,
                    "content_mode": block["content_mode"],
                    "scope_suggestion": block["scope_suggestion"],
                    "snippet": body[-180:],
                }
            )
            continue
        if block.get("is_last_commentary") and not last_page_sliced_end and not re.search(r'[.!?:"”\')\]]$', body):
            tail = trailing_words(body, 2)
            if tail:
                if tail[-1] in DANGLING_END_WORDS or tuple(tail) in DANGLING_END_BIGRAMS:
                    issues.append(
                        {
                            "severity": "warn",
                            "code": "rag_block_dangling_end",
                            "path": path,
                            "block_kind": block_kind,
                            "content_mode": block["content_mode"],
                            "scope_suggestion": block["scope_suggestion"],
                            "tail": " ".join(tail),
                            "snippet": body[-180:],
                        }
                    )
        if (
            not block["scope_suggestion"].get("label")
            and block["token_count"] > MAX_UNANCHORED_ATOMIC_BLOCK_TOKENS
        ):
            issues.append(
                {
                    "severity": "warn",
                    "code": "oversized_unanchored_atomic_block",
                    "path": path,
                    "block_kind": block_kind,
                    "content_mode": block["content_mode"],
                    "scope_suggestion": block["scope_suggestion"],
                    "token_count": block["token_count"],
                    "snippet": body[:180],
                }
            )
    return issues


def boundary_micro_fragment_issues(bundle_dir: Path, manifest_item: dict[str, Any]) -> list[dict[str, Any]]:
    spatial_path = manifest_item.get("spatial_output_path")
    if not spatial_path:
        return []
    full_path = bundle_dir / spatial_path
    if not full_path.exists():
        return []
    payload = load_json(full_path)
    issues: list[dict[str, Any]] = []
    for page in payload.get("pages", []):
        if page.get("slice_min_y") is None and page.get("slice_max_y") is None:
            continue
        if page.get("content_mode", "prose") != "prose":
            continue
        micro_regions: list[str] = []
        for region in page.get("regions", []):
            raw_text = clean_text(region.get("raw_text", ""))
            if not raw_text or ANCHOR_RE.match(raw_text):
                continue
            if len(raw_text) <= 18:
                micro_regions.append(raw_text)
        if len(micro_regions) >= 6:
            issues.append(
                {
                    "severity": "warn",
                    "code": "boundary_page_many_micro_regions",
                    "path": manifest_item.get("output_path"),
                    "pdf_page": page.get("pdf_page"),
                    "content_mode": page.get("content_mode", "prose"),
                    "scope_suggestion": semantic_segment_scope(
                        str(page.get("page_label")),
                        int(page.get("pdf_page")),
                    ),
                    "region_count": len(micro_regions),
                    "examples": micro_regions[:8],
                }
            )
    return issues


def main() -> int:
    args = parse_args()
    bundle_dir = args.bundle_dir.resolve()
    metadata = load_json(bundle_dir / "metadata.json")
    file_manifest = metadata.get("file_manifest", [])

    issues: list[dict[str, Any]] = []
    scanned_paths: set[str] = set()

    for item in file_manifest:
        kind = item.get("kind")
        output_path = item.get("output_path")
        if output_path and output_path not in scanned_paths:
            full_path = bundle_dir / output_path
            if full_path.exists():
                text = full_path.read_text(encoding="utf-8")
                default_content_mode = "index" if kind == "index" else "prose"
                semantic_segments = iter_semantic_segments(text, default_content_mode=default_content_mode)
                if semantic_segments:
                    for segment in semantic_segments:
                        issues.extend(
                            repeated_word_issues(
                                segment["body"],
                                output_path,
                                content_mode=segment["content_mode"],
                                scope_suggestion=semantic_segment_scope(
                                    segment["page_label"],
                                    segment["pdf_page"],
                                ),
                            )
                        )
                else:
                    issues.extend(
                        repeated_word_issues(
                            text,
                            output_path,
                            content_mode=default_content_mode,
                            scope_suggestion=None,
                        )
                    )
                scanned_paths.add(output_path)
        rag_path = item.get("rag_output_path")
        if rag_path and rag_path not in scanned_paths:
            full_path = bundle_dir / rag_path
            if full_path.exists():
                text = full_path.read_text(encoding="utf-8")
                default_content_mode = "index" if kind == "index" else "prose"
                rag_blocks = iter_rag_blocks(
                    text,
                    default_content_mode=default_content_mode,
                    page_content_modes=page_content_mode_map(
                        bundle_dir,
                        item.get("spatial_output_path"),
                    ),
                )
                page_slices = spatial_pages(bundle_dir, item.get("spatial_output_path"))
                for block in rag_blocks:
                    issues.extend(
                        repeated_word_issues(
                            block["body"],
                            rag_path,
                            content_mode=block["content_mode"],
                            scope_suggestion=block["scope_suggestion"],
                        )
                    )
                if kind not in {"frontmatter", "index"}:
                    issues.extend(
                        rag_block_issues(
                            rag_blocks,
                            rag_path,
                            first_page_sliced_start=bool(
                                page_slices and page_slices[0].get("slice_min_y") is not None
                            ),
                            last_page_sliced_end=bool(
                                page_slices and page_slices[-1].get("slice_max_y") is not None
                            ),
                        )
                    )
                scanned_paths.add(rag_path)
        issues.extend(boundary_micro_fragment_issues(bundle_dir, item))

    if len(issues) > args.max_issues:
        issues = issues[: args.max_issues]

    annotated_issues = [issue | {"issue_key": issue_case_key(issue)} for issue in issues]
    summary = Counter(issue["code"] for issue in issues)
    report = {
        "bundle_dir": str(bundle_dir),
        "issue_count": len(issues),
        "issue_summary": dict(summary),
        "summary_by_code": dict(summary),
        "issue_codes": sorted(summary.keys()),
        "issues_by_code": summarize_issue_cases(annotated_issues),
        "issues": annotated_issues,
    }
    print(json.dumps(report, indent=2, ensure_ascii=False))

    if issues and args.strict:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
