import argparse
import io
import json
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from ticky_cli import cli
from ticky_cli.config import AppPaths, ConfigError, ConfigStore, new_config
from ticky_cli.wizard import prompt_agent, run_roster_wizard


def scripted(answers):
    return mock.patch("builtins.input", side_effect=list(answers))


def _agent_add_args(**overrides):
    values = dict(
        name=None, display=None, account=None, model=None, thinking=None,
        specialty=None, note=None, priority=None, access=None, workdir=None,
        network=False, timeout=None, profile=None,
    )
    values.update(overrides)
    return argparse.Namespace(**values)


class PromptAgentTests(unittest.TestCase):
    def test_all_fields_are_collected(self):
        with tempfile.TemporaryDirectory() as temporary:
            config = new_config(["codex", "claude"])
            answers = [
                "Rook",            # name
                "2",               # account: sorted -> claude-default, codex-default
                "gpt-5.5",         # model
                "xhigh",           # thinking
                "2",               # access: workspace-write
                "y",               # network (codex + workspace-write)
                temporary,          # workdir
                "1",               # priority
                "600",             # timeout
                "Deep audits and second opinions",
                "Call first for verification-shaped tasks",
            ]
            with scripted(answers), redirect_stdout(io.StringIO()):
                record = prompt_agent(config, [])
        self.assertEqual(record["name"], "rook")
        self.assertEqual(record["display"], "Rook")
        self.assertEqual(record["account"], "codex-default")
        self.assertEqual(record["model"], "gpt-5.5")
        self.assertEqual(record["thinking"], "xhigh")
        self.assertEqual(record["access"], "workspace-write")
        self.assertTrue(record["network"])
        self.assertEqual(record["workdir"], temporary)
        self.assertEqual(record["priority"], 1)
        self.assertEqual(record["timeout"], 600)
        self.assertEqual(record["specialty"], "Deep audits and second opinions")
        self.assertEqual(record["routing_note"], "Call first for verification-shaped tasks")

    def test_duplicate_name_is_rejected_until_unique(self):
        config = new_config(["codex"])
        answers = [
            "Rook",            # collides with existing name
            "Wren",            # accepted
            "",                # model default
            "",                # thinking default
            "",                # access default read-only
            "",                # workdir default
            "",                # priority default
            "",                # timeout default
            "Research",        # specialty
            "",                # routing note
        ]
        with scripted(answers), redirect_stdout(io.StringIO()):
            record = prompt_agent(config, ["rook"])
        self.assertEqual(record["name"], "wren")
        self.assertEqual(record["access"], "read-only")
        self.assertEqual(record["model"], None)

    def test_missing_workdir_is_reprompted(self):
        with tempfile.TemporaryDirectory() as temporary:
            missing = str(Path(temporary, "missing"))
            answers = [
                "Scout", "", "", "", missing, temporary,
                "", "", "Research", "",
            ]
            output = io.StringIO()
            with scripted(answers), redirect_stdout(output):
                record = prompt_agent(new_config(["codex"]), [])

            self.assertEqual(record["workdir"], temporary)
            self.assertIn("does not exist", output.getvalue())

    def test_full_access_requires_a_second_confirmation(self):
        with tempfile.TemporaryDirectory() as temporary:
            answers = [
                "Scout", "", "", "full", "n", "read-only", temporary,
                "", "", "Research", "",
            ]
            output = io.StringIO()
            with scripted(answers), redirect_stdout(output):
                record = prompt_agent(new_config(["codex"]), [])

            self.assertEqual(record["access"], "read-only")
            self.assertIn("Full access was not enabled", output.getvalue())

    def test_eof_becomes_config_error(self):
        config = new_config(["codex"])
        with mock.patch("builtins.input", side_effect=EOFError), redirect_stdout(io.StringIO()):
            with self.assertRaises(ConfigError):
                prompt_agent(config, [])


class RosterWizardTests(unittest.TestCase):
    def _store(self, temporary):
        return ConfigStore(AppPaths(Path(temporary)))

    def test_empty_roster_offers_first_agent_and_saves(self):
        with tempfile.TemporaryDirectory() as temporary:
            store = self._store(temporary)
            config = new_config(["codex"])
            config["profiles"]["default"]["agents"] = []
            store.save(config)
            answers = [
                "",                # add first agent now? default yes
                "Scout",           # name
                "",                # model
                "",                # thinking
                "",                # access
                "",                # workdir
                "",                # priority
                "",                # timeout
                "Recon and research",
                "",                # routing note
                "",                # action: default done
            ]
            with scripted(answers), redirect_stdout(io.StringIO()):
                code = run_roster_wizard(store, config, "default")
            self.assertEqual(code, 0)
            saved = json.loads(Path(temporary, "config.json").read_text())
            agents = saved["profiles"]["default"]["agents"]
            self.assertEqual([agent["name"] for agent in agents], ["scout"])
            self.assertEqual(agents[0]["specialty"], "Recon and research")

    def test_edit_remove_and_preferences(self):
        with tempfile.TemporaryDirectory() as temporary:
            store = self._store(temporary)
            config = new_config(["codex", "claude"])
            store.save(config)
            names = sorted(agent["name"] for agent in config["profiles"]["default"]["agents"])
            first, second = names[0], names[1]
            answers = [
                "edit", first,     # edit first agent
                "",                # keep name
                "",                # keep account
                "",                # keep model
                "high",            # thinking
                "",                # keep access
                "",                # workdir
                "1",               # priority
                "",                # timeout
                "Sharpened specialty",
                "Pick me first",
                "remove", second, "y",
                "preferences", "Prefer the codex agent for analysis.",
                "done",
            ]
            with scripted(answers), redirect_stdout(io.StringIO()):
                run_roster_wizard(store, config, "default")
            saved = json.loads(Path(temporary, "config.json").read_text())
            profile = saved["profiles"]["default"]
            self.assertEqual(len(profile["agents"]), 1)
            agent = profile["agents"][0]
            self.assertEqual(agent["name"], first)
            self.assertEqual(agent["thinking"], "high")
            self.assertEqual(agent["priority"], 1)
            self.assertEqual(agent["specialty"], "Sharpened specialty")
            self.assertEqual(agent["routing_note"], "Pick me first")
            self.assertEqual(profile["preferences"], "Prefer the codex agent for analysis.")


class CliIntegrationTests(unittest.TestCase):
    def test_init_interactive_builds_roster_through_wizard(self):
        with tempfile.TemporaryDirectory() as temporary:
            answers = [
                "codex",           # providers
                "",                # existing login
                "",                # account label
                "",                # account id
                "",                # do not replace an existing login
                "Scout",           # name
                "",                # model
                "",                # thinking
                "",                # access
                "",                # workdir
                "",                # priority
                "",                # timeout
                "Recon and research",
                "",                # routing note
                "",                # add another agent: no
                "Prefer Scout for research.",
            ]
            args = argparse.Namespace(yes=False, provider=None, no_install=True, no_link=True)
            with (
                mock.patch.dict(os.environ, {"TICKY_HOME": temporary}),
                mock.patch("ticky_cli.cli.sys.stdin.isatty", return_value=True),
                mock.patch("ticky_cli.setup_wizard.subprocess.run") as login,
                scripted(answers),
                redirect_stdout(io.StringIO()),
            ):
                code = cli.cmd_init(args)
            login.assert_not_called()
            self.assertEqual(code, 0)
            saved = json.loads(Path(temporary, "config.json").read_text())
            agents = saved["profiles"]["default"]["agents"]
            self.assertEqual([agent["name"] for agent in agents], ["scout"])
            self.assertIn("codex-default", saved["accounts"])

    def test_init_interactive_accepting_defaults_keeps_seeded_agent(self):
        with tempfile.TemporaryDirectory() as temporary:
            args = argparse.Namespace(yes=False, provider=None, no_install=True, no_link=True)
            answers = [
                "codex", "", "", "", "",  # provider and account
                "", "", "", "", "", "", "", "", "",  # seeded agent
                "", "",  # no extra agent, keep general directions
            ]
            with (
                mock.patch.dict(os.environ, {"TICKY_HOME": temporary}),
                mock.patch("ticky_cli.cli.sys.stdin.isatty", return_value=True),
                mock.patch("ticky_cli.setup_wizard.subprocess.run") as login,
                scripted(answers),
                redirect_stdout(io.StringIO()),
            ):
                code = cli.cmd_init(args)
            login.assert_not_called()
            self.assertEqual(code, 0)
            saved = json.loads(Path(temporary, "config.json").read_text())
            self.assertEqual(len(saved["profiles"]["default"]["agents"]), 1)

    def test_agent_add_without_arguments_is_interactive(self):
        with tempfile.TemporaryDirectory() as temporary:
            store = ConfigStore(AppPaths(Path(temporary)))
            store.save(new_config(["codex"]))
            answers = [
                "Research Helper", # name outside the random production pool
                "",                # model
                "",                # thinking
                "",                # access
                "",                # workdir
                "",                # priority
                "",                # timeout
                "Research and drafting",
                "",                # routing note
            ]
            args = _agent_add_args()
            with (
                mock.patch.dict(os.environ, {"TICKY_HOME": temporary}),
                mock.patch("ticky_cli.cli.sys.stdin.isatty", return_value=True),
                scripted(answers),
                redirect_stdout(io.StringIO()),
            ):
                code = cli.cmd_agent_add(args)
            self.assertEqual(code, 0)
            saved = json.loads(Path(temporary, "config.json").read_text())
            names = [agent["name"] for agent in saved["profiles"]["default"]["agents"]]
            self.assertIn("research-helper", names)
            added = next(
                agent
                for agent in saved["profiles"]["default"]["agents"]
                if agent["name"] == "research-helper"
            )
            self.assertEqual(added["specialty"], "Research and drafting")

    def test_agent_add_with_flags_stays_noninteractive(self):
        with tempfile.TemporaryDirectory() as temporary:
            store = ConfigStore(AppPaths(Path(temporary)))
            store.save(new_config(["codex"]))
            args = _agent_add_args(model="gpt-5.5")
            with (
                mock.patch.dict(os.environ, {"TICKY_HOME": temporary}),
                mock.patch("ticky_cli.cli.sys.stdin.isatty", return_value=True),
                scripted([]),
                redirect_stdout(io.StringIO()),
            ):
                code = cli.cmd_agent_add(args)
            self.assertEqual(code, 0)
            saved = json.loads(Path(temporary, "config.json").read_text())
            self.assertEqual(len(saved["profiles"]["default"]["agents"]), 2)

    def test_agent_add_with_explicit_default_valued_flag_stays_noninteractive(self):
        with tempfile.TemporaryDirectory() as temporary:
            store = ConfigStore(AppPaths(Path(temporary)))
            store.save(new_config(["codex"]))
            args = _agent_add_args(access="read-only")
            with (
                mock.patch.dict(os.environ, {"TICKY_HOME": temporary}),
                mock.patch("ticky_cli.cli.sys.stdin.isatty", return_value=True),
                scripted([]),
                redirect_stdout(io.StringIO()),
            ):
                code = cli.cmd_agent_add(args)
            self.assertEqual(code, 0)
            saved = json.loads(Path(temporary, "config.json").read_text())
            agents = saved["profiles"]["default"]["agents"]
            self.assertEqual(len(agents), 2)
            self.assertEqual(agents[1]["access"], "read-only")
            self.assertEqual(agents[1]["priority"], 2)
            self.assertEqual(agents[1]["timeout"], 900)
            self.assertEqual(agents[1]["workdir"], "~")
            self.assertEqual(agents[1]["thinking"], "default")

    def test_init_with_empty_roster_offers_to_resume_wizard(self):
        with tempfile.TemporaryDirectory() as temporary:
            store = ConfigStore(AppPaths(Path(temporary)))
            config = new_config(["codex"])
            config["profiles"]["default"]["agents"] = []
            store.save(config)
            answers = [
                "",                # keep codex provider selection
                "",                # keep existing account
                "",                # review roster
                "Scout",           # name
                "",                # model
                "",                # thinking
                "",                # access
                "",                # workdir
                "",                # priority
                "",                # timeout
                "Recon",           # specialty
                "",                # routing note
                "",                # add another agent: no
                "",                # keep general directions
            ]
            args = argparse.Namespace(yes=False, provider=None, no_install=True, no_link=True)
            with (
                mock.patch.dict(os.environ, {"TICKY_HOME": temporary}),
                mock.patch("ticky_cli.cli.sys.stdin.isatty", return_value=True),
                scripted(answers),
                redirect_stdout(io.StringIO()),
            ):
                code = cli.cmd_init(args)
            self.assertEqual(code, 0)
            saved = json.loads(Path(temporary, "config.json").read_text())
            names = [agent["name"] for agent in saved["profiles"]["default"]["agents"]]
            self.assertEqual(names, ["scout"])

    def test_init_provider_prompt_eof_is_a_clean_config_error(self):
        with tempfile.TemporaryDirectory() as temporary:
            args = argparse.Namespace(yes=False, provider=None, no_install=True, no_link=True)
            with (
                mock.patch.dict(os.environ, {"TICKY_HOME": temporary}),
                mock.patch("ticky_cli.cli.sys.stdin.isatty", return_value=True),
                mock.patch("builtins.input", side_effect=EOFError),
                redirect_stdout(io.StringIO()),
            ):
                with self.assertRaises(ConfigError):
                    cli.cmd_init(args)
            self.assertFalse(Path(temporary, "config.json").exists())

    def test_dash_clears_model_and_routing_note_in_edit(self):
        with tempfile.TemporaryDirectory() as temporary:
            store = ConfigStore(AppPaths(Path(temporary)))
            config = new_config(["codex"])
            agent = config["profiles"]["default"]["agents"][0]
            agent["model"] = "old-model"
            agent["routing_note"] = "old note"
            store.save(config)
            answers = [
                "edit", agent["name"],
                "",                # keep name
                "-",               # clear model
                "",                # keep thinking
                "",                # keep access
                "",                # keep workdir
                "",                # keep priority
                "",                # keep timeout
                "",                # keep specialty
                "-",               # clear routing note
                "done",
            ]
            with scripted(answers), redirect_stdout(io.StringIO()):
                run_roster_wizard(store, config, "default")
            saved = json.loads(Path(temporary, "config.json").read_text())
            edited = saved["profiles"]["default"]["agents"][0]
            self.assertIsNone(edited["model"])
            self.assertEqual(edited["routing_note"], "")

    def test_dash_clears_preferences(self):
        with tempfile.TemporaryDirectory() as temporary:
            store = ConfigStore(AppPaths(Path(temporary)))
            config = new_config(["codex"])
            store.save(config)
            with scripted(["preferences", "-", "done"]), redirect_stdout(io.StringIO()):
                run_roster_wizard(store, config, "default")
            saved = json.loads(Path(temporary, "config.json").read_text())
            self.assertEqual(saved["profiles"]["default"]["preferences"], "")

    def test_roster_refuses_noninteractive_use(self):
        with tempfile.TemporaryDirectory() as temporary:
            store = ConfigStore(AppPaths(Path(temporary)))
            store.save(new_config(["codex"]))
            args = argparse.Namespace(profile=None)
            with (
                mock.patch.dict(os.environ, {"TICKY_HOME": temporary}),
                mock.patch("ticky_cli.cli.sys.stdin.isatty", return_value=False),
                redirect_stdout(io.StringIO()),
            ):
                with self.assertRaises(ConfigError):
                    cli.cmd_roster(args)


if __name__ == "__main__":
    unittest.main()
