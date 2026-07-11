import shutil
import subprocess
import tempfile
import unittest
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LAUNCHER = ROOT / "Start Ticky.command"
WINDOWS_LAUNCHER = ROOT / "Start Ticky.cmd"


class LauncherBehaviorTests(unittest.TestCase):
    def test_windows_launcher_uses_source_wrapper_and_setup(self):
        text = WINDOWS_LAUNCHER.read_text(encoding="utf-8")
        self.assertIn('set "PYTHON=py -3"', text)
        self.assertIn('set "PYTHON=python"', text)
        self.assertIn('%PYTHON% "%~dp0ticky" setup', text)
        self.assertIn('%PYTHON% "%~dp0ticky" ui', text)
        self.assertIn("%USERPROFILE%\\.ticky\\config.json", text)

    @unittest.skipIf(os.name == "nt", "macOS launcher requires zsh")
    def test_status_failure_is_visible_and_propagated(self):
        with tempfile.TemporaryDirectory() as temporary:
            checkout = Path(temporary, "checkout with spaces")
            checkout.mkdir()
            launcher = checkout / LAUNCHER.name
            shutil.copy2(LAUNCHER, launcher)
            ticky = checkout / "ticky"
            ticky.write_text(
                "#!/bin/sh\n"
                "if [ \"$1\" = setup ]; then exit 0; fi\n"
                "if [ \"$1\" = status ]; then echo status failed >&2; exit 7; fi\n"
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
            self.assertIn("status failed", result.stderr)
            self.assertIn("status check failed with exit code 7", result.stdout)
            self.assertNotIn("Ticky is ready", result.stdout)


if __name__ == "__main__":
    unittest.main()
