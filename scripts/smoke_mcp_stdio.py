"""Verify installed CLI/module MCP handshakes without contacting the Hub."""

from __future__ import annotations

import argparse
import json
import os
import queue
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path
from typing import Any


def smoke(python: str, entry: str, profile: str, timeout: float = 15) -> dict[str, Any]:
    executable = Path(python).absolute()
    command = (
        [str(executable), "-m", "echome_mcp"]
        if entry == "module"
        else [
            str(executable.parent / ("echome.exe" if os.name == "nt" else "echome")),
            "mcp",
            "serve",
        ]
    )
    messages: queue.Queue[tuple[str, str]] = queue.Queue()

    def read_lines(stream: Any, name: str) -> None:
        for line in stream:
            messages.put((name, line))
        messages.put((name, ""))

    # A different cwd ensures the built-wheel check cannot import the source checkout.
    with tempfile.TemporaryDirectory(prefix="echome-mcp-smoke-") as cwd:
        process = subprocess.Popen(
            command,
            cwd=cwd,
            env={**os.environ, "ECHOME_MCP_PROFILE": profile},
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
        )
        assert process.stdin and process.stdout and process.stderr
        for stream, name in ((process.stdout, "stdout"), (process.stderr, "stderr")):
            threading.Thread(target=read_lines, args=(stream, name), daemon=True).start()
        diagnostics: list[str] = []

        def send(payload: dict[str, Any]) -> None:
            assert process.stdin
            process.stdin.write(json.dumps(payload) + "\n")
            process.stdin.flush()

        def receive(request_id: int) -> dict[str, Any]:
            deadline = time.monotonic() + timeout
            while (remaining := deadline - time.monotonic()) > 0:
                try:
                    stream, line = messages.get(timeout=remaining)
                except queue.Empty:
                    break
                if stream == "stderr":
                    if line:
                        diagnostics.append(line.strip())
                        del diagnostics[:-10]
                    continue
                if not line:
                    raise RuntimeError(f"MCP stdout closed: {diagnostics}")
                message = json.loads(line)
                if message.get("id") == request_id:
                    if "error" in message:
                        raise RuntimeError(f"MCP request {request_id}: {message['error']}")
                    return message["result"]
            raise TimeoutError(
                f"{entry}/{profile}: request {request_id} timed out after {timeout}s; "
                f"exit={process.poll()}, stderr={diagnostics}. "
                "Compare in a normal terminal if sandbox stdio/thread I/O is restricted."
            )

        try:
            send(
                {
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "initialize",
                    "params": {
                        "protocolVersion": "2025-11-25",
                        "capabilities": {},
                        "clientInfo": {"name": "echome-install-smoke", "version": "1"},
                    },
                }
            )
            initialized = receive(1)
            send({"jsonrpc": "2.0", "method": "notifications/initialized"})
            send({"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}})
            names = {item["name"] for item in receive(2)["tools"]}
            required = {"echome_capabilities", "echome_context", "echome_remember"}
            if not required <= names:
                raise RuntimeError(f"Missing tools: {required - names}")
            if ("echome_search_summary" in names) != (profile == "full"):
                raise RuntimeError("Advertised tools do not match the requested profile")
            send(
                {
                    "jsonrpc": "2.0",
                    "id": 3,
                    "method": "tools/call",
                    "params": {
                        "name": "echome_capabilities",
                        "arguments": {"format": "json"},
                    },
                }
            )
            result = receive(3)
            if result.get("isError"):
                raise RuntimeError("Capability discovery failed")
            capabilities = json.loads(
                next(item["text"] for item in result["content"] if item["type"] == "text")
            )
            return {
                "entry": entry,
                "profile": profile,
                "tools": len(names),
                "server": initialized["serverInfo"],
                "capabilities_version": capabilities["capabilities_version"],
            }
        finally:
            process.stdin.close()
            try:
                process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                process.terminate()
                try:
                    process.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()
            process.stdout.close()
            process.stderr.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--python", default=sys.executable)
    parser.add_argument("--entry", choices=["cli", "module", "all"], default="all")
    parser.add_argument("--profile", choices=["core", "full", "all"], default="all")
    parser.add_argument("--timeout", type=float, default=15)
    args = parser.parse_args()
    for entry in ("cli", "module") if args.entry == "all" else (args.entry,):
        for profile in ("core", "full") if args.profile == "all" else (args.profile,):
            print(json.dumps(smoke(args.python, entry, profile, args.timeout)), flush=True)


if __name__ == "__main__":
    main()
