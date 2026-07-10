import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LAUNCHER = ROOT / "Start Ticky.command"


class LauncherBehaviorTests(unittest.TestCase):
    def test_status_failure_is_visible_and_propagated(self):
        with tempfile.TemporaryDirectory() as temporary:
            checkout = Path(temporary, "checkout with spaces")
            checkout.mkdir()
            launcher = checkout / LAUNCHER.name
            shutil.copy2(LAUNCHER, launcher)
            ticky = checkout / "ticky"
            ticky.write_text(
                "#!/bin/sh\n"
                "if [ \"$1\" = init ]; then exit 0; fi\n"
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
