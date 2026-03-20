from __future__ import annotations

import io
import json
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from unittest import mock


TESTS_DIR = Path(__file__).resolve().parent
if str(TESTS_DIR) not in sys.path:
    sys.path.insert(0, str(TESTS_DIR))

from helpers import load_fixture, load_script_module


compare_embedding_backends = load_script_module("compare_embedding_backends")
evaluate_embedding_space = load_script_module("evaluate_embedding_space")


class FakeCudaModule:
    def __init__(self, *, available: bool) -> None:
        self._available = available

    def is_available(self) -> bool:
        return self._available

    def device_count(self) -> int:
        return 1 if self._available else 0

    def get_device_name(self, index: int) -> str:
        return f"Fake CUDA Device {index}"


class FakeTorchModule:
    __version__ = "2.4.1"

    class version:
        cuda = "12.1"

    def __init__(self, *, cuda_available: bool) -> None:
        self.cuda = FakeCudaModule(available=cuda_available)


class FakeSentenceTransformerModel:
    def __init__(self, model_name: str, device: str, trust_remote_code: bool = False) -> None:
        self.model_name = model_name
        self.device = device
        self.trust_remote_code = trust_remote_code

    def encode(
        self,
        texts: list[str],
        *,
        batch_size: int,
        show_progress_bar: bool,
        convert_to_numpy: bool,
        normalize_embeddings: bool,
    ) -> list[list[float]]:
        rows: list[list[float]] = []
        for text in texts:
            lowered = text.lower()
            rows.append(
                [
                    float(lowered.count("ethical")),
                    float(lowered.count("citation")),
                    float(lowered.count("commentary")),
                    float(len(lowered.split())),
                ]
            )
        return rows


class FakeSentenceTransformersModule:
    __version__ = "3.0.1"
    SentenceTransformer = FakeSentenceTransformerModel


class RemoteEmbeddingBackendTests(unittest.TestCase):
    def test_evaluator_parses_sentence_transformer_args(self) -> None:
        args = evaluate_embedding_space.parse_args(
            [
                "/tmp/bundle",
                "/tmp/benchmark.json",
                "--embedding-backend",
                "sentence_transformers",
                "--model-name",
                "BAAI/bge-small-en-v1.5",
                "--device",
                "cpu",
                "--batch-size",
                "16",
            ]
        )
        self.assertEqual(args.embedding_backend, "sentence_transformers")
        self.assertEqual(args.model_name, "BAAI/bge-small-en-v1.5")
        self.assertEqual(args.device, "cpu")
        self.assertEqual(args.batch_size, 16)

    def test_sentence_transformer_device_resolution_prefers_cuda_when_available(self) -> None:
        resolved, probe = evaluate_embedding_space.resolve_sentence_transformers_device(
            "auto",
            FakeTorchModule(cuda_available=True),
        )
        self.assertEqual(resolved, "cuda")
        self.assertTrue(probe["cuda_available"])
        self.assertEqual(probe["device_count"], 1)

    def test_remote_backend_config_validation_and_command_builders(self) -> None:
        fixture = load_fixture("remote_backend_cases.json")
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            valid_path = temp_path / "valid.json"
            invalid_path = temp_path / "invalid.json"
            valid_path.write_text(json.dumps(fixture["valid_config"]), encoding="utf-8")
            invalid_path.write_text(json.dumps(fixture["invalid_missing_field"]), encoding="utf-8")

            valid_backends = compare_embedding_backends.load_remote_backends(valid_path)
            self.assertEqual(valid_backends[0]["id"], "fake-gpu-host")

            with self.assertRaises(ValueError):
                compare_embedding_backends.load_remote_backends(invalid_path)

            ssh_command = compare_embedding_backends.build_ssh_command(
                "fake-host",
                ["bash", "-lc", "echo hello"],
            )
            rsync_command = compare_embedding_backends.build_rsync_to_remote_command(
                Path("/tmp/bundle"),
                "fake-host",
                "/remote/pdfmd/bundle/",
                copy_dir_contents=True,
            )
            tar_command = compare_embedding_backends.build_remote_artifact_tar_command(
                "fake-host",
                remote_backend_root="/remote/pdfmd/run-01/fake-gpu-host",
                model_slug="baai-bge-small-en-v1-5",
            )

            self.assertEqual(ssh_command[:2], ["ssh", "fake-host"])
            self.assertEqual(rsync_command[:2], ["rsync", "-az"])
            self.assertTrue(rsync_command[2].endswith("/"))
            self.assertIn("tar -czf", tar_command[-1])
            self.assertIn("baai-bge-small-en-v1-5", tar_command[-1])

    def test_hash_helpers_and_manifest_capture_input_identity(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            bundle_dir = temp_path / "bundle"
            bundle_dir.mkdir(parents=True, exist_ok=True)
            (bundle_dir / "alpha.txt").write_text("alpha\n", encoding="utf-8")
            (bundle_dir / "nested").mkdir()
            (bundle_dir / "nested" / "beta.txt").write_text("beta\n", encoding="utf-8")
            benchmark_json = temp_path / "benchmark.json"
            benchmark_json.write_text('{"name":"tiny","cases":[]}\n', encoding="utf-8")

            bundle_hash = compare_embedding_backends.sha256_directory(bundle_dir)
            benchmark_hash = compare_embedding_backends.sha256_file(benchmark_json)
            manifest = compare_embedding_backends.build_run_manifest(
                bundle_dir=bundle_dir,
                bundle_sha256=bundle_hash,
                benchmark_json=benchmark_json,
                benchmark_sha256=benchmark_hash,
                evaluator_script=compare_embedding_backends.SCRIPT_DIR / "evaluate_embedding_space.py",
                backend_id="fake-gpu-host",
                backend_label="Fake GPU Host",
                model_name="BAAI/bge-small-en-v1.5",
                resolved_device="cuda",
                variant_id="default",
                ssh_target="fake-host",
            )

            self.assertEqual(manifest["bundle"]["sha256"], bundle_hash)
            self.assertEqual(manifest["benchmark"]["sha256"], benchmark_hash)
            self.assertEqual(manifest["backend"]["resolved_device"], "cuda")

    def test_choose_winner_discards_hash_mismatch(self) -> None:
        selection = compare_embedding_backends.choose_winner(
            [
                {
                    "backend_id": "remote-a",
                    "model_name": "small",
                    "success": True,
                    "manifest_hash_match": False,
                    "runtime_seconds": 1.0,
                    "aggregate_metrics": {
                        "mean_twin_cosine": 0.99,
                        "twin_hit_at_1": 0.99,
                        "twin_mean_reciprocal_rank": 0.99,
                    },
                },
                {
                    "backend_id": "remote-b",
                    "model_name": "base",
                    "success": True,
                    "manifest_hash_match": True,
                    "runtime_seconds": 2.0,
                    "aggregate_metrics": {
                        "mean_twin_cosine": 0.98,
                        "twin_hit_at_1": 0.98,
                        "twin_mean_reciprocal_rank": 0.98,
                    },
                },
            ],
            baseline_manifest={"bundle": {"sha256": "abc"}, "benchmark": {"sha256": "def"}},
        )
        self.assertIsNotNone(selection["winner"])
        assert selection["winner"] is not None
        self.assertEqual(selection["winner"]["backend_id"], "remote-b")

    def test_compare_harness_dry_run_writes_summary_and_manifests(self) -> None:
        fixture = load_fixture("remote_backend_cases.json")
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            bundle_dir = temp_path / "bundle"
            bundle_dir.mkdir(parents=True, exist_ok=True)
            (bundle_dir / "metadata.json").write_text('{"file_manifest":[]}\n', encoding="utf-8")
            (bundle_dir / "index.md").write_text("# Bundle\n", encoding="utf-8")
            benchmark_json = temp_path / "benchmark.json"
            benchmark_json.write_text('{"name":"tiny","cases":[]}\n', encoding="utf-8")
            remote_config = temp_path / "remote-backends.json"
            remote_config.write_text(json.dumps(fixture["valid_config"]), encoding="utf-8")
            out_dir = temp_path / "out"

            exit_code = compare_embedding_backends.main(
                [
                    str(bundle_dir),
                    str(benchmark_json),
                    "--remote-backends-config",
                    str(remote_config),
                    "--out-dir",
                    str(out_dir),
                    "--run-id",
                    "dry-run-case",
                    "--dry-run",
                ]
            )

            self.assertEqual(exit_code, 0)
            summary_path = out_dir / "dry-run-case" / "comparison-summary.json"
            self.assertTrue(summary_path.exists())
            summary = json.loads(summary_path.read_text(encoding="utf-8"))
            self.assertTrue(summary["dry_run"])
            self.assertEqual(len(summary["results"]), 2)
            remote_result = next(item for item in summary["results"] if item["backend_id"] != "local-apple")
            self.assertEqual(remote_result["status"], "dry_run")
            self.assertTrue(
                (out_dir / "dry-run-case" / "local-apple" / "run-manifest.json").exists()
            )
            self.assertTrue(
                (
                    out_dir
                    / "dry-run-case"
                    / "fake-gpu-host"
                    / "baai-bge-small-en-v1-5"
                    / "remote-environment.json"
                ).exists()
            )

    def test_sentence_transformers_cpu_smoke_on_tiny_fixture_bundle(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            bundle_dir = temp_path / "bundle"
            (bundle_dir / "body").mkdir(parents=True, exist_ok=True)
            (bundle_dir / "flat" / "leaf-nodes").mkdir(parents=True, exist_ok=True)
            (bundle_dir / "rag" / "leaf-nodes").mkdir(parents=True, exist_ok=True)
            (bundle_dir / "spatial" / "body").mkdir(parents=True, exist_ok=True)

            output_path = "body/sample-section.md"
            flat_output_path = "flat/leaf-nodes/sample-section.md"
            rag_output_path = "rag/leaf-nodes/sample-section.md"
            spatial_output_path = "spatial/body/sample-section.layout.json"
            metadata = {
                "file_manifest": [
                    {
                        "title": "Sample Section",
                        "context_path": "Part I > Chapter 1",
                        "kind": "section",
                        "output_path": output_path,
                        "flat_output_path": flat_output_path,
                        "rag_output_path": rag_output_path,
                        "spatial_output_path": spatial_output_path,
                    }
                ]
            }
            (bundle_dir / "metadata.json").write_text(
                json.dumps(metadata, indent=2) + "\n",
                encoding="utf-8",
            )
            semantic_markdown = (
                "# Sample Section\n\n"
                "Context: Part I > Chapter 1\n\n"
                "Source pages: 1-2 (PDF 1-2).\n\n"
                "Ethical citation and commentary belong together in this sample section.\n"
            )
            rag_markdown = (
                "# Sample Section\n\n"
                "## Passage 001 (1a)\n"
                "Label: 1a\n"
                "Source reference: Example\n"
                "Source page labels: 1\n\n"
                "### Citation\n\n"
                "Ethical citation begins here.\n\n"
                "### Commentary\n\n"
                "Commentary follows the citation carefully.\n"
            )
            spatial_payload = {
                "pages": [
                    {
                        "pdf_page": 1,
                        "layout_text": "Ethical citation begins here. Commentary follows the citation carefully.",
                        "regions": [
                            {
                                "role": "main",
                                "semantic_text": "Ethical citation begins here. Commentary follows the citation carefully.",
                            },
                            {
                                "role": "aside",
                                "semantic_text": "Margin gloss about responsibility.",
                            },
                        ],
                    }
                ]
            }
            (bundle_dir / output_path).write_text(semantic_markdown, encoding="utf-8")
            (bundle_dir / flat_output_path).write_text(semantic_markdown, encoding="utf-8")
            (bundle_dir / rag_output_path).write_text(rag_markdown, encoding="utf-8")
            (bundle_dir / spatial_output_path).write_text(
                json.dumps(spatial_payload, indent=2) + "\n",
                encoding="utf-8",
            )
            benchmark_json = temp_path / "benchmark.json"
            benchmark_json.write_text(
                json.dumps(
                    {
                        "name": "tiny-benchmark",
                        "cases": [
                            {
                                "id": "case-1",
                                "query": "ethical citation",
                                "expected_doc_ids": [output_path],
                            }
                        ],
                    },
                    indent=2,
                )
                + "\n",
                encoding="utf-8",
            )

            fake_torch = FakeTorchModule(cuda_available=False)
            fake_st = FakeSentenceTransformersModule()

            def fake_import(name: str) -> object:
                if name == "torch":
                    return fake_torch
                if name == "sentence_transformers":
                    return fake_st
                raise ModuleNotFoundError(name)

            stdout = io.StringIO()
            with mock.patch.object(
                evaluate_embedding_space.importlib,
                "import_module",
                side_effect=fake_import,
            ):
                with redirect_stdout(stdout):
                    exit_code = evaluate_embedding_space.main(
                        [
                            str(bundle_dir),
                            str(benchmark_json),
                            "--embedding-backend",
                            "sentence_transformers",
                            "--model-name",
                            "BAAI/bge-small-en-v1.5",
                            "--device",
                            "cpu",
                            "--corpora",
                            "rag_linearized,semantic_flat_clean,spatial_main_plus_supplement",
                            "--views",
                            "body,contextual",
                        ]
                    )

            self.assertEqual(exit_code, 0)
            payload = json.loads(stdout.getvalue())
            self.assertEqual(payload["embedding_backend"]["backend"], "sentence_transformers")
            self.assertEqual(payload["embedding_backend"]["model_name"], "BAAI/bge-small-en-v1.5")
            self.assertEqual(payload["embedding_backend"]["device_resolved"], "cpu")
            self.assertGreaterEqual(
                payload["representation_summary_by_run"]["semantic_flat_clean::body"]["mean_twin_cosine"],
                0.0,
            )


class VramProbeTests(unittest.TestCase):
    """Tests for VRAM probe helpers (INFRA-03)."""

    def test_parse_vram_probe_valid_csv_output(self) -> None:
        """parse_vram_probe correctly parses well-formed nvidia-smi CSV output."""
        runtime = {
            "success": True,
            "status": "success",
            "stdout": "256, 11264, 11008\n",
            "stderr": "",
        }
        result = compare_embedding_backends.parse_vram_probe(runtime)
        self.assertTrue(result["available"])
        self.assertEqual(result["used_mib"], 256)
        self.assertEqual(result["total_mib"], 11264)
        self.assertEqual(result["free_mib"], 11008)
        self.assertAlmostEqual(result["utilization_pct"], round(256 / 11264 * 100, 2), places=2)

    def test_parse_vram_probe_empty_output_returns_unavailable(self) -> None:
        """parse_vram_probe returns available=False when stdout is empty."""
        runtime = {
            "success": True,
            "status": "success",
            "stdout": "",
            "stderr": "",
        }
        result = compare_embedding_backends.parse_vram_probe(runtime)
        self.assertFalse(result["available"])
        self.assertIn("error", result)

    def test_parse_vram_probe_garbage_output_returns_unavailable(self) -> None:
        """parse_vram_probe returns available=False when output cannot be parsed."""
        runtime = {
            "success": True,
            "status": "success",
            "stdout": "not,a,valid,gpu,line,at,all\n",
            "stderr": "",
        }
        result = compare_embedding_backends.parse_vram_probe(runtime)
        self.assertFalse(result["available"])
        self.assertIn("error", result)

    def test_parse_vram_probe_failed_command_returns_unavailable(self) -> None:
        """parse_vram_probe returns available=False when the command failed."""
        runtime = {
            "success": False,
            "status": "failure",
            "stdout": "",
            "stderr": "nvidia-smi: command not found",
        }
        result = compare_embedding_backends.parse_vram_probe(runtime)
        self.assertFalse(result["available"])
        self.assertIn("error", result)

    def test_build_vram_probe_command_produces_valid_ssh_command(self) -> None:
        """build_vram_probe_command returns a well-formed SSH command."""
        cmd = compare_embedding_backends.build_vram_probe_command("rookslog@dionysus")
        self.assertEqual(cmd[0], "ssh")
        self.assertEqual(cmd[1], "rookslog@dionysus")
        self.assertIn("nvidia-smi", cmd)
        self.assertTrue(any("memory.used" in arg for arg in cmd))
        self.assertTrue(any("csv" in arg for arg in cmd))


class RunCommandTimeoutTests(unittest.TestCase):
    """Tests for run_command timeout behavior (INFRA-02)."""

    def test_run_command_timeout_returns_structured_error(self) -> None:
        """When subprocess times out, run_command returns status='timeout' dict."""
        with mock.patch("subprocess.run", side_effect=subprocess.TimeoutExpired(cmd=["sleep", "999"], timeout=1)):
            result = compare_embedding_backends.run_command(["sleep", "999"], timeout=1)
        self.assertFalse(result["success"])
        self.assertEqual(result["status"], "timeout")
        self.assertIsNone(result["exit_code"])
        self.assertIn("timed out", result["stderr"])
        self.assertIn("1s", result["stderr"])
        self.assertIsInstance(result["wall_clock_seconds"], float)

    def test_run_command_timeout_none_works_as_before(self) -> None:
        """run_command with timeout=None executes successfully (backward compatibility)."""
        result = compare_embedding_backends.run_command(["echo", "backward-compat"], timeout=None)
        self.assertTrue(result["success"])
        self.assertEqual(result["status"], "success")
        self.assertIn("backward-compat", result["stdout"])

    def test_parse_json_stdout_handles_timeout_status(self) -> None:
        """parse_json_stdout treats timeout runtime as a distinct status (not failure)."""
        timeout_runtime = {
            "status": "timeout",
            "success": False,
            "exit_code": None,
            "stdout": "",
            "stderr": "Command timed out after 60s",
            "wall_clock_seconds": 60.1,
        }
        result = compare_embedding_backends.parse_json_stdout(timeout_runtime, label="pre_probe")
        self.assertEqual(result["status"], "timeout")
        self.assertIsNone(result["payload"])
        self.assertEqual(result["label"], "pre_probe")


class TrustRemoteCodeTests(unittest.TestCase):
    """Tests for trust_remote_code threading (EMBED-04)."""

    def _minimal_backend(self) -> dict:
        return {
            "id": "fake-gpu-host",
            "label": "Fake GPU Host",
            "transport": "ssh",
            "ssh_target": "fake-host",
            "remote_root": "/remote/pdfmd",
            "python_bin": "python3",
            "venv_dir": "venv",
            "device": "cuda",
            "bootstrap_mode": "ssh_venv",
            "models": ["BAAI/bge-small-en-v1.5"],
            "model_config": {},
        }

    def _minimal_args(self) -> SimpleNamespace:
        return SimpleNamespace(
            reference_corpus="rag_linearized",
            corpora="rag_linearized",
            views="body",
            top_k=5,
            neighbor_k=5,
            dense_char_limit=1600,
            batch_size=32,
        )

    def test_build_remote_evaluation_command_with_trust_remote_code_includes_flag(self) -> None:
        """build_remote_evaluation_command with trust_remote_code=True appends --trust-remote-code."""
        backend = self._minimal_backend()
        args = self._minimal_args()
        cmd = compare_embedding_backends.build_remote_evaluation_command(
            backend,
            remote_backend_root="/remote/pdfmd/run-01/fake-gpu-host",
            model_name="BAAI/bge-small-en-v1.5",
            model_slug="baai-bge-small-en-v1-5",
            args=args,
            trust_remote_code=True,
        )
        # The SSH command wraps a bash script; join to search the full string
        full_cmd = " ".join(cmd)
        self.assertIn("--trust-remote-code", full_cmd)

    def test_build_remote_evaluation_command_without_trust_remote_code_excludes_flag(self) -> None:
        """build_remote_evaluation_command with trust_remote_code=False (default) omits the flag."""
        backend = self._minimal_backend()
        args = self._minimal_args()
        cmd = compare_embedding_backends.build_remote_evaluation_command(
            backend,
            remote_backend_root="/remote/pdfmd/run-01/fake-gpu-host",
            model_name="BAAI/bge-small-en-v1.5",
            model_slug="baai-bge-small-en-v1-5",
            args=args,
            trust_remote_code=False,
        )
        full_cmd = " ".join(cmd)
        self.assertNotIn("--trust-remote-code", full_cmd)

    def test_validate_backend_entry_passes_with_model_config_present(self) -> None:
        """validate_backend_entry accepts and passes through a model_config dict."""
        entry = {
            "id": "fake-gpu-host",
            "label": "Fake GPU Host",
            "transport": "ssh",
            "ssh_target": "fake-host",
            "remote_root": "/remote/pdfmd",
            "python_bin": "python3",
            "venv_dir": "venv",
            "device": "cuda",
            "bootstrap_mode": "ssh_venv",
            "models": ["BAAI/bge-small-en-v1.5"],
            "model_config": {"nomic-ai/nomic-embed-text-v1.5": {"trust_remote_code": True}},
        }
        result = compare_embedding_backends.validate_backend_entry(entry)
        self.assertIn("model_config", result)
        self.assertEqual(
            result["model_config"]["nomic-ai/nomic-embed-text-v1.5"]["trust_remote_code"], True
        )

    def test_validate_backend_entry_passes_without_model_config(self) -> None:
        """validate_backend_entry accepts entries with no model_config (defaults to empty dict)."""
        entry = {
            "id": "fake-gpu-host",
            "label": "Fake GPU Host",
            "transport": "ssh",
            "ssh_target": "fake-host",
            "remote_root": "/remote/pdfmd",
            "python_bin": "python3",
            "venv_dir": "venv",
            "device": "cuda",
            "bootstrap_mode": "ssh_venv",
            "models": ["BAAI/bge-small-en-v1.5"],
        }
        result = compare_embedding_backends.validate_backend_entry(entry)
        self.assertIn("model_config", result)
        self.assertEqual(result["model_config"], {})

    def test_parse_args_recognizes_trust_remote_code_flag(self) -> None:
        """evaluate_embedding_space.parse_args accepts --trust-remote-code as a store_true flag."""
        args = evaluate_embedding_space.parse_args(
            [
                "/tmp/bundle",
                "/tmp/benchmark.json",
                "--embedding-backend",
                "sentence_transformers",
                "--model-name",
                "nomic-ai/nomic-embed-text-v1.5",
                "--trust-remote-code",
            ]
        )
        self.assertTrue(args.trust_remote_code)

    def test_parse_args_trust_remote_code_defaults_to_false(self) -> None:
        """evaluate_embedding_space.parse_args defaults trust_remote_code to False."""
        args = evaluate_embedding_space.parse_args(
            ["/tmp/bundle", "/tmp/benchmark.json"]
        )
        self.assertFalse(args.trust_remote_code)


if __name__ == "__main__":
    unittest.main()
