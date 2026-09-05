import shutil
import subprocess
import tempfile
import unittest
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LAUNCHER = ROOT / "Start Ticky.command"
WINDOWS_LAUNCHER = ROOT / "Start Ticky.cmd"


class LauncherBehaviorTests(unittest.TestCase):
    def test_windows_launcher_delegates_to_smart_start(self):
        text = WINDOWS_LAUNCHER.read_text(encoding="utf-8")
        self.assertIn('set "PYTHON=py -3"', text)
        self.assertIn('set "PYTHON=python"', text)
        self.assertIn('%PYTHON% "%~dp0ticky" start', text)
        self.assertNotIn('%PYTHON% "%~dp0ticky" setup', text)
        self.assertNotIn('%PYTHON% "%~dp0ticky" account status', text)
        self.assertNotIn('%PYTHON% "%~dp0ticky" ui', text)

    @unittest.skipUnless(sys.platform == "darwin", "macOS launcher is tested on macOS")
    def test_first_launch_delegates_setup_policy_to_start(self):
        with tempfile.TemporaryDirectory() as temporary:
            checkout = Path(temporary, "checkout with spaces")
            checkout.mkdir()
            launcher = checkout / LAUNCHER.name
            shutil.copy2(LAUNCHER, launcher)
            calls = Path(temporary, "calls.txt")
            ticky = checkout / "ticky"
            ticky.write_text(
                "#!/bin/sh\n"
                "printf '%s\\n' \"$*\" >> \"$TICKY_TEST_LOG\"\n"
                "exit 0\n",
                encoding="utf-8",
            )
            ticky.chmod(0o755)

            result = subprocess.run(
                [str(launcher)],
                input="\n",
                text=True,
                capture_output=True,
                env=dict(
                    os.environ,
                    TICKY_HOME=str(Path(temporary, "ticky-home")),
                    TICKY_TEST_LOG=str(calls),
                ),
                timeout=30,
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(
                calls.read_text(encoding="utf-8").splitlines(),
                ["start"],
            )

    @unittest.skipUnless(sys.platform == "darwin", "macOS launcher is tested on macOS")
    def test_existing_config_uses_the_same_start_path(self):
        with tempfile.TemporaryDirectory() as temporary:
            checkout = Path(temporary, "checkout")
            checkout.mkdir()
            launcher = checkout / LAUNCHER.name
            shutil.copy2(LAUNCHER, launcher)
            calls = Path(temporary, "calls.txt")
            home = Path(temporary, "ticky-home")
            home.mkdir()
            Path(home, "config.json").write_text("{}\n", encoding="utf-8")
            ticky = checkout / "ticky"
            ticky.write_text(
                "#!/bin/sh\n"
                "printf '%s\\n' \"$*\" >> \"$TICKY_TEST_LOG\"\n"
                "exit 0\n",
                encoding="utf-8",
            )
            ticky.chmod(0o755)

            result = subprocess.run(
                [str(launcher)],
                input="\n",
                text=True,
                capture_output=True,
                env=dict(os.environ, TICKY_HOME=str(home), TICKY_TEST_LOG=str(calls)),
                timeout=30,
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(
                calls.read_text(encoding="utf-8").splitlines(),
                ["start"],
            )

    @unittest.skipUnless(sys.platform == "darwin", "macOS launcher is tested on macOS")
    def test_finder_path_finds_grok_and_nvm_provider_clis(self):
        with tempfile.TemporaryDirectory() as temporary:
            checkout = Path(temporary, "checkout")
            checkout.mkdir()
            launcher = checkout / LAUNCHER.name
            shutil.copy2(LAUNCHER, launcher)
            fake_home = Path(temporary, "home")
            ticky_home = Path(temporary, "ticky-home")
            ticky_home.mkdir()
            Path(ticky_home, "config.json").write_text("{}\n", encoding="utf-8")
            codex = Path(fake_home, ".nvm", "versions", "node", "v23.11.1", "bin", "codex")
            grok = Path(fake_home, ".grok", "bin", "grok")
            for executable in (codex, grok):
                executable.parent.mkdir(parents=True, exist_ok=True)
                executable.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
                executable.chmod(0o755)
            ticky = checkout / "ticky"
            ticky.write_text(
                "#!/bin/sh\n"
                "if [ \"$1\" = start ]; then\n"
                "  command -v codex\n"
                "  command -v grok\n"
                "fi\n"
                "exit 0\n",
                encoding="utf-8",
            )
            ticky.chmod(0o755)

            result = subprocess.run(
                [str(launcher)],
                input="\n",
                text=True,
                capture_output=True,
                env=dict(os.environ, HOME=str(fake_home), TICKY_HOME=str(ticky_home)),
                timeout=30,
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn(str(codex), result.stdout)
            self.assertIn(str(grok), result.stdout)

    @unittest.skipUnless(sys.platform == "darwin", "macOS launcher is tested on macOS")
    def test_start_failure_is_visible_and_propagated(self):
        with tempfile.TemporaryDirectory() as temporary:
            checkout = Path(temporary, "checkout with spaces")
            checkout.mkdir()
            launcher = checkout / LAUNCHER.name
            shutil.copy2(LAUNCHER, launcher)
            ticky = checkout / "ticky"
            ticky.write_text(
                "#!/bin/sh\n"
                "if [ \"$1\" = start ]; then echo start failed >&2; exit 7; fi\n"
                "exit 9\n",
                encoding="utf-8",
            )
            ticky.chmod(0o755)

            result = subprocess.run(
                [str(launcher)],
                input="\n",
                text=True,
                capture_output=True,
                timeout=30,
            )

            self.assertEqual(result.returncode, 7)
            self.assertIn("start failed", result.stderr)
            self.assertIn("Ticky could not start", result.stdout)


if __name__ == "__main__":
    unittest.main()
