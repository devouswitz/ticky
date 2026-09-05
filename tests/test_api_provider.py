import contextlib
import io
import json
import os
import subprocess
import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ticky_cli.api_provider import build_request, extract_response, generate, validate_spec
from ticky_cli.config import AppPaths, ConfigStore, account_record, agent_record, new_config, write_env_file
from ticky_cli.providers import build_invocation, run_agent
from ticky_cli.setup_wizard import run_setup_wizard


class ApiAdapterTests(unittest.TestCase):
    def spec(self, protocol="openai-chat"):
        return {"protocol": protocol, "endpoint": "https://example.com/v1/generate"}

    def test_protocol_request_shapes_and_auth_headers(self):
        for protocol, field, header in (
            ("openai-chat", "messages", "Authorization"),
            ("openai-responses", "input", "Authorization"),
            ("anthropic", "messages", "X-api-key"),
            ("gemini", "contents", "X-goog-api-key"),
        ):
            with self.subTest(protocol=protocol):
                request = build_request(self.spec(protocol), "any/model", 'hello "world"', "private-key")
                payload = json.loads(request.data)
                self.assertIn(field, payload)
                self.assertIn("private-key", request.get_header(header))
                self.assertNotIn("private-key", request.full_url)
                self.assertNotIn("private-key", request.data.decode())

    def test_response_blocks_extract_only_answer_text(self):
        cases = [
            ("openai-chat", {"choices": [{"message": {"content": "hello"}}]}),
            ("openai-responses", {"status": "completed", "output": [{"type": "message", "content": [{"type": "output_text", "text": "hello"}]}]}),
            ("anthropic", {"content": [{"type": "thinking", "text": "private reasoning"}, {"type": "text", "text": "hello"}]}),
            ("gemini", {"candidates": [{"content": {"parts": [{"thought": True, "text": "private reasoning"}, {"text": "hello"}]}}]}),
        ]
        for protocol, response in cases:
            with self.subTest(protocol=protocol):
                self.assertEqual(extract_response(self.spec(protocol), response), "hello")

    def test_custom_json_adapter_and_pointer_escape(self):
        spec = {**self.spec("custom"), "request": {"deployment": "{model}", "query": "{prompt}"},
                "response_pointer": "/answer~1text/0/value"}
        request = build_request(spec, "future-model", "Keep {model} literal")
        self.assertEqual(json.loads(request.data)["query"], "Keep {model} literal")
        self.assertEqual(extract_response(spec, {"answer/text": [{"value": "done"}]}), "done")

    def test_local_endpoints_supported_but_remote_credentials_require_tls(self):
        for endpoint in ("http://127.0.0.1:9999/chat", "http://[::1]:9999/chat", "http://localhost:9999/chat"):
            validate_spec({**self.spec(), "endpoint": endpoint})
        for endpoint in ("http://remote.example/chat", "https://user:key@example.com/chat", "file:///tmp/a", "https://example.com/#fragment"):
            with self.subTest(endpoint=endpoint), self.assertRaises(ValueError):
                validate_spec({**self.spec(), "endpoint": endpoint})

    def test_incomplete_and_malformed_responses_are_not_successes(self):
        for response in ({}, {"choices": []}, {"choices": [{"finish_reason": "length", "message": {"content": "partial"}}]}):
            with self.assertRaises(ValueError):
                extract_response(self.spec(), response)

    def test_endpoint_account_does_not_inherit_another_api_key(self):
        with tempfile.TemporaryDirectory() as directory:
            paths = AppPaths(Path(directory))
            account = account_record("endpoint", "api", auth="api-key")
            agent = agent_record("endpoint", name="vale")
            agent["model"] = "any-model"
            with mock.patch.dict(os.environ, {"TICKY_API_KEY": "unrelated-key"}):
                with self.assertRaisesRegex(ValueError, "API key is not set"):
                    build_invocation(paths, account, agent, "private task")
                write_env_file(paths.account_env("endpoint"), {"TICKY_API_KEY": "account-key"})
                invocation = build_invocation(paths, account, agent, "private task")
            self.assertEqual(invocation.env["TICKY_API_KEY"], "account-key")
            self.assertNotIn("private task", " ".join(invocation.command))
            self.assertNotIn("account-key", invocation.stdin)


class HttpIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.requests = []
        requests = self.requests

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                data = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                requests.append((self.path, self.headers, data))
                if self.path == "/redirect":
                    self.send_response(302)
                    self.send_header("Location", "/should-not-be-called")
                    self.end_headers()
                    return
                if self.path == "/error":
                    self.send_response(401)
                    self.end_headers()
                    self.wfile.write(b"echoed-secret-key")
                    return
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"choices": [{"message": {"content": "endpoint answer"}}]}).encode())

            def log_message(self, *args):
                pass

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base = f"http://127.0.0.1:{self.server.server_port}"

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)

    def test_subprocess_dispatch_reaches_endpoint_with_context(self):
        with tempfile.TemporaryDirectory() as directory:
            paths = AppPaths(Path(directory))
            account = account_record("local-api", "api", auth="inherit")
            account["api"] = {"protocol": "openai-chat", "endpoint": self.base + "/chat"}
            agent = agent_record("local-api", name="vale")
            agent.update(model="some/future-model", workdir=directory)
            result = run_agent(paths, account, agent, "Check the design", "Earlier agent found a bug")
        self.assertTrue(result.ok, result.text)
        self.assertEqual(result.text, "endpoint answer")
        request = self.requests[0][2]
        self.assertEqual(request["model"], "some/future-model")
        self.assertIn("Earlier agent found a bug", request["messages"][0]["content"])

    def test_cli_first_account_setup_and_team_reach_the_endpoint(self):
        wrapper = Path(__file__).resolve().parents[1] / "ticky"
        with tempfile.TemporaryDirectory() as directory:
            env = dict(os.environ, TICKY_HOME=directory)
            def cli(*args):
                result = subprocess.run([sys.executable, str(wrapper), *args], env=env,
                                        capture_output=True, text=True, timeout=15)
                self.assertEqual(result.returncode, 0, result.stderr)
                return result.stdout
            cli("account", "add", "--id", "endpoint", "--provider", "api", "--auth", "inherit",
                "--protocol", "openai-chat", "--endpoint", self.base + "/chat")
            for name in ("reviewer", "editor"):
                cli("agent", "add", name, "--account", "endpoint", "--model", "future-model")
            self.assertIn("cli=not required", cli("status"))
            result = cli("team", "reviewer,editor", "Review the design")
            self.assertIn("## editor (ok)", result)
            self.assertEqual(len(self.requests), 2)
            self.assertIn("endpoint answer", self.requests[1][2]["messages"][0]["content"])

    def test_redirect_is_not_followed_and_error_body_is_not_echoed(self):
        for route in ("/redirect", "/error"):
            with self.subTest(route=route), self.assertRaises(RuntimeError) as raised:
                generate({"protocol": "openai-chat", "endpoint": self.base + route}, "model", "prompt", "secret")
            self.assertNotIn("secret", str(raised.exception))
        self.assertEqual([request[0] for request in self.requests], ["/redirect", "/error"])

    def test_guided_api_setup_creates_callable_named_agent_without_a_cli(self):
        with tempfile.TemporaryDirectory() as directory:
            store = ConfigStore(AppPaths(Path(directory)))
            answers = ["Local API", "openai-chat", self.base + "/chat", "custom-model"]
            with mock.patch("builtins.input", side_effect=answers), mock.patch(
                "getpass.getpass", return_value="",
            ), contextlib.redirect_stdout(io.StringIO()):
                run_setup_wizard(store, requested=["api"], quick=True)
            config = store.load()
            agent = config["profiles"]["default"]["agents"][0]
            self.assertEqual(agent["model"], "custom-model")
            self.assertEqual(agent["access"], "read-only")
            result = run_agent(store.paths, config["accounts"][agent["account"]], agent, "hello")
            self.assertTrue(result.ok, result.text)

    def test_team_relays_between_custom_cli_and_http_api(self):
        from ticky_cli.team import run_team
        with tempfile.TemporaryDirectory() as directory:
            paths = AppPaths(Path(directory))
            config = new_config([])
            first = account_record("bridge", "command")
            first["command"] = [sys.executable, "-c", "import sys; sys.stdin.read(); print('BRIDGE_FINDING: missing boundary check')"]
            second = account_record("endpoint", "api")
            second["api"] = {"protocol": "openai-chat", "endpoint": self.base + "/chat"}
            config["accounts"] = {"bridge": first, "endpoint": second}
            a = agent_record("bridge", name="builder")
            a.update(access="full", workdir=directory)
            b = agent_record("endpoint", name="reviewer")
            b.update(model="any-model", workdir=directory)
            config["profiles"]["default"]["agents"] = [a, b]
            ConfigStore(paths).save(config)
            result = run_team(config, paths, ["builder", "reviewer"], "Check the result")
        self.assertTrue(result.ok, result.text())
        self.assertIn("BRIDGE_FINDING", self.requests[0][2]["messages"][0]["content"])
        self.assertIn("endpoint answer", result.text())

    def test_custom_command_does_not_interpret_prompt_as_shell_code(self):
        with tempfile.TemporaryDirectory() as directory:
            paths = AppPaths(Path(directory))
            account = account_record("bridge", "command")
            account["command"] = [sys.executable, "-c", "import sys; print(sys.stdin.read())"]
            agent = agent_record("bridge", name="bridge")
            agent.update(access="full", workdir=directory)
            result = run_agent(paths, account, agent, "literal $(touch SHOULD_NOT_EXIST)")
            self.assertTrue(result.ok, result.text)
            self.assertIn("$(touch SHOULD_NOT_EXIST)", result.text)
            self.assertFalse((Path(directory) / "SHOULD_NOT_EXIST").exists())


if __name__ == "__main__":
    unittest.main()
