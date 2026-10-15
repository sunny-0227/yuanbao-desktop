"""实际启动与可观察结果分开记录，不能把Shell接受请求当成窗口已出现。"""

import ctypes
import os
import shutil
import subprocess
import time
from ctypes import wintypes
from dataclasses import dataclass

import psutil

from app.utils import is_windows
from app.windows import user32_api
from services.app_discovery_service import _parse_lnk


@dataclass(frozen=True)
class LaunchOutcome:
    name: str
    target: str
    status: str
    detail: str = ""

    def __str__(self):
        if self.status == "failed":
            return f"未能启动「{self.name}」：{self.detail}"
        if self.status == "window":
            activation = "已尝试切换到前台。" if self.detail == "activation_attempted" else ""
            return f"已检测到「{self.name}」的可见窗口。{activation}\n程序位置：{self.target}"
        if self.status == "process":
            return (
                f"检测到「{self.name}」的程序正在运行，但尚未检测到可见窗口。\n"
                f"程序位置：{self.target}\n可能仍在加载，或以后台/托盘方式运行。"
            )
        return (
            f"已向Windows发送「{self.name}」的启动请求，暂未确认程序或窗口已出现。\n"
            f"程序位置：{self.target}\n可以稍后问“打开了吗”，我会重新检查，不会重复启动。"
        )


def _process_ids(target):
    expected = os.path.normcase(os.path.abspath(target))
    matches = set()
    for process in psutil.process_iter(["pid", "exe"]):
        try:
            exe = process.info.get("exe")
            if exe and os.path.normcase(os.path.abspath(exe)) == expected:
                matches.add(process.info["pid"])
        except (psutil.Error, OSError):
            continue
    return matches


def _find_window(pids, activate=False):
    """按进程ID关联顶层可见窗口，不靠窗口标题猜软件身份。"""
    if not pids or not is_windows():
        return False
    api = user32_api()
    callback_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    api.EnumWindows.argtypes = [callback_type, wintypes.LPARAM]
    api.EnumWindows.restype = wintypes.BOOL
    api.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
    api.ShowWindow.restype = wintypes.BOOL
    api.SetForegroundWindow.argtypes = [wintypes.HWND]
    api.SetForegroundWindow.restype = wintypes.BOOL
    found = []

    @callback_type
    def visit(hwnd, extra):
        if api.IsWindowVisible(hwnd):
            pid = wintypes.DWORD()
            api.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            if pid.value in pids:
                found.append(hwnd)
        return True

    api.EnumWindows(visit, 0)
    if found and activate:
        # Windows可能因前台切换限制拒绝激活，因此结果只声明“尝试切换”。
        api.ShowWindow(found[0], 9)
        api.SetForegroundWindow(found[0])
    return bool(found)


def observe_launch(name, target, activate=False):
    if not is_windows() or not os.path.isfile(target):
        return LaunchOutcome(name, target, "requested")
    try:
        pids = _process_ids(target)
        if _find_window(pids, activate):
            return LaunchOutcome(name, target, "window", "activation_attempted" if activate else "")
        if pids:
            return LaunchOutcome(name, target, "process")
    except (psutil.Error, OSError, AttributeError):
        # 无权限观察时不能据此断言启动成功或失败。
        pass
    return LaunchOutcome(name, target, "requested")


def launch_application(command, name, arguments="", working_dir="", timeout=2):
    if not is_windows():
        return LaunchOutcome(name, command, "failed", "该功能仅支持Windows")
    target = os.path.normpath(os.path.expandvars(command))
    work = os.path.expandvars(working_dir) if working_dir else ""
    if not os.path.isfile(target):
        target = shutil.which(target) or target
    if not os.path.isfile(target):
        return LaunchOutcome(name, target, "failed", "程序文件不存在，启动请求未执行")
    if target.lower().endswith(".lnk"):
        entry = _parse_lnk(target, "explicit_shortcut")
        if not entry:
            return LaunchOutcome(
                name, target, "failed", "无法解析快捷方式，或它指向的程序已经移动/删除"
            )
        target = entry["path"]
        arguments = entry.get("arguments", "")
        work = entry.get("working_dir", "")
    kwargs = {"shell": False}
    if work and os.path.isdir(work):
        kwargs["cwd"] = work
    child = None
    try:
        if arguments:
            # 参数来自本地快捷方式/配置，不接受模型拼接命令。
            child = subprocess.Popen(subprocess.list2cmdline([target]) + " " + arguments, **kwargs)
        else:
            try:
                os.startfile(target)
            except (OSError, AttributeError):
                if not target.lower().endswith((".exe", ".com")):
                    raise
                child = subprocess.Popen([target], **kwargs)
    except (OSError, ValueError) as exc:
        return LaunchOutcome(name, target, "failed", str(exc))
    deadline = time.monotonic() + timeout
    last = LaunchOutcome(name, target, "requested")
    while True:
        last = observe_launch(name, target, activate=True)
        if last.status == "window":
            return last
        if child is not None and child.poll() not in (None, 0):
            return LaunchOutcome(name, target, "failed", f"程序已退出，退出码 {child.returncode}")
        if time.monotonic() >= deadline:
            return last
        time.sleep(0.15)
