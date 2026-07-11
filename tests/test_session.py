import contextlib
import io
import json
import os
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
    ConfigStore,
    account_record,
    agent_record,
    new_config,
)
from ticky_cli.mcp import McpServer
from ticky_cli.providers import AgentRun
from ticky_cli.session import (
    Session,
    Style,
    build_session_context,
    parse_input,
    pick_agent,
    render_response,
    wrap_text,
)


def mock_config(agent_names=("vale",)):
    config = new_config([])
    config["accounts"]["mock-default"] = account_record("mock-default", "mock", "Mock")
    agents = []
    for index, name in enumerate(agent_names):
        agent = agent_record("mock-default", name=name, display=name.title())
        agent["priority"] = index + 1
        agents.append(agent)
    config["profiles"]["default"]["agents"] = agents
    return config


class ParseInputTests(unittest.TestCase):
    def test_empty_and_whitespace(self):
        self.assertEqual(parse_input("").kind, "empty")
        self.assertEqual(parse_input("   \t").kind, "empty")

    def test_slash_command_with_args(self):
        parsed = parse_input("/use lark")
        self.assertEqual(parsed.kind, "slash")
        self.assertEqual(parsed.command, "/use")
        self.assertEqual(parsed.args, ["lark"])

    def test_at_agent_task(self):
        parsed = parse_input("@Lark review the diff")
        self.assertEqual(parsed.kind, "task")
        self.assertEqual(parsed.agent, "lark")
        self.assertEqual(parsed.text, "review the diff")

    def test_at_agent_without_task_has_empty_text(self):
        parsed = parse_input("@lark")
        self.assertEqual(parsed.kind, "task")
        self.assertEqual(parsed.agent, "lark")
        self.assertEqual(parsed.text, "")

    def test_plain_task(self):
        parsed = parse_input("summarize the repo")
        self.assertEqual(parsed.kind, "task")
        self.assertIsNone(parsed.agent)
        self.assertEqual(parsed.text, "summarize the repo")


class PickAgentTests(unittest.TestCase):
    def test_auto_route_prefers_lowest_priority(self):
        config = mock_config(("vale", "rook"))
        self.assertEqual(pick_agent(config, "default")["name"], "vale")

    def test_requested_agent_is_matched_case_insensitively(self):
        config = mock_config(("vale", "rook"))
        self.assertEqual(pick_agent(config, "default", "Rook")["name"], "rook")

    def test_unknown_agent_lists_available(self):
        config = mock_config(("vale",))
        with self.assertRaises(ConfigError) as raised:
            pick_agent(config, "default", "ghost")
        self.assertIn("vale", str(raised.exception))

    def test_disabled_agents_are_skipped(self):
        config = mock_config(("vale", "rook"))
        config["profiles"]["default"]["agents"][0]["enabled"] = False
        self.assertEqual(pick_agent(config, "default")["name"], "rook")


class SessionContextTests(unittest.TestCase):
    def test_no_history_means_no_context(self):
        self.assertIsNone(build_session_context([]))

    def test_context_keeps_recent_exchanges_and_truncates(self):
        exchanges = [(f"task {index}", "reply " + "x" * 5000) for index in range(5)]
        context = build_session_context(exchanges)
        self.assertIn("task 4", context)
        self.assertNotIn("task 0", context)
        self.assertLess(len(context), 6000)


class RenderResponseTests(unittest.TestCase):
    def test_plain_text_passes_through_without_color(self):
        style = Style(enabled=False)
        lines = render_response("hello\nworld", style, 80)
        self.assertEqual(lines, ["hello", "world"])

    def test_bold_and_headers_are_stripped_of_markup(self):
        style = Style(enabled=False)
        lines = render_response("# Title\nthis is **bold** text", style, 80)
        self.assertEqual(lines, ["Title", "this is bold text"])

    def test_long_lines_wrap_to_width(self):
        style = Style(enabled=False)
        lines = render_response("word " * 40, style, 40)
        self.assertTrue(all(len(line) <= 40 for line in lines))
        self.assertGreater(len(lines), 1)


class WrapTextTests(unittest.TestCase):
    def test_long_lines_wrap_without_losing_words(self):
        text = "alpha beta gamma delta epsilon zeta eta theta " * 4
        lines = wrap_text(text, 30)
        self.assertGreater(len(lines), 1)
        self.assertTrue(all(len(line) <= 30 for line in lines))
        self.assertEqual(" ".join(" ".join(lines).split()), " ".join(text.split()))

    def test_unbroken_tokens_are_split_to_fit(self):
        token = "x" * 90
        lines = wrap_text(f"before {token} after", 30)
        self.assertTrue(all(len(line) <= 30 for line in lines))
        self.assertEqual("".join(lines).replace(" ", ""), f"before{token}after")

    def test_empty_text_yields_one_blank_line(self):
        self.assertEqual(wrap_text("", 40), [""])


class SessionCommandTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.paths = AppPaths(Path(temporary.name))
        self.store = ConfigStore(self.paths)
        self.store.save(mock_config(("vale", "rook")))
        self.session = Session(self.store)
        self.session.style = Style(enabled=False)

    def run_command(self, line):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.session.command(parse_input(line))
        return out.getvalue()

    def saved_agent(self, name):
        config = self.store.load()
        for agent in config["profiles"]["default"]["agents"]:
            if agent["name"] == name:
                return agent
        raise AssertionError(f"agent {name!r} not in saved config")

    def test_model_sets_model_and_effort_together(self):
        self.run_command("/model vale gpt-5.5 xhigh")
        agent = self.saved_agent("vale")
        self.assertEqual(agent["model"], "gpt-5.5")
        self.assertEqual(agent["thinking"], "xhigh")

    def test_model_effort_only_keeps_model(self):
        self.run_command("/model vale high")
        agent = self.saved_agent("vale")
        self.assertIsNone(agent["model"])
        self.assertEqual(agent["thinking"], "high")

    def test_model_dash_resets_model(self):
        self.run_command("/model vale gpt-5.5")
        self.run_command("/model vale -")
        self.assertIsNone(self.saved_agent("vale")["model"])

    def test_model_without_args_lists_models_and_efforts(self):
        output = self.run_command("/model")
        self.assertIn("Vale", output)
        self.assertIn("effort default", output)

    def test_model_rejects_flag_shaped_values_without_partial_updates(self):
        output = self.run_command("/model vale high --dangerously-skip-permissions")
        self.assertIn("looks like a command-line flag", output)
        agent = self.saved_agent("vale")
        self.assertIsNone(agent["model"])
        self.assertEqual(agent["thinking"], "default")
        in_memory = self.session.config["profiles"]["default"]["agents"][0]
        self.assertEqual(in_memory["thinking"], "default")

    def test_model_rejects_too_many_arguments(self):
        output = self.run_command("/model vale opus high extra")
        self.assertIn("usage", output)
        self.assertIsNone(self.saved_agent("vale")["model"])

    def test_roster_abort_reverts_unsaved_memory_state(self):
        import builtins
        answers = iter(["edit", "", "Renamed"])

        def scripted(prompt=""):
            try:
                return next(answers)
            except StopIteration:
                raise EOFError

        original = builtins.input
        builtins.input = scripted
        try:
            output = self.run_command("/roster")
        finally:
            builtins.input = original
        names = [agent["name"]
                 for agent in self.session.config["profiles"]["default"]["agents"]]
        self.assertEqual(sorted(names), ["rook", "vale"])
        self.assertIn("ended before it finished", output)

    def test_profile_switch_clears_stale_pin(self):
        self.run_command("/profile save solo")
        config = self.store.load()
        config["profiles"]["solo"]["agents"] = [
            agent for agent in config["profiles"]["solo"]["agents"]
            if agent["name"] == "vale"
        ]
        self.store.save(config)
        self.session.config = self.store.load()
        self.session.pinned_agent = "rook"
        output = self.run_command("/profile solo")
        self.assertIsNone(self.session.pinned_agent)
        self.assertIn("pin cleared", output)

    def test_refresh_config_follows_external_profile_switch(self):
        config = self.store.load()
        config["profiles"]["other"] = {"description": "", "preferences": "",
                                       "agents": list(config["profiles"]["default"]["agents"])}
        config["active_profile"] = "other"
        self.store.save(config)
        stat = self.paths.config.stat()
        os.utime(self.paths.config, ns=(stat.st_atime_ns, stat.st_mtime_ns + 1_000_000))
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.session.refresh_config()
        self.assertEqual(self.session.profile_name, "other")
        self.assertIn("profile is now other", out.getvalue())

    def test_tagline_set_and_clear(self):
        self.run_command("/tagline vale Deep audits and gnarly refactors")
        self.assertEqual(self.saved_agent("vale")["specialty"],
                         "Deep audits and gnarly refactors")
        self.run_command("/tagline vale -")
        self.assertEqual(self.saved_agent("vale")["specialty"], "")

    def test_setup_slash_command_runs_guided_setup_and_reloads(self):
        with mock.patch("ticky_cli.setup_wizard.run_setup_wizard") as setup:
            self.run_command("/setup")
        setup.assert_called_once()
        store, config = setup.call_args.args
        self.assertIs(store, self.store)
        self.assertEqual(config, self.session.config)

    def test_profile_save_snapshots_current_roster(self):
        self.run_command("/profile save backup my snapshot")
        config = self.store.load()
        self.assertIn("backup", config["profiles"])
        self.assertEqual(len(config["profiles"]["backup"]["agents"]), 2)
        self.assertEqual(config["profiles"]["backup"]["description"], "my snapshot")

    def test_profile_save_refuses_existing_name(self):
        self.run_command("/profile save backup")
        before = self.store.load()["profiles"]["backup"]
        output = self.run_command("/profile save backup")
        self.assertIn("already exists", output)
        self.assertEqual(self.store.load()["profiles"]["backup"], before)

    def test_profile_delete_removes_inactive_profile_only(self):
        self.run_command("/profile save backup")
        output = self.run_command("/profile delete default")
        self.assertIn("cannot delete the active profile", output)
        self.run_command("/profile delete backup")
        config = self.store.load()
        self.assertNotIn("backup", config["profiles"])
        self.assertIn("default", config["profiles"])

    def test_profile_rename_updates_active_pointer(self):
        self.run_command("/profile rename default main")
        config = self.store.load()
        self.assertIn("main", config["profiles"])
        self.assertNotIn("default", config["profiles"])
        self.assertEqual(config["active_profile"], "main")
        self.assertEqual(self.session.profile_name, "main")

    def test_banner_and_agents_fit_terminal_width(self):
        original = os.environ.get("COLUMNS")
        os.environ["COLUMNS"] = "44"
        self.addCleanup(
            lambda: os.environ.update({"COLUMNS": original}) if original
            else os.environ.pop("COLUMNS", None)
        )
        self.run_command(
            "/tagline vale An extremely long specialty line that used to be"
            " truncated at the terminal edge and unreadable"
        )
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.session.banner()
            self.session.command(parse_input("/agents"))
        lines = out.getvalue().splitlines()
        self.assertTrue(all(len(line) <= 44 for line in lines),
                        [line for line in lines if len(line) > 44])
        self.assertIn("unreadable", out.getvalue())


class AgentRunTests(unittest.TestCase):
    def test_mock_run_resolves_immediately(self):
        with tempfile.TemporaryDirectory() as temporary:
            paths = AppPaths(Path(temporary))
            account = account_record("mock-default", "mock", "Mock")
            agent = agent_record("mock-default", name="vale", display="Vale")
            run = AgentRun(paths, account, agent, "ping")
            self.assertFalse(run.running())
            result = run.finish()
            self.assertTrue(result.ok)
            self.assertIn("[mock:vale]", result.text)

    def test_missing_binary_reports_start_failure(self):
        with tempfile.TemporaryDirectory() as temporary:
            paths = AppPaths(Path(temporary))
            account = account_record("codex-default", "codex", "Codex")
            agent = agent_record("codex-default", name="vale", display="Vale")
            agent["workdir"] = temporary
            import os
            original = os.environ.get("PATH")
            os.environ["PATH"] = temporary
            try:
                run = AgentRun(paths, account, agent, "ping")
            finally:
                os.environ["PATH"] = original or ""
            self.assertFalse(run.running())
            result = run.finish()
            self.assertFalse(result.ok)
            self.assertIn("could not start provider", result.text)


class McpConfigReloadTests(unittest.TestCase):
    def test_tools_list_and_dispatch_pick_up_config_edits(self):
        with tempfile.TemporaryDirectory() as temporary:
            paths = AppPaths(Path(temporary))
            store = ConfigStore(paths)
            store.save(mock_config(("vale",)))
            sink = io.StringIO()
            server = McpServer(store.load(), paths, sink=sink, store=store)

            server.handle({"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
            first = json.loads(sink.getvalue().splitlines()[-1])
            names = {tool["name"] for tool in first["result"]["tools"]}
            self.assertEqual(names, {"ask_vale", "ticky_roster"})

            edited = mock_config(("vale", "rook"))
            store.save(edited)
            import os
            stat = paths.config.stat()
            os.utime(paths.config, ns=(stat.st_atime_ns, stat.st_mtime_ns + 1_000_000))

            server.handle({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
            second = json.loads(sink.getvalue().splitlines()[-1])
            names = {tool["name"] for tool in second["result"]["tools"]}
            self.assertEqual(names, {"ask_vale", "ask_rook", "ticky_roster"})

            server.handle({
                "jsonrpc": "2.0", "id": 3, "method": "tools/call",
                "params": {"name": "ask_rook", "arguments": {"task": "ping", "reason": "reload test"}},
            })
            for worker in server._workers:
                worker.join(timeout=10)
            responses = {value["id"]: value for value in map(json.loads, sink.getvalue().splitlines())}
            self.assertFalse(responses[3]["result"]["isError"])
            self.assertIn("[mock:rook]", responses[3]["result"]["content"][0]["text"])

    def test_broken_config_edit_keeps_last_good_config(self):
        with tempfile.TemporaryDirectory() as temporary:
            paths = AppPaths(Path(temporary))
            store = ConfigStore(paths)
            store.save(mock_config(("vale",)))
            sink = io.StringIO()
            server = McpServer(store.load(), paths, sink=sink, store=store)

            paths.config.write_text("{not json", encoding="utf-8")
            import os
            stat = paths.config.stat()
            os.utime(paths.config, ns=(stat.st_atime_ns, stat.st_mtime_ns + 1_000_000))

            server.handle({"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
            response = json.loads(sink.getvalue().splitlines()[-1])
            names = {tool["name"] for tool in response["result"]["tools"]}
            self.assertEqual(names, {"ask_vale", "ticky_roster"})


if __name__ == "__main__":
    unittest.main()
