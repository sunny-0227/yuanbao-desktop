"""事务化笔记服务，失败抛出异常，避免虚假成功。"""

from datetime import datetime

from app.storage import Database


class NoteService:
    def __init__(self, db=None):
        self.db = db or Database()

    def all(self, query=""):
        with self.db.connect() as conn:
            return [
                dict(r)
                for r in conn.execute(
                    "SELECT * FROM notes WHERE content LIKE ? ORDER BY id DESC",
                    ("%" + query + "%",),
                )
            ]

    def add_note(self, content):
        if not content.strip():
            raise ValueError("请填写笔记内容")
        with self.db.connect() as conn:
            ident = conn.execute(
                "INSERT INTO notes(content,created_at) VALUES (?,?)",
                (content.strip(), datetime.now().isoformat(timespec="seconds")),
            ).lastrowid
        return f"已记录笔记 #{ident}：{content.strip()}"

    def update(self, ident, content):
        if not content.strip():
            raise ValueError("内容不能为空")
        with self.db.connect() as conn:
            conn.execute("UPDATE notes SET content=? WHERE id=?", (content.strip(), ident))

    def delete(self, ident):
        with self.db.connect() as conn:
            conn.execute("DELETE FROM notes WHERE id=?", (ident,))

    def list_notes(self):
        rows = self.all()[:30]
        return "暂无笔记。" if not rows else "\n".join(f"#{r['id']} {r['content']}" for r in rows)

    def clear_notes(self):
        with self.db.connect() as conn:
            conn.execute("DELETE FROM notes")
        return "已清空笔记。"
