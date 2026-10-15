"""只读资源与可写用户数据严格分离，开发和单文件打包使用同一接口。"""

import os
import sys
from pathlib import Path

from app.identity import APP_ID, DATA_ENV, LEGACY_APP_ID, LEGACY_DATA_ENV


def get_base_path() -> str:
    return str(Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent)))


def get_data_base_path() -> str:
    """支持便携/测试目录覆盖；默认使用系统用户数据目录。"""
    override = os.getenv(DATA_ENV) or os.getenv(LEGACY_DATA_ENV)
    if override:
        return str(Path(override).expanduser().resolve())
    if sys.platform == "win32":
        root = Path(os.getenv("LOCALAPPDATA", str(Path.home() / "AppData/Local")))
    elif sys.platform == "darwin":
        root = Path.home() / "Library/Application Support"
    else:
        root = Path(os.getenv("XDG_DATA_HOME", str(Path.home() / ".local/share")))
    current, legacy = root / APP_ID, root / LEGACY_APP_ID
    # 已有安装继续使用原目录，避免复制数据库或丢失记录；新安装使用新名称。
    if not (current / "config.json").exists() and not (current / "assistant.sqlite3").exists():
        if (legacy / "config.json").exists() or (legacy / "assistant.sqlite3").exists():
            return str(legacy)
    return str(current)


def resource_path(relative_path: str) -> str:
    return str(Path(get_base_path()) / relative_path)


def data_path(relative_path: str = "") -> str:
    # 兼容旧服务的 data/xxx 与 xxx 两种调用，均落入同一个数据目录。
    parts = Path(relative_path).parts
    if parts and parts[0] == "data":
        parts = parts[1:]
    return str(Path(get_data_base_path()).joinpath(*parts))
