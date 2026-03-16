#!/usr/bin/env python3
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import re
import signal
import subprocess
import sys
import time
from collections import Counter
from pathlib import Path
from typing import Any

from pdfmd.benchmarks.calibration import (
    load_calibration_report,
    resolve_calibration_dir,
    selected_timeout_from_report,
)
from pdfmd.common.manifests import write_manifest
from pdfmd.cli.quality_gate_common import (
    SCRIPT_DIR,
    build_chunk_diagnostics,
    classify_probe_issues,
    dump_json,
    flatten_scope_entries,
    load_json,
    resolve_reference_path,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Run the structural, artifact, retrieval, embedding, and review gates "
            "for a generated PDF bundle."
        )
    )
    parser.add_argument("bundle_dir", type=Path)
    parser.add_argument("gate_config", type=Path)
    parser.add_argument(
        "--out-dir",
        type=Path,
        help="Directory for the gate artifacts. Defaults to <bundle>/quality-gate.",
    )
    parser.add_argument(
        "--embedding-timeout-seconds",
        type=int,
        help="Override the embedding evaluator helper timeout in seconds.",
    )
    parser.add_argument(
        "--embedding-retries",
        type=int,
        help="Override the number of retry attempts for embedding runtime failures.",
    )
    parser.add_argument(
        "--stability-runs",
        type=int,
        help="Override the number of consecutive full gate runs required for stability.",
    )
    parser.add_argument(
        "--variant-id",
        default=os.environ.get("PDFMD_VARIANT_ID", "default"),
        help="Logical heuristic variant identifier recorded in gate artifacts.",
    )
    return parser.parse_args()


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def parse_cleanup_result(stderr: str) -> str | None:
    match = re.search(r"cleanup=(?P<cleanup>[A-Za-z0-9_.:-]+)", stderr)
    return match.group("cleanup") if match else None


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


def invoke_json_attempt(
    command: list[str],
    *,
    timeout_seconds: int | None = None,
) -> dict[str, Any]:
    started = time.monotonic()
    runtime: dict[str, Any] = {
        "command": command,
        "timeout_seconds": timeout_seconds,
        "completed": False,
        "failure_category": None,
        "cleanup_result": None,
        "exit_code": None,
        "stderr": "",
        "stdout": "",
        "payload": None,
    }
    try:
        if timeout_seconds is None:
            completed = subprocess.run(command, text=True, capture_output=True, check=False)
            stdout = completed.stdout.strip()
            stderr = completed.stderr.strip()
            exit_code = completed.returncode
        else:
            process = subprocess.Popen(
                command,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                start_new_session=True,
            )
            try:
                stdout, stderr = process.communicate(timeout=timeout_seconds)
            except subprocess.TimeoutExpired:
                cleanup_result = terminate_process_group(process)
                stdout, stderr = process.communicate()
                runtime.update(
                    {
                        "failure_category": "timeout",
                        "cleanup_result": cleanup_result,
                        "stderr": stderr.strip(),
                        "stdout": stdout.strip(),
                    }
                )
                return runtime | {
                    "duration_seconds": round(time.monotonic() - started, 4),
                }
            exit_code = process.returncode
            stdout = stdout.strip()
            stderr = stderr.strip()
    except OSError as exc:
        runtime.update({"failure_category": "oserror", "error": str(exc)})
        return runtime | {
            "duration_seconds": round(time.monotonic() - started, 4),
        }

    runtime.update(
        {
            "exit_code": exit_code,
            "stdout": stdout,
            "stderr": stderr,
            "duration_seconds": round(time.monotonic() - started, 4),
        }
    )
    if not stdout:
        runtime["failure_category"] = (
            "timeout" if "timed out" in stderr.lower() else "empty_stdout"
        )
        runtime["cleanup_result"] = runtime.get("cleanup_result") or parse_cleanup_result(stderr)
        return runtime
    try:
        payload = json.loads(stdout)
    except json.JSONDecodeError as exc:
        runtime["failure_category"] = "invalid_json"
        runtime["error"] = str(exc)
        return runtime
    runtime["payload"] = payload
    runtime["completed"] = True
    return runtime


def run_json_command(
    command: list[str],
    *,
    label: str,
    timeout_seconds: int | None = None,
    retries: int = 0,
) -> tuple[int | None, dict[str, Any], str, dict[str, Any]]:
    attempts: list[dict[str, Any]] = []
    max_attempts = max(1, retries + 1)
    selected: dict[str, Any] | None = None
    for attempt_index in range(1, max_attempts + 1):
        attempt = invoke_json_attempt(command, timeout_seconds=timeout_seconds)
        attempt["attempt"] = attempt_index
        attempts.append(attempt)
        if attempt["completed"]:
            selected = attempt
            break
        if attempt["failure_category"] not in {"timeout", "oserror", "empty_stdout", "invalid_json"}:
            selected = attempt
            break
    if selected is None:
        selected = attempts[-1]
    runtime = {
        "label": label,
        "status": "pass" if selected.get("completed") else "fail",
        "selected_attempt": selected.get("attempt"),
        "attempt_count": len(attempts),
        "attempts": attempts,
    }
    payload = selected.get("payload") if isinstance(selected.get("payload"), dict) else {}
    return selected.get("exit_code"), payload, str(selected.get("stderr") or ""), runtime


def sanitize_runtime(runtime: dict[str, Any]) -> dict[str, Any]:
    attempts: list[dict[str, Any]] = []
    for attempt in runtime.get("attempts", []):
        attempts.append(
            {
                "attempt": attempt.get("attempt"),
                "command": attempt.get("command"),
                "timeout_seconds": attempt.get("timeout_seconds"),
                "completed": attempt.get("completed"),
                "failure_category": attempt.get("failure_category"),
                "cleanup_result": attempt.get("cleanup_result"),
                "exit_code": attempt.get("exit_code"),
                "duration_seconds": attempt.get("duration_seconds"),
                "stdout_preview": str(attempt.get("stdout") or "")[:800],
                "stderr_preview": str(attempt.get("stderr") or "")[:1200],
            }
        )
    selected_attempt = attempts[runtime.get("selected_attempt", 1) - 1] if attempts and runtime.get("selected_attempt") else None
    return {
        "label": runtime.get("label"),
        "status": runtime.get("status"),
        "selected_attempt": runtime.get("selected_attempt"),
        "attempt_count": runtime.get("attempt_count"),
        "summary": {
            "success": runtime.get("status") == "pass",
            "failure_category": (selected_attempt or {}).get("failure_category"),
            "wall_clock_seconds": (selected_attempt or {}).get("duration_seconds"),
            "attempt_count": runtime.get("attempt_count"),
            "cleanup_result": (selected_attempt or {}).get("cleanup_result"),
        },
        "attempts": attempts,
    }


def collect_runtime_gate_failures(
    runtime_commands: dict[str, dict[str, Any]],
    *,
    completed_runs: int,
    stability_runs: int,
    identical_signatures: bool,
) -> list[dict[str, str]]:
    failures: list[dict[str, str]] = []
    selected_runtime_failed = False
    for stage, runtime in runtime_commands.items():
        if runtime["status"] != "pass":
            attempt = runtime["attempts"][-1] if runtime.get("attempts") else {}
            failure_category = attempt.get("failure_category") or "unknown_runtime_failure"
            failures.append(
                {
                    "gate": f"{stage}_runtime",
                    "message": f"{stage} command failed at runtime: {failure_category}.",
                }
            )
            selected_runtime_failed = True

    if selected_runtime_failed:
        return failures

    if completed_runs < stability_runs:
        failures.append(
            {
                "gate": "runtime_stability",
                "message": (
                    f"Only {completed_runs} of {stability_runs} required gate runs "
                    "completed with structured outputs."
                ),
            }
        )
    elif not identical_signatures:
        failures.append(
            {
                "gate": "runtime_stability",
                "message": "Consecutive gate runs produced non-identical summary signatures.",
            }
        )
    return failures


def build_run_manifest(
    metadata: dict[str, Any],
    *,
    config_path: Path,
    variant_id: str,
    generated_at: str,
) -> dict[str, Any]:
    source = metadata.get("source", {})
    extraction = metadata.get("extraction", {})
    return {
        "generated_at": generated_at,
        "variant_id": variant_id,
        "input_pdf": {
            "absolute_path": source.get("absolute_path"),
            "filename": source.get("filename"),
            "sha256": source.get("sha256"),
            "page_count": source.get("page_count"),
        },
        "converter_version": extraction.get("script_version"),
        "gate_config": {
            "path": str(config_path),
            "sha256": sha256_text(config_path.read_text(encoding="utf-8")),
        },
    }


def derive_regression_spec_path(config_path: Path) -> Path:
    stem = config_path.stem.replace("-quality-gate", "")
    return (config_path.parent / f"{stem}-regressions.json").resolve()


def delta(current: float | None, baseline: float | None) -> float | None:
    if current is None or baseline is None:
        return None
    return round(current - baseline, 6)


def build_retrieval_run_ids(config: dict[str, Any]) -> list[str]:
    corpora = config["retrieval_gates"]["corpora"]
    profiles = config["retrieval_gates"]["profiles"]
    return [f"{corpus}::{profile}" for corpus in corpora for profile in profiles]


def build_embedding_run_ids(config: dict[str, Any]) -> list[str]:
    corpora = config["embedding_gates"]["corpora"]
    views = config["embedding_gates"]["views"]
    return [f"{corpus}::{view}" for corpus in corpora for view in views]


def resolve_embedding_timeout(
    *,
    bundle_dir: Path,
    config_path: Path,
    runtime_config: dict[str, Any],
    override_timeout: int | None,
) -> tuple[int, str, dict[str, Any] | None]:
    if override_timeout is not None:
        return int(override_timeout), "cli_override", None

    default_timeout = int(runtime_config.get("embedding_timeout_seconds", 180))
    calibration_config = runtime_config.get("calibration") or {}
    calibration_dir = resolve_calibration_dir(
        bundle_dir,
        report_dir=calibration_config.get("report_dir"),
        project_root=bundle_dir.resolve().parents[1],
    )
    calibration_report = load_calibration_report(calibration_dir)
    calibration_snapshot = None
    if calibration_report:
        calibration_snapshot = {
            "report_dir": str(calibration_dir),
            "report_path": str(calibration_dir / "calibration-report.json"),
            "status": calibration_report.get("status"),
            "recommendation_status": calibration_report.get("recommendation_status"),
            "generated_at": calibration_report.get("generated_at"),
            "requested_runs": calibration_report.get("requested_runs"),
            "completed_runs": calibration_report.get("completed_runs"),
            "suggested_timeout_seconds": calibration_report.get("durations", {}).get(
                "suggested_timeout_seconds"
            ),
            "artifact_status": calibration_report.get("artifact_status"),
            "freshness": calibration_report.get("freshness"),
        }
        selected_timeout = selected_timeout_from_report(calibration_report)
        if selected_timeout is not None:
            source = (
                "calibration_report"
                if calibration_report.get("status") == "calibrated"
                else "calibration_report_provisional"
            )
            return selected_timeout, source, calibration_snapshot

    return default_timeout, "gate_config", calibration_snapshot


def build_gate_signature(
    audit_report: dict[str, Any],
    regressions_report: dict[str, Any],
    probe_report: dict[str, Any],
    retrieval_report: dict[str, Any],
    embedding_report: dict[str, Any],
) -> dict[str, Any]:
    payload = {
        "audit": {
            "status": audit_report.get("status"),
            "issues": [issue.get("code") for issue in audit_report.get("issues", [])],
        },
        "regressions": {
            "failure_count": regressions_report.get("failure_count"),
            "pass_count": regressions_report.get("pass_count"),
        },
        "probe": {
            "issue_count": probe_report.get("issue_count"),
            "issue_summary": probe_report.get("issue_summary", {}),
        },
        "retrieval": retrieval_report.get("summary_by_run", {}),
        "embedding": embedding_report.get("representation_summary_by_run", {}),
    }
    serialized = json.dumps(payload, sort_keys=True, ensure_ascii=False)
    return {
        "sha256": sha256_text(serialized),
        "payload": payload,
    }


def run_gate_iteration(
    *,
    bundle_dir: Path,
    config: dict[str, Any],
    retrieval_benchmark: Path,
    embedding_benchmark: Path,
    regression_spec: Path,
    embedding_timeout_seconds: int,
    embedding_retries: int,
) -> dict[str, Any]:
    audit_code, audit_report, audit_stderr, audit_runtime = run_json_command(
        [sys.executable, str(SCRIPT_DIR / "audit_bundle.py"), str(bundle_dir)],
        label="audit",
    )
    regressions_code, regressions_report, regressions_stderr, regressions_runtime = run_json_command(
        [
            sys.executable,
            str(SCRIPT_DIR / "check_regressions.py"),
            str(bundle_dir),
            str(regression_spec),
            "--strict",
        ],
        label="regressions",
    )
    probe_code, probe_report, probe_stderr, probe_runtime = run_json_command(
        [sys.executable, str(SCRIPT_DIR / "probe_artifacts.py"), str(bundle_dir)],
        label="probe",
    )
    retrieval_code, retrieval_report, retrieval_stderr, retrieval_runtime = run_json_command(
        [
            sys.executable,
            str(SCRIPT_DIR / "evaluate_retrieval.py"),
            str(bundle_dir),
            str(retrieval_benchmark),
            "--profiles",
            ",".join(config["retrieval_gates"]["profiles"]),
        ],
        label="retrieval",
    )
    embedding_code, embedding_report, embedding_stderr, embedding_runtime = run_json_command(
        [
            sys.executable,
            str(SCRIPT_DIR / "evaluate_embedding_space.py"),
            str(bundle_dir),
            str(embedding_benchmark),
            "--reference-corpus",
            config["embedding_gates"]["reference_corpus"],
            "--corpora",
            ",".join(config["embedding_gates"]["corpora"]),
            "--views",
            ",".join(config["embedding_gates"]["views"]),
            "--helper-timeout-seconds",
            str(embedding_timeout_seconds),
        ],
        label="embedding",
        timeout_seconds=embedding_timeout_seconds + 90,
        retries=embedding_retries,
    )

    return {
        "audit": {
            "code": audit_code,
            "report": audit_report,
            "stderr": audit_stderr,
            "runtime": audit_runtime,
        },
        "regressions": {
            "code": regressions_code,
            "report": regressions_report,
            "stderr": regressions_stderr,
            "runtime": regressions_runtime,
        },
        "probe": {
            "code": probe_code,
            "report": probe_report,
            "stderr": probe_stderr,
            "runtime": probe_runtime,
        },
        "retrieval": {
            "code": retrieval_code,
            "report": retrieval_report,
            "stderr": retrieval_stderr,
            "runtime": retrieval_runtime,
        },
        "embedding": {
            "code": embedding_code,
            "report": embedding_report,
            "stderr": embedding_stderr,
            "runtime": embedding_runtime,
        },
        "signature": build_gate_signature(
            audit_report,
            regressions_report,
            probe_report,
            retrieval_report,
            embedding_report,
        ),
    }


def aggregate_non_target_counts(classification: dict[str, Any]) -> Counter[str]:
    counts = Counter()
    for group in ("holdout_scopes", "negative_controls", "other"):
        counts.update(classification["counts_by_group"].get(group, {}))
    return counts


def aggregate_target_counts(classification: dict[str, Any]) -> Counter[str]:
    return Counter(classification["counts_by_group"].get("target_scopes", {}))


def evaluate_manual_sample(config: dict[str, Any]) -> dict[str, Any]:
    manual_config = config["manual_sample"]
    scope_entries = flatten_scope_entries(config)
    verdict_counts = Counter(entry.get("verdict", "pending") for entry in manual_config["entries"])
    target_entries = [
        entry
        for entry in manual_config["entries"]
        if scope_entries[entry["scope_id"]]["group"] == "target_scopes"
    ]
    fail_count = verdict_counts.get("fail", 0)
    pass_count = verdict_counts.get("pass", 0)
    overall_count = len(manual_config["entries"])
    targets_all_pass = all(entry.get("verdict") == "pass" for entry in target_entries)
    no_fail = fail_count == 0
    minimum_pass = pass_count >= int(manual_config.get("minimum_pass_count", 0))
    would_pass = no_fail and targets_all_pass and minimum_pass
    return {
        "enforce_acceptance": bool(manual_config.get("enforce_acceptance", False)),
        "entry_count": overall_count,
        "verdict_counts": dict(verdict_counts),
        "target_entry_count": len(target_entries),
        "no_fail": no_fail,
        "targets_all_pass": targets_all_pass,
        "minimum_pass_count_met": minimum_pass,
        "minimum_pass_count": int(manual_config.get("minimum_pass_count", 0)),
        "would_pass_acceptance": would_pass,
    }


def render_markdown_report(report: dict[str, Any]) -> str:
    lines: list[str] = []
    lines.append(f"# Quality Gate Report: {report['bundle_dir']}")
    lines.append("")
    lines.append(f"- Status: `{report['status']}`")
    lines.append(f"- Generated: `{report['generated_at']}`")
    lines.append(f"- Config: `{report['config']}`")
    lines.append(f"- Baseline: `{report['baseline_dir']}`")
    lines.append(f"- Variant: `{report.get('variant_id', 'default')}`")
    lines.append("")

    failures = report["hard_gate_failures"]
    lines.append("## Hard Gates")
    if failures:
        for failure in failures:
            lines.append(f"- `{failure['gate']}`: {failure['message']}")
    else:
        lines.append("- All enforced gates passed.")
    lines.append("")

    audit = report["sections"]["audit"]
    regressions = report["sections"]["regressions"]
    probe = report["sections"]["probe"]
    retrieval = report["sections"]["retrieval"]
    embedding = report["sections"]["embedding"]
    manual = report["sections"]["manual_sample"]
    chunking = report["sections"]["chunk_diagnostics"]
    stretch = report["sections"]["stretch_targets"]
    runtime = report["sections"]["runtime"]

    lines.append("## Structural")
    lines.append(
        f"- Audit codes: `{', '.join(audit['issue_codes']) if audit['issue_codes'] else 'none'}`"
    )
    lines.append(
        f"- Regression checks: `{regressions['pass_count']}` passes, `{regressions['failure_count']}` failures"
    )
    lines.append("")

    lines.append("## Artifact Probe")
    lines.append(
        f"- Issue count: `{probe['issue_count']}` vs baseline `{probe['baseline_issue_count']}`"
    )
    lines.append(
        f"- Issue summary: `{json.dumps(probe['issue_summary'], ensure_ascii=False, sort_keys=True)}`"
    )
    if probe["new_issue_codes"]:
        lines.append(f"- New issue codes: `{', '.join(probe['new_issue_codes'])}`")
    if probe["non_target_increases"]:
        for item in probe["non_target_increases"]:
            lines.append(
                f"- Non-target increase `{item['code']}`: `{item['baseline']}` -> `{item['current']}`"
            )
    if probe["target_drops"]:
        for item in probe["target_drops"]:
            lines.append(
                f"- Target decrease `{item['code']}`: `{item['baseline']}` -> `{item['current']}`"
            )
    lines.append("")

    lines.append("## Retrieval")
    for run_id, summary in retrieval["runs"].items():
        lines.append(
            f"- `{run_id}`: MRR `{summary['current']['mean_reciprocal_rank']}` "
            f"(delta `{summary['delta']['mean_reciprocal_rank']}`), "
            f"hit@1 `{summary['current']['hit_at_1']}` "
            f"(delta `{summary['delta']['hit_at_1']}`), "
            f"recall@3 `{summary['current']['recall_at_3']}` "
            f"(delta `{summary['delta']['recall_at_3']}`)"
        )
    lines.append("")

    lines.append("## Embedding")
    if embedding.get("evaluation_status") == "skipped_due_to_runtime":
        lines.append("- Embedding metrics skipped because the embedding command failed at runtime.")
    else:
        for run_id, summary in embedding["runs"].items():
            lines.append(
                f"- `{run_id}`: twin_hit@1 `{summary['current']['twin_hit_at_1']}` "
                f"(delta `{summary['delta']['twin_hit_at_1']}`), "
                f"mean_twin_cosine `{summary['current']['mean_twin_cosine']}` "
                f"(delta `{summary['delta']['mean_twin_cosine']}`), "
                f"twin_MRR `{summary['current']['twin_mean_reciprocal_rank']}` "
                f"(delta `{summary['delta']['twin_mean_reciprocal_rank']}`)"
            )
            diagnostics = embedding.get("diagnostics", {}).get(run_id, {})
            worst = diagnostics.get("worst_mismatches", [])
            if worst:
                lines.append(
                    f"  worst mismatches: `{diagnostics.get('mismatch_count', 0)}` docs with top-1 miss"
                )
                for item in worst:
                    current = item["current_metrics"]
                    legacy = item.get("legacy_metrics")
                    legacy_suffix = ""
                    if legacy is not None:
                        legacy_suffix = (
                            f"; legacy hit@1 `{legacy['twin_hit_at_1']}`"
                            f", legacy MRR `{legacy['twin_rr']}`"
                        )
                    lines.append(
                        f"  - `{item['doc_id']}` -> `{item.get('nearest_wrong_twin_doc_id')}` "
                        f"[{item['mismatch_class']}] hit@1 `{current['twin_hit_at_1']}` "
                        f"MRR `{current['twin_rr']}` margin `{current['separation_margin']}`{legacy_suffix}"
                    )
                    lines.append(
                        f"    preview: `{item['normalized_input']['preview']}`"
                    )
    lines.append("")

    lines.append("## Manual Sample")
    lines.append(
        f"- Status: `{'enforced' if manual['enforce_acceptance'] else 'report-only'}`"
    )
    lines.append(f"- Verdict counts: `{json.dumps(manual['verdict_counts'], sort_keys=True)}`")
    lines.append(f"- Would pass acceptance: `{manual['would_pass_acceptance']}`")
    lines.append("")

    lines.append("## Chunk Diagnostics")
    for strategy, summary in chunking.items():
        lines.append(
            f"- `{strategy}`: chunks `{summary['total_chunks']}`, "
            f"mean tokens `{summary['mean_tokens']}`, max tokens `{summary['max_tokens']}`"
        )
    lines.append("")

    lines.append("## Runtime")
    lines.append(
        f"- Stability runs: `{runtime['stability']['required_runs']}` required, "
        f"`{runtime['stability']['completed_runs']}` completed, "
        f"identical summaries `{runtime['stability']['identical_signatures']}`"
    )
    runtime_gates = runtime.get("runtime_gates", {})
    lines.append(
        f"- Embedding timeout: `{runtime_gates.get('embedding_timeout_seconds')}`s "
        f"from `{runtime_gates.get('embedding_timeout_source', 'unknown')}`"
    )
    calibration = runtime_gates.get("calibration") or {}
    if calibration:
        lines.append(
            f"- Calibration: status `{calibration.get('status', 'missing')}`, "
            f"recommendation `{calibration.get('recommendation_status', 'unknown')}`, "
            f"suggested timeout `{calibration.get('suggested_timeout_seconds')}`, "
            f"generated `{calibration.get('generated_at') or 'unknown'}`"
        )
    embedding_runtime = runtime["commands"].get("embedding", {})
    embedding_summary = embedding_runtime.get("summary", {})
    lines.append(
        f"- Embedding runtime: `{embedding_runtime.get('status', 'unknown')}` after "
        f"`{embedding_runtime.get('attempt_count', 0)}` attempt(s), "
        f"selected attempt `{embedding_runtime.get('selected_attempt', 'n/a')}`"
    )
    if embedding_summary:
        lines.append(
            f"- Embedding runtime summary: failure `{embedding_summary.get('failure_category') or 'none'}`, "
            f"wall-clock `{embedding_summary.get('wall_clock_seconds')}`, "
            f"cleanup `{embedding_summary.get('cleanup_result') or 'n/a'}`"
        )
    if embedding_runtime.get("attempts"):
        for attempt in embedding_runtime["attempts"]:
            lines.append(
                f"  - attempt `{attempt['attempt']}`: "
                f"{attempt.get('failure_category') or 'completed'} "
                f"in `{attempt.get('duration_seconds')}`s"
            )
    lines.append("")

    lines.append("## Stretch Targets")
    lines.append(
        f"- Probe issue stretch target: `{stretch['probe_issue_count']}` "
        f"(current `{probe['issue_count']}`)"
    )
    return "\n".join(lines) + "\n"


def main() -> int:
    args = parse_args()
    bundle_dir = args.bundle_dir.resolve()
    config_path = args.gate_config.resolve()
    out_dir = args.out_dir.resolve() if args.out_dir else (bundle_dir / "quality-gate")
    out_dir.mkdir(parents=True, exist_ok=True)

    config = load_json(config_path)
    metadata = load_json(bundle_dir / "metadata.json")
    generated_at = dt.datetime.now(dt.UTC).isoformat()

    baseline_dir = resolve_reference_path(config_path, config["baseline_dir"])
    regression_spec = derive_regression_spec_path(config_path)
    retrieval_benchmark = resolve_reference_path(config_path, config["retrieval_gates"]["benchmark"])
    embedding_benchmark = resolve_reference_path(config_path, config["embedding_gates"]["benchmark"])
    runtime_config = config.get("runtime_gates", {})
    embedding_timeout_seconds, embedding_timeout_source, calibration_snapshot = resolve_embedding_timeout(
        bundle_dir=bundle_dir,
        config_path=config_path,
        runtime_config=runtime_config,
        override_timeout=args.embedding_timeout_seconds,
    )
    embedding_retries = int(
        args.embedding_retries
        if args.embedding_retries is not None
        else runtime_config.get("embedding_retries", 1)
    )
    stability_runs = max(
        1,
        int(
            args.stability_runs
            if args.stability_runs is not None
            else runtime_config.get("stability_runs", 1)
        ),
    )

    iterations: list[dict[str, Any]] = []
    for run_index in range(1, stability_runs + 1):
        iteration = run_gate_iteration(
            bundle_dir=bundle_dir,
            config=config,
            retrieval_benchmark=retrieval_benchmark,
            embedding_benchmark=embedding_benchmark,
            regression_spec=regression_spec,
            embedding_timeout_seconds=embedding_timeout_seconds,
            embedding_retries=embedding_retries,
        )
        iteration["run_index"] = run_index
        iterations.append(iteration)

    selected_iteration = iterations[-1]
    audit_code = selected_iteration["audit"]["code"]
    audit_report = selected_iteration["audit"]["report"]
    audit_stderr = selected_iteration["audit"]["stderr"]
    regressions_code = selected_iteration["regressions"]["code"]
    regressions_report = selected_iteration["regressions"]["report"]
    regressions_stderr = selected_iteration["regressions"]["stderr"]
    probe_code = selected_iteration["probe"]["code"]
    probe_report = selected_iteration["probe"]["report"]
    probe_stderr = selected_iteration["probe"]["stderr"]
    retrieval_code = selected_iteration["retrieval"]["code"]
    retrieval_report = selected_iteration["retrieval"]["report"]
    retrieval_stderr = selected_iteration["retrieval"]["stderr"]
    embedding_code = selected_iteration["embedding"]["code"]
    embedding_report = selected_iteration["embedding"]["report"]
    embedding_stderr = selected_iteration["embedding"]["stderr"]

    hard_failures: list[dict[str, str]] = []

    dump_json(out_dir / "audit.json", audit_report)
    dump_json(out_dir / "regressions.json", regressions_report)
    dump_json(out_dir / "probe.json", probe_report)
    dump_json(out_dir / "retrieval.json", retrieval_report)
    dump_json(out_dir / "embedding.json", embedding_report)

    runtime_commands = {
        stage: sanitize_runtime(selected_iteration[stage]["runtime"])
        for stage in ("audit", "regressions", "probe", "retrieval", "embedding")
    }
    stability_signatures = [iteration["signature"]["sha256"] for iteration in iterations]
    completed_runs = sum(
        1
        for iteration in iterations
        if all(
            iteration[stage]["runtime"]["status"] == "pass"
            for stage in ("audit", "regressions", "probe", "retrieval", "embedding")
        )
    )
    identical_signatures = len(set(stability_signatures)) == 1
    runtime_failures = collect_runtime_gate_failures(
        runtime_commands,
        completed_runs=completed_runs,
        stability_runs=stability_runs,
        identical_signatures=identical_signatures,
    )
    gate_runtime = {
        "generated_at": generated_at,
        "gate_config_sha256": sha256_text(config_path.read_text(encoding="utf-8")),
        "bundle_metadata_sha256": sha256_text(json.dumps(metadata, sort_keys=True, ensure_ascii=False)),
        "variant_id": args.variant_id,
        "runtime_gates": {
            "embedding_timeout_seconds": embedding_timeout_seconds,
            "embedding_timeout_source": embedding_timeout_source,
            "embedding_retries": embedding_retries,
            "stability_runs": stability_runs,
            "calibration": calibration_snapshot,
        },
        "commands": runtime_commands,
        "stability": {
            "required_runs": stability_runs,
            "completed_runs": completed_runs,
            "identical_signatures": identical_signatures,
            "signatures": stability_signatures,
            "evaluation_status": (
                "blocked_by_runtime_failure"
                if any(failure["gate"].endswith("_runtime") for failure in runtime_failures)
                else ("stable" if identical_signatures and completed_runs == stability_runs else "unstable")
            ),
        },
        "iterations": [
            {
                "run_index": iteration["run_index"],
                "signature": iteration["signature"],
                "commands": {
                    stage: sanitize_runtime(iteration[stage]["runtime"])
                    for stage in ("audit", "regressions", "probe", "retrieval", "embedding")
                },
            }
            for iteration in iterations
        ],
    }
    dump_json(out_dir / "gate-runtime.json", gate_runtime)
    dump_json(
        out_dir / "embedding-runtime.json",
        {
            "generated_at": gate_runtime["generated_at"],
            "gate_config_sha256": gate_runtime["gate_config_sha256"],
            "variant_id": args.variant_id,
            "stability": gate_runtime["stability"],
            "selected": sanitize_runtime(selected_iteration["embedding"]["runtime"]),
            "iterations": [
                {
                    "run_index": iteration["run_index"],
                    "runtime": sanitize_runtime(iteration["embedding"]["runtime"]),
                }
                for iteration in iterations
            ],
        },
    )
    hard_failures.extend(runtime_failures)

    baseline_probe = load_json(baseline_dir / "probe-summary.json")
    baseline_retrieval = load_json(baseline_dir / "retrieval-summary.json")
    baseline_embedding = load_json(baseline_dir / "embedding-summary.json")
    baseline_regressions = load_json(baseline_dir / "regression-summary.json")

    allowed_audit_codes = set(config["allowed_audit_codes"])
    audit_codes = [issue["code"] for issue in audit_report.get("issues", [])]
    disallowed_audit_codes = sorted(code for code in audit_codes if code not in allowed_audit_codes)
    if disallowed_audit_codes:
        hard_failures.append(
            {
                "gate": "audit",
                "message": f"Disallowed audit codes: {', '.join(disallowed_audit_codes)}",
            }
        )
    if audit_report.get("status") == "fail" or audit_code != 0:
        hard_failures.append({"gate": "audit", "message": "Structural audit returned failure."})

    if regressions_report.get("failure_count", 0) != 0 or regressions_code != 0:
        hard_failures.append({"gate": "regressions", "message": "Regression checker reported failures."})

    current_probe_classification = classify_probe_issues(probe_report.get("issues", []), config)
    baseline_probe_classification = baseline_probe.get("classification")
    if baseline_probe_classification is None:
        baseline_probe_classification = classify_probe_issues(baseline_probe.get("issues", []), config)
    current_issue_codes = set(probe_report.get("issue_summary", {}).keys())
    baseline_issue_codes = set(baseline_probe.get("issue_codes", baseline_probe.get("issue_summary", {}).keys()))
    new_issue_codes = sorted(current_issue_codes - baseline_issue_codes)
    if new_issue_codes:
        hard_failures.append(
            {
                "gate": "probe",
                "message": f"New issue codes present: {', '.join(new_issue_codes)}",
            }
        )

    max_issue_count = int(config["probe_limits"]["max_issue_count"])
    if probe_report.get("issue_count", 0) > max_issue_count:
        hard_failures.append(
            {
                "gate": "probe",
                "message": (
                    f"Probe issue count {probe_report.get('issue_count', 0)} "
                    f"exceeds baseline cap {max_issue_count}."
                ),
            }
        )

    baseline_non_target = aggregate_non_target_counts(baseline_probe_classification)
    current_non_target = aggregate_non_target_counts(current_probe_classification)
    non_target_increases: list[dict[str, Any]] = []
    for code, current_count in sorted(current_non_target.items()):
        baseline_count = baseline_non_target.get(code, 0)
        if current_count > baseline_count:
            non_target_increases.append(
                {"code": code, "baseline": baseline_count, "current": current_count}
            )
    if non_target_increases:
        hard_failures.append(
            {
                "gate": "probe",
                "message": "Non-target issue counts increased above the frozen baseline.",
            }
        )

    baseline_target = aggregate_target_counts(baseline_probe_classification)
    current_target = aggregate_target_counts(current_probe_classification)
    target_drops = []
    for code, baseline_count in sorted(baseline_target.items()):
        current_count = current_target.get(code, 0)
        if current_count < baseline_count:
            target_drops.append({"code": code, "baseline": baseline_count, "current": current_count})
    if config["probe_limits"].get("require_target_class_decrease") and not target_drops:
        hard_failures.append(
            {
                "gate": "probe",
                "message": "No target-scope issue class decreased despite target-wave enforcement.",
            }
        )

    retrieval_runs: dict[str, Any] = {}
    for run_id in build_retrieval_run_ids(config):
        current = retrieval_report.get("summary_by_run", {}).get(run_id)
        baseline = baseline_retrieval["summary_by_run"].get(run_id)
        if current is None or baseline is None:
            hard_failures.append(
                {"gate": "retrieval", "message": f"Missing retrieval run summary: {run_id}"}
            )
            continue
        retrieval_runs[run_id] = {
            "baseline": {metric: baseline[metric] for metric in config["retrieval_gates"]["metrics"]},
            "current": {metric: current[metric] for metric in config["retrieval_gates"]["metrics"]},
            "delta": {
                metric: delta(current[metric], baseline[metric])
                for metric in config["retrieval_gates"]["metrics"]
            },
        }
        for metric in config["retrieval_gates"]["metrics"]:
            if float(current[metric]) < float(baseline[metric]):
                hard_failures.append(
                    {
                        "gate": "retrieval",
                        "message": (
                            f"{run_id} regressed on {metric}: "
                            f"{current[metric]} < {baseline[metric]}"
                        ),
                    }
                )

    embedding_runs: dict[str, Any] = {}
    embedding_diagnostics: dict[str, Any] = {}
    embedding_runtime_ok = runtime_commands["embedding"]["status"] == "pass"
    if embedding_runtime_ok:
        strict_metrics = config["embedding_gates"]["strict_no_drop_metrics"]
        tolerated_metrics = config["embedding_gates"]["tolerance_metrics"]
        for run_id in build_embedding_run_ids(config):
            current = embedding_report.get("representation_summary_by_run", {}).get(run_id)
            baseline = baseline_embedding["representation_summary_by_run"].get(run_id)
            if current is None or baseline is None:
                hard_failures.append(
                    {"gate": "embedding", "message": f"Missing embedding run summary: {run_id}"}
                )
                continue
            tracked_metrics = list(strict_metrics) + list(tolerated_metrics.keys())
            embedding_runs[run_id] = {
                "baseline": {metric: baseline[metric] for metric in tracked_metrics},
                "current": {metric: current[metric] for metric in tracked_metrics},
                "delta": {metric: delta(current[metric], baseline[metric]) for metric in tracked_metrics},
            }
            for metric in strict_metrics:
                if float(current[metric]) < float(baseline[metric]):
                    hard_failures.append(
                        {
                            "gate": "embedding",
                            "message": (
                                f"{run_id} regressed on {metric}: "
                                f"{current[metric]} < {baseline[metric]}"
                            ),
                        }
                    )
            for metric, tolerance in tolerated_metrics.items():
                if float(current[metric]) < float(baseline[metric]) - float(tolerance):
                    hard_failures.append(
                        {
                            "gate": "embedding",
                            "message": (
                                f"{run_id} regressed on {metric} beyond tolerance: "
                                f"{current[metric]} < {baseline[metric]} - {tolerance}"
                            ),
                        }
                    )
            diagnostics = embedding_report.get("representation_diagnostics_by_run", {}).get(run_id)
            if diagnostics is not None:
                embedding_diagnostics[run_id] = diagnostics

        reference_corpus = config["embedding_gates"]["reference_corpus"]
        for view in config["embedding_gates"]["views"]:
            run_id = f"{reference_corpus}::{view}"
            current = embedding_report.get("representation_summary_by_run", {}).get(run_id, {})
            for metric in ("mean_twin_cosine", "twin_hit_at_1", "twin_mean_reciprocal_rank"):
                if round(float(current.get(metric, 0.0)), 6) != 1.0:
                    hard_failures.append(
                        {
                            "gate": "embedding",
                            "message": f"{run_id} is no longer an identity reference on {metric}.",
                        }
                    )

    manual_summary = evaluate_manual_sample(config)
    if manual_summary["enforce_acceptance"] and not manual_summary["would_pass_acceptance"]:
        hard_failures.append(
            {
                "gate": "manual_sample",
                "message": "Manual sample verdicts do not satisfy the acceptance thresholds.",
            }
        )

    chunk_diagnostics = build_chunk_diagnostics(bundle_dir, metadata)

    report = {
        "bundle_dir": str(bundle_dir),
        "config": str(config_path),
        "baseline_dir": str(baseline_dir),
        "generated_at": generated_at,
        "variant_id": args.variant_id,
        "status": "fail" if hard_failures else "pass",
        "hard_gate_failures": hard_failures,
        "sections": {
            "audit": {
                "exit_code": audit_code,
                "stderr": audit_stderr,
                "status": audit_report.get("status"),
                "issue_count": audit_report.get("issue_count", 0),
                "issue_codes": audit_codes,
                "allowed_audit_codes": sorted(allowed_audit_codes),
                "disallowed_audit_codes": disallowed_audit_codes,
            },
            "regressions": {
                "exit_code": regressions_code,
                "stderr": regressions_stderr,
                "failure_count": regressions_report.get("failure_count", 0),
                "pass_count": regressions_report.get("pass_count", 0),
                "baseline_pass_count": baseline_regressions.get("pass_count", 0),
            },
            "probe": {
                "exit_code": probe_code,
                "stderr": probe_stderr,
                "issue_count": probe_report.get("issue_count", 0),
                "baseline_issue_count": baseline_probe.get("issue_count", 0),
                "issue_summary": probe_report.get("issue_summary", {}),
                "baseline_issue_summary": baseline_probe.get("issue_summary", {}),
                "new_issue_codes": new_issue_codes,
                "counts_by_group": current_probe_classification["counts_by_group"],
                "baseline_counts_by_group": baseline_probe_classification["counts_by_group"],
                "non_target_increases": non_target_increases,
                "target_drops": target_drops,
            },
            "retrieval": {
                "exit_code": retrieval_code,
                "stderr": retrieval_stderr,
                "runs": retrieval_runs,
            },
            "embedding": {
                "exit_code": embedding_code,
                "stderr": embedding_stderr,
                "runtime_ok": embedding_runtime_ok,
                "evaluation_status": "evaluated" if embedding_runtime_ok else "skipped_due_to_runtime",
                "runs": embedding_runs,
                "diagnostics": embedding_diagnostics,
            },
            "manual_sample": manual_summary,
            "chunk_diagnostics": chunk_diagnostics,
            "stretch_targets": config["stretch_targets"],
            "runtime": gate_runtime,
        },
    }

    dump_json(out_dir / "quality-gate-report.json", report)
    write_manifest(
        "quality_gate",
        out_dir / "run-manifest.json",
        build_run_manifest(
            metadata,
            config_path=config_path,
            variant_id=args.variant_id,
            generated_at=generated_at,
        )
        | {
            "artifact_status": "generated",
            "freshness": "fresh",
            "report_status": report["status"],
            "runtime_status": gate_runtime["stability"]["evaluation_status"],
        },
    )
    (out_dir / "quality-gate-report.md").write_text(
        render_markdown_report(report),
        encoding="utf-8",
    )

    return 1 if hard_failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
