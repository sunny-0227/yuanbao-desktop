"""
聊天消息列表组件
展示对话历史，处理用户消息并调用 AI 服务获取回复
"""

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QScrollArea, QLabel, QSizePolicy
)
from PySide6.QtCore import Qt, QThread, Signal, Slot

from app.config import AppConfig
from app.logger import setup_logger
from ui.message_bubble import MessageBubble
from services.ai_service import AIService

logger = setup_logger()


class AIWorker(QThread):
    """
    在后台线程中调用 AI 服务，避免阻塞 UI。
    完成后通过信号将结果传回主线程。
    """
    reply_ready = Signal(str)    # 正常回复
    error_occurred = Signal(str) # 错误信息

    def __init__(self, service: AIService, messages: list, parent=None):
        super().__init__(parent)
        self.service = service
        self.messages = messages

    def run(self):
        """线程入口：调用 AI 服务"""
        try:
            reply = self.service.chat(self.messages)
            self.reply_ready.emit(reply)
        except Exception as e:
            logger.error(f"AI 调用失败：{e}")
            self.error_occurred.emit(str(e))


class ChatWidget(QWidget):
    """
    聊天消息列表主组件。
    维护本轮对话历史（messages），每次用户发送后追加并请求 AI 回复。
    """

    def __init__(self, config: AppConfig, parent=None):
        super().__init__(parent)
        self.config = config
        self.ai_service = AIService(config.ai)
        self.messages: list[dict] = []   # OpenAI 格式消息历史
        self._worker: AIWorker | None = None
        self._build_ui()
        self._add_welcome_message()

    def _build_ui(self):
        """构建可滚动的消息列表"""
        root_layout = QVBoxLayout(self)
        root_layout.setContentsMargins(0, 0, 0, 0)

        # 滚动区域
        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.scroll_area.setObjectName("ChatScrollArea")

        # 消息容器
        self.msg_container = QWidget()
        self.msg_container.setObjectName("MsgContainer")
        self.msg_layout = QVBoxLayout(self.msg_container)
        self.msg_layout.setContentsMargins(0, 8, 0, 8)
        self.msg_layout.setSpacing(2)
        self.msg_layout.addStretch()  # 消息从上往下堆叠

        self.scroll_area.setWidget(self.msg_container)
        root_layout.addWidget(self.scroll_area)

    def _add_welcome_message(self):
        """首次打开时显示欢迎语"""
        welcome = (
            "你好！我是你的桌面AI助手 🤖\n"
            "有什么我可以帮到你的吗？"
        )
        self._append_bubble(welcome, "assistant")

    def _append_bubble(self, text: str, role: str):
        """
        向消息列表末尾添加一个气泡。
        注意：插入到 stretch 之前（index = count-1）。
        """
        bubble = MessageBubble(text=text, role=role)
        # stretch 占据最后一个位置，新气泡插在它前面
        insert_pos = self.msg_layout.count() - 1
        self.msg_layout.insertWidget(insert_pos, bubble)
        # 滚动到底部
        self._scroll_to_bottom()

    def _scroll_to_bottom(self):
        """将滚动条移到最底部"""
        bar = self.scroll_area.verticalScrollBar()
        bar.setValue(bar.maximum())

    def _show_loading(self):
        """显示"正在思考…"占位气泡"""
        self._loading_bubble = MessageBubble(text="正在思考…", role="assistant")
        insert_pos = self.msg_layout.count() - 1
        self.msg_layout.insertWidget(insert_pos, self._loading_bubble)
        self._scroll_to_bottom()

    def _remove_loading(self):
        """移除"正在思考…"占位气泡"""
        if hasattr(self, "_loading_bubble") and self._loading_bubble:
            self._loading_bubble.setParent(None)
            self._loading_bubble.deleteLater()
            self._loading_bubble = None

    @Slot(str)
    def on_user_message(self, text: str):
        """接收用户输入，显示气泡，并异步请求 AI 回复"""
        if not text.strip():
            return

        # 展示用户气泡
        self._append_bubble(text, "user")

        # 追加到消息历史（OpenAI 格式）
        self.messages.append({"role": "user", "content": text})

        # 显示加载占位
        self._show_loading()

        # 构建完整消息列表（含 system prompt）
        full_messages = [
            {"role": "system", "content": self.config.ai.system_prompt}
        ] + self.messages

        # 启动后台 AI 线程
        self._worker = AIWorker(self.ai_service, full_messages)
        self._worker.reply_ready.connect(self._on_ai_reply)
        self._worker.error_occurred.connect(self._on_ai_error)
        self._worker.start()

    @Slot(str)
    def _on_ai_reply(self, reply: str):
        """AI 回复就绪，更新 UI"""
        self._remove_loading()
        self._append_bubble(reply, "assistant")
        self.messages.append({"role": "assistant", "content": reply})

    @Slot(str)
    def _on_ai_error(self, error: str):
        """AI 调用出错，显示错误提示"""
        self._remove_loading()
        self._append_bubble(f"⚠️ 出错了：{error}", "assistant")

    def clear_messages(self):
        """清空聊天记录和消息历史"""
        # 移除所有 MessageBubble 子组件
        for i in reversed(range(self.msg_layout.count())):
            item = self.msg_layout.itemAt(i)
            if item and item.widget():
                widget = item.widget()
                if isinstance(widget, MessageBubble):
                    widget.setParent(None)
                    widget.deleteLater()

        self.messages.clear()
        self._add_welcome_message()
