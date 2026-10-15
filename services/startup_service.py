"""Windows 当前用户开机启动，不需要管理员权限。"""

import subprocess
import sys
from pathlib import Path

from app.identity import APP_ID, LEGACY_APP_ID
from app.utils import is_windows


def set_autostart(enabled):
    if not is_windows():
        if enabled:
            raise RuntimeError("开机启动仅支持 Windows")
        return
    import winreg

    with winreg.OpenKey(
        winreg.HKEY_CURRENT_USER,
        r"Software\Microsoft\Windows\CurrentVersion\Run",
        0,
        winreg.KEY_SET_VALUE,
    ) as key:
        if enabled:
            command = [sys.executable]
            if not getattr(sys, "frozen", False):
                command.append(str(Path(__file__).resolve().parent.parent / "main.py"))
            command.append("--autostart")
            winreg.SetValueEx(key, APP_ID, 0, winreg.REG_SZ, subprocess.list2cmdline(command))
        else:
            try:
                winreg.DeleteValue(key, APP_ID)
            except FileNotFoundError:
                pass

        # 更新或关闭自启时同时移除旧名称，避免两个启动项并存。
        try:
            winreg.DeleteValue(key, LEGACY_APP_ID)
        except FileNotFoundError:
            pass
