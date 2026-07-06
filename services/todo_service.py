"""
待办 / 提醒服务
将提醒事项持久化到 data/todos.json，支持新增、查看、删除、到点检测。

功能说明：
- 支持时间格式：HH:MM（默认今天，已过时顺延明天）和 YYYY-MM-DD HH:MM
- 待办状态：pending（未提醒）/ done（已提醒）
- check_due_todos() 检测到期任务并自动将状态标记为 done
- todos.json 不存在时自动创建；损坏时备份为 .bak 后重置

与 chat_window.py 的协作方式：
    chat_window 只负责调用 TodoService 的方法，所有业务逻辑封装在此。
"""

import json
import os
import re
from datetime import datetime, timedelta
from typing import Optional

from app.app_context import resource_path, data_path
from app.logger import setup_logger

logger = setup_logger()

# 数据文件路径：使用 data_path 保证打包后写入 exe 同目录（而非 _MEIPASS 临时目录）
_TODOS_PATH = data_path(os.path.join("data", "todos.json"))

# 支持的时间格式（第一版，不做 NLP 解析）
_FMT_DATETIME = "%Y-%m-%d %H:%M"   # 完整日期+时间
_FMT_TIME     = "%H:%M"            # 仅时分（默认今天，已过则顺延明天）


# ── 私有工具函数 ──────────────────────────────────────────────

def _load_todos() -> list:
    """
    从 todos.json 加载待办列表。
    文件不存在时返回空列表；
    JSON 损坏时自动备份为 .bak 并重置为空列表，不崩溃。
    """
    if not os.path.exists(_TODOS_PATH):
        return []
    try:
        with open(_TODOS_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        # 健壮性：确保根节点是列表
        return data if isinstance(data, list) else []
    except json.JSONDecodeError:
        # 文件损坏，备份后重置
        backup_path = _TODOS_PATH + ".bak"
        try:
            os.replace(_TODOS_PATH, backup_path)
            logger.warning(f"todos.json 格式异常，已备份到 {backup_path}，重置为空列表")
            # 立即写入空文件，避免下次 _load 前程序异常时再次触发备份逻辑
            _save_todos([])
        except Exception as backup_err:
            logger.error(f"备份/重置 todos.json 失败：{backup_err}")
        return []
    except Exception as e:
        logger.error(f"加载 todos.json 失败：{e}")
        return []


def _save_todos(todos: list) -> None:
    """将待办列表写入 todos.json，目录不存在时自动创建。"""
    try:
        os.makedirs(os.path.dirname(_TODOS_PATH), exist_ok=True)
        with open(_TODOS_PATH, "w", encoding="utf-8") as f:
            json.dump(todos, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.error(f"写入 todos.json 失败：{e}")


def _next_id(todos: list) -> int:
    """生成自增 ID：取现有最大 id + 1，列表为空时从 1 开始。"""
    return max((t.get("id", 0) for t in todos), default=0) + 1


def _parse_remind_time(text: str) -> Optional[str]:
    """
    从用户输入文本中解析提醒时间，返回 "YYYY-MM-DD HH:MM" 格式字符串。
    支持两种格式：
      1. HH:MM         → 使用今天日期；如果时间已过，顺延到明天
      2. YYYY-MM-DD HH:MM → 直接使用
    解析失败时返回 None（不抛异常）。
    """
    text = text.strip()

    # 尝试匹配完整日期时间：YYYY-MM-DD HH:MM
    m = re.search(r"(\d{4}-\d{2}-\d{2}\s+\d{1,2}:\d{2})", text)
    if m:
        raw = m.group(1).strip()
        try:
            dt = datetime.strptime(raw, _FMT_DATETIME)
            return dt.strftime(_FMT_DATETIME)
        except ValueError:
            pass  # 格式对但日期非法（如 2026-13-01），继续尝试其他

    # 尝试匹配纯时间：HH:MM 或 H:MM
    m = re.search(r"\b(\d{1,2}:\d{2})\b", text)
    if m:
        raw = m.group(1)
        try:
            t = datetime.strptime(raw, _FMT_TIME)
            now = datetime.now()
            # 用今天的日期拼出完整 datetime
            candidate = now.replace(hour=t.hour, minute=t.minute, second=0, microsecond=0)
            # 如果时间已经过去（超过1分钟容错），顺延到明天
            if candidate < now - timedelta(minutes=1):
                candidate += timedelta(days=1)
            return candidate.strftime(_FMT_DATETIME)
        except ValueError:
            pass

    return None  # 无法解析时返回 None


def _extract_title(text: str) -> str:
    """
    从用户输入中提取提醒标题（去掉时间部分和触发关键词）。
    例：
      "提醒我 18:30 喝水"          → "喝水"
      "提醒我 2026-07-06 20:00 开会" → "开会"
    """
    # 先去掉完整日期时间
    s = re.sub(r"\d{4}-\d{2}-\d{2}\s+\d{1,2}:\d{2}", "", text)
    # 再去掉纯时间
    s = re.sub(r"\b\d{1,2}:\d{2}\b", "", s)
    # 去掉触发关键词前缀（提醒我 / 帮我提醒 / 记得 等）
    s = re.sub(r"^(提醒我|帮我提醒|帮忙提醒|记得|设个提醒|加个提醒)\s*", "", s.strip())
    # 清理多余空格
    return re.sub(r"\s+", " ", s).strip()


# ── 服务类 ────────────────────────────────────────────────────

class TodoService:
    """
    待办 / 提醒服务。

    数据结构（每条记录）：
    {
        "id":          int,    # 自增 ID
        "title":       str,    # 提醒标题（用户描述内容）
        "remind_time": str,    # 提醒时间，"YYYY-MM-DD HH:MM" 格式
        "status":      str,    # "pending"（未提醒）/ "done"（已提醒）
        "created_at":  str     # 创建时间，"YYYY-MM-DD HH:MM" 格式
    }

    chat_window 只调用本类的公开方法，不持有任何待办业务逻辑。
    """

    # ── 公开接口 ─────────────────────────────────────────────

    def add_todo_from_text(self, text: str) -> str:
        """
        解析用户输入文本，提取时间和标题，新增一条待办提醒。
        适合直接接收聊天窗口的原始输入，如"提醒我 18:30 喝水"。

        返回：操作结果字符串，供聊天窗口展示。
        """
        try:
            # 解析提醒时间
            remind_time = _parse_remind_time(text)

            # 提取标题（去掉时间和触发词）
            title = _extract_title(text)
            if not title:
                return "⚠️ 请告诉我提醒内容，例如：提醒我 18:30 喝水"

            # 构建待办记录
            todos = _load_todos()
            new_id = _next_id(todos)
            entry = {
                "id":          new_id,
                "title":       title,
                "remind_time": remind_time or "",  # 无法解析时存空字符串
                "status":      "pending",
                "created_at":  datetime.now().strftime(_FMT_DATETIME),
            }
            todos.append(entry)
            _save_todos(todos)

            logger.debug(f"新增待办 #{new_id}：{title!r}  时间={remind_time!r}")

            # 组织返回给用户的提示
            if remind_time:
                return f"✅ 已添加提醒 #{new_id}：{title}（{remind_time}）"
            else:
                return (
                    f"✅ 已添加提醒 #{new_id}：{title}\n"
                    f"⚠️ 未能识别时间，若需定时提醒请使用格式：HH:MM 或 YYYY-MM-DD HH:MM"
                )

        except Exception as e:
            logger.error(f"新增待办失败：{e}")
            return f"⚠️ 新增提醒失败：{e}"

    def list_todos(self) -> str:
        """
        返回当前所有待办提醒的列表文本，适合在聊天窗口展示。
        pending 状态在前，done 状态在后，按 id 排序。
        """
        try:
            todos = _load_todos()
            if not todos:
                return "📋 暂无待办提醒。"

            # pending 在前，done 在后，同状态按 id 升序
            pending = [t for t in todos if t.get("status") == "pending"]
            done    = [t for t in todos if t.get("status") == "done"]

            lines = [f"📋 待办提醒（共 {len(todos)} 条）："]

            if pending:
                lines.append("  ⏰ 待提醒：")
                for t in sorted(pending, key=lambda x: x.get("id", 0)):
                    lines.append(_format_todo_line(t))

            if done:
                lines.append("  ✅ 已完成：")
                for t in sorted(done, key=lambda x: x.get("id", 0)):
                    lines.append(_format_todo_line(t))

            lines.append('\n提示：输入「删除提醒 [编号]」可删除对应条目。')
            return "\n".join(lines)

        except Exception as e:
            logger.error(f"查看待办失败：{e}")
            return f"⚠️ 查看提醒失败：{e}"

    def delete_todo(self, todo_id: int) -> str:
        """
        删除指定 ID 的待办提醒。
        返回：操作结果字符串，供聊天窗口展示。
        """
        try:
            todos = _load_todos()
            if not todos:
                return "📋 暂无待办可删除。"

            new_list = [t for t in todos if t.get("id") != todo_id]
            if len(new_list) == len(todos):
                return f'⚠️ 未找到编号为 {todo_id} 的提醒，请先输入「查看提醒」确认编号。'

            _save_todos(new_list)
            logger.debug(f"已删除待办 #{todo_id}")
            return f"🗑️ 提醒 #{todo_id} 已删除。"

        except Exception as e:
            logger.error(f"删除待办失败：{e}")
            return f"⚠️ 删除提醒失败：{e}"

    def check_due_todos(self) -> list:
        """
        检查当前时间已到期但状态仍为 pending 的待办。
        将到期任务的 status 更新为 done 并持久化。

        返回：到期任务的字典列表（已更新为 done），供调用方决定如何通知用户。
        格式：[{"id": int, "title": str, "remind_time": str, ...}, ...]
        """
        due: list = []
        try:
            todos = _load_todos()
            now_str = datetime.now().strftime(_FMT_DATETIME)
            changed = False

            for todo in todos:
                # 只检查 pending 状态且有提醒时间的任务
                if todo.get("status") != "pending":
                    continue
                remind_time = todo.get("remind_time", "")
                if not remind_time:
                    continue

                # 比较字符串即可（格式统一为 YYYY-MM-DD HH:MM，字典序等价于时间序）
                if remind_time <= now_str:
                    todo["status"] = "done"
                    due.append(dict(todo))  # 返回副本
                    changed = True
                    logger.debug(f"待办 #{todo.get('id')} 已到期：{todo.get('title')!r}")

            if changed:
                _save_todos(todos)

        except Exception as e:
            logger.error(f"检查到期待办失败：{e}")

        return due


# ── 私有格式化辅助 ────────────────────────────────────────────

def _format_todo_line(todo: dict) -> str:
    """将单条待办格式化为聊天窗口可展示的文本行。"""
    tid    = todo.get("id", "?")
    title  = todo.get("title", "（无标题）")
    rtime  = todo.get("remind_time", "")
    status = todo.get("status", "pending")

    status_icon = "⏰" if status == "pending" else "✅"
    time_part   = f"  [{rtime}]" if rtime else ""
    return f"    {status_icon} #{tid}{time_part} {title}"
