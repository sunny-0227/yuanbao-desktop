"""对话面板：历史会话、流式阅读与本地快捷入口。"""

import html

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QDesktopServices, QTextDocument
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QTextBrowser,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)


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


class SafeDocument(QTextDocument):
    def loadResource(self, kind, url):
        # 模型文本不能加载远程图片、文件路径或主动发出网络请求。
        return None


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
        self.view = QTextBrowser()
        self.document = SafeDocument(self.view)
        self.view.setDocument(self.document)
        self.view.setOpenLinks(False)
        self.view.anchorClicked.connect(self._open_link)
        self.view.setAccessibleName("对话内容")
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

    def _open_link(self, url):
        if url.scheme() in ("https", "http"):
            QDesktopServices.openUrl(url)

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

    def add_message(self, role, text):
        if role == "assistant":
            self.partial_text = ""
        self.messages.append({"role": role, "content": text})
        self._render()

    def set_partial(self, text):
        if text == self.partial_text:
            return
        self.partial_text = text
        self._render()

    def load_messages(self, messages):
        self.messages = list(messages)
        self.partial_text = ""
        self._render()

    def _render(self):
        bar = self.view.verticalScrollBar()
        follow = bar.maximum() - bar.value() < 50
        position = bar.value()
        entries = self.messages + (
            [{"role": "assistant", "content": self.partial_text}] if self.partial_text else []
        )
        if not entries:
            self.document.setMarkdown(
                "### 今天有什么需要处理？\n\n你可以直接说“打开计算器”，也可以输入问题与元宝聊聊。\n\nAI 和语音首次使用时，请先到设置完成连接。"
            )
        else:
            parts = []
            for entry in entries:
                label = {
                    "user": "你",
                    "assistant": "元宝",
                    "error": "未完成",
                    "system": "提示",
                }.get(entry["role"], "元宝")
                text = html.escape(entry["content"])
                # Markdown 图片不加载，也不把模型 HTML 当网页执行。
                import re

                text = re.sub(r"!\[([^]]*)\]\([^)]*\)", r"[图片：\1]", text)
                parts.append("**" + label + "**\n\n" + text)
            self.document.setMarkdown("\n\n---\n\n".join(parts))
        QTimer.singleShot(0, lambda: bar.setValue(bar.maximum() if follow else position))

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
