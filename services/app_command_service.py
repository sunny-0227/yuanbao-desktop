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

import os
import json
import subprocess
import webbrowser
from typing import Optional

from app.config import AppConfig
from app.app_context import data_path
from app.logger import setup_logger
from app.utils import is_windows

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


def _launch_exe(command: str, display_name: str,
                arguments: str = "", working_dir: str = "") -> str:
    """
    启动一个应用程序。
    - arguments 不为空时通过 subprocess.Popen 传递。
    - working_dir 不为空时设置 cwd。
    策略：先尝试 os.startfile（无参数时），失败则回退到 subprocess.Popen。
    """
    cmd_expanded   = _expand(command)
    work_expanded  = _expand(working_dir) if working_dir else None

    # 路径存在性检查（系统命令如 calc.exe 跳过）
    is_system_cmd = not os.sep in command and not (":" in command)
    if not is_system_cmd and not os.path.exists(cmd_expanded):
        logger.warning(f"程序文件不存在：{cmd_expanded}")
        return (
            f"⚠️ 找不到「{display_name}」的程序文件，"
            f"路径可能已变更：{cmd_expanded}\n"
            "你可以在设置中更新路径，或点击重新识别常用入口。"
        )

    # 有参数时必须用 Popen
    if arguments:
        try:
            args = [cmd_expanded] + arguments.split()
            kw: dict = {"shell": False}
            if work_expanded and os.path.isdir(work_expanded):
                kw["cwd"] = work_expanded
            subprocess.Popen(args, **kw)
            return f"{display_name} 已打开。"
        except Exception as e:
            logger.error(f"Popen 启动失败（{cmd_expanded}）：{e}")
            return f"⚠️ 打开「{display_name}」失败：{e}"

    # 无参数：优先 os.startfile
    try:
        _startfile(cmd_expanded)
        return f"{display_name} 已打开。"
    except Exception as e1:
        logger.debug(f"startfile 失败，尝试 Popen：{e1}")

    try:
        kw = {"shell": False}
        if work_expanded and os.path.isdir(work_expanded):
            kw["cwd"] = work_expanded
        subprocess.Popen([cmd_expanded], **kw)
        return f"{display_name} 已打开。"
    except FileNotFoundError:
        logger.warning(f"找不到可执行文件：{cmd_expanded}")
        return (
            f"⚠️ 找不到「{display_name}」，"
            "请在设置中手动添加，或点击重新识别常用入口。"
        )
    except Exception as e2:
        logger.error(f"启动 {display_name} 失败：{e2}")
        return f"⚠️ 打开「{display_name}」失败：{e2}"


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


def _save_custom_entries(data: dict) -> None:
    """保存 data/user_custom_entries.json"""
    path = data_path(_CUSTOM_FILE)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


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
        discovery=None,   # AppDiscoveryService 可选注入，避免循环导入
    ):
        self._config    = config
        self._discovery = discovery

        # config 快速查找表（不区分大小写）
        self._cfg_app_map:    dict[str, dict] = {}
        self._cfg_folder_map: dict[str, dict] = {}
        self._rebuild_config_maps()

    def _rebuild_config_maps(self):
        """从 config 构建快速查找表"""
        self._cfg_app_map    = {}
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
                if key == entry_key.lower() or key in aliases:
                    return {"category": category, **entry}

        # ── 2. config.json quick_apps ─────────────────────────
        for map_key, item in self._cfg_app_map.items():
            if key == map_key or key in map_key or map_key in key:
                return {
                    "category":     "apps",
                    "display_name": item.get("name", name),
                    "path":         item.get("command", ""),
                    "arguments":    item.get("arguments", ""),
                    "working_dir":  item.get("working_dir", ""),
                    "source":       "config",
                }

        # config.json quick_folders
        for map_key, item in self._cfg_folder_map.items():
            if key == map_key or key in map_key or map_key in key:
                return {
                    "category":     "folders",
                    "display_name": item.get("name", name),
                    "path":         item.get("path", ""),
                    "source":       "config",
                }

        # ── 3. app_index.json ─────────────────────────────────
        if self._discovery:
            try:
                entry = self._discovery.get_entry_by_name(name)
                if entry:
                    return entry
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

        entry = self._lookup(name)

        if not entry:
            return (
                f"我还没有找到「{name}」的位置。\n"
                "你可以：\n"
                "• 在设置中手动添加\n"
                "• 点击「重新识别常用入口」让我重新扫描你的桌面快捷方式"
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
            cmd     = entry.get("command", "")
            display = entry.get("display_name", name)
            return _launch_exe(cmd, display)

        # apps
        path      = entry.get("path", "")
        display   = entry.get("display_name", name)
        arguments = entry.get("arguments", "")
        working   = entry.get("working_dir", "")
        return _launch_exe(path, display, arguments, working)

    def open_app(self, app_name: str) -> str:
        """按名称打开应用（向后兼容接口）"""
        return self.open_entry(app_name)

    def open_folder(self, folder_name: str) -> str:
        """按名称打开文件夹（向后兼容接口）"""
        if not is_windows():
            return _NOT_WIN_MSG

        entry = self._lookup(folder_name)
        if entry and entry.get("category") == "folders":
            return _open_folder_path(
                entry.get("path", ""),
                entry.get("display_name", folder_name)
            )
        if entry and entry.get("category") == "apps":
            # 用户说"打开下载"，可能在 app_index 里被识别成 app，再试文件夹查找
            pass

        # 如果 _lookup 没有命中文件夹，直接回退 open_entry
        return self.open_entry(folder_name)

    def open_browser(self, url: str = "") -> str:
        """打开系统默认浏览器，可选传入目标 URL"""
        try:
            target = url.strip() if url else ""
            webbrowser.open(target if target else "about:blank")
            return f"已在浏览器中打开：{target}" if target else "浏览器已打开。"
        except Exception as e:
            logger.error(f"打开浏览器失败：{e}")
            return f"⚠️ 打开浏览器失败：{e}"

    # ── 用户自定义条目管理 ────────────────────────────────────

    def add_custom_app(self, display_name: str, path: str) -> str:
        """手动添加软件到 user_custom_entries.json"""
        try:
            data = _load_custom_entries()
            data["apps"][display_name] = {
                "display_name": display_name,
                "path":         path,
                "arguments":    "",
                "working_dir":  "",
                "source":       "user_custom",
                "aliases":      [display_name],
                "confidence":   1.0,
            }
            _save_custom_entries(data)
            return f"已添加软件「{display_name}」，路径：{path}"
        except Exception as e:
            logger.error(f"添加自定义软件失败：{e}")
            return f"⚠️ 添加失败：{e}"

    def add_custom_folder(self, display_name: str, path: str) -> str:
        """手动添加文件夹到 user_custom_entries.json"""
        try:
            data = _load_custom_entries()
            data["folders"][display_name] = {
                "display_name": display_name,
                "path":         path,
                "source":       "user_custom",
                "aliases":      [display_name],
                "confidence":   1.0,
            }
            _save_custom_entries(data)
            return f"已添加文件夹「{display_name}」，路径：{path}"
        except Exception as e:
            logger.error(f"添加自定义文件夹失败：{e}")
            return f"⚠️ 添加失败：{e}"

    # ── 兼容旧方法 ────────────────────────────────────────────

    def open_notepad(self) -> str:
        return self.open_entry("记事本")

    def open_calculator(self) -> str:
        return self.open_entry("计算器")

    def open_wechat(self) -> str:
        return self.open_entry("微信")

    def open_word(self) -> str:
        return self.open_entry("Word")

    def open_excel(self) -> str:
        return self.open_entry("Excel")
