from __future__ import annotations

import sys
import unittest
from pathlib import Path


TESTS_DIR = Path(__file__).resolve().parent
SKILL_DIR = TESTS_DIR.parent
SCRIPTS_DIR = SKILL_DIR / "scripts"
WORKSPACE_ROOT = TESTS_DIR.parents[2]
SRC_ROOT = WORKSPACE_ROOT / "src"
if str(TESTS_DIR) not in sys.path:
    sys.path.insert(0, str(TESTS_DIR))
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from helpers import load_script_module


WRAPPER_IMPORTS = {
    "audit_bundle": "from pdfmd.gates.audit_bundle import *",
    "catalog_anchors": "from pdfmd.gates.catalog import *",
    "check_regressions": "from pdfmd.gates.check_regressions import *",
    "compare_embedding_backends": "from pdfmd.benchmarks.compare_embedding_backends import *",
    "compare_variants": "from pdfmd.benchmarks.compare_variants import *",
    "convert_pdf": "from pdfmd.convert.convert_pdf import *",
    "doctor": "from pdfmd.ops.doctor import *",
    "evaluate_embedding_space": "from pdfmd.benchmarks.evaluate_embedding_space import *",
    "evaluate_retrieval": "from pdfmd.benchmarks.evaluate_retrieval import *",
    "probe_artifacts": "from pdfmd.gates.probe_artifacts import *",
    "render_review_packet": "from pdfmd.gates.render_review_packet import *",
    "run_challenge_corpus": "from pdfmd.gates.run_challenge_corpus import *",
    "run_quality_gate": "from pdfmd.gates.run_quality_gate import *",
    "status_snapshot": "from pdfmd.ops.status_snapshot import *",
}


class WrapperParityTests(unittest.TestCase):
    def test_major_wrappers_import_expected_package_modules(self) -> None:
        for module_name, import_line in WRAPPER_IMPORTS.items():
            wrapper_path = SCRIPTS_DIR / f"{module_name}.py"
            with self.subTest(wrapper=module_name):
                text = wrapper_path.read_text(encoding="utf-8")
                self.assertIn(import_line, text)
                self.assertIn("SRC_DIR = Path(__file__).resolve().parents[3] / \"src\"", text)

    def test_major_wrappers_expose_main(self) -> None:
        for module_name in WRAPPER_IMPORTS:
            with self.subTest(wrapper=module_name):
                module = load_script_module(module_name)
                self.assertTrue(callable(getattr(module, "main", None)))

    def test_makefile_operator_surface_uses_script_wrappers(self) -> None:
        makefile = (WORKSPACE_ROOT / "Makefile").read_text(encoding="utf-8")
        self.assertIn("$(PYTHON) $(SCRIPTS_DIR)/doctor.py", makefile)
        self.assertIn("$(PYTHON) $(SCRIPTS_DIR)/status_snapshot.py", makefile)
        self.assertIn("$(PYTHON) $(SCRIPTS_DIR)/run_quality_gate.py", makefile)
        self.assertIn("$(PYTHON) $(SCRIPTS_DIR)/run_challenge_corpus.py", makefile)
        self.assertIn("$(PYTHON) $(SCRIPTS_DIR)/compare_embedding_backends.py", makefile)


if __name__ == "__main__":
    unittest.main()
