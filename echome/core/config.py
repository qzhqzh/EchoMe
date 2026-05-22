"""Configuration management for EchoMe CLI."""

from pathlib import Path

import yaml
from pydantic import BaseModel, Field

ECHOME_DIR = Path.home() / ".echome"
CONFIG_FILE = ECHOME_DIR / "config.yaml"
VAULT_DIR = ECHOME_DIR / "vault"
PENDING_DIR = ECHOME_DIR / "pending"
STATE_DIR = ECHOME_DIR / ".state"


class Config(BaseModel):
    """EchoMe CLI configuration."""

    hub_url: str = Field(default="https://echome.qzhqzh.com")
    token: str = Field(default="")
    default_layer: str = Field(default="L2")
    editor: str = Field(default="")

    @classmethod
    def load(cls) -> "Config":
        """Load config from ~/.echome/config.yaml."""
        if not CONFIG_FILE.exists():
            return cls()
        with open(CONFIG_FILE) as f:
            data = yaml.safe_load(f) or {}
        return cls(**data)

    def save(self) -> None:
        """Save config to ~/.echome/config.yaml."""
        import platform

        ECHOME_DIR.mkdir(parents=True, exist_ok=True)
        CONFIG_FILE.write_text(yaml.dump(self.model_dump(), default_flow_style=False))
        # Secure the config file (contains token) — Unix only
        if platform.system() != "Windows":
            CONFIG_FILE.chmod(0o600)


def ensure_vault_dirs() -> None:
    """Create vault directory structure if it doesn't exist."""
    dirs = [
        VAULT_DIR / "identity",
        VAULT_DIR / "guardrail",
        VAULT_DIR / "reasoning",
        VAULT_DIR / "method",
        VAULT_DIR / "stack",
        VAULT_DIR / "style",
        VAULT_DIR / "decision",
        VAULT_DIR / "context",
        VAULT_DIR / "template",
        VAULT_DIR / "project",
        PENDING_DIR,
        STATE_DIR,
    ]
    for d in dirs:
        d.mkdir(parents=True, exist_ok=True)
