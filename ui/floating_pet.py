"""
悬浮宠物窗口模块
创建一个无边框、透明背景、始终置顶的桌面悬浮窗口。

特性：
- 显示宠物图片（assets/pet/idle.png），图片不存在时显示占位区域
- 鼠标左键拖拽移动位置
- 双击触发外部回调（预留聊天窗口入口）
- set_pet_state(state) 切换四种状态图：idle / thinking / speaking / sleep
"""

import os
from typing import Optional, Callable

from PySide6.QtWidgets import QWidget, QVBoxLayout
from PySide6.QtCore import Qt, QPoint
from PySide6.QtGui import QPixmap, QPainter, QColor, QFont, QPen, QBrush

from app.app_context import resource_path
from app.logger import setup_logger

logger = setup_logger()

# 宠物窗口默认尺寸
PET_WIDTH = 120
PET_HEIGHT = 120

# 状态名 → 图片文件名映射
STATE_IMAGE_MAP: dict[str, str] = {
    "idle":     "idle.png",
    "thinking": "thinking.png",
    "speaking": "speaking.png",
    "sleep":    "sleep.png",
}


class _PetCanvas(QWidget):
    """
    宠物图片画布。
    负责渲染宠物图片或占位图，不处理任何交互逻辑。
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(PET_WIDTH, PET_HEIGHT)
        self._pixmap: Optional[QPixmap] = None
        self._placeholder_text = "AI助手"

    def set_pixmap(self, pixmap: Optional[QPixmap]):
        """更新宠物图片，传 None 时显示占位图"""
        self._pixmap = pixmap
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        if self._pixmap and not self._pixmap.isNull():
            # 等比缩放到画布尺寸，居中绘制
            scaled = self._pixmap.scaled(
                self.width(), self.height(),
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
            x = (self.width() - scaled.width()) // 2
            y = (self.height() - scaled.height()) // 2
            painter.drawPixmap(x, y, scaled)
        else:
            self._draw_placeholder(painter)

    def _draw_placeholder(self, painter: QPainter):
        """图片缺失时绘制圆角浅色占位区域"""
        rect = self.rect().adjusted(4, 4, -4, -4)

        # 圆角背景
        painter.setBrush(QBrush(QColor(230, 240, 255, 220)))
        painter.setPen(QPen(QColor(180, 200, 240, 180), 2))
        painter.drawRoundedRect(rect, 20, 20)

        # 中央文字
        painter.setPen(QColor(80, 120, 200))
        font = QFont()
        font.setPointSize(11)
        font.setBold(True)
        painter.setFont(font)
        painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, self._placeholder_text)


class FloatingPetWindow(QWidget):
    """
    无边框透明悬浮宠物窗口。

    使用方式：
        pet = FloatingPetWindow()
        pet.set_open_chat_callback(lambda: chat_window.show())
        pet.show()
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self._drag_start_pos: Optional[QPoint] = None
        self._open_chat_callback: Optional[Callable] = None
        self._click_callback: Optional[Callable] = None   # 单击回调（用于恢复 active）
        self._current_state: str = "idle"

        self._init_window()
        self._init_ui()
        self._load_state_image("idle")

    # ── 窗口初始化 ───────────────────────────────────────────

    def _init_window(self):
        """配置无边框透明置顶窗口属性"""
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint        # 无边框
            | Qt.WindowType.WindowStaysOnTopHint     # 始终置顶
            | Qt.WindowType.Tool                     # 不在任务栏显示
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setFixedSize(PET_WIDTH, PET_HEIGHT)

        # 默认出现在屏幕右下角附近
        self._set_default_position()

    def _set_default_position(self):
        """将窗口定位到屏幕右下角（距边缘 40px）"""
        from PySide6.QtGui import QGuiApplication
        screen = QGuiApplication.primaryScreen()
        if screen:
            geo = screen.availableGeometry()
            x = geo.right() - PET_WIDTH - 40
            y = geo.bottom() - PET_HEIGHT - 40
            self.move(x, y)

    def _init_ui(self):
        """构建内部布局（仅包含画布）"""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self._canvas = _PetCanvas()
        layout.addWidget(self._canvas)

    # ── 公开接口 ─────────────────────────────────────────────

    def set_open_chat_callback(self, callback: Callable):
        """
        注册双击打开聊天窗口的回调函数。
        callback 无参数，直接调用即可。
        """
        self._open_chat_callback = callback

    def set_click_callback(self, callback: Callable):
        """
        注册单击宠物的回调函数（用于通知 StateManager 恢复 active）。
        callback 无参数，直接调用即可。
        """
        self._click_callback = callback

    def set_pet_state(self, state: str):
        """
        切换宠物状态图片。
        state: "idle" | "thinking" | "speaking" | "sleep"
        未知 state 会记录警告并保持当前图片。
        """
        if state not in STATE_IMAGE_MAP:
            logger.warning(f"未知宠物状态：{state}，有效值：{list(STATE_IMAGE_MAP.keys())}")
            return
        if state == self._current_state:
            return
        self._current_state = state
        self._load_state_image(state)

    # ── 图片加载 ──────────────────────────────────────────────

    def _load_state_image(self, state: str):
        """根据状态加载对应图片，失败时静默回退到占位图"""
        filename = STATE_IMAGE_MAP.get(state, "idle.png")
        img_path = resource_path(os.path.join("assets", "pet", filename))

        if os.path.exists(img_path):
            pixmap = QPixmap(img_path)
            if not pixmap.isNull():
                self._canvas.set_pixmap(pixmap)
                logger.debug(f"宠物图片已加载：{img_path}")
                return

        # 图片不存在或加载失败 → 占位图
        logger.debug(f"宠物图片不存在，使用占位图：{img_path}")
        self._canvas.set_pixmap(None)

    # ── 鼠标事件：拖拽 + 双击 ─────────────────────────────────

    def mousePressEvent(self, event):
        """左键按下时记录拖拽起始位置"""
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_start_pos = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        """左键拖动时移动窗口"""
        if event.buttons() & Qt.MouseButton.LeftButton and self._drag_start_pos is not None:
            new_pos = event.globalPosition().toPoint() - self._drag_start_pos
            self.move(new_pos)
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        """左键释放时清除拖拽状态，并触发单击回调（通知 StateManager 恢复 active）"""
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_start_pos = None
            # 单击宠物 → 通知外部恢复 active（不管是否在拖拽中都触发，main.py 中去重）
            if self._click_callback is not None:
                try:
                    self._click_callback()
                except Exception as e:
                    logger.debug(f"单击宠物回调异常：{e}")
        super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event):
        """双击时触发聊天窗口回调（如已注册）"""
        if event.button() == Qt.MouseButton.LeftButton:
            if self._open_chat_callback is not None:
                logger.debug("双击宠物，触发聊天窗口回调")
                self._open_chat_callback()
            else:
                logger.debug("双击宠物，聊天窗口回调未注册")
        super().mouseDoubleClickEvent(event)
