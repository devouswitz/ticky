import os
import stat
import tempfile
import unittest
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from ticky_cli.config import AppPaths, ConfigError, account_record, agent_record, write_env_file
from ticky_cli.providers import build_invocation, run_agent


class ProviderBehaviorTests(unittest.TestCase):
    def test_codex_command_maps_account_model_thinking_access_and_network(self):
        with tempfile.TemporaryDirectory() as temporary:
            paths = AppPaths(Path(temporary))
            account = account_record("codex-work", "codex", auth="isolated")
            agent = agent_record("codex-work", name="vale", display="Vale")
            agent.update({
                "model": "gpt-5.6",
                "thinking": "xhigh",
                "access": "workspace-write",
                "network": True,
                "workdir": temporary,
            })
            invocation = build_invocation(paths, account, agent, "Inspect the UI")
            try:
                command = invocation.command
                self.assertEqual(command[:2], ["codex", "exec"])
                self.assertIn("workspace-write", command)
                self.assertIn("gpt-5.6", command)
                self.assertIn('model_reasoning_effort="xhigh"', command)
                self.assertIn("sandbox_workspace_write.network_access=true", command)
                self.assertEqual(
                    invocation.env["CODEX_HOME"],
                    str(paths.account_home("codex-work")),
                )
            finally:
                if invocation.output_file:
                    invocation.output_file.unlink(missing_ok=True)

    def test_claude_command_keeps_bash_blocked_for_workspace_write(self):
        with tempfile.TemporaryDirectory() as temporary:
            paths = AppPaths(Path(temporary))
            account = account_record("claude-work", "claude", auth="isolated")
            agent = agent_record("claude-work", name="finch", display="Finch")
            agent.update({
                "model": "opus",
                "thinking": "high",
                "access": "workspace-write",
                "workdir": temporary,
            })
            invocation = build_invocation(paths, account, agent, "Implement the change")
            command = invocation.command
            self.assertEqual(command[0], "claude")
            self.assertIn("acceptEdits", command)
            self.assertIn("Bash", command)
            self.assertIn("opus", command)
            self.assertIn("high", command)
            self.assertNotIn("--dangerously-skip-permissions", command)
            self.assertEqual(
                invocation.env["CLAUDE_CONFIG_DIR"],
                str(paths.account_home("claude-work")),
            )

    def test_account_secret_file_is_private_and_overlays_environment(self):
        with tempfile.TemporaryDirectory() as temporary:
            paths = AppPaths(Path(temporary))
            account = account_record("codex-api", "codex", auth="api-key")
            write_env_file(paths.account_env("codex-api"), {"OPENAI_API_KEY": "secret-value"})
            agent = agent_record("codex-api", name="rook", display="Rook")
            agent["workdir"] = temporary
            invocation = build_invocation(paths, account, agent, "Audit")
            try:
                self.assertEqual(invocation.env["OPENAI_API_KEY"], "secret-value")
                mode = stat.S_IMODE(paths.account_env("codex-api").stat().st_mode)
                self.assertEqual(mode, stat.S_IRUSR | stat.S_IWUSR)
            finally:
                if invocation.output_file:
                    invocation.output_file.unlink(missing_ok=True)

    def test_mock_provider_returns_observable_result(self):
        with tempfile.TemporaryDirectory() as temporary:
            paths = AppPaths(Path(temporary))
            account = account_record("mock-test", "mock")
            agent = agent_record("mock-test", name="probe", display="Probe")
            result = run_agent(paths, account, agent, "ping")
            self.assertTrue(result.ok)
            self.assertIn("[mock:probe]", result.text)
            self.assertIn("ping", result.text)

    def test_extra_args_cannot_override_access_policy(self):
        with tempfile.TemporaryDirectory() as temporary:
            paths = AppPaths(Path(temporary))
            account = account_record("claude-test", "claude")
            agent = agent_record("claude-test", name="probe", display="Probe")
            agent["workdir"] = temporary
            agent["extra_args"] = ["--dangerously-skip-permissions"]
            with self.assertRaises(ConfigError):
                build_invocation(paths, account, agent, "ping")

    def test_missing_workdir_returns_start_error(self):
        with tempfile.TemporaryDirectory() as temporary:
            paths = AppPaths(Path(temporary))
            account = account_record("codex-test", "codex")
            agent = agent_record("codex-test", name="probe", display="Probe")
            agent["workdir"] = str(Path(temporary) / "missing")
            result = run_agent(paths, account, agent, "ping")
            self.assertFalse(result.ok)
            self.assertIn("could not start provider", result.text)
            self.assertEqual(result.duration, 0.0)


if __name__ == "__main__":
    unittest.main()
