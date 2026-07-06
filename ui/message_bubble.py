"""
聊天消息气泡组件
单条消息气泡：区分用户消息（右对齐）和 AI 消息（左对齐）
"""

from PySide6.QtWidgets import QWidget, QHBoxLayout, QLabel, QSizePolicy
from PySide6.QtCore import Qt
from PySide6.QtGui import QFont


class MessageBubble(QWidget):
    """
    单条消息气泡。
    role: "user" | "assistant"
    """

    def __init__(self, text: str, role: str, parent=None):
        super().__init__(parent)
        self.role = role
        self._label: QLabel | None = None
        self._build(text)

    def _build(self, text: str):
        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 4, 12, 4)
        layout.setSpacing(0)

        label = QLabel(text)
        label.setWordWrap(True)
        label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)

        font = QFont()
        font.setPointSize(11)
        label.setFont(font)

        if self.role == "user":
            label.setObjectName("UserBubble")
            layout.addStretch()
            layout.addWidget(label)
        else:
            label.setObjectName("AssistantBubble")
            layout.addWidget(label)
            layout.addStretch()

        self._label = label

    def setText(self, text: str):
        """更新气泡内容（用于动态更新 loading 文案）"""
        if self._label:
            self._label.setText(text)
