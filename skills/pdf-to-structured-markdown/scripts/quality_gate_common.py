#!/usr/bin/env python3
from __future__ import annotations

import sys
from pathlib import Path

SRC_DIR = Path(__file__).resolve().parents[3] / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from pdfmd.gates.quality_gate_common import *  # noqa: F401,F403
