"""Base class for target adapters."""

from abc import ABC, abstractmethod
from pathlib import Path

MARKER_BEGIN = "<!-- echome:begin -->"
MARKER_END = "<!-- echome:end -->"


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

    def _inject_marker_content(self, file_path: Path, content: str) -> None:
        """Inject content into a file using marker blocks.

        If the file already exists:
          - If it has markers: replace only the marker block
          - If no markers: append the marker block at the end
        If the file doesn't exist: create it with just the marker block.
        """
        file_path.parent.mkdir(parents=True, exist_ok=True)

        if file_path.exists():
            existing = file_path.read_text()
            if MARKER_BEGIN in existing:
                # Replace existing marker block
                before = existing.split(MARKER_BEGIN)[0]
                after = existing.split(MARKER_END)[1] if MARKER_END in existing else ""
                new_content = f"{before}{content}{after}"
            else:
                # Append marker block at end
                new_content = f"{existing.rstrip()}\n\n{content}\n"
        else:
            new_content = f"{content}\n"

        file_path.write_text(new_content)

    def _remove_marker_content(self, file_path: Path) -> None:
        """Remove marker block from a file. Delete file if nothing remains."""
        if not file_path.exists():
            return

        existing = file_path.read_text()
        if MARKER_BEGIN in existing and MARKER_END in existing:
            before = existing.split(MARKER_BEGIN)[0]
            after = existing.split(MARKER_END)[1]
            cleaned = f"{before}{after}".strip()
            if cleaned:
                file_path.write_text(cleaned + "\n")
            else:
                file_path.unlink()

    def inject_global(self, content: str) -> None:
        """Inject content into the global rules file using markers."""
        self._inject_marker_content(self.global_file, content)

    def inject_project(self, content: str, project_dir: Path) -> None:
        """Inject content into project-level file using markers.

        Uses the same marker strategy as global — safe to call on files
        that already have user-written content.
        """
        self._inject_marker_content(self.project_file(project_dir), content)

    def eject_global(self) -> None:
        """Remove EchoMe content from global file."""
        self._remove_marker_content(self.global_file)

    def eject_project(self, project_dir: Path) -> None:
        """Remove EchoMe content from project file."""
        self._remove_marker_content(self.project_file(project_dir))
