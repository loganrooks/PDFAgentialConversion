#!/usr/bin/env python3
from __future__ import annotations

import argparse
import datetime as dt
import json
from pathlib import Path
from typing import Any

from pdfmd.cli.quality_gate_common import (
    build_sidecar_excerpt,
    dump_json,
    extract_scope_page_refs,
    flatten_scope_entries,
    load_json,
    resolve_scope_text,
    slugify,
)

try:
    import fitz  # type: ignore
except ImportError:  # pragma: no cover - optional runtime dependency
    fitz = None


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Render the fixed manual review packet for a quality-gate config."
    )
    parser.add_argument("bundle_dir", type=Path)
    parser.add_argument("gate_config", type=Path)
    parser.add_argument(
        "--out-dir",
        type=Path,
        help="Directory for the review packet. Defaults to <bundle>/quality-gate.",
    )
    parser.add_argument(
        "--skip-images",
        action="store_true",
        help="Do not render PDF page images into the review packet.",
    )
    return parser.parse_args()


def render_page_images(
    source_pdf: Path | None,
    pdf_pages: list[int],
    out_dir: Path,
    scope_id: str,
) -> list[str]:
    if source_pdf is None or fitz is None or not source_pdf.exists():
        return []
    out_dir.mkdir(parents=True, exist_ok=True)
    document = fitz.open(source_pdf)
    image_paths: list[str] = []
    try:
        for pdf_page in pdf_pages:
            page = document.load_page(int(pdf_page) - 1)
            pixmap = page.get_pixmap(matrix=fitz.Matrix(1.5, 1.5), alpha=False)
            image_path = out_dir / f"{slugify(scope_id)}--pdf-{int(pdf_page):03d}.png"
            pixmap.save(image_path)
            image_paths.append(str(image_path.resolve()))
    finally:
        document.close()
    return image_paths


def normalize_extracted_text(text: str | None) -> str:
    if text is None:
        return ""
    return text.strip()


def format_review_packet_markdown(packet: dict[str, Any]) -> str:
    lines: list[str] = []
    lines.append(f"# Review Packet: {packet['bundle_dir']}")
    lines.append("")
    lines.append(f"- Generated: `{packet['generated_at']}`")
    lines.append(f"- Config: `{packet['config']}`")
    lines.append(f"- Entry count: `{packet['entry_count']}`")
    lines.append("")

    for entry in packet["entries"]:
        lines.append(f"## {entry['scope_id']}")
        lines.append("")
        lines.append(f"- Group: `{entry['group']}`")
        lines.append(f"- Verdict: `{entry['verdict']}`")
        lines.append(f"- Path: `{entry['path']}`")
        lines.append(f"- Source pages: `{', '.join(entry['source_page_labels']) or 'n/a'}`")
        lines.append(f"- PDF pages: `{', '.join(str(page) for page in entry['pdf_pages']) or 'n/a'}`")
        lines.append(f"- Checklist: {entry['checklist_line']}")
        lines.append("")
        lines.append("### Extracted Text")
        lines.append("")
        lines.append("```text")
        lines.append(entry["extracted_text"].rstrip())
        lines.append("```")
        lines.append("")
        lines.append("### Sidecar Excerpt")
        lines.append("")
        lines.append("```json")
        lines.append(json.dumps(entry["sidecar_excerpt"], indent=2, ensure_ascii=False))
        lines.append("```")
        lines.append("")
        if entry["page_image_paths"]:
            lines.append("### Page Images")
            lines.append("")
            for image_path in entry["page_image_paths"]:
                lines.append(f"![{entry['scope_id']}]({image_path})")
            lines.append("")
    appendix = packet.get("embedding_mismatch_appendix", {})
    if appendix:
        lines.append("## Embedding Mismatch Appendix")
        lines.append("")
        for run_id, diagnostics in appendix.items():
            lines.append(f"### {run_id}")
            lines.append("")
            lines.append(
                f"- Top-1 mismatches: `{diagnostics.get('mismatch_count', 0)}`"
            )
            for item in diagnostics.get("worst_mismatches", []):
                lines.append(
                    f"- `{item['doc_id']}` -> `{item.get('nearest_wrong_twin_doc_id')}` "
                    f"[{item['mismatch_class']}] preview: `{item['normalized_input']['preview']}`"
                )
            lines.append("")
    return "\n".join(lines) + "\n"


def main() -> int:
    args = parse_args()
    bundle_dir = args.bundle_dir.resolve()
    config_path = args.gate_config.resolve()
    out_dir = args.out_dir.resolve() if args.out_dir else (bundle_dir / "quality-gate")
    out_dir.mkdir(parents=True, exist_ok=True)

    config = load_json(config_path)
    metadata = load_json(bundle_dir / "metadata.json")
    source_pdf_path = metadata.get("source", {}).get("absolute_path")
    source_pdf = Path(source_pdf_path).resolve() if source_pdf_path else None
    embedding_appendix: dict[str, Any] = {}
    embedding_path = out_dir / "embedding.json"
    if embedding_path.exists():
        embedding_report = load_json(embedding_path)
        embedding_appendix = embedding_report.get("representation_diagnostics_by_run", {})

    scope_entries = flatten_scope_entries(config)
    packet_entries: list[dict[str, Any]] = []
    image_dir = out_dir / "review-images"

    for sample_entry in config["manual_sample"]["entries"]:
        scope_entry = scope_entries[sample_entry["scope_id"]]
        extracted_text, _ = resolve_scope_text(bundle_dir, scope_entry["path"], scope_entry["scope"])
        page_refs = extract_scope_page_refs(bundle_dir, metadata, scope_entry["path"], scope_entry["scope"])
        sidecar_excerpt = {"pages": []}
        if page_refs["spatial_path"]:
            spatial_payload = load_json(bundle_dir / page_refs["spatial_path"])
            sidecar_excerpt = build_sidecar_excerpt(
                spatial_payload,
                page_labels=page_refs["page_labels"],
                pdf_pages=page_refs["pdf_pages"],
            )

        page_image_paths: list[str] = []
        if not args.skip_images and page_refs["pdf_pages"]:
            page_image_paths = render_page_images(
                source_pdf,
                page_refs["pdf_pages"],
                image_dir,
                sample_entry["scope_id"],
            )

        packet_entries.append(
            {
                "scope_id": sample_entry["scope_id"],
                "group": scope_entry["group"],
                "verdict": sample_entry.get("verdict", "pending"),
                "path": scope_entry["path"],
                "scope": scope_entry["scope"],
                "source_page_labels": page_refs["page_labels"],
                "pdf_pages": page_refs["pdf_pages"],
                "extracted_text": normalize_extracted_text(extracted_text),
                "sidecar_excerpt": sidecar_excerpt,
                "page_image_paths": page_image_paths,
                "page_image_path": page_image_paths[0] if page_image_paths else None,
                "checklist_line": sample_entry["checklist_line"],
                "notes": sample_entry.get("notes"),
            }
        )

    packet = {
        "bundle_dir": str(bundle_dir),
        "config": str(config_path),
        "generated_at": dt.datetime.now(dt.UTC).isoformat(),
        "entry_count": len(packet_entries),
        "entries": packet_entries,
        "embedding_mismatch_appendix": embedding_appendix,
    }

    dump_json(out_dir / "review-packet.json", packet)
    (out_dir / "review-packet.md").write_text(
        format_review_packet_markdown(packet),
        encoding="utf-8",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
