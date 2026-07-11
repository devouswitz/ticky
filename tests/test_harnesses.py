import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from ticky_cli.harnesses import install, server_command


class HarnessInstallTests(unittest.TestCase):
    def test_windows_source_checkout_uses_python_for_mcp_server(self):
        command, arguments = server_command("research", platform="nt")
        self.assertEqual(command, sys.executable)
        self.assertTrue(arguments[0].endswith("ticky"))
        self.assertEqual(arguments[1:], ["serve", "--profile", "research"])

    def test_failed_registration_restores_previous_config(self):
        for target, relative in (
            ("claude", ".claude.json"),
            ("codex", ".codex/config.toml"),
        ):
            with self.subTest(target=target), tempfile.TemporaryDirectory() as temporary:
                config_path = Path(temporary, relative)
                config_path.parent.mkdir(parents=True, exist_ok=True)
                original = f"previous {target} registration\n".encode()
                config_path.write_bytes(original)
                config_path.chmod(0o600)
                commands = []

                def run(command, **_kwargs):
                    commands.append(command)
                    config_path.write_text("partially changed\n", encoding="utf-8")
                    if "remove" in command:
                        return subprocess.CompletedProcess(command, 0, "", "")
                    return subprocess.CompletedProcess(command, 1, "", "add failed")

                with (
                    mock.patch.dict(os.environ, {"HOME": temporary}),
                    mock.patch("ticky_cli.harnesses.shutil.which", return_value=target),
                    mock.patch("ticky_cli.harnesses.executable_path", return_value="/tmp/ticky"),
                    mock.patch("ticky_cli.harnesses.subprocess.run", side_effect=run),
                ):
                    ok, message = install(target, "default")

                self.assertFalse(ok)
                self.assertIn("add failed", message)
                self.assertIn("previous registration restored", message)
                self.assertEqual(config_path.read_bytes(), original)
                self.assertEqual(config_path.stat().st_mode & 0o777, 0o600)
                self.assertEqual(len(commands), 2)

    def test_registration_process_error_restores_previous_config(self):
        with tempfile.TemporaryDirectory() as temporary:
            config_path = Path(temporary, ".codex", "config.toml")
            config_path.parent.mkdir(parents=True)
            original = b"previous codex registration\n"
            config_path.write_bytes(original)

            def run(command, **_kwargs):
                config_path.write_text("partially changed\n", encoding="utf-8")
                if "remove" in command:
                    return subprocess.CompletedProcess(command, 0, "", "")
                raise OSError("could not start codex")

            with (
                mock.patch.dict(os.environ, {"HOME": temporary}),
                mock.patch("ticky_cli.harnesses.shutil.which", return_value="codex"),
                mock.patch("ticky_cli.harnesses.executable_path", return_value="/tmp/ticky"),
                mock.patch("ticky_cli.harnesses.subprocess.run", side_effect=run),
            ):
                ok, message = install("codex", "default")

            self.assertFalse(ok)
            self.assertIn("could not start codex", message)
            self.assertIn("previous registration restored", message)
            self.assertEqual(config_path.read_bytes(), original)

    def test_codex_registration_prompts_for_write_capable_ticky_tools(self):
        with tempfile.TemporaryDirectory() as temporary:
            config_path = Path(temporary, ".codex", "config.toml")
            config_path.parent.mkdir(parents=True)

            def run(command, **_kwargs):
                if "add" in command:
                    config_path.write_text(
                        "[mcp_servers.ticky]\n"
                        "command = \"/tmp/ticky\"\n"
                        "args = [\"serve\"]\n"
                        "default_tools_approval_mode = \"approve\"\n",
                        encoding="utf-8",
                    )
                return subprocess.CompletedProcess(command, 0, "", "")

            with (
                mock.patch.dict(os.environ, {"HOME": temporary}),
                mock.patch("ticky_cli.harnesses.shutil.which", return_value="codex"),
                mock.patch("ticky_cli.harnesses.executable_path", return_value="/tmp/ticky"),
                mock.patch("ticky_cli.harnesses.subprocess.run", side_effect=run),
            ):
                ok, message = install("codex", "default")

            self.assertTrue(ok, message)
            updated = config_path.read_text(encoding="utf-8")
            self.assertIn('default_tools_approval_mode = "writes"', updated)
            self.assertNotIn('default_tools_approval_mode = "approve"', updated)
            self.assertIn("write-capable tools", message)


if __name__ == "__main__":
    unittest.main()
