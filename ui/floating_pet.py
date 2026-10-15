"""悬浮素材容器：拖动吸附、迷你收纳、状态切换与位置记忆。"""

from collections import OrderedDict
from pathlib import Path

from PySide6.QtCore import QPoint, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QGuiApplication, QPainter, QPen, QPixmap
from PySide6.QtWidgets import QMenu, QWidget

from app.app_context import resource_path
from app.pet_animation import advance_ping_pong, load_animation
from ui.brand import BRAND


class FloatingPetWindow(QWidget):
    open_requested = Signal()
    settings_requested = Signal()
    sleep_requested = Signal()
    wake_requested = Signal()
    quit_requested = Signal()
    skin_requested = Signal(str)
    position_changed = Signal(int, int)
    hidden_requested = Signal()

    def __init__(self, config):
        super().__init__()
        self.config = config
        self.state = "idle"
        self.drag = None
        self.moved = False
        self.collapsed = False
        self.expanded_pos = QPoint()
        self.image_cache = {}
        self.animation_cache = OrderedDict()
        self.animation_frames = []
        self.animation_clip = None
        self.animation_sets = {}
        self.animation_index = 0
        self.animation_direction = 1
        self.animation_timer = QTimer(self)
        self.animation_timer.setSingleShot(True)
        self.animation_timer.timeout.connect(self._advance_animation)
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setMouseTracking(True)
        self.setToolTip("点击打开元宝 · 拖动移动 · 右键更多操作")
        self.fade_timer = QTimer(self)
        self.fade_timer.setSingleShot(True)
        self.fade_timer.timeout.connect(self._fade)
        self.apply_config(config)

    def apply_config(self, config):
        self.config = config
        self.image_cache.clear()
        self.animation_cache.clear()
        self.animation_timer.stop()
        self.animation_index = 0
        self.animation_direction = 1
        self.animation_sets.clear()
        self.animation_clip = None
        self.animation_frames = []
        self.collapsed = False
        self.setFixedSize(config.pet_size, config.pet_size)
        self.setWindowOpacity(config.pet_opacity)
        screen = (
            QGuiApplication.screenAt(QPoint(config.pet_x, config.pet_y))
            or QGuiApplication.primaryScreen()
        )
        if screen:
            area = screen.availableGeometry()
            x = config.pet_x if config.pet_x >= 0 else area.right() - self.width() - 36
            y = config.pet_y if config.pet_y >= 0 else area.bottom() - self.height() - 36
            self.move(
                max(area.left(), min(x, area.right() - self.width())),
                max(area.top(), min(y, area.bottom() - self.height())),
            )
        if config.pet_visible:
            self.show()
        else:
            self.hide()
        self.set_pet_state(self.state)

    def set_pet_state(self, state):
        if state != self.state:
            self.animation_timer.stop()
            self.animation_index = 0
            self.animation_direction = 1
        self.state = state
        if state not in self.animation_sets:
            self.animation_sets[state] = (
                load_animation(Path(resource_path("assets/pet/default")), state)
                if self.config.pet_skin == "default" else None
            )
        self.animation_clip = self.animation_sets[state]
        self.animation_frames = self.animation_clip.frames if self.animation_clip else []
        self._sync_animation()
        self.update()

    def _sync_animation(self):
        if (
            self.animation_clip
            and self.animation_clip.animated
            and self.isVisible()
            and not self.collapsed
            and len(self.animation_frames) > 1
        ):
            if not self.animation_timer.isActive():
                self.animation_timer.start(self.animation_clip.delay_ms(self.animation_index))
        else:
            self.animation_timer.stop()

    def _advance_animation(self):
        if (
            not self.animation_clip or not self.animation_clip.animated
            or not self.isVisible() or self.collapsed
        ):
            return
        self.animation_index, self.animation_direction = advance_ping_pong(
            self.animation_index, self.animation_direction, len(self.animation_frames)
        )
        self.update()
        self._sync_animation()

    def _animation_image(self):
        if not self.animation_frames:
            return None
        key = (self.state, self.animation_index, self.devicePixelRatioF())
        if key not in self.animation_cache:
            image = QPixmap(str(self.animation_frames[self.animation_index]))
            if image.isNull():
                self.animation_timer.stop()
                self.animation_frames = []
                self.animation_clip = None
                self.animation_sets[self.state] = None
                return None
            pixels = max(1, round(self.config.pet_size * self.devicePixelRatioF()))
            image = image.scaled(
                pixels, pixels, Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
            image.setDevicePixelRatio(self.devicePixelRatioF())
            self.animation_cache[key] = image
            if len(self.animation_cache) > 16:
                self.animation_cache.popitem(last=False)
        self.animation_cache.move_to_end(key)
        return self.animation_cache[key]

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        if self.collapsed:
            painter.setBrush(QColor(BRAND["teal"]))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawRoundedRect(QRectF(2, 2, 30, 42), 14, 14)
            painter.setPen(QColor(BRAND["cream"]))
            painter.drawText(QRectF(2, 2, 30, 42), Qt.AlignmentFlag.AlignCenter, "元")
            return
        # 用户自带皮肤按状态懒加载；缺图时显示占位标记。
        skin = self.config.pet_skin
        key = (skin, self.state)
        if key not in self.image_cache:
            path = Path(resource_path(f"assets/pet/{skin}/{self.state}.png"))
            if not path.is_file():
                path = Path(resource_path(f"assets/pet/default/{self.state}.png"))
            if path.is_file():
                # 只缓存显示所需尺寸，避免6张高分辨率PNG常驻数十MB。
                image = QPixmap(str(path))
                pixels = max(1, round(self.config.pet_size * self.devicePixelRatioF()))
                image = image.scaled(
                    pixels,
                    pixels,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
                image.setDevicePixelRatio(self.devicePixelRatioF())
                self.image_cache[key] = image
            else:
                self.image_cache[key] = None
        image = self._animation_image() or self.image_cache[key]
        if image and not image.isNull():
            image_size = image.deviceIndependentSize()
            x = (self.width() - image_size.width()) / 2
            y = (self.height() - image_size.height()) / 2
            painter.drawPixmap(
                QRectF(x, y, image_size.width(), image_size.height()), image, QRectF(image.rect())
            )
            return
        # 素材由用户后续准备，当前只显示可操作的占位窗口。
        painter.setPen(QPen(QColor(BRAND["teal"]), 1, Qt.PenStyle.DashLine))
        painter.setBrush(QColor(245, 249, 246, 200))
        painter.drawRoundedRect(QRectF(5, 5, self.width() - 10, self.height() - 10), 12, 12)
        painter.setPen(QColor(BRAND["teal"]))
        label = {
            "idle": "待机",
            "thinking": "思考",
            "listening": "聆听",
            "speaking": "播报",
            "working": "执行",
            "sleep": "休眠",
        }.get(self.state, self.state)
        painter.drawText(
            self.rect(), Qt.AlignmentFlag.AlignCenter, "元宝 · " + label + "\n素材待添加"
        )

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.drag = event.globalPosition().toPoint() - self.pos()
            self.moved = False

    def mouseMoveEvent(self, event):
        if self.drag is not None and event.buttons() & Qt.MouseButton.LeftButton:
            self.moved = True
            self.move(event.globalPosition().toPoint() - self.drag)

    def mouseReleaseEvent(self, event):
        if event.button() != Qt.MouseButton.LeftButton:
            return
        self.drag = None
        if self.moved:
            screen = (
                QGuiApplication.screenAt(self.frameGeometry().center())
                or QGuiApplication.primaryScreen()
            )
            if screen:
                area = screen.availableGeometry()
                x = max(area.left(), min(self.x(), area.right() - self.width() + 1))
                y = max(area.top(), min(self.y(), area.bottom() - self.height() + 1))
                edge = abs(x - area.left()) < 24 or abs(x + self.width() - area.right()) < 24
                if edge:
                    x = (
                        area.left()
                        if abs(x - area.left()) < 24
                        else area.right() - self.width() + 1
                    )
                self.move(x, y)
                self.expanded_pos = self.pos()
                self.position_changed.emit(x, y)
                if edge and self.config.edge_collapse:
                    self.collapsed = True
                    self._sync_animation()
                    self.setFixedSize(34, 46)
                    self.move(area.left() if x == area.left() else area.right() - 33, y)
        else:
            if self.collapsed:
                self._expand()
            self.wake_requested.emit()
            self.open_requested.emit()

    def _expand(self):
        self.collapsed = False
        self.setFixedSize(self.config.pet_size, self.config.pet_size)
        self.move(self.expanded_pos)
        self._sync_animation()
        self.update()

    def enterEvent(self, event):
        self.fade_timer.stop()
        self.setWindowOpacity(self.config.pet_opacity)
        super().enterEvent(event)

    def leaveEvent(self, event):
        self.fade_timer.start(3000)
        super().leaveEvent(event)

    def _fade(self):
        self.setWindowOpacity(max(0.3, self.config.pet_opacity * 0.65))

    def showEvent(self, event):
        super().showEvent(event)
        self.set_pet_state(self.state)

    def hideEvent(self, event):
        self.fade_timer.stop()
        self.animation_timer.stop()
        super().hideEvent(event)

    def contextMenuEvent(self, event):
        menu = QMenu(self)
        menu.addAction("打开对话", self.open_requested.emit)
        menu.addAction("设置", self.settings_requested.emit)
        skins = menu.addMenu("切换皮肤")
        for key, title in (("default", "薄荷"), ("peach", "蜜桃"), ("night", "夜蓝")):
            skins.addAction(title, lambda value=key: self.skin_requested.emit(value))
        menu.addAction(
            "恢复工作" if self.state == "sleep" else "进入休眠",
            self.wake_requested.emit if self.state == "sleep" else self.sleep_requested.emit,
        )
        menu.addAction("隐藏形象", self.hidden_requested.emit)
        menu.addSeparator()
        menu.addAction("退出", self.quit_requested.emit)
        menu.exec(event.globalPos())
