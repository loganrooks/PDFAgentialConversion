from __future__ import annotations

from pdfmd.convert.convert_pdf import *  # noqa: F401,F403

def write_markdown_file(base_dir: Path, relative_path: str, content: str) -> None:
    path = base_dir / relative_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def write_json_file(base_dir: Path, relative_path: str, payload: dict[str, Any]) -> None:
    path = base_dir / relative_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def build_index_markdown(metadata: dict[str, Any], file_manifest: list[dict[str, Any]]) -> str:
    citation = metadata["citation"]
    flat_count = sum(1 for item in file_manifest if item.get("flat_output_path"))
    rag_count = sum(1 for item in file_manifest if item.get("rag_output_path"))
    spatial_count = sum(1 for item in file_manifest if item.get("spatial_output_path"))
    lines = [
        f"# {citation.get('title') or metadata['source']['filename']}",
        "",
        "## Citation",
        "",
    ]
    if citation.get("recommended_citation"):
        lines.append(citation["recommended_citation"])
        lines.append("")
    lines.extend(
        [
            "## Bundle Contents",
            "",
            f"- Metadata: [metadata.json](metadata.json)",
            f"- Table of contents: [toc.md](toc.md)",
            f"- File count: {len(file_manifest)}",
            f"- Flat leaf exports: {flat_count}",
            f"- RAG linearized leaf exports: {rag_count}",
            f"- Spatial sidecars: {spatial_count}",
        ]
    )
    return "\n".join(lines).rstrip() + "\n"


def build_toc_markdown(entries: list[TocEntry]) -> str:
    lines = ["# Table of Contents", ""]
    for entry in entries:
        indent = "  " * max(entry.level - 1, 0)
        page_label = entry.page_label or "?"
        lines.append(f"{indent}- [{entry.display_title}]({entry.output_path}) ({page_label})")
    return "\n".join(lines).rstrip() + "\n"


def entries_to_tree(entries: list[TocEntry]) -> list[dict[str, Any]]:
    by_id = get_entry_by_id(entries)

    def walk(entry: TocEntry) -> dict[str, Any]:
        return {
            "id": entry.id,
            "kind": entry.kind,
            "title": entry.title,
            "display_title": entry.display_title,
            "marker": entry.marker,
            "page_label": entry.page_label,
            "numbering": entry.numbering,
            "pdf_page": entry.pdf_page,
            "end_pdf_page": entry.end_pdf_page,
            "output_path": entry.output_path,
            "children": [walk(by_id[child_id]) for child_id in entry.children],
        }

    roots = [entry for entry in entries if not entry.parent_id]
    return [walk(entry) for entry in roots]
