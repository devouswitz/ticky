import io
import json
import tempfile
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ticky_cli.config import AppPaths, ConfigError
from ticky_cli.mcp import McpServer
from ticky_cli.providers import AgentRun, RunResult
from ticky_cli.runtime import read_log_tail, read_state
from ticky_cli.team import run_team
from tests.test_session import mock_config


class TeamTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.paths = AppPaths(Path(temporary.name))
        self.config = mock_config(("vale", "rook", "sage"))

    def test_relay_passes_first_result_to_second_and_lead_gets_both(self):
        with mock.patch("ticky_cli.team.AgentRun", wraps=AgentRun) as runs:
            result = run_team(self.config, self.paths, ["vale", "rook"], "review", lead="sage")
        self.assertTrue(result.ok)
        self.assertEqual(len(runs.call_args_list), 3)
        self.assertIsNone(runs.call_args_list[0].args[4])
        self.assertIn("[mock:vale]", runs.call_args_list[1].args[4])
        self.assertIn("[mock:rook]", runs.call_args_list[2].args[4])
        self.assertEqual(len(read_log_tail(self.paths)), 3)
        self.assertEqual(read_state(self.paths)["running"], [])

    def test_parallel_starts_all_contributors_before_collecting(self):
        order = []

        class Run:
            timeout = 10
            def __init__(self, paths, account, agent, task, context):
                self.name = agent["name"]
                order.append("start:" + self.name)
            def running(self):
                return False
            def finish(self):
                order.append("finish:" + self.name)
                return RunResult(True, self.name, 0)

        with mock.patch("ticky_cli.team.AgentRun", Run):
            result = run_team(self.config, self.paths, ["vale", "rook"], "review", mode="parallel")
        self.assertTrue(result.ok)
        self.assertEqual(order[:2], ["start:vale", "start:rook"])

    def test_disabled_duplicates_and_parallel_writers_fail_before_dispatch(self):
        self.config["profiles"]["default"]["agents"][0]["access"] = "full"
        for names, mode in ((["vale", "rook"], "parallel"), (["vale", "Vale"], "relay"), (["vale", "missing"], "relay")):
            with mock.patch("ticky_cli.team.AgentRun") as run, self.assertRaises(ConfigError):
                run_team(self.config, self.paths, names, "task", mode=mode)
            run.assert_not_called()

    def test_failure_stops_relay_and_is_reported(self):
        failed = mock.Mock()
        failed.running.return_value = False
        failed.finish.return_value = RunResult(False, "network unavailable", 0)
        with mock.patch("ticky_cli.team.AgentRun", return_value=failed) as runs:
            result = run_team(self.config, self.paths, ["vale", "rook"], "review", lead="sage")
        self.assertFalse(result.ok)
        self.assertIn("network unavailable", result.text())
        self.assertEqual(runs.call_count, 1)
        self.assertEqual(read_state(self.paths)["running"], [])

    def test_mcp_team_tool_dispatches_and_returns_real_results(self):
        sink = io.StringIO()
        server = McpServer(self.config, self.paths, sink=sink)
        server.handle({"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {
            "name": "ticky_team", "arguments": {"agents": ["vale", "rook"], "task": "review", "reason": "second opinion"},
        }})
        for worker in server._workers:
            worker.join(timeout=5)
        value = json.loads(sink.getvalue())
        self.assertFalse(value["result"]["isError"])
        self.assertIn("[mock:rook]", value["result"]["content"][0]["text"])

    def test_interrupt_cancels_every_started_call_and_clears_activity(self):
        runs = [mock.Mock(timeout=10), mock.Mock(timeout=10)]
        for run in runs:
            run.running.return_value = True
            run.timed_out.return_value = False
            run.finish.return_value = RunResult(False, "cancelled", 0)
        with mock.patch("ticky_cli.team.AgentRun", side_effect=runs), mock.patch(
            "ticky_cli.team.time.sleep", side_effect=KeyboardInterrupt,
        ), self.assertRaises(KeyboardInterrupt):
            run_team(self.config, self.paths, ["vale", "rook"], "review", mode="parallel")
        for run in runs:
            run.cancel.assert_called_once_with("team interrupted")
        self.assertEqual(read_state(self.paths)["running"], [])
        self.assertEqual(len(read_log_tail(self.paths)), 2)

    def test_second_launch_failure_cancels_first_call(self):
        first = mock.Mock()
        first.finish.return_value = RunResult(False, "cancelled", 0)
        with mock.patch("ticky_cli.team.AgentRun", side_effect=[first, OSError("unavailable")]), self.assertRaises(OSError):
            run_team(self.config, self.paths, ["vale", "rook"], "review", mode="parallel")
        first.cancel.assert_called_once()
        self.assertEqual(read_state(self.paths)["running"], [])

    def test_mcp_returns_failure_for_unexpected_launch_error(self):
        sink = io.StringIO()
        server = McpServer(self.config, self.paths, sink=sink)
        with mock.patch("ticky_cli.team.AgentRun", side_effect=OSError("private detail")):
            server._call(1, {"name": "ticky_team", "arguments": {
                "agents": ["vale", "rook"], "task": "review", "reason": "review",
            }})
        value = json.loads(sink.getvalue())
        self.assertTrue(value["result"]["isError"])
        self.assertNotIn("private detail", sink.getvalue())


if __name__ == "__main__":
    unittest.main()
