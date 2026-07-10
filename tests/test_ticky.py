import json
import os
from pathlib import Path
import runpy
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
TICKY = ROOT / "ticky"


class TickyCoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.previous_home = os.environ.get("TICKY_HOME")
        os.environ["TICKY_HOME"] = self.temp.name
        self.module = runpy.run_path(str(TICKY))

    def tearDown(self):
        if self.previous_home is None:
            os.environ.pop("TICKY_HOME", None)
        else:
            os.environ["TICKY_HOME"] = self.previous_home
        self.temp.cleanup()

    def test_state_keeps_calls_from_multiple_sessions(self):
        write_state = self.module["write_state"]
        state_path = Path(self.module["STATE_PATH"])
        rook = {"agent": "Rook", "reason": "review", "started": "2026-07-10T00:00:00+00:00"}
        wren = {"agent": "Wren", "reason": "research", "started": "2026-07-10T00:00:01+00:00"}

        write_state([rook], "session-a")
        write_state([wren], "session-b")
        state = json.loads(state_path.read_text())
        self.assertEqual({call["agent"] for call in state["running"]}, {"Rook", "Wren"})

        write_state([], "session-a")
        state = json.loads(state_path.read_text())
        self.assertEqual(state["running"], [wren])

    def test_alternate_home_does_not_report_the_live_widget(self):
        self.assertEqual(self.module["widget_pids"](), [])

    def test_default_roster_names(self):
        names = [a["name"] for a in self.module["DEFAULT_AGENTS"]]
        self.assertEqual(names, ["rook", "wren", "finch"])
        for agent in self.module["DEFAULT_AGENTS"]:
            self.assertEqual(agent["display"], agent["name"].capitalize())

    def test_swift_widget_defaults_match_cli_defaults(self):
        # The widget duplicates DEFAULT_AGENTS/DEFAULT_PREFS; catch drift.
        source = (ROOT / "widget" / "macos" / "TickyWidget.swift").read_text()
        for agent in self.module["DEFAULT_AGENTS"]:
            self.assertIn(f'"{agent["display"]}"', source)
            self.assertIn(agent["specialty"], source)
        self.assertIn("prefer the codex-backed ones (Rook, Wren)", source)

    def test_no_platform_specific_wording_in_shared_strings(self):
        # Strings that reach the boss LLM or config must not assume macOS.
        shared = self.module["DEFAULT_PREFS"] + json.dumps(self.module["DEFAULT_AGENTS"])
        for word in ("menu bar", "macOS", "Mac"):
            self.assertNotIn(word, shared)

    def test_backend_start_failure_returns_an_error(self):
        agent = {
            "name": "probe",
            "display": "Probe",
            "backend": "codex",
            "model": None,
            "specialty": "probe",
            "priority": 1,
            "access": "read-only",
            "workdir": str(Path(self.temp.name) / "missing"),
            "network": False,
            "timeout": 1,
            "enabled": True,
            "extra_args": [],
        }
        ok, text, duration = self.module["run_agent"](agent, "ping")
        self.assertFalse(ok)
        self.assertIn("could not start backend", text)
        self.assertEqual(duration, 0.0)


if __name__ == "__main__":
    unittest.main()
