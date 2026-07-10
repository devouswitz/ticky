import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
TICKY = ROOT / "ticky"
sys.path.insert(0, str(ROOT / "src"))

from ticky_cli.config import AppPaths, ConfigStore, agent_record, generated_agent_name


class ConfigBehaviorTests(unittest.TestCase):
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
            environment = dict(
                os.environ,
                TICKY_HOME=temporary,
                HOME=temporary,
                USERPROFILE=temporary,
            )
            initialized = subprocess.run(
                [str(TICKY), "init", "--yes", "--no-install"],
                cwd=ROOT,
                env=environment,
                text=True,
                capture_output=True,
                timeout=30,
            )
            self.assertEqual(initialized.returncode, 0, initialized.stderr)
            config = json.loads(Path(temporary, "config.json").read_text())
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
        record = agent_record("codex-work", existing=("luna", "rook"))
        self.assertEqual(record["account"], "codex-work")
        self.assertNotIn(record["name"], {"luna", "rook"})
        self.assertEqual(record["thinking"], "default")
        self.assertEqual(record["access"], "read-only")


if __name__ == "__main__":
    unittest.main()
