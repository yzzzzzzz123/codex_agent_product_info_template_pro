"""Run the internal Node bridge's entirely offline browser/protocol contracts."""

from __future__ import annotations

import os
from pathlib import Path
import shutil
import subprocess
import unittest


ROOT = Path(__file__).resolve().parents[1]
NODE = os.environ.get("PLAYWRIGHT_NODEJS_PATH") or shutil.which("node")


@unittest.skipUnless(NODE, "需要已有系统 Node 才能运行离线采集桥接测试")
class NodeCaptureTests(unittest.TestCase):
    def test_offline_node_capture_contracts(self) -> None:
        result = subprocess.run(
            [str(NODE), "--test", str(ROOT / "tests/node_capture.test.cjs")],
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
