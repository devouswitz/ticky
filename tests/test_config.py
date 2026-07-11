import json
import io
import os
import subprocess
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
import sys
from types import SimpleNamespace
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
TICKY = ROOT / "ticky"
sys.path.insert(0, str(ROOT / "src"))

from ticky_cli.config import (
    AppPaths,
    ConfigError,
    ConfigStore,
    agent_record,
    generated_agent_name,
    new_config,
    validate_config,
    write_env_file,
)
from ticky_cli.cli import _selected_account, _symlink_to_path, cmd_account_status, cmd_init


class ModelValidationTests(unittest.TestCase):
    def _config_with_model(self, model):
        config = new_config(["codex"])
        config["profiles"]["default"]["agents"][0]["model"] = model
        return config

    def test_plain_model_names_are_accepted(self):
        for model in (None, "gpt-5.5", "opus"):
            validate_config(self._config_with_model(model))

    def test_flag_shaped_and_empty_models_are_rejected(self):
        for model in ("--dangerously-skip-permissions", "-o", "", "   ", 7):
            with self.assertRaises(ConfigError):
                validate_config(self._config_with_model(model))


class ConfigBehaviorTests(unittest.TestCase):
    def _environment(self, temporary):
        return dict(
            os.environ,
            TICKY_HOME=temporary,
            HOME=temporary,
            USERPROFILE=temporary,
        )

    def _run(self, temporary, *arguments):
        return subprocess.run(
            [str(TICKY), *arguments],
            cwd=ROOT,
            env=self._environment(temporary),
            text=True,
            capture_output=True,
            timeout=30,
        )

    def _load(self, temporary):
        return json.loads(Path(temporary, "config.json").read_text())

    def _initialize(self, temporary, *providers):
        arguments = ["init", "--yes", "--no-install", "--no-link"]
        for provider in providers or ("codex",):
            arguments.extend(["--provider", provider])
        result = self._run(temporary, *arguments)
        self.assertEqual(result.returncode, 0, result.stderr)
        return result

    def test_shared_gemini_status_is_explicit_about_deferred_login_verification(self):
        with tempfile.TemporaryDirectory() as temporary:
            store = ConfigStore(AppPaths(Path(temporary)))
            store.save(new_config(["gemini"]))
            output = io.StringIO()
            with (
                mock.patch.dict(os.environ, {"TICKY_HOME": temporary}),
                mock.patch("ticky_cli.cli.shutil.which", return_value="/fake/gemini"),
                redirect_stdout(output),
            ):
                code = cmd_account_status(SimpleNamespace(account=None))
            self.assertEqual(code, 0)
            self.assertIn("configured", output.getvalue())
            self.assertIn("verified on the first agent call", output.getvalue())

    def test_api_key_status_distinguishes_configuration_from_live_validity(self):
        with tempfile.TemporaryDirectory() as temporary:
            store = ConfigStore(AppPaths(Path(temporary)))
            config = new_config(["gemini"])
            config["accounts"]["gemini-default"]["auth"] = "api-key"
            store.save(config)
            write_env_file(
                store.paths.account_env("gemini-default"),
                {"GEMINI_API_KEY": "test-secret"},
            )
            output = io.StringIO()
            with (
                mock.patch.dict(os.environ, {"TICKY_HOME": temporary}),
                mock.patch("ticky_cli.cli.shutil.which", return_value="/fake/gemini"),
                redirect_stdout(output),
            ):
                code = cmd_account_status(SimpleNamespace(account=None))
            self.assertEqual(code, 0)
            self.assertIn("configured", output.getvalue())
            self.assertIn("validity is checked on first call", output.getvalue())

    def test_noninteractive_setup_adds_requested_provider_to_existing_config(self):
        with tempfile.TemporaryDirectory() as temporary:
            self._initialize(temporary, "codex")
            added = self._run(
                temporary,
                "setup", "--yes", "--provider", "google", "--no-install", "--no-link",
            )
            repeated = self._run(
                temporary,
                "setup", "--yes", "--provider", "google", "--no-install", "--no-link",
            )
            self.assertEqual(added.returncode, 0, added.stderr)
            self.assertEqual(repeated.returncode, 0, repeated.stderr)
            saved = self._load(temporary)
            self.assertIn("gemini-default", saved["accounts"])
            gemini_agents = [
                agent for agent in saved["profiles"]["default"]["agents"]
                if agent["account"] == "gemini-default"
            ]
            self.assertEqual(len(gemini_agents), 1)

    def test_v1_migration_preserves_roster_and_creates_backup(self):
        with tempfile.TemporaryDirectory() as temporary:
            paths = AppPaths(Path(temporary))
            legacy_agents = []
            for name, backend in (
                ("rook", "codex"),
                ("wren", "codex"),
                ("finch", "claude"),
                ("agent1", "codex"),
                ("agent2", "codex"),
            ):
                legacy_agents.append({
                    "name": name,
                    "display": name.title(),
                    "backend": backend,
                    "access": "read-only",
                    "network": False,
                    "priority": 2,
                    "enabled": True,
                    "workdir": "~",
                    "specialty": f"{name} work",
                    "timeout": 900,
                    "extra_args": [],
                })
            paths.config.write_text(json.dumps({
                "version": 1,
                "preferences": "Preserve this routing rule.",
                "agents": legacy_agents,
            }), encoding="utf-8")

            migrated = ConfigStore(paths).load()

            self.assertEqual(migrated["version"], 2)
            self.assertEqual(migrated["active_profile"], "default")
            self.assertEqual(len(migrated["profiles"]["default"]["agents"]), 5)
            self.assertEqual(
                migrated["profiles"]["default"]["preferences"],
                "Preserve this routing rule.",
            )
            self.assertEqual(set(migrated["accounts"]), {"codex-default", "claude-default"})
            self.assertTrue(paths.v1_backup.exists())
            self.assertEqual(json.loads(paths.v1_backup.read_text())["version"], 1)

    def test_profile_clone_and_use_are_isolated(self):
        with tempfile.TemporaryDirectory() as temporary:
            self._initialize(temporary)
            environment = self._environment(temporary)
            config = self._load(temporary)
            original_name = config["profiles"]["default"]["agents"][0]["name"]

            created = subprocess.run(
                [str(TICKY), "profile", "create", "review"],
                cwd=ROOT, env=environment, text=True, capture_output=True, timeout=30,
            )
            used = subprocess.run(
                [str(TICKY), "profile", "use", "review"],
                cwd=ROOT, env=environment, text=True, capture_output=True, timeout=30,
            )
            edited = subprocess.run(
                [str(TICKY), "agent", "edit", original_name, "specialty=Review only"],
                cwd=ROOT, env=environment, text=True, capture_output=True, timeout=30,
            )
            self.assertEqual(created.returncode, 0, created.stderr)
            self.assertEqual(used.returncode, 0, used.stderr)
            self.assertEqual(edited.returncode, 0, edited.stderr)

            updated = json.loads(Path(temporary, "config.json").read_text())
            self.assertEqual(updated["active_profile"], "review")
            self.assertNotEqual(
                updated["profiles"]["default"]["agents"][0]["specialty"],
                updated["profiles"]["review"]["agents"][0]["specialty"],
            )

    def test_generated_agent_names_do_not_collide(self):
        names = []
        for _ in range(40):
            name, display = generated_agent_name(names)
            self.assertTrue(display)
            self.assertNotIn(name, names)
            names.append(name)
        self.assertEqual(len(names), len(set(names)))

    def test_agent_record_uses_requested_account_and_generated_identity(self):
        record = agent_record("codex-work", existing=("vale", "rook"))
        self.assertEqual(record["account"], "codex-work")
        self.assertNotIn(record["name"], {"vale", "rook"})
        self.assertEqual(record["thinking"], "default")
        self.assertEqual(record["access"], "read-only")

    def test_init_provider_selection_is_ordered_and_deduplicated(self):
        with tempfile.TemporaryDirectory() as temporary:
            self._initialize(temporary, "claude", "codex", "claude")

            config = self._load(temporary)
            agents = config["profiles"]["default"]["agents"]
            self.assertEqual(set(config["accounts"]), {"claude-default", "codex-default"})
            self.assertEqual(
                [agent["account"] for agent in agents],
                ["claude-default", "codex-default"],
            )

    def test_init_registration_failure_is_an_error_and_returns_nonzero(self):
        with tempfile.TemporaryDirectory() as temporary:
            args = mock.Mock(
                provider=["codex"],
                yes=True,
                no_install=False,
                no_link=True,
            )
            output = io.StringIO()
            with (
                mock.patch.dict(os.environ, self._environment(temporary)),
                mock.patch(
                    "ticky_cli.cli.install_harness",
                    return_value=(False, "registration failed"),
                ),
                redirect_stdout(output),
            ):
                code = cmd_init(args)

            self.assertEqual(code, 1)
            self.assertIn("codex: error: registration failed", output.getvalue())

    @unittest.skipIf(os.name == "nt", "source checkout symlinks are POSIX-only")
    def test_init_link_is_idempotent_and_preserves_conflict(self):
        with tempfile.TemporaryDirectory() as temporary:
            arguments = (
                "init", "--yes", "--provider", "codex", "--no-install",
            )
            first = self._run(temporary, *arguments)
            second = self._run(temporary, *arguments)
            link = Path(temporary, ".local", "bin", "ticky")

            self.assertEqual(first.returncode, 0, first.stderr)
            self.assertEqual(second.returncode, 0, second.stderr)
            self.assertTrue(link.is_symlink())
            self.assertEqual(link.resolve(), TICKY.resolve())
            self.assertIn("using existing config", second.stdout)

        with tempfile.TemporaryDirectory() as temporary:
            destination = Path(temporary, ".local", "bin", "ticky")
            destination.parent.mkdir(parents=True)
            other = Path(temporary, "other-ticky")
            other.write_text("not this checkout\n", encoding="utf-8")
            destination.symlink_to(other)

            result = self._run(
                temporary, "init", "--yes", "--provider", "codex", "--no-install"
            )

            self.assertEqual(result.returncode, 2)
            self.assertIn("link conflict", result.stderr)
            self.assertIn(str(other), result.stderr)
            self.assertTrue(destination.is_symlink())
            self.assertEqual(destination.resolve(), other.resolve())

    @unittest.skipIf(os.name == "nt", "source checkout symlinks are POSIX-only")
    def test_init_link_errors_are_clean(self):
        with tempfile.TemporaryDirectory() as temporary:
            environment = self._environment(temporary)
            with (
                mock.patch.dict(os.environ, environment),
                mock.patch.object(
                    Path,
                    "symlink_to",
                    side_effect=PermissionError("permission denied"),
                ),
            ):
                with self.assertRaisesRegex(
                    ConfigError,
                    "could not link.*permission denied",
                ):
                    _symlink_to_path()

        with tempfile.TemporaryDirectory() as temporary:
            destination = Path(temporary, ".local", "bin", "ticky")
            destination.parent.mkdir(parents=True)
            destination.symlink_to(destination)

            result = self._run(
                temporary, "init", "--yes", "--provider", "codex", "--no-install"
            )

            self.assertEqual(result.returncode, 2)
            self.assertRegex(result.stderr, "link conflict|could not link")
            self.assertNotIn("Traceback", result.stderr)
            self.assertTrue(destination.is_symlink())

    def test_agent_add_reports_zero_and_multiple_account_choices(self):
        with tempfile.TemporaryDirectory() as temporary:
            ConfigStore(AppPaths(Path(temporary))).save(new_config([]))
            result = self._run(temporary, "agent", "add", "helper")

            self.assertEqual(result.returncode, 2)
            self.assertEqual(
                result.stderr.strip(),
                "ticky: no enabled accounts; run ticky account add",
            )

        with tempfile.TemporaryDirectory() as temporary:
            ConfigStore(AppPaths(Path(temporary))).save(new_config(["codex", "claude"]))
            result = self._run(temporary, "agent", "add", "helper")

            self.assertEqual(result.returncode, 2)
            self.assertIn("available accounts:", result.stderr)
            self.assertIn("claude-default", result.stderr)
            self.assertIn("codex-default", result.stderr)

            output = io.StringIO()
            with (
                mock.patch("ticky_cli.cli.sys.stdin.isatty", return_value=True),
                mock.patch("builtins.input", side_effect=["invalid", "2"]),
                redirect_stdout(output),
            ):
                selected = _selected_account(new_config(["codex", "claude"]), None)
            self.assertEqual(selected, "codex-default")
            self.assertIn(
                "1. claude-default (claude; Default Claude)", output.getvalue()
            )
            self.assertIn(
                "2. codex-default (codex; Default Codex)", output.getvalue()
            )
            self.assertIn("Enter a number from 1 to 2.", output.getvalue())

    def test_agent_add_uses_positional_or_display_identity_and_infers_account(self):
        with tempfile.TemporaryDirectory() as temporary:
            self._initialize(temporary)

            named = self._run(
                temporary, "agent", "add", "finch", "--display", "Finch Helper"
            )
            displayed = self._run(
                temporary, "agent", "add", "--display", "Display Only"
            )

            self.assertEqual(named.returncode, 0, named.stderr)
            self.assertEqual(displayed.returncode, 0, displayed.stderr)
            self.assertIn("Restart connected harnesses", named.stdout)
            self.assertIn("Restart connected harnesses", displayed.stdout)
            agents = {
                agent["name"]: agent
                for agent in self._load(temporary)["profiles"]["default"]["agents"]
            }
            self.assertEqual(agents["finch"]["display"], "Finch Helper")
            self.assertEqual(agents["finch"]["account"], "codex-default")
            self.assertEqual(agents["display-only"]["display"], "Display Only")

    def test_agent_multi_remove_is_atomic(self):
        with tempfile.TemporaryDirectory() as temporary:
            self._initialize(temporary)
            for name in ("alpha", "beta"):
                added = self._run(temporary, "agent", "add", name)
                self.assertEqual(added.returncode, 0, added.stderr)

            failed = self._run(
                temporary, "agent", "remove", "alpha", "missing", "beta"
            )
            self.assertEqual(failed.returncode, 2)
            names = {
                agent["name"]
                for agent in self._load(temporary)["profiles"]["default"]["agents"]
            }
            self.assertTrue({"alpha", "beta"}.issubset(names))

            removed = self._run(temporary, "agent", "remove", "alpha", "beta")
            self.assertEqual(removed.returncode, 0, removed.stderr)
            self.assertIn("removed agents alpha, beta", removed.stdout)
            self.assertIn("Restart connected harnesses", removed.stdout)
            names = {
                agent["name"]
                for agent in self._load(temporary)["profiles"]["default"]["agents"]
            }
            self.assertTrue({"alpha", "beta"}.isdisjoint(names))

    def test_agent_edit_conversion_errors_are_clean(self):
        with tempfile.TemporaryDirectory() as temporary:
            self._initialize(temporary)
            name = self._load(temporary)["profiles"]["default"]["agents"][0]["name"]
            original = Path(temporary, "config.json").read_text(encoding="utf-8")

            invalid_integer = self._run(
                temporary, "agent", "edit", name, "priority=not-a-number"
            )
            malformed_json = self._run(
                temporary, "agent", "edit", name, "extra_args=["
            )

            self.assertEqual(invalid_integer.returncode, 2)
            self.assertEqual(len(invalid_integer.stderr.splitlines()), 1)
            self.assertIn("priority must be an integer", invalid_integer.stderr)
            self.assertNotIn("Traceback", invalid_integer.stderr)
            self.assertEqual(malformed_json.returncode, 2)
            self.assertEqual(len(malformed_json.stderr.splitlines()), 1)
            self.assertIn("extra_args must be valid JSON", malformed_json.stderr)
            self.assertNotIn("Traceback", malformed_json.stderr)
            self.assertEqual(
                Path(temporary, "config.json").read_text(encoding="utf-8"),
                original,
            )


if __name__ == "__main__":
    unittest.main()
