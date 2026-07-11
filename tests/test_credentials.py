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
    account_record,
    provider_key_name,
    read_env_file,
    write_env_file,
)
from ticky_cli.credentials import set_api_key, unset_api_key


class CredentialTests(unittest.TestCase):
    def test_windows_secret_file_acl_is_restricted_to_current_user(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary, "account", "env")
            completed = subprocess.CompletedProcess([], 0, "", "")
            with (
                mock.patch("ticky_cli.config.os.name", "nt"),
                mock.patch.dict(
                    "ticky_cli.config.os.environ",
                    {"USERNAME": "TickyUser", "USERDOMAIN": "TickyDomain"},
                ),
                mock.patch("ticky_cli.config.subprocess.run", return_value=completed) as run,
            ):
                write_env_file(path, {"XAI_API_KEY": "secret"})
            command = run.call_args.args[0]
            self.assertEqual(command[0], "icacls")
            self.assertIn("/inheritance:r", command)
            self.assertIn("TickyDomain\\TickyUser:(F)", command)

    def test_provider_default_key_names(self):
        expected = {
            "codex": "OPENAI_API_KEY",
            "claude": "ANTHROPIC_API_KEY",
            "gemini": "GEMINI_API_KEY",
            "grok": "XAI_API_KEY",
            "ollama": "OLLAMA_API_KEY",
        }
        for provider, name in expected.items():
            with self.subTest(provider=provider):
                self.assertEqual(provider_key_name(provider), name)

    def test_codex_key_is_stored_and_activated_in_isolated_home(self):
        with tempfile.TemporaryDirectory() as temporary:
            paths = AppPaths(Path(temporary))
            account = account_record("codex-api", "codex", auth="api-key")
            completed = subprocess.CompletedProcess([], 0, "", "")
            with (
                mock.patch("ticky_cli.credentials.shutil.which", return_value="codex"),
                mock.patch("ticky_cli.credentials.subprocess.run", return_value=completed) as run,
            ):
                ok, message = set_api_key(paths, account, "openai-secret")
            self.assertTrue(ok, message)
            command, kwargs = run.call_args
            self.assertEqual(command[0], ["codex", "login", "--with-api-key"])
            self.assertEqual(kwargs["input"], "openai-secret\n")
            self.assertEqual(
                kwargs["env"]["CODEX_HOME"],
                str(paths.account_home("codex-api")),
            )
            secret_path = paths.account_env("codex-api")
            self.assertEqual(read_env_file(secret_path)["OPENAI_API_KEY"], "openai-secret")
            if os.name != "nt":
                self.assertEqual(
                    stat.S_IMODE(secret_path.stat().st_mode),
                    stat.S_IRUSR | stat.S_IWUSR,
                )

    def test_non_codex_key_does_not_run_a_login_subprocess(self):
        with tempfile.TemporaryDirectory() as temporary:
            paths = AppPaths(Path(temporary))
            for provider in ("claude", "gemini", "grok", "ollama"):
                with self.subTest(provider=provider), mock.patch(
                    "ticky_cli.credentials.subprocess.run",
                ) as run:
                    account = account_record(f"{provider}-api", provider, auth="api-key")
                    ok, _ = set_api_key(paths, account, f"{provider}-secret")
                    self.assertTrue(ok)
                    run.assert_not_called()

    def test_unset_uses_provider_default_name(self):
        with tempfile.TemporaryDirectory() as temporary:
            paths = AppPaths(Path(temporary))
            account = account_record("grok-api", "grok", auth="api-key")
            set_api_key(paths, account, "xai-secret")
            self.assertEqual(unset_api_key(paths, account), "XAI_API_KEY")
            self.assertEqual(read_env_file(paths.account_env("grok-api")), {})


if __name__ == "__main__":
    unittest.main()
