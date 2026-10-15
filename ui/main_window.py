"""单一桌面工作台，避免两套聊天窗口和配置来源。"""

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QListWidget,
    QMainWindow,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from ui.chat_window import ChatWindow
from ui.library_panel import LibraryPanel
from ui.settings_window import SettingsWindow
from ui.tray_menu import app_icon


class MainWindow(QMainWindow):
    closed_to_tray = Signal()

    def __init__(self, config):
        super().__init__()
        self.setWindowTitle("元宝桌面助手")
        self.setMinimumSize(840, 560)
        self.resize(max(840, config.ui.window_width), max(560, config.ui.window_height))
        central = QWidget()
        central.setObjectName("Workspace")
        root = QHBoxLayout(central)
        root.setContentsMargins(14, 14, 14, 14)
        root.setSpacing(14)
        side = QVBoxLayout()
        brand = QLabel("元宝\n桌面助手")
        brand.setObjectName("PageTitle")
        avatar = QLabel()
        avatar.setPixmap(app_icon().pixmap(64, 64))
        side.addWidget(avatar)
        side.addWidget(brand)
        badge = QLabel("长毛金虎斑猫")
        badge.setObjectName("BrandBadge")
        side.addWidget(badge)
        self.nav = QListWidget()
        self.nav.setObjectName("Navigation")
        self.nav.setFixedWidth(144)
        self.nav.addItems(["对话", "待办与提醒", "笔记", "设置"])
        self.nav.setCurrentRow(0)
        side.addWidget(self.nav, 1)
        hint = QLabel("关闭窗口后\n仍在托盘运行")
        hint.setObjectName("Hint")
        side.addWidget(hint)
        root.addLayout(side)
        self.stack = QStackedWidget()
        self.chat = ChatWindow()
        self.todos = LibraryPanel("todos")
        self.notes = LibraryPanel("notes")
        self.settings = SettingsWindow(config)
        for panel in (self.chat, self.todos, self.notes, self.settings):
            self.stack.addWidget(panel)
        self.nav.currentRowChanged.connect(self.stack.setCurrentIndex)
        root.addWidget(self.stack, 1)
        self.setCentralWidget(central)
        self.apply_config(config)

    def apply_config(self, config):
        visible = self.isVisible()
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, config.ui.always_on_top)
        self.resize(max(840, config.ui.window_width), max(560, config.ui.window_height))
        if visible:
            self.show()

    def open(self, page=0):
        self.nav.setCurrentRow(page)
        self.show()
        self.raise_()
        self.activateWindow()
        if page == 0:
            self.chat.input.setFocus()

    def closeEvent(self, event):
        event.ignore()
        self.hide()
        self.closed_to_tray.emit()
