"""
应用启动 & 文件夹打开服务
从 config.json 读取 quick_apps 和 quick_folders，按名称查找并执行。

设计原则：
- 只在 Windows 下执行真实命令，非 Windows 返回提示，不崩溃。
- 路径支持 Windows 环境变量（%USERPROFILE% 等），启动前展开。
- command 为空时返回"请在 config.json 中配置"提示。
- command 非空时先尝试 os.startfile，失败再尝试 subprocess.Popen。
- 所有异常全部被捕获，返回友好字符串，不向上抛出。
- 保留 open_notepad / open_calculator / open_browser 兼容方法。
"""

import os
import subprocess
import webbrowser
from typing import Optional

from app.config import AppConfig
from app.logger import setup_logger
from app.utils import is_windows

logger = setup_logger()

_NOT_WIN_MSG = "该功能需要在 Windows 环境下运行。"


# ── 私有辅助函数 ──────────────────────────────────────────────

def _startfile(target: str) -> None:
    """
    调用 os.startfile（仅 Windows 有此函数）。
    封装后可在 Mac/Linux 导入本模块时不报 AttributeError。
    """
    if hasattr(os, "startfile"):
        os.startfile(target)  # type: ignore[attr-defined]
    else:
        raise RuntimeError("os.startfile 仅在 Windows 上可用")


def _expand(path: str) -> str:
    """
    展开 Windows 环境变量并规范化路径。
    例如：%USERPROFILE%\\Downloads → C:\\Users\\username\\Downloads
    非 Windows 上也能安全调用（os.path.expandvars 跨平台）。
    """
    return os.path.normpath(os.path.expandvars(path))


def _launch(command: str, display_name: str) -> str:
    """
    启动一个应用程序或打开一个文件/目录。
    策略：先尝试 os.startfile，失败则回退到 subprocess.Popen。
    返回展示给用户的结果字符串。
    """
    try:
        _startfile(command)
        logger.debug(f"startfile 启动成功：{command}")
        return f"{display_name} 已打开。"
    except Exception as e1:
        logger.debug(f"startfile 失败，尝试 Popen：{e1}")

    try:
        subprocess.Popen([command], shell=False)
        logger.debug(f"Popen 启动成功：{command}")
        return f"{display_name} 已打开。"
    except FileNotFoundError:
        logger.warning(f"找不到可执行文件：{command}")
        return f"⚠️ 找不到 {display_name} 的程序文件，请检查 config.json 中的路径。"
    except Exception as e2:
        logger.error(f"启动 {display_name} 失败：{e2}")
        return f"⚠️ 打开 {display_name} 失败：{e2}"


# ── 服务类 ────────────────────────────────────────────────────

class AppCommandService:
    """
    应用启动 & 文件夹打开服务。

    实例化时传入 AppConfig，从中读取 quick_apps / quick_folders。
    config 为 None 时退化为无配置模式（只支持内置的系统命令）。

    所有 public 方法返回字符串，供聊天窗口直接展示。
    """

    def __init__(self, config: Optional[AppConfig] = None):
        self._config = config
        # 构建名称 → 配置项的查找字典（不区分大小写）
        self._app_map: dict[str, dict]    = {}
        self._folder_map: dict[str, dict] = {}
        self._build_maps()

    def _build_maps(self):
        """从 config 构建快速查找表"""
        if not self._config:
            return

        for item in self._config.quick_apps:
            name = item.get("name", "").strip().lower()
            if name:
                self._app_map[name] = item

        for item in self._config.quick_folders:
            name = item.get("name", "").strip().lower()
            if name:
                self._folder_map[name] = item

        logger.debug(
            f"AppCommandService 初始化：{len(self._app_map)} 个快捷应用，"
            f"{len(self._folder_map)} 个快捷文件夹"
        )

    # ── 通用接口 ──────────────────────────────────────────────

    def open_app(self, app_name: str) -> str:
        """
        按名称打开快捷应用。
        先在 quick_apps 中查找，命中后展开路径并启动；
        找不到时返回"请在 config.json 中配置"提示。
        """
        if not is_windows():
            return _NOT_WIN_MSG

        key = app_name.strip().lower()
        item = self._app_map.get(key)

        if not item:
            logger.debug(f"quick_apps 中未找到：{app_name!r}")
            return (
                f"暂未找到「{app_name}」的配置，"
                "请在 config.json 的 quick_apps 中添加。"
            )

        command = _expand(item.get("command", "").strip())
        display = item.get("name", app_name)

        if not command:
            return (
                f"暂未配置「{display}」的启动路径，"
                "请在 config.json 的 quick_apps 中设置 command 字段。"
            )

        return _launch(command, display)

    def open_folder(self, folder_name: str) -> str:
        """
        按名称打开快捷文件夹。
        支持别名匹配：用户输入的名称在 _folder_map 中的任意 name 包含即命中。
        路径支持 Windows 环境变量（%USERPROFILE% 等）。
        截图目录不存在时自动创建；其他目录不存在时给出友好提示。
        """
        if not is_windows():
            return _NOT_WIN_MSG

        key  = folder_name.strip().lower()
        item = self._folder_map.get(key)

        # 若精确匹配失败，尝试包含匹配（支持别名）
        if not item:
            for map_key, map_item in self._folder_map.items():
                if key in map_key or map_key in key:
                    item = map_item
                    break

        if not item:
            logger.debug(f"quick_folders 中未找到：{folder_name!r}")
            return (
                f"暂未找到「{folder_name}」的配置，"
                "请在 config.json 的 quick_folders 中添加。"
            )

        raw_path = item.get("path", "").strip()
        display  = item.get("name", folder_name)

        if not raw_path:
            return (
                f"暂未配置「{display}」的文件夹路径，"
                "请在 config.json 的 quick_folders 中设置 path 字段。"
            )

        path = _expand(raw_path)

        if not os.path.exists(path):
            # 截图目录：不存在时自动创建
            if "screenshot" in raw_path.lower() or "截图" in display:
                try:
                    os.makedirs(path, exist_ok=True)
                    logger.info(f"截图目录已自动创建：{path}")
                except Exception as e:
                    logger.error(f"截图目录创建失败：{e}")
                    return f"⚠️ 截图目录创建失败：{e}"
            else:
                logger.warning(f"文件夹不存在：{path}")
                return (
                    f"⚠️ 找不到文件夹「{display}」：{path}\n"
                    "请检查 config.json 中的路径是否正确。"
                )

        try:
            _startfile(path)
            logger.debug(f"已打开文件夹：{path}")
            return f"已打开「{display}」文件夹。"
        except Exception as e:
            logger.error(f"打开文件夹失败：{path}  {e}")
            return f"⚠️ 打开文件夹失败：{e}"

    # ── 浏览器（特殊：可带 URL）─────────────────────────────

    def open_browser(self, url: str = "") -> str:
        """
        打开系统默认浏览器，可选传入目标 URL。
        使用 webbrowser 模块，跨平台支持 Windows / macOS / Linux。
        """
        try:
            target = url.strip() if url else ""
            webbrowser.open(target)
            logger.debug(f"已打开浏览器，url={target!r}")
            return f"已在浏览器中打开：{target}" if target else "浏览器已打开。"
        except Exception as e:
            logger.error(f"打开浏览器失败：{e}")
            return f"⚠️ 打开浏览器失败：{e}"

    # ── 兼容方法（内部委托给 open_app）──────────────────────

    def open_notepad(self) -> str:
        """兼容旧调用，等价于 open_app('记事本')"""
        result = self.open_app("记事本")
        # 如果 config 未配置，直接用系统命令兜底
        if "config.json" in result and is_windows():
            return _launch("notepad.exe", "记事本")
        return result

    def open_calculator(self) -> str:
        """兼容旧调用，等价于 open_app('计算器')"""
        result = self.open_app("计算器")
        if "config.json" in result and is_windows():
            return _launch("calc.exe", "计算器")
        return result

    def open_wechat(self) -> str:
        """快捷方法：打开微信"""
        return self.open_app("微信")

    def open_word(self) -> str:
        """快捷方法：打开 Word"""
        return self.open_app("Word")

    def open_excel(self) -> str:
        """快捷方法：打开 Excel"""
        return self.open_app("Excel")
