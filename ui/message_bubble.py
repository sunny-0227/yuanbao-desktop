"""独立聊天气泡：左右对齐、自适应宽度、安全Markdown和文本选择。"""

import math
import re

from PySide6.QtCore import QEvent, Qt, QTimer
from PySide6.QtGui import QDesktopServices, QTextDocument
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QTextBrowser, QVBoxLayout, QWidget

from ui.tray_menu import app_icon


class SafeDocument(QTextDocument):
    def loadResource(self, kind, url):
        # 聊天内容不得读取本地文件或加载远程图片。
        return None


class MessageBubble(QWidget):
    def __init__(self, role, content, parent=None):
        super().__init__(parent)
        self.role = role
        self.content = content
        self.setAccessibleName("你的消息" if role == "user" else "元宝回复")
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(10)
        avatar = QLabel("我" if role == "user" else "")
        avatar.setObjectName("UserAvatar" if role == "user" else "PetAvatar")
        avatar.setAlignment(Qt.AlignmentFlag.AlignCenter)
        avatar.setFixedSize(34, 34)
        if role != "user":
            avatar.setPixmap(app_icon().pixmap(34, 34))
        self.body = QFrame()
        self.body.setObjectName(
            "UserBubble"
            if role == "user"
            else "ErrorBubble"
            if role == "error"
            else "AssistantBubble"
        )
        body = QVBoxLayout(self.body)
        body.setContentsMargins(14, 10, 14, 10)
        body.setSpacing(4)
        if role in ("error", "system"):
            label = QLabel("暂未完成" if role == "error" else "提示")
            label.setObjectName("BubbleHint")
            body.addWidget(label)
        self.text = QTextBrowser()
        self.text.setObjectName("BubbleText")
        self.text.setFrameShape(QFrame.Shape.NoFrame)
        self.text.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.text.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.text.setOpenLinks(False)
        self.text.setOpenExternalLinks(False)
        self.text.anchorClicked.connect(self._open_link)
        self.document = SafeDocument(self.text)
        self.document.setDocumentMargin(0)
        self.text.setDocument(self.document)
        body.addWidget(self.text)
        if role == "user":
            row.addStretch(1)
            row.addWidget(self.body)
            row.addWidget(avatar, 0, Qt.AlignmentFlag.AlignTop)
        else:
            row.addWidget(avatar, 0, Qt.AlignmentFlag.AlignTop)
            row.addWidget(self.body)
            row.addStretch(1)
        self.set_content(content)

    def _open_link(self, url):
        if url.scheme() in ("http", "https"):
            QDesktopServices.openUrl(url)

    def set_content(self, content):
        self.content = content
        text = re.sub(r"!\[([^]]*)\]\([^)]*\)", r"[图片：\1]", content)
        self.document.setMarkdown(
            text,
            QTextDocument.MarkdownFeature.MarkdownDialectGitHub
            | QTextDocument.MarkdownFeature.MarkdownNoHTML,
        )
        self._fit()

    def _fit(self):
        # 短消息按内容收窄，长消息最多占对话区约72%，保留两侧聊天留白。
        available = max(160, min(720, round(self.width() * 0.72) - 44))
        self.document.setDefaultFont(self.text.font())
        self.document.setTextWidth(available)
        width = min(available, max(28, math.ceil(self.document.idealWidth()) + 2))
        self.document.setTextWidth(width)
        self.text.setFixedSize(width + 2, max(22, math.ceil(self.document.size().height()) + 4))
        self.body.setFixedWidth(width + 30)
        self.updateGeometry()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._fit()

    def changeEvent(self, event):
        super().changeEvent(event)
        if event.type() in (QEvent.Type.StyleChange, QEvent.Type.ApplicationPaletteChange):
            if hasattr(self, "document"):
                QTimer.singleShot(0, self._fit)
