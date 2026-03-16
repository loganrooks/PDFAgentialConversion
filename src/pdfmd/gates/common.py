#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import json
import re
import statistics
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path("/Users/rookslog/Projects/PDFAgentialConversion")
SKILL_DIR = PROJECT_ROOT / "skills" / "pdf-to-structured-markdown"
SCRIPT_DIR = SKILL_DIR / "scripts"
TOKEN_RE = re.compile(r"[A-Za-z0-9]+")
WHITESPACE_RE = re.compile(r"\s+")
RAG_PASSAGE_RE = re.compile(
    r"^## Passage (?P<ordinal>\d+)(?: \((?P<label>[^)]+)\))?\n(?P<body>.*?)(?=^## Passage |\Z)",
    re.MULTILINE | re.DOTALL,
)
RAG_BLOCK_RE = re.compile(
    r"^### (?P<kind>Citation|Commentary|Reference Notes)\n\n(?P<body>.*?)(?=^### |\n## Passage |\Z)",
    re.MULTILINE | re.DOTALL,
)


def load_script_module(name: str, path: Path) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load module {name} from {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


CHECK_REGRESSIONS = load_script_module("quality_gate_check_regressions", SCRIPT_DIR / "check_regressions.py")


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def dump_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def clean_text(text: str) -> str:
    return WHITESPACE_RE.sub(" ", text).strip()


def slugify(text: str) -> str:
    text = re.sub(r"[^A-Za-z0-9]+", "-", text.lower()).strip("-")
    return text or "item"


def token_count(text: str) -> int:
    return len(TOKEN_RE.findall(text))


def percentile(values: list[int], q: float) -> float:
    if not values:
        return 0.0
    if len(values) == 1:
        return float(values[0])
    ordered = sorted(values)
    index = (len(ordered) - 1) * q
    lower = int(index)
    upper = min(lower + 1, len(ordered) - 1)
    weight = index - lower
    return ordered[lower] * (1.0 - weight) + ordered[upper] * weight


def stats_for_counts(values: list[int]) -> dict[str, Any]:
    if not values:
        return {
            "count": 0,
            "min_tokens": 0,
            "max_tokens": 0,
            "mean_tokens": 0.0,
            "median_tokens": 0.0,
            "p90_tokens": 0.0,
        }
    return {
        "count": len(values),
        "min_tokens": min(values),
        "max_tokens": max(values),
        "mean_tokens": round(sum(values) / len(values), 2),
        "median_tokens": round(float(statistics.median(values)), 2),
        "p90_tokens": round(percentile(values, 0.9), 2),
    }


def manifest_item_for_path(metadata: dict[str, Any], relative_path: str) -> dict[str, Any] | None:
    for item in metadata.get("file_manifest", []):
        for key in ("output_path", "flat_output_path", "rag_output_path", "spatial_output_path"):
            if item.get(key) == relative_path:
                return item
    return None


def resolve_scope_text(bundle_dir: Path, relative_path: str, scope: dict[str, Any] | None) -> tuple[str | None, str]:
    text = (bundle_dir / relative_path).read_text(encoding="utf-8")
    return CHECK_REGRESSIONS.resolve_scope_text(text, scope)


def extract_rag_passage_body(text: str, *, label: str | None = None, index: int | None = None) -> str | None:
    return CHECK_REGRESSIONS.extract_rag_passage(text, label=label, index=index)


def extract_rag_passage_fields(body: str) -> dict[str, str]:
    return CHECK_REGRESSIONS.passage_fields_from_body(body)


def extract_scope_page_refs(
    bundle_dir: Path,
    metadata: dict[str, Any],
    relative_path: str,
    scope: dict[str, Any],
) -> dict[str, Any]:
    item = manifest_item_for_path(metadata, relative_path)
    spatial_path: str | None = None
    if relative_path.endswith(".layout.json"):
        spatial_path = relative_path
    elif item:
        spatial_path = item.get("spatial_output_path")

    page_labels: list[str] = []
    pdf_pages: list[int] = []

    if scope.get("kind") == "rag_passage":
        text = (bundle_dir / relative_path).read_text(encoding="utf-8")
        passage_body = extract_rag_passage_body(
            text,
            label=scope.get("label"),
            index=scope.get("index"),
        )
        if passage_body:
            fields = extract_rag_passage_fields(passage_body)
            page_labels = [
                part.strip()
                for part in (fields.get("source_pages") or "").split(",")
                if part.strip()
            ]
    elif scope.get("kind") in {"semantic_page", "spatial_page"}:
        if scope.get("page_label") is not None:
            page_labels = [str(scope["page_label"])]
        if scope.get("pdf_page") is not None:
            pdf_pages = [int(scope["pdf_page"])]

    payload = load_json(bundle_dir / spatial_path) if spatial_path else None
    if payload:
        page_label_map = {
            str(page.get("page_label")): int(page.get("pdf_page"))
            for page in payload.get("pages", [])
            if page.get("page_label") is not None and page.get("pdf_page") is not None
        }
        if page_labels and not pdf_pages:
            pdf_pages = [page_label_map[label] for label in page_labels if label in page_label_map]
        if pdf_pages and not page_labels:
            pdf_page_map = {
                int(page.get("pdf_page")): str(page.get("page_label"))
                for page in payload.get("pages", [])
                if page.get("page_label") is not None and page.get("pdf_page") is not None
            }
            page_labels = [pdf_page_map[page] for page in pdf_pages if page in pdf_page_map]

    return {
        "manifest_item": item,
        "spatial_path": spatial_path,
        "page_labels": page_labels,
        "pdf_pages": pdf_pages,
    }


def select_spatial_pages(
    payload: dict[str, Any],
    *,
    page_labels: list[str] | None = None,
    pdf_pages: list[int] | None = None,
) -> list[dict[str, Any]]:
    labels = set(page_labels or [])
    pages = set(pdf_pages or [])
    selected: list[dict[str, Any]] = []
    for page in payload.get("pages", []):
        page_label = str(page.get("page_label")) if page.get("page_label") is not None else None
        pdf_page = int(page.get("pdf_page")) if page.get("pdf_page") is not None else None
        if labels and page_label in labels:
            selected.append(page)
            continue
        if pages and pdf_page in pages:
            selected.append(page)
    return selected


def summarize_region(region: dict[str, Any], *, max_chars: int = 220) -> dict[str, Any]:
    semantic_text = clean_text(region.get("semantic_text") or "")
    raw_text = clean_text(region.get("raw_text") or "")
    text = semantic_text or raw_text
    if len(text) > max_chars:
        text = text[:max_chars].rsplit(" ", 1)[0].rstrip() + " ..."
    return {
        "role": region.get("role"),
        "bbox": region.get("bbox"),
        "excerpt": text,
    }


def build_sidecar_excerpt(
    payload: dict[str, Any],
    *,
    page_labels: list[str] | None = None,
    pdf_pages: list[int] | None = None,
    max_regions: int = 6,
) -> dict[str, Any]:
    excerpt_pages: list[dict[str, Any]] = []
    for page in select_spatial_pages(payload, page_labels=page_labels, pdf_pages=pdf_pages):
        page_excerpt = {
            "page_label": page.get("page_label"),
            "pdf_page": page.get("pdf_page"),
            "layout": page.get("layout"),
            "content_mode": page.get("content_mode"),
            "slice_min_y": page.get("slice_min_y"),
            "slice_max_y": page.get("slice_max_y"),
            "region_count": len(page.get("regions", [])),
            "regions": [summarize_region(region) for region in page.get("regions", [])[:max_regions]],
        }
        rag_fragments = page.get("rag_fragments") or []
        if rag_fragments:
            page_excerpt["rag_fragments"] = [
                {
                    "label": fragment.get("label"),
                    "bucket": fragment.get("bucket"),
                    "text": clean_text(fragment.get("text") or "")[:180],
                }
                for fragment in rag_fragments[:max_regions]
            ]
        excerpt_pages.append(page_excerpt)
    return {"pages": excerpt_pages}


def scope_matches(target_scope: dict[str, Any], candidate_scope: dict[str, Any] | None) -> bool:
    if not candidate_scope:
        return False
    if str(candidate_scope.get("kind")) != str(target_scope.get("kind")):
        return False
    for key, value in target_scope.items():
        if key == "kind":
            continue
        candidate_value = candidate_scope.get(key)
        if candidate_value is None:
            return False
        if str(candidate_value) != str(value):
            return False
    return True


def flatten_scope_entries(config: dict[str, Any]) -> dict[str, dict[str, Any]]:
    entries: dict[str, dict[str, Any]] = {}
    for group in ("target_scopes", "holdout_scopes", "negative_controls"):
        for item in config.get(group, []):
            entry = {**item, "group": group}
            entries[item["id"]] = entry
    return entries


def classify_probe_issues(
    issues: list[dict[str, Any]],
    config: dict[str, Any],
) -> dict[str, Any]:
    scope_entries = flatten_scope_entries(config)
    grouped_counts: dict[str, Counter[str]] = {
        "target_scopes": Counter(),
        "holdout_scopes": Counter(),
        "negative_controls": Counter(),
        "other": Counter(),
    }
    grouped_issue_count: Counter[str] = Counter()
    matches: list[dict[str, Any]] = []

    for issue in issues:
        matched_entry: dict[str, Any] | None = None
        for entry in scope_entries.values():
            if issue.get("path") != entry.get("path"):
                continue
            if scope_matches(entry["scope"], issue.get("scope_suggestion")):
                matched_entry = entry
                break
        group = matched_entry["group"] if matched_entry else "other"
        grouped_counts[group][issue["code"]] += 1
        grouped_issue_count[group] += 1
        matches.append(
            {
                "code": issue["code"],
                "path": issue.get("path"),
                "group": group,
                "scope_id": matched_entry.get("id") if matched_entry else None,
            }
        )

    return {
        "counts_by_group": {group: dict(counter) for group, counter in grouped_counts.items()},
        "issue_count_by_group": dict(grouped_issue_count),
        "matches": matches,
    }


def extract_atomic_rag_blocks(text: str) -> list[dict[str, Any]]:
    units: list[dict[str, Any]] = []
    for passage_match in RAG_PASSAGE_RE.finditer(text):
        ordinal = passage_match.group("ordinal")
        label = passage_match.group("label")
        passage_body = passage_match.group("body")
        for block_match in RAG_BLOCK_RE.finditer(passage_body):
            body = clean_text(block_match.group("body"))
            if not body:
                continue
            units.append(
                {
                    "ordinal": ordinal,
                    "label": label,
                    "kind": block_match.group("kind"),
                    "text": body,
                    "token_count": token_count(body),
                }
            )
    return units


def window_atomic_units(units: list[dict[str, Any]], limit: int) -> list[int]:
    chunks: list[int] = []
    current = 0
    for unit in units:
        size = unit["token_count"]
        if current and current + size > limit:
            chunks.append(current)
            current = 0
        current += size
    if current:
        chunks.append(current)
    return chunks


def build_chunk_diagnostics(bundle_dir: Path, metadata: dict[str, Any]) -> dict[str, Any]:
    atomic_sizes: list[int] = []
    atomic_units_per_file: dict[str, list[dict[str, Any]]] = {}
    for item in metadata.get("file_manifest", []):
        rag_path = item.get("rag_output_path")
        if not rag_path:
            continue
        text = (bundle_dir / rag_path).read_text(encoding="utf-8")
        units = extract_atomic_rag_blocks(text)
        if not units:
            continue
        atomic_units_per_file[rag_path] = units
        atomic_sizes.extend(unit["token_count"] for unit in units)

    diagnostics: dict[str, Any] = {
        "passage_block_atomic": {
            **stats_for_counts(atomic_sizes),
            "total_chunks": len(atomic_sizes),
            "total_tokens": sum(atomic_sizes),
        }
    }

    for window in (700, 1000, 1400):
        chunk_sizes: list[int] = []
        oversized_units = sum(1 for size in atomic_sizes if size > window)
        for units in atomic_units_per_file.values():
            chunk_sizes.extend(window_atomic_units(units, window))
        diagnostics[f"window_{window}"] = {
            **stats_for_counts(chunk_sizes),
            "total_chunks": len(chunk_sizes),
            "total_tokens": sum(chunk_sizes),
            "oversized_atomic_units": oversized_units,
        }

    return diagnostics


def resolve_reference_path(config_path: Path, path_value: str) -> Path:
    path = Path(path_value)
    if path.is_absolute():
        return path
    return (config_path.parent / path).resolve()


def markdown_code_block(value: str, language: str = "") -> str:
    fence = f"```{language}".rstrip()
    return f"{fence}\n{value.rstrip()}\n```"
