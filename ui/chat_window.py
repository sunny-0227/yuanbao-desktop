"""对话面板：历史会话、流式阅读与本地快捷入口。"""

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from ui.message_bubble import MessageBubble


class InputEdit(QTextEdit):
    submitted = Signal()

    def keyPressEvent(self, event):
        if (
            event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter)
            and not event.modifiers() & Qt.KeyboardModifier.ShiftModifier
        ):
            self.submitted.emit()
        else:
            super().keyPressEvent(event)


class ChatWindow(QWidget):
    send_requested = Signal(str)
    cancel_requested = Signal()
    voice_requested = Signal()
    new_requested = Signal()
    load_requested = Signal(str)
    delete_requested = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.messages = []
        self.partial_text = ""
        self.running = False
        self.voice_state = "idle"
        layout = QVBoxLayout(self)
        layout.setContentsMargins(22, 20, 22, 20)
        layout.setSpacing(12)
        title = QLabel("随时说一句，元宝来帮你")
        title.setObjectName("PageTitle")
        layout.addWidget(title)
        hint = QLabel("本地指令直接处理 · AI 对话支持连续追问")
        hint.setObjectName("Hint")
        layout.addWidget(hint)
        row = QHBoxLayout()
        self.sessions = QComboBox()
        self.sessions.setAccessibleName("历史会话")
        self.sessions.activated.connect(
            lambda _: self.load_requested.emit(self.sessions.currentData())
        )
        row.addWidget(self.sessions, 1)
        new = QPushButton("新对话")
        new.clicked.connect(self.new_requested.emit)
        row.addWidget(new)
        delete = QPushButton("删除会话")
        delete.clicked.connect(self._delete)
        row.addWidget(delete)
        layout.addLayout(row)
        self.view = QScrollArea()
        self.view.setObjectName("ChatScroll")
        self.view.setWidgetResizable(True)
        self.view.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.view.setAccessibleName("对话内容")
        self.surface = QWidget()
        self.surface.setObjectName("ChatSurface")
        self.message_layout = QVBoxLayout(self.surface)
        self.message_layout.setContentsMargins(20, 20, 20, 20)
        self.message_layout.setSpacing(18)
        self.empty_label = QLabel(
            "今天有什么需要处理？\n\n可以说“打开桌面上的微信”，也可以输入问题与元宝聊聊。\n"
            "普通软件指令自动在本地处理；AI对话请先在设置里完成连接。"
        )
        self.empty_label.setObjectName("ChatEmpty")
        self.empty_label.setWordWrap(True)
        self.message_layout.addWidget(self.empty_label)
        self.message_layout.addStretch(1)
        self.bubbles = []
        self.partial_bubble = None
        self.follow_bottom = True
        self.view.setWidget(self.surface)
        bar = self.view.verticalScrollBar()
        bar.valueChanged.connect(
            lambda value: setattr(self, "follow_bottom", bar.maximum() - value < 50)
        )
        bar.rangeChanged.connect(
            lambda low, high: bar.setValue(high) if self.follow_bottom else None
        )
        layout.addWidget(self.view, 1)
        quick = QHBoxLayout()
        for label, command in (
            ("看电脑状态", "查看电脑状态"),
            ("记一条笔记", "记一下 "),
            ("设个提醒", "十分钟后提醒我 "),
            ("截图", "截图"),
        ):
            button = QPushButton(label)
            button.clicked.connect(lambda checked=False, text=command: self._quick(text))
            quick.addWidget(button)
        layout.addLayout(quick)
        self.input = InputEdit()
        self.input.setMaximumHeight(110)
        self.input.setMinimumHeight(75)
        self.input.setPlaceholderText(
            "例如：打开微信 / 明天下午3点提醒我开会 / 帮我整理这段话\nEnter 发送，Shift+Enter 换行"
        )
        self.input.setAccessibleName("输入消息")
        self.input.submitted.connect(self._send)
        layout.addWidget(self.input)
        footer = QHBoxLayout()
        self.status_label = QLabel("可以开始对话")
        self.status_label.setObjectName("Status")
        footer.addWidget(self.status_label, 1)
        self.voice_btn = QPushButton("语音输入")
        self.voice_btn.clicked.connect(self.voice_requested.emit)
        footer.addWidget(self.voice_btn)
        self.send_btn = QPushButton("发送")
        self.send_btn.setObjectName("Primary")
        self.send_btn.clicked.connect(self._send)
        footer.addWidget(self.send_btn)
        layout.addLayout(footer)
        self._render()

    def _send(self):
        if self.running:
            self.cancel_requested.emit()
            return
        if self.voice_state in ("recording", "recognizing"):
            self.status_label.setText("请先结束录音或识别")
            return
        text = self.input.toPlainText().strip()
        if text:
            self.input.clear()
            self.send_requested.emit(text)

    def _quick(self, text):
        self.input.setPlainText(text)
        self.input.setFocus()
        if not text.endswith(" "):
            self._send()

    def _delete(self):
        ident = self.sessions.currentData()
        if (
            ident
            and QMessageBox.question(self, "删除会话", "删除这段对话及本地记录？")
            == QMessageBox.StandardButton.Yes
        ):
            self.delete_requested.emit(ident)

    def _append_bubble(self, role, text):
        bubble = MessageBubble(role, text, self.surface)
        self.message_layout.insertWidget(self.message_layout.count() - 1, bubble)
        self.empty_label.hide()
        return bubble

    def _remove_partial(self):
        if self.partial_bubble:
            self.message_layout.removeWidget(self.partial_bubble)
            self.partial_bubble.deleteLater()
            self.partial_bubble = None

    def add_message(self, role, text):
        if role in ("assistant", "error"):
            self.partial_text = ""
            self._remove_partial()
        if role == "user":
            self.follow_bottom = True
        self.messages.append({"role": role, "content": text})
        self.bubbles.append(self._append_bubble(role, text))
        self._scroll_after_layout()

    def set_partial(self, text):
        if text == self.partial_text:
            return
        self.partial_text = text
        if not text:
            self._remove_partial()
            self.empty_label.setVisible(not self.messages)
        elif self.partial_bubble:
            self.partial_bubble.set_content(text)
        else:
            self.partial_bubble = self._append_bubble("assistant", text)
        self._scroll_after_layout()

    def load_messages(self, messages):
        self.messages = list(messages)
        self.partial_text = ""
        self.follow_bottom = True
        self._render()

    def _render(self):
        self._remove_partial()
        for bubble in self.bubbles:
            self.message_layout.removeWidget(bubble)
            bubble.deleteLater()
        self.bubbles = [self._append_bubble(e["role"], e["content"]) for e in self.messages]
        self.empty_label.setVisible(not self.messages)
        self._scroll_after_layout()

    def _scroll_after_layout(self):
        if self.follow_bottom:
            QTimer.singleShot(
                0,
                lambda: (
                    self.view.verticalScrollBar().setValue(self.view.verticalScrollBar().maximum())
                    if self.follow_bottom
                    else None
                ),
            )

    def set_busy(self, value):
        self.running = value
        self.send_btn.setText("停止" if value else "发送")
        self.voice_btn.setEnabled(not value)

    def set_audio_state(self, state):
        self.voice_state = state
        self.voice_btn.setText(
            {
                "idle": "语音输入",
                "recording": "结束录音",
                "recognizing": "停止识别",
                "speaking": "停止播报",
            }[state]
        )
        if state != "idle":
            self.status_label.setText(
                {
                    "recording": "正在聆听，最长30秒",
                    "recognizing": "正在识别",
                    "speaking": "正在播报",
                }[state]
            )

    def update_sessions(self, rows, active):
        self.sessions.blockSignals(True)
        self.sessions.clear()
        for row in rows:
            self.sessions.addItem(row["title"], row["id"])
        self.sessions.setCurrentIndex(self.sessions.findData(active))
        self.sessions.blockSignals(False)
