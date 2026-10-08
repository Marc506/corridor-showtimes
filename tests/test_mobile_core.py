"""The phone pages' data layer (site/m/_shared/core.js): its own Node tests, run from pytest."""
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
CORE_TEST = ROOT / "site" / "m" / "_shared" / "core.test.js"


def test_mobile_core_js():
    if not shutil.which("node"):
        pytest.skip("node is not installed")
    out = subprocess.run(["node", str(CORE_TEST)], capture_output=True, text=True, timeout=60)
    assert out.returncode == 0, out.stdout + out.stderr
