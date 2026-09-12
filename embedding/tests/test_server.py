"""Embedding runtime guard and request boundary tests."""

import unittest
from unittest.mock import patch

import server
from pydantic import ValidationError


class EmbeddingServerTests(unittest.IsolatedAsyncioTestCase):
    def test_request_rejects_text_over_configured_limit(self) -> None:
        with self.assertRaises(ValidationError):
            server.EmbedRequest(texts=["a" * (server.MAX_TEXT_CHARS + 1)])

    async def test_cuda_configuration_fails_fast_when_unavailable(self) -> None:
        with (
            patch.object(server, "DEVICE", "cuda"),
            patch.object(server, "USE_FP16", True),
            patch.object(server.torch.cuda, "is_available", return_value=False),
            self.assertRaisesRegex(RuntimeError, "CUDA device"),
        ):
            async with server.lifespan(server.app):
                self.fail("lifespan should not start without CUDA")


if __name__ == "__main__":
    unittest.main()
