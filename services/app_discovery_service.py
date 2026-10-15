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
import os
import platform
import re
import shutil
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
    aliases = [display_name]
    key = display_name.lower()
    for map_key, extra in _ALIAS_MAP.items():
        if key == map_key or key.startswith(map_key):
            for a in extra:
                if a not in aliases:
                    aliases.append(a)
            break
    return aliases


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

        if not target:
            logger.debug(f"跳过空目标快捷方式：{lnk_path}")
            return None

        # 展开环境变量
        target_expanded = _expand(target)

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
        """
        扫描桌面、公共桌面、开始菜单、任务栏固定快捷方式。
        返回已解析的原始条目列表，格式：
        {"apps": [...], "folders": [...], "websites": [...]}
        """
        if platform.system() != "Windows":
            logger.info("AppDiscoveryService：非 Windows 环境，跳过扫描")
            return {"apps": [], "folders": [], "websites": []}

        apps, folders, websites = [], [], []

        for source, raw_dir in _SCAN_SOURCES:
            scan_dir = _expand(raw_dir)
            if not os.path.isdir(scan_dir):
                logger.debug(f"扫描目录不存在，跳过：{scan_dir}")
                continue

            for filename in os.listdir(scan_dir):
                full_path = os.path.join(scan_dir, filename)
                try:
                    if filename.lower().endswith(".lnk"):
                        entry = _parse_lnk(full_path, source)
                        if entry:
                            if entry["entry_type"] == "folder":
                                folders.append(entry)
                            else:
                                apps.append(entry)
                    elif filename.lower().endswith(".url"):
                        entry = _parse_url_file(full_path, source)
                        if entry:
                            websites.append(entry)
                except Exception as e:
                    logger.debug(f"处理快捷方式异常，跳过（{full_path}）：{e}")

            # 开始菜单目录：递归一层子目录
            if source in ("start_menu", "public_start_menu"):
                for subdir in os.listdir(scan_dir):
                    sub_path = os.path.join(scan_dir, subdir)
                    if not os.path.isdir(sub_path):
                        continue
                    for filename in os.listdir(sub_path):
                        full_path = os.path.join(sub_path, filename)
                        try:
                            if filename.lower().endswith(".lnk"):
                                entry = _parse_lnk(full_path, source)
                                if entry:
                                    if entry["entry_type"] == "folder":
                                        folders.append(entry)
                                    else:
                                        apps.append(entry)
                            elif filename.lower().endswith(".url"):
                                entry = _parse_url_file(full_path, source)
                                if entry:
                                    websites.append(entry)
                        except Exception as e:
                            logger.debug(f"处理快捷方式异常，跳过（{full_path}）：{e}")

        logger.info(
            f"AppDiscovery 扫描完成：{len(apps)} 个应用，"
            f"{len(folders)} 个文件夹，{len(websites)} 个网页"
        )
        return {"apps": apps, "folders": folders, "websites": websites}

    def build_app_index(self) -> dict:
        """
        整合 apps、folders、websites、system_tools，生成完整索引。
        同名条目：后扫描的来源覆盖前者，但 desktop_shortcut 优先级最高。
        """
        raw = self.scan_shortcuts()
        index = _empty_index()
        now = _now_str()

        # 优先级：桌面 > 公共桌面 > 开始菜单 > 公共开始菜单 > 任务栏
        priority = {
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
            # candidates 保存同名多路径
            existing = index["apps"].get(name)
            if existing:
                if not _better(existing, entry["source"]):
                    candidates = existing.setdefault("candidates", [])
                    candidates.append({"path": entry["path"], "source": entry["source"]})
                    continue
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
        """
        根据名称或别名查找条目。
        查找顺序：apps → folders → websites → system_tools。
        匹配策略：精确 > 别名精确 > 包含匹配。
        返回 {"category": "apps"|"folders"|"websites"|"system_tools", **entry_fields}
        或 None（未找到）。
        """
        index = self.load_app_index()
        name_lower = name.strip().lower()

        for category in ("apps", "folders", "websites", "system_tools"):
            section = index.get(category, {})
            # 精确匹配 display_name
            for key, entry in section.items():
                if key.lower() == name_lower:
                    return {"category": category, **entry}
            # 别名精确匹配
            for _key, entry in section.items():
                aliases = [a.lower() for a in entry.get("aliases", [])]
                if name_lower in aliases:
                    return {"category": category, **entry}

        return None

    def count_summary(self, index: dict) -> tuple[int, int, int]:
        """返回 (apps数, folders数, websites数) 用于通知文案"""
        return (
            len(index.get("apps", {})),
            len(index.get("folders", {})),
            len(index.get("websites", {})),
        )
