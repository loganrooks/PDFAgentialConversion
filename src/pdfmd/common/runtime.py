from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

from pdfmd.common.io import load_json


def run_command(command: list[str], *, timeout: int | None = None) -> dict[str, Any]:
    try:
        completed = subprocess.run(
            command,
            text=True,
            capture_output=True,
            check=False,
            timeout=timeout,
        )
        return {
            "success": completed.returncode == 0,
            "exit_code": completed.returncode,
            "stdout": completed.stdout.strip(),
            "stderr": completed.stderr.strip(),
        }
    except subprocess.TimeoutExpired:
        return {
            "success": False,
            "exit_code": None,
            "stdout": "",
            "stderr": "timeout",
        }
    except OSError as exc:
        return {
            "success": False,
            "exit_code": None,
            "stdout": "",
            "stderr": str(exc),
        }


def local_environment(swift_helper: Path) -> dict[str, Any]:
    swift_available = shutil.which("swift") is not None
    swift_version = run_command(["swift", "--version"], timeout=5) if swift_available else None
    apple_helper_exists = swift_helper.exists()
    return {
        "python_executable": sys.executable,
        "python_version": sys.version.splitlines()[0],
        "swift_available": swift_available,
        "swift_version": swift_version["stdout"] if swift_version and swift_version["success"] else None,
        "apple_helper_exists": apple_helper_exists,
        "apple_helper_path": str(swift_helper),
        "apple_helper_ready": bool(swift_available and apple_helper_exists),
    }


def remote_backend_environment(config_path: Path, *, timeout: int = 8) -> list[dict[str, Any]]:
    if not config_path.exists():
        return []
    payload = load_json(config_path)
    entries: list[dict[str, Any]] = []
    for backend in payload.get("backends", []):
        ssh_target = str(backend.get("ssh_target") or "")
        if not ssh_target:
            continue
        uname = run_command(["ssh", ssh_target, "uname", "-a"], timeout=timeout)
        python_version = run_command(["ssh", ssh_target, str(backend.get("python_bin", "python3")), "--version"], timeout=timeout)
        nvidia = run_command(
            [
                "ssh",
                ssh_target,
                "nvidia-smi --query-gpu=name,memory.total,driver_version --format=csv,noheader",
            ],
            timeout=timeout,
        )
        entries.append(
            {
                "id": backend.get("id"),
                "label": backend.get("label"),
                "ssh_target": ssh_target,
                "reachable": uname["success"],
                "python_version": python_version["stdout"] if python_version["success"] else None,
                "gpu": nvidia["stdout"] if nvidia["success"] else None,
                "errors": {
                    "uname": None if uname["success"] else uname["stderr"],
                    "python": None if python_version["success"] else python_version["stderr"],
                    "gpu": None if nvidia["success"] else nvidia["stderr"],
                },
            }
        )
    return entries
