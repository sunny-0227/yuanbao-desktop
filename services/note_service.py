"""
快速记事服务
将用户口述的笔记保存到 data/notes.json，支持添加、查看、清空。

文件结构（notes.json）：
    [
        {"id": 1, "content": "买咖啡", "created_at": "2026-07-06 10:30:00"},
        ...
    ]

异常处理策略：
- 文件不存在 → 自动创建
- JSON 损坏 → 备份原文件（notes.json.bak）并重置为空数组，继续运行
"""

import json
import os
import shutil
from datetime import datetime

from app.app_context import resource_path, data_path
from app.logger import setup_logger

logger = setup_logger()

# 笔记文件路径：使用 data_path 保证打包后写入 exe 同目录（而非 _MEIPASS 临时目录）
_NOTES_PATH = data_path(os.path.join("data", "notes.json"))

# 查看笔记时最多显示的条数
_LIST_LIMIT = 10


class NoteService:
    """
    快速记事服务。

    所有方法返回字符串，可直接在聊天气泡中展示。
    实例无状态，每次操作直接读写文件，保证多次调用数据一致。
    """

    # ── 公开接口 ──────────────────────────────────────────────

    def add_note(self, content: str) -> str:
        """
        新增一条笔记。
        content 为空时返回提示，要求用户补充内容。
        """
        content = content.strip() if content else ""
        if not content:
            return "请告诉我要记什么内容？"

        notes = self._load()
        new_id = (notes[-1]["id"] + 1) if notes else 1
        note = {
            "id":         new_id,
            "content":    content,
            "created_at": _now(),
        }
        notes.append(note)
        self._save(notes)
        logger.debug(f"已添加笔记 #{new_id}：{content!r}")
        return f"✅ 已记录（#{new_id}）：{content}"

    def list_notes(self) -> str:
        """
        返回最近 N 条笔记的格式化文本。
        没有任何笔记时返回提示。
        """
        notes = self._load()
        if not notes:
            return "📒 你还没有任何笔记。"

        # 取最近 _LIST_LIMIT 条（列表末尾为最新）
        recent = notes[-_LIST_LIMIT:]
        lines = [f"📒 最近 {len(recent)} 条笔记："]
        for n in reversed(recent):   # 最新的显示在最前面
            lines.append(f"  #{n['id']}  {n['created_at']}  {n['content']}")
        return "\n".join(lines)

    def clear_notes(self) -> str:
        """清空所有笔记，并重置 notes.json 为空数组。"""
        notes = self._load()
        count = len(notes)
        self._save([])
        logger.debug(f"已清空 {count} 条笔记")
        if count == 0:
            return "📒 笔记本已经是空的。"
        return f"🗑️ 已清空全部 {count} 条笔记。"

    # ── 文件读写 ──────────────────────────────────────────────

    def _load(self) -> list:
        """
        从 notes.json 读取笔记列表。
        文件不存在时返回空列表；JSON 损坏时备份后返回空列表。
        """
        if not os.path.exists(_NOTES_PATH):
            return []

        try:
            with open(_NOTES_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
            # 基本结构校验：必须是列表
            if not isinstance(data, list):
                raise ValueError("notes.json 顶层不是数组")
            return data
        except (json.JSONDecodeError, ValueError) as e:
            logger.error(f"notes.json 损坏：{e}，正在备份并重置")
            self._backup_and_reset()
            return []
        except IOError as e:
            logger.error(f"读取 notes.json 失败：{e}")
            return []

    def _save(self, notes: list) -> None:
        """将笔记列表写入 notes.json，目录不存在时自动创建。"""
        os.makedirs(os.path.dirname(_NOTES_PATH), exist_ok=True)
        try:
            with open(_NOTES_PATH, "w", encoding="utf-8") as f:
                json.dump(notes, f, ensure_ascii=False, indent=2)
        except IOError as e:
            logger.error(f"保存 notes.json 失败：{e}")

    def _backup_and_reset(self) -> None:
        """
        将损坏的 notes.json 备份为 notes.json.bak，
        然后用空数组覆盖原文件，保证后续操作正常进行。
        """
        bak_path = _NOTES_PATH + ".bak"
        try:
            shutil.copy2(_NOTES_PATH, bak_path)
            logger.info(f"已备份损坏文件到：{bak_path}")
        except Exception as e:
            logger.warning(f"备份失败：{e}")
        self._save([])


# ── 工具函数 ──────────────────────────────────────────────────

def _now() -> str:
    """返回当前时间的格式化字符串，用于笔记的 created_at 字段"""
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")
