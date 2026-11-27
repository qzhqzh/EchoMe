"""The optional local adapter must bound inputs and preserve decision answers."""

import json
import sys
import threading
from http.client import HTTPConnection
from typing import Any

import pytest

from echome import piccolo_server
from echome.piccolo_server import MAX_REQUEST_BYTES, create_server, validate_payload


def request() -> dict[str, Any]:
    return {
        "model": "piccolo-4b",
        "state": {"user_message": "hello", "project_hint": "example"},
        "questions": {
            "action": {
                "type": "choice",
                "instructions": "Choose",
                "criteria": {"retrieve": "needs context", "skip": "does not need context"},
            }
        },
    }


def test_validate_payload_requires_one_bounded_choice() -> None:
    value = request()
    assert validate_payload(value) is value
    for bad in (
        {},
        value | {"model": "other"},
        value | {"questions": {}},
        value | {"questions": {"action": {"type": "noul"}}},
    ):
        with pytest.raises(ValueError):
            validate_payload(bad)


def test_service_warms_model_before_announcing_readiness(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Any
) -> None:
    events: list[str] = []

    class FakeEngine:
        dtype = "float16"

        def __init__(self, model_dir: Any, device: str, dtype: str) -> None:
            events.append("load")

        def predict(self, payload: dict[str, Any]) -> dict[str, Any]:
            events.append("warmup")
            assert validate_payload(payload) == payload
            return {}

    class FakeServer:
        def serve_forever(self) -> None:
            events.append("serve")

        def server_close(self) -> None:
            events.append("close")

    def create(engine: Any, port: int) -> FakeServer:
        events.append("bind")
        return FakeServer()

    monkeypatch.setattr(piccolo_server, "PiccoloEngine", FakeEngine)
    monkeypatch.setattr(piccolo_server, "create_server", create)
    monkeypatch.setattr(sys, "argv", ["piccolo", "--model-dir", str(tmp_path)])
    piccolo_server.main()
    assert events == ["load", "warmup", "bind", "serve", "close"]


def test_adapter_accepts_local_choice_and_never_exposes_input_in_errors() -> None:
    class FakeEngine:
        dtype = "float16"

        def predict(self, payload: dict[str, Any]) -> dict[str, Any]:
            return {
                "model": "piccolo-4b",
                "answers": {
                    "action": {
                        "type": "choice",
                        "choice": "retrieve",
                        "probabilities": {"retrieve": 0.8, "skip": 0.2},
                    }
                },
            }

    try:
        server = create_server(FakeEngine(), 0)
    except PermissionError:
        pytest.skip("The execution sandbox does not permit loopback sockets")
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    connection = HTTPConnection(*server.server_address, timeout=2)
    try:
        connection.request("GET", "/health")
        response = connection.getresponse()
        assert response.status == 200 and json.loads(response.read())["status"] == "ready"

        connection.request("POST", "/v1/systemone", body=json.dumps(request()))
        response = connection.getresponse()
        result = json.loads(response.read())
        assert response.status == 200
        assert result["answers"]["action"]["choice"] == "retrieve"
        assert "hello" not in json.dumps(result)

        connection.request("POST", "/v1/systemone", body=b"sensitive invalid payload")
        response = connection.getresponse()
        assert response.status == 400 and b"sensitive" not in response.read()

        connection.request(
            "POST", "/v1/systemone", headers={"Content-Length": str(MAX_REQUEST_BYTES + 1)}
        )
        response = connection.getresponse()
        assert response.status == 400
        response.read()
    finally:
        connection.close()
        server.shutdown()
        server.server_close()
        worker.join(timeout=2)
