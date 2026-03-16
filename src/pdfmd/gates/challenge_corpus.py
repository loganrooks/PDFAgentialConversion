#!/usr/bin/env python3
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import re
import subprocess
import sys
from collections import Counter
from pathlib import Path
from typing import Any

from pdfmd.common.manifests import write_manifest
from pdfmd.cli.quality_gate_common import (
    build_chunk_diagnostics,
    dump_json,
    extract_atomic_rag_blocks,
    load_json,
    markdown_code_block,
)


PROJECT_ROOT = Path("/Users/rookslog/Projects/PDFAgentialConversion")
SCRIPT_DIR = PROJECT_ROOT / "skills" / "pdf-to-structured-markdown" / "scripts"
DEFAULT_BASELINE_DIR = (
    PROJECT_ROOT
    / "skills"
    / "pdf-to-structured-markdown"
    / "references"
    / "baselines"
    / "challenge-corpus"
)
REQUIRED_CITATION_FIELDS = ("title", "authors", "publisher", "publication_year")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run the PDF converter and generic smoke checks on an out-of-sample challenge corpus."
    )
    parser.add_argument("corpus_config", type=Path)
    parser.add_argument(
        "--baseline-dir",
        type=Path,
        default=DEFAULT_BASELINE_DIR,
        help="Directory containing a frozen smoke-report.json baseline.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Rebuild output directories even if they already exist.",
    )
    parser.add_argument(
        "--skip-convert",
        action="store_true",
        help="Reuse existing bundles and only run the smoke checks.",
    )
    parser.add_argument(
        "--gate-mode",
        choices=("soft", "hard"),
        default="hard",
        help="Use hard non-regression mode by default; pass --gate-mode soft for exploratory report-only runs.",
    )
    parser.add_argument(
        "--variant-id",
        default="default",
        help="Logical heuristic variant identifier recorded in the challenge-corpus artifacts.",
    )
    parser.add_argument(
        "--report-dir",
        type=Path,
        help="Directory for the smoke-report and review packet artifacts. Defaults to generated/challenge-corpus.",
    )
    return parser.parse_args(argv)


def run_json_command(command: list[str]) -> tuple[int, dict[str, Any], str]:
    completed = subprocess.run(command, text=True, capture_output=True, check=False)
    stdout = completed.stdout.strip()
    if not stdout:
        message = completed.stderr.strip() or "Command produced no JSON output."
        raise RuntimeError(f"{' '.join(command)} failed: {message}")
    try:
        payload = json.loads(stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Invalid JSON from {' '.join(command)}") from exc
    return completed.returncode, payload, completed.stderr.strip()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(65536):
            digest.update(chunk)
    return digest.hexdigest()


def relative_to_project(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(PROJECT_ROOT))
    except ValueError:
        return str(path.resolve())


def metadata_completeness(citation: dict[str, Any]) -> dict[str, Any]:
    missing_fields: list[str] = []
    present_fields: list[str] = []
    for field in REQUIRED_CITATION_FIELDS:
        value = citation.get(field)
        if field == "authors":
            if value:
                present_fields.append(field)
            else:
                missing_fields.append(field)
            continue
        if value in (None, "", []):
            missing_fields.append(field)
        else:
            present_fields.append(field)
    return {
        "present_fields": present_fields,
        "missing_fields": missing_fields,
        "present_count": len(present_fields),
        "missing_count": len(missing_fields),
        "contributors_count": len(citation.get("contributors", [])),
    }


def audit_issue_counter(issue_codes: list[str]) -> dict[str, int]:
    return dict(Counter(issue_codes))


def diff_counter(current: dict[str, int], baseline: dict[str, int]) -> dict[str, int]:
    keys = set(current) | set(baseline)
    return {
        key: current.get(key, 0) - baseline.get(key, 0)
        for key in sorted(keys)
        if current.get(key, 0) != baseline.get(key, 0)
    }


def load_baseline_report(baseline_dir: Path) -> dict[str, Any] | None:
    baseline_path = baseline_dir / "smoke-report.json"
    if not baseline_path.exists():
        return None
    return load_json(baseline_path)


def baseline_entries_by_id(baseline_report: dict[str, Any] | None) -> dict[str, dict[str, Any]]:
    if not baseline_report:
        return {}
    return {entry["id"]: entry for entry in baseline_report.get("entries", [])}


def largest_atomic_block(bundle_dir: Path, metadata: dict[str, Any]) -> dict[str, Any] | None:
    best: dict[str, Any] | None = None
    for item in metadata.get("file_manifest", []):
        rag_path = item.get("rag_output_path")
        if not rag_path:
            continue
        text = (bundle_dir / rag_path).read_text(encoding="utf-8")
        for block in extract_atomic_rag_blocks(text):
            candidate = {
                "rag_output_path": rag_path,
                "title": item.get("title"),
                "ordinal": block.get("ordinal"),
                "label": block.get("label"),
                "kind": block.get("kind"),
                "token_count": block.get("token_count"),
                "snippet": block.get("text", "")[:700],
            }
            if best is None or candidate["token_count"] > best["token_count"]:
                best = candidate
    return best


def numbered_index_paths(metadata: dict[str, Any]) -> list[str]:
    flagged: list[str] = []
    for item in metadata.get("file_manifest", []):
        title = str(item.get("title") or "")
        output_path = str(item.get("output_path") or "")
        if item.get("kind") == "index" and re.match(r"^\d+\s*[.)]\s+", title):
            flagged.append(output_path)
    return flagged


def probe_limit_status(probe_section: dict[str, Any], limits: dict[str, int]) -> dict[str, Any]:
    summary = probe_section.get("issue_summary", {})
    failures = {
        code: {"actual": summary.get(code, 0), "limit": limit}
        for code, limit in limits.items()
        if summary.get(code, 0) > limit
    }
    return {"limits": limits, "failures": failures, "within_limits": not failures}


def entry_targets(entry_id: str, metadata: dict[str, Any], audit_section: dict[str, Any], probe_section: dict[str, Any], chunk_diagnostics: dict[str, Any]) -> dict[str, Any]:
    audit_codes = set(audit_section["issue_codes"])
    metadata_summary = metadata_completeness(metadata.get("citation", {}))
    targets: dict[str, Any] = {
        "metadata_complete": metadata_summary["missing_count"] == 0,
        "max_atomic_tokens": chunk_diagnostics["passage_block_atomic"]["max_tokens"],
        "within_atomic_cap": chunk_diagnostics["passage_block_atomic"]["max_tokens"] <= 1600,
    }
    if entry_id == "of-grammatology":
        targets["no_duplicate_output_path"] = "duplicate_output_path" not in audit_codes
        targets["no_invalid_range_overlap"] = "invalid_leaf_range_overlap" not in audit_codes and "overlapping_leaf_ranges" not in audit_codes
        targets["probe_issue_count_within_limit"] = probe_section["issue_count"] <= 5
        targets["probe_limit_status"] = probe_limit_status(
            probe_section,
            {
                "rag_block_lowercase_start": 2,
                "rag_block_dangling_end": 2,
                "rag_block_hyphen_end": 1,
                "repeated_adjacent_word": 0,
            },
        )
    elif entry_id == "specters-of-marx":
        targets["probe_issue_count_zero"] = probe_section["issue_count"] == 0
    elif entry_id == "otherwise-than-being":
        flagged_indexes = numbered_index_paths(metadata)
        targets["numbered_body_entries_not_indexed"] = len(flagged_indexes) == 0
        targets["numbered_index_paths"] = flagged_indexes
        targets["probe_issue_count_within_limit"] = probe_section["issue_count"] <= 6
        targets["probe_limit_status"] = probe_limit_status(
            probe_section,
            {
                "rag_block_lowercase_start": 5,
                "rag_block_dangling_end": 1,
                "rag_block_hyphen_end": 0,
                "repeated_adjacent_word": 0,
                "boundary_page_many_micro_regions": 0,
            },
        )
    return targets


def entry_delta(entry_report: dict[str, Any], baseline_entry: dict[str, Any] | None) -> dict[str, Any] | None:
    if baseline_entry is None:
        return None
    current_metadata = entry_report["metadata_summary"]
    baseline_metadata = baseline_entry.get("metadata_summary", {})
    current_chunk = entry_report["chunk_diagnostics"]
    baseline_chunk = baseline_entry.get("chunk_diagnostics", {})
    return {
        "metadata_present_delta": current_metadata["present_count"] - baseline_metadata.get("present_count", 0),
        "metadata_missing_delta": current_metadata["missing_count"] - baseline_metadata.get("missing_count", 0),
        "audit_issue_delta": entry_report["audit"]["issue_count"] - baseline_entry.get("audit", {}).get("issue_count", 0),
        "audit_codes_delta": diff_counter(
            audit_issue_counter(entry_report["audit"]["issue_codes"]),
            audit_issue_counter(baseline_entry.get("audit", {}).get("issue_codes", [])),
        ),
        "probe_issue_delta": entry_report["probe"]["issue_count"] - baseline_entry.get("probe", {}).get("issue_count", 0),
        "probe_codes_delta": diff_counter(
            entry_report["probe"]["issue_summary"],
            baseline_entry.get("probe", {}).get("issue_summary", {}),
        ),
        "chunk_max_delta": {
            strategy: current_chunk.get(strategy, {}).get("max_tokens", 0)
            - baseline_chunk.get(strategy, {}).get("max_tokens", 0)
            for strategy in ("passage_block_atomic", "window_700", "window_1000", "window_1400")
        },
    }


def safe_read_text(path: Path, limit: int = 1800) -> str:
    if not path.exists():
        return ""
    text = path.read_text(encoding="utf-8")
    return text[:limit].strip()


def derive_regression_spec(entry_id: str) -> Path | None:
    candidate = SCRIPT_DIR.parent / "references" / f"{entry_id}-regressions.json"
    if candidate.exists():
        return candidate
    return None


def gate_failures_for_entry(entry_id: str, entry_report: dict[str, Any]) -> list[str]:
    failures: list[str] = []
    audit_codes = set(entry_report["audit"]["issue_codes"])
    targets = entry_report["acceptance_targets"]
    regressions = entry_report.get("regressions")
    if not targets.get("metadata_complete", False):
        failures.append("metadata_incomplete")
    if not targets.get("within_atomic_cap", False):
        failures.append("atomic_chunk_above_cap")
    if regressions and regressions.get("failure_count", 0) != 0:
        failures.append("regressions_failed")

    if entry_id == "of-grammatology":
        if entry_report["audit"]["status"] != "pass":
            failures.append("audit_not_clean")
        if not targets.get("no_duplicate_output_path", False):
            failures.append("duplicate_output_path")
        if not targets.get("no_invalid_range_overlap", False):
            failures.append("invalid_or_overlapping_ranges")
        if not targets.get("probe_issue_count_within_limit", False):
            failures.append("probe_issue_count_above_limit")
        if not targets.get("probe_limit_status", {}).get("within_limits", False):
            failures.append("probe_code_limit_exceeded")
    elif entry_id == "specters-of-marx":
        if entry_report["audit"]["status"] != "pass":
            failures.append("audit_not_clean")
        if not targets.get("probe_issue_count_zero", False):
            failures.append("probe_nonzero")
    elif entry_id == "otherwise-than-being":
        disallowed = audit_codes - {"high_complex_layout_ratio"}
        if disallowed:
            failures.append("disallowed_audit_code")
        if not targets.get("numbered_body_entries_not_indexed", False):
            failures.append("numbered_entries_indexed")
        if not targets.get("probe_issue_count_within_limit", False):
            failures.append("probe_issue_count_above_limit")
        if not targets.get("probe_limit_status", {}).get("within_limits", False):
            failures.append("probe_code_limit_exceeded")
    return failures


def render_review_packet(report: dict[str, Any]) -> str:
    lines = [
        f"# Challenge Review Packet: {report['name']}",
        "",
        "Status: report-only. This packet is for sampled human inspection, not a hard gate.",
        "",
    ]
    for entry in report["entries"]:
        if entry["convert"]["status"] != "pass":
            lines.append(f"## {entry['label']}")
            lines.append("")
            lines.append("- Conversion failed; no review samples available.")
            lines.append("")
            continue
        output_dir = Path(entry["output_dir"])
        metadata_path = output_dir / "metadata.json"
        toc_path = output_dir / "toc.md"
        metadata = load_json(metadata_path)
        largest = largest_atomic_block(output_dir, metadata)
        prelim_path = output_dir / "frontmatter" / "00-preliminaries.md"

        lines.append(f"## {entry['label']}")
        lines.append("")
        lines.append("### Metadata Sample")
        lines.append("")
        lines.append(markdown_code_block(json.dumps(metadata.get("citation", {}), indent=2, ensure_ascii=False), "json"))
        prelim_excerpt = safe_read_text(prelim_path)
        if prelim_excerpt:
            lines.append("")
            lines.append(markdown_code_block(prelim_excerpt, "markdown"))

        lines.append("")
        lines.append("### ToC Sample")
        lines.append("")
        lines.append(markdown_code_block(safe_read_text(toc_path), "markdown"))

        lines.append("")
        lines.append("### Largest RAG Block Sample")
        lines.append("")
        if largest:
            lines.append(
                f"- Path: `{largest['rag_output_path']}` | kind `{largest['kind']}` | "
                f"label `{largest.get('label') or 'unanchored'}` | tokens `{largest['token_count']}`"
            )
            lines.append("")
            lines.append(markdown_code_block(largest["snippet"], "markdown"))
        else:
            lines.append("- No RAG leaf blocks were found.")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def render_markdown(report: dict[str, Any]) -> str:
    enforcement = (
        "hard non-regression gate"
        if report.get("gate_mode") == "hard"
        else "report-only soft gate"
    )
    lines = [
        f"# Challenge Corpus Smoke Report: {report['name']}",
        "",
        f"- Generated: `{report['generated_at']}`",
        f"- Entry count: `{len(report['entries'])}`",
        f"- Baseline: `{report['baseline_dir'] or 'none'}`",
        f"- Variant: `{report.get('variant_id', 'default')}`",
        f"- Enforcement: `{enforcement}`",
        "",
    ]
    for entry in report["entries"]:
        lines.append(f"## {entry['label']}")
        lines.append("")
        lines.append(f"- Input: `{entry['input_pdf']}`")
        lines.append(f"- Bundle: `{entry['output_dir']}`")
        lines.append(f"- Convert status: `{entry['convert']['status']}`")
        if entry["convert"]["status"] == "skipped":
            lines.append("- Convert skipped: existing bundle reused.")
            lines.append("")
        elif entry["convert"]["status"] != "pass":
            stderr = entry["convert"].get("stderr") or "conversion failed"
            lines.append(f"- Convert stderr: `{stderr}`")
            lines.append("")
            continue
        lines.append(
            f"- Metadata completeness: `{entry['metadata_summary']['present_count']}` present / "
            f"`{entry['metadata_summary']['missing_count']}` missing "
            f"({', '.join(entry['metadata_summary']['missing_fields']) if entry['metadata_summary']['missing_fields'] else 'none'})"
        )
        lines.append(
            f"- Audit: `{entry['audit']['status']}` with codes "
            f"`{', '.join(entry['audit']['issue_codes']) if entry['audit']['issue_codes'] else 'none'}`"
        )
        lines.append(
            f"- Probe: `{entry['probe']['issue_count']}` issues "
            f"({json.dumps(entry['probe']['issue_summary'], ensure_ascii=False, sort_keys=True)})"
        )
        lines.append(
            f"- Chunks: atomic max `{entry['chunk_diagnostics']['passage_block_atomic']['max_tokens']}`, "
            f"window_1000 max `{entry['chunk_diagnostics']['window_1000']['max_tokens']}`"
        )
        if entry.get("regressions"):
            lines.append(
                f"- Regressions: `{entry['regressions']['pass_count']}` pass / "
                f"`{entry['regressions']['failure_count']}` fail"
            )
        target_summary = ", ".join(
            f"{key}={value}"
            for key, value in entry["acceptance_targets"].items()
            if not isinstance(value, list)
        )
        lines.append(f"- Targets: `{target_summary}`")
        if entry.get("gate_failures"):
            lines.append(f"- Gate failures: `{', '.join(entry['gate_failures'])}`")
        if entry.get("baseline_delta"):
            lines.append(
                f"- Delta vs baseline: metadata missing `{entry['baseline_delta']['metadata_missing_delta']}`, "
                f"audit issues `{entry['baseline_delta']['audit_issue_delta']}`, "
                f"probe issues `{entry['baseline_delta']['probe_issue_delta']}`"
            )
            if entry["baseline_delta"]["audit_codes_delta"]:
                lines.append(
                    f"- Audit code delta: `{json.dumps(entry['baseline_delta']['audit_codes_delta'], sort_keys=True)}`"
                )
            if entry["baseline_delta"]["probe_codes_delta"]:
                lines.append(
                    f"- Probe code delta: `{json.dumps(entry['baseline_delta']['probe_codes_delta'], sort_keys=True)}`"
                )
        lines.append("")
    return "\n".join(lines) + "\n"


def main() -> int:
    args = parse_args()
    config_path = args.corpus_config.resolve()
    config = load_json(config_path)
    generated_at = dt.datetime.now(dt.UTC).isoformat()
    baseline_report = load_baseline_report(args.baseline_dir.resolve())
    baseline_entries = baseline_entries_by_id(baseline_report)

    entries_report: list[dict[str, Any]] = []
    overall_status = "pass"
    gate_failures: list[dict[str, Any]] = []

    for entry in config["entries"]:
        input_pdf = Path(entry["input_pdf"]).resolve()
        output_dir = Path(entry["output_dir"]).resolve()
        entry_report: dict[str, Any] = {
            "id": entry["id"],
            "label": entry["label"],
            "input_pdf": str(input_pdf),
            "input_pdf_sha256": sha256_file(input_pdf),
            "output_dir": str(output_dir),
        }

        convert_status = {"status": "skipped", "output": None, "stderr": ""}
        if not args.skip_convert:
            command = [
                sys.executable,
                str(SCRIPT_DIR / "convert_pdf.py"),
                str(input_pdf),
                str(output_dir),
                "--book-id",
                entry["book_id"],
            ]
            if args.force:
                command.append("--force")
            completed = subprocess.run(command, text=True, capture_output=True, check=False)
            convert_status["stderr"] = completed.stderr.strip()
            if completed.returncode == 0:
                convert_status["status"] = "pass"
                stdout = completed.stdout.strip()
                convert_status["output"] = json.loads(stdout) if stdout else None
            else:
                convert_status["status"] = "fail"
                convert_status["output"] = completed.stdout.strip()
                overall_status = "fail"
                entry_report["convert"] = convert_status
                entries_report.append(entry_report)
                continue
        entry_report["convert"] = convert_status

        audit_code, audit_report, audit_stderr = run_json_command(
            [sys.executable, str(SCRIPT_DIR / "audit_bundle.py"), str(output_dir)]
        )
        probe_code, probe_report, probe_stderr = run_json_command(
            [sys.executable, str(SCRIPT_DIR / "probe_artifacts.py"), str(output_dir)]
        )
        regression_spec = derive_regression_spec(entry["id"])
        regressions_section: dict[str, Any] | None = None
        if regression_spec is not None:
            regressions_code, regressions_report, regressions_stderr = run_json_command(
                [
                    sys.executable,
                    str(SCRIPT_DIR / "check_regressions.py"),
                    str(output_dir),
                    str(regression_spec),
                    "--strict",
                ]
            )
            regressions_section = {
                "path": relative_to_project(regression_spec),
                "exit_code": regressions_code,
                "stderr": regressions_stderr,
                "failure_count": regressions_report.get("failure_count", 0),
                "pass_count": regressions_report.get("pass_count", 0),
            }

        metadata = load_json(output_dir / "metadata.json")
        chunk_diagnostics = build_chunk_diagnostics(output_dir, metadata)
        metadata_summary = metadata_completeness(metadata.get("citation", {}))

        audit_section = {
            "exit_code": audit_code,
            "stderr": audit_stderr,
            "status": audit_report.get("status"),
            "issue_count": audit_report.get("issue_count", 0),
            "issue_codes": [issue["code"] for issue in audit_report.get("issues", [])],
        }
        probe_section = {
            "exit_code": probe_code,
            "stderr": probe_stderr,
            "issue_count": probe_report.get("issue_count", 0),
            "issue_summary": probe_report.get("issue_summary", {}),
        }

        if audit_section["status"] == "fail":
            overall_status = "fail"
        elif overall_status != "fail" and audit_section["status"] == "warn":
            overall_status = "warn"

        entry_report["metadata_summary"] = metadata_summary
        entry_report["audit"] = audit_section
        entry_report["probe"] = probe_section
        if regressions_section is not None:
            entry_report["regressions"] = regressions_section
        entry_report["chunk_diagnostics"] = chunk_diagnostics
        entry_report["acceptance_targets"] = entry_targets(
            entry["id"],
            metadata,
            audit_section,
            probe_section,
            chunk_diagnostics,
        )
        entry_report["gate_failures"] = gate_failures_for_entry(entry["id"], entry_report)
        if entry_report["gate_failures"]:
            gate_failures.append({"id": entry["id"], "failures": entry_report["gate_failures"]})
        entry_report["baseline_delta"] = entry_delta(entry_report, baseline_entries.get(entry["id"]))
        entry_report["bundle_paths"] = {
            "metadata": relative_to_project(output_dir / "metadata.json"),
            "index": relative_to_project(output_dir / "index.md"),
            "toc": relative_to_project(output_dir / "toc.md"),
        }
        entries_report.append(entry_report)

    report = {
        "name": config.get("name", "challenge-corpus"),
        "generated_at": generated_at,
        "status": overall_status,
        "baseline_dir": str(args.baseline_dir.resolve()) if args.baseline_dir else None,
        "gate_mode": args.gate_mode,
        "variant_id": args.variant_id,
        "gate_failures": gate_failures,
        "entries": entries_report,
    }

    report_dir = args.report_dir.resolve() if args.report_dir else (PROJECT_ROOT / "generated" / "challenge-corpus")
    report_dir.mkdir(parents=True, exist_ok=True)
    write_manifest(
        "challenge_corpus",
        report_dir / "run-manifest.json",
        {
            "generated_at": generated_at,
            "variant_id": args.variant_id,
            "baseline_dir": str(args.baseline_dir.resolve()) if args.baseline_dir else None,
            "entry_count": len(entries_report),
            "artifact_status": "generated",
            "freshness": "fresh",
            "gate_mode": args.gate_mode,
            "skip_convert": args.skip_convert,
            "corpus_config": {
                "path": str(config_path),
                "sha256": hashlib.sha256(config_path.read_text(encoding="utf-8").encode("utf-8")).hexdigest(),
            },
            "entries": [
                {
                    "id": entry["id"],
                    "label": entry["label"],
                    "input_pdf": entry["input_pdf"],
                    "input_pdf_sha256": entry["input_pdf_sha256"],
                    "converter_version": (
                        load_json(Path(entry["output_dir"]) / "metadata.json").get("extraction", {}).get("script_version")
                        if (Path(entry["output_dir"]) / "metadata.json").exists()
                        else None
                    ),
                }
                for entry in entries_report
            ],
        },
    )
    dump_json(report_dir / "smoke-report.json", report)
    (report_dir / "smoke-report.md").write_text(render_markdown(report), encoding="utf-8")
    (report_dir / "review-packet.md").write_text(render_review_packet(report), encoding="utf-8")
    print(json.dumps(report, indent=2, ensure_ascii=False))
    if args.gate_mode == "hard" and (overall_status == "fail" or gate_failures):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
