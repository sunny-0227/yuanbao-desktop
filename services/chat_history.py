"""会话保存、恢复与上下文窗口。"""

import uuid
from datetime import datetime

from app.storage import Database


class ChatHistory:
    def __init__(self, db=None):
        self.db = db or Database()

    def create(self, title="新对话"):
        ident = uuid.uuid4().hex
        with self.db.connect() as conn:
            conn.execute(
                "INSERT INTO sessions VALUES (?,?,?)", (ident, title, datetime.now().isoformat())
            )
        return ident

    def sessions(self):
        with self.db.connect() as conn:
            return [
                dict(r) for r in conn.execute("SELECT * FROM sessions ORDER BY created_at DESC")
            ]

    def append(self, session_id, role, content):
        with self.db.connect() as conn:
            if role == "user":
                conn.execute(
                    "UPDATE sessions SET title=? WHERE id=? AND title='新对话'",
                    (content[:24], session_id),
                )
            conn.execute(
                "INSERT INTO messages(session_id,role,content,created_at) VALUES (?,?,?,?)",
                (session_id, role, content, datetime.now().isoformat()),
            )

    def messages(self, session_id):
        with self.db.connect() as conn:
            return [
                dict(r)
                for r in conn.execute(
                    "SELECT role,content FROM messages WHERE session_id=? ORDER BY id",
                    (session_id,),
                )
            ]

    def context(self, session_id, max_chars=6000):
        chosen, size = [], 0
        for row in reversed(self.messages(session_id)):
            if size + len(row["content"]) > max_chars and chosen:
                break
            chosen.append(row)
            size += len(row["content"])
        return list(reversed(chosen))

    def delete(self, ident):
        with self.db.connect() as conn:
            conn.execute("DELETE FROM messages WHERE session_id=?", (ident,))
            conn.execute("DELETE FROM conversation_state WHERE session_id=?", (ident,))
            conn.execute("DELETE FROM tool_events WHERE session_id=?", (ident,))
            conn.execute("DELETE FROM sessions WHERE id=?", (ident,))
