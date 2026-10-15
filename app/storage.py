"""原子 JSON 与事务数据库；业务写入失败必须传递给调用方。"""

import json
import os
import sqlite3
import tempfile
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

from app.app_context import data_path


def atomic_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp = tempfile.mkstemp(prefix=path.name + ".", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp, path)
    finally:
        if os.path.exists(temp):
            os.unlink(temp)


class Database:
    """每次事务独立连接，WAL 允许主线程读取与后台写入并存。"""

    def __init__(self, path=None):
        self.path = str(path or data_path("assistant.sqlite3"))
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as conn:
            conn.executescript("""
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS todos (
                    id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT NOT NULL,
                    remind_time TEXT NOT NULL, recurrence TEXT NOT NULL DEFAULT '',
                    status TEXT NOT NULL DEFAULT 'pending', notified_at TEXT,
                    created_at TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS notes (
                    id INTEGER PRIMARY KEY AUTOINCREMENT, content TEXT NOT NULL,
                    created_at TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS sessions (
                    id TEXT PRIMARY KEY, title TEXT NOT NULL, created_at TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT, session_id TEXT NOT NULL,
                    role TEXT NOT NULL, content TEXT NOT NULL, created_at TEXT NOT NULL);
                CREATE INDEX IF NOT EXISTS messages_session ON messages(session_id,id);
                CREATE TABLE IF NOT EXISTS cache (
                    key TEXT PRIMARY KEY, answer TEXT NOT NULL, created_at REAL NOT NULL);
                CREATE TABLE IF NOT EXISTS metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS conversation_state (
                    session_id TEXT PRIMARY KEY, value TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS tool_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT, session_id TEXT NOT NULL,
                    name TEXT NOT NULL, arguments TEXT NOT NULL,
                    status TEXT NOT NULL, result TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL);
                CREATE INDEX IF NOT EXISTS tool_events_session ON tool_events(session_id,id);
            """)

    @contextmanager
    def connect(self):
        conn = sqlite3.connect(self.path, timeout=5)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        except BaseException:
            conn.rollback()
            raise
        finally:
            conn.close()

    def migrate_legacy(self, directory):
        """一次性导入旧 JSON；事务成功才记标记，不删除原文件。"""
        directory = Path(directory)
        with self.connect() as conn:
            key = "legacy:" + str(directory.resolve())
            if conn.execute("SELECT 1 FROM metadata WHERE key=?", (key,)).fetchone():
                return
            for filename, table in (("notes.json", "notes"), ("todos.json", "todos")):
                source = directory / filename
                if not source.exists():
                    continue
                rows = json.loads(source.read_text(encoding="utf-8"))
                if not isinstance(rows, list):
                    raise ValueError(f"{filename} 必须是列表，原文件已保留")
                for item in rows:
                    if table == "notes":
                        conn.execute(
                            "INSERT INTO notes(content,created_at) VALUES (?,?)",
                            (item["content"], item.get("created_at", "")),
                        )
                    else:
                        # 旧 done 表示已弹过通知，不代表用户已完成。
                        conn.execute(
                            "INSERT INTO todos(title,remind_time,status,created_at) VALUES (?,?,?,?)",
                            (
                                item["title"],
                                datetime.fromisoformat(item["remind_time"]).strftime(
                                    "%Y-%m-%d %H:%M:%S"
                                ),
                                "notified" if item.get("status") == "done" else "pending",
                                item.get("created_at", ""),
                            ),
                        )
            conn.execute("INSERT INTO metadata VALUES (?,?)", (key, "1"))
