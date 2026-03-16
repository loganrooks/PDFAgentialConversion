from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

from pdfmd.common.io import load_json, newest_child_directory
from pdfmd.common.paths import project_paths, resolve_project_root
from pdfmd.ops.doctor import build_report as build_doctor_report


PROJECT_ROOT = resolve_project_root()
ROADMAP_PATH = project_paths(PROJECT_ROOT).planning_dir / "ROADMAP.md"
PHASE_RE = re.compile(r"^### Phase (?P<number>\d+): (?P<name>.+)$")
STATUS_RE = re.compile(r"^- Status: (?P<status>[a-z_]+)$")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Render a compact project health snapshot.")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--project-root", type=Path, default=PROJECT_ROOT)
    return parser.parse_args(argv)


def roadmap_snapshot(path: Path) -> dict[str, Any]:
    current: dict[str, Any] | None = None
    phases: list[dict[str, Any]] = []
    lines = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
    for index, line in enumerate(lines):
        phase_match = PHASE_RE.match(line.strip())
        if not phase_match:
            continue
        status = "unknown"
        if index + 1 < len(lines):
            status_match = STATUS_RE.match(lines[index + 1].strip())
            if status_match:
                status = status_match.group("status")
        phase = {
            "number": phase_match.group("number"),
            "name": phase_match.group("name"),
            "status": status,
        }
        phases.append(phase)
        if current is None and status != "done":
            current = phase
    milestone_ready = bool(phases) and current is None
    next_milestone_planning = not phases
    return {
        "current_phase": current,
        "phases": phases,
        "milestone_ready": milestone_ready,
        "next_milestone_planning": next_milestone_planning,
    }


def latest_backend_comparison(root: Path) -> dict[str, Any] | None:
    if not root.exists():
        return None
    latest_dir = newest_child_directory(root)
    if latest_dir is None:
        return None
    summary_path = latest_dir / "comparison-summary.json"
    if not summary_path.exists():
        return None
    payload = load_json(summary_path)
    manifest_path = latest_dir / "run-manifest.json"
    manifest = load_json(manifest_path) if manifest_path.exists() else {}
    return {
        "path": str(summary_path),
        "run_id": payload.get("run_id"),
        "generated_at": payload.get("generated_at"),
        "selection": payload.get("selection"),
        "dry_run": payload.get("dry_run"),
        "result_count": len(payload.get("results", [])),
        "artifact_status": manifest.get("artifact_status"),
        "freshness": manifest.get("freshness"),
    }


def load_artifact_status(
    report_path: Path,
    manifest_path: Path,
    *,
    status_key: str,
    extra_fields: tuple[str, ...] = (),
) -> dict[str, Any] | None:
    report = load_json(report_path) if report_path.exists() else None
    manifest = load_json(manifest_path) if manifest_path.exists() else None
    if report is None and manifest is None:
        return None
    status = report.get(status_key) if report else None
    payload: dict[str, Any] = {
        "status": status or manifest.get("artifact_status") if manifest else status,
        "generated_at": (report or {}).get("generated_at") or (manifest or {}).get("generated_at"),
        "artifact_status": (manifest or {}).get("artifact_status"),
        "freshness": (manifest or {}).get("freshness"),
    }
    for field in extra_fields:
        if report and field in report:
            payload[field] = report[field]
        elif manifest and field in manifest:
            payload[field] = manifest[field]
    return payload


def build_report(project_root: Path) -> dict[str, Any]:
    paths = project_paths(project_root)
    roadmap = roadmap_snapshot(project_root / ".planning" / "ROADMAP.md")
    bundle_manifest_path = paths.why_ethics_bundle_dir / "run-manifest.json"
    bundle_metadata_path = paths.why_ethics_bundle_dir / "metadata.json"
    quality_gate_report_path = paths.why_ethics_quality_gate_report
    challenge_report_path = paths.challenge_corpus_report
    backend_comparison_root = paths.backend_comparison_root
    quality_gate_manifest_path = paths.why_ethics_bundle_dir / "quality-gate" / "run-manifest.json"
    challenge_manifest_path = paths.project_root / "generated" / "challenge-corpus" / "run-manifest.json"
    bundle_manifest = load_json(bundle_manifest_path) if bundle_manifest_path.exists() else None
    if bundle_manifest is None and bundle_metadata_path.exists():
        bundle_metadata = load_json(bundle_metadata_path)
        extraction = bundle_metadata.get("extraction", {})
        bundle_manifest = {
            "generated_at": extraction.get("generated_at"),
            "book_id": bundle_metadata.get("book_id"),
            "output_dir": str((project_root / "generated" / "why-ethics").resolve()),
        }
    quality_gate = load_artifact_status(
        quality_gate_report_path,
        quality_gate_manifest_path,
        status_key="status",
        extra_fields=("hard_gate_failures",),
    )
    challenge = load_artifact_status(
        challenge_report_path,
        challenge_manifest_path,
        status_key="status",
        extra_fields=("gate_failures", "gate_mode"),
    )
    backend = latest_backend_comparison(backend_comparison_root)
    doctor = build_doctor_report(project_root)

    active_failures: list[str] = []
    if quality_gate:
        active_failures.extend(
            f"why-ethics:{item['gate']}" for item in quality_gate.get("hard_gate_failures", [])
        )
    if challenge:
        for item in challenge.get("gate_failures", []):
            active_failures.append(f"{item['id']}:{','.join(item['failures'])}")
    active_failures = list(dict.fromkeys(active_failures))

    return {
        "project_root": str(project_root.resolve()),
        "roadmap": roadmap,
        "bundle_generation": (
            {
                "generated_at": bundle_manifest.get("generated_at"),
                "book_id": bundle_manifest.get("book_id"),
                "output_dir": bundle_manifest.get("output_dir"),
            }
            if bundle_manifest
            else None
        ),
        "why_ethics_gate": (
            {
                "status": quality_gate.get("status"),
                "generated_at": quality_gate.get("generated_at"),
                "hard_failure_count": len(quality_gate.get("hard_gate_failures", [])),
                "artifact_status": quality_gate.get("artifact_status"),
                "freshness": quality_gate.get("freshness"),
            }
            if quality_gate
            else None
        ),
        "challenge_corpus": (
            {
                "status": challenge.get("status"),
                "generated_at": challenge.get("generated_at"),
                "gate_failure_count": len(challenge.get("gate_failures", [])),
                "artifact_status": challenge.get("artifact_status"),
                "freshness": challenge.get("freshness"),
                "gate_mode": challenge.get("gate_mode"),
            }
            if challenge
            else None
        ),
        "backend_comparison": backend,
        "active_failures": active_failures,
        "environment": {
            "local_python": doctor["local"]["python_version"],
            "local_swift": doctor["local"]["swift_version"],
            "apple_helper_ready": doctor["local"]["apple_helper_ready"],
            "remote_backends_config_exists": doctor["remote_backends_config_exists"],
            "remote_backends": [
                {
                    "id": item["id"],
                    "reachable": item["reachable"],
                    "python_version": item["python_version"],
                    "gpu": item["gpu"],
                }
                for item in doctor["remote_backends"]
            ],
        },
    }


def render_text(report: dict[str, Any]) -> str:
    current_phase = report["roadmap"]["current_phase"]
    milestone_ready = report["roadmap"].get("milestone_ready", False)
    next_milestone_planning = report["roadmap"].get("next_milestone_planning", False)
    gate = report["why_ethics_gate"]
    challenge = report["challenge_corpus"]
    backend = report["backend_comparison"]
    bundle_generation = report["bundle_generation"]
    lines = [
        "# Status Snapshot",
        "",
        (
            f"- Current phase: `{current_phase['number']} {current_phase['name']}`"
            if current_phase
            else (
                "- Current phase: `milestone audit/completion`"
                if milestone_ready
                else (
                    "- Current phase: `next milestone planning`"
                    if next_milestone_planning
                    else "- Current phase: `unknown`"
                )
            )
        ),
        (
            f"- Latest bundle: `{bundle_generation['book_id']}` @ `{bundle_generation['generated_at']}`"
            if bundle_generation
            else "- Latest bundle: `missing`"
        ),
        (
            f"- Why-ethics gate: `{gate['status']}` freshness=`{gate.get('freshness') or 'unknown'}` @ `{gate['generated_at']}`"
            if gate
            else "- Why-ethics gate: `missing`"
        ),
        (
            f"- Challenge corpus: `{challenge['status']}` mode=`{challenge.get('gate_mode') or 'unknown'}` freshness=`{challenge.get('freshness') or 'unknown'}` @ `{challenge['generated_at']}`"
            if challenge
            else "- Challenge corpus: `missing`"
        ),
        (
            f"- Backend comparison: run `{backend['run_id']}` dry_run=`{backend['dry_run']}` freshness=`{backend.get('freshness') or 'unknown'}` @ `{backend['generated_at']}`"
            if backend
            else "- Backend comparison: `missing`"
        ),
        f"- Local Python: `{report['environment']['local_python']}`",
        f"- Local Swift: `{report['environment']['local_swift'] or 'unavailable'}`",
        f"- Apple helper ready: `{report['environment']['apple_helper_ready']}`",
        f"- Remote backend config present: `{report['environment']['remote_backends_config_exists']}`",
        "",
        "## Active Failures",
    ]
    if report["active_failures"]:
        for item in report["active_failures"]:
            lines.append(f"- `{item}`")
    else:
        lines.append("- none")
    lines.append("")
    lines.append("## Remote Backends")
    if report["environment"]["remote_backends"]:
        for backend_item in report["environment"]["remote_backends"]:
            lines.append(
                f"- `{backend_item['id']}` reachable=`{backend_item['reachable']}` "
                f"python=`{backend_item['python_version'] or 'unavailable'}` "
                f"gpu=`{backend_item['gpu'] or 'unavailable'}`"
            )
    else:
        lines.append("- none")
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    report = build_report(args.project_root.resolve())
    if args.json:
        print(json.dumps(report, indent=2, ensure_ascii=False))
    else:
        print(render_text(report), end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
