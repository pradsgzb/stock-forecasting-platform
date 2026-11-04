import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.integration

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def test_repository_static_validation_passes() -> None:
    completed = subprocess.run(
        [sys.executable, "scripts/validate-repository.py", "--root", str(PROJECT_ROOT)],
        cwd=PROJECT_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0, completed.stderr
    assert "validation passed" in completed.stdout
