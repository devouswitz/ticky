import os
import stat
import subprocess
import tempfile
import unittest
from pathlib import Path
import sys
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from ticky_cli.config import (
    AppPaths,
    ConfigError,
    account_record,
    agent_record,
    write_env_file,
)
from ticky_cli.providers import (
    account_environment,
    auth_status_command,
    auth_status_is_linked,
    build_invocation,
    login_command,
    _process_group_options,
    run_agent,
)


class ProviderBehaviorTests(unittest.TestCase):
    def test_process_groups_use_native_options_on_each_platform(self):
        self.assertIn("start_new_session", _process_group_options("posix"))
        self.assertIn("creationflags", _process_group_options("nt"))

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

    def test_claude_api_key_mode_ignores_cached_oauth(self):
        with tempfile.TemporaryDirectory() as temporary:
            paths = AppPaths(Path(temporary))
            account = account_record("claude-api", "claude", auth="api-key")
            write_env_file(
                paths.account_env("claude-api"),
                {"ANTHROPIC_API_KEY": "secret-value"},
            )
            agent = agent_record("claude-api", name="finch", display="Finch")
            agent["workdir"] = temporary
            invocation = build_invocation(paths, account, agent, "Implement the change")
            self.assertIn("--bare", invocation.command)
            self.assertEqual(invocation.env["ANTHROPIC_API_KEY"], "secret-value")
            self.assertEqual(
                invocation.env["CLAUDE_CONFIG_DIR"],
                str(paths.account_home("claude-api")),
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
                if os.name != "nt":
                    mode = stat.S_IMODE(paths.account_env("codex-api").stat().st_mode)
                    self.assertEqual(mode, stat.S_IRUSR | stat.S_IWUSR)
            finally:
                if invocation.output_file:
                    invocation.output_file.unlink(missing_ok=True)

    def test_subscription_modes_drop_global_api_keys(self):
        with tempfile.TemporaryDirectory() as temporary:
            paths = AppPaths(Path(temporary))
            cases = (
                ("codex", "OPENAI_API_KEY"),
                ("claude", "ANTHROPIC_API_KEY"),
                ("gemini", "GEMINI_API_KEY"),
                ("grok", "XAI_API_KEY"),
                ("ollama", "OLLAMA_API_KEY"),
            )
            for auth in ("inherit", "isolated"):
                for provider, key in cases:
                    with self.subTest(auth=auth, provider=provider), mock.patch.dict(
                        os.environ, {key: "global-secret"}, clear=False,
                    ):
                        account = account_record(
                            f"{provider}-{auth}", provider, auth=auth,
                        )
                        env = account_environment(paths, account)
                        self.assertNotIn(key, env)

    def test_gemini_and_grok_api_keys_use_clean_dedicated_homes(self):
        with tempfile.TemporaryDirectory() as temporary:
            paths = AppPaths(Path(temporary))
            cases = (
                ("gemini", "GEMINI_API_KEY", "GOOGLE_API_KEY", "GEMINI_CLI_HOME"),
                ("grok", "XAI_API_KEY", "GROK_CODE_XAI_API_KEY", "GROK_HOME"),
            )
            for provider, key, alternate, home_variable in cases:
                with self.subTest(provider=provider), mock.patch.dict(
                    os.environ, {alternate: "wrong-global-secret"}, clear=False,
                ):
                    account_id = f"{provider}-api"
                    write_env_file(
                        paths.account_env(account_id),
                        {key: "account-secret"},
                    )
                    account = account_record(account_id, provider, auth="api-key")
                    env = account_environment(paths, account)
                    self.assertEqual(env[key], "account-secret")
                    self.assertNotIn(alternate, env)
                    self.assertEqual(
                        env[home_variable],
                        str(paths.account_home(account_id) / "api-key"),
                    )

    def test_grok_maps_subscription_home_model_effort_and_access(self):
        with tempfile.TemporaryDirectory() as temporary:
            paths = AppPaths(Path(temporary))
            account = account_record("grok-private", "grok", auth="isolated")
            agent = agent_record("grok-private", name="rook", display="Rook")
            agent.update({
                "model": "grok-build",
                "thinking": "max",
                "access": "read-only",
                "workdir": temporary,
            })
            invocation = build_invocation(paths, account, agent, "Audit")
            self.assertEqual(invocation.command[:2], ["grok", "--single"])
            self.assertIn("grok-build", invocation.command)
            self.assertIn("high", invocation.command)
            self.assertIn("--no-subagents", invocation.command)
            self.assertEqual(
                invocation.env["GROK_HOME"],
                str(paths.account_home("grok-private")),
            )

    def test_gemini_maps_subscription_home_model_and_access(self):
        with tempfile.TemporaryDirectory() as temporary:
            paths = AppPaths(Path(temporary))
            account = account_record("google-private", "gemini", auth="isolated")
            agent = agent_record("google-private", name="sage", display="Sage")
            agent.update({
                "model": "gemini-3-flash",
                "access": "workspace-write",
                "workdir": temporary,
            })
            invocation = build_invocation(paths, account, agent, "Research")
            self.assertEqual(invocation.command[0], "gemini")
            self.assertIn("auto_edit", invocation.command)
            self.assertIn("gemini-3-flash", invocation.command)
            self.assertEqual(
                invocation.env["GEMINI_CLI_HOME"],
                str(paths.account_home("google-private")),
            )
            self.assertEqual(invocation.env["GEMINI_FORCE_FILE_STORAGE"], "true")

            credentials = paths.account_home("google-private") / ".gemini" / "gemini-credentials.json"
            credentials.parent.mkdir(parents=True)
            credentials.write_text("encrypted", encoding="utf-8")
            command, env = auth_status_command(paths, account)
            status = subprocess.run(command, env=env, capture_output=True, text=True)
            self.assertEqual(status.returncode, 0, status.stderr)
            self.assertIn("credentials found", status.stdout)

    def test_ollama_local_and_cloud_api_key_invocations_are_distinct(self):
        with tempfile.TemporaryDirectory() as temporary:
            paths = AppPaths(Path(temporary))
            agent = agent_record("ollama-default", name="local", display="Local")
            agent.update({
                "model": "gpt-oss:20b",
                "thinking": "max",
                "workdir": temporary,
            })
            local = build_invocation(
                paths,
                account_record("ollama-default", "ollama", auth="inherit"),
                agent,
                "Local task",
            )
            self.assertEqual(local.command[:3], ["ollama", "run", "gpt-oss:20b"])
            self.assertIn("--think=max", local.command)
            self.assertIsNone(local.stdin)

            api_account = account_record("ollama-api", "ollama", auth="api-key")
            write_env_file(
                paths.account_env("ollama-api"),
                {"OLLAMA_API_KEY": "secret-value"},
            )
            agent["account"] = "ollama-api"
            remote = build_invocation(paths, api_account, agent, "Cloud task")
            self.assertEqual(remote.command[0], sys.executable)
            self.assertTrue(remote.command[1].endswith("ollama_api.py"))
            self.assertEqual(remote.stdin, "Cloud task")
            self.assertEqual(remote.env["OLLAMA_API_KEY"], "secret-value")

    def test_provider_login_commands_cover_subscription_flows(self):
        with tempfile.TemporaryDirectory() as temporary:
            paths = AppPaths(Path(temporary))
            expected = {
                "codex": ["codex", "login"],
                "claude": ["claude", "auth", "login"],
                "gemini": ["gemini"],
                "grok": ["grok", "login"],
                "ollama": ["ollama", "signin"],
            }
            for provider, command in expected.items():
                with self.subTest(provider=provider):
                    account = account_record(
                        f"{provider}-private", provider, auth="isolated",
                    )
                    actual, _ = login_command(paths, account)
                    self.assertEqual(actual, command)

    def test_grok_status_rejects_false_success_exit_code(self):
        self.assertFalse(
            auth_status_is_linked("grok", 0, "You are not authenticated."),
        )
        self.assertTrue(
            auth_status_is_linked("grok", 0, "You are logged in with grok.com."),
        )

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
