from __future__ import annotations

from pathlib import Path
from typing import Any

from pdfmd.common.io import dump_json


MANIFEST_SCHEMA_VERSION = "1.0"
DEFAULT_ARTIFACT_STATUS = "generated"
DEFAULT_FRESHNESS = "fresh"
ALLOWED_ARTIFACT_STATUSES = {"generated", "failed", "skipped", "dry_run"}
ALLOWED_FRESHNESS_VALUES = {"fresh", "stale", "unknown"}

MANIFEST_REQUIRED_KEYS: dict[str, tuple[str, ...]] = {
    "quality_gate": ("generated_at", "variant_id", "input_pdf", "converter_version", "gate_config"),
    "challenge_corpus": ("generated_at", "variant_id", "baseline_dir", "entry_count"),
    "backend_comparison": ("generated_at", "variant_id", "bundle", "benchmark", "backend"),
    "bundle_generation": ("generated_at", "book_id", "source", "converter_version", "output_dir"),
}


def normalize_manifest_payload(kind: str, payload: dict[str, Any]) -> dict[str, Any]:
    if kind not in MANIFEST_REQUIRED_KEYS:
        raise KeyError(f"Unknown manifest kind: {kind}")
    manifest = dict(payload)
    manifest.setdefault("manifest_kind", kind)
    manifest.setdefault("manifest_schema_version", MANIFEST_SCHEMA_VERSION)
    manifest.setdefault("artifact_status", DEFAULT_ARTIFACT_STATUS)
    manifest.setdefault("freshness", DEFAULT_FRESHNESS)
    return manifest


def validate_manifest_payload(kind: str, payload: dict[str, Any]) -> list[str]:
    manifest = normalize_manifest_payload(kind, payload)
    required = MANIFEST_REQUIRED_KEYS[kind]
    errors = [key for key in required if key not in manifest]
    artifact_status = str(manifest.get("artifact_status"))
    freshness = str(manifest.get("freshness"))
    if artifact_status not in ALLOWED_ARTIFACT_STATUSES:
        errors.append(f"invalid artifact_status: {artifact_status}")
    if freshness not in ALLOWED_FRESHNESS_VALUES:
        errors.append(f"invalid freshness: {freshness}")
    return errors


def ensure_manifest_payload(kind: str, payload: dict[str, Any]) -> dict[str, Any]:
    manifest = normalize_manifest_payload(kind, payload)
    errors = validate_manifest_payload(kind, manifest)
    if errors:
        raise ValueError(
            f"Invalid {kind} manifest; issues: {', '.join(errors)}"
        )
    return manifest


def write_manifest(kind: str, path: Path, payload: dict[str, Any]) -> dict[str, Any]:
    manifest = ensure_manifest_payload(kind, payload)
    dump_json(path, manifest)
    return manifest
