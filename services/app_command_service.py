"""
应用启动 & 文件夹打开服务

打开优先级（从高到低）：
    1. user_custom_entries.json  用户手动添加（最高优先）
    2. config.json quick_apps / quick_folders  用户预配置
    3. data/app_index.json  自动扫描识别结果
    4. system_tools  内置系统工具（计算器、记事本等）
    5. 找不到 → 返回友好提示

设计原则：
- 只在 Windows 下执行真实命令，非 Windows 返回提示，不崩溃。
- 路径支持 Windows 环境变量（%USERPROFILE% 等），启动前展开。
- 所有异常全部被捕获，返回友好字符串，不向上抛出。
- AppDiscoveryService 以可选依赖方式注入（非必须）。
"""

import json
import os
import webbrowser
from typing import Optional

from app.app_context import data_path
from app.config import AppConfig
from app.logger import setup_logger
from app.utils import is_windows
from services.app_discovery_service import _name_key
from services.app_launch_service import LaunchOutcome, launch_application, observe_launch

logger = setup_logger()

_NOT_WIN_MSG = "该功能需要在 Windows 环境下运行。"
_CUSTOM_FILE = "user_custom_entries.json"


# ── 私有辅助函数 ──────────────────────────────────────────────


def _startfile(target: str) -> None:
    """调用 os.startfile（仅 Windows 有此函数）"""
    if hasattr(os, "startfile"):
        os.startfile(target)  # type: ignore[attr-defined]
    else:
        raise RuntimeError("os.startfile 仅在 Windows 上可用")


def _expand(path: str) -> str:
    """展开 Windows 环境变量并规范化路径"""
    return os.path.normpath(os.path.expandvars(path))


def _entry_available(entry):
    category = entry.get("category", "apps")
    if category in ("websites", "system_tools"):
        return True
    path = entry.get("path", "")
    if not path:
        return False
    expanded = _expand(path)
    if os.path.exists(expanded):
        return True
    # 仅允许PATH里实际存在的程序名，不能把失效路径当成系统命令。
    import shutil

    return (
        category == "apps"
        and not any(c in path for c in ("/", "\\", ":"))
        and bool(shutil.which(path))
    )


def _launch_exe(command, display_name, arguments="", working_dir=""):
    return launch_application(command, display_name, arguments, working_dir)


def _open_folder_path(path: str, display_name: str) -> str:
    """打开文件夹路径"""
    path_expanded = _expand(path)

    if not os.path.exists(path_expanded):
        # 截图目录自动创建
        if "screenshot" in path.lower() or "截图" in display_name:
            try:
                os.makedirs(path_expanded, exist_ok=True)
                logger.info(f"截图目录已自动创建：{path_expanded}")
            except Exception as e:
                return f"⚠️ 截图目录创建失败：{e}"
        else:
            return (
                f"⚠️ 文件夹「{display_name}」不存在：{path_expanded}\n"
                "请检查路径是否正确，或在设置中更新。"
            )

    try:
        _startfile(path_expanded)
        return f"已打开「{display_name}」文件夹。"
    except Exception as e:
        logger.error(f"打开文件夹失败：{path_expanded}  {e}")
        return f"⚠️ 打开文件夹失败：{e}"


# ── 用户自定义条目读取 ────────────────────────────────────────


def _load_custom_entries() -> dict:
    """读取 data/user_custom_entries.json"""
    path = data_path(_CUSTOM_FILE)
    if not os.path.exists(path):
        return {"apps": {}, "folders": {}, "websites": {}}
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        for key in ("apps", "folders", "websites"):
            data.setdefault(key, {})
        return data
    except Exception as e:
        logger.warning(f"读取 user_custom_entries.json 失败：{e}")
        return {"apps": {}, "folders": {}, "websites": {}}


# ── 服务类 ────────────────────────────────────────────────────


class AppCommandService:
    """
    应用启动 & 文件夹 & 网页打开服务。

    注入方式：
        svc = AppCommandService(config=app_config, discovery=discovery_service)

    所有 public 方法返回字符串，供聊天窗口直接展示。
    """

    def __init__(
        self,
        config: Optional[AppConfig] = None,
        discovery=None,  # AppDiscoveryService 可选注入，避免循环导入
    ):
        self._config = config
        self._discovery = discovery
        self.last_launch = None

        # config 快速查找表（不区分大小写）
        self._cfg_app_map: dict[str, dict] = {}
        self._cfg_folder_map: dict[str, dict] = {}
        self._rebuild_config_maps()

    def _rebuild_config_maps(self):
        """从 config 构建快速查找表"""
        self._cfg_app_map = {}
        self._cfg_folder_map = {}
        if not self._config:
            return
        for item in self._config.quick_apps:
            name = item.get("name", "").strip().lower()
            if name:
                self._cfg_app_map[name] = item
        for item in self._config.quick_folders:
            name = item.get("name", "").strip().lower()
            if name:
                self._cfg_folder_map[name] = item
        logger.debug(
            f"AppCommandService config 表：{len(self._cfg_app_map)} apps，"
            f"{len(self._cfg_folder_map)} folders"
        )

    # ── 统一查找入口 ──────────────────────────────────────────

    def _lookup(self, name: str) -> Optional[dict]:
        """
        按优先级查找入口：
        1. user_custom  2. config  3. app_index  4. system_tools
        返回 {"category", "display_name", "path"/"url"/"command", ...} 或 None
        """
        key = name.strip().lower()

        # ── 1. 用户自定义 ────────────────────────────────────
        custom = _load_custom_entries()
        for category in ("apps", "folders", "websites"):
            for entry_key, entry in custom[category].items():
                aliases = [a.lower() for a in entry.get("aliases", [entry_key])]
                if _name_key(key) == _name_key(entry_key) or _name_key(key) in map(
                    _name_key, aliases
                ):
                    candidate = {"category": category, **entry}
                    if _entry_available(candidate):
                        return candidate

        # ── 2. config.json quick_apps ─────────────────────────
        for map_key, item in self._cfg_app_map.items():
            if _name_key(key) == _name_key(map_key):
                candidate = {
                    "category": "apps",
                    "display_name": item.get("name", name),
                    "path": item.get("command", ""),
                    "arguments": item.get("arguments", ""),
                    "working_dir": item.get("working_dir", ""),
                    "source": "config",
                }
                if _entry_available(candidate):
                    return candidate

        # config.json quick_folders
        for map_key, item in self._cfg_folder_map.items():
            if key == map_key:
                candidate = {
                    "category": "folders",
                    "display_name": item.get("name", name),
                    "path": item.get("path", ""),
                    "source": "config",
                }
                if _entry_available(candidate):
                    return candidate

        # ── 3. app_index.json ─────────────────────────────────
        if self._discovery:
            try:
                entry = self._discovery.resolve_entry(name)
                if entry:
                    return entry
            except ValueError:
                raise
            except Exception as e:
                logger.debug(f"app_index 查找异常：{e}")

        return None

    # ── 统一打开入口 ──────────────────────────────────────────

    def open_entry(self, name: str) -> str:
        """
        根据名称查找并打开对应入口（应用 / 文件夹 / 网页 / 系统工具）。
        这是最推荐的统一调用接口。
        """
        if not is_windows():
            return _NOT_WIN_MSG

        if name.strip() in ("浏览器", "默认浏览器"):
            return self.open_browser()
        try:
            entry = self._lookup(name)
        except ValueError as exc:
            return str(exc)

        if not entry:
            return (
                f"已自动查找桌面、开始菜单、应用注册信息和正在运行的软件，仍未找到「{name}」。\n"
                "可以试试桌面图标的完整名称。便携软件如果没有快捷方式或注册记录，"
                "可先把快捷方式放到桌面，再直接说“打开软件名”。"
            )

        category = entry.get("category", "apps")

        if category == "websites":
            url = entry.get("url", "")
            return self.open_browser(url)

        if category == "folders":
            path = entry.get("path", "")
            display = entry.get("display_name", name)
            return _open_folder_path(path, display)

        if category == "system_tools":
            cmd = entry.get("command", "")
            display = entry.get("display_name", name)
            return self._launch(cmd, display)

        # apps
        path = entry.get("path", "")
        display = entry.get("display_name", name)
        arguments = entry.get("arguments", "")
        working = entry.get("working_dir", "")
        return self._launch(path, display, arguments, working)

    def _launch(self, path, name, arguments="", working=""):
        result = _launch_exe(path, name, arguments, working)
        if isinstance(result, LaunchOutcome):
            self.last_launch = result
        return str(result)

    def open_path(self, path):
        if not is_windows():
            return _NOT_WIN_MSG
        target = _expand(path)
        if os.path.isdir(target):
            try:
                _startfile(target)
                self.last_launch = LaunchOutcome(os.path.basename(target), target, "requested")
                return "已向Windows发送打开文件夹的请求：\n" + target
            except OSError as exc:
                self.last_launch = LaunchOutcome(target, target, "failed", str(exc))
                return str(self.last_launch)
        return self._launch(target, os.path.basename(target))

    def check_last_launch(self):
        if self.last_launch is None:
            return "当前对话还没有实际启动软件的记录。可以告诉我软件名或完整路径。"
        if self.last_launch.status != "failed":
            self.last_launch = observe_launch(self.last_launch.name, self.last_launch.target)
        return str(self.last_launch)

    def find_entry_path(self, name):
        """本地查询实际位置，不启动程序，也不调用AI。"""
        if not is_windows():
            return _NOT_WIN_MSG
        try:
            entry = self._lookup(name)
        except ValueError as exc:
            return str(exc)
        if not entry:
            return f"自动查找后仍未找到「{name}」。请确认桌面图标名称；无需逐个配置安装路径。"
        path = entry.get("path") or entry.get("url") or entry.get("command")
        return f"找到了「{entry.get('display_name', name)}」：\n{_expand(path) if entry.get('path') else path}"

    def open_browser(self, url: str = "") -> str:
        """打开系统默认浏览器，可选传入目标 URL"""
        try:
            target = url.strip() if url else ""
            if not webbrowser.open(target if target else "about:blank"):
                return "⚠️ 系统没有接受浏览器启动请求，请检查默认浏览器设置。"
            return f"已向默认浏览器发送打开请求：{target or '新标签页'}，尚未核实窗口状态。"
        except Exception as e:
            logger.error(f"打开浏览器失败：{e}")
            return f"⚠️ 打开浏览器失败：{e}"
