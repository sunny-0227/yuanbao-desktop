"""测试隔离用户数据，不启动桌面应用或执行真实系统操作。"""

import os
import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ["YUANBAO_DATA_DIR"] = tempfile.mkdtemp(prefix="yuanbao-tests-")
os.environ["QT_QPA_PLATFORM"] = "offscreen"


@pytest.fixture
def db(tmp_path):
    from app.storage import Database

    return Database(tmp_path / "test.sqlite3")


@pytest.fixture(scope="session")
def qt_core():
    from PySide6.QtCore import QCoreApplication

    return QCoreApplication.instance() or QCoreApplication([])


def wait_for(app, condition, timeout=3):
    import time

    end = time.monotonic() + timeout
    while time.monotonic() < end:
        app.processEvents()
        if condition():
            return
        time.sleep(0.005)
    raise AssertionError("等待事件超时")
