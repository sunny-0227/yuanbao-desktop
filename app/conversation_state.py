"""按会话保存任务状态与真实工具轨迹，聊天文本不能冒充执行记录。"""

import json
from datetime import datetime


class ConversationStore:
    def __init__(self, db, session):
        self.db, self.session = db, session

    def load(self):
        with self.db.connect() as conn:
            row = conn.execute(
                "SELECT value FROM conversation_state WHERE session_id=?", (self.session,)
            ).fetchone()
        return json.loads(row["value"]) if row else {}

    def save(self, state):
        with self.db.connect() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO conversation_state SELECT ?,? WHERE EXISTS(SELECT 1 FROM sessions WHERE id=?)",
                (self.session, json.dumps(state, ensure_ascii=False), self.session),
            )

    def start(self, name, arguments):
        # 必须先成功记录，再允许发生副作用；断电后保留started，不能假定失败并重放。
        with self.db.connect() as conn:
            if not conn.execute("SELECT 1 FROM sessions WHERE id=?", (self.session,)).fetchone():
                raise RuntimeError("会话已删除，操作没有执行")
            return conn.execute(
                "INSERT INTO tool_events(session_id,name,arguments,status,created_at) VALUES (?,?,?,?,?)",
                (
                    self.session,
                    name,
                    json.dumps(arguments, ensure_ascii=False),
                    "started",
                    datetime.now().isoformat(),
                ),
            ).lastrowid

    def finish(self, ident, result, state):
        with self.db.connect() as conn:
            conn.execute(
                "UPDATE tool_events SET status=?,result=? WHERE id=? AND session_id=?",
                (result["status"], json.dumps(result, ensure_ascii=False), ident, self.session),
            )
            conn.execute(
                "INSERT OR REPLACE INTO conversation_state SELECT ?,? WHERE EXISTS(SELECT 1 FROM sessions WHERE id=?)",
                (self.session, json.dumps(state, ensure_ascii=False), self.session),
            )

    def recent(self, limit=8):
        with self.db.connect() as conn:
            rows = conn.execute(
                "SELECT name,arguments,status,result FROM tool_events WHERE session_id=? ORDER BY id DESC LIMIT ?",
                (self.session, limit),
            ).fetchall()
        return [
            {
                **dict(row),
                "arguments": json.loads(row["arguments"]),
                "result": json.loads(row["result"]),
            }
            for row in reversed(rows)
        ]

    def has_unsettled(self):
        with self.db.connect() as conn:
            return (
                conn.execute(
                    "SELECT 1 FROM tool_events WHERE session_id=? AND status='started' LIMIT 1",
                    (self.session,),
                ).fetchone()
                is not None
            )
