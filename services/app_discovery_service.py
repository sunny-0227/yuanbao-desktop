"""
常用入口自动识别服务
扫描 Windows 系统中的桌面快捷方式、公共桌面、开始菜单等位置，
自动识别用户常用软件、文件夹和网页入口，生成 data/app_index.json。

设计原则：
- 不做全盘扫描，只扫描快捷方式来源目录。
- 不预设固定软件列表，从快捷方式名称自动生成 display_name 和 aliases。
- win32com.client 不可用时优雅降级，只记录日志。
- 非 Windows 环境返回空索引，不崩溃。
- 所有路径都使用 os.path.expandvars 展开环境变量。
- 路径读取失败、权限不足、快捷方式损坏时跳过并记录日志。
"""

import json
import ntpath
import os
import platform
import re
import shutil
import time
from datetime import datetime
from typing import Optional

from app.app_context import data_path
from app.logger import setup_logger

logger = setup_logger()

# ── 常量 ─────────────────────────────────────────────────────

_INDEX_FILE = "app_index.json"

# 扫描来源目录（按优先级排列）
_SCAN_SOURCES = [
    ("desktop_shortcut", "%USERPROFILE%\\Desktop"),
    ("public_desktop", "C:\\Users\\Public\\Desktop"),
    ("start_menu", "%APPDATA%\\Microsoft\\Windows\\Start Menu\\Programs"),
    ("public_start_menu", "C:\\ProgramData\\Microsoft\\Windows\\Start Menu\\Programs"),
    (
        "taskbar_pinned",
        "%APPDATA%\\Microsoft\\Internet Explorer\\Quick Launch\\User Pinned\\TaskBar",
    ),
]

# 无意义后缀 / 词语（用于清理快捷方式名称）
_NOISE_PATTERNS = [
    r"\s*-\s*快捷方式$",
    r"\s*快捷方式$",
    r"\s*-\s*Shortcut$",
    r"\s*Shortcut$",
]

# 通用别名映射表（仅少量常见缩写，不限制软件范围）
_ALIAS_MAP: dict[str, list[str]] = {
    "visual studio code": ["VS Code", "Code", "VSCode"],
    "vs code": ["Visual Studio Code", "Code", "VSCode"],
    "microsoft edge": ["Edge", "Edge浏览器"],
    "google chrome": ["Chrome", "谷歌浏览器"],
    "mozilla firefox": ["Firefox", "火狐浏览器"],
    "wps office": ["WPS"],
    "剪映专业版": ["剪映"],
    "adobe photoshop": ["PS", "Photoshop"],
    "adobe premiere": ["PR", "Premiere"],
    "adobe after effects": ["AE", "After Effects"],
    "tencent meeting": ["腾讯会议"],
    "netease cloudmusic": ["网易云音乐"],
    "wechat": ["微信"],
    "weixin": ["微信", "WeChat"],
    "微信": ["WeChat", "Weixin"],
    "dingtalk": ["钉钉"],
}

# 内置系统工具
_SYSTEM_TOOLS: dict[str, dict] = {
    "计算器": {
        "display_name": "计算器",
        "command": "calc",
        "source": "system_builtin",
        "aliases": ["计算器", "calc", "计算"],
        "confidence": 1.0,
    },
    "记事本": {
        "display_name": "记事本",
        "command": "notepad",
        "source": "system_builtin",
        "aliases": ["记事本", "notepad"],
        "confidence": 1.0,
    },
    "画图": {
        "display_name": "画图",
        "command": "mspaint",
        "source": "system_builtin",
        "aliases": ["画图", "mspaint", "Paint"],
        "confidence": 1.0,
    },
    "文件资源管理器": {
        "display_name": "文件资源管理器",
        "command": "explorer",
        "source": "system_builtin",
        "aliases": ["文件资源管理器", "explorer", "资源管理器", "文件管理器"],
        "confidence": 1.0,
    },
    "命令提示符": {
        "display_name": "命令提示符",
        "command": "cmd",
        "source": "system_builtin",
        "aliases": ["命令提示符", "cmd", "命令行"],
        "confidence": 1.0,
    },
    "PowerShell": {
        "display_name": "PowerShell",
        "command": "powershell",
        "source": "system_builtin",
        "aliases": ["PowerShell", "powershell", "PS"],
        "confidence": 1.0,
    },
}


# 空索引结构模板
def _empty_index() -> dict:
    return {"apps": {}, "folders": {}, "websites": {}, "system_tools": {}}


# ── 工具函数 ─────────────────────────────────────────────────


def _now_str() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _expand(path: str) -> str:
    """展开环境变量并规范化路径"""
    return os.path.normpath(os.path.expandvars(path))


def _clean_name(raw: str) -> str:
    """
    清理快捷方式名称：
    - 去掉 .lnk / .url 后缀
    - 去掉"快捷方式""Shortcut"等无意义词
    - 去掉首尾空格
    """
    name = raw
    # 去掉扩展名
    name = re.sub(r"\.(lnk|url)$", "", name, flags=re.IGNORECASE)
    # 去掉无意义词
    for pattern in _NOISE_PATTERNS:
        name = re.sub(pattern, "", name, flags=re.IGNORECASE)
    return name.strip()


def _build_aliases(display_name: str) -> list[str]:
    """
    根据 display_name 生成别名列表。
    规则：
    1. 始终包含 display_name 本身。
    2. 查找 _ALIAS_MAP 补充通用别名。
    3. 去重，保持顺序。
    """
    short_name = re.sub(r"\s+v?\d+(?:\.\d+)*.*$", "", display_name, flags=re.I).strip()
    aliases = list(dict.fromkeys([display_name, short_name]))
    key = short_name.lower()
    for map_key, extra in _ALIAS_MAP.items():
        if (
            key == map_key
            or key in (a.casefold() for a in extra)
            or key.startswith((map_key + " ", map_key + "(", map_key + "（"))
        ):
            for a in [map_key, *extra]:
                if a not in aliases:
                    aliases.append(a)
    return aliases


def _name_key(name):
    return re.sub(r"[\s._-]+", "", name).casefold()


def _is_app_file(path):
    return bool(path) and os.path.isfile(_expand(path))


def _safe_executable(value):
    """从App Paths/DisplayIcon提取文件，不执行注册表中的命令行。"""
    match = re.match(r'^\s*"([^"\r\n]+\.(?:exe|com))"', value or "", re.I)
    if not match:
        match = re.match(r"^\s*(.+?\.(?:exe|com))(?=\s|,|$)", value or "", re.I)
    path = _expand(match[1]) if match else ""
    if re.search(r"unins|uninstall|updater|setup", ntpath.basename(path), re.I):
        return ""
    return path if _is_app_file(path) else ""


def _registry_subkeys(winreg, root, branch, access):
    try:
        with winreg.OpenKey(root, branch, 0, access) as parent:
            for i in range(min(winreg.QueryInfoKey(parent)[0], 10000)):
                try:
                    yield winreg.EnumKey(parent, i)
                except OSError:
                    continue
    except OSError:
        return


def _registry_value(winreg, key, name):
    try:
        value = winreg.QueryValueEx(key, name)[0]
        return value if isinstance(value, str) else ""
    except OSError:
        return ""


def _scan_sources():
    """补充系统登记的桌面/开始菜单位置，兼容OneDrive和移动后的桌面。"""
    sources = list(_SCAN_SOURCES)
    for env in ("OneDrive", "OneDriveConsumer", "OneDriveCommercial"):
        if os.environ.get(env):
            sources.append(("desktop_shortcut", os.path.join(os.environ[env], "Desktop")))
    try:
        import winreg

        branch = r"Software\Microsoft\Windows\CurrentVersion\Explorer\User Shell Folders"
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, branch) as key:
            for value, source in (("Desktop", "desktop_shortcut"), ("Programs", "start_menu")):
                path = _registry_value(winreg, key, value)
                if path:
                    sources.append((source, path))
    except (ImportError, OSError):
        pass
    unique = {}
    for source, path in sources:
        unique.setdefault(os.path.normcase(_expand(path)), (source, path))
    return list(unique.values())


# ── 快捷方式解析 ─────────────────────────────────────────────


def _parse_lnk(lnk_path: str, source: str) -> Optional[dict]:
    """
    使用 win32com.client 解析 .lnk 文件。
    返回 {"display_name", "path", "arguments", "working_dir",
           "icon_location", "source", "entry_type"}
    或 None（解析失败时）。
    """
    try:
        import win32com.client  # type: ignore
    except ImportError:
        logger.debug("win32com.client 不可用，跳过 .lnk 解析（仅 Windows + pywin32）")
        return None

    try:
        shell = win32com.client.Dispatch("WScript.Shell")
        shortcut = shell.CreateShortcut(lnk_path)

        target = (shortcut.TargetPath or "").strip()
        args = (shortcut.Arguments or "").strip()
        work = (shortcut.WorkingDirectory or "").strip()
        icon = (shortcut.IconLocation or "").strip()

        display_name = _clean_name(os.path.basename(lnk_path))

        if not target or target.lower().startswith(("shell:", "::{")):
            # Store/打包应用的快捷方式交给Windows Shell解析，不能当成exe路径。
            return {
                "display_name": _clean_name(os.path.basename(lnk_path)),
                "path": lnk_path,
                "source": source,
                "entry_type": "app",
            }

        # 展开环境变量
        target_expanded = _expand(target)
        if not os.path.exists(target_expanded):
            return None

        # 判断类型
        if os.path.isdir(target_expanded):
            entry_type = "folder"
        elif target_expanded.lower().endswith(".exe") or os.path.isfile(target_expanded):
            entry_type = "app"
        else:
            # 目标不存在或无法判断（可能是 Store App / URI）
            # 尝试是否可作为应用路径
            entry_type = "app"

        return {
            "display_name": display_name,
            "path": target_expanded,
            "arguments": args,
            "working_dir": _expand(work) if work else "",
            "icon_location": icon,
            "source": source,
            "entry_type": entry_type,
        }
    except Exception as e:
        logger.debug(f"解析 .lnk 失败（{lnk_path}）：{e}")
        return None


def _parse_url_file(url_path: str, source: str) -> Optional[dict]:
    """
    解析 .url 文件，提取 URL 字段。
    .url 是 INI 格式，[InternetShortcut] 下有 URL= 字段。
    """
    try:
        url = None
        with open(url_path, "r", encoding="utf-8", errors="ignore") as f:
            for line in f:
                line = line.strip()
                if line.upper().startswith("URL="):
                    url = line[4:].strip()
                    break

        if not url:
            logger.debug(f"跳过无 URL 字段的 .url 文件：{url_path}")
            return None

        display_name = _clean_name(os.path.basename(url_path))
        return {
            "display_name": display_name,
            "url": url,
            "source": source,
            "entry_type": "website",
        }
    except Exception as e:
        logger.debug(f"解析 .url 失败（{url_path}）：{e}")
        return None


# ── 主服务类 ─────────────────────────────────────────────────


class AppDiscoveryService:
    """
    常用入口自动识别服务。

    职责：
    - 扫描桌面、公共桌面、开始菜单等快捷方式目录
    - 解析 .lnk 和 .url 文件，生成 apps / folders / websites 索引
    - 保存 / 加载 data/app_index.json
    - 提供名称 / 别名查找接口

    非 Windows 环境下所有扫描方法返回空结构，不抛出异常。
    """

    def __init__(self):
        self._index_path = data_path(_INDEX_FILE)

    # ── 公开接口 ──────────────────────────────────────────────

    def scan_shortcuts(self) -> dict:
        """限定来源目录和递归深度，不扫描用户整块磁盘。"""
        result = {"apps": [], "folders": [], "websites": []}
        if platform.system() != "Windows":
            return result
        deadline = time.monotonic() + 10
        visited = 0
        for source, raw_dir in _scan_sources():
            root = _expand(raw_dir)
            for directory, children, files in os.walk(root, followlinks=False):
                if time.monotonic() > deadline or visited >= 5000:
                    return result
                depth = os.path.relpath(directory, root).count(os.sep)
                if directory != root:
                    depth += 1
                if depth >= 4:
                    children[:] = []
                children[:] = [
                    d for d in children if not os.path.islink(os.path.join(directory, d))
                ]
                for filename in files:
                    visited += 1
                    if visited >= 5000 or time.monotonic() > deadline:
                        return result
                    path = os.path.join(directory, filename)
                    try:
                        lower = filename.lower()
                        if lower.endswith(".lnk"):
                            entry = _parse_lnk(path, source)
                            if entry:
                                category = "folders" if entry["entry_type"] == "folder" else "apps"
                                result[category].append(entry)
                        elif lower.endswith(".url"):
                            entry = _parse_url_file(path, source)
                            if entry:
                                result["websites"].append(entry)
                        elif lower.endswith(".exe") and _safe_executable(path):
                            result["apps"].append(
                                {
                                    "display_name": os.path.splitext(filename)[0],
                                    "path": path,
                                    "source": source,
                                }
                            )
                    except Exception as exc:
                        logger.debug("跳过无法读取的入口 %s: %s", path, exc)
        return result

    def scan_registered_apps(self):
        """读取当前用户/系统、32/64位的应用注册信息；支持自定义安装盘。"""
        apps = []
        if platform.system() != "Windows":
            return apps
        try:
            import winreg
        except ImportError:
            return apps
        views = (winreg.KEY_WOW64_64KEY, winreg.KEY_WOW64_32KEY)
        branches = (
            (r"Software\Microsoft\Windows\CurrentVersion\App Paths", "registry_app_path"),
            (r"Software\Microsoft\Windows\CurrentVersion\Uninstall", "registry_install"),
        )
        for root in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
            for view in views:
                access = winreg.KEY_READ | view
                for branch, source in branches:
                    for subkey in _registry_subkeys(winreg, root, branch, access):
                        try:
                            with winreg.OpenKey(root, branch + "\\" + subkey, 0, access) as key:
                                if source == "registry_app_path":
                                    name = ntpath.splitext(subkey)[0]
                                    path = _safe_executable(_registry_value(winreg, key, ""))
                                else:
                                    name = _registry_value(winreg, key, "DisplayName")
                                    if not name:
                                        continue
                                    path = _safe_executable(
                                        _registry_value(winreg, key, "DisplayIcon")
                                    )
                                    if not path:
                                        location = _registry_value(winreg, key, "InstallLocation")
                                        path = self._find_installed_exe(location, name)
                                if name and path:
                                    apps.append(
                                        {"display_name": name, "path": path, "source": source}
                                    )
                        except OSError:
                            continue
        return apps

    @staticmethod
    def _find_installed_exe(location, name):
        if not location or not os.path.isdir(_expand(location)):
            return ""
        aliases = {_name_key(n) for n in _build_aliases(name)}
        matches = []
        visited = 0
        root = _expand(location)
        for directory, children, files in os.walk(root, followlinks=False):
            visited += 1
            if visited > 100:
                break
            if os.path.relpath(directory, root).count(os.sep) >= 2:
                children[:] = []
            children[:] = [d for d in children if not os.path.islink(os.path.join(directory, d))]
            for filename in files:
                if _name_key(os.path.splitext(filename)[0]) in aliases:
                    path = _safe_executable(os.path.join(directory, filename))
                    if path:
                        matches.append(path)
        return sorted(set(matches), key=lambda p: (len(p), p.casefold()))[0] if matches else ""

    def scan_running_apps(self):
        """只读取现有进程的程序位置，不结束或启动进程。"""
        if platform.system() != "Windows":
            return []
        import psutil

        apps = []
        try:
            for proc in psutil.process_iter(["exe"]):
                try:
                    path = _safe_executable(proc.info.get("exe") or "")
                    if path:
                        apps.append(
                            {
                                "display_name": ntpath.splitext(ntpath.basename(path))[0],
                                "path": path,
                                "source": "running_process",
                            }
                        )
                except (psutil.Error, OSError):
                    continue
        except psutil.Error:
            pass
        return apps

    def build_app_index(self) -> dict:
        """
        整合 apps、folders、websites、system_tools，生成完整索引。
        同名条目：后扫描的来源覆盖前者，但 desktop_shortcut 优先级最高。
        """
        raw = self.scan_shortcuts()
        raw["apps"] += self.scan_registered_apps() + self.scan_running_apps()
        index = _empty_index()
        now = _now_str()

        # 优先级：桌面 > 公共桌面 > 开始菜单 > 公共开始菜单 > 任务栏
        priority = {
            "registry_app_path": 4,
            "registry_install": 3,
            "running_process": 0,
            "desktop_shortcut": 5,
            "public_desktop": 4,
            "start_menu": 3,
            "public_start_menu": 2,
            "taskbar_pinned": 1,
        }

        def _better(existing: dict, new_source: str) -> bool:
            """新条目是否比已有条目优先级高（或相同可覆盖）"""
            old_p = priority.get(existing.get("source", ""), 0)
            new_p = priority.get(new_source, 0)
            return new_p >= old_p

        # ── 处理 apps ────────────────────────────────────────
        for entry in raw["apps"]:
            if not _is_app_file(entry.get("path", "")):
                continue
            name = entry["display_name"]
            aliases = _build_aliases(name)
            record = {
                "display_name": name,
                "path": entry["path"],
                "arguments": entry.get("arguments", ""),
                "working_dir": entry.get("working_dir", ""),
                "source": entry["source"],
                "aliases": aliases,
                "confidence": 0.9 if entry["source"] == "desktop_shortcut" else 0.8,
                "last_scanned_at": now,
            }
            # 同名、不同安装位置全部保留，以免默默启动另一个版本。
            existing = index["apps"].get(name)
            if existing:
                if not _better(existing, entry["source"]):
                    candidates = existing.setdefault("candidates", [])
                    candidates.append(record)
                    continue
                record["candidates"] = [
                    {k: v for k, v in existing.items() if k != "candidates"},
                    *existing.get("candidates", []),
                ]
            index["apps"][name] = record

        # ── 处理 folders ─────────────────────────────────────
        for entry in raw["folders"]:
            name = entry["display_name"]
            aliases = _build_aliases(name)
            record = {
                "display_name": name,
                "path": entry["path"],
                "source": entry["source"],
                "aliases": aliases,
                "confidence": 0.9 if entry["source"] == "desktop_shortcut" else 0.8,
                "last_scanned_at": now,
            }
            existing = index["folders"].get(name)
            if not existing or _better(existing, entry["source"]):
                index["folders"][name] = record

        # ── 处理 websites ─────────────────────────────────────
        for entry in raw["websites"]:
            name = entry["display_name"]
            aliases = _build_aliases(name)
            record = {
                "display_name": name,
                "url": entry["url"],
                "source": entry["source"],
                "aliases": aliases,
                "confidence": 0.9 if entry["source"] == "desktop_shortcut" else 0.8,
                "last_scanned_at": now,
            }
            existing = index["websites"].get(name)
            if not existing or _better(existing, entry["source"]):
                index["websites"][name] = record

        # ── 系统工具 ─────────────────────────────────────────
        index = self.ensure_default_system_tools(index)

        return index

    def ensure_default_system_tools(self, index: dict) -> dict:
        """补充 Windows 内置系统工具（不覆盖已有条目）"""
        for name, tool in _SYSTEM_TOOLS.items():
            if name not in index["system_tools"]:
                index["system_tools"][name] = tool
        return index

    def save_app_index(self, index):
        from app.storage import atomic_json

        atomic_json(self._index_path, index)

    def load_app_index(self) -> dict:
        """
        读取 data/app_index.json。
        不存在 → 返回空结构（含系统工具）。
        损坏  → 备份为 .bak，返回空结构。
        """
        if not os.path.exists(self._index_path):
            logger.debug("app_index.json 不存在，返回空结构")
            return self.ensure_default_system_tools(_empty_index())

        try:
            with open(self._index_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            # 确保四个顶层 key 都存在
            for key in ("apps", "folders", "websites", "system_tools"):
                data.setdefault(key, {})
            return data
        except json.JSONDecodeError as e:
            logger.warning(f"app_index.json 解析失败，备份后重置：{e}")
            bak = self._index_path + ".bak"
            try:
                shutil.copy2(self._index_path, bak)
            except Exception:
                pass
            empty = self.ensure_default_system_tools(_empty_index())
            self.save_app_index(empty)
            return empty
        except Exception as e:
            logger.error(f"读取 app_index.json 异常：{e}")
            return self.ensure_default_system_tools(_empty_index())

    def get_entry_by_name(self, name: str) -> Optional[dict]:
        return self._match_entry(name, self.load_app_index())

    def resolve_entry(self, name: str) -> Optional[dict]:
        entry = self.get_entry_by_name(name)
        if entry:
            return entry
        index = self.build_app_index()
        try:
            self.save_app_index(index)
        except OSError as exc:
            # 缓存写入失败不妨碍使用本次已经找到的位置。
            logger.warning("应用索引暂未保存：%s", exc)
        return self._match_entry(name, index)

    @staticmethod
    def _matching_entries(name, index):
        query = _name_key(name)
        if not query:
            return []
        exact, aliases, partial = [], [], []
        for category in ("apps", "folders", "websites", "system_tools"):
            for label, original in index.get(category, {}).items():
                records = [original, *original.get("candidates", [])]
                for entry in records:
                    if category == "apps" and not _is_app_file(entry.get("path", "")):
                        continue
                    if category == "folders" and not os.path.isdir(_expand(entry.get("path", ""))):
                        continue
                    item = {"category": category, **entry}
                    display = entry.get("display_name", label)
                    names = {
                        _name_key(n) for n in _build_aliases(display) + entry.get("aliases", [])
                    }
                    if query == _name_key(display):
                        exact.append(item)
                    elif query in names:
                        aliases.append(item)
                    elif (
                        len(query) >= 2
                        and query in _name_key(display)
                        and not re.search(
                            r"卸载|更新|帮助|uninstall|updater|setup|helper", display, re.I
                        )
                    ):
                        partial.append(item)
        matches = exact or aliases or partial
        unique = {}
        for entry in matches:
            target = entry.get("path") or entry.get("url") or entry.get("command")
            if target:
                unique.setdefault(os.path.normcase(target), entry)
        return list(unique.values())

    def find_candidates(self, name):
        matches = self._matching_entries(name, self.load_app_index())
        if not matches:
            index = self.build_app_index()
            try:
                self.save_app_index(index)
            except OSError as exc:
                logger.warning("应用索引暂未保存：%s", exc)
            matches = self._matching_entries(name, index)
        return matches[:12]

    @staticmethod
    def _match_entry(name, index):
        matches = AppDiscoveryService._matching_entries(name, index)
        if len(matches) > 1:
            options = "\n".join(
                f"• {e.get('display_name', name)}：{e.get('path') or e.get('url') or e.get('command')}"
                for e in matches[:5]
            )
            raise ValueError(
                f"找到多个「{name}」入口，暂未打开：\n{options}\n请使用更完整的软件名称或直接提供其中的路径。"
            )
        return next(iter(matches), None)

    def count_summary(self, index: dict) -> tuple[int, int, int]:
        """返回 (apps数, folders数, websites数) 用于通知文案"""
        return (
            len(index.get("apps", {})),
            len(index.get("folders", {})),
            len(index.get("websites", {})),
        )
