"""Codex CLI target adapter."""

from pathlib import Path

from echome.targets.base import BaseTarget


class CodexTarget(BaseTarget):
    """Adapter for Codex CLI (AGENTS.md)."""

    @property
    def name(self) -> str:
        return "Codex CLI"

    @property
    def global_file(self) -> Path:
        return Path.home() / ".codex" / "AGENTS.md"

    def project_file(self, project_dir: Path) -> Path:
        """Project-level: write directly into the project's AGENTS.md (marker area)."""
        return project_dir / "AGENTS.md"

    def detect(self, project_dir: Path) -> bool:
        """Detect Codex CLI by presence of AGENTS.md or .codex/ directory."""
        return (
            (project_dir / "AGENTS.md").exists()
            or (project_dir / ".codex").exists()
            or self.global_file.exists()
        )
