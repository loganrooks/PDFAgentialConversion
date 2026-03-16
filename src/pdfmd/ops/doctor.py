from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from pdfmd.common.paths import project_paths, resolve_project_root
from pdfmd.common.runtime import local_environment, remote_backend_environment


PROJECT_ROOT = resolve_project_root()


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Probe local and optional remote runtime readiness.")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--project-root", type=Path, default=PROJECT_ROOT)
    return parser.parse_args(argv)


def build_report(project_root: Path) -> dict[str, Any]:
    paths = project_paths(project_root)
    return {
        "project_root": str(paths.project_root),
        "remote_backends_config": str(paths.remote_backends_config),
        "remote_backends_config_exists": paths.remote_backends_config.exists(),
        "local": local_environment(paths.apple_nl_helper),
        "remote_backends": remote_backend_environment(paths.remote_backends_config),
    }


def render_text(report: dict[str, Any]) -> str:
    local = report["local"]
    lines = [
        "# Doctor",
        "",
        f"- Python: `{local['python_version']}`",
        f"- Python executable: `{local['python_executable']}`",
        f"- Swift available: `{local['swift_available']}`",
        f"- Swift version: `{local['swift_version'] or 'unavailable'}`",
        f"- Apple helper present: `{local['apple_helper_exists']}`",
        f"- Apple helper ready: `{local['apple_helper_ready']}`",
        f"- Apple helper path: `{local['apple_helper_path']}`",
        f"- Remote backend config present: `{report['remote_backends_config_exists']}`",
        "",
        "## Remote Backends",
    ]
    if not report["remote_backends"]:
        lines.append("- none configured")
    else:
        for backend in report["remote_backends"]:
            lines.append(
                f"- `{backend['id']}` reachable=`{backend['reachable']}` "
                f"python=`{backend['python_version'] or 'unavailable'}` "
                f"gpu=`{backend['gpu'] or 'unavailable'}`"
            )
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
