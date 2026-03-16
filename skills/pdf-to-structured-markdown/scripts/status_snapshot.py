#!/usr/bin/env python3
from __future__ import annotations

import sys
from pathlib import Path

SRC_DIR = Path(__file__).resolve().parents[3] / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from pdfmd.ops.status_snapshot import *  # noqa: F401,F403

if __name__ == "__main__":
    raise SystemExit(main())
