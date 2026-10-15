import subprocess
import sys
from pathlib import Path

import pytest


@pytest.mark.skipif(sys.platform != "win32", reason="Mac 仅执行核心单元测试，界面在 Windows 验证")
def test_windows_ui():
    root = Path(__file__).resolve().parent.parent
    subprocess.run(
        [sys.executable, str(root / "scripts/smoke_windows.py")], check=True, cwd=root, timeout=30
    )
