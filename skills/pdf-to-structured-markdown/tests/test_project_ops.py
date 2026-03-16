from __future__ import annotations

import importlib
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


TESTS_DIR = Path(__file__).resolve().parent
WORKSPACE_ROOT = TESTS_DIR.parents[2]
SRC_ROOT = WORKSPACE_ROOT / "src"
if str(TESTS_DIR) not in sys.path:
    sys.path.insert(0, str(TESTS_DIR))
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from helpers import load_script_module


doctor = load_script_module("doctor")
status_snapshot = load_script_module("status_snapshot")
run_quality_gate = load_script_module("run_quality_gate")
compare_embedding_backends = load_script_module("compare_embedding_backends")
evaluate_embedding_space = load_script_module("evaluate_embedding_space")
calibrate_embedding_timeout = load_script_module("calibrate_embedding_timeout")
compare_variants = load_script_module("compare_variants")

from pdfmd.common.manifests import (
    ensure_manifest_payload,
    normalize_manifest_payload,
    validate_manifest_payload,
    write_manifest,
)
from pdfmd.common.paths import project_paths


class ProjectOpsTests(unittest.TestCase):
    def test_package_modules_import(self) -> None:
        modules = [
            "pdfmd.common.io",
            "pdfmd.common.manifests",
            "pdfmd.common.paths",
            "pdfmd.common.runtime",
            "pdfmd.ops.doctor",
            "pdfmd.ops.status_snapshot",
            "pdfmd.gates.quality_gate",
            "pdfmd.gates.challenge_corpus",
            "pdfmd.gates.run_quality_gate",
            "pdfmd.gates.run_challenge_corpus",
            "pdfmd.benchmarks.embedding_space",
            "pdfmd.benchmarks.remote_backends",
            "pdfmd.benchmarks.evaluate_embedding_space",
            "pdfmd.benchmarks.compare_embedding_backends",
            "pdfmd.convert.metadata",
            "pdfmd.convert.page_mapping",
            "pdfmd.convert.render",
            "pdfmd.convert.convert_pdf",
        ]
        for module_name in modules:
            with self.subTest(module=module_name):
                module = importlib.import_module(module_name)
                self.assertIsNotNone(module)

    def test_wrapper_modules_expose_main(self) -> None:
        for module_name in ("convert_pdf", "evaluate_embedding_space", "status_snapshot", "doctor"):
            with self.subTest(wrapper=module_name):
                module = load_script_module(module_name)
                self.assertTrue(callable(getattr(module, "main", None)))

    def test_split_package_defaults_still_point_at_skill_layer_artifacts(self) -> None:
        compare_args = compare_embedding_backends.parse_args([])
        compare_variants_args = compare_variants.parse_args([])
        embed_args = evaluate_embedding_space.parse_args(
            ["/tmp/bundle", "/tmp/benchmark.json"]
        )
        calibrate_args = calibrate_embedding_timeout.parse_args([])
        self.assertTrue(compare_args.remote_backends_config.exists())
        self.assertTrue(compare_args.requirements.exists())
        self.assertEqual(compare_variants_args.variants, None)
        self.assertTrue(embed_args.apple_nl_helper.exists())
        self.assertTrue(calibrate_args.bundle_dir.exists())
        self.assertTrue(calibrate_args.benchmark_json.exists())

    def test_challenge_corpus_defaults_to_hard_gate_mode(self) -> None:
        challenge_corpus = importlib.import_module("pdfmd.gates.challenge_corpus")
        args = challenge_corpus.parse_args(
            [str(WORKSPACE_ROOT / "skills" / "pdf-to-structured-markdown" / "references" / "challenge-corpus.json")]
        )
        self.assertEqual(args.gate_mode, "hard")

    def test_variant_comparison_filter_variants_preserves_requested_order(self) -> None:
        variants = [
            {"id": "balanced"},
            {"id": "boundary-aggressive"},
            {"id": "group-first"},
        ]
        filtered = compare_variants.filter_variants(
            variants,
            "group-first,balanced",
        )
        self.assertEqual([variant["id"] for variant in filtered], ["group-first", "balanced"])

    def test_project_paths_resolve_canonical_repo_locations(self) -> None:
        paths = project_paths(WORKSPACE_ROOT)
        self.assertEqual(paths.project_root, WORKSPACE_ROOT.resolve())
        self.assertEqual(
            paths.apple_nl_helper,
            WORKSPACE_ROOT / "skills" / "pdf-to-structured-markdown" / "scripts" / "apple_nl_embed.swift",
        )
        self.assertEqual(
            paths.remote_backends_config,
            WORKSPACE_ROOT / "skills" / "pdf-to-structured-markdown" / "references" / "remote-backends.json",
        )
        self.assertEqual(
            paths.why_ethics_quality_gate_report,
            WORKSPACE_ROOT / "generated" / "why-ethics" / "quality-gate" / "quality-gate-report.json",
        )

    def test_doctor_build_report_uses_project_root_scoped_paths(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            project_root = Path(temp_dir).resolve()
            expected_helper = (
                project_root / "skills" / "pdf-to-structured-markdown" / "scripts" / "apple_nl_embed.swift"
            )
            expected_config = (
                project_root / "skills" / "pdf-to-structured-markdown" / "references" / "remote-backends.json"
            )

            def fake_local_environment(path: Path) -> dict[str, object]:
                self.assertEqual(path, expected_helper)
                return {
                    "python_executable": "/usr/bin/python3",
                    "python_version": "3.12.0",
                    "swift_available": True,
                    "swift_version": "Swift 6.0",
                    "apple_helper_exists": False,
                }

            def fake_remote_environment(path: Path) -> list[dict[str, object]]:
                self.assertEqual(path, expected_config)
                return [
                    {
                        "id": "remote-a",
                        "reachable": True,
                        "python_version": "Python 3.12.1",
                        "gpu": "Fake GPU",
                    }
                ]

            with mock.patch("pdfmd.ops.doctor.local_environment", side_effect=fake_local_environment):
                with mock.patch(
                    "pdfmd.ops.doctor.remote_backend_environment",
                    side_effect=fake_remote_environment,
                ):
                    report = doctor.build_report(project_root)

        self.assertEqual(report["project_root"], str(project_root.resolve()))
        self.assertFalse(report["remote_backends_config_exists"])
        self.assertEqual(report["local"]["swift_version"], "Swift 6.0")
        self.assertEqual(report["remote_backends"][0]["id"], "remote-a")

    def test_status_snapshot_reads_project_root_reports_and_bundle_manifest_fallback(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            project_root = Path(temp_dir)
            (project_root / ".planning").mkdir(parents=True)
            (project_root / "generated" / "why-ethics" / "quality-gate").mkdir(parents=True)
            (project_root / "generated" / "challenge-corpus").mkdir(parents=True)
            (project_root / "generated" / "embedding-backend-comparison" / "20260313T000000Z").mkdir(
                parents=True
            )
            (project_root / "generated" / "why-ethics").mkdir(parents=True, exist_ok=True)

            (project_root / ".planning" / "ROADMAP.md").write_text(
                "# ROADMAP\n\n"
                "## Milestone 01\n\n"
                "### Phase 01: Repo and planning bootstrap\n"
                "- Status: done\n\n"
                "### Phase 02: Package extraction and wrapper parity\n"
                "- Status: in_progress\n",
                encoding="utf-8",
            )
            (project_root / "generated" / "why-ethics" / "metadata.json").write_text(
                json.dumps(
                    {
                        "book_id": "why-ethics",
                        "extraction": {"generated_at": "2026-03-13T00:00:00Z"},
                    }
                ),
                encoding="utf-8",
            )
            (project_root / "generated" / "why-ethics" / "quality-gate" / "quality-gate-report.json").write_text(
                json.dumps(
                    {
                        "status": "fail",
                        "generated_at": "2026-03-13T01:00:00Z",
                        "hard_gate_failures": [{"gate": "probe"}],
                    }
                ),
                encoding="utf-8",
            )
            (project_root / "generated" / "why-ethics" / "quality-gate" / "run-manifest.json").write_text(
                json.dumps(
                    {
                        "generated_at": "2026-03-13T01:00:00Z",
                        "artifact_status": "generated",
                        "freshness": "fresh",
                    }
                ),
                encoding="utf-8",
            )
            (project_root / "generated" / "challenge-corpus" / "smoke-report.json").write_text(
                json.dumps(
                    {
                        "status": "soft_fail",
                        "generated_at": "2026-03-13T02:00:00Z",
                        "gate_failures": [{"id": "of-grammatology", "failures": ["probe"]}],
                    }
                ),
                encoding="utf-8",
            )
            (project_root / "generated" / "challenge-corpus" / "run-manifest.json").write_text(
                json.dumps(
                    {
                        "generated_at": "2026-03-13T02:00:00Z",
                        "artifact_status": "generated",
                        "freshness": "fresh",
                        "gate_mode": "soft",
                    }
                ),
                encoding="utf-8",
            )
            (
                project_root
                / "generated"
                / "embedding-backend-comparison"
                / "20260313T000000Z"
                / "comparison-summary.json"
            ).write_text(
                json.dumps(
                    {
                        "run_id": "20260313T000000Z",
                        "generated_at": "2026-03-13T03:00:00Z",
                        "dry_run": True,
                        "selection": {"winner": None},
                        "results": [{"backend_id": "local-apple"}],
                    }
                ),
                encoding="utf-8",
            )
            (
                project_root
                / "generated"
                / "embedding-backend-comparison"
                / "20260313T000000Z"
                / "run-manifest.json"
            ).write_text(
                json.dumps(
                    {
                        "generated_at": "2026-03-13T03:00:00Z",
                        "artifact_status": "dry_run",
                        "freshness": "fresh",
                    }
                ),
                encoding="utf-8",
            )

            with mock.patch(
                "pdfmd.ops.status_snapshot.build_doctor_report",
                return_value={
                    "local": {
                        "python_version": "3.12.0",
                        "swift_version": "Swift 6.0",
                        "apple_helper_ready": True,
                    },
                    "remote_backends_config_exists": True,
                    "remote_backends": [
                        {
                            "id": "gpu-lab",
                            "reachable": True,
                            "python_version": "Python 3.12.3",
                            "gpu": "GTX 1080 Ti",
                        }
                    ],
                },
            ):
                report = status_snapshot.build_report(project_root)

        self.assertEqual(report["roadmap"]["current_phase"]["number"], "02")
        self.assertEqual(report["bundle_generation"]["generated_at"], "2026-03-13T00:00:00Z")
        self.assertEqual(report["why_ethics_gate"]["hard_failure_count"], 1)
        self.assertEqual(report["why_ethics_gate"]["freshness"], "fresh")
        self.assertEqual(report["challenge_corpus"]["gate_failure_count"], 1)
        self.assertEqual(report["challenge_corpus"]["gate_mode"], "soft")
        self.assertEqual(report["backend_comparison"]["artifact_status"], "dry_run")
        self.assertEqual(report["backend_comparison"]["run_id"], "20260313T000000Z")
        self.assertTrue(report["environment"]["apple_helper_ready"])
        self.assertTrue(report["environment"]["remote_backends_config_exists"])
        self.assertIn("why-ethics:probe", report["active_failures"])
        self.assertIn("of-grammatology:probe", report["active_failures"])

    def test_status_snapshot_reports_milestone_audit_when_all_phases_done(self) -> None:
        report = {
            "roadmap": {
                "current_phase": None,
                "milestone_ready": True,
                "next_milestone_planning": False,
            },
            "bundle_generation": None,
            "why_ethics_gate": None,
            "challenge_corpus": None,
            "backend_comparison": None,
            "environment": {
                "local_python": "3.14.3",
                "local_swift": "Swift 6.2.3",
                "apple_helper_ready": True,
                "remote_backends_config_exists": False,
                "remote_backends": [],
            },
            "active_failures": [],
        }
        text = status_snapshot.render_text(report)
        self.assertIn("Current phase: `milestone audit/completion`", text)

    def test_status_snapshot_reports_next_milestone_planning_when_roadmap_is_collapsed(self) -> None:
        report = {
            "roadmap": {
                "current_phase": None,
                "milestone_ready": False,
                "next_milestone_planning": True,
            },
            "bundle_generation": None,
            "why_ethics_gate": None,
            "challenge_corpus": None,
            "backend_comparison": None,
            "environment": {
                "local_python": "3.14.3",
                "local_swift": "Swift 6.2.3",
                "apple_helper_ready": True,
                "remote_backends_config_exists": False,
                "remote_backends": [],
            },
            "active_failures": [],
        }
        text = status_snapshot.render_text(report)
        self.assertIn("Current phase: `next milestone planning`", text)

    def test_manifest_contract_validation_and_builders(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            config_path = temp_path / "gate.json"
            benchmark_json = temp_path / "benchmark.json"
            evaluator_script = temp_path / "evaluate_embedding_space.py"
            bundle_dir = temp_path / "bundle"
            bundle_dir.mkdir(parents=True)
            config_path.write_text('{"name":"gate"}\n', encoding="utf-8")
            benchmark_json.write_text('{"name":"bench"}\n', encoding="utf-8")
            evaluator_script.write_text("print('ok')\n", encoding="utf-8")

            quality_manifest = run_quality_gate.build_run_manifest(
                {
                    "source": {
                        "absolute_path": "/tmp/source.pdf",
                        "filename": "source.pdf",
                        "sha256": "abc",
                        "page_count": 42,
                    },
                    "extraction": {"script_version": "0.1.0"},
                },
                config_path=config_path,
                variant_id="default",
                generated_at="2026-03-13T00:00:00Z",
            )
            backend_manifest = compare_embedding_backends.build_run_manifest(
                bundle_dir=bundle_dir,
                bundle_sha256="bundlehash",
                benchmark_json=benchmark_json,
                benchmark_sha256="benchhash",
                evaluator_script=evaluator_script,
                backend_id="local-apple",
                backend_label="Local Apple",
                model_name=None,
                resolved_device="apple_nl",
                variant_id="default",
                ssh_target=None,
            )
            challenge_manifest = {
                "generated_at": "2026-03-13T00:00:00Z",
                "variant_id": "default",
                "baseline_dir": "/tmp/baseline",
                "entry_count": 3,
            }
            bundle_manifest = {
                "generated_at": "2026-03-13T00:00:00Z",
                "book_id": "why-ethics",
                "source": {"filename": "source.pdf"},
                "converter_version": "0.1.0",
                "output_dir": "/tmp/out",
            }

        self.assertEqual(validate_manifest_payload("quality_gate", quality_manifest), [])
        self.assertEqual(validate_manifest_payload("backend_comparison", backend_manifest), [])
        self.assertEqual(validate_manifest_payload("challenge_corpus", challenge_manifest), [])
        self.assertEqual(validate_manifest_payload("bundle_generation", bundle_manifest), [])
        normalized = normalize_manifest_payload("bundle_generation", bundle_manifest)
        self.assertEqual(normalized["manifest_kind"], "bundle_generation")
        self.assertEqual(normalized["manifest_schema_version"], "1.0")
        self.assertEqual(normalized["artifact_status"], "generated")
        self.assertEqual(normalized["freshness"], "fresh")
        self.assertIsInstance(ensure_manifest_payload("bundle_generation", bundle_manifest), dict)
        manifest_path = temp_path / "bundle-manifest.json"
        written = write_manifest("bundle_generation", manifest_path, bundle_manifest)
        self.assertEqual(written["book_id"], "why-ethics")
        self.assertEqual(written["manifest_kind"], "bundle_generation")
        self.assertEqual(json.loads(manifest_path.read_text(encoding="utf-8"))["book_id"], "why-ethics")
        with self.assertRaises(ValueError):
            ensure_manifest_payload("quality_gate", {"generated_at": "now"})
        with self.assertRaises(ValueError):
            ensure_manifest_payload(
                "quality_gate",
                quality_manifest | {"artifact_status": "not-a-real-status"},
            )

    def test_runtime_failure_does_not_add_stability_failure_for_same_run(self) -> None:
        failures = run_quality_gate.collect_runtime_gate_failures(
            {
                "audit": {"status": "pass", "attempts": []},
                "regressions": {"status": "pass", "attempts": []},
                "probe": {"status": "pass", "attempts": []},
                "retrieval": {"status": "pass", "attempts": []},
                "embedding": {
                    "status": "fail",
                    "attempts": [{"failure_category": "timeout"}],
                },
            },
            completed_runs=0,
            stability_runs=2,
            identical_signatures=False,
        )
        self.assertEqual(len(failures), 1)
        self.assertEqual(failures[0]["gate"], "embedding_runtime")

    def test_runtime_stability_failure_requires_successful_selected_run(self) -> None:
        failures = run_quality_gate.collect_runtime_gate_failures(
            {
                "audit": {"status": "pass", "attempts": []},
                "regressions": {"status": "pass", "attempts": []},
                "probe": {"status": "pass", "attempts": []},
                "retrieval": {"status": "pass", "attempts": []},
                "embedding": {"status": "pass", "attempts": []},
            },
            completed_runs=1,
            stability_runs=2,
            identical_signatures=False,
        )
        self.assertEqual(len(failures), 1)
        self.assertEqual(failures[0]["gate"], "runtime_stability")

    def test_manual_acceptance_is_enforced_for_canonical_quality_gate_config(self) -> None:
        quality_gate = importlib.import_module("pdfmd.gates.quality_gate")
        config_path = (
            WORKSPACE_ROOT
            / "skills"
            / "pdf-to-structured-markdown"
            / "references"
            / "why-ethics-quality-gate.json"
        )
        config = json.loads(config_path.read_text(encoding="utf-8"))
        manual = quality_gate.evaluate_manual_sample(config)
        self.assertTrue(manual["enforce_acceptance"])
        self.assertTrue(manual["would_pass_acceptance"])
        self.assertEqual(manual["verdict_counts"].get("fail", 0), 0)
        self.assertTrue(manual["targets_all_pass"])
        self.assertTrue(manual["no_fail"])
        self.assertGreaterEqual(
            manual["verdict_counts"].get("pass", 0),
            manual["minimum_pass_count"],
        )

    def test_calibration_cli_accepts_positional_paths(self) -> None:
        args = calibrate_embedding_timeout.parse_args(["/tmp/bundle", "/tmp/benchmark.json", "--runs", "5"])
        self.assertEqual(args.bundle_dir, Path("/tmp/bundle").resolve())
        self.assertEqual(args.benchmark_json, Path("/tmp/benchmark.json").resolve())
        self.assertEqual(args.runs, 5)

    def test_calibration_report_blocks_on_runtime_failure(self) -> None:
        report = calibrate_embedding_timeout.build_calibration_report(
            bundle_dir=Path("/tmp/bundle"),
            benchmark_json=Path("/tmp/benchmark.json"),
            runs=5,
            helper_timeout_seconds=60,
            attempts=[
                {
                    "run_index": 1,
                    "success": False,
                    "exit_code": None,
                    "duration_seconds": 6.5,
                    "failure_category": "timeout",
                    "cleanup_result": "killpg_sigkill",
                }
            ],
        )
        self.assertEqual(report["status"], "blocked_by_runtime_failure")
        self.assertEqual(report["artifact_status"], "generated")
        self.assertEqual(report["freshness"], "fresh")
        self.assertEqual(report["recommendation_status"], "unavailable")
        self.assertEqual(report["durations"]["suggested_timeout_seconds"], None)

    def test_calibration_report_suggests_timeout_when_runs_succeed(self) -> None:
        report = calibrate_embedding_timeout.build_calibration_report(
            bundle_dir=Path("/tmp/bundle"),
            benchmark_json=Path("/tmp/benchmark.json"),
            runs=3,
            helper_timeout_seconds=60,
            attempts=[
                {"run_index": 1, "success": True, "duration_seconds": 10.0},
                {"run_index": 2, "success": True, "duration_seconds": 12.0},
                {"run_index": 3, "success": True, "duration_seconds": 11.0},
            ],
        )
        self.assertEqual(report["status"], "calibrated")
        self.assertEqual(report["artifact_status"], "generated")
        self.assertEqual(report["recommendation_status"], "complete")
        self.assertEqual(report["durations"]["suggested_timeout_seconds"], 42)

    def test_partial_calibration_report_keeps_provisional_recommendation(self) -> None:
        report = calibrate_embedding_timeout.build_calibration_report(
            bundle_dir=Path("/tmp/bundle"),
            benchmark_json=Path("/tmp/benchmark.json"),
            runs=5,
            helper_timeout_seconds=60,
            attempts=[
                {"run_index": 1, "success": True, "duration_seconds": 10.0},
                {"run_index": 2, "success": True, "duration_seconds": 12.0},
                {"run_index": 3, "success": True, "duration_seconds": 11.0},
                {"run_index": 4, "success": True, "duration_seconds": 12.5},
                {"run_index": 5, "success": False, "duration_seconds": 60.0, "failure_category": "timeout"},
            ],
        )
        self.assertEqual(report["status"], "blocked_by_runtime_failure")
        self.assertEqual(report["recommendation_status"], "provisional")
        self.assertEqual(report["durations"]["suggested_timeout_seconds"], 43)

    def test_calibration_report_path_resolution_uses_project_root_for_relative_config(self) -> None:
        bundle_dir = Path("/tmp/project/generated/why-ethics")
        resolved = calibrate_embedding_timeout.resolve_calibration_dir(
            bundle_dir,
            report_dir="generated/why-ethics/quality-gate/embedding-calibration",
            project_root=Path("/tmp/project"),
        )
        self.assertEqual(
            resolved,
            Path("/tmp/project/generated/why-ethics/quality-gate/embedding-calibration").resolve(),
        )

    def test_quality_gate_prefers_calibrated_timeout_without_override(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            project_root = Path(temp_dir)
            bundle_dir = project_root / "generated" / "why-ethics"
            calibration_dir = bundle_dir / "quality-gate" / "embedding-calibration"
            calibration_dir.mkdir(parents=True)
            (calibration_dir / "calibration-report.json").write_text(
                json.dumps(
                    {
                        "generated_at": "2026-03-15T00:00:00Z",
                        "status": "calibrated",
                        "recommendation_status": "complete",
                        "requested_runs": 5,
                        "completed_runs": 5,
                        "artifact_status": "generated",
                        "freshness": "fresh",
                        "durations": {"suggested_timeout_seconds": 222},
                    }
                ),
                encoding="utf-8",
            )
            config_path = (
                project_root
                / "skills"
                / "pdf-to-structured-markdown"
                / "references"
                / "why-ethics-quality-gate.json"
            )
            config_path.parent.mkdir(parents=True)
            config_path.write_text("{}\n", encoding="utf-8")

            timeout_seconds, source, calibration = run_quality_gate.resolve_embedding_timeout(
                bundle_dir=bundle_dir,
                config_path=config_path,
                runtime_config={
                    "embedding_timeout_seconds": 180,
                    "calibration": {
                        "report_dir": "generated/why-ethics/quality-gate/embedding-calibration"
                    },
                },
                override_timeout=None,
            )

        self.assertEqual(timeout_seconds, 222)
        self.assertEqual(source, "calibration_report")
        self.assertEqual(calibration["status"], "calibrated")
        self.assertEqual(calibration["recommendation_status"], "complete")

    def test_quality_gate_uses_provisional_calibration_when_timeout_is_present(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            project_root = Path(temp_dir)
            bundle_dir = project_root / "generated" / "why-ethics"
            calibration_dir = bundle_dir / "quality-gate" / "embedding-calibration"
            calibration_dir.mkdir(parents=True)
            (calibration_dir / "calibration-report.json").write_text(
                json.dumps(
                    {
                        "generated_at": "2026-03-15T00:00:00Z",
                        "status": "blocked_by_runtime_failure",
                        "recommendation_status": "provisional",
                        "requested_runs": 5,
                        "completed_runs": 4,
                        "artifact_status": "generated",
                        "freshness": "fresh",
                        "durations": {"suggested_timeout_seconds": 461},
                    }
                ),
                encoding="utf-8",
            )
            config_path = (
                project_root
                / "skills"
                / "pdf-to-structured-markdown"
                / "references"
                / "why-ethics-quality-gate.json"
            )
            config_path.parent.mkdir(parents=True)
            config_path.write_text("{}\n", encoding="utf-8")

            timeout_seconds, source, calibration = run_quality_gate.resolve_embedding_timeout(
                bundle_dir=bundle_dir,
                config_path=config_path,
                runtime_config={
                    "embedding_timeout_seconds": 180,
                    "calibration": {
                        "report_dir": "generated/why-ethics/quality-gate/embedding-calibration"
                    },
                },
                override_timeout=None,
            )

        self.assertEqual(timeout_seconds, 461)
        self.assertEqual(source, "calibration_report_provisional")
        self.assertEqual(calibration["recommendation_status"], "provisional")

    def test_quality_gate_override_timeout_beats_calibration(self) -> None:
        timeout_seconds, source, calibration = run_quality_gate.resolve_embedding_timeout(
            bundle_dir=Path("/tmp/project/generated/why-ethics"),
            config_path=Path(
                "/tmp/project/skills/pdf-to-structured-markdown/references/why-ethics-quality-gate.json"
            ),
            runtime_config={"embedding_timeout_seconds": 180, "calibration": {}},
            override_timeout=77,
        )
        self.assertEqual(timeout_seconds, 77)
        self.assertEqual(source, "cli_override")
        self.assertIsNone(calibration)


if __name__ == "__main__":
    unittest.main()
