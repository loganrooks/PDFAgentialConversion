#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import math
import re
import shutil
import subprocess
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any


TOKEN_RE = re.compile(r"[a-z0-9]+")
NON_ALNUM_RE = re.compile(r"[^a-z0-9]+")
WHITESPACE_RE = re.compile(r"\s+")
TABLE_HEADING_RE = re.compile(r"\b(TABLE\s+[0-9IVXLC]+\.?\s+[A-Za-z][A-Za-z0-9'’ .-]+)")
STOPWORDS = {
    "a",
    "an",
    "and",
    "are",
    "as",
    "at",
    "be",
    "by",
    "for",
    "from",
    "how",
    "in",
    "is",
    "it",
    "of",
    "on",
    "or",
    "that",
    "the",
    "this",
    "to",
    "what",
    "when",
    "where",
    "who",
    "why",
    "with",
}
DEFAULT_WORD_BM25_K1 = 1.5
DEFAULT_WORD_BM25_B = 0.75
FUSION_K = 60


BASE_PROFILES: list[dict[str, Any]] = [
    {
        "name": "body_bm25",
        "kind": "bm25",
        "fields": {
            "body": 1.0,
            "supplement": 0.2,
        },
    },
    {
        "name": "fielded_bm25",
        "kind": "bm25",
        "fields": {
            "title": 3.0,
            "context": 2.0,
            "path": 2.4,
            "kind": 0.4,
            "body": 1.0,
            "supplement": 0.45,
        },
    },
    {
        "name": "structure_bm25",
        "kind": "bm25",
        "fields": {
            "title": 3.2,
            "context": 2.7,
            "path": 3.1,
            "kind": 0.5,
            "pages": 0.15,
        },
    },
    {
        "name": "chargram_tfidf",
        "kind": "tfidf_char",
        "fields": {
            "title": 2.4,
            "context": 1.8,
            "path": 2.2,
            "body": 1.0,
            "supplement": 0.5,
        },
    },
]
BASE_FUSION_COMPONENTS = [
    "body_bm25",
    "fielded_bm25",
    "structure_bm25",
    "chargram_tfidf",
]


@dataclass(frozen=True)
class Document:
    doc_id: str
    path: str
    fields: dict[str, str]


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


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Evaluate retrieval behavior for generated PDF markdown bundles "
            "across multiple corpora, signal profiles, and query probes."
        )
    )
    parser.add_argument("bundle_dir", type=Path)
    parser.add_argument("benchmark_json", type=Path)
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument(
        "--profiles",
        help=(
            "Comma-separated profile names to run. "
            "Defaults to all locally available profiles."
        ),
    )
    parser.add_argument(
        "--enable-apple-nl",
        action="store_true",
        help="Enable the Apple NaturalLanguage dense similarity profile.",
    )
    parser.add_argument(
        "--apple-nl-helper",
        type=Path,
        default=Path(__file__).with_name("apple_nl_similarity.swift"),
        help="Path to the Swift helper used for Apple NaturalLanguage similarities.",
    )
    parser.add_argument(
        "--dense-char-limit",
        type=int,
        default=2200,
        help="Maximum characters from each document to send to the dense encoder.",
    )
    return parser.parse_args()


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def stem_token(token: str) -> str:
    if len(token) > 5 and token.endswith("ies"):
        return token[:-3] + "y"
    for suffix in ("ingly", "edly", "ing", "edly", "edly", "ed", "es", "s"):
        if len(token) > len(suffix) + 2 and token.endswith(suffix):
            return token[: -len(suffix)]
    return token


def tokenize(text: str) -> list[str]:
    tokens = TOKEN_RE.findall(text.lower())
    normalized = [stem_token(token) for token in tokens]
    return [token for token in normalized if token not in STOPWORDS and len(token) > 1]


def char_ngrams(text: str) -> list[str]:
    cleaned = NON_ALNUM_RE.sub(" ", text.lower())
    cleaned = WHITESPACE_RE.sub(" ", cleaned).strip()
    if not cleaned:
        return []
    padded = f" {cleaned} "
    grams: list[str] = []
    for size in (3, 4, 5):
        for index in range(len(padded) - size + 1):
            gram = padded[index : index + size]
            if gram.strip():
                grams.append(gram)
    return grams


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
            text = region.get("semantic_text", "").strip()
            if text:
                parts.append(text)
    return "\n\n".join(parts).strip()


def sidecar_layout_text(payload: dict[str, Any]) -> str:
    return "\n".join(page.get("layout_text", "") for page in payload.get("pages", [])).strip()


def sidecar_table_heading(payload: dict[str, Any]) -> str:
    for page in payload.get("pages", []):
        for region in page.get("regions", []):
            text = str(region.get("semantic_text") or region.get("raw_text") or "").strip()
            if not text:
                continue
            match = TABLE_HEADING_RE.search(text.replace("\n", " "))
            if match:
                return WHITESPACE_RE.sub(" ", match.group(1)).strip().rstrip(".")
    return ""


def merge_retrieval_context(context: str, table_heading: str) -> str:
    base_context = str(context or "").strip()
    heading = str(table_heading or "").strip()
    if not heading:
        return base_context
    if heading.lower() in base_context.lower():
        return base_context
    if not base_context:
        return heading
    return f"{base_context} > {heading}"


def semantic_excerpt(text: str, limit: int) -> str:
    compact = WHITESPACE_RE.sub(" ", text).strip()
    if len(compact) <= limit:
        return compact
    return compact[:limit].rsplit(" ", 1)[0].strip()


def format_page_span(item: dict[str, Any]) -> str:
    start = item.get("book_page_start")
    end = item.get("book_page_end")
    if start and end:
        return f"pages {start} to {end}"
    if start:
        return f"page {start}"
    return ""


def build_document(
    item: dict[str, Any],
    *,
    path_label: str,
    body_text: str,
    dense_char_limit: int,
    supplement_text: str = "",
    layout_text: str = "",
) -> Document:
    title = str(item.get("title") or "")
    context = str(item.get("context_path") or "")
    kind = str(item.get("kind") or "")
    pages = format_page_span(item)
    dense_parts = [
        title,
        context,
        semantic_excerpt(body_text, dense_char_limit),
        semantic_excerpt(supplement_text, max(350, dense_char_limit // 4)),
    ]
    dense_text = "\n\n".join(part for part in dense_parts if part).strip()
    return Document(
        doc_id=item["output_path"],
        path=path_label,
        fields={
            "title": title,
            "context": context,
            "path": path_label,
            "kind": kind,
            "pages": pages,
            "body": str(body_text or ""),
            "supplement": str(supplement_text or ""),
            "layout": str(layout_text or ""),
            "dense_text": dense_text,
        },
    )


def build_corpora(
    bundle_dir: Path,
    metadata: dict[str, Any],
    dense_char_limit: int,
) -> dict[str, list[Document]]:
    manifests = metadata["file_manifest"]
    corpora: dict[str, list[Document]] = defaultdict(list)

    for item in manifests:
        output_path = item.get("output_path")
        if output_path:
            raw_text = (bundle_dir / output_path).read_text(encoding="utf-8")
            nested_path_label = Path(output_path).with_suffix("").as_posix().replace("/", " ")
            corpora["semantic_nested_current"].append(
                build_document(
                    item,
                    path_label=nested_path_label,
                    body_text=strip_frontmatter(raw_text),
                    dense_char_limit=dense_char_limit,
                )
            )
            corpora["semantic_nested_clean"].append(
                build_document(
                    item,
                    path_label=nested_path_label,
                    body_text=clean_markdown_for_retrieval(raw_text),
                    dense_char_limit=dense_char_limit,
                )
            )

        flat_path = item.get("flat_output_path")
        if flat_path:
            flat_text = (bundle_dir / flat_path).read_text(encoding="utf-8")
            flat_path_label = Path(flat_path).stem.replace("__", " ")
            corpora["semantic_flat_current"].append(
                build_document(
                    item,
                    path_label=flat_path_label,
                    body_text=strip_frontmatter(flat_text),
                    dense_char_limit=dense_char_limit,
                )
            )
            corpora["semantic_flat_clean"].append(
                build_document(
                    item,
                    path_label=flat_path_label,
                    body_text=clean_markdown_for_retrieval(flat_text),
                    dense_char_limit=dense_char_limit,
                )
            )

        rag_path = item.get("rag_output_path")
        if rag_path:
            rag_text = (bundle_dir / rag_path).read_text(encoding="utf-8")
            rag_path_label = Path(rag_path).stem.replace("__", " ")
            corpora["rag_linearized"].append(
                build_document(
                    item,
                    path_label=rag_path_label,
                    body_text=strip_frontmatter(rag_text),
                    dense_char_limit=dense_char_limit,
                )
            )

        spatial_path = item.get("spatial_output_path")
        if spatial_path:
            payload = load_json(bundle_dir / spatial_path)
            layout_text = sidecar_layout_text(payload)
            main_text = sidecar_semantic_text(payload, {"main"})
            supplement_text = sidecar_semantic_text(payload, {"aside", "table"})
            table_heading = sidecar_table_heading(payload)
            spatial_item = dict(item)
            spatial_item["context_path"] = merge_retrieval_context(
                item.get("context_path", ""),
                table_heading,
            )

            corpora["layout_sidecar"].append(
                build_document(
                    spatial_item,
                    path_label=Path(spatial_path).stem.replace(".", " "),
                    body_text=layout_text,
                    dense_char_limit=dense_char_limit,
                    layout_text=layout_text,
                )
            )
            corpora["spatial_main_only"].append(
                build_document(
                    spatial_item,
                    path_label=Path(output_path).with_suffix("").as_posix().replace("/", " "),
                    body_text=main_text,
                    dense_char_limit=dense_char_limit,
                    layout_text=layout_text,
                )
            )
            corpora["spatial_main_plus_supplement"].append(
                build_document(
                    spatial_item,
                    path_label=Path(output_path).with_suffix("").as_posix().replace("/", " "),
                    body_text=main_text,
                    dense_char_limit=dense_char_limit,
                    supplement_text=supplement_text,
                    layout_text=layout_text,
                )
            )

    return dict(corpora)


def dedupe_preserve_order(items: list[str]) -> tuple[str, ...]:
    seen: set[str] = set()
    ordered: list[str] = []
    for item in items:
        if item in seen:
            continue
        seen.add(item)
        ordered.append(item)
    return tuple(ordered)


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


class BM25FieldIndex:
    def __init__(self, documents: list[Document], field_weights: dict[str, float]) -> None:
        self.documents = documents
        self.field_weights = field_weights
        self.total_docs = max(len(documents), 1)
        self.doc_terms: dict[str, list[Counter[str]]] = {}
        self.doc_freq: dict[str, Counter[str]] = {}
        self.doc_lengths: dict[str, list[int]] = {}
        self.avg_lengths: dict[str, float] = {}

        for field in field_weights:
            counters: list[Counter[str]] = []
            doc_freq: Counter[str] = Counter()
            lengths: list[int] = []
            for document in documents:
                counts = Counter(tokenize(document.fields.get(field, "")))
                counters.append(counts)
                doc_freq.update(counts.keys())
                lengths.append(sum(counts.values()))
            self.doc_terms[field] = counters
            self.doc_freq[field] = doc_freq
            self.doc_lengths[field] = lengths
            self.avg_lengths[field] = (sum(lengths) / len(lengths)) if lengths else 0.0

    def rank(self, query: str) -> list[dict[str, Any]]:
        query_counts = Counter(tokenize(query))
        results: list[dict[str, Any]] = []
        for index, document in enumerate(self.documents):
            total_score = 0.0
            components: dict[str, float] = {}
            for field, weight in self.field_weights.items():
                raw = self._field_score(field, index, query_counts)
                weighted = weight * raw
                if weighted:
                    components[field] = round(weighted, 6)
                total_score += weighted
            results.append(
                {
                    "doc_id": document.doc_id,
                    "path": document.path,
                    "score": round(total_score, 6),
                    "components": components,
                }
            )
        results.sort(key=lambda item: item["score"], reverse=True)
        return results

    def _field_score(self, field: str, doc_index: int, query_counts: Counter[str]) -> float:
        doc_terms = self.doc_terms[field][doc_index]
        if not doc_terms or not query_counts:
            return 0.0
        doc_length = self.doc_lengths[field][doc_index]
        avg_length = self.avg_lengths[field] or 1.0
        score = 0.0
        for term, qtf in query_counts.items():
            tf = doc_terms.get(term, 0)
            if tf == 0:
                continue
            df = self.doc_freq[field].get(term, 0)
            idf = math.log(1.0 + ((self.total_docs - df + 0.5) / (df + 0.5)))
            denom = tf + DEFAULT_WORD_BM25_K1 * (
                1.0 - DEFAULT_WORD_BM25_B + DEFAULT_WORD_BM25_B * (doc_length / avg_length)
            )
            score += qtf * idf * ((tf * (DEFAULT_WORD_BM25_K1 + 1.0)) / denom)
        return score


class TfidfCharFieldIndex:
    def __init__(self, documents: list[Document], field_weights: dict[str, float]) -> None:
        self.documents = documents
        self.field_weights = field_weights
        self.total_docs = max(len(documents), 1)
        self.doc_vectors: dict[str, list[dict[str, float]]] = {}
        self.doc_norms: dict[str, list[float]] = {}
        self.idf: dict[str, dict[str, float]] = {}

        for field in field_weights:
            counters: list[Counter[str]] = []
            doc_freq: Counter[str] = Counter()
            for document in documents:
                counts = Counter(char_ngrams(document.fields.get(field, "")))
                counters.append(counts)
                doc_freq.update(counts.keys())
            idf = {
                term: math.log((1 + self.total_docs) / (1 + freq)) + 1.0
                for term, freq in doc_freq.items()
            }
            vectors: list[dict[str, float]] = []
            norms: list[float] = []
            for counts in counters:
                total_terms = sum(counts.values()) or 1
                vector = {
                    term: (count / total_terms) * idf[term]
                    for term, count in counts.items()
                }
                vectors.append(vector)
                norms.append(math.sqrt(sum(value * value for value in vector.values())))
            self.doc_vectors[field] = vectors
            self.doc_norms[field] = norms
            self.idf[field] = idf

    def rank(self, query: str) -> list[dict[str, Any]]:
        query_vectors: dict[str, dict[str, float]] = {}
        query_norms: dict[str, float] = {}
        for field in self.field_weights:
            counts = Counter(char_ngrams(query))
            total_terms = sum(counts.values()) or 1
            vector = {
                term: (count / total_terms) * self.idf[field].get(term, 0.0)
                for term, count in counts.items()
                if self.idf[field].get(term, 0.0) > 0.0
            }
            query_vectors[field] = vector
            query_norms[field] = math.sqrt(sum(value * value for value in vector.values()))

        results: list[dict[str, Any]] = []
        for index, document in enumerate(self.documents):
            total_score = 0.0
            components: dict[str, float] = {}
            for field, weight in self.field_weights.items():
                raw = cosine_sparse(
                    query_vectors[field],
                    self.doc_vectors[field][index],
                    query_norms[field],
                    self.doc_norms[field][index],
                )
                weighted = weight * raw
                if weighted:
                    components[field] = round(weighted, 6)
                total_score += weighted
            results.append(
                {
                    "doc_id": document.doc_id,
                    "path": document.path,
                    "score": round(total_score, 6),
                    "components": components,
                }
            )
        results.sort(key=lambda item: item["score"], reverse=True)
        return results


def cosine_sparse(
    left: dict[str, float],
    right: dict[str, float],
    left_norm: float | None = None,
    right_norm: float | None = None,
) -> float:
    if not left or not right:
        return 0.0
    numerator = sum(weight * right.get(term, 0.0) for term, weight in left.items())
    if numerator == 0.0:
        return 0.0
    computed_left = left_norm if left_norm is not None else math.sqrt(sum(v * v for v in left.values()))
    computed_right = (
        right_norm if right_norm is not None else math.sqrt(sum(v * v for v in right.values()))
    )
    if computed_left == 0.0 or computed_right == 0.0:
        return 0.0
    return numerator / (computed_left * computed_right)


def apple_nl_available(helper: Path, enabled: bool) -> bool:
    if not enabled:
        return False
    return helper.exists() and shutil.which("swift") is not None


def run_apple_nl_similarity(
    helper: Path,
    documents: list[Document],
    probes: list[Probe],
) -> tuple[dict[str, dict[str, float]], dict[str, Any]]:
    request = {
        "documents": [
            {
                "id": document.doc_id,
                "text": document.fields.get("dense_text", ""),
            }
            for document in documents
        ],
        "queries": [{"id": probe.key, "text": probe.query} for probe in probes],
    }
    completed = subprocess.run(
        ["swift", str(helper)],
        input=json.dumps(request),
        text=True,
        capture_output=True,
        check=True,
    )
    payload = json.loads(completed.stdout)
    return payload.get("similarities", {}), payload


def rank_dense_similarity(
    documents: list[Document],
    similarity_map: dict[str, float],
) -> list[dict[str, Any]]:
    results = []
    for document in documents:
        score = float(similarity_map.get(document.doc_id, 0.0))
        results.append(
            {
                "doc_id": document.doc_id,
                "path": document.path,
                "score": round(score, 6),
                "components": {"dense_text": round(score, 6)} if score else {},
            }
        )
    results.sort(key=lambda item: item["score"], reverse=True)
    return results


def reciprocal_rank_fuse(
    documents: list[Document],
    component_rankings: dict[str, list[dict[str, Any]]],
) -> list[dict[str, Any]]:
    per_profile_ranks: dict[str, dict[str, int]] = {}
    for profile_name, ranking in component_rankings.items():
        per_profile_ranks[profile_name] = {
            item["doc_id"]: index
            for index, item in enumerate(ranking, start=1)
        }

    fused_scores: Counter[str] = Counter()
    for profile_name, rank_map in per_profile_ranks.items():
        for doc_id, rank in rank_map.items():
            fused_scores[doc_id] += 1.0 / (FUSION_K + rank)

    results: list[dict[str, Any]] = []
    for document in documents:
        components: dict[str, float] = {}
        for profile_name, rank_map in per_profile_ranks.items():
            rank = rank_map.get(document.doc_id)
            if rank is not None:
                components[profile_name] = round(1.0 / (FUSION_K + rank), 6)
        results.append(
            {
                "doc_id": document.doc_id,
                "path": document.path,
                "score": round(fused_scores.get(document.doc_id, 0.0), 6),
                "components": components,
            }
        )
    results.sort(key=lambda item: item["score"], reverse=True)
    return results


def reciprocal_rank(results: list[dict[str, Any]], gold: set[str]) -> float:
    for index, result in enumerate(results, start=1):
        if result["doc_id"] in gold:
            return 1.0 / index
    return 0.0


def recall_at_k(results: list[dict[str, Any]], gold: set[str]) -> float:
    if not gold:
        return 0.0
    found = sum(1 for result in results if result["doc_id"] in gold)
    return found / len(gold)


def best_gold_rank(results: list[dict[str, Any]], gold: set[str]) -> int | None:
    for index, result in enumerate(results, start=1):
        if result["doc_id"] in gold:
            return index
    return None


def best_gold_result(results: list[dict[str, Any]], gold: set[str]) -> dict[str, Any] | None:
    for result in results:
        if result["doc_id"] in gold:
            return result
    return None


def score_margin(results: list[dict[str, Any]], gold: set[str]) -> float | None:
    best_gold = next((item["score"] for item in results if item["doc_id"] in gold), None)
    best_non_gold = next((item["score"] for item in results if item["doc_id"] not in gold), None)
    if best_gold is None or best_non_gold is None:
        return None
    return round(best_gold - best_non_gold, 6)


def explained_share(result: dict[str, Any]) -> float:
    components = result.get("components", {})
    if not components:
        return 0.0
    values = [value for value in components.values() if value > 0]
    if not values:
        return 0.0
    return max(values) / sum(values)


def classify_case_miss(result: dict[str, Any]) -> str:
    if result.get("hit_at_1", 0.0) < 1.0 and result.get("recall_at_3", 0.0) < 1.0:
        return "top1_and_recall_miss"
    if result.get("hit_at_1", 0.0) < 1.0:
        return "top1_miss"
    if result.get("mrr", 0.0) < 1.0:
        return "rank_drop"
    return "pass"


def build_run_case_diagnostics(all_results: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    by_run: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for result in all_results:
        run_id = f"{result['corpus']}::{result['profile']}"
        by_run[run_id].append(result)

    diagnostics: dict[str, dict[str, Any]] = {}
    for run_id, items in by_run.items():
        miss_cases: list[dict[str, Any]] = []
        for item in items:
            miss_class = classify_case_miss(item)
            if miss_class == "pass":
                continue
            miss_cases.append(
                {
                    "case_key": f"{item['case_id']}::{item['probe_id']}",
                    "case_id": item["case_id"],
                    "probe_id": item["probe_id"],
                    "query": item["query"],
                    "tags": list(item.get("tags", [])),
                    "gold": list(item.get("gold", [])),
                    "best_gold_rank": item.get("best_gold_rank"),
                    "best_gold_doc_id": item.get("best_gold_doc_id"),
                    "top_result_doc_id": item.get("top_result_doc_id"),
                    "top_result_is_gold": item.get("top_result_is_gold"),
                    "mrr": item.get("mrr"),
                    "hit_at_1": item.get("hit_at_1"),
                    "recall_at_3": item.get("recall_at_3"),
                    "recall_at_5": item.get("recall_at_5"),
                    "score_margin": item.get("score_margin"),
                    "miss_class": miss_class,
                    "top_results": item.get("top_results", []),
                }
            )
        miss_cases.sort(
            key=lambda item: (
                item["mrr"],
                item["best_gold_rank"] if item["best_gold_rank"] is not None else 10**9,
                item["case_id"],
                item["probe_id"],
            )
        )
        diagnostics[run_id] = {
            "miss_count": len(miss_cases),
            "top1_miss_count": sum(1 for item in miss_cases if item["hit_at_1"] < 1.0),
            "recall_at_3_miss_count": sum(1 for item in miss_cases if item["recall_at_3"] < 1.0),
            "cases": miss_cases,
        }
    return diagnostics


def summarize_items(items: list[dict[str, Any]]) -> dict[str, Any]:
    if not items:
        return {}
    score_margins = [item["score_margin"] for item in items if item["score_margin"] is not None]
    adversarial = [item for item in items if "adversarial" in item["tags"]]
    explained = [item["top_explained_share"] for item in items if item["top_explained_share"] is not None]
    summary = {
        "probe_count": len(items),
        "mean_reciprocal_rank": round(sum(item["mrr"] for item in items) / len(items), 4),
        "hit_at_1": round(sum(item["hit_at_1"] for item in items) / len(items), 4),
        "recall_at_3": round(sum(item["recall_at_3"] for item in items) / len(items), 4),
        "recall_at_5": round(sum(item["recall_at_5"] for item in items) / len(items), 4),
        "mean_score_margin": round(sum(score_margins) / len(score_margins), 4) if score_margins else None,
        "mean_top_explained_share": round(sum(explained) / len(explained), 4) if explained else None,
        "tag_slices": {},
        "lens_proxies": {
            "process_reliability": round(sum(item["mrr"] for item in items) / len(items), 4),
            "progressiveness": round(sum(item["recall_at_5"] for item in items) / len(items), 4),
            "pragmatist_inquiry": round(sum(item["hit_at_1"] for item in items) / len(items), 4),
            "social_epistemology": (
                round(sum(item["mrr"] for item in adversarial) / len(adversarial), 4)
                if adversarial
                else None
            ),
            "information_content": (
                round(sum(score_margins) / len(score_margins), 4) if score_margins else None
            ),
            "empirical_adequacy": round(sum(item["recall_at_3"] for item in items) / len(items), 4),
        },
    }

    tags = sorted({tag for item in items for tag in item["tags"]})
    for tag in tags:
        tagged_items = [item for item in items if tag in item["tags"]]
        summary["tag_slices"][tag] = {
            "probe_count": len(tagged_items),
            "mean_reciprocal_rank": round(
                sum(item["mrr"] for item in tagged_items) / len(tagged_items), 4
            ),
            "hit_at_1": round(sum(item["hit_at_1"] for item in tagged_items) / len(tagged_items), 4),
            "recall_at_3": round(
                sum(item["recall_at_3"] for item in tagged_items) / len(tagged_items), 4
            ),
            "recall_at_5": round(
                sum(item["recall_at_5"] for item in tagged_items) / len(tagged_items), 4
            ),
        }
    return summary


def summarize_results(all_results: list[dict[str, Any]]) -> tuple[dict[str, Any], dict[str, Any]]:
    by_run: dict[str, list[dict[str, Any]]] = defaultdict(list)
    by_corpus: dict[str, list[dict[str, Any]]] = defaultdict(list)
    by_profile: dict[str, list[dict[str, Any]]] = defaultdict(list)

    for result in all_results:
        run_id = f"{result['corpus']}::{result['profile']}"
        by_run[run_id].append(result)
        by_corpus[result["corpus"]].append(result)
        by_profile[result["profile"]].append(result)

    run_summary = {run_id: summarize_items(items) for run_id, items in by_run.items()}
    aggregate_summary = {
        "by_corpus": {name: summarize_items(items) for name, items in by_corpus.items()},
        "by_profile": {name: summarize_items(items) for name, items in by_profile.items()},
    }
    return run_summary, aggregate_summary


def filter_profiles(profile_names: list[str] | None, apple_available: bool) -> list[dict[str, Any]]:
    allowed = None
    if profile_names:
        allowed = {name.strip() for name in profile_names if name.strip()}

    profiles = list(BASE_PROFILES)
    if apple_available:
        profiles.append(
            {
                "name": "apple_nl_dense",
                "kind": "apple_nl_dense",
                "fields": {"dense_text": 1.0},
            }
        )
    available_names = {profile["name"] for profile in profiles}
    fusion_names = {"fused_rrf"}
    if apple_available:
        fusion_names.add("fused_rrf_with_dense")

    if allowed is not None:
        unknown = sorted(name for name in allowed if name not in available_names and name not in fusion_names)
        if unknown:
            raise ValueError(f"Unknown profile name(s): {', '.join(unknown)}")
        profiles = [profile for profile in profiles if profile["name"] in allowed]

    if allowed is None or "fused_rrf" in allowed:
        profiles.append(
            {
                "name": "fused_rrf",
                "kind": "fusion",
                "components": list(BASE_FUSION_COMPONENTS),
                "fields": {},
            }
        )
    if apple_available and (allowed is None or "fused_rrf_with_dense" in allowed):
        profiles.append(
            {
                "name": "fused_rrf_with_dense",
                "kind": "fusion",
                "components": list(BASE_FUSION_COMPONENTS) + ["apple_nl_dense"],
                "fields": {},
            }
        )
    return profiles


def main() -> int:
    args = parse_args()
    bundle_dir = args.bundle_dir.resolve()
    metadata = load_json(bundle_dir / "metadata.json")
    benchmark = load_json(args.benchmark_json.resolve())
    probes = build_probes(benchmark)
    corpora = build_corpora(bundle_dir, metadata, args.dense_char_limit)

    apple_available = apple_nl_available(args.apple_nl_helper.resolve(), args.enable_apple_nl)
    profiles = filter_profiles(
        args.profiles.split(",") if args.profiles else None,
        apple_available=apple_available,
    )
    profile_names = [profile["name"] for profile in profiles]

    all_results: list[dict[str, Any]] = []
    apple_backend: dict[str, Any] | None = None

    for corpus_name, documents in corpora.items():
        profile_rankings: dict[str, dict[str, list[dict[str, Any]]]] = defaultdict(dict)
        apple_similarities: dict[str, dict[str, float]] = {}

        if any(profile["kind"] == "apple_nl_dense" for profile in profiles):
            apple_similarities, apple_backend = run_apple_nl_similarity(
                args.apple_nl_helper.resolve(),
                documents,
                probes,
            )

        prepared_profiles: dict[str, Any] = {}
        for profile in profiles:
            if profile["kind"] == "bm25":
                prepared_profiles[profile["name"]] = BM25FieldIndex(documents, profile["fields"])
            elif profile["kind"] == "tfidf_char":
                prepared_profiles[profile["name"]] = TfidfCharFieldIndex(documents, profile["fields"])

        for probe in probes:
            for profile in profiles:
                profile_name = profile["name"]
                profile_kind = profile["kind"]
                if profile_kind == "fusion":
                    component_rankings = {
                        name: rankings[probe.key]
                        for name, rankings in profile_rankings.items()
                        if name in profile.get("components", []) and probe.key in rankings
                    }
                    ranking = reciprocal_rank_fuse(documents, component_rankings) if component_rankings else []
                elif profile_kind == "apple_nl_dense":
                    ranking = rank_dense_similarity(
                        documents,
                        apple_similarities.get(probe.key, {}),
                    )
                else:
                    ranking = prepared_profiles[profile_name].rank(probe.query)

                profile_rankings[profile_name][probe.key] = ranking
                top_results = ranking[: args.top_k]
                gold = set(probe.gold)
                best_gold = best_gold_result(ranking, gold)
                top_result = top_results[0] if top_results else None
                top_explained = explained_share(top_results[0]) if top_results else None
                all_results.append(
                    {
                        "case_id": probe.case_id,
                        "probe_id": probe.probe_id,
                        "query": probe.query,
                        "corpus": corpus_name,
                        "profile": profile_name,
                        "tags": list(probe.tags),
                        "gold": sorted(gold),
                        "top_results": top_results,
                        "best_gold_rank": best_gold_rank(ranking, gold),
                        "best_gold_doc_id": best_gold["doc_id"] if best_gold else None,
                        "best_gold_score": best_gold["score"] if best_gold else None,
                        "top_result_doc_id": top_result["doc_id"] if top_result else None,
                        "top_result_is_gold": bool(top_result and top_result["doc_id"] in gold),
                        "mrr": round(reciprocal_rank(ranking, gold), 4),
                        "hit_at_1": 1.0 if top_results and top_results[0]["doc_id"] in gold else 0.0,
                        "recall_at_3": round(recall_at_k(ranking[:3], gold), 4),
                        "recall_at_5": round(recall_at_k(ranking[:5], gold), 4),
                        "score_margin": score_margin(ranking, gold),
                        "top_explained_share": round(top_explained, 4) if top_explained is not None else None,
                    }
                )

    summary_by_run, aggregate_summary = summarize_results(all_results)
    run_case_diagnostics = build_run_case_diagnostics(all_results)
    report = {
        "bundle_dir": str(bundle_dir),
        "benchmark": benchmark.get("name"),
        "case_count": len(benchmark["cases"]),
        "probe_count": len(probes),
        "available_profiles": profile_names,
        "apple_nl": {
            "enabled": any(profile == "apple_nl_dense" for profile in profile_names),
            "helper": str(args.apple_nl_helper.resolve()),
            "backend": apple_backend,
        },
        "summary_by_run": summary_by_run,
        "summary": aggregate_summary,
        "run_case_diagnostics": run_case_diagnostics,
        "results": all_results,
    }
    print(json.dumps(report, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
