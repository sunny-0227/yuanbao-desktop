"""
待办到点提醒弹窗模块

职责：
- 接收一条待办 dict，以小型桌面弹窗形式展示提醒内容
- 弹窗置顶但不强制抢占焦点，不阻塞用户操作
- 点击"知道了"或关闭按钮后隐藏窗口，不退出主程序
- 风格简洁，适配深色 / 浅色主题（默认深色）

使用方式：
    todo = {"id": 1, "title": "喝水", "remind_time": "2026-07-06 18:30"}
    popup = ReminderPopup(todo)
    popup.show_popup()   # 自动定位到屏幕右下角
"""

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton,
)
from PySide6.QtCore import Qt, QPropertyAnimation, QEasingCurve, QPoint, QRect
from PySide6.QtGui import QFont, QGuiApplication

from app.logger import setup_logger

logger = setup_logger()

# 弹窗固定尺寸
_POPUP_WIDTH  = 300
_POPUP_HEIGHT = 150

# 距屏幕边缘的间距（像素）
_MARGIN = 20

# 淡入动画时长（毫秒）
_FADE_IN_MS = 180


class ReminderPopup(QWidget):
    """
    待办到点提醒弹窗。

    特性：
    - 无边框、圆角、置顶，固定显示于屏幕右下角
    - 不强制抢占输入焦点（Qt.WindowDoesNotAcceptFocus）
    - 淡入动画，关闭时直接隐藏，不销毁对象（可复用）
    - 关闭窗口不触发 QApplication.quit()
    """

    def __init__(self, todo: dict, theme: str = "dark", parent=None):
        super().__init__(parent)
        self._todo  = todo
        self._theme = theme
        self._anim: QPropertyAnimation | None = None  # 淡入动画引用

        self._init_window()
        self._build_ui()
        self._apply_style()

    # ── 窗口初始化 ────────────────────────────────────────────

    def _init_window(self):
        """设置无边框、置顶、不抢焦点的窗口属性"""
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint        # 无边框
            | Qt.WindowType.WindowStaysOnTopHint     # 置顶（不全屏抢占）
            | Qt.WindowType.Tool                     # 不在任务栏出现
            | Qt.WindowType.WindowDoesNotAcceptFocus # 不抢夺键盘焦点
        )
        # 背景可绘制圆角（透明底）
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setFixedSize(_POPUP_WIDTH, _POPUP_HEIGHT)

    # ── UI 构建 ───────────────────────────────────────────────

    def _build_ui(self):
        """构建弹窗内部布局"""
        # 外层容器：实现圆角背景（通过 objectName 绑定 QSS）
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)

        # 内容卡片
        card = QWidget()
        card.setObjectName("ReminderCard")
        outer.addWidget(card)

        layout = QVBoxLayout(card)
        layout.setContentsMargins(18, 14, 18, 14)
        layout.setSpacing(6)

        # ── 顶部：图标 + 标题 + 时间 ───────────────────────
        header = QHBoxLayout()
        header.setSpacing(6)

        icon_lbl = QLabel("⏰")
        icon_lbl.setObjectName("ReminderIcon")
        font_icon = QFont()
        font_icon.setPointSize(18)
        icon_lbl.setFont(font_icon)
        icon_lbl.setFixedWidth(30)
        header.addWidget(icon_lbl)

        header_right = QVBoxLayout()
        header_right.setSpacing(2)

        title_lbl = QLabel("提醒")
        title_lbl.setObjectName("ReminderTitle")
        font_title = QFont()
        font_title.setPointSize(12)
        font_title.setBold(True)
        title_lbl.setFont(font_title)
        header_right.addWidget(title_lbl)

        # 提醒时间（副标题）
        remind_time = self._todo.get("remind_time", "")
        if remind_time:
            time_lbl = QLabel(remind_time)
            time_lbl.setObjectName("ReminderTime")
            font_time = QFont()
            font_time.setPointSize(10)
            time_lbl.setFont(font_time)
            header_right.addWidget(time_lbl)

        header.addLayout(header_right)
        header.addStretch()
        layout.addLayout(header)

        # ── 提醒内容 ──────────────────────────────────────
        title_text = self._todo.get("title", "（无内容）")
        content_lbl = QLabel(title_text)
        content_lbl.setObjectName("ReminderContent")
        content_lbl.setWordWrap(True)
        font_content = QFont()
        font_content.setPointSize(12)
        content_lbl.setFont(font_content)
        # 限制最多显示两行，超出省略
        content_lbl.setMaximumHeight(50)
        layout.addWidget(content_lbl)

        layout.addStretch()

        # ── 底部："知道了"按钮 ───────────────────────────
        btn_row = QHBoxLayout()
        btn_row.addStretch()

        ok_btn = QPushButton("知道了")
        ok_btn.setObjectName("ReminderOkButton")
        ok_btn.setFixedSize(80, 30)
        ok_btn.clicked.connect(self._on_ok)
        btn_row.addWidget(ok_btn)

        layout.addLayout(btn_row)

    def _apply_style(self):
        """根据主题设置弹窗样式（QSS 内联，不依赖全局样式表）"""
        if self._theme == "light":
            self.setStyleSheet(_LIGHT_POPUP_QSS)
        else:
            self.setStyleSheet(_DARK_POPUP_QSS)

    # ── 公开接口 ──────────────────────────────────────────────

    def show_popup(self):
        """
        将弹窗定位到屏幕右下角并显示，带淡入动画。
        可被外部重复调用来更新内容（先调 update_todo 再调本方法）。
        """
        self._position_bottom_right()
        self.setWindowOpacity(0.0)
        self.show()
        self._start_fade_in()
        logger.debug(
            f"提醒弹窗已显示：#{self._todo.get('id')} {self._todo.get('title')!r}"
        )

    def update_todo(self, todo: dict):
        """
        更新弹窗内容（复用同一个实例展示新的提醒）。
        调用后需再调用 show_popup() 才会显示。
        """
        self._todo = todo
        # 重新构建 UI
        old_layout = self.layout()
        if old_layout:
            # 清空旧布局中的所有子部件
            while old_layout.count():
                item = old_layout.takeAt(0)
                if item.widget():
                    item.widget().deleteLater()
        self._build_ui()
        self._apply_style()

    # ── 私有方法 ──────────────────────────────────────────────

    def _position_bottom_right(self):
        """将弹窗定位到主屏幕右下角"""
        screen = QGuiApplication.primaryScreen()
        if screen:
            avail: QRect = screen.availableGeometry()
            x = avail.right()  - _POPUP_WIDTH  - _MARGIN
            y = avail.bottom() - _POPUP_HEIGHT - _MARGIN
            self.move(QPoint(x, y))

    def _start_fade_in(self):
        """启动淡入动画（opacity 0 → 1）"""
        self._anim = QPropertyAnimation(self, b"windowOpacity", self)
        self._anim.setDuration(_FADE_IN_MS)
        self._anim.setStartValue(0.0)
        self._anim.setEndValue(1.0)
        self._anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._anim.start()

    def _on_ok(self):
        """点击"知道了"后隐藏弹窗，不退出主程序"""
        logger.debug(f"提醒弹窗已确认：#{self._todo.get('id')}")
        self.hide()

    def closeEvent(self, event):
        """拦截关闭事件：改为隐藏，不销毁，不退出主程序"""
        event.ignore()
        self.hide()


# ── 内联 QSS 样式 ─────────────────────────────────────────────

_DARK_POPUP_QSS = """
/* 卡片背景：深色，圆角，带细边框 */
#ReminderCard {
    background-color: #24273a;
    border: 1px solid #414560;
    border-radius: 14px;
}

/* 钟形图标 */
#ReminderIcon {
    color: #f5a97f;
    background: transparent;
}

/* "提醒"标题 */
#ReminderTitle {
    color: #cad3f5;
    background: transparent;
}

/* 时间副标题 */
#ReminderTime {
    color: #8087a2;
    background: transparent;
}

/* 提醒内容正文 */
#ReminderContent {
    color: #cad3f5;
    background: transparent;
}

/* "知道了"按钮 */
#ReminderOkButton {
    background-color: #8aadf4;
    color: #1e2030;
    border: none;
    border-radius: 8px;
    font-size: 13px;
    font-weight: bold;
}
#ReminderOkButton:hover {
    background-color: #7dc4e4;
}
#ReminderOkButton:pressed {
    background-color: #5b7fcb;
}
"""

_LIGHT_POPUP_QSS = """
/* 卡片背景：浅色，圆角，带阴影感边框 */
#ReminderCard {
    background-color: #ffffff;
    border: 1px solid #ccd0da;
    border-radius: 14px;
}

#ReminderIcon {
    color: #fe640b;
    background: transparent;
}

#ReminderTitle {
    color: #4c4f69;
    background: transparent;
}

#ReminderTime {
    color: #9ca0b0;
    background: transparent;
}

#ReminderContent {
    color: #4c4f69;
    background: transparent;
}

#ReminderOkButton {
    background-color: #1e66f5;
    color: #ffffff;
    border: none;
    border-radius: 8px;
    font-size: 13px;
    font-weight: bold;
}
#ReminderOkButton:hover {
    background-color: #5277d4;
}
#ReminderOkButton:pressed {
    background-color: #1453c2;
}
"""
