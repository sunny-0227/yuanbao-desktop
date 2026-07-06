"""
聊天历史持久化服务
将对话记录保存到本地 JSON 文件，支持加载历史会话（预留接口，第一版不强制使用）
"""

import json
import os
from datetime import datetime
from typing import Optional

from app.app_context import resource_path, data_path
from app.logger import setup_logger

logger = setup_logger()

HISTORY_FILE = "chat_history.json"


class ChatHistory:
    """
    简单的对话历史管理器。
    每次会话保存为独立条目，存储在 data/chat_history.json 中。
    """

    def __init__(self):
        self.file_path = data_path(os.path.join("data", HISTORY_FILE))

    def save_session(self, messages: list[dict]) -> bool:
        """
        保存当前会话到文件。
        返回是否保存成功。
        """
        if not messages:
            return False

        try:
            history = self._load_raw()
            session = {
                "timestamp": datetime.now().isoformat(),
                "messages": messages,
            }
            history.append(session)

            os.makedirs(os.path.dirname(self.file_path), exist_ok=True)
            with open(self.file_path, "w", encoding="utf-8") as f:
                json.dump(history, f, ensure_ascii=False, indent=2)

            logger.info(f"聊天记录已保存，共 {len(messages)} 条消息")
            return True

        except Exception as e:
            logger.error(f"保存聊天记录失败：{e}")
            return False

    def load_last_session(self) -> list[dict]:
        """加载最近一次会话的消息列表，找不到则返回空列表"""
        history = self._load_raw()
        if history:
            return history[-1].get("messages", [])
        return []

    def _load_raw(self) -> list:
        """从文件读取原始历史数据"""
        if not os.path.exists(self.file_path):
            return []
        try:
            with open(self.file_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError) as e:
            logger.warning(f"读取聊天历史失败：{e}")
            return []
