"""
聊天消息气泡组件

支持三种气泡类型：
    user       右侧蓝紫渐变气泡
    assistant  左侧深色半透明气泡（含助手头像）
    loading    临时执行状态气泡（虚线边框 + 动态省略号）

loading 气泡额外提供：
    set_text(text)     更新气泡文案（用于 AI 流程时切换文案）
    start_dots()       开始动态省略号动画
    stop_dots()        停止动画（结果返回前调用）
"""

from PySide6.QtWidgets import (
    QWidget, QHBoxLayout, QVBoxLayout, QLabel, QSizePolicy, QPushButton
)
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QApplication


# 动态省略号帧序列
_DOT_FRAMES = ["", ".", "..", "..."]


class MessageBubble(QWidget):
    """
    单条消息气泡行容器。

    参数：
        text    气泡初始文案
        role    "user" | "assistant" | "loading"
    """

    def __init__(self, text: str, role: str, parent=None):
        super().__init__(parent)
        self.role    = role
        self._label: QLabel | None  = None   # 气泡文字标签
        self._base_text: str        = text   # loading 气泡的基础文案
        self._dot_timer: QTimer | None = None
        self._dot_idx: int          = 0

        self.setObjectName("BubbleRow")
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
        self._build(text)

        # loading 气泡自动启动动画
        if role == "loading":
            self.start_dots()

    # ── 构建 ──────────────────────────────────────────────────

    def _build(self, text: str):
        """构建气泡行布局"""
        row = QHBoxLayout(self)
        row.setContentsMargins(12, 3, 12, 3)
        row.setSpacing(8)

        if self.role == "user":
            self._build_user_bubble(row, text)
        elif self.role == "loading":
            self._build_loading_bubble(row, text)
        else:
            self._build_assistant_bubble(row, text)

    def _build_user_bubble(self, row: QHBoxLayout, text: str):
        """用户气泡：右侧对齐，无头像"""
        label = self._make_label(text, "UserBubble")
        row.addStretch(1)
        row.addWidget(label, 0, Qt.AlignmentFlag.AlignRight)

    def _build_assistant_bubble(self, row: QHBoxLayout, text: str):
        """助手气泡：左侧头像 + 气泡 + 复制按钮"""
        avatar = self._make_avatar("🤖")
        label  = self._make_label(text, "AssistantBubble")

        # 气泡 + 复制按钮垂直叠放
        col = QVBoxLayout()
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(2)
        col.addWidget(label, 0, Qt.AlignmentFlag.AlignLeft)

        # 复制按钮（默认半透明，hover 变亮）
        copy_btn = QPushButton("复制")
        copy_btn.setObjectName("CopyButton")
        copy_btn.setFixedSize(44, 20)
        copy_btn.setToolTip("复制消息内容")
        copy_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        copy_btn.clicked.connect(lambda: self._copy_text())
        col.addWidget(copy_btn, 0, Qt.AlignmentFlag.AlignLeft)

        row.addWidget(avatar, 0, Qt.AlignmentFlag.AlignTop)
        row.addLayout(col)
        row.addStretch(1)

    def _copy_text(self):
        """复制 label 文本到剪切板"""
        if self._label:
            QApplication.clipboard().setText(self._label.text())

    def _build_loading_bubble(self, row: QHBoxLayout, text: str):
        """loading 气泡：左侧头像 + 虚线气泡"""
        avatar = self._make_avatar("🤖")
        label  = self._make_label(text, "LoadingBubble")

        row.addWidget(avatar, 0, Qt.AlignmentFlag.AlignTop)
        row.addWidget(label,  0, Qt.AlignmentFlag.AlignLeft)
        row.addStretch(1)

    # ── 控件工厂 ─────────────────────────────────────────────

    def _make_label(self, text: str, obj_name: str) -> QLabel:
        """创建气泡文字标签"""
        label = QLabel(text)
        label.setObjectName(obj_name)
        label.setWordWrap(True)
        label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        label.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Minimum)
        # 最大宽度：约窗口宽度的 68%（具体由父容器宽度决定）
        label.setMaximumWidth(310)

        font = QFont()
        font.setPointSize(11)
        label.setFont(font)

        self._label = label
        return label

    def _make_avatar(self, emoji: str) -> QLabel:
        """创建助手头像小圆标签"""
        avatar = QLabel(emoji)
        avatar.setObjectName("AvatarLabel")
        avatar.setAlignment(Qt.AlignmentFlag.AlignCenter)
        avatar.setFixedSize(32, 32)

        font = QFont()
        font.setPointSize(14)
        avatar.setFont(font)
        return avatar

    # ── 公开接口 ─────────────────────────────────────────────

    def setText(self, text: str):
        """
        更新气泡文案（不重启动画）。
        也可用于 loading 气泡切换文案，如"执行中..."→"思考中..."。
        """
        self._base_text = text
        if self._label:
            if self.role == "loading" and self._dot_timer and self._dot_timer.isActive():
                # 保持动画：只更新基础文案，动画帧在 _tick 里自动刷新
                pass
            else:
                self._label.setText(text)

    def start_dots(self):
        """启动动态省略号动画（每 450ms 更新一帧）"""
        if self._dot_timer is not None:
            return
        self._dot_idx   = 0
        self._dot_timer = QTimer(self)
        self._dot_timer.setInterval(450)
        self._dot_timer.timeout.connect(self._tick)
        self._dot_timer.start()

    def stop_dots(self):
        """停止动态省略号动画"""
        if self._dot_timer:
            self._dot_timer.stop()
            self._dot_timer.deleteLater()
            self._dot_timer = None

    def _tick(self):
        """动画帧：循环更新省略号"""
        if self._label:
            self._dot_idx = (self._dot_idx + 1) % len(_DOT_FRAMES)
            self._label.setText(self._base_text + _DOT_FRAMES[self._dot_idx])
