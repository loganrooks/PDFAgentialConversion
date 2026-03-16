#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="List available semantic and RAG regression anchors in a generated bundle."
    )
    parser.add_argument("bundle_dir", type=Path)
    parser.add_argument(
        "--path-contains",
        help="Only include files whose relative path contains this substring.",
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


def passage_fields_from_body(body: str) -> dict[str, str]:
    fields: dict[str, str] = {}
    label_match = re.search(r"^Label:\s*(.+)$", body, re.MULTILINE)
    if label_match:
        fields["label"] = label_match.group(1).strip()
    source_pages_match = re.search(r"^Source page labels:\s*(.+)$", body, re.MULTILINE)
    if source_pages_match:
        fields["source_pages"] = source_pages_match.group(1).strip()
    return fields


def collect_file_paths(metadata: dict[str, Any]) -> list[str]:
    seen: set[str] = set()
    paths: list[str] = []
    for item in metadata.get("file_manifest", []):
        for key in ("output_path", "rag_output_path"):
            path = item.get(key)
            if path and path not in seen:
                seen.add(path)
                paths.append(path)
    return paths


def catalog_file(text: str) -> list[dict[str, Any]]:
    anchors: list[dict[str, Any]] = []

    for match in re.finditer(r"^<!-- semantic-page: (?P<anchor>[^\n]+) -->$", text, re.MULTILINE):
        anchors.append({"kind": "semantic-page", **parse_anchor_fields(match.group("anchor"))})

    passage_pattern = re.compile(
        r"^(?:<!-- rag-passage: (?P<anchor>[^\n]+) -->\n)?## Passage (?P<ordinal>\d+)(?: \((?P<label>[^)]+)\))?\n(?P<body>.*?)(?=^(?:<!-- rag-passage: [^\n]+ -->\n)?## Passage |\Z)",
        re.MULTILINE | re.DOTALL,
    )
    block_pattern = re.compile(
        r"^(?:<!-- rag-block: (?P<anchor>[^\n]+) -->\n)?### (?P<kind>Citation|Commentary|Reference Notes)\n\n(?P<body>.*?)(?=^(?:<!-- rag-block: [^\n]+ -->\n)?### |\n## Passage |\Z)",
        re.MULTILINE | re.DOTALL,
    )

    for match in passage_pattern.finditer(text):
        fields = parse_anchor_fields(match.group("anchor") or "")
        fields.setdefault("ordinal", match.group("ordinal"))
        if match.group("label"):
            fields.setdefault("label", match.group("label"))
        fields.update(passage_fields_from_body(match.group("body")))
        anchors.append({"kind": "rag-passage", **fields})

        for block_match in block_pattern.finditer(match.group("body")):
            fields = {
                **parse_anchor_fields(block_match.group("anchor") or ""),
                "ordinal": match.group("ordinal"),
                "label": match.group("label") or fields.get("label"),
                "block": block_match.group("kind"),
            }
            anchors.append({"kind": "rag-block", **fields})

    return anchors


def main() -> int:
    args = parse_args()
    bundle_dir = args.bundle_dir.resolve()
    metadata = load_json(bundle_dir / "metadata.json")

    files: list[dict[str, Any]] = []
    total = 0
    for relative_path in collect_file_paths(metadata):
        if args.path_contains and args.path_contains not in relative_path:
            continue
        full_path = bundle_dir / relative_path
        if not full_path.exists():
            continue
        anchors = catalog_file(full_path.read_text(encoding="utf-8"))
        if not anchors:
            continue
        total += len(anchors)
        files.append({"path": relative_path, "anchor_count": len(anchors), "anchors": anchors})

    print(
        json.dumps(
            {
                "bundle_dir": str(bundle_dir),
                "file_count": len(files),
                "anchor_count": total,
                "files": files,
            },
            indent=2,
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
