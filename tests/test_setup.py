import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
import sys
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from ticky_cli.config import AppPaths, ConfigStore, read_env_file, new_config
from ticky_cli.setup_wizard import parse_provider_selection, run_setup_wizard


def scripted(answers):
    return mock.patch("builtins.input", side_effect=list(answers))


class SetupWizardTests(unittest.TestCase):
    def test_provider_aliases_are_canonical_and_ordered(self):
        self.assertEqual(
            parse_provider_selection("google, xai, local-llm, openai, google"),
            ["gemini", "grok", "ollama", "codex"],
        )

    def test_gemini_api_key_setup_stores_secret_outside_config(self):
        with tempfile.TemporaryDirectory() as temporary:
            store = ConfigStore(AppPaths(Path(temporary)))
            answers = [
                "api-key",          # authentication
                "",                 # account label
                "",                 # account id
                "Gem",              # agent name
                "gemini-3-flash",   # model
                "",                 # thinking
                "",                 # access
                "",                 # workdir
                "1",                # priority
                "",                 # timeout
                "Google research",  # tagline
                "Use for search",   # routing note
                "",                 # no extra agent
                "Prefer Gem for Google research.",
            ]
            with (
                scripted(answers),
                mock.patch("ticky_cli.setup_wizard.getpass.getpass", return_value="gemini-secret"),
                mock.patch("ticky_cli.setup_wizard.shutil.which", return_value="gemini"),
                contextlib.redirect_stdout(io.StringIO()),
            ):
                result = run_setup_wizard(store, requested=["google"])

            self.assertEqual(result.providers, ["gemini"])
            saved_text = store.paths.config.read_text(encoding="utf-8")
            saved = json.loads(saved_text)
            self.assertNotIn("gemini-secret", saved_text)
            account = saved["accounts"]["gemini-api"]
            self.assertEqual(account["auth"], "api-key")
            self.assertEqual(
                read_env_file(store.paths.account_env("gemini-api"))["GEMINI_API_KEY"],
                "gemini-secret",
            )
            agent = saved["profiles"]["default"]["agents"][0]
            self.assertEqual(agent["model"], "gemini-3-flash")
            self.assertEqual(agent["specialty"], "Google research")
            self.assertEqual(
                saved["profiles"]["default"]["preferences"],
                "Prefer Gem for Google research.",
            )

    def test_grok_separate_subscription_login_uses_isolated_home(self):
        with tempfile.TemporaryDirectory() as temporary:
            store = ConfigStore(AppPaths(Path(temporary)))
            answers = [
                "separate-login", "", "", "",  # account and login now
                "Rook", "grok-build", "high", "", "", "1", "",
                "Deep audits", "Use for verification", "", "Prefer Rook for audits.",
            ]
            completed = mock.Mock(returncode=0)
            with (
                scripted(answers),
                mock.patch("ticky_cli.setup_wizard.shutil.which", return_value="grok"),
                mock.patch("ticky_cli.setup_wizard.subprocess.run", return_value=completed) as run,
                contextlib.redirect_stdout(io.StringIO()),
            ):
                run_setup_wizard(store, requested=["xai"])

            command, kwargs = run.call_args
            self.assertEqual(command[0], ["grok", "login"])
            self.assertEqual(
                kwargs["env"]["GROK_HOME"],
                str(store.paths.account_home("grok-private")),
            )
            saved = store.load()
            self.assertEqual(saved["accounts"]["grok-private"]["auth"], "isolated")
            self.assertEqual(saved["profiles"]["default"]["agents"][0]["model"], "grok-build")

    def test_existing_setup_keeps_accounts_and_can_skip_agent_review(self):
        with tempfile.TemporaryDirectory() as temporary:
            store = ConfigStore(AppPaths(Path(temporary)))
            original = new_config(["codex"])
            original_agent = original["profiles"]["default"]["agents"][0]["name"]
            store.save(original)
            with (
                scripted(["", "", "n", "n", "Keep the current routing."]),
                mock.patch("ticky_cli.setup_wizard.subprocess.run") as run,
                contextlib.redirect_stdout(io.StringIO()),
            ):
                run_setup_wizard(store, original)
            run.assert_not_called()
            saved = store.load()
            self.assertIn("codex-default", saved["accounts"])
            self.assertEqual(
                saved["profiles"]["default"]["agents"][0]["name"],
                original_agent,
            )
            self.assertEqual(
                saved["profiles"]["default"]["preferences"],
                "Keep the current routing.",
            )


if __name__ == "__main__":
    unittest.main()
