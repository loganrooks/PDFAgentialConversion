#!/usr/bin/env python3
from __future__ import annotations

import argparse
import datetime as dt
import json
import math
import os
import signal
import subprocess
import sys
import time
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path("/Users/rookslog/Projects/PDFAgentialConversion")
SCRIPT_DIR = PROJECT_ROOT / "skills" / "pdf-to-structured-markdown" / "scripts"
DEFAULT_BUNDLE = PROJECT_ROOT / "generated" / "why-ethics"
DEFAULT_BENCHMARK = (
    PROJECT_ROOT
    / "skills"
    / "pdf-to-structured-markdown"
    / "references"
    / "why-ethics-retrieval-benchmark.json"
)
DEFAULT_TIMEOUT_RULE = "max(p95 * 2, p99 + 30s)"


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Empirically calibrate the local Apple embedding helper timeout by running "
            "the embedding evaluator multiple times and computing a suggested timeout."
        )
    )
    parser.add_argument("bundle_dir_arg", type=Path, nargs="?")
    parser.add_argument("benchmark_json_arg", type=Path, nargs="?")
    parser.add_argument("--bundle-dir", type=Path)
    parser.add_argument("--benchmark-json", type=Path)
    parser.add_argument("--runs", type=int, default=5)
    parser.add_argument("--helper-timeout-seconds", type=int, default=240)
    parser.add_argument("--out-dir", type=Path, help="Directory for calibration artifacts.")
    args = parser.parse_args(argv)
    args.bundle_dir = (args.bundle_dir or args.bundle_dir_arg or DEFAULT_BUNDLE).resolve()
    args.benchmark_json = (
        args.benchmark_json or args.benchmark_json_arg or DEFAULT_BENCHMARK
    ).resolve()
    return args


def percentile(values: list[float], fraction: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    position = max(0, min(len(ordered) - 1, math.ceil(len(ordered) * fraction) - 1))
    return ordered[position]


def dump_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def resolve_calibration_dir(
    bundle_dir: Path,
    *,
    report_dir: Path | str | None = None,
    project_root: Path | None = None,
) -> Path:
    if report_dir:
        candidate = Path(report_dir)
        if candidate.is_absolute():
            return candidate.resolve()
        if project_root is not None:
            return (project_root / candidate).resolve()
    return (bundle_dir.resolve() / "quality-gate" / "embedding-calibration").resolve()


def calibration_report_path(calibration_dir: Path) -> Path:
    return calibration_dir / "calibration-report.json"


def load_calibration_report(calibration_dir: Path) -> dict[str, Any] | None:
    report_path = calibration_report_path(calibration_dir)
    if not report_path.exists():
        return None
    return json.loads(report_path.read_text(encoding="utf-8"))


def selected_timeout_from_report(report: dict[str, Any] | None) -> int | None:
    if not report:
        return None
    suggested = report.get("durations", {}).get("suggested_timeout_seconds")
    try:
        value = int(suggested)
    except (TypeError, ValueError):
        return None
    return value if value > 0 else None


def terminate_process_group(process: subprocess.Popen[str]) -> str:
    try:
        if process.poll() is not None:
            return "already_exited"
        if hasattr(os, "killpg"):
            os.killpg(process.pid, signal.SIGKILL)
            return "killpg_sigkill"
        process.kill()
        return "process_kill"
    except ProcessLookupError:
        return "process_lookup_error"


def run_calibration_attempt(command: list[str], *, timeout_seconds: int) -> dict[str, Any]:
    started = time.monotonic()
    process = subprocess.Popen(
        command,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        start_new_session=True,
    )
    try:
        stdout, stderr = process.communicate(timeout=timeout_seconds)
        exit_code = process.returncode
        cleanup_result = None
        if exit_code == 0:
            failure_category = None
        else:
            stderr_lower = (stderr or "").lower()
            failure_category = (
                "timeout"
                if "timeoutexpired" in stderr_lower or "timed out" in stderr_lower
                else "nonzero_exit"
            )
    except subprocess.TimeoutExpired:
        cleanup_result = terminate_process_group(process)
        stdout, stderr = process.communicate()
        exit_code = process.returncode
        failure_category = "timeout"
    duration = round(time.monotonic() - started, 4)
    success = failure_category is None and exit_code == 0
    return {
        "success": success,
        "exit_code": exit_code,
        "duration_seconds": duration,
        "failure_category": failure_category,
        "cleanup_result": cleanup_result,
        "stdout_preview": (stdout or "").strip()[:500],
        "stderr_preview": (stderr or "").strip()[:1200],
    }


def build_calibration_report(
    *,
    bundle_dir: Path,
    benchmark_json: Path,
    runs: int,
    helper_timeout_seconds: int,
    attempts: list[dict[str, Any]],
    generated_at: str | None = None,
) -> dict[str, Any]:
    successful_durations = [item["duration_seconds"] for item in attempts if item["success"]]
    attempted_runs = len(attempts)
    completed_runs = len(successful_durations)
    failure_categories = sorted(
        {str(item["failure_category"]) for item in attempts if item.get("failure_category")}
    )
    calibration_blocked = completed_runs != runs
    p95 = percentile(successful_durations, 0.95)
    p99 = percentile(successful_durations, 0.99)
    suggested = (
        None
        if not successful_durations
        else int(math.ceil(max(p95 * 2, p99 + 30.0)))
    )
    artifact_status = "generated"
    recommendation_status = (
        "complete"
        if completed_runs == runs and suggested is not None
        else ("provisional" if suggested is not None else "unavailable")
    )
    return {
        "generated_at": generated_at or dt.datetime.now(dt.UTC).isoformat(),
        "artifact_status": artifact_status,
        "freshness": "fresh",
        "bundle_dir": str(bundle_dir),
        "benchmark_json": str(benchmark_json),
        "requested_runs": runs,
        "attempted_runs": attempted_runs,
        "completed_runs": completed_runs,
        "helper_timeout_seconds": helper_timeout_seconds,
        "status": "blocked_by_runtime_failure" if calibration_blocked else "calibrated",
        "recommendation_status": recommendation_status,
        "failure_categories": failure_categories,
        "attempts": attempts,
        "durations": {
            "min_seconds": min(successful_durations) if successful_durations else 0.0,
            "max_seconds": max(successful_durations) if successful_durations else 0.0,
            "p95_seconds": p95,
            "p99_seconds": p99,
            "suggested_timeout_seconds": suggested,
            "rule": DEFAULT_TIMEOUT_RULE,
        },
    }


def main() -> int:
    args = parse_args()
    out_dir = resolve_calibration_dir(
        args.bundle_dir,
        report_dir=args.out_dir,
    )
    out_dir.mkdir(parents=True, exist_ok=True)

    attempts: list[dict[str, Any]] = []
    for run_index in range(1, args.runs + 1):
        command = [
            sys.executable,
            str(SCRIPT_DIR / "evaluate_embedding_space.py"),
            str(args.bundle_dir),
            str(args.benchmark_json),
            "--reference-corpus",
            "rag_linearized",
            "--corpora",
            "rag_linearized,semantic_flat_clean,spatial_main_plus_supplement",
            "--views",
            "body,contextual",
            "--helper-timeout-seconds",
            str(args.helper_timeout_seconds),
        ]
        attempt = run_calibration_attempt(
            command,
            timeout_seconds=max(args.helper_timeout_seconds + 90, args.helper_timeout_seconds),
        )
        attempt["run_index"] = run_index
        attempts.append(attempt)
        if not attempt["success"]:
            break

    report = build_calibration_report(
        bundle_dir=args.bundle_dir,
        benchmark_json=args.benchmark_json,
        runs=args.runs,
        helper_timeout_seconds=args.helper_timeout_seconds,
        attempts=attempts,
    )
    dump_json(calibration_report_path(out_dir), report)
    print(json.dumps(report, indent=2, ensure_ascii=False))
    return 0 if report["status"] == "calibrated" else 1


if __name__ == "__main__":
    raise SystemExit(main())
