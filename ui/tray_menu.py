"""系统托盘入口，退出交给控制器执行完整资源清理。"""

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtGui import QColor, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import QMenu, QSystemTrayIcon

from app.app_context import resource_path
from ui.brand import BRAND


def app_icon():
    for filename in ("app_icon.ico", "app_icon.png"):
        icon = QIcon(resource_path("assets/icons/" + filename))
        if not icon.isNull():
            return icon
    pixmap = QPixmap(64, 64)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setBrush(QColor(BRAND["teal"]))
    painter.setPen(Qt.PenStyle.NoPen)
    painter.drawRoundedRect(2, 2, 60, 60, 18, 18)
    painter.setBrush(QColor(BRAND["cream"]))
    painter.drawEllipse(12, 19, 40, 34)
    painter.setBrush(QColor(BRAND["gold"]))
    painter.drawEllipse(23, 31, 4, 7)
    painter.drawEllipse(38, 31, 4, 7)
    painter.end()
    return QIcon(pixmap)


class TrayMenu(QObject):
    open_requested = Signal()
    settings_requested = Signal()
    voice_requested = Signal()
    pet_toggled = Signal(bool)
    mute_toggled = Signal(bool)
    sleep_requested = Signal()
    wake_requested = Signal()
    quit_requested = Signal()

    def __init__(self, config, parent=None):
        super().__init__(parent)
        self.tray = QSystemTrayIcon(app_icon(), self)
        self.tray.setToolTip("元宝桌面助手")
        menu = QMenu()
        self.menu = menu
        menu.addAction("打开对话", self.open_requested.emit)
        menu.addAction("语音输入", self.voice_requested.emit)
        menu.addAction("设置", self.settings_requested.emit)
        menu.addSeparator()
        self.pet_action = menu.addAction("显示桌面形象")
        self.pet_action.setCheckable(True)
        self.pet_action.setChecked(config.ui.pet_visible)
        self.pet_action.toggled.connect(self.pet_toggled.emit)
        self.mute_action = menu.addAction("静音模式（关闭播报与唤醒）")
        self.mute_action.setCheckable(True)
        self.mute_action.toggled.connect(self.mute_toggled.emit)
        menu.addSeparator()
        menu.addAction("进入休眠", self.sleep_requested.emit)
        menu.addAction("恢复工作", self.wake_requested.emit)
        menu.addSeparator()
        menu.addAction("退出程序", self.quit_requested.emit)
        self.tray.setContextMenu(menu)
        self.tray.activated.connect(self._activate)
        self.tray.show()

    def _activate(self, reason):
        if reason in (
            QSystemTrayIcon.ActivationReason.Trigger,
            QSystemTrayIcon.ActivationReason.DoubleClick,
        ):
            self.open_requested.emit()

    def notify(self, title, message):
        self.tray.showMessage(title, message, QSystemTrayIcon.MessageIcon.Information, 5000)

    def hide(self):
        self.tray.hide()
