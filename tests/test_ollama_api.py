import io
import json
import unittest
from pathlib import Path
import sys
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from ticky_cli.ollama_api import generate


class FakeResponse:
    def __init__(self, value):
        self.value = value

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self):
        return json.dumps(self.value).encode("utf-8")


class OllamaApiTests(unittest.TestCase):
    def test_generate_uses_https_bearer_auth_and_nonstreaming_payload(self):
        captured = {}

        def open_request(request, timeout):
            captured["request"] = request
            captured["timeout"] = timeout
            return FakeResponse({"response": "Cloud reply"})

        with mock.patch("ticky_cli.ollama_api.urllib.request.urlopen", side_effect=open_request):
            text = generate(
                "gpt-oss:120b",
                "Explain this",
                "ollama-secret",
                think="high",
            )
        self.assertEqual(text, "Cloud reply")
        request = captured["request"]
        self.assertEqual(request.full_url, "https://ollama.com/api/generate")
        self.assertEqual(request.get_header("Authorization"), "Bearer ollama-secret")
        payload = json.loads(request.data)
        self.assertEqual(payload["model"], "gpt-oss:120b")
        self.assertEqual(payload["prompt"], "Explain this")
        self.assertEqual(payload["think"], "high")
        self.assertFalse(payload["stream"])

    def test_generate_rejects_missing_key_and_plain_http(self):
        with self.assertRaisesRegex(ValueError, "OLLAMA_API_KEY"):
            generate("model", "prompt", "")
        with self.assertRaisesRegex(ValueError, "https"):
            generate("model", "prompt", "secret", base_url="http://example.com")

    def test_generate_rejects_empty_provider_response(self):
        with mock.patch(
            "ticky_cli.ollama_api.urllib.request.urlopen",
            return_value=FakeResponse({"response": ""}),
        ):
            with self.assertRaisesRegex(RuntimeError, "no response text"):
                generate("model", "prompt", "secret")


if __name__ == "__main__":
    unittest.main()
