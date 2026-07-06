"""
底部输入栏组件
包含多行文本框 + 发送按钮；支持 Shift+Enter 换行，Enter 发送
"""

from PySide6.QtWidgets import QWidget, QHBoxLayout, QPushButton
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QKeyEvent

from PySide6.QtWidgets import QTextEdit

from app.config import AppConfig


class _TextEdit(QTextEdit):
    """
    自定义文本框：
    - Enter 触发发送
    - Shift+Enter 换行
    """
    enter_pressed = Signal()

    def keyPressEvent(self, event: QKeyEvent):
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            if event.modifiers() & Qt.KeyboardModifier.ShiftModifier:
                # Shift+Enter 插入换行
                super().keyPressEvent(event)
            else:
                # 普通 Enter 发送
                self.enter_pressed.emit()
        else:
            super().keyPressEvent(event)


class InputBar(QWidget):
    """
    底部输入栏。
    message_sent(str) 信号会在用户按下发送后触发。
    """

    message_sent = Signal(str)  # 携带消息文本

    def __init__(self, config: AppConfig, parent=None):
        super().__init__(parent)
        self.config = config
        self._build_ui()

    def _build_ui(self):
        self.setObjectName("InputBar")
        self.setFixedHeight(90)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(8)

        # 输入框
        self.text_edit = _TextEdit()
        self.text_edit.setObjectName("InputTextEdit")
        self.text_edit.setPlaceholderText("输入消息… (Enter 发送，Shift+Enter 换行)")
        self.text_edit.setFixedHeight(66)
        self.text_edit.enter_pressed.connect(self._on_send)

        # 发送按钮
        self.send_btn = QPushButton("发送")
        self.send_btn.setObjectName("SendButton")
        self.send_btn.setFixedSize(72, 66)
        self.send_btn.clicked.connect(self._on_send)

        layout.addWidget(self.text_edit)
        layout.addWidget(self.send_btn)

    def _on_send(self):
        """获取文本并发出信号，随后清空输入框"""
        text = self.text_edit.toPlainText().strip()
        if text:
            self.message_sent.emit(text)
            self.text_edit.clear()
