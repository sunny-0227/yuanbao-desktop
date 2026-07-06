"""
聊天窗口模块
独立的对话窗口，包含消息展示区、输入栏、发送/清空按钮。

职责：
- 渲染对话历史（用户气泡 + AI 气泡）
- 接收用户输入，经由 LocalCommandExecutor 在后台线程异步执行
- 执行结果通过回调更新 UI，不阻塞主线程
- 打开窗口或发送消息时通知 StateManager 切换为 active

指令分发流程：
    用户输入
      → LocalCommandExecutor.execute(text)          [后台线程]
          → CommandDispatcher.handle(text)
              → CommandRouter.route()               [识别分类]
              ├─ 本地指令命中 → 对应 Service 执行    [quick_app / web_search 等]
              └─ 未命中 → AI 流程
                    → _on_ai_start() 回调           [主线程，切换为"思考中…"]
                    → CacheService 查缓存
                    → AIService.ask_ai()            [30s 超时]
                    → CacheService 写缓存
      → _on_reply(reply) 回调                       [主线程，更新 UI]
"""

from typing import Callable, Optional, TYPE_CHECKING

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout,
    QScrollArea, QPushButton, QTextEdit, QLabel,
)
from PySide6.QtCore import Qt, Signal, QTimer
from PySide6.QtGui import QFont, QKeyEvent, QCloseEvent

from ui.message_bubble import MessageBubble
from ui.style import load_stylesheet
from services.local_command_executor import LocalCommandExecutor
from app.logger import setup_logger

if TYPE_CHECKING:
    from app.state_manager import StateManager

logger = setup_logger()

_IDLE_RESTORE_MS = 2000   # 宠物恢复 idle 的延迟（毫秒）

# loading 气泡文案
_LOADING_LOCAL = "执行中…"
_LOADING_AI    = "思考中…"


class _InputEdit(QTextEdit):
    """
    支持 Enter 发送、Shift+Enter 换行的输入框。
    """
    enter_pressed = Signal()

    def keyPressEvent(self, event: QKeyEvent):
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            if event.modifiers() & Qt.KeyboardModifier.ShiftModifier:
                super().keyPressEvent(event)
            else:
                self.enter_pressed.emit()
        else:
            super().keyPressEvent(event)


class ChatWindow(QWidget):
    """
    聊天窗口。

    外部接入方式：
        window = ChatWindow(config=app_config, todo_service=todo_svc)
        window.set_state_manager(state_manager)
        window.set_pet_state_callback(pet.set_pet_state)
        window.open()

    AI 服务通过 LocalCommandExecutor 内置，无需外部注入。
    set_ai_handler() 保留以便自定义覆盖。
    """

    def __init__(self, theme: str = "dark", config=None, todo_service=None, parent=None):
        super().__init__(parent)
        self._theme = theme
        self._config = config
        self._state_manager: Optional["StateManager"] = None
        self._pet_state_cb: Optional[Callable[[str], None]] = None
        self._idle_timer = QTimer(self)
        self._idle_timer.setSingleShot(True)
        self._idle_timer.timeout.connect(self._restore_idle)

        # 异步执行器：内置 AIService + CacheService + 所有本地 Service
        # todo_service 由 main.py 注入，与弹窗定时检测共用同一实例
        self._executor = LocalCommandExecutor(config=config, todo_service=todo_service)
        self._executor.connect_result(self._on_reply)
        self._executor.connect_error(self._on_error)
        self._executor.connect_ai_start(self._on_ai_start)
        self._is_ai_request = False   # 标记当前请求是否走了 AI 流程

        self._build_window()
        self._build_ui()
        self._apply_style()
        self._add_welcome()

    # ── 公开接口 ─────────────────────────────────────────────

    def set_state_manager(self, manager: "StateManager"):
        """注入 StateManager，打开/发送消息时自动切换为 active"""
        self._state_manager = manager

    def set_pet_state_callback(self, callback: Callable[[str], None]):
        """注册宠物状态切换回调，签名：callback(state: str)"""
        self._pet_state_cb = callback

    def set_ai_handler(self, handler: Callable[[str], str]):
        """
        注入自定义 AI 调用函数（可选）。
        未调用时使用内置 AIService + CacheService 流程。
        签名：handler(text: str) -> str
        """
        self._executor.set_ai_handler(handler)

    # 向后兼容旧接口名
    def set_user_message_handler(self, handler: Callable[[str], str]):
        self.set_ai_handler(handler)

    def open(self):
        """显示窗口并将其激活到前台；同时通知 StateManager 进入 active"""
        if self.isHidden():
            self.show()
        self.raise_()
        self.activateWindow()
        self._set_active()

    # ── 窗口构建 ──────────────────────────────────────────────

    def _build_window(self):
        pet_name = self._config.pet_name if self._config else "AI 助手"
        self.setWindowTitle(f"{pet_name} · 对话")
        self.resize(440, 640)
        self.setMinimumSize(360, 480)

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        root.addWidget(self._build_title_bar())

        # 消息滚动区
        self._scroll = QScrollArea()
        self._scroll.setObjectName("ChatScrollArea")
        self._scroll.setWidgetResizable(True)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        self._msg_container = QWidget()
        self._msg_container.setObjectName("MsgContainer")
        self._msg_layout = QVBoxLayout(self._msg_container)
        self._msg_layout.setContentsMargins(0, 8, 0, 8)
        self._msg_layout.setSpacing(2)
        self._msg_layout.addStretch()

        self._scroll.setWidget(self._msg_container)
        root.addWidget(self._scroll, stretch=1)

        root.addWidget(self._build_input_bar())

    def _build_title_bar(self) -> QWidget:
        bar = QWidget()
        bar.setObjectName("TitleBar")
        bar.setFixedHeight(48)

        layout = QHBoxLayout(bar)
        layout.setContentsMargins(16, 0, 8, 0)
        layout.setSpacing(8)

        lbl = QLabel(f"🤖 {self._config.pet_name if self._config else 'AI 助手'}")
        lbl.setObjectName("TitleLabel")
        font = QFont()
        font.setPointSize(13)
        font.setBold(True)
        lbl.setFont(font)
        layout.addWidget(lbl)
        layout.addStretch()

        clear_btn = QPushButton("清空")
        clear_btn.setObjectName("ClearButton")
        clear_btn.setFixedSize(52, 28)
        clear_btn.setToolTip("清空聊天记录")
        clear_btn.clicked.connect(self._on_clear)
        layout.addWidget(clear_btn)

        return bar

    def _build_input_bar(self) -> QWidget:
        bar = QWidget()
        bar.setObjectName("InputBar")
        bar.setFixedHeight(90)

        layout = QHBoxLayout(bar)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(8)

        self._input = _InputEdit()
        self._input.setObjectName("InputTextEdit")
        self._input.setFixedHeight(66)
        self._input.setPlaceholderText("输入消息… (Enter 发送，Shift+Enter 换行)")
        self._input.enter_pressed.connect(self._on_send)

        self._send_btn = QPushButton("发送")
        self._send_btn.setObjectName("SendButton")
        self._send_btn.setFixedSize(72, 66)
        self._send_btn.clicked.connect(self._on_send)

        layout.addWidget(self._input)
        layout.addWidget(self._send_btn)

        return bar

    def _apply_style(self):
        self.setStyleSheet(load_stylesheet(self._theme))

    # ── 消息渲染 ──────────────────────────────────────────────

    def _add_welcome(self):
        """显示欢迎语；若 AI 未配置则附加提示"""
        pet_name = self._config.pet_name if self._config else "AI 助手"
        msg = f"你好！我是{pet_name}，有什么我可以帮到你的吗？😊"

        # 检查 AI 是否已配置，未配置时追加提示
        if not self._executor.ai_configured:
            msg += "\n\n💡 当前未配置 AI API，请在 .env 中填写模型配置（AI_API_KEY 等），才能使用 AI 问答功能。"

        self._append_bubble(msg, "assistant")

    def _append_bubble(self, text: str, role: str):
        """在消息列表末尾插入一条气泡（插入到 stretch 前）"""
        bubble = MessageBubble(text=text, role=role)
        pos = self._msg_layout.count() - 1
        self._msg_layout.insertWidget(pos, bubble)
        self._scroll_to_bottom()

    def _scroll_to_bottom(self):
        """延迟一帧滚动到底部，确保布局已更新"""
        QTimer.singleShot(0, lambda: self._scroll.verticalScrollBar().setValue(
            self._scroll.verticalScrollBar().maximum()
        ))

    def _set_loading(self, visible: bool, text: str = _LOADING_LOCAL):
        """
        显示或移除 loading 占位气泡。
        visible=True 时插入气泡；False 时移除已有气泡。
        text 参数控制气泡文案（"执行中…" or "思考中…"）。
        """
        if visible:
            self._loading_bubble = MessageBubble(text, "assistant")
            pos = self._msg_layout.count() - 1
            self._msg_layout.insertWidget(pos, self._loading_bubble)
            self._scroll_to_bottom()
        else:
            bubble = getattr(self, "_loading_bubble", None)
            if bubble:
                bubble.setParent(None)
                bubble.deleteLater()
                self._loading_bubble = None

    def _update_loading_text(self, text: str):
        """更新现有 loading 气泡的文案（AI 流程开始时调用）"""
        bubble = getattr(self, "_loading_bubble", None)
        if bubble:
            bubble.setText(text)

    def _set_sending(self, busy: bool):
        """发送中禁用输入和发送按钮，防止重复提交"""
        self._input.setEnabled(not busy)
        self._send_btn.setEnabled(not busy)

    # ── 事件处理 ──────────────────────────────────────────────

    def _on_send(self):
        """用户点击发送或按 Enter"""
        text = self._input.toPlainText().strip()
        if not text:
            return
        self._input.clear()

        # 通知 StateManager → active
        self._set_active()

        # 显示用户气泡
        self._append_bubble(text, "user")

        # 切换宠物为 thinking，禁用输入，显示"执行中…"占位（本地指令快，先显示通用文案）
        self._notify_pet_state("thinking")
        self._set_sending(True)
        self._set_loading(True, _LOADING_LOCAL)
        self._is_ai_request = False   # 每次发送前重置

        # 后台异步执行：结果通过 _on_reply / _on_error 回调返回
        self._executor.execute(text)
        logger.debug(f"异步执行指令：{text!r}")

    def _on_ai_start(self):
        """
        后台线程确认进入 AI 流程时回调（在主线程执行，Qt 信号保证）。
        更新 loading 气泡文案为"思考中…"，提升用户感知。
        """
        self._is_ai_request = True
        self._update_loading_text(_LOADING_AI)
        logger.debug("进入 AI 问答流程，loading 切换为'思考中…'")

    def _on_reply(self, reply: str):
        """后台线程完成后，在主线程更新 UI（Qt 信号机制保证线程安全）"""
        self._set_loading(False)
        self._set_sending(False)
        self._append_bubble(reply, "assistant")

        # AI 回复后：speaking 状态 → 2 秒后恢复 idle
        # 本地指令回复：直接恢复 idle（无需经过 speaking）
        if self._is_ai_request:
            self._notify_pet_state("speaking")
            self._idle_timer.start(_IDLE_RESTORE_MS)
        else:
            self._notify_pet_state("idle")
        logger.debug(f"收到回复：{reply!r}")

    def _on_error(self, error_msg: str):
        """后台线程出错时在主线程显示错误提示"""
        self._set_loading(False)
        self._set_sending(False)
        self._append_bubble(error_msg, "assistant")
        self._notify_pet_state("idle")

    def _on_clear(self):
        """清空全部消息气泡并重新显示欢迎语"""
        for i in reversed(range(self._msg_layout.count())):
            item = self._msg_layout.itemAt(i)
            if item and isinstance(item.widget(), MessageBubble):
                w = item.widget()
                w.setParent(None)
                w.deleteLater()
        self._add_welcome()

    # ── 辅助方法 ──────────────────────────────────────────────

    def _notify_pet_state(self, state: str):
        """安全调用宠物状态回调，未注册时静默跳过"""
        if self._pet_state_cb:
            try:
                self._pet_state_cb(state)
            except Exception as e:
                logger.warning(f"宠物状态切换失败：{e}")

    def _restore_idle(self):
        """定时器触发后恢复宠物为 idle"""
        self._notify_pet_state("idle")

    def _set_active(self):
        """通知 StateManager 切换为 active（未注入时静默）"""
        if self._state_manager:
            self._state_manager.set_state("active")

    def closeEvent(self, event: QCloseEvent):
        """关闭窗口时停止定时器，避免野指针"""
        self._idle_timer.stop()
        super().closeEvent(event)
