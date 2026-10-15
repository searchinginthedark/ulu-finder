"""Runs tests/sw_shim.mjs, which drives the real public/sw.js fetch handler under Node."""
import shutil
import subprocess
import unittest
from pathlib import Path

SHIM = Path(__file__).with_name("sw_shim.mjs")


class ServiceWorkerTest(unittest.TestCase):
    @unittest.skipUnless(shutil.which("node"), "node not installed")
    def test_network_first_with_timeout(self):
        p = subprocess.run(["node", str(SHIM)], capture_output=True, text=True,
                           encoding="utf-8", timeout=60)
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)


if __name__ == "__main__":
    unittest.main()
