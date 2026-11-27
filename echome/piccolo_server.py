"""Optional loopback-only System One adapter for the full Piccolo checkpoint.

The model's published ``piccolo_inference.py`` and ``piccolo_layout.py`` supply
the decision layout. This adapter keeps the same bidirectional attention and
candidate-token readout used in EchoMe's local evaluation. PyTorch and
Transformers are optional runtime dependencies, not CLI dependencies.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace
from typing import Any

MAX_REQUEST_BYTES = 65_536
MAX_CONTEXT_TOKENS = 8_192


class PiccoloEngine:
    def __init__(self, model_dir: Path, device: str, dtype: str) -> None:
        # Import the publisher's layout from the explicitly configured local model.
        sys.path.insert(0, str(model_dir))
        import piccolo_inference  # type: ignore[import-not-found]
        import piccolo_layout  # type: ignore[import-not-found]
        import torch  # type: ignore[import-not-found]
        import transformers  # type: ignore[import-not-found]
        from transformers.models.qwen3_5 import modeling_qwen3_5  # type: ignore[import-not-found]

        descriptor = json.loads((model_dir / "decision-inference.json").read_text())
        if (
            descriptor.get("attention_mode") != "bidirectional_prompt"
            or descriptor.get("prompt_variant") != "flex_twice"
        ):
            raise ValueError("Unsupported Piccolo inference contract")
        if dtype == "auto":
            if device.startswith("cuda"):
                dtype = (
                    "bfloat16"
                    if torch.cuda.is_bf16_supported(including_emulation=False)
                    else "float16"
                )
            else:
                dtype = "float32"
        self.dtype = dtype
        self.device = device
        self.torch = torch
        torch.set_num_threads(4)
        tokenizer = transformers.AutoTokenizer.from_pretrained(model_dir, local_files_only=True)
        self.compiler = piccolo_inference.FlexCompiler(
            tokenizer,
            SimpleNamespace(
                Layout=piccolo_layout.Layout, render_question=piccolo_layout.render_question
            ),
            max_context=MAX_CONTEXT_TOKENS,
        )
        self.model = transformers.AutoModelForImageTextToText.from_pretrained(
            model_dir,
            dtype=getattr(torch, dtype),
            device_map={"": device},
            attn_implementation="sdpa",
            local_files_only=True,
        ).eval()
        self.decoder = self.model.model.language_model
        self.head = self.model.get_output_embeddings()
        self.hook_calls = 0

        def full_attention_mask(
            module: Any, positional: Any, kwargs: dict[str, Any]
        ) -> tuple[Any, dict[str, Any]]:
            hidden = kwargs["hidden_states"]
            length = hidden.shape[1]
            kwargs["attention_mask"] = torch.zeros(
                (hidden.shape[0], 1, length, length), dtype=hidden.dtype, device=hidden.device
            )
            self.hook_calls += 1
            return positional, kwargs

        self.hooks = [
            module.register_forward_pre_hook(full_attention_mask, with_kwargs=True)
            for module in self.decoder.modules()
            if isinstance(module, modeling_qwen3_5.Qwen3_5Attention)
        ]
        expected = self.decoder.config.layer_types.count("full_attention")
        if len(self.hooks) != expected or not expected:
            raise ValueError("Piccolo full-attention layer count mismatch")

    def predict(self, payload: dict[str, Any]) -> dict[str, Any]:
        rows, _ = self.compiler.compile(payload)
        if len(rows) != 1:
            raise ValueError("Exactly one decision question is supported")
        row = rows[0]
        torch = self.torch
        ids = torch.tensor([row.input_ids], device=self.device)
        before = self.hook_calls
        with torch.inference_mode():
            hidden = self.decoder(input_ids=ids, attention_mask=None, use_cache=False)
            last = hidden.last_hidden_state[0, -1].float()
            weights = self.head.weight[torch.tensor(row.candidate_ids, device=self.device)].float()
            values = torch.softmax(torch.mv(weights, last), dim=-1).cpu().tolist()
        if self.hook_calls - before != len(self.hooks) or not all(
            math.isfinite(value) for value in values
        ):
            raise ValueError("Invalid Piccolo attention or probabilities")
        probabilities = dict(zip(row.option_keys, values, strict=True))
        return {
            "model": "piccolo-4b",
            "answers": {
                row.question_id: {
                    "type": "choice",
                    "choice": max(probabilities, key=probabilities.__getitem__),
                    "probabilities": probabilities,
                }
            },
        }


def validate_payload(payload: Any) -> dict[str, Any]:
    """Accept one bounded text Choice request; never silently truncate input."""
    if not isinstance(payload, dict) or payload.get("model") != "piccolo-4b":
        raise ValueError("Unknown model")
    if not isinstance(payload.get("state"), (str, dict)):
        raise ValueError("Invalid state")
    questions = payload.get("questions")
    if not isinstance(questions, dict) or len(questions) != 1:
        raise ValueError("Exactly one question is required")
    name, question = next(iter(questions.items()))
    if not isinstance(name, str) or not 1 <= len(name) <= 80 or not isinstance(question, dict):
        raise ValueError("Invalid question")
    criteria = question.get("criteria")
    if (
        question.get("type") != "choice"
        or not isinstance(question.get("instructions"), str)
        or not isinstance(criteria, dict)
        or not 2 <= len(criteria) <= 8
        or any(
            not isinstance(key, str) or not isinstance(value, str)
            for key, value in criteria.items()
        )
    ):
        raise ValueError("A bounded Choice question is required")
    return payload


def create_server(engine: Any, port: int) -> ThreadingHTTPServer:
    """Bind only loopback, serialize GPU work, and suppress request logs."""
    lock = threading.Lock()

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, format: str, *args: Any) -> None:
            pass

        def respond(self, status: int, body: dict[str, Any]) -> None:
            raw = json.dumps(body, ensure_ascii=False, allow_nan=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

        def do_GET(self) -> None:
            if self.path == "/health":
                self.respond(200, {"status": "ready", "model": "piccolo-4b", "dtype": engine.dtype})
            else:
                self.respond(404, {"error": "not_found"})

        def do_POST(self) -> None:
            if self.path != "/v1/systemone":
                self.respond(404, {"error": "not_found"})
                return
            try:
                length = int(self.headers.get("Content-Length", "0"))
                if not 1 <= length <= MAX_REQUEST_BYTES:
                    raise ValueError("Invalid request size")
                payload = validate_payload(json.loads(self.rfile.read(length)))
            except (ValueError, TypeError, UnicodeDecodeError, RecursionError):
                self.respond(400, {"error": "invalid_request"})
                return
            if not lock.acquire(blocking=False):
                self.respond(503, {"error": "busy"})
                return
            try:
                result = engine.predict(payload)
            except Exception:
                self.respond(500, {"error": "inference_failed"})
                return
            finally:
                lock.release()
            self.respond(200, result)

    return ThreadingHTTPServer(("127.0.0.1", port), Handler)


def main() -> None:
    parser = argparse.ArgumentParser(description="Serve a local Piccolo decision model on loopback")
    parser.add_argument("--model-dir", type=Path, default=Path("/data/models/Piccolo-4B"))
    parser.add_argument("--device", default="cuda:0")
    parser.add_argument(
        "--dtype", choices=["auto", "float16", "bfloat16", "float32"], default="auto"
    )
    parser.add_argument("--port", type=int, default=18643)
    args = parser.parse_args()
    if not 1 <= args.port <= 65535:
        parser.error("port must be between 1 and 65535")
    engine = PiccoloEngine(args.model_dir.resolve(), args.device, args.dtype)
    engine.predict(
        {
            "model": "piccolo-4b",
            "state": "Warm up the local decision model.",
            "questions": {
                "action": {
                    "type": "choice",
                    "instructions": "Is historical context required?",
                    "criteria": {"retrieve": "yes", "skip": "no"},
                }
            },
        }
    )
    server = create_server(engine, args.port)
    print(f"Piccolo ready on 127.0.0.1:{args.port} ({engine.dtype})", flush=True)
    try:
        server.serve_forever()
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
