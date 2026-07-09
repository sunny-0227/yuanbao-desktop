"""
系统托盘模块
使用 QSystemTrayIcon 在系统托盘区域显示图标和右键菜单。

职责：
- 管理托盘图标的创建与显示
- 提供右键菜单及各菜单项的点击事件
- 通过回调与外部（FloatingPetWindow、QApplication）解耦
- "进入休眠"/"恢复工作"通过 StateManager 统一控制状态

不在本模块实现：AI 调用、系统指令、任何业务逻辑。
"""

import os
import json
from typing import Callable, Optional, TYPE_CHECKING

from PySide6.QtWidgets import QSystemTrayIcon, QMenu, QApplication
from PySide6.QtGui import QIcon, QPixmap, QPainter, QColor, QBrush
from PySide6.QtCore import Qt, QSize

from app.app_context import resource_path
from app.logger import setup_logger

if TYPE_CHECKING:
    from app.state_manager import StateManager

logger = setup_logger()

# 托盘图标文件名（相对于 assets/icons/）
TRAY_ICON_FILENAME = "app_icon.ico"


def _make_fallback_icon(size: int = 32) -> QIcon:
    """
    当图标文件不存在时，用代码绘制一个简单的圆形占位图标。
    纯色圆形可以保证在任何系统主题下都清晰可见。
    """
    pixmap = QPixmap(QSize(size, size))
    pixmap.fill(Qt.GlobalColor.transparent)

    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setBrush(QBrush(QColor(100, 160, 255)))
    painter.setPen(Qt.PenStyle.NoPen)
    painter.drawEllipse(2, 2, size - 4, size - 4)
    painter.end()

    return QIcon(pixmap)


class TrayMenu:
    """
    系统托盘菜单管理器。

    "进入休眠"/"恢复工作"通过 set_state_manager() 注入 StateManager 控制，
    其余菜单项（显示/隐藏助手、打开对话）通过 set_callbacks() 注入回调。

    使用方式：
        tray = TrayMenu()
        tray.set_state_manager(state_manager)
        tray.set_callbacks(
            on_open_chat=...,
            on_show_pet=...,
            on_hide_pet=...,
        )
        tray.show()
    """

    def __init__(self, config=None):
        self._tray = QSystemTrayIcon()
        self._config = config
        self._state_manager: Optional["StateManager"] = None
        self._on_open_chat:         Optional[Callable] = None
        self._on_show_pet:          Optional[Callable] = None
        self._on_hide_pet:          Optional[Callable] = None
        self._on_open_settings:     Optional[Callable] = None
        self._on_voice_input:       Optional[Callable] = None   # 触发语音输入

        self._init_icon()
        self._init_menu()

    # ── 初始化 ───────────────────────────────────────────────

    def _init_icon(self):
        """加载托盘图标，不存在时使用绘制的占位图标"""
        icon_path = resource_path(os.path.join("assets", "icons", TRAY_ICON_FILENAME))
        if os.path.exists(icon_path):
            icon = QIcon(icon_path)
            if not icon.isNull():
                self._tray.setIcon(icon)
                logger.debug(f"托盘图标已加载：{icon_path}")
                return

        # 文件不存在或加载失败，使用绘制的占位图标
        logger.debug(f"托盘图标不存在，使用占位图标：{icon_path}")
        self._tray.setIcon(_make_fallback_icon())

    def _init_menu(self):
        """构建右键菜单"""
        menu = QMenu()

        # ── 菜单项定义 ──────────────────────────────────────
        self._act_open_chat   = menu.addAction("打开对话")
        self._act_voice_input = menu.addAction("🎤 语音对话")
        self._act_settings    = menu.addAction("打开设置")
        menu.addSeparator()

        self._act_show = menu.addAction("显示助手")
        self._act_hide = menu.addAction("隐藏助手")
        menu.addSeparator()

        # 语音播报开关（Checkable）
        self._act_tts_toggle = menu.addAction("🔊 语音播报")
        self._act_tts_toggle.setCheckable(True)
        tts_on = True
        if self._config and hasattr(self._config, "voice"):
            tts_on = self._config.voice.tts_enabled
        self._act_tts_toggle.setChecked(tts_on)

        menu.addSeparator()

        self._act_sleep = menu.addAction("进入休眠")
        self._act_wake  = menu.addAction("恢复工作")
        menu.addSeparator()

        self._act_quit = menu.addAction("退出程序")

        # ── 连接信号 ────────────────────────────────────────
        self._act_open_chat.triggered.connect(self._handle_open_chat)
        self._act_voice_input.triggered.connect(self._handle_voice_input)
        self._act_settings.triggered.connect(self._handle_open_settings)
        self._act_show.triggered.connect(self._handle_show_pet)
        self._act_hide.triggered.connect(self._handle_hide_pet)
        self._act_tts_toggle.triggered.connect(self._handle_tts_toggle)
        self._act_sleep.triggered.connect(self._handle_sleep)
        self._act_wake.triggered.connect(self._handle_wake)
        self._act_quit.triggered.connect(self._handle_quit)

        self._tray.setContextMenu(menu)
        app_name = self._config.app_name if self._config else "图图助手"
        self._tray.setToolTip(app_name)

        # 单击托盘图标也弹出菜单（Windows 默认左键单击行为）
        self._tray.activated.connect(self._on_tray_activated)

    # ── 公开接口 ─────────────────────────────────────────────

    def set_state_manager(self, manager: "StateManager"):
        """注入 StateManager，休眠/恢复工作通过它统一控制"""
        self._state_manager = manager

    def set_callbacks(
        self,
        on_open_chat:     Optional[Callable] = None,
        on_show_pet:      Optional[Callable] = None,
        on_hide_pet:      Optional[Callable] = None,
        on_open_settings: Optional[Callable] = None,
        on_voice_input:   Optional[Callable] = None,
    ):
        """
        注册菜单项回调函数，全部可选。
        on_voice_input：点击「语音对话」时触发（通常委托给 ChatWindow.trigger_voice_input）
        """
        self._on_open_chat     = on_open_chat
        self._on_show_pet      = on_show_pet
        self._on_hide_pet      = on_hide_pet
        self._on_open_settings = on_open_settings
        self._on_voice_input   = on_voice_input

    def show(self):
        """显示托盘图标"""
        self._tray.show()
        logger.debug("系统托盘已显示")

    def hide(self):
        """隐藏托盘图标"""
        self._tray.hide()

    # ── 内部事件处理 ──────────────────────────────────────────

    def _on_tray_activated(self, reason: QSystemTrayIcon.ActivationReason):
        """单击托盘图标时弹出菜单（兼容 Windows 单击行为）"""
        if reason == QSystemTrayIcon.ActivationReason.Trigger:
            self._tray.contextMenu().popup(
                self._tray.geometry().center()
            )

    def _invoke(self, name: str, callback: Optional[Callable]):
        """安全调用回调，未注册时只记录 debug 日志"""
        if callback is not None:
            callback()
        else:
            logger.debug(f'托盘菜单："{name}" 回调未注册')

    def _handle_open_chat(self):
        self._invoke("打开对话", self._on_open_chat)

    def _handle_open_settings(self):
        self._invoke("打开设置", self._on_open_settings)

    def _handle_voice_input(self):
        """触发语音对话：先打开聊天窗口再启动录音"""
        self._invoke("语音对话", self._on_voice_input)

    def _handle_tts_toggle(self, checked: bool):
        """切换语音播报开关，并持久化到 config.json"""
        logger.debug(f"托盘菜单：语音播报 → {'开启' if checked else '关闭'}")
        if self._config and hasattr(self._config, "voice"):
            self._config.voice.tts_enabled = checked
        # 持久化到 config.json
        try:
            from app.app_context import resource_path
            cfg_path = resource_path("config.json")
            import json as _json
            if os.path.exists(cfg_path):
                with open(cfg_path, "r", encoding="utf-8") as f:
                    raw = _json.load(f)
            else:
                raw = {}
            raw["tts_enabled"] = checked
            with open(cfg_path, "w", encoding="utf-8") as f:
                _json.dump(raw, f, ensure_ascii=False, indent=2)
            logger.debug(f"tts_enabled={checked} 已写入 config.json")
        except Exception as e:
            logger.warning(f"托盘菜单：写入 tts_enabled 失败：{e}")

    def _handle_show_pet(self):
        self._invoke("显示助手", self._on_show_pet)

    def _handle_hide_pet(self):
        self._invoke("隐藏助手", self._on_hide_pet)

    def _handle_sleep(self):
        """进入休眠：通过 StateManager 统一切换状态"""
        if self._state_manager:
            self._state_manager.set_state("sleep")
            logger.debug("托盘菜单：进入休眠 → StateManager.set_state('sleep')")
        else:
            logger.debug("托盘菜单：StateManager 未注入，进入休眠无效")

    def _handle_wake(self):
        """恢复工作：通过 StateManager 统一切换到 active 状态"""
        if self._state_manager:
            self._state_manager.touch_interaction()   # 同时更新最后交互时间
            logger.debug("托盘菜单：恢复工作 → StateManager.touch_interaction() → active")
        else:
            logger.debug("托盘菜单：StateManager 未注入，恢复工作无效")

    def _handle_quit(self):
        """安全退出：先隐藏托盘图标再退出，避免托盘图标残留"""
        logger.debug("用户点击退出程序")
        self._tray.hide()
        QApplication.quit()

    # ── 公开通知方法 ──────────────────────────────────────────

    def show_sleep_notification(self, message: str = ""):
        """
        在系统托盘气泡中显示通知。
        message 为空时显示默认休眠提示。
        """
        if not self._tray.isSystemTrayAvailable():
            return
        try:
            if message:
                title = "图图助手"
                body  = message
            else:
                title = "检测到高负载"
                body  = "助手已进入休眠模式，点击托盘图标可恢复工作。"
            self._tray.showMessage(
                title, body,
                QSystemTrayIcon.MessageIcon.Information,
                4000,
            )
            logger.debug(f"托盘通知：{body[:40]}")
        except Exception as e:
            logger.warning(f"显示托盘通知失败：{e}")
