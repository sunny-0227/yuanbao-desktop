"""Windows 操作适配与受限算术；系统操作不使用 shell 或 AI 生成代码。"""

import ast
import ctypes
import math
import operator
import os
import subprocess
from pathlib import Path

from app.utils import is_windows


def calculate(expression):
    if len(expression) > 200:
        raise ValueError("表达式太长")
    tree = ast.parse(expression.replace("×", "*").replace("÷", "/").replace("^", "**"), mode="eval")
    ops = {
        ast.Add: operator.add,
        ast.Sub: operator.sub,
        ast.Mult: operator.mul,
        ast.Div: operator.truediv,
        ast.FloorDiv: operator.floordiv,
        ast.Mod: operator.mod,
        ast.Pow: operator.pow,
    }

    def walk(node, depth=0):
        if depth > 16:
            raise ValueError("表达式过于复杂")
        if isinstance(node, ast.Constant) and type(node.value) in (int, float):
            result = node.value
        elif isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
            result = walk(node.operand, depth + 1) * (-1 if isinstance(node.op, ast.USub) else 1)
        elif isinstance(node, ast.BinOp) and type(node.op) in ops:
            left, right = walk(node.left, depth + 1), walk(node.right, depth + 1)
            if isinstance(node.op, ast.Pow) and abs(right) > 12:
                raise ValueError("指数过大")
            result = ops[type(node.op)](left, right)
        else:
            raise ValueError("只支持数字、括号与加减乘除，不执行代码")
        if abs(result) > 1e100 or not math.isfinite(result):
            raise ValueError("结果超出范围")
        return result

    return str(walk(tree.body))


class ToolsService:
    def __init__(self, config, apps):
        self.config, self.apps = config, apps

    def execute(self, action, data):
        if action == "calculate":
            return calculate(data["expression"])
        if action == "mkdir":
            path = Path(os.path.expandvars(data["path"])).expanduser()
            if not path.is_absolute():
                path = Path.home() / "Desktop" / path
            path.mkdir(parents=True, exist_ok=False)
            return f"已新建文件夹：{path}"
        if not is_windows():
            raise RuntimeError("这个系统操作仅支持 Windows")
        if action == "media":
            key = {"next": 0xB0, "previous": 0xB1, "play_pause": 0xB3}[data["key"]]
            ctypes.windll.user32.keybd_event(key, 0, 0, 0)
            ctypes.windll.user32.keybd_event(key, 0, 2, 0)
            return "已发送媒体控制指令。"
        if action == "recycle":
            from ctypes import wintypes

            empty = ctypes.windll.shell32.SHEmptyRecycleBinW
            empty.argtypes = [wintypes.HWND, wintypes.LPCWSTR, wintypes.DWORD]
            empty.restype = ctypes.c_long
            result = empty(None, None, 0x1 | 0x2 | 0x4)
            if result:
                raise RuntimeError(f"回收站清理失败（{result}）")
            return "已清空回收站。"
        if action in ("shutdown", "cancel_shutdown"):
            args = (
                ["shutdown.exe", "/a"]
                if action == "cancel_shutdown"
                else [
                    "shutdown.exe",
                    "/r" if data["restart"] else "/s",
                    "/t",
                    str(max(60, min(data["seconds"], 86400))),
                ]
            )
            subprocess.run(args, check=True, capture_output=True, creationflags=0x08000000)
            return (
                "已取消定时关机。"
                if action == "cancel_shutdown"
                else "已安排关机/重启，可发送“取消关机”撤销。"
            )
        if action == "close_app":
            # 只关闭已经配置/识别的软件，向窗口发送正常关闭消息，不强杀进程。
            entry = self.apps._lookup(data["name"])
            if not entry or entry.get("category") != "apps":
                raise ValueError("请先在快捷入口中配置这个软件")
            import psutil

            target = Path(
                os.path.expandvars(entry.get("path") or entry.get("command", ""))
            ).name.lower()
            if (
                target in {"explorer.exe", "cmd.exe", "powershell.exe", "python.exe", "yuanbao.exe"}
                or not target
            ):
                raise ValueError("不能通过助手关闭系统核心进程")
            pids = {
                p.pid
                for p in psutil.process_iter(["name"])
                if (p.info["name"] or "").lower() == target
            }
            from ctypes import wintypes

            from app.windows import user32_api

            user32 = user32_api()
            sent = []
            callback_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
            user32.EnumWindows.argtypes = [callback_type, wintypes.LPARAM]

            def visit(hwnd, _):
                pid = ctypes.c_ulong()
                user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
                if pid.value in pids and user32.IsWindowVisible(hwnd):
                    user32.PostMessageW(hwnd, 0x0010, 0, 0)
                    sent.append(hwnd)
                return True

            user32.EnumWindows(callback_type(visit), 0)
            return (
                "已请求软件正常关闭；如有未保存内容，请在软件中处理。"
                if sent
                else "没有找到这个软件的可见窗口。"
            )
        raise ValueError("未知系统操作")
