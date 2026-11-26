"""Small hook executable: avoid loading the interactive CLI on every user turn."""

import json
import os
import sys
from pathlib import Path
from typing import Any

MAX_INPUT_BYTES = 65536


def handle(raw: bytes, managed_by: str = "echome-v1") -> dict[str, Any]:
    """Keep malformed input and all failures silent; the main task always proceeds."""
    try:
        if managed_by != "echome-v1" or len(raw) > MAX_INPUT_BYTES:
            return {}
        event = json.loads(raw)
        if not isinstance(event, dict):
            return {}
        import asyncio

        from echome.core.config import Config
        from echome.core.memory_gate import GateSettings, default_api_key_env
        from echome.core.task_hook import run_hook

        provider = os.getenv("ECHOME_HOOK_GATE_PROVIDER", "rules")
        gate = GateSettings.model_validate(
            {
                "provider": provider,
                "base_url": os.getenv("ECHOME_HOOK_GATE_URL"),
                "model": os.getenv("ECHOME_HOOK_GATE_MODEL"),
                "api_key": os.getenv(default_api_key_env(provider), ""),
                "timeout_seconds": 1.0,
            }
        )
        return asyncio.run(
            run_hook(
                event,
                config=Config.load(),
                state_dir=Path.home() / ".echome" / "hook-state",
                gate=gate,
            )
        )
    except Exception:
        # Never echo raw task text, authentication material or a remote error.
        return {}


def main() -> None:
    """Use the same fixed command marker as the interactive hook subcommand."""
    expected = ["hook", "codex", "--managed-by", "echome-v1"]
    output = handle(sys.stdin.buffer.read(MAX_INPUT_BYTES + 1)) if sys.argv[1:] == expected else {}
    print(json.dumps(output, ensure_ascii=False))


if __name__ == "__main__":
    main()
