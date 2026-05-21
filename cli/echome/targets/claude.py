"""Claude Code target adapter."""

from pathlib import Path

from echome.targets.base import BaseTarget


class ClaudeCodeTarget(BaseTarget):
    """Adapter for Claude Code (CLAUDE.md)."""

    @property
    def name(self) -> str:
        return "Claude Code"

    @property
    def global_file(self) -> Path:
        return Path.home() / ".claude" / "CLAUDE.md"

    def project_file(self, project_dir: Path) -> Path:
        return project_dir / ".echome" / "echome-rules.md"

    def detect(self, project_dir: Path) -> bool:
        """Detect Claude Code by presence of CLAUDE.md or .claude/ directory."""
        return (
            (project_dir / "CLAUDE.md").exists()
            or (project_dir / ".claude").exists()
            or self.global_file.exists()
        )
