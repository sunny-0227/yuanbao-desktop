"""
主窗口模块
负责整体布局：顶部标题栏 + 聊天区域 + 底部输入栏
"""

import os
from PySide6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QSizePolicy
)
from PySide6.QtCore import Qt, QSize
from PySide6.QtGui import QIcon, QFont

from app.app_context import resource_path
from app.config import AppConfig
from ui.chat_widget import ChatWidget
from ui.input_bar import InputBar
from ui.style import load_stylesheet


class MainWindow(QMainWindow):
    """
    应用主窗口。
    布局结构：
        ┌─────────────────────────┐
        │  标题栏（拖动区域）       │
        ├─────────────────────────┤
        │  聊天消息列表（可滚动）   │
        ├─────────────────────────┤
        │  底部输入栏              │
        └─────────────────────────┘
    """

    def __init__(self, config: AppConfig, parent=None):
        super().__init__(parent)
        self.config = config
        self._init_window()
        self._init_ui()
        self._apply_style()

    def _init_window(self):
        """配置窗口基本属性"""
        self.setWindowTitle("轻量化桌面AI虚拟助手")
        self.resize(self.config.ui.window_width, self.config.ui.window_height)
        self.setMinimumSize(360, 500)

        # 置顶（根据配置）
        if self.config.ui.always_on_top:
            self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)

        # 设置图标
        icon_path = resource_path(os.path.join("assets", "icons", "app_icon.ico"))
        if os.path.exists(icon_path):
            self.setWindowIcon(QIcon(icon_path))

    def _init_ui(self):
        """构建主界面布局"""
        central = QWidget()
        self.setCentralWidget(central)

        root_layout = QVBoxLayout(central)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)

        # ── 标题栏 ──
        title_bar = self._build_title_bar()
        root_layout.addWidget(title_bar)

        # ── 聊天消息区 ──
        self.chat_widget = ChatWidget(config=self.config)
        root_layout.addWidget(self.chat_widget, stretch=1)

        # ── 底部输入栏 ──
        self.input_bar = InputBar(config=self.config)
        root_layout.addWidget(self.input_bar)

        # 连接信号：用户发送消息 → 聊天组件处理
        self.input_bar.message_sent.connect(self.chat_widget.on_user_message)

    def _build_title_bar(self) -> QWidget:
        """创建自定义标题栏"""
        bar = QWidget()
        bar.setObjectName("TitleBar")
        bar.setFixedHeight(48)

        layout = QHBoxLayout(bar)
        layout.setContentsMargins(16, 0, 8, 0)
        layout.setSpacing(8)

        # 应用名称标签
        title_label = QLabel("🤖 AI 助手")
        title_label.setObjectName("TitleLabel")
        font = QFont()
        font.setPointSize(13)
        font.setBold(True)
        title_label.setFont(font)

        layout.addWidget(title_label)
        layout.addStretch()

        # 清空聊天按钮
        clear_btn = QPushButton("清空")
        clear_btn.setObjectName("ClearButton")
        clear_btn.setFixedSize(QSize(52, 28))
        clear_btn.setToolTip("清空聊天记录")
        clear_btn.clicked.connect(self._on_clear_chat)
        layout.addWidget(clear_btn)

        return bar

    def _apply_style(self):
        """加载并应用 QSS 样式"""
        qss = load_stylesheet(self.config.ui.theme)
        self.setStyleSheet(qss)

    def _on_clear_chat(self):
        """清空聊天区域"""
        self.chat_widget.clear_messages()
