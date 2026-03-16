#!/usr/bin/env python3
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path("/Users/rookslog/Projects/PDFAgentialConversion")
SCRIPT_DIR = PROJECT_ROOT / "skills" / "pdf-to-structured-markdown" / "scripts"
DEFAULT_GATE_CONFIG = (
    PROJECT_ROOT
    / "skills"
    / "pdf-to-structured-markdown"
    / "references"
    / "why-ethics-quality-gate.json"
)
DEFAULT_CHALLENGE_CONFIG = (
    PROJECT_ROOT
    / "skills"
    / "pdf-to-structured-markdown"
    / "references"
    / "challenge-corpus.json"
)
DEFAULT_WHY_ETHICS_PDF = PROJECT_ROOT / "Gibbs_WhyEthics.pdf"
DEFAULT_OUT_DIR = PROJECT_ROOT / "generated" / "variant-comparison"


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Run named heuristic variants against the why-ethics quality gate "
            "and the challenge corpus, then compare the results."
        )
    )
    parser.add_argument(
        "variants_json",
        type=Path,
        nargs="?",
        help="Optional JSON file describing variant ids, labels, and environment overrides.",
    )
    parser.add_argument("--why-ethics-pdf", type=Path, default=DEFAULT_WHY_ETHICS_PDF)
    parser.add_argument("--gate-config", type=Path, default=DEFAULT_GATE_CONFIG)
    parser.add_argument("--challenge-config", type=Path, default=DEFAULT_CHALLENGE_CONFIG)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--gate-mode", choices=("soft", "hard"), default="soft")
    parser.add_argument("--skip-convert", action="store_true")
    parser.add_argument("--force", action="store_true")
    parser.add_argument(
        "--variants",
        help="Optional comma-separated variant ids to run from the variants JSON.",
    )
    parser.add_argument("--embedding-timeout-seconds", type=int)
    parser.add_argument("--embedding-retries", type=int)
    parser.add_argument("--stability-runs", type=int)
    return parser.parse_args(argv)


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def dump_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def load_variants(path: Path | None) -> list[dict[str, Any]]:
    if path is None:
        return [{"id": "default", "label": "Default", "env": {}, "description": "Baseline behavior."}]
    payload = load_json(path)
    variants = payload.get("variants", [])
    if not variants:
        raise SystemExit(f"No variants found in {path}")
    return variants


def filter_variants(variants: list[dict[str, Any]], requested: str | None) -> list[dict[str, Any]]:
    if not requested:
        return variants
    requested_ids = [item.strip() for item in requested.split(",") if item.strip()]
    if not requested_ids:
        return variants
    by_id = {variant["id"]: variant for variant in variants}
    missing = [variant_id for variant_id in requested_ids if variant_id not in by_id]
    if missing:
        raise SystemExit(f"Unknown variant id(s): {', '.join(missing)}")
    return [by_id[variant_id] for variant_id in requested_ids]


def run_command(command: list[str], *, env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, text=True, capture_output=True, check=False, env=env)


def rewrite_challenge_config(config_path: Path, variant_dir: Path) -> Path:
    payload = load_json(config_path)
    rewritten = json.loads(json.dumps(payload))
    for entry in rewritten.get("entries", []):
        entry["output_dir"] = str((variant_dir / entry["id"]).resolve())
    target = variant_dir / "challenge-corpus.config.json"
    dump_json(target, rewritten)
    return target


def quality_gate_summary(report: dict[str, Any]) -> dict[str, Any]:
    runtime = report.get("sections", {}).get("runtime", {})
    embedding_runtime = runtime.get("commands", {}).get("embedding", {})
    retrieval = report.get("sections", {}).get("retrieval", {}).get("runs", {})
    return {
        "status": report.get("status"),
        "hard_failure_count": len(report.get("hard_gate_failures", [])),
        "hard_failures": report.get("hard_gate_failures", []),
        "probe_issue_count": report.get("sections", {}).get("probe", {}).get("issue_count"),
        "audit_codes": report.get("sections", {}).get("audit", {}).get("issue_codes", []),
        "embedding_runtime": embedding_runtime.get("summary", {}),
        "retrieval_runs": retrieval,
    }


def challenge_summary(report: dict[str, Any]) -> dict[str, Any]:
    return {
        "status": report.get("status"),
        "gate_mode": report.get("gate_mode"),
        "gate_failure_count": len(report.get("gate_failures", [])),
        "gate_failures": report.get("gate_failures", []),
        "entries": {
            entry["id"]: {
                "audit_status": entry.get("audit", {}).get("status"),
                "audit_codes": entry.get("audit", {}).get("issue_codes", []),
                "probe_issue_count": entry.get("probe", {}).get("issue_count"),
                "probe_issue_summary": entry.get("probe", {}).get("issue_summary", {}),
                "gate_failures": entry.get("gate_failures", []),
                "max_atomic_tokens": entry.get("chunk_diagnostics", {})
                .get("passage_block_atomic", {})
                .get("max_tokens"),
            }
            for entry in report.get("entries", [])
        },
    }


def render_markdown(report: dict[str, Any]) -> str:
    baseline = report["variants"][0] if report["variants"] else None
    lines = [
        "# Variant Comparison",
        "",
        f"- Generated: `{report['generated_at']}`",
        f"- Variant count: `{len(report['variants'])}`",
        "",
        "| Variant | Why-Ethics | Probe | Embedding Runtime | Of Grammar | Otherwise | Specters |",
        "| --- | --- | ---: | --- | --- | --- | --- |",
    ]
    for variant in report["variants"]:
        gate = variant["why_ethics"]
        challenge = variant["challenge_corpus"]
        runtime = gate.get("embedding_runtime", {})
        entries = challenge.get("entries", {})
        of_grammar = entries.get("of-grammatology", {})
        otherwise = entries.get("otherwise-than-being", {})
        specters = entries.get("specters-of-marx", {})
        lines.append(
            f"| `{variant['id']}` | `{gate['status']}` | `{gate.get('probe_issue_count')}` | "
            f"`{runtime.get('failure_category') or 'ok'}` | "
            f"`{of_grammar.get('probe_issue_count')}` / `{of_grammar.get('max_atomic_tokens')}` | "
            f"`{otherwise.get('probe_issue_count')}` / `{','.join(otherwise.get('audit_codes', [])) or 'pass'}` | "
            f"`{specters.get('probe_issue_count')}` / `{specters.get('audit_status')}` |"
        )
    lines.append("")
    for variant in report["variants"]:
        lines.append(f"## {variant['label']}")
        lines.append("")
        lines.append(f"- Variant id: `{variant['id']}`")
        if variant.get("description"):
            lines.append(f"- Description: {variant['description']}")
        lines.append(f"- Why-ethics status: `{variant['why_ethics']['status']}`")
        if variant["why_ethics"]["hard_failures"]:
            lines.append(
                f"- Why-ethics failures: `{'; '.join(item['gate'] for item in variant['why_ethics']['hard_failures'])}`"
            )
        lines.append(
            f"- Challenge status: `{variant['challenge_corpus']['status']}` with "
            f"`{variant['challenge_corpus']['gate_failure_count']}` gate-failure group(s)"
        )
        entries = variant["challenge_corpus"]["entries"]
        for entry_id in ("of-grammatology", "otherwise-than-being", "specters-of-marx"):
            entry = entries.get(entry_id, {})
            baseline_entry = (
                baseline["challenge_corpus"]["entries"].get(entry_id, {})
                if baseline is not None
                else {}
            )
            baseline_probe = baseline_entry.get("probe_issue_count")
            current_probe = entry.get("probe_issue_count")
            probe_delta = (
                None
                if baseline_probe is None or current_probe is None
                else current_probe - baseline_probe
            )
            delta_text = (
                ""
                if probe_delta is None or variant is baseline
                else f" (delta `{probe_delta:+d}`)"
            )
            lines.append(
                f"- {entry_id}: audit `{entry.get('audit_status')}`, "
                f"probe `{current_probe}`{delta_text}, "
                f"max atomic `{entry.get('max_atomic_tokens')}`, "
                f"failures `{', '.join(entry.get('gate_failures', [])) or 'none'}`"
            )
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def main() -> int:
    args = parse_args()
    variants = filter_variants(
        load_variants(args.variants_json.resolve() if args.variants_json else None),
        args.variants,
    )
    out_dir = args.out_dir.resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    report: dict[str, Any] = {
        "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "variants": [],
    }

    for variant in variants:
        variant_id = variant["id"]
        variant_label = variant.get("label", variant_id)
        variant_dir = out_dir / variant_id
        variant_dir.mkdir(parents=True, exist_ok=True)
        if args.skip_convert:
            why_ethics_bundle = Path(
                variant.get("existing_bundle_dir")
                or (PROJECT_ROOT / "generated" / "why-ethics")
            ).resolve()
            variant_challenge_config = Path(
                variant.get("existing_challenge_config") or args.challenge_config.resolve()
            ).resolve()
        else:
            why_ethics_bundle = variant_dir / "why-ethics"
            variant_challenge_config = rewrite_challenge_config(args.challenge_config.resolve(), variant_dir)
        why_ethics_gate_dir = variant_dir / "quality-gate"
        challenge_report_dir = variant_dir / "challenge-corpus"

        env = os.environ.copy()
        env.update({str(key): str(value) for key, value in variant.get("env", {}).items()})
        env["PDFMD_VARIANT_ID"] = variant_id

        if not args.skip_convert:
            convert_command = [
                sys.executable,
                str(SCRIPT_DIR / "convert_pdf.py"),
                str(args.why_ethics_pdf.resolve()),
                str(why_ethics_bundle),
                "--book-id",
                "robert-gibbs-why-ethics",
            ]
            if args.force:
                convert_command.append("--force")
            completed = run_command(convert_command, env=env)
            if completed.returncode != 0:
                raise SystemExit(
                    f"Why-ethics conversion failed for variant {variant_id}:\n{completed.stderr.strip()}"
                )

        gate_command = [
            sys.executable,
            str(SCRIPT_DIR / "run_quality_gate.py"),
            str(why_ethics_bundle),
            str(args.gate_config.resolve()),
            "--out-dir",
            str(why_ethics_gate_dir),
            "--variant-id",
            variant_id,
        ]
        if args.embedding_timeout_seconds is not None:
            gate_command.extend(["--embedding-timeout-seconds", str(args.embedding_timeout_seconds)])
        if args.embedding_retries is not None:
            gate_command.extend(["--embedding-retries", str(args.embedding_retries)])
        if args.stability_runs is not None:
            gate_command.extend(["--stability-runs", str(args.stability_runs)])
        run_command(gate_command, env=env)
        gate_report = load_json(why_ethics_gate_dir / "quality-gate-report.json")

        challenge_command = [
            sys.executable,
            str(SCRIPT_DIR / "run_challenge_corpus.py"),
            str(variant_challenge_config),
            "--gate-mode",
            args.gate_mode,
            "--variant-id",
            variant_id,
            "--report-dir",
            str(challenge_report_dir),
        ]
        if args.skip_convert:
            challenge_command.append("--skip-convert")
        if args.force:
            challenge_command.append("--force")
        run_command(challenge_command, env=env)
        challenge_report = load_json(challenge_report_dir / "smoke-report.json")

        report["variants"].append(
            {
                "id": variant_id,
                "label": variant_label,
                "description": variant.get("description"),
                "env": variant.get("env", {}),
                "why_ethics": quality_gate_summary(gate_report),
                "challenge_corpus": challenge_summary(challenge_report),
                "paths": {
                    "why_ethics_bundle": str(why_ethics_bundle),
                    "quality_gate_dir": str(why_ethics_gate_dir),
                    "challenge_report_dir": str(challenge_report_dir),
                },
            }
        )

    dump_json(out_dir / "comparison-summary.json", report)
    (out_dir / "comparison-summary.md").write_text(render_markdown(report), encoding="utf-8")
    print(json.dumps(report, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
