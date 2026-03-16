from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class ProjectPaths:
    project_root: Path

    @property
    def planning_dir(self) -> Path:
        return self.project_root / ".planning"

    @property
    def skill_dir(self) -> Path:
        return self.project_root / "skills" / "pdf-to-structured-markdown"

    @property
    def scripts_dir(self) -> Path:
        return self.skill_dir / "scripts"

    @property
    def references_dir(self) -> Path:
        return self.skill_dir / "references"

    @property
    def generated_root(self) -> Path:
        return self.project_root / "generated"

    @property
    def why_ethics_bundle_dir(self) -> Path:
        return self.generated_root / "why-ethics"

    @property
    def why_ethics_quality_gate_dir(self) -> Path:
        return self.why_ethics_bundle_dir / "quality-gate"

    @property
    def why_ethics_quality_gate_report(self) -> Path:
        return self.why_ethics_quality_gate_dir / "quality-gate-report.json"

    @property
    def challenge_corpus_dir(self) -> Path:
        return self.generated_root / "challenge-corpus"

    @property
    def challenge_corpus_report(self) -> Path:
        return self.challenge_corpus_dir / "smoke-report.json"

    @property
    def backend_comparison_root(self) -> Path:
        return self.generated_root / "embedding-backend-comparison"

    @property
    def remote_backends_config(self) -> Path:
        return self.references_dir / "remote-backends.json"

    @property
    def apple_nl_helper(self) -> Path:
        return self.scripts_dir / "apple_nl_embed.swift"

    @property
    def challenge_corpus_config(self) -> Path:
        return self.references_dir / "challenge-corpus.json"

    @property
    def why_ethics_quality_gate_config(self) -> Path:
        return self.references_dir / "why-ethics-quality-gate.json"

    @property
    def why_ethics_benchmark(self) -> Path:
        return self.references_dir / "why-ethics-retrieval-benchmark.json"

    def bundle_dir(self, book_id: str) -> Path:
        return self.generated_root / book_id


DEFAULT_PROJECT_ROOT = Path(__file__).resolve().parents[3]


def resolve_project_root(project_root: Path | None = None) -> Path:
    return (project_root or DEFAULT_PROJECT_ROOT).resolve()


def project_paths(project_root: Path | None = None) -> ProjectPaths:
    return ProjectPaths(project_root=resolve_project_root(project_root))
