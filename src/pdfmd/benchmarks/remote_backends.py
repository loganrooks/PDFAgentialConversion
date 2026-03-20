#!/usr/bin/env python3
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import re
import shlex
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

from pdfmd.common.manifests import ensure_manifest_payload, write_manifest

PROJECT_ROOT = Path("/Users/rookslog/Projects/PDFAgentialConversion")
SKILL_DIR = PROJECT_ROOT / "skills" / "pdf-to-structured-markdown"
SCRIPT_DIR = SKILL_DIR / "scripts"
REFERENCES_DIR = SKILL_DIR / "references"
DEFAULT_BUNDLE_DIR = PROJECT_ROOT / "generated" / "why-ethics"
DEFAULT_BENCHMARK_JSON = REFERENCES_DIR / "why-ethics-retrieval-benchmark.json"
DEFAULT_REMOTE_BACKENDS_JSON = REFERENCES_DIR / "remote-backends.json"
DEFAULT_REQUIREMENTS = REFERENCES_DIR / "remote-embedding-requirements.txt"
DEFAULT_OUT_ROOT = PROJECT_ROOT / "generated" / "embedding-backend-comparison"
DEFAULT_REFERENCE_CORPUS = "rag_linearized"
DEFAULT_CORPORA = "rag_linearized,semantic_flat_clean,spatial_main_plus_supplement"
DEFAULT_VIEWS = "body,contextual"
DEFAULT_BATCH_SIZE = 32
DIRECTORY_HASH_BUFFER = 1024 * 1024
MODEL_SIZE_HINTS = {
    "small": 0,
    "base": 1,
    "medium": 2,
    "large": 3,
    "xl": 4,
}

# Timeout tiers for SSH subprocess calls (seconds).
# These values prevent indefinite hangs while allowing normal operations to complete.
DEFAULT_TIMEOUT_PROBE = 60       # SSH probes: nvidia-smi, uname, python probe script
DEFAULT_TIMEOUT_BOOTSTRAP = 120  # venv creation and pip install
DEFAULT_TIMEOUT_STAGE = 120      # mkdir, rsync, tar, fetch staging operations
DEFAULT_TIMEOUT_EVALUATION = 600 # model evaluation (per model, configurable via CLI)

# VRAM safety threshold (MiB): if more than this much VRAM is in use before loading
# a model, something is wrong (leaked from prior model or another process).
VRAM_SAFETY_THRESHOLD_MIB = 512


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Compare local Apple embeddings against optional remote SSH embedding backends "
            "using the same generated bundle and benchmark inputs."
        )
    )
    parser.add_argument(
        "bundle_dir",
        type=Path,
        nargs="?",
        default=DEFAULT_BUNDLE_DIR,
        help="Generated bundle directory to evaluate.",
    )
    parser.add_argument(
        "benchmark_json",
        type=Path,
        nargs="?",
        default=DEFAULT_BENCHMARK_JSON,
        help="Benchmark JSON passed through to the embedding evaluator.",
    )
    parser.add_argument(
        "--remote-backends-config",
        type=Path,
        default=DEFAULT_REMOTE_BACKENDS_JSON,
        help="JSON config describing the available remote SSH embedding backends.",
    )
    parser.add_argument(
        "--requirements",
        type=Path,
        default=DEFAULT_REQUIREMENTS,
        help="Pinned requirements file staged to the remote host for sentence-transformers runs.",
    )
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=DEFAULT_OUT_ROOT,
        help="Root directory for local comparison outputs.",
    )
    parser.add_argument(
        "--run-id",
        help="Optional stable run identifier. Defaults to an UTC timestamp.",
    )
    parser.add_argument(
        "--variant-id",
        default=os.environ.get("PDFMD_VARIANT_ID", "default"),
        help="Logical experiment variant identifier recorded in manifests.",
    )
    parser.add_argument(
        "--backend-ids",
        help="Comma-separated subset of backend ids from the config to run.",
    )
    parser.add_argument(
        "--reference-corpus",
        default=DEFAULT_REFERENCE_CORPUS,
        help="Reference corpus passed through to the evaluator.",
    )
    parser.add_argument(
        "--corpora",
        default=DEFAULT_CORPORA,
        help="Comma-separated corpora passed through to the evaluator.",
    )
    parser.add_argument(
        "--views",
        default=DEFAULT_VIEWS,
        help="Comma-separated embedding views passed through to the evaluator.",
    )
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument("--neighbor-k", type=int, default=5)
    parser.add_argument("--dense-char-limit", type=int, default=1600)
    parser.add_argument(
        "--helper-timeout-seconds",
        type=int,
        default=180,
        help="Timeout forwarded to the local Apple embedding helper.",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=DEFAULT_BATCH_SIZE,
        help="Batch size used for sentence-transformers backends.",
    )
    parser.add_argument(
        "--evaluation-timeout",
        type=int,
        default=DEFAULT_TIMEOUT_EVALUATION,
        help=(
            "Timeout in seconds for each remote model evaluation SSH command. "
            "Increase for particularly slow models or large corpora. "
            f"Default: {DEFAULT_TIMEOUT_EVALUATION}."
        ),
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Write planned artifacts and commands without executing local or remote evaluators.",
    )
    parser.add_argument(
        "--keep-remote-run",
        action="store_true",
        help="Keep the staged remote run directory even after successful fetch.",
    )
    return parser.parse_args(argv)


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def dump_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat()


def default_run_id() -> str:
    return dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def slugify_model_name(model_name: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9]+", "-", model_name).strip("-").lower()
    return slug or "model"


def sha256_file(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(DIRECTORY_HASH_BUFFER)
            if not chunk:
                break
            hasher.update(chunk)
    return hasher.hexdigest()


def sha256_directory(path: Path) -> str:
    hasher = hashlib.sha256()
    for file_path in sorted(item for item in path.rglob("*") if item.is_file()):
        relative = file_path.relative_to(path).as_posix()
        hasher.update(relative.encode("utf-8"))
        hasher.update(b"\0")
        with file_path.open("rb") as handle:
            while True:
                chunk = handle.read(DIRECTORY_HASH_BUFFER)
                if not chunk:
                    break
                hasher.update(chunk)
        hasher.update(b"\0")
    return hasher.hexdigest()


def validate_backend_entry(entry: dict[str, Any]) -> dict[str, Any]:
    required_fields = (
        "id",
        "label",
        "transport",
        "ssh_target",
        "remote_root",
        "python_bin",
        "venv_dir",
        "device",
        "bootstrap_mode",
        "models",
    )
    missing = [field for field in required_fields if field not in entry]
    if missing:
        raise ValueError(f"Remote backend entry is missing required fields: {', '.join(missing)}")
    if entry["transport"] != "ssh":
        raise ValueError(f"Unsupported transport for backend {entry['id']}: {entry['transport']}")
    if entry["bootstrap_mode"] != "ssh_venv":
        raise ValueError(
            f"Unsupported bootstrap_mode for backend {entry['id']}: {entry['bootstrap_mode']}"
        )
    if entry["device"] not in {"auto", "cuda", "cpu"}:
        raise ValueError(f"Unsupported device mode for backend {entry['id']}: {entry['device']}")
    models = entry["models"]
    if not isinstance(models, list) or not models:
        raise ValueError(f"Backend {entry['id']} must declare at least one model.")
    return {
        "id": str(entry["id"]),
        "label": str(entry["label"]),
        "transport": "ssh",
        "ssh_target": str(entry["ssh_target"]),
        "remote_root": str(entry["remote_root"]).rstrip("/"),
        "python_bin": str(entry["python_bin"]),
        "venv_dir": str(entry["venv_dir"]).strip("/"),
        "device": str(entry["device"]),
        "bootstrap_mode": "ssh_venv",
        "models": [str(item) for item in models],
    }


def load_remote_backends(path: Path, selected_ids: set[str] | None = None) -> list[dict[str, Any]]:
    payload = load_json(path)
    entries = payload.get("backends")
    if not isinstance(entries, list) or not entries:
        raise ValueError(f"No remote backends found in {path}")
    validated = [validate_backend_entry(entry) for entry in entries]
    if selected_ids:
        validated = [entry for entry in validated if entry["id"] in selected_ids]
    if not validated:
        raise ValueError("No remote backends matched the requested backend ids.")
    return validated


def build_ssh_command(ssh_target: str, remote_args: list[str]) -> list[str]:
    return ["ssh", ssh_target, *remote_args]


def build_rsync_to_remote_command(
    source: Path,
    ssh_target: str,
    remote_path: str,
    *,
    copy_dir_contents: bool = False,
) -> list[str]:
    source_arg = str(source)
    if copy_dir_contents:
        source_arg = f"{source_arg.rstrip('/')}/"
    return ["rsync", "-az", source_arg, f"{ssh_target}:{remote_path}"]


def build_rsync_from_remote_command(
    ssh_target: str,
    remote_path: str,
    local_path: Path,
) -> list[str]:
    return ["rsync", "-az", f"{ssh_target}:{remote_path}", str(local_path)]


def build_remote_artifact_tar_command(
    ssh_target: str,
    *,
    remote_backend_root: str,
    model_slug: str,
) -> list[str]:
    model_dir = f"{remote_backend_root}/models/{model_slug}"
    archive_path = f"{remote_backend_root}/artifacts-{model_slug}.tgz"
    script = (
        "set -euo pipefail\n"
        f"mkdir -p {shlex.quote(remote_backend_root)}\n"
        f"tar -czf {shlex.quote(archive_path)} -C {shlex.quote(model_dir)} .\n"
    )
    return build_ssh_command(ssh_target, ["bash", "-lc", script])


def build_remote_remove_command(ssh_target: str, remote_path: str) -> list[str]:
    script = f"set -euo pipefail\nrm -rf {shlex.quote(remote_path)}\n"
    return build_ssh_command(ssh_target, ["bash", "-lc", script])


def build_remote_mkdir_command(ssh_target: str, *paths: str) -> list[str]:
    quoted_paths = " ".join(shlex.quote(path) for path in paths)
    script = f"set -euo pipefail\nmkdir -p {quoted_paths}\n"
    return build_ssh_command(ssh_target, ["bash", "-lc", script])


def build_remote_probe_command(ssh_target: str, python_bin: str) -> list[str]:
    script = f"""set -euo pipefail
{shlex.quote(python_bin)} - <<'PY'
import importlib
import json
import os
import platform
import subprocess
import sys

def probe_module(name):
    try:
        module = importlib.import_module(name)
    except Exception as exc:
        return {{"installed": False, "error": f"{{type(exc).__name__}}: {{exc}}"}}
    return {{"installed": True, "version": getattr(module, "__version__", None)}}

torch_probe = probe_module("torch")
torch_cuda = None
if torch_probe["installed"]:
    try:
        torch = importlib.import_module("torch")
        cuda = getattr(torch, "cuda", None)
        cuda_available = bool(cuda and cuda.is_available())
        device_count = int(cuda.device_count()) if cuda_available and hasattr(cuda, "device_count") else 0
        device_names = []
        if cuda_available and hasattr(cuda, "get_device_name"):
            for index in range(device_count):
                try:
                    device_names.append(str(cuda.get_device_name(index)))
                except Exception:
                    device_names.append(f"cuda:{{index}}")
        torch_cuda = {{
            "available": cuda_available,
            "device_count": device_count,
            "device_names": device_names,
            "cuda_version": getattr(getattr(torch, "version", None), "cuda", None),
        }}
    except Exception as exc:
        torch_cuda = {{"error": f"{{type(exc).__name__}}: {{exc}}"}}

try:
    nvidia = subprocess.run(
        ["nvidia-smi", "--query-gpu=name,memory.total,driver_version", "--format=csv,noheader"],
        capture_output=True,
        text=True,
        check=False,
    )
    nvidia_payload = {{
        "available": nvidia.returncode == 0,
        "exit_code": nvidia.returncode,
        "stdout": nvidia.stdout.strip(),
        "stderr": nvidia.stderr.strip(),
    }}
except FileNotFoundError:
    nvidia_payload = {{
        "available": False,
        "exit_code": None,
        "stdout": "",
        "stderr": "nvidia-smi not found",
    }}

payload = {{
    "probed_at": __import__("datetime").datetime.now(__import__("datetime").timezone.utc).isoformat(),
    "platform": {{
        "system": platform.system(),
        "release": platform.release(),
        "machine": platform.machine(),
        "python_version": sys.version,
        "python_executable": sys.executable,
        "uname": platform.uname()._asdict(),
    }},
    "environment": {{
        "CUDA_VISIBLE_DEVICES": os.environ.get("CUDA_VISIBLE_DEVICES"),
    }},
    "nvidia_smi": nvidia_payload,
    "modules": {{
        "torch": torch_probe,
        "sentence_transformers": probe_module("sentence_transformers"),
        "transformers": probe_module("transformers"),
        "numpy": probe_module("numpy"),
    }},
    "torch_cuda": torch_cuda,
}}
print(json.dumps(payload))
PY"""
    return build_ssh_command(ssh_target, ["bash", "-lc", script])


def build_remote_bootstrap_command(
    backend: dict[str, Any],
    *,
    remote_backend_root: str,
) -> list[str]:
    venv_dir = f"{remote_backend_root}/{backend['venv_dir']}"
    script = f"""set -euo pipefail
ROOT={shlex.quote(remote_backend_root)}
PYTHON_BIN={shlex.quote(backend["python_bin"])}
VENV_DIR={shlex.quote(venv_dir)}
REQ_FILE="$ROOT/requirements.txt"
CREATED_VENV=0
INSTALLED_REQUIREMENTS=0
TORCH_PREINSTALLED=0
REQ_USED="$REQ_FILE"

mkdir -p "$ROOT/models"
if [ ! -d "$VENV_DIR" ]; then
  "$PYTHON_BIN" -m venv --system-site-packages "$VENV_DIR"
  CREATED_VENV=1
fi

VENV_PY="$VENV_DIR/bin/python"
VENV_PIP="$VENV_DIR/bin/pip"

if "$VENV_PY" -c "import torch" >/dev/null 2>&1; then
  TORCH_PREINSTALLED=1
fi

if ! "$VENV_PY" -c "import sentence_transformers, transformers, numpy" >/dev/null 2>&1; then
  if [ "$TORCH_PREINSTALLED" -eq 1 ]; then
    FILTERED_REQ="$ROOT/requirements.no-torch.txt"
    grep -vi '^torch==' "$REQ_FILE" > "$FILTERED_REQ"
    REQ_USED="$FILTERED_REQ"
    "$VENV_PIP" install -r "$FILTERED_REQ"
  else
    "$VENV_PIP" install -r "$REQ_FILE"
  fi
  INSTALLED_REQUIREMENTS=1
fi

"$VENV_PY" - <<'PY'
import json
import os
import sys

payload = {{
    "created_venv": os.environ.get("CREATED_VENV") == "1",
    "installed_requirements": os.environ.get("INSTALLED_REQUIREMENTS") == "1",
    "torch_preinstalled": os.environ.get("TORCH_PREINSTALLED") == "1",
    "requirements_used": os.environ.get("REQ_USED"),
    "venv_python": sys.executable,
}}
print(json.dumps(payload))
PY"""
    env_script = (
        f"export CREATED_VENV=\"$CREATED_VENV\"\n"
        f"export INSTALLED_REQUIREMENTS=\"$INSTALLED_REQUIREMENTS\"\n"
        f"export TORCH_PREINSTALLED=\"$TORCH_PREINSTALLED\"\n"
        f"export REQ_USED=\"$REQ_USED\"\n"
    )
    script = script.replace(
        "\"$VENV_PY\" - <<'PY'",
        env_script + "\"$VENV_PY\" - <<'PY'",
    )
    return build_ssh_command(backend["ssh_target"], ["bash", "-lc", script])


def build_remote_evaluation_command(
    backend: dict[str, Any],
    *,
    remote_backend_root: str,
    model_name: str,
    model_slug: str,
    args: argparse.Namespace,
) -> list[str]:
    evaluator = f"{remote_backend_root}/evaluate_embedding_space.py"
    bundle_dir = f"{remote_backend_root}/bundle"
    benchmark_json = f"{remote_backend_root}/benchmark.json"
    model_dir = f"{remote_backend_root}/models/{model_slug}"
    venv_python = f"{remote_backend_root}/{backend['venv_dir']}/bin/python"
    command = [
        shlex.quote(venv_python),
        shlex.quote(evaluator),
        shlex.quote(bundle_dir),
        shlex.quote(benchmark_json),
        "--reference-corpus",
        shlex.quote(args.reference_corpus),
        "--corpora",
        shlex.quote(args.corpora),
        "--views",
        shlex.quote(args.views),
        "--top-k",
        str(args.top_k),
        "--neighbor-k",
        str(args.neighbor_k),
        "--dense-char-limit",
        str(args.dense_char_limit),
        "--embedding-backend",
        "sentence_transformers",
        "--model-name",
        shlex.quote(model_name),
        "--device",
        shlex.quote(backend["device"]),
        "--batch-size",
        str(args.batch_size),
        ">",
        shlex.quote(f"{model_dir}/evaluation.json"),
    ]
    script = (
        "set -euo pipefail\n"
        f"mkdir -p {shlex.quote(model_dir)}\n"
        + " ".join(command)
        + "\n"
    )
    return build_ssh_command(backend["ssh_target"], ["bash", "-lc", script])


def build_vram_probe_command(ssh_target: str) -> list[str]:
    """Build an SSH command to query GPU VRAM usage via nvidia-smi."""
    return build_ssh_command(
        ssh_target,
        [
            "nvidia-smi",
            "--query-gpu=memory.used,memory.total,memory.free",
            "--format=csv,noheader,nounits",
        ],
    )


def parse_vram_probe(runtime: dict[str, Any]) -> dict[str, Any]:
    """Parse the output of a build_vram_probe_command run_command result.

    Returns a dict with 'available' key. On success:
        {"available": True, "used_mib": int, "total_mib": int, "free_mib": int,
         "utilization_pct": float}
    On failure:
        {"available": False, "error": str}
    """
    if not runtime.get("success"):
        status = runtime.get("status", "unknown")
        stderr = runtime.get("stderr", "")
        return {
            "available": False,
            "error": f"nvidia-smi command {status}: {stderr}".strip(),
        }
    stdout = str(runtime.get("stdout") or "").strip()
    if not stdout:
        return {"available": False, "error": "nvidia-smi returned empty output"}
    try:
        # nvidia-smi CSV output: "used_mib, total_mib, free_mib" (one GPU per line;
        # we read the first line for single-GPU hosts like dionysus GTX 1080 Ti)
        first_line = stdout.splitlines()[0].strip()
        parts = [p.strip() for p in first_line.split(",")]
        if len(parts) != 3:
            return {
                "available": False,
                "error": f"Unexpected nvidia-smi output format: {first_line!r}",
            }
        used_mib = int(parts[0])
        total_mib = int(parts[1])
        free_mib = int(parts[2])
        utilization_pct = round(used_mib / total_mib * 100, 2) if total_mib > 0 else 0.0
        return {
            "available": True,
            "used_mib": used_mib,
            "total_mib": total_mib,
            "free_mib": free_mib,
            "utilization_pct": utilization_pct,
        }
    except (ValueError, IndexError) as exc:
        return {
            "available": False,
            "error": f"Failed to parse nvidia-smi output: {exc}",
        }


def run_command(
    command: list[str],
    *,
    dry_run: bool = False,
    cwd: Path | None = None,
    timeout: int | None = None,
) -> dict[str, Any]:
    runtime: dict[str, Any] = {
        "command": command,
        "cwd": str(cwd) if cwd else None,
        "started_at": utc_now(),
        "success": False,
        "status": "dry_run" if dry_run else "pending",
        "exit_code": None,
        "stdout": "",
        "stderr": "",
        "wall_clock_seconds": 0.0,
    }
    if dry_run:
        return runtime
    started = time.monotonic()
    try:
        completed = subprocess.run(
            command,
            text=True,
            capture_output=True,
            check=False,
            cwd=str(cwd) if cwd else None,
            timeout=timeout,
        )
        runtime.update(
            {
                "success": completed.returncode == 0,
                "status": "success" if completed.returncode == 0 else "failure",
                "exit_code": completed.returncode,
                "stdout": completed.stdout,
                "stderr": completed.stderr,
                "wall_clock_seconds": round(time.monotonic() - started, 4),
            }
        )
    except subprocess.TimeoutExpired:
        runtime.update(
            {
                "success": False,
                "status": "timeout",
                "exit_code": None,
                "stdout": "",
                "stderr": f"Command timed out after {timeout}s",
                "wall_clock_seconds": round(time.monotonic() - started, 4),
            }
        )
    return runtime


def parse_json_stdout(runtime: dict[str, Any], *, label: str) -> dict[str, Any]:
    if runtime["status"] == "dry_run":
        return {"status": "dry_run", "label": label, "payload": None}
    if runtime["status"] == "timeout":
        return {"status": "timeout", "label": label, "payload": None, "runtime": runtime}
    if not runtime["success"]:
        return {"status": "failure", "label": label, "payload": None, "runtime": runtime}
    stdout = str(runtime["stdout"] or "").strip()
    if not stdout:
        return {"status": "failure", "label": label, "payload": None, "runtime": runtime}
    try:
        payload = json.loads(stdout)
    except json.JSONDecodeError:
        return {"status": "failure", "label": label, "payload": None, "runtime": runtime}
    return {"status": "success", "label": label, "payload": payload, "runtime": runtime}


def aggregate_embedding_metrics(report: dict[str, Any]) -> dict[str, Any]:
    reference_corpus = report.get("reference_corpus")
    summary = report.get("representation_summary_by_run", {})
    aggregate_runs = []
    for run_id, metrics in summary.items():
        corpus_name, _, view = run_id.partition("::")
        if corpus_name == reference_corpus:
            continue
        aggregate_runs.append((run_id, metrics))
    if not aggregate_runs:
        return {
            "run_count": 0,
            "mean_twin_cosine": None,
            "twin_hit_at_1": None,
            "twin_mean_reciprocal_rank": None,
            "runs": {},
        }
    return {
        "run_count": len(aggregate_runs),
        "mean_twin_cosine": round(
            sum(item[1]["mean_twin_cosine"] for item in aggregate_runs) / len(aggregate_runs),
            4,
        ),
        "twin_hit_at_1": round(
            sum(item[1]["twin_hit_at_1"] for item in aggregate_runs) / len(aggregate_runs),
            4,
        ),
        "twin_mean_reciprocal_rank": round(
            sum(item[1]["twin_mean_reciprocal_rank"] for item in aggregate_runs) / len(aggregate_runs),
            4,
        ),
        "runs": {run_id: metrics for run_id, metrics in aggregate_runs},
    }


def metric_deltas(current: dict[str, Any], baseline: dict[str, Any] | None) -> dict[str, Any] | None:
    if not baseline or baseline.get("run_count", 0) == 0:
        return None
    return {
        "mean_twin_cosine": round(
            float(current["mean_twin_cosine"]) - float(baseline["mean_twin_cosine"]),
            4,
        ),
        "twin_hit_at_1": round(
            float(current["twin_hit_at_1"]) - float(baseline["twin_hit_at_1"]),
            4,
        ),
        "twin_mean_reciprocal_rank": round(
            float(current["twin_mean_reciprocal_rank"]) - float(baseline["twin_mean_reciprocal_rank"]),
            4,
        ),
    }


def model_size_rank(model_name: str) -> int:
    lowered = model_name.lower()
    for hint, rank in MODEL_SIZE_HINTS.items():
        if hint in lowered:
            return rank
    return 99


def choose_winner(results: list[dict[str, Any]], baseline_manifest: dict[str, Any] | None) -> dict[str, Any]:
    eligible: list[dict[str, Any]] = []
    for result in results:
        if not result.get("success"):
            continue
        if baseline_manifest is not None and not result.get("manifest_hash_match", False):
            continue
        eligible.append(result)
    if not eligible:
        return {"winner": None, "reason": "No successful backend/model runs matched the baseline hashes."}

    def sort_key(item: dict[str, Any]) -> tuple[float, float, float]:
        metrics = item["aggregate_metrics"]
        return (
            float(metrics["twin_hit_at_1"]),
            float(metrics["twin_mean_reciprocal_rank"]),
            float(metrics["mean_twin_cosine"]),
        )

    eligible.sort(key=sort_key, reverse=True)
    winner = eligible[0]
    if len(eligible) > 1:
        candidate = eligible[1]
        winner_metrics = winner["aggregate_metrics"]
        candidate_metrics = candidate["aggregate_metrics"]
        if (
            abs(float(winner_metrics["mean_twin_cosine"]) - float(candidate_metrics["mean_twin_cosine"])) < 0.001
            and abs(float(winner_metrics["twin_hit_at_1"]) - float(candidate_metrics["twin_hit_at_1"])) < 0.01
            and abs(
                float(winner_metrics["twin_mean_reciprocal_rank"])
                - float(candidate_metrics["twin_mean_reciprocal_rank"])
            )
            < 0.01
        ):
            faster = min(
                (winner, candidate),
                key=lambda item: float(item.get("runtime_seconds") or float("inf")),
            )
            if faster.get("runtime_seconds") != winner.get("runtime_seconds"):
                winner = faster
            elif model_size_rank(candidate["model_name"]) < model_size_rank(winner["model_name"]):
                winner = candidate
    return {
        "winner": {
            "backend_id": winner["backend_id"],
            "model_name": winner["model_name"],
            "status": winner.get("status", "success"),
            "runtime_seconds": winner.get("runtime_seconds"),
            "aggregate_metrics": winner["aggregate_metrics"],
        },
        "reason": (
            "Selected by gated aggregate metrics; ties within threshold were broken by runtime "
            "and then by model size."
        ),
    }


def build_run_manifest(
    *,
    bundle_dir: Path,
    bundle_sha256: str,
    benchmark_json: Path,
    benchmark_sha256: str,
    evaluator_script: Path,
    backend_id: str,
    backend_label: str,
    model_name: str | None,
    resolved_device: str | None,
    variant_id: str,
    ssh_target: str | None,
) -> dict[str, Any]:
    return {
        "generated_at": utc_now(),
        "variant_id": variant_id,
        "bundle": {
            "path": str(bundle_dir.resolve()),
            "sha256": bundle_sha256,
        },
        "benchmark": {
            "path": str(benchmark_json.resolve()),
            "sha256": benchmark_sha256,
        },
        "evaluator": {
            "path": str(evaluator_script.resolve()),
            "sha256": sha256_file(evaluator_script),
        },
        "backend": {
            "id": backend_id,
            "label": backend_label,
            "model_name": model_name,
            "resolved_device": resolved_device,
            "ssh_target": ssh_target,
        },
    }


def extract_remote_backend_metadata(report: dict[str, Any]) -> tuple[str | None, float | None]:
    backend = report.get("embedding_backend", {})
    runtime = backend.get("runtime", {})
    device = backend.get("device_resolved")
    runtime_seconds = runtime.get("duration_seconds")
    return device, runtime_seconds


def build_local_baseline_command(
    args: argparse.Namespace,
    evaluator_script: Path,
) -> list[str]:
    return [
        sys.executable,
        str(evaluator_script),
        str(args.bundle_dir.resolve()),
        str(args.benchmark_json.resolve()),
        "--reference-corpus",
        args.reference_corpus,
        "--corpora",
        args.corpora,
        "--views",
        args.views,
        "--top-k",
        str(args.top_k),
        "--neighbor-k",
        str(args.neighbor_k),
        "--dense-char-limit",
        str(args.dense_char_limit),
        "--embedding-backend",
        "apple_nl",
        "--helper-timeout-seconds",
        str(args.helper_timeout_seconds),
    ]


def sync_json_to_remote(
    *,
    payload: dict[str, Any],
    local_temp_dir: Path,
    ssh_target: str,
    remote_path: str,
    dry_run: bool,
    timeout: int | None = DEFAULT_TIMEOUT_STAGE,
) -> dict[str, Any]:
    local_path = local_temp_dir / Path(remote_path).name
    dump_json(local_path, payload)
    return run_command(
        build_rsync_to_remote_command(local_path, ssh_target, remote_path),
        dry_run=dry_run,
        timeout=timeout,
    )


def extract_tarball(archive_path: Path, target_dir: Path, *, dry_run: bool) -> dict[str, Any]:
    if dry_run:
        return {
            "command": ["tar", "-xzf", str(archive_path), "-C", str(target_dir)],
            "status": "dry_run",
            "success": False,
            "stdout": "",
            "stderr": "",
            "wall_clock_seconds": 0.0,
            "exit_code": None,
            "started_at": utc_now(),
            "cwd": None,
        }
    target_dir.mkdir(parents=True, exist_ok=True)
    return run_command(
        ["tar", "-xzf", str(archive_path), "-C", str(target_dir)],
        timeout=DEFAULT_TIMEOUT_STAGE,
    )


def render_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# Embedding Backend Comparison",
        "",
        f"- Generated: `{report['generated_at']}`",
        f"- Run id: `{report['run_id']}`",
        f"- Variant id: `{report['variant_id']}`",
        f"- Dry run: `{report['dry_run']}`",
        f"- Bundle hash: `{report['bundle']['sha256']}`",
        f"- Benchmark hash: `{report['benchmark']['sha256']}`",
        "",
        "## Summary",
        "",
        "| Backend | Model | Status | Device | Runtime (s) | Mean Cosine | Hit@1 | MRR | Delta Cosine | Delta Hit@1 | Delta MRR |",
        "| --- | --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for result in report["results"]:
        aggregate = result.get("aggregate_metrics", {})
        deltas = result.get("deltas_vs_baseline") or {}
        lines.append(
            f"| `{result['backend_id']}` | `{result['model_name'] or 'apple_nl'}` | `{result['status']}` | "
            f"`{result.get('device_used') or '-'}` | `{result.get('runtime_seconds') if result.get('runtime_seconds') is not None else '-'}` | "
            f"`{aggregate.get('mean_twin_cosine', '-')}` | `{aggregate.get('twin_hit_at_1', '-')}` | "
            f"`{aggregate.get('twin_mean_reciprocal_rank', '-')}` | "
            f"`{deltas.get('mean_twin_cosine', '-')}` | `{deltas.get('twin_hit_at_1', '-')}` | "
            f"`{deltas.get('twin_mean_reciprocal_rank', '-')}` |"
        )
    lines.extend(["", "## Decision", ""])
    selection = report.get("selection", {})
    winner = selection.get("winner")
    if winner:
        lines.append(
            f"- Selected backend/model: `{winner['backend_id']} / {winner['model_name']}` "
            f"on `{winner.get('runtime_seconds')}` seconds."
        )
    else:
        lines.append("- No eligible winner.")
    lines.append(f"- Reason: {selection.get('reason')}")
    lines.append("")
    for result in report["results"]:
        lines.append(f"## {result['backend_id']} / {result['model_name'] or 'apple_nl'}")
        lines.append("")
        lines.append(f"- Status: `{result['status']}`")
        if result.get("failure_stage"):
            lines.append(f"- Failure stage: `{result['failure_stage']}`")
        if result.get("manifest_hash_match") is not None:
            lines.append(f"- Manifest hash match: `{result['manifest_hash_match']}`")
        lines.append(f"- Artifacts: `{result['artifacts_dir']}`")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def plan_remote_paths(backend: dict[str, Any], run_id: str, model_slug: str) -> dict[str, str]:
    remote_backend_root = f"{backend['remote_root']}/{run_id}/{backend['id']}"
    return {
        "remote_backend_root": remote_backend_root,
        "remote_bundle_dir": f"{remote_backend_root}/bundle",
        "remote_models_root": f"{remote_backend_root}/models",
        "remote_model_dir": f"{remote_backend_root}/models/{model_slug}",
        "remote_archive_path": f"{remote_backend_root}/artifacts-{model_slug}.tgz",
    }


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    evaluator_script = SCRIPT_DIR / "evaluate_embedding_space.py"
    selected_ids = (
        {item.strip() for item in args.backend_ids.split(",") if item.strip()}
        if args.backend_ids
        else None
    )
    backends = load_remote_backends(args.remote_backends_config.resolve(), selected_ids)
    run_id = args.run_id or default_run_id()
    comparison_root = args.out_dir.resolve() / run_id
    comparison_root.mkdir(parents=True, exist_ok=True)

    bundle_dir = args.bundle_dir.resolve()
    benchmark_json = args.benchmark_json.resolve()
    bundle_sha = sha256_directory(bundle_dir)
    benchmark_sha = sha256_file(benchmark_json)
    report: dict[str, Any] = {
        "generated_at": utc_now(),
        "run_id": run_id,
        "variant_id": args.variant_id,
        "dry_run": args.dry_run,
        "bundle": {
            "path": str(bundle_dir),
            "sha256": bundle_sha,
        },
        "benchmark": {
            "path": str(benchmark_json),
            "sha256": benchmark_sha,
        },
        "results": [],
    }

    local_baseline_dir = comparison_root / "local-apple"
    local_baseline_dir.mkdir(parents=True, exist_ok=True)
    local_baseline_command = build_local_baseline_command(args, evaluator_script)
    local_baseline_manifest = ensure_manifest_payload(
        "backend_comparison",
        build_run_manifest(
            bundle_dir=bundle_dir,
            bundle_sha256=bundle_sha,
            benchmark_json=benchmark_json,
            benchmark_sha256=benchmark_sha,
            evaluator_script=evaluator_script,
            backend_id="local-apple",
            backend_label="Local Apple NaturalLanguage baseline",
            model_name=None,
            resolved_device="apple_nl" if not args.dry_run else None,
            variant_id=args.variant_id,
            ssh_target=None,
        ),
    )
    write_manifest(
        "backend_comparison",
        local_baseline_dir / "run-manifest.json",
        local_baseline_manifest | {"artifact_status": "generated", "freshness": "fresh"},
    )

    baseline_result: dict[str, Any]
    if args.dry_run:
        dump_json(
            local_baseline_dir / "runtime.json",
            {"status": "dry_run", "command": local_baseline_command},
        )
        baseline_result = {
            "backend_id": "local-apple",
            "model_name": None,
            "status": "dry_run",
            "success": False,
            "failure_stage": None,
            "device_used": None,
            "runtime_seconds": None,
            "aggregate_metrics": {
                "run_count": 0,
                "mean_twin_cosine": None,
                "twin_hit_at_1": None,
                "twin_mean_reciprocal_rank": None,
                "runs": {},
            },
            "deltas_vs_baseline": None,
            "manifest_hash_match": True,
            "artifacts_dir": str(local_baseline_dir),
            "commands": {"evaluate": local_baseline_command},
        }
    else:
        baseline_runtime = run_command(local_baseline_command)
        dump_json(local_baseline_dir / "runtime.json", baseline_runtime)
        if baseline_runtime["success"]:
            try:
                baseline_payload = json.loads(str(baseline_runtime["stdout"]).strip())
            except json.JSONDecodeError:
                baseline_payload = None
        else:
            baseline_payload = None
        if baseline_payload is not None:
            dump_json(local_baseline_dir / "evaluation.json", baseline_payload)
            baseline_device, baseline_seconds = extract_remote_backend_metadata(baseline_payload)
            local_baseline_manifest["backend"]["resolved_device"] = baseline_device
            write_manifest(
                "backend_comparison",
                local_baseline_dir / "run-manifest.json",
                local_baseline_manifest | {"artifact_status": "failed", "freshness": "fresh"},
            )
            baseline_result = {
                "backend_id": "local-apple",
                "model_name": None,
                "status": "success",
                "success": True,
                "failure_stage": None,
                "device_used": baseline_device,
                "runtime_seconds": baseline_seconds,
                "aggregate_metrics": aggregate_embedding_metrics(baseline_payload),
                "deltas_vs_baseline": {
                    "mean_twin_cosine": 0.0,
                    "twin_hit_at_1": 0.0,
                    "twin_mean_reciprocal_rank": 0.0,
                },
                "manifest_hash_match": True,
                "artifacts_dir": str(local_baseline_dir),
                "commands": {"evaluate": local_baseline_command},
            }
        else:
            baseline_result = {
                "backend_id": "local-apple",
                "model_name": None,
                "status": "failure",
                "success": False,
                "failure_stage": "local_baseline",
                "device_used": None,
                "runtime_seconds": None,
                "aggregate_metrics": {
                    "run_count": 0,
                    "mean_twin_cosine": None,
                    "twin_hit_at_1": None,
                    "twin_mean_reciprocal_rank": None,
                    "runs": {},
                },
                "deltas_vs_baseline": None,
                "manifest_hash_match": True,
                "artifacts_dir": str(local_baseline_dir),
                "commands": {"evaluate": local_baseline_command},
            }
    report["results"].append(baseline_result)
    baseline_metrics = baseline_result["aggregate_metrics"] if baseline_result["success"] else None

    for backend in backends:
        backend_local_root = comparison_root / backend["id"]
        backend_local_root.mkdir(parents=True, exist_ok=True)
        backend_failure_stage: str | None = None
        backend_shared_runtime: dict[str, Any] = {}
        remote_probe_payload: dict[str, Any] | None = None
        bootstrap_payload: dict[str, Any] | None = None
        post_bootstrap_probe: dict[str, Any] | None = None
        remote_backend_root = f"{backend['remote_root']}/{run_id}/{backend['id']}"

        stage_commands = {
            "mkdir": build_remote_mkdir_command(
                backend["ssh_target"],
                remote_backend_root,
                f"{remote_backend_root}/bundle",
                f"{remote_backend_root}/models",
            ),
            "bundle": build_rsync_to_remote_command(
                bundle_dir,
                backend["ssh_target"],
                f"{remote_backend_root}/bundle/",
                copy_dir_contents=True,
            ),
            "benchmark": build_rsync_to_remote_command(
                benchmark_json,
                backend["ssh_target"],
                f"{remote_backend_root}/benchmark.json",
            ),
            "evaluator": build_rsync_to_remote_command(
                evaluator_script,
                backend["ssh_target"],
                f"{remote_backend_root}/evaluate_embedding_space.py",
            ),
            "requirements": build_rsync_to_remote_command(
                args.requirements.resolve(),
                backend["ssh_target"],
                f"{remote_backend_root}/requirements.txt",
            ),
        }

        for stage_name in ("mkdir", "bundle", "benchmark", "evaluator", "requirements"):
            runtime = run_command(
                stage_commands[stage_name],
                dry_run=args.dry_run,
                timeout=DEFAULT_TIMEOUT_STAGE,
            )
            backend_shared_runtime[f"stage_{stage_name}"] = runtime
            if not args.dry_run and not runtime["success"]:
                backend_failure_stage = f"stage_{stage_name}"
                break

        if backend_failure_stage is None:
            probe_runtime = run_command(
                build_remote_probe_command(backend["ssh_target"], backend["python_bin"]),
                dry_run=args.dry_run,
                timeout=DEFAULT_TIMEOUT_PROBE,
            )
            backend_shared_runtime["pre_probe"] = probe_runtime
            probe_result = parse_json_stdout(probe_runtime, label="pre_probe")
            remote_probe_payload = probe_result["payload"]
            if not args.dry_run and remote_probe_payload is None:
                backend_failure_stage = "pre_probe"

        if backend_failure_stage is None:
            bootstrap_runtime = run_command(
                build_remote_bootstrap_command(backend, remote_backend_root=remote_backend_root),
                dry_run=args.dry_run,
                timeout=DEFAULT_TIMEOUT_BOOTSTRAP,
            )
            backend_shared_runtime["bootstrap"] = bootstrap_runtime
            bootstrap_result = parse_json_stdout(bootstrap_runtime, label="bootstrap")
            bootstrap_payload = bootstrap_result["payload"]
            if not args.dry_run and bootstrap_payload is None:
                backend_failure_stage = "bootstrap"

        if backend_failure_stage is None:
            post_probe_runtime = run_command(
                build_remote_probe_command(
                    backend["ssh_target"],
                    f"{remote_backend_root}/{backend['venv_dir']}/bin/python",
                ),
                dry_run=args.dry_run,
                timeout=DEFAULT_TIMEOUT_PROBE,
            )
            backend_shared_runtime["post_probe"] = post_probe_runtime
            post_probe_result = parse_json_stdout(post_probe_runtime, label="post_probe")
            post_bootstrap_probe = post_probe_result["payload"]
            if not args.dry_run and post_bootstrap_probe is None:
                backend_failure_stage = "post_probe"

        for model_name in backend["models"]:
            model_slug = slugify_model_name(model_name)
            model_local_dir = backend_local_root / model_slug
            model_local_dir.mkdir(parents=True, exist_ok=True)
            model_paths = plan_remote_paths(backend, run_id, model_slug)
            commands = {
                "probe": build_remote_probe_command(backend["ssh_target"], backend["python_bin"]),
                "bootstrap": build_remote_bootstrap_command(
                    backend,
                    remote_backend_root=remote_backend_root,
                ),
                "evaluate": build_remote_evaluation_command(
                    backend,
                    remote_backend_root=remote_backend_root,
                    model_name=model_name,
                    model_slug=model_slug,
                    args=args,
                ),
                "tar": build_remote_artifact_tar_command(
                    backend["ssh_target"],
                    remote_backend_root=remote_backend_root,
                    model_slug=model_slug,
                ),
                "fetch": build_rsync_from_remote_command(
                    backend["ssh_target"],
                    model_paths["remote_archive_path"],
                    model_local_dir / "artifacts.tgz",
                ),
                "cleanup": build_remote_remove_command(backend["ssh_target"], remote_backend_root),
            }

            remote_environment_payload = {
                "generated_at": utc_now(),
                "backend_id": backend["id"],
                "model_name": model_name,
                "pre_bootstrap": remote_probe_payload,
                "post_bootstrap": post_bootstrap_probe,
                "bootstrap": bootstrap_payload,
            }
            dump_json(model_local_dir / "remote-environment.json", remote_environment_payload)

            failure_stage = backend_failure_stage
            evaluation_report: dict[str, Any] | None = None
            evaluation_runtime: dict[str, Any] | None = None
            manifest_hash_match: bool | None = None
            resolved_device: str | None = None
            runtime_seconds: float | None = None

            local_sync_dir = model_local_dir / "_sync"
            local_sync_dir.mkdir(parents=True, exist_ok=True)

            if backend_failure_stage is None:
                # INFRA-03: VRAM probe before each model evaluation to detect leaked VRAM
                # from prior model processes. Each evaluation is a separate SSH subprocess;
                # VRAM should be free after process exit. This guard catches failures.
                if not args.dry_run:
                    vram_probe_runtime = run_command(
                        build_vram_probe_command(backend["ssh_target"]),
                        timeout=DEFAULT_TIMEOUT_PROBE,
                    )
                    vram_state = parse_vram_probe(vram_probe_runtime)
                    backend_shared_runtime[f"model_{model_slug}_vram_pre"] = vram_state
                    dump_json(model_local_dir / "vram-pre.json", vram_state)
                    if vram_state.get("available") and vram_state["used_mib"] > VRAM_SAFETY_THRESHOLD_MIB:
                        # VRAM is dirty beyond the safety threshold -- skip this model.
                        # Do NOT abort the entire backend; later models may succeed if
                        # this is transient (another process, not a leaked evaluator).
                        failure_stage = "vram_dirty"
                        dump_json(
                            model_local_dir / "runtime.json",
                            {
                                "status": "skipped",
                                "failure_stage": "vram_dirty",
                                "vram_pre": vram_state,
                            },
                        )
                        result = {
                            "backend_id": backend["id"],
                            "backend_label": backend["label"],
                            "model_name": model_name,
                            "model_slug": model_slug,
                            "status": "failure",
                            "success": False,
                            "failure_stage": failure_stage,
                            "device_used": None,
                            "runtime_seconds": None,
                            "aggregate_metrics": {
                                "run_count": 0,
                                "mean_twin_cosine": None,
                                "twin_hit_at_1": None,
                                "twin_mean_reciprocal_rank": None,
                                "runs": {},
                            },
                            "deltas_vs_baseline": None,
                            "manifest_hash_match": None,
                            "artifacts_dir": str(model_local_dir),
                            "commands": commands,
                        }
                        report["results"].append(result)
                        continue

                mkdir_runtime = run_command(
                    build_remote_mkdir_command(backend["ssh_target"], model_paths["remote_model_dir"]),
                    dry_run=args.dry_run,
                    timeout=DEFAULT_TIMEOUT_STAGE,
                )
                backend_shared_runtime[f"model_{model_slug}_mkdir"] = mkdir_runtime
                sync_env_runtime = sync_json_to_remote(
                    payload=remote_environment_payload,
                    local_temp_dir=local_sync_dir,
                    ssh_target=backend["ssh_target"],
                    remote_path=f"{model_paths['remote_model_dir']}/remote-environment.json",
                    dry_run=args.dry_run,
                )
                backend_shared_runtime[f"model_{model_slug}_env_sync"] = sync_env_runtime

                evaluation_runtime = run_command(
                    commands["evaluate"],
                    dry_run=args.dry_run,
                    timeout=args.evaluation_timeout,
                )
                dump_json(model_local_dir / "runtime.json", evaluation_runtime)

                manifest_payload = ensure_manifest_payload(
                    "backend_comparison",
                    build_run_manifest(
                        bundle_dir=bundle_dir,
                        bundle_sha256=bundle_sha,
                        benchmark_json=benchmark_json,
                        benchmark_sha256=benchmark_sha,
                        evaluator_script=evaluator_script,
                        backend_id=backend["id"],
                        backend_label=backend["label"],
                        model_name=model_name,
                        resolved_device=None,
                        variant_id=args.variant_id,
                        ssh_target=backend["ssh_target"],
                    ),
                )
                write_manifest(
                    "backend_comparison",
                    model_local_dir / "run-manifest.json",
                    manifest_payload | {"artifact_status": "generated", "freshness": "fresh"},
                )
                sync_json_to_remote(
                    payload=manifest_payload,
                    local_temp_dir=local_sync_dir,
                    ssh_target=backend["ssh_target"],
                    remote_path=f"{model_paths['remote_model_dir']}/run-manifest.json",
                    dry_run=args.dry_run,
                )
                sync_json_to_remote(
                    payload=evaluation_runtime or {"status": "unknown"},
                    local_temp_dir=local_sync_dir,
                    ssh_target=backend["ssh_target"],
                    remote_path=f"{model_paths['remote_model_dir']}/runtime.json",
                    dry_run=args.dry_run,
                )

                if not args.dry_run and evaluation_runtime["success"]:
                    tar_runtime = run_command(commands["tar"], timeout=DEFAULT_TIMEOUT_STAGE)
                    backend_shared_runtime[f"model_{model_slug}_tar"] = tar_runtime
                    if tar_runtime["success"]:
                        fetch_runtime = run_command(commands["fetch"], timeout=DEFAULT_TIMEOUT_STAGE)
                        backend_shared_runtime[f"model_{model_slug}_fetch"] = fetch_runtime
                        if fetch_runtime["success"]:
                            extract_runtime = extract_tarball(
                                model_local_dir / "artifacts.tgz",
                                model_local_dir,
                                dry_run=False,
                            )
                            backend_shared_runtime[f"model_{model_slug}_extract"] = extract_runtime
                            evaluation_path = model_local_dir / "evaluation.json"
                            if evaluation_path.exists():
                                evaluation_report = load_json(evaluation_path)
                                resolved_device, runtime_seconds = extract_remote_backend_metadata(
                                    evaluation_report
                                )
                                manifest_payload["backend"]["resolved_device"] = resolved_device
                        else:
                            failure_stage = "fetch"
                    else:
                        failure_stage = "archive"
                elif args.dry_run:
                    dump_json(model_local_dir / "runtime.json", {"status": "dry_run"})
                else:
                    failure_stage = "runtime"

                write_manifest(
                    "backend_comparison",
                    model_local_dir / "run-manifest.json",
                    manifest_payload | {"artifact_status": "failed", "freshness": "fresh"},
                )
                sync_json_to_remote(
                    payload=manifest_payload,
                    local_temp_dir=local_sync_dir,
                    ssh_target=backend["ssh_target"],
                    remote_path=f"{model_paths['remote_model_dir']}/run-manifest.json",
                    dry_run=args.dry_run,
                )

                if evaluation_report is not None:
                    remote_manifest = load_json(model_local_dir / "run-manifest.json")
                    manifest_hash_match = (
                        remote_manifest["bundle"]["sha256"] == local_baseline_manifest["bundle"]["sha256"]
                        and remote_manifest["benchmark"]["sha256"] == local_baseline_manifest["benchmark"]["sha256"]
                    )
                elif args.dry_run:
                    manifest_hash_match = True
            else:
                dump_json(
                    model_local_dir / "runtime.json",
                    {
                        "status": "blocked",
                        "failure_stage": backend_failure_stage,
                        "shared_runtime": backend_shared_runtime,
                    },
                )
                write_manifest(
                    "backend_comparison",
                    model_local_dir / "run-manifest.json",
                    build_run_manifest(
                        bundle_dir=bundle_dir,
                        bundle_sha256=bundle_sha,
                        benchmark_json=benchmark_json,
                        benchmark_sha256=benchmark_sha,
                        evaluator_script=evaluator_script,
                        backend_id=backend["id"],
                        backend_label=backend["label"],
                        model_name=model_name,
                        resolved_device=None,
                        variant_id=args.variant_id,
                        ssh_target=backend["ssh_target"],
                    )
                    | {"artifact_status": "failed", "freshness": "fresh"},
                )

            aggregate_metrics = (
                aggregate_embedding_metrics(evaluation_report)
                if evaluation_report is not None
                else {
                    "run_count": 0,
                    "mean_twin_cosine": None,
                    "twin_hit_at_1": None,
                    "twin_mean_reciprocal_rank": None,
                    "runs": {},
                }
            )
            result = {
                "backend_id": backend["id"],
                "backend_label": backend["label"],
                "model_name": model_name,
                "model_slug": model_slug,
                "status": (
                    "dry_run"
                    if args.dry_run
                    else ("success" if evaluation_report is not None else "failure")
                ),
                "success": evaluation_report is not None,
                "failure_stage": failure_stage,
                "device_used": resolved_device,
                "runtime_seconds": runtime_seconds,
                "aggregate_metrics": aggregate_metrics,
                "deltas_vs_baseline": metric_deltas(aggregate_metrics, baseline_metrics)
                if evaluation_report is not None
                else None,
                "manifest_hash_match": manifest_hash_match,
                "artifacts_dir": str(model_local_dir),
                "commands": commands,
            }
            report["results"].append(result)

        if not args.dry_run and backend_failure_stage is None and not args.keep_remote_run:
            if all(
                result.get("success")
                for result in report["results"]
                if result["backend_id"] == backend["id"]
            ):
                cleanup_runtime = run_command(commands["cleanup"], timeout=DEFAULT_TIMEOUT_STAGE)
                backend_shared_runtime["cleanup"] = cleanup_runtime

    report["selection"] = choose_winner(
        [item for item in report["results"] if item["backend_id"] != "local-apple"],
        local_baseline_manifest if baseline_result.get("success") else None,
    )

    write_manifest(
        "backend_comparison",
        comparison_root / "run-manifest.json",
        {
            "generated_at": report["generated_at"],
            "variant_id": args.variant_id,
            "bundle": report["bundle"],
            "benchmark": report["benchmark"],
            "backend": {
                "id": "comparison-root",
                "label": "Embedding Backend Comparison",
                "model_name": None,
                "resolved_device": None,
                "ssh_target": None,
            },
            "artifact_status": "dry_run" if args.dry_run else "generated",
            "freshness": "fresh",
        },
    )
    dump_json(comparison_root / "comparison-summary.json", report)
    write_text(comparison_root / "comparison-summary.md", render_markdown(report))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
