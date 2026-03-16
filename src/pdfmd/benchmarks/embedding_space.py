#!/usr/bin/env python3
from __future__ import annotations

import argparse
import importlib
import json
import math
import os
import re
import shutil
import signal
import subprocess
import time
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path("/Users/rookslog/Projects/PDFAgentialConversion")
DEFAULT_APPLE_HELPER = (
    PROJECT_ROOT
    / "skills"
    / "pdf-to-structured-markdown"
    / "scripts"
    / "apple_nl_embed.swift"
)
WHITESPACE_RE = re.compile(r"\s+")
HEADING_RE = re.compile(r"^\s*#{1,6}\s+")
TOKEN_RE = re.compile(r"[A-Za-z0-9]+")
RAG_PASSAGE_RE = re.compile(
    r"^## Passage (?P<ordinal>\d+)(?: \((?P<label>[^)]+)\))?\n(?P<body>.*?)(?=^## Passage |\Z)",
    re.MULTILINE | re.DOTALL,
)
RAG_BLOCK_RE = re.compile(
    r"^### (?P<kind>Citation|Commentary|Reference Notes)\n\n(?P<body>.*?)(?=^### |\n## Passage |\Z)",
    re.MULTILINE | re.DOTALL,
)
EMBEDDING_METADATA_PREFIXES = (
    "Context:",
    "Source pages:",
    "Representation:",
    "Label:",
    "Source reference:",
    "Source page labels:",
)
EMBEDDING_BODY_CHAR_LIMIT = 1600
EMBEDDING_SUPPLEMENT_CHAR_LIMIT = 180
EMBEDDING_PREVIEW_CHAR_LIMIT = 220
EMBEDDING_DIAGNOSTIC_LIMIT = 10
DEFAULT_SENTENCE_TRANSFORMERS_BATCH_SIZE = 32
COMMON_COLLISION_TOKENS = {
    "chapter",
    "part",
    "section",
    "why",
    "and",
    "the",
    "commentaries",
    "commentary",
    "citation",
    "read",
    "write",
    "justice",
    "third",
    "judgment",
}
STOPWORD_TOKENS = {
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
    "is",
    "of",
    "on",
    "or",
    "the",
    "to",
    "with",
}


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Evaluate embedding-space drift and embedding-only retrieval "
            "for generated PDF markdown bundles."
        )
    )
    parser.add_argument("bundle_dir", type=Path)
    parser.add_argument("benchmark_json", type=Path)
    parser.add_argument(
        "--corpora",
        help="Comma-separated corpus variants to include. Defaults to all available corpora.",
    )
    parser.add_argument(
        "--reference-corpus",
        default="rag_linearized",
        help="Corpus variant treated as the operational reference representation.",
    )
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument("--neighbor-k", type=int, default=5)
    parser.add_argument(
        "--views",
        default="body,contextual",
        help="Comma-separated embedding views to evaluate: body,contextual",
    )
    parser.add_argument(
        "--dense-char-limit",
        type=int,
        default=EMBEDDING_BODY_CHAR_LIMIT,
        help="Maximum normalized body characters included in the contextual view.",
    )
    parser.add_argument(
        "--apple-nl-helper",
        type=Path,
        default=DEFAULT_APPLE_HELPER,
        help="Path to the Swift helper used to generate local embeddings.",
    )
    parser.add_argument(
        "--helper-timeout-seconds",
        type=int,
        default=180,
        help="Hard timeout for the local Swift embedding helper.",
    )
    parser.add_argument(
        "--embedding-backend",
        choices=("apple_nl", "sentence_transformers"),
        default="apple_nl",
        help="Embedding backend used for the evaluator.",
    )
    parser.add_argument(
        "--model-name",
        default="",
        help="Model name for non-Apple embedding backends such as sentence-transformers.",
    )
    parser.add_argument(
        "--device",
        choices=("auto", "cuda", "cpu"),
        default="auto",
        help="Execution device for sentence-transformers backends.",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=DEFAULT_SENTENCE_TRANSFORMERS_BATCH_SIZE,
        help="Batch size for sentence-transformers backends.",
    )
    return parser.parse_args(argv)


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def strip_frontmatter(text: str) -> str:
    if text.startswith("---\n"):
        parts = text.split("\n---\n", 1)
        if len(parts) == 2:
            return parts[1]
    return text


def clean_markdown_for_retrieval(text: str) -> str:
    lines = strip_frontmatter(text).splitlines()
    cleaned: list[str] = []
    for line in lines:
        stripped = line.strip()
        if not stripped:
            cleaned.append("")
            continue
        if stripped.startswith("<!--") and stripped.endswith("-->"):
            continue
        if stripped.startswith("_Source page ") and stripped.endswith("_"):
            continue
        if stripped.startswith("Source pages:"):
            continue
        if stripped.startswith("Context:"):
            continue
        if stripped.startswith("Supplementary side material from source page "):
            continue
        if stripped.startswith("Table-like content from source page "):
            continue
        if stripped.startswith("- "):
            cleaned.append(stripped[2:])
            continue
        cleaned.append(line)
    return "\n".join(cleaned).strip()


def sidecar_semantic_text(payload: dict[str, Any], roles: set[str]) -> str:
    parts: list[str] = []
    for page in payload.get("pages", []):
        for region in page.get("regions", []):
            if region.get("role") not in roles:
                continue
            text = (region.get("semantic_text") or "").strip()
            if text:
                parts.append(text)
    return "\n\n".join(parts).strip()


def sidecar_layout_text(payload: dict[str, Any]) -> str:
    return "\n".join(page.get("layout_text", "") for page in payload.get("pages", [])).strip()


def semantic_excerpt(text: str, limit: int) -> str:
    compact = " ".join(text.split()).strip()
    if len(compact) <= limit:
        return compact
    return compact[:limit].rsplit(" ", 1)[0].strip()


def text_preview(text: str, limit: int = EMBEDDING_PREVIEW_CHAR_LIMIT) -> str:
    compact = normalize_projection_text(text)
    if len(compact) <= limit:
        return compact
    return compact[:limit].rsplit(" ", 1)[0].rstrip() + " ..."


def normalize_projection_text(text: str) -> str:
    return WHITESPACE_RE.sub(" ", text).strip()


def strip_embedding_boilerplate(lines: list[str], *, drop_title_heading: bool) -> list[str]:
    cleaned: list[str] = []
    title_dropped = not drop_title_heading
    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith("<!--") and stripped.endswith("-->"):
            continue
        if stripped.startswith("_Source page ") and stripped.endswith("_"):
            continue
        if any(stripped.startswith(prefix) for prefix in EMBEDDING_METADATA_PREFIXES):
            continue
        if stripped.startswith("Supplementary side material from source page "):
            continue
        if stripped.startswith("Table-like content from source page "):
            continue
        if HEADING_RE.match(stripped):
            if not title_dropped:
                title_dropped = True
                continue
            continue
        if stripped.startswith("- "):
            stripped = stripped[2:].strip()
        cleaned.append(stripped)
    return cleaned


def normalize_semantic_markdown_for_embedding(text: str, *, drop_title_heading: bool = True) -> str:
    lines = strip_embedding_boilerplate(strip_frontmatter(text).splitlines(), drop_title_heading=drop_title_heading)
    return normalize_projection_text("\n".join(lines))


def normalize_rag_markdown_for_embedding(text: str) -> str:
    body = strip_frontmatter(text)
    blocks: list[str] = []
    for passage_match in RAG_PASSAGE_RE.finditer(body):
        passage_body = passage_match.group("body")
        for block_match in RAG_BLOCK_RE.finditer(passage_body):
            block_text = normalize_projection_text(block_match.group("body"))
            if block_text:
                blocks.append(block_text)
    if blocks:
        return "\n\n".join(blocks)
    return normalize_semantic_markdown_for_embedding(text)


def build_view_payload(
    document: Document,
    view: str,
    dense_char_limit: int,
    *,
    normalized: bool,
) -> dict[str, Any]:
    title = normalize_projection_text(document.title)
    context = normalize_projection_text(document.context)
    kind = normalize_projection_text(document.kind)

    if normalized:
        body = normalized_body_projection(document)
        supplement = normalized_supplement_projection(document)
    else:
        body = normalize_projection_text(document.body_text)
        supplement = normalize_projection_text(document.supplement_text)

    body_excerpt = body if view == "body" else semantic_excerpt(body, dense_char_limit)
    body_chars = len(body)
    supplement_chars = len(supplement)
    supplement_ratio = supplement_chars / max(body_chars, 1) if supplement_chars else 0.0

    supplement_preview = ""
    if view == "contextual":
        if normalized:
            if supplement and supplement_ratio <= 0.25:
                supplement_preview = semantic_excerpt(supplement, EMBEDDING_SUPPLEMENT_CHAR_LIMIT)
        elif supplement:
            supplement_preview = semantic_excerpt(supplement, max(350, dense_char_limit // 4))

    if view == "body":
        text = body
    elif view == "contextual":
        parts = [title, context, kind, body_excerpt]
        if supplement_preview:
            parts.append(f"Supplement: {supplement_preview}")
        text = "\n\n".join(part for part in parts if part).strip()
    else:
        raise ValueError(f"Unknown embedding view: {view}")

    return {
        "text": text,
        "preview": text_preview(text),
        "normalized": normalized,
        "title_chars": len(title),
        "context_chars": len(context),
        "kind_chars": len(kind),
        "body_chars": body_chars,
        "body_tokens": len(TOKEN_RE.findall(body)),
        "body_excerpt_chars": len(body_excerpt),
        "supplement_chars": supplement_chars,
        "supplement_tokens": len(TOKEN_RE.findall(supplement)),
        "supplement_preview_chars": len(supplement_preview),
        "supplement_preview_included": bool(supplement_preview),
        "supplement_ratio": round(supplement_ratio, 6),
        "projection_chars": len(text),
        "projection_tokens": len(TOKEN_RE.findall(text)),
    }


def diagnostic_projection_payload(payload: dict[str, Any] | None) -> dict[str, Any] | None:
    if payload is None:
        return None
    return {key: value for key, value in payload.items() if key != "text"}


def normalized_body_projection(document: Document) -> str:
    if document.corpus == "rag_linearized":
        return normalize_rag_markdown_for_embedding(document.body_text)
    if document.corpus.startswith("semantic_"):
        return normalize_semantic_markdown_for_embedding(document.body_text)
    if document.corpus.startswith("spatial_"):
        return normalize_projection_text(document.body_text)
    if document.corpus == "layout_sidecar":
        return normalize_projection_text(document.layout_text)
    return normalize_projection_text(document.body_text)


def normalized_supplement_projection(document: Document) -> str:
    if document.corpus == "spatial_main_plus_supplement":
        return normalize_projection_text(document.supplement_text)
    return ""


def build_legacy_view_text(document: Document, view: str, dense_char_limit: int) -> str:
    return build_view_payload(
        document,
        view,
        dense_char_limit,
        normalized=False,
    )["text"]


def dedupe_preserve_order(items: list[str]) -> tuple[str, ...]:
    seen: set[str] = set()
    ordered: list[str] = []
    for item in items:
        if item in seen:
            continue
        seen.add(item)
        ordered.append(item)
    return tuple(ordered)


@dataclass(frozen=True)
class Document:
    doc_id: str
    corpus: str
    title: str
    context: str
    kind: str
    body_text: str
    supplement_text: str
    layout_text: str


@dataclass(frozen=True)
class Probe:
    case_id: str
    probe_id: str
    query: str
    gold: frozenset[str]
    tags: tuple[str, ...]

    @property
    def key(self) -> str:
        return f"{self.case_id}::{self.probe_id}"


def build_probes(benchmark: dict[str, Any]) -> list[Probe]:
    probes: list[Probe] = []
    for case in benchmark["cases"]:
        gold = frozenset(case["expected_doc_ids"])
        case_tags = list(case.get("tags", []))
        probe_items = case.get("probes")
        if not probe_items:
            probe_items = [{"id": "default", "query": case["query"]}]
        for index, item in enumerate(probe_items, start=1):
            if isinstance(item, str):
                probe_id = f"probe-{index}"
                query = item
                probe_tags: list[str] = []
            else:
                probe_id = item.get("id", f"probe-{index}")
                query = item["query"]
                probe_tags = list(item.get("tags", []))
            probes.append(
                Probe(
                    case_id=case["id"],
                    probe_id=probe_id,
                    query=query,
                    gold=gold,
                    tags=dedupe_preserve_order(case_tags + probe_tags),
                )
            )
    return probes


def build_corpora(bundle_dir: Path, metadata: dict[str, Any]) -> dict[str, list[Document]]:
    manifests = metadata["file_manifest"]
    corpora: dict[str, list[Document]] = defaultdict(list)

    for item in manifests:
        output_path = item.get("output_path")
        if output_path:
            raw_text = (bundle_dir / output_path).read_text(encoding="utf-8")
            corpora["semantic_nested_current"].append(
                Document(
                    doc_id=output_path,
                    corpus="semantic_nested_current",
                    title=str(item.get("title") or ""),
                    context=str(item.get("context_path") or ""),
                    kind=str(item.get("kind") or ""),
                    body_text=strip_frontmatter(raw_text),
                    supplement_text="",
                    layout_text="",
                )
            )
            corpora["semantic_nested_clean"].append(
                Document(
                    doc_id=output_path,
                    corpus="semantic_nested_clean",
                    title=str(item.get("title") or ""),
                    context=str(item.get("context_path") or ""),
                    kind=str(item.get("kind") or ""),
                    body_text=clean_markdown_for_retrieval(raw_text),
                    supplement_text="",
                    layout_text="",
                )
            )

        flat_path = item.get("flat_output_path")
        if flat_path:
            flat_text = (bundle_dir / flat_path).read_text(encoding="utf-8")
            corpora["semantic_flat_current"].append(
                Document(
                    doc_id=output_path,
                    corpus="semantic_flat_current",
                    title=str(item.get("title") or ""),
                    context=str(item.get("context_path") or ""),
                    kind=str(item.get("kind") or ""),
                    body_text=strip_frontmatter(flat_text),
                    supplement_text="",
                    layout_text="",
                )
            )
            corpora["semantic_flat_clean"].append(
                Document(
                    doc_id=output_path,
                    corpus="semantic_flat_clean",
                    title=str(item.get("title") or ""),
                    context=str(item.get("context_path") or ""),
                    kind=str(item.get("kind") or ""),
                    body_text=clean_markdown_for_retrieval(flat_text),
                    supplement_text="",
                    layout_text="",
                )
            )

        rag_path = item.get("rag_output_path")
        if rag_path:
            rag_text = (bundle_dir / rag_path).read_text(encoding="utf-8")
            corpora["rag_linearized"].append(
                Document(
                    doc_id=output_path,
                    corpus="rag_linearized",
                    title=str(item.get("title") or ""),
                    context=str(item.get("context_path") or ""),
                    kind=str(item.get("kind") or ""),
                    body_text=strip_frontmatter(rag_text),
                    supplement_text="",
                    layout_text="",
                )
            )

        spatial_path = item.get("spatial_output_path")
        if spatial_path:
            payload = load_json(bundle_dir / spatial_path)
            layout_text = sidecar_layout_text(payload)
            main_text = sidecar_semantic_text(payload, {"main"})
            supplement_text = sidecar_semantic_text(payload, {"aside", "table"})

            corpora["layout_sidecar"].append(
                Document(
                    doc_id=output_path,
                    corpus="layout_sidecar",
                    title=str(item.get("title") or ""),
                    context=str(item.get("context_path") or ""),
                    kind=str(item.get("kind") or ""),
                    body_text=layout_text,
                    supplement_text="",
                    layout_text=layout_text,
                )
            )
            corpora["spatial_main_only"].append(
                Document(
                    doc_id=output_path,
                    corpus="spatial_main_only",
                    title=str(item.get("title") or ""),
                    context=str(item.get("context_path") or ""),
                    kind=str(item.get("kind") or ""),
                    body_text=main_text,
                    supplement_text="",
                    layout_text=layout_text,
                )
            )
            corpora["spatial_main_plus_supplement"].append(
                Document(
                    doc_id=output_path,
                    corpus="spatial_main_plus_supplement",
                    title=str(item.get("title") or ""),
                    context=str(item.get("context_path") or ""),
                    kind=str(item.get("kind") or ""),
                    body_text=main_text,
                    supplement_text=supplement_text,
                    layout_text=layout_text,
                )
            )

    return dict(corpora)


def build_view_text(document: Document, view: str, dense_char_limit: int) -> str:
    return build_view_payload(
        document,
        view,
        dense_char_limit,
        normalized=True,
    )["text"]


def terminate_process_group(process: subprocess.Popen[str]) -> str:
    try:
        if process.poll() is not None:
            return "already_exited"
        if hasattr(os, "killpg"):
            os.killpg(process.pid, signal.SIGKILL)
            return "killpg_sigkill"
        else:
            process.kill()
            return "process_kill"
    except ProcessLookupError:
        return "process_lookup_error"


def load_embeddings(
    helper: Path,
    items: list[dict[str, str]],
    *,
    timeout_seconds: int,
) -> tuple[dict[str, Any], dict[str, Any]]:
    if not helper.exists():
        raise FileNotFoundError(f"Embedding helper not found: {helper}")
    if shutil.which("swift") is None:
        raise RuntimeError("Swift is unavailable on this machine.")
    started = time.monotonic()
    process = subprocess.Popen(
        ["swift", str(helper)],
        text=True,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        start_new_session=True,
    )
    try:
        stdout, stderr = process.communicate(
            input=json.dumps({"items": items}),
            timeout=timeout_seconds,
        )
    except subprocess.TimeoutExpired as exc:
        cleanup_result = terminate_process_group(process)
        stdout, stderr = process.communicate()
        raise RuntimeError(
            f"Embedding helper timed out after {timeout_seconds}s. cleanup={cleanup_result}"
        ) from exc
    if process.returncode != 0:
        raise RuntimeError(stderr.strip() or "Embedding helper failed.")
    payload = json.loads(stdout)
    runtime = {
        "helper": str(helper),
        "timeout_seconds": timeout_seconds,
        "duration_seconds": round(time.monotonic() - started, 4),
        "item_count": len(items),
    }
    return payload, runtime


def probe_torch_environment(torch_module: Any) -> dict[str, Any]:
    cuda_module = getattr(torch_module, "cuda", None)
    cuda_available = bool(cuda_module and cuda_module.is_available())
    device_count = int(cuda_module.device_count()) if cuda_available and hasattr(cuda_module, "device_count") else 0
    device_names: list[str] = []
    if cuda_available and hasattr(cuda_module, "get_device_name"):
        for index in range(device_count):
            try:
                device_names.append(str(cuda_module.get_device_name(index)))
            except Exception:
                device_names.append(f"cuda:{index}")
    return {
        "torch_version": getattr(torch_module, "__version__", None),
        "cuda_available": cuda_available,
        "cuda_version": getattr(getattr(torch_module, "version", None), "cuda", None),
        "device_count": device_count,
        "device_names": device_names,
    }


def resolve_sentence_transformers_device(
    requested_device: str,
    torch_module: Any,
) -> tuple[str, dict[str, Any]]:
    gpu_probe = probe_torch_environment(torch_module)
    if requested_device == "auto":
        return ("cuda" if gpu_probe["cuda_available"] else "cpu"), gpu_probe
    if requested_device == "cuda" and not gpu_probe["cuda_available"]:
        raise RuntimeError("CUDA was requested for sentence-transformers but is unavailable.")
    return requested_device, gpu_probe


def load_embeddings_sentence_transformers(
    items: list[dict[str, str]],
    *,
    model_name: str,
    requested_device: str,
    batch_size: int,
) -> tuple[dict[str, Any], dict[str, Any]]:
    if not model_name:
        raise ValueError("--model-name is required when --embedding-backend=sentence_transformers")
    try:
        sentence_transformers_module = importlib.import_module("sentence_transformers")
        torch_module = importlib.import_module("torch")
    except ModuleNotFoundError as exc:
        raise RuntimeError(
            "sentence-transformers backend requires sentence_transformers and torch."
        ) from exc

    resolved_device, gpu_probe = resolve_sentence_transformers_device(requested_device, torch_module)
    started = time.monotonic()
    model = sentence_transformers_module.SentenceTransformer(model_name, device=resolved_device)
    texts = [item["text"] for item in items]
    embeddings = model.encode(
        texts,
        batch_size=batch_size,
        show_progress_bar=False,
        convert_to_numpy=True,
        normalize_embeddings=True,
    )
    if hasattr(embeddings, "tolist"):
        embedding_rows = embeddings.tolist()
    else:
        embedding_rows = list(embeddings)
    embedding_map = {
        item["id"]: [float(value) for value in row]
        for item, row in zip(items, embedding_rows, strict=True)
    }
    dimension = len(next(iter(embedding_map.values()))) if embedding_map else 0
    payload = {
        "backend": "sentence_transformers",
        "model_name": model_name,
        "dimension": dimension,
        "device_resolved": resolved_device,
        "gpu_probe": gpu_probe,
        "embeddings": embedding_map,
    }
    runtime = {
        "model_name": model_name,
        "device_requested": requested_device,
        "device_resolved": resolved_device,
        "batch_size": batch_size,
        "duration_seconds": round(time.monotonic() - started, 4),
        "item_count": len(items),
        "gpu_probe": gpu_probe,
        "library_versions": {
            "sentence_transformers": getattr(sentence_transformers_module, "__version__", None),
            "torch": getattr(torch_module, "__version__", None),
        },
    }
    return payload, runtime


def load_embeddings_for_backend(
    args: argparse.Namespace,
    items: list[dict[str, str]],
) -> tuple[dict[str, Any], dict[str, Any]]:
    if args.embedding_backend == "apple_nl":
        payload, runtime = load_embeddings(
            args.apple_nl_helper.resolve(),
            items,
            timeout_seconds=args.helper_timeout_seconds,
        )
        runtime["backend"] = "apple_nl"
        runtime["device_requested"] = None
        runtime["device_resolved"] = "apple_nl"
        runtime["batch_size"] = None
        runtime["gpu_probe"] = None
        return payload, runtime
    if args.embedding_backend == "sentence_transformers":
        return load_embeddings_sentence_transformers(
            items,
            model_name=args.model_name,
            requested_device=args.device,
            batch_size=args.batch_size,
        )
    raise ValueError(f"Unsupported embedding backend: {args.embedding_backend}")


def cosine(left: list[float], right: list[float]) -> float:
    return sum(l * r for l, r in zip(left, right))


def reciprocal_rank(results: list[str], gold: set[str]) -> float:
    for index, doc_id in enumerate(results, start=1):
        if doc_id in gold:
            return 1.0 / index
    return 0.0


def recall_at_k(results: list[str], gold: set[str]) -> float:
    if not gold:
        return 0.0
    found = sum(1 for doc_id in results if doc_id in gold)
    return found / len(gold)


def rank_against_reference(
    query_vector: list[float],
    reference_vectors: dict[str, list[float]],
) -> list[tuple[str, float]]:
    ranked = [
        (doc_id, cosine(query_vector, vector))
        for doc_id, vector in reference_vectors.items()
    ]
    ranked.sort(key=lambda item: item[1], reverse=True)
    return ranked


def neighborhood(
    query_vector: list[float],
    corpus_vectors: dict[str, list[float]],
    *,
    exclude_doc_id: str,
    limit: int,
) -> list[str]:
    ranked = [
        (doc_id, cosine(query_vector, vector))
        for doc_id, vector in corpus_vectors.items()
        if doc_id != exclude_doc_id
    ]
    ranked.sort(key=lambda item: item[1], reverse=True)
    return [doc_id for doc_id, _ in ranked[:limit]]


def mean(values: list[float]) -> float | None:
    if not values:
        return None
    return sum(values) / len(values)


def summarize_tagged_results(items: list[dict[str, Any]]) -> dict[str, Any]:
    tags = sorted({tag for item in items for tag in item["tags"]})
    summary: dict[str, Any] = {}
    for tag in tags:
        tagged = [item for item in items if tag in item["tags"]]
        summary[tag] = {
            "probe_count": len(tagged),
            "mean_reciprocal_rank": round(sum(item["mrr"] for item in tagged) / len(tagged), 4),
            "hit_at_1": round(sum(item["hit_at_1"] for item in tagged) / len(tagged), 4),
            "recall_at_3": round(sum(item["recall_at_3"] for item in tagged) / len(tagged), 4),
            "recall_at_5": round(sum(item["recall_at_5"] for item in tagged) / len(tagged), 4),
        }
    return summary


def context_tokens(document: Document) -> set[str]:
    raw = f"{document.title} {document.context} {document.kind}".lower()
    return {
        token
        for token in TOKEN_RE.findall(raw)
        if len(token) >= 3 and token not in STOPWORD_TOKENS
    }


def classify_mismatch(
    source_doc: Document,
    wrong_doc: Document | None,
    *,
    view: str,
    projection_payload: dict[str, Any],
) -> tuple[str, list[str]]:
    if wrong_doc is None:
        return "true body-content divergence", []
    if (
        view == "contextual"
        and source_doc.corpus.startswith("spatial_")
        and float(projection_payload.get("supplement_ratio", 0.0)) > 0.25
    ):
        return "supplement overload", []
    source_marker = f"{source_doc.doc_id} {source_doc.title}".lower()
    wrong_marker = f"{wrong_doc.doc_id} {wrong_doc.title}".lower()
    if "re-citation" in source_marker or "re-citation" in wrong_marker:
        return "commentary-heavy repeated-citation collision", []
    overlap = sorted(context_tokens(source_doc) & context_tokens(wrong_doc))
    if overlap and (
        view == "contextual" or any(token in COMMON_COLLISION_TOKENS for token in overlap)
    ):
        return "title/context collision", overlap[:6]
    return "true body-content divergence", overlap[:6]


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    bundle_dir = args.bundle_dir.resolve()
    metadata = load_json(bundle_dir / "metadata.json")
    benchmark = load_json(args.benchmark_json.resolve())
    views = [view.strip() for view in args.views.split(",") if view.strip()]
    corpora = build_corpora(bundle_dir, metadata)
    if args.corpora:
        requested = {name.strip() for name in args.corpora.split(",") if name.strip()}
        corpora = {name: documents for name, documents in corpora.items() if name in requested}
    probes = build_probes(benchmark)

    if args.reference_corpus not in corpora:
        raise ValueError(f"Unknown reference corpus: {args.reference_corpus}")

    embedding_items: list[dict[str, str]] = []
    doc_item_ids: dict[tuple[str, str, str], str] = {}
    legacy_doc_item_ids: dict[tuple[str, str, str], str] = {}
    doc_projection_payloads: dict[tuple[str, str, str], dict[str, Any]] = {}
    legacy_projection_payloads: dict[tuple[str, str, str], dict[str, Any]] = {}
    query_item_ids: dict[str, str] = {}
    documents_by_corpus: dict[str, dict[str, Document]] = {
        corpus_name: {document.doc_id: document for document in documents}
        for corpus_name, documents in corpora.items()
    }

    for corpus_name, documents in corpora.items():
        for document in documents:
            for view in views:
                item_id = f"doc::{corpus_name}::{view}::{document.doc_id}"
                doc_item_ids[(corpus_name, view, document.doc_id)] = item_id
                doc_projection_payloads[(corpus_name, view, document.doc_id)] = build_view_payload(
                    document,
                    view,
                    args.dense_char_limit,
                    normalized=True,
                )
                embedding_items.append(
                    {
                        "id": item_id,
                        "text": doc_projection_payloads[(corpus_name, view, document.doc_id)]["text"],
                    }
                )
                if corpus_name != args.reference_corpus:
                    legacy_item_id = f"doc-legacy::{corpus_name}::{view}::{document.doc_id}"
                    legacy_doc_item_ids[(corpus_name, view, document.doc_id)] = legacy_item_id
                    legacy_projection_payloads[(corpus_name, view, document.doc_id)] = build_view_payload(
                        document,
                        view,
                        args.dense_char_limit,
                        normalized=False,
                    )
                    embedding_items.append(
                        {
                            "id": legacy_item_id,
                            "text": legacy_projection_payloads[(corpus_name, view, document.doc_id)]["text"],
                        }
                    )

    for probe in probes:
        item_id = f"query::{probe.key}"
        query_item_ids[probe.key] = item_id
        embedding_items.append({"id": item_id, "text": probe.query})

    embedding_payload, helper_runtime = load_embeddings_for_backend(args, embedding_items)
    embedding_map: dict[str, list[float]] = embedding_payload["embeddings"]

    corpus_vectors: dict[str, dict[str, dict[str, list[float]]]] = defaultdict(lambda: defaultdict(dict))
    for (corpus_name, view, doc_id), item_id in doc_item_ids.items():
        vector = embedding_map.get(item_id)
        if vector is not None:
            corpus_vectors[corpus_name][view][doc_id] = vector
    legacy_corpus_vectors: dict[str, dict[str, dict[str, list[float]]]] = defaultdict(lambda: defaultdict(dict))
    for (corpus_name, view, doc_id), item_id in legacy_doc_item_ids.items():
        vector = embedding_map.get(item_id)
        if vector is not None:
            legacy_corpus_vectors[corpus_name][view][doc_id] = vector

    query_vectors: dict[str, list[float]] = {}
    for probe in probes:
        vector = embedding_map.get(query_item_ids[probe.key])
        if vector is not None:
            query_vectors[probe.key] = vector

    representation_results: list[dict[str, Any]] = []
    representation_summary: dict[str, Any] = {}
    representation_diagnostics: dict[str, Any] = {}
    reference_vectors_by_view = corpus_vectors[args.reference_corpus]
    reference_documents = documents_by_corpus[args.reference_corpus]

    for corpus_name, views_map in corpus_vectors.items():
        for view in views:
            current_vectors = views_map.get(view, {})
            reference_vectors = reference_vectors_by_view.get(view, {})
            shared_doc_ids = sorted(set(current_vectors) & set(reference_vectors))
            if not shared_doc_ids:
                continue

            twin_cosines: list[float] = []
            twin_rrs: list[float] = []
            twin_hit_at_1: list[float] = []
            margins: list[float] = []
            neighbor_overlaps: list[float] = []
            run_diagnostics: list[dict[str, Any]] = []

            for doc_id in shared_doc_ids:
                query_vector = current_vectors[doc_id]
                ranked_reference = rank_against_reference(query_vector, reference_vectors)
                ranked_doc_ids = [ranked_doc_id for ranked_doc_id, _ in ranked_reference]
                twin_cosine = next(score for ranked_doc_id, score in ranked_reference if ranked_doc_id == doc_id)
                twin_rr = reciprocal_rank(ranked_doc_ids, {doc_id})
                current_hit_at_1 = 1.0 if ranked_doc_ids and ranked_doc_ids[0] == doc_id else 0.0
                twin_cosines.append(twin_cosine)
                twin_rrs.append(twin_rr)
                twin_hit_at_1.append(current_hit_at_1)
                best_non_twin = next(
                    (score for ranked_doc_id, score in ranked_reference if ranked_doc_id != doc_id),
                    None,
                )
                if best_non_twin is not None:
                    margins.append(twin_cosine - best_non_twin)

                current_neighbors = neighborhood(
                    query_vector,
                    current_vectors,
                    exclude_doc_id=doc_id,
                    limit=args.neighbor_k,
                )
                reference_neighbors = neighborhood(
                    reference_vectors[doc_id],
                    reference_vectors,
                    exclude_doc_id=doc_id,
                    limit=args.neighbor_k,
                )
                if current_neighbors and reference_neighbors:
                    overlap = len(set(current_neighbors) & set(reference_neighbors)) / min(
                        len(current_neighbors),
                        len(reference_neighbors),
                    )
                    neighbor_overlaps.append(overlap)

                source_document = documents_by_corpus[corpus_name][doc_id]
                wrong_doc_id = next(
                    (ranked_doc_id for ranked_doc_id, _ in ranked_reference if ranked_doc_id != doc_id),
                    None,
                )
                wrong_document = reference_documents.get(wrong_doc_id) if wrong_doc_id else None
                mismatch_class, overlap_tokens = classify_mismatch(
                    source_document,
                    wrong_document,
                    view=view,
                    projection_payload=doc_projection_payloads[(corpus_name, view, doc_id)],
                )
                top_reference_neighbors = [
                    {
                        "doc_id": ranked_doc_id,
                        "score": round(score, 6),
                        "is_twin": ranked_doc_id == doc_id,
                    }
                    for ranked_doc_id, score in ranked_reference[:3]
                ]
                legacy_metrics: dict[str, Any] | None = None
                legacy_payload = legacy_projection_payloads.get((corpus_name, view, doc_id))
                legacy_vector = legacy_corpus_vectors.get(corpus_name, {}).get(view, {}).get(doc_id)
                if legacy_vector is not None:
                    legacy_ranked = rank_against_reference(legacy_vector, reference_vectors)
                    legacy_ranked_doc_ids = [ranked_doc_id for ranked_doc_id, _ in legacy_ranked]
                    legacy_twin_cosine = next(
                        score for ranked_doc_id, score in legacy_ranked if ranked_doc_id == doc_id
                    )
                    legacy_best_wrong = next(
                        (score for ranked_doc_id, score in legacy_ranked if ranked_doc_id != doc_id),
                        None,
                    )
                    legacy_metrics = {
                        "twin_cosine": round(legacy_twin_cosine, 6),
                        "twin_rr": round(reciprocal_rank(legacy_ranked_doc_ids, {doc_id}), 6),
                        "twin_hit_at_1": 1.0
                        if legacy_ranked_doc_ids and legacy_ranked_doc_ids[0] == doc_id
                        else 0.0,
                        "separation_margin": (
                            round(legacy_twin_cosine - legacy_best_wrong, 6)
                            if legacy_best_wrong is not None
                            else None
                        ),
                    }

                run_diagnostics.append(
                    {
                        "doc_id": doc_id,
                        "mismatch_class": mismatch_class,
                        "collision_tokens": overlap_tokens,
                        "current_metrics": {
                            "twin_cosine": round(twin_cosine, 6),
                            "twin_rr": round(twin_rr, 6),
                            "twin_hit_at_1": current_hit_at_1,
                            "separation_margin": round(twin_cosine - best_non_twin, 6)
                            if best_non_twin is not None
                            else None,
                        },
                        "legacy_metrics": legacy_metrics,
                        "metric_delta_vs_legacy": (
                            {
                                "twin_cosine": round(twin_cosine - float(legacy_metrics["twin_cosine"]), 6),
                                "twin_rr": round(twin_rr - float(legacy_metrics["twin_rr"]), 6),
                                "twin_hit_at_1": round(
                                    current_hit_at_1 - float(legacy_metrics["twin_hit_at_1"]),
                                    6,
                                ),
                                "separation_margin": (
                                    round(
                                        (twin_cosine - best_non_twin) - float(legacy_metrics["separation_margin"]),
                                        6,
                                    )
                                    if best_non_twin is not None
                                    and legacy_metrics["separation_margin"] is not None
                                    else None
                                ),
                            }
                            if legacy_metrics is not None
                            else None
                        ),
                        "nearest_wrong_twin_doc_id": wrong_doc_id,
                        "top_reference_neighbors": top_reference_neighbors,
                        "normalized_input": diagnostic_projection_payload(
                            doc_projection_payloads[(corpus_name, view, doc_id)]
                        ),
                        "legacy_input": diagnostic_projection_payload(legacy_payload),
                    }
                )

            run_id = f"{corpus_name}::{view}"
            representation_summary[run_id] = {
                "doc_count": len(shared_doc_ids),
                "reference_corpus": args.reference_corpus,
                "mean_twin_cosine": round(mean(twin_cosines) or 0.0, 4),
                "twin_hit_at_1": round(mean(twin_hit_at_1) or 0.0, 4),
                "twin_mean_reciprocal_rank": round(mean(twin_rrs) or 0.0, 4),
                "mean_separation_margin": round(mean(margins) or 0.0, 4) if margins else None,
                "mean_neighbor_overlap_at_k": (
                    round(mean(neighbor_overlaps) or 0.0, 4) if neighbor_overlaps else None
                ),
            }
            if corpus_name != args.reference_corpus:
                sorted_diagnostics = sorted(
                    run_diagnostics,
                    key=lambda item: (
                        item["current_metrics"]["twin_hit_at_1"],
                        item["current_metrics"]["twin_rr"],
                        item["current_metrics"]["separation_margin"]
                        if item["current_metrics"]["separation_margin"] is not None
                        else math.inf,
                        item["current_metrics"]["twin_cosine"],
                    ),
                )
                mismatch_count = sum(
                    1
                    for item in run_diagnostics
                    if item["current_metrics"]["twin_hit_at_1"] < 1.0
                )
                representation_diagnostics[run_id] = {
                    "doc_count": len(run_diagnostics),
                    "mismatch_count": mismatch_count,
                    "worst_mismatches": sorted_diagnostics[:EMBEDDING_DIAGNOSTIC_LIMIT],
                }

            for doc_id, twin_cosine, twin_rr, hit_at_1 in zip(
                shared_doc_ids,
                twin_cosines,
                twin_rrs,
                twin_hit_at_1,
                strict=True,
            ):
                representation_results.append(
                    {
                        "corpus": corpus_name,
                        "view": view,
                        "doc_id": doc_id,
                        "twin_cosine": round(twin_cosine, 6),
                        "twin_rr": round(twin_rr, 6),
                        "twin_hit_at_1": hit_at_1,
                    }
                )

    retrieval_results: list[dict[str, Any]] = []
    retrieval_summary: dict[str, Any] = {}

    for corpus_name, views_map in corpus_vectors.items():
        for view in views:
            doc_vectors = views_map.get(view, {})
            if not doc_vectors:
                continue
            run_items: list[dict[str, Any]] = []
            for probe in probes:
                query_vector = query_vectors.get(probe.key)
                if query_vector is None:
                    continue
                ranked = [
                    (doc_id, cosine(query_vector, vector))
                    for doc_id, vector in doc_vectors.items()
                ]
                ranked.sort(key=lambda item: item[1], reverse=True)
                ranked_doc_ids = [doc_id for doc_id, _ in ranked]
                top_results = [
                    {"doc_id": doc_id, "score": round(score, 6)}
                    for doc_id, score in ranked[: args.top_k]
                ]
                gold = set(probe.gold)
                item = {
                    "case_id": probe.case_id,
                    "probe_id": probe.probe_id,
                    "query": probe.query,
                    "corpus": corpus_name,
                    "view": view,
                    "tags": list(probe.tags),
                    "gold": sorted(gold),
                    "top_results": top_results,
                    "mrr": round(reciprocal_rank(ranked_doc_ids, gold), 4),
                    "hit_at_1": 1.0 if ranked_doc_ids and ranked_doc_ids[0] in gold else 0.0,
                    "recall_at_3": round(recall_at_k(ranked_doc_ids[:3], gold), 4),
                    "recall_at_5": round(recall_at_k(ranked_doc_ids[:5], gold), 4),
                }
                run_items.append(item)
                retrieval_results.append(item)

            run_id = f"{corpus_name}::{view}"
            retrieval_summary[run_id] = {
                "probe_count": len(run_items),
                "mean_reciprocal_rank": round(sum(item["mrr"] for item in run_items) / len(run_items), 4),
                "hit_at_1": round(sum(item["hit_at_1"] for item in run_items) / len(run_items), 4),
                "recall_at_3": round(sum(item["recall_at_3"] for item in run_items) / len(run_items), 4),
                "recall_at_5": round(sum(item["recall_at_5"] for item in run_items) / len(run_items), 4),
                "tag_slices": summarize_tagged_results(run_items),
            }

    report = {
        "bundle_dir": str(bundle_dir),
        "benchmark": benchmark.get("name"),
        "reference_corpus": args.reference_corpus,
        "views": views,
        "embedding_backend": {
            "helper": (
                str(args.apple_nl_helper.resolve())
                if args.embedding_backend == "apple_nl"
                else None
            ),
            "backend": args.embedding_backend,
            "backend_label": embedding_payload.get("backend"),
            "dimension": embedding_payload.get("dimension"),
            "model_name": embedding_payload.get("model_name") or args.model_name or None,
            "device_requested": args.device if args.embedding_backend != "apple_nl" else None,
            "device_resolved": embedding_payload.get("device_resolved") or helper_runtime.get("device_resolved"),
            "batch_size": args.batch_size if args.embedding_backend != "apple_nl" else None,
            "gpu_probe": embedding_payload.get("gpu_probe") or helper_runtime.get("gpu_probe"),
            "runtime": helper_runtime,
        },
        "representation_summary_by_run": representation_summary,
        "representation_diagnostics_by_run": representation_diagnostics,
        "retrieval_summary_by_run": retrieval_summary,
        "representation_results": representation_results,
        "retrieval_results": retrieval_results,
    }
    print(json.dumps(report, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
