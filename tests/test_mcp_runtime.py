import io
import json
import os
import subprocess
import tempfile
import time
import unittest
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
TICKY = ROOT / "ticky"
sys.path.insert(0, str(ROOT / "src"))

from ticky_cli.config import AppPaths, account_record, agent_record, new_config
from ticky_cli.mcp import McpServer
from ticky_cli.runtime import append_log, read_log_tail, read_state, render_activity, write_state


class McpAndActivityBehaviorTests(unittest.TestCase):
    def mock_config(self):
        config = new_config([])
        config["accounts"]["mock-default"] = account_record("mock-default", "mock", "Mock")
        agent = agent_record(
            "mock-default",
            name="vale",
            display="Vale",
            specialty="UI testing and browser QA.",
        )
        agent.update({
            "model": "gpt-test",
            "thinking": "high",
            "routing_note": "Call Vale for visible product behavior.",
            "priority": 1,
        })
        config["profiles"]["default"]["agents"] = [agent]
        return config

    def test_mcp_lists_descriptive_agent_tool_and_dispatches_mock_call(self):
        with tempfile.TemporaryDirectory() as temporary:
            paths = AppPaths(Path(temporary))
            sink = io.StringIO()
            server = McpServer(self.mock_config(), paths, sink=sink)
            server.handle({
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2025-06-18",
                    "clientInfo": {"name": "test-harness"},
                },
            })
            server.handle({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
            server.handle({
                "jsonrpc": "2.0",
                "id": 3,
                "method": "tools/call",
                "params": {
                    "name": "ask_vale",
                    "arguments": {
                        "task": "Check the setup screen",
                        "reason": "Vale specializes in UI testing",
                    },
                },
            })
            for worker in server._workers:
                worker.join(timeout=10)
            responses = {value["id"]: value for value in map(json.loads, sink.getvalue().splitlines())}

            tools = responses[2]["result"]["tools"]
            vale = next(tool for tool in tools if tool["name"] == "ask_vale")
            self.assertIn("UI testing", vale["description"])
            self.assertIn("mock-default", vale["description"])
            self.assertIn("thinking: high", vale["description"])
            self.assertEqual(vale["inputSchema"]["required"], ["task", "reason"])
            self.assertFalse(responses[3]["result"]["isError"])
            self.assertIn("[mock:vale]", responses[3]["result"]["content"][0]["text"])

            entries = read_log_tail(paths, 5)
            self.assertEqual(len(entries), 1)
            self.assertEqual(entries[0]["boss"], "test-harness")
            self.assertEqual(entries[0]["profile"], "default")
            self.assertEqual(entries[0]["account"], "mock-default")
            self.assertEqual(entries[0]["thinking"], "high")
            self.assertEqual(read_state(paths)["running"], [])

    def test_state_merges_independent_sessions(self):
        with tempfile.TemporaryDirectory() as temporary:
            paths = AppPaths(Path(temporary))
            vale = {"agent": "Vale", "provider": "codex", "account": "work", "reason": "UI"}
            rook = {"agent": "Rook", "provider": "claude", "account": "audit", "reason": "Review"}
            write_state(paths, [vale], "session-a")
            write_state(paths, [rook], "session-b")
            self.assertEqual(
                {call["agent"] for call in read_state(paths)["running"]},
                {"Vale", "Rook"},
            )
            write_state(paths, [], "session-a")
            self.assertEqual(read_state(paths)["running"], [rook])

    def test_read_state_prunes_dead_process_owner(self):
        with tempfile.TemporaryDirectory() as temporary:
            paths = AppPaths(Path(temporary))
            stale = {"agent": "Vale", "provider": "codex", "account": "work", "reason": "old"}
            write_state(paths, [stale], "dead-session", pid=999_999_999)
            self.assertEqual(read_state(paths)["running"], [])

    def test_watch_once_renders_current_calls(self):
        with tempfile.TemporaryDirectory() as temporary:
            paths = AppPaths(Path(temporary))
            write_state(paths, [{
                "agent": "Vale",
                "provider": "codex",
                "account": "work",
                "boss": "claude-code",
                "reason": "UI testing",
            }], "watch-test")
            result = subprocess.run(
                [str(TICKY), "watch", "--once"],
                cwd=ROOT,
                env=dict(os.environ, TICKY_HOME=temporary),
                text=True,
                capture_output=True,
                timeout=30,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("1 running", result.stdout)
            self.assertIn("Vale", result.stdout)
            self.assertIn("UI testing", result.stdout)

    def test_doctor_exercises_mcp_and_activity_pipeline(self):
        with tempfile.TemporaryDirectory() as temporary:
            result = subprocess.run(
                [str(TICKY), "doctor"],
                cwd=ROOT,
                env=dict(os.environ, TICKY_HOME=temporary),
                text=True,
                capture_output=True,
                timeout=30,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("MCP handshake        ok", result.stdout)
            self.assertIn("mock tools/call      ok", result.stdout)
            self.assertIn("activity cleanup     ok", result.stdout)
            self.assertIn("completion log       ok", result.stdout)

    def test_log_follow_prints_first_entry_when_log_is_created_later(self):
        with tempfile.TemporaryDirectory() as temporary:
            paths = AppPaths(Path(temporary))
            process = subprocess.Popen(
                [str(TICKY), "log", "--follow"],
                cwd=ROOT,
                env=dict(os.environ, TICKY_HOME=temporary),
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            try:
                time.sleep(0.7)
                append_log(paths, {
                    "ts": "2026-07-10T00:00:00+00:00",
                    "agent": "Vale",
                    "provider": "codex",
                    "account": "work",
                    "boss": "claude-code",
                    "duration_s": 1.2,
                    "status": "ok",
                    "reason": "UI testing",
                })
                time.sleep(0.8)
                process.terminate()
                stdout, stderr = process.communicate(timeout=10)
            finally:
                if process.poll() is None:
                    process.kill()
                    process.wait(timeout=10)
            self.assertEqual(stderr, "")
            self.assertIn("Vale", stdout)
            self.assertIn("UI testing", stdout)

    def test_render_activity_empty_state_is_explicit(self):
        with tempfile.TemporaryDirectory() as temporary:
            text = render_activity(AppPaths(Path(temporary)))
            self.assertIn("0 running", text)
            self.assertIn("No calls yet", text)


if __name__ == "__main__":
    unittest.main()
