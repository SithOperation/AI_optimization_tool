"""Large benchmarks run separately so ordinary test runs remain short."""
import os
from pathlib import Path
import subprocess
import sys
import pytest


@pytest.mark.skipif(os.getenv("AIOPT_ENTERPRISE_STRESS") != "1", reason="opt-in 500k/1m importer benchmark")
@pytest.mark.parametrize("rows", [500000, 1000000])
def test_enterprise_import_scale(rows):
    subprocess.run([sys.executable, "scripts/stress-enterprise.py", "--rows", str(rows),
                    "--output", str(Path("artifacts") / f"stress-{rows}.json")], check=True, timeout=3600)
