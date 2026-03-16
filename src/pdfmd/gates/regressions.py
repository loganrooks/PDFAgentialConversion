#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Check a generated bundle against a deterministic regression spec."
    )
    parser.add_argument("bundle_dir", type=Path)
    parser.add_argument("spec", type=Path)
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Exit non-zero when any regression check fails.",
    )
    return parser.parse_args()


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def parse_anchor_fields(text: str) -> dict[str, str]:
    fields: dict[str, str] = {}
    for part in text.split(";"):
        if "=" not in part:
            continue
        key, value = part.split("=", 1)
        fields[key.strip()] = value.strip()
    return fields


def passage_fields_from_body(body: str) -> dict[str, str]:
    fields: dict[str, str] = {}
    label_match = re.search(r"^Label:\s*(.+)$", body, re.MULTILINE)
    if label_match:
        fields["label"] = label_match.group(1).strip()
    source_pages_match = re.search(r"^Source page labels:\s*(.+)$", body, re.MULTILINE)
    if source_pages_match:
        fields["source_pages"] = source_pages_match.group(1).strip()
    return fields


def extract_rag_passages(text: str, label: str | None = None, index: int | None = None) -> list[str]:
    passage_pattern = re.compile(
        r"^(?:<!-- rag-passage: (?P<anchor>[^\n]+) -->\n)?## Passage (?P<ordinal>\d+)(?: \((?P<label>[^)]+)\))?\n(?P<body>.*?)(?=^(?:<!-- rag-passage: [^\n]+ -->\n)?## Passage |\Z)",
        re.MULTILINE | re.DOTALL,
    )
    matches: list[str] = []
    for match in passage_pattern.finditer(text):
        fields = {}
        if match.group("anchor"):
            fields.update(parse_anchor_fields(match.group("anchor")))
        fields.setdefault("ordinal", match.group("ordinal"))
        if match.group("label"):
            fields.setdefault("label", match.group("label"))
        fields.update(passage_fields_from_body(match.group("body")))
        if label is not None and fields.get("label") != label:
            continue
        if index is not None and fields.get("ordinal") != f"{index:03d}":
            continue
        matches.append(match.group("body"))
    return matches


def extract_rag_passage(text: str, label: str | None = None, index: int | None = None) -> str | None:
    passages = extract_rag_passages(text, label=label, index=index)
    return passages[0] if passages else None


def extract_markdown_block(text: str, heading: str) -> str | None:
    anchored_pattern = re.compile(
        rf"^(?:<!-- rag-block: (?P<anchor>[^\n]+) -->\n)?### {re.escape(heading)}\n\n(?P<body>.*?)(?=^(?:<!-- rag-block: [^\n]+ -->\n)?### |\n## Passage |\Z)",
        re.MULTILINE | re.DOTALL,
    )
    anchored_match = anchored_pattern.search(text)
    if anchored_match:
        return anchored_match.group("body")

    pattern = re.compile(
        rf"^### {re.escape(heading)}\n\n(?P<body>.*?)(?=^### |\n## Passage |\Z)",
        re.MULTILINE | re.DOTALL,
    )
    match = pattern.search(text)
    return match.group("body") if match else None


def extract_semantic_page(text: str, page_label: str | None = None, pdf_page: int | None = None) -> str | None:
    anchored_pattern = re.compile(
        r"^<!-- semantic-page: (?P<anchor>[^\n]+) -->\n(?P<body>.*?)(?=^<!-- source-page-label: |\Z)",
        re.MULTILINE | re.DOTALL,
    )
    for match in anchored_pattern.finditer(text):
        fields = parse_anchor_fields(match.group("anchor"))
        if page_label is not None and fields.get("page_label") != page_label:
            continue
        if pdf_page is not None and int(fields.get("pdf_page", "-1")) != pdf_page:
            continue
        return match.group("body")

    marker_pattern = re.compile(
        r"^<!-- source-page-label: (?P<page_label>[^;]+); pdf-page: (?P<pdf_page>\d+); layout: [^>]+ -->\n(?P<body>.*?)(?=^<!-- source-page-label: |\Z)",
        re.MULTILINE | re.DOTALL,
    )
    for match in marker_pattern.finditer(text):
        if page_label is not None and match.group("page_label") != page_label:
            continue
        if pdf_page is not None and int(match.group("pdf_page")) != pdf_page:
            continue
        return match.group("body")
    return None


def extract_spatial_page(
    text: str,
    page_label: str | None = None,
    pdf_page: int | None = None,
) -> str | None:
    payload = json.loads(text)
    for page in payload.get("pages", []):
        if page_label is not None and str(page.get("page_label")) != str(page_label):
            continue
        if pdf_page is not None and int(page.get("pdf_page", -1)) != pdf_page:
            continue
        return json.dumps(page, ensure_ascii=False)
    return None


def resolve_scope_text(text: str, scope: dict[str, Any] | None) -> tuple[str | None, str]:
    if not scope:
        return text, "full-file"

    kind = scope.get("kind")
    if kind == "rag_passage":
        passages = extract_rag_passages(text, label=scope.get("label"), index=scope.get("index"))
        if not passages:
            return None, f"rag_passage:{scope}"
        block = scope.get("block")
        if not block:
            return passages[0], f"rag_passage:{scope}"
        blocks = [
            block_text
            for passage in passages
            if (block_text := extract_markdown_block(passage, block)) is not None
        ]
        if not blocks:
            return None, f"rag_passage:{scope}"
        return "\n\n".join(blocks), f"rag_passage:{scope}"

    if kind == "semantic_page":
        page_text = extract_semantic_page(text, page_label=scope.get("page_label"), pdf_page=scope.get("pdf_page"))
        return page_text, f"semantic_page:{scope}"

    if kind == "spatial_page":
        page_text = extract_spatial_page(text, page_label=scope.get("page_label"), pdf_page=scope.get("pdf_page"))
        return page_text, f"spatial_page:{scope}"

    if kind == "markdown_block":
        block_text = extract_markdown_block(text, scope["block"])
        return block_text, f"markdown_block:{scope}"

    raise ValueError(f"Unsupported scope kind: {kind}")


def main() -> int:
    args = parse_args()
    bundle_dir = args.bundle_dir.resolve()
    spec_path = args.spec.resolve()
    spec = load_json(spec_path)
    failures: list[dict[str, Any]] = []
    passes = 0

    for check in spec.get("checks", []):
        relative_path = check["path"]
        full_path = bundle_dir / relative_path
        if not full_path.exists():
            failures.append(
                {
                    "path": relative_path,
                    "code": "missing_target_file",
                }
            )
            continue
        text = full_path.read_text(encoding="utf-8")
        scoped_text, scope_label = resolve_scope_text(text, check.get("scope"))
        if scoped_text is None:
            failures.append(
                {
                    "path": relative_path,
                    "code": "scope_not_found",
                    "scope": check.get("scope"),
                }
            )
            continue
        for needle in check.get("must_contain", []):
            if needle not in scoped_text:
                failures.append(
                    {
                        "path": relative_path,
                        "code": "missing_required_substring",
                        "needle": needle,
                        "scope": scope_label,
                    }
                )
            else:
                passes += 1
        for needle in check.get("must_not_contain", []):
            if needle in scoped_text:
                failures.append(
                    {
                        "path": relative_path,
                        "code": "forbidden_substring_present",
                        "needle": needle,
                        "scope": scope_label,
                    }
                )
            else:
                passes += 1
        for pattern in check.get("must_match", []):
            if not re.search(pattern, scoped_text, re.MULTILINE):
                failures.append(
                    {
                        "path": relative_path,
                        "code": "required_pattern_missing",
                        "pattern": pattern,
                        "scope": scope_label,
                    }
                )
            else:
                passes += 1
        for pattern in check.get("must_not_match", []):
            if re.search(pattern, scoped_text, re.MULTILINE):
                failures.append(
                    {
                        "path": relative_path,
                        "code": "forbidden_pattern_present",
                        "pattern": pattern,
                        "scope": scope_label,
                    }
                )
            else:
                passes += 1

    report = {
        "bundle_dir": str(bundle_dir),
        "spec": str(spec_path),
        "failure_count": len(failures),
        "pass_count": passes,
        "failures": failures,
    }
    print(json.dumps(report, indent=2, ensure_ascii=False))

    if failures and args.strict:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
