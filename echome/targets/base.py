"""Base class for target adapters."""

from abc import ABC, abstractmethod
from pathlib import Path


class BaseTarget(ABC):
    """Abstract base for AI CLI target adapters."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Human-readable target name."""
        ...

    @property
    @abstractmethod
    def global_file(self) -> Path:
        """Path to the global rules file (e.g. ~/.claude/CLAUDE.md)."""
        ...

    @abstractmethod
    def project_file(self, project_dir: Path) -> Path:
        """Path to the project-level rules file."""
        ...

    @abstractmethod
    def detect(self, project_dir: Path) -> bool:
        """Check if this target is active in the given directory."""
        ...

    def inject_global(self, content: str) -> None:
        """Inject content into the global rules file using markers."""
        file_path = self.global_file
        file_path.parent.mkdir(parents=True, exist_ok=True)

        marker_begin = "<!-- echome:begin -->"
        marker_end = "<!-- echome:end -->"

        if file_path.exists():
            existing = file_path.read_text()
            # Replace existing marker block
            if marker_begin in existing:
                before = existing.split(marker_begin)[0]
                after = existing.split(marker_end)[1] if marker_end in existing else ""
                new_content = f"{before}{content}{after}"
            else:
                # Append marker block
                new_content = f"{existing}\n\n{content}\n"
        else:
            new_content = f"{content}\n"

        file_path.write_text(new_content)

    def inject_project(self, content: str, project_dir: Path) -> None:
        """Inject content into project-level file using markers."""
        file_path = self.project_file(project_dir)
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_text(content)

    def eject_global(self) -> None:
        """Remove EchoMe content from global file."""
        file_path = self.global_file
        if not file_path.exists():
            return

        marker_begin = "<!-- echome:begin -->"
        marker_end = "<!-- echome:end -->"
        existing = file_path.read_text()

        if marker_begin in existing and marker_end in existing:
            before = existing.split(marker_begin)[0]
            after = existing.split(marker_end)[1]
            cleaned = f"{before}{after}".strip()
            if cleaned:
                file_path.write_text(cleaned + "\n")
            else:
                file_path.unlink()

    def eject_project(self, project_dir: Path) -> None:
        """Remove EchoMe project file."""
        echome_dir = project_dir / ".echome"
        if echome_dir.exists():
            for f in echome_dir.iterdir():
                if f.name.startswith("echome-"):
                    f.unlink()
