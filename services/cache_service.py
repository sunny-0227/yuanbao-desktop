"""完整请求指纹与有效期缓存；失败结果不进入缓存。"""

import hashlib
import json
import time

from app.storage import Database


class CacheService:
    def __init__(self, enable=False, db=None, ttl=86400):
        self.enabled = enable
        self.db = db or Database()
        self.ttl = ttl

    @staticmethod
    def key(messages, model, endpoint, system_prompt="", **options):
        source = json.dumps(
            [messages, model, endpoint, system_prompt, options], ensure_ascii=False, sort_keys=True
        )
        return hashlib.sha256(source.encode()).hexdigest()

    def get(self, key):
        if not self.enabled:
            return None
        with self.db.connect() as conn:
            row = conn.execute("SELECT answer,created_at FROM cache WHERE key=?", (key,)).fetchone()
            return row["answer"] if row and time.time() - row["created_at"] < self.ttl else None

    def save(self, key, answer):
        if self.enabled and answer:
            with self.db.connect() as conn:
                conn.execute("DELETE FROM cache WHERE created_at<?", (time.time() - self.ttl,))
                conn.execute(
                    "INSERT OR REPLACE INTO cache VALUES (?,?,?)", (key, answer, time.time())
                )
                conn.execute(
                    "DELETE FROM cache WHERE key NOT IN (SELECT key FROM cache ORDER BY created_at DESC LIMIT 500)"
                )

    def clear(self):
        with self.db.connect() as conn:
            conn.execute("DELETE FROM cache")
