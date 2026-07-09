"""
聊天窗口模块

UI 架构：
    ┌─────────────────────────────────┐
    │  TitleBar  [🤖 标题 副标题] [清空] │  56px 固定高
    ├─────────────────────────────────┤
    │                                 │
    │       ChatScrollArea            │  弹性
    │    （消息气泡列表）              │
    │                                 │
    ├─────────────────────────────────┤
    │  InputBar                       │  88px 固定高
    │  [ InputFrame: TextEdit ] [btn] │
    └─────────────────────────────────┘

按钮状态机（_btn_state）：
    idle     → 用户点击发送 → running
    running  → 任务完成     → idle
    running  → 用户点停止   → idle（丢弃旧任务结果）

任务取消机制（task_id）：
    每次发送时生成唯一 task_id（uuid4 前 8 位）。
    所有回调均携带 task_id；ChatWindow 比对 self._current_task_id，
    不一致则丢弃（旧任务或已被取消的任务）。
"""

import uuid
from typing import Callable, Optional, TYPE_CHECKING

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout,
    QScrollArea, QPushButton, QTextEdit, QLabel, QFrame, QSizePolicy,
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

# 宠物恢复 idle 的延迟（ms）
_IDLE_RESTORE_MS = 2000

# 按钮状态标识
_BTN_IDLE    = "idle"
_BTN_RUNNING = "running"


class _InputEdit(QTextEdit):
    """Enter 发送、Shift+Enter 换行的输入框"""
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
    聊天主窗口。

    接入方式：
        window = ChatWindow(config=app_config, todo_service=todo_svc)
        window.set_state_manager(state_manager)
        window.set_pet_state_callback(pet.set_pet_state)
        window.open()
    """

    def __init__(self, theme: str = "dark", config=None, todo_service=None, parent=None):
        super().__init__(parent)
        self.setObjectName("ChatWindow")
        self._theme        = theme
        self._config       = config

        self._state_manager: Optional["StateManager"] = None
        self._pet_state_cb: Optional[Callable[[str], None]] = None

        # AI 回复后恢复 idle 的定时器
        self._idle_timer = QTimer(self)
        self._idle_timer.setSingleShot(True)
        self._idle_timer.timeout.connect(self._restore_idle)

        # ── 任务状态 ──────────────────────────────────────────
        self._btn_state: str       = _BTN_IDLE    # 按钮当前状态
        self._current_task_id: str = ""           # 当前进行中的 task_id
        self._loading_bubble: Optional[MessageBubble] = None  # 临时 loading 气泡

        # ── 异步执行器 ────────────────────────────────────────
        self._executor = LocalCommandExecutor(config=config, todo_service=todo_service)
        self._executor.connect_result(self._on_result)
        self._executor.connect_error(self._on_error)
        self._executor.connect_ai_start(self._on_ai_start)
        self._executor.connect_finished(self._on_finished)

        self._build_window()
        self._build_ui()
        self._apply_style()
        self._add_welcome()

    # ── 公开接口 ──────────────────────────────────────────────

    def set_state_manager(self, manager: "StateManager"):
        self._state_manager = manager

    def set_pet_state_callback(self, callback: Callable[[str], None]):
        self._pet_state_cb = callback

    def set_ai_handler(self, handler: Callable[[str], str]):
        self._executor.set_ai_handler(handler)

    # 向后兼容旧接口名
    def set_user_message_handler(self, handler: Callable[[str], str]):
        self.set_ai_handler(handler)

    def open(self):
        """显示并激活窗口"""
        if self.isHidden():
            self.show()
        self.raise_()
        self.activateWindow()
        self._set_active()

    # ── 窗口构建 ──────────────────────────────────────────────

    def _build_window(self):
        pet_name = self._config.pet_name if self._config else "AI 助手"
        self.setWindowTitle(f"{pet_name} · 对话")
        self.resize(460, 660)
        self.setMinimumSize(360, 500)

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
        self._msg_layout.setContentsMargins(0, 10, 0, 10)
        self._msg_layout.setSpacing(4)
        self._msg_layout.addStretch()

        self._scroll.setWidget(self._msg_container)
        root.addWidget(self._scroll, stretch=1)

        root.addWidget(self._build_input_bar())

    def _build_title_bar(self) -> QWidget:
        bar = QWidget()
        bar.setObjectName("TitleBar")
        bar.setFixedHeight(56)

        layout = QHBoxLayout(bar)
        layout.setContentsMargins(14, 0, 10, 0)
        layout.setSpacing(10)

        # 机器人头像
        avatar = QLabel("🤖")
        avatar.setFixedSize(34, 34)
        avatar.setAlignment(Qt.AlignmentFlag.AlignCenter)
        font_a = QFont()
        font_a.setPointSize(18)
        avatar.setFont(font_a)
        layout.addWidget(avatar)

        # 标题 + 副标题
        title_col = QVBoxLayout()
        title_col.setSpacing(1)
        title_col.setContentsMargins(0, 0, 0, 0)

        pet_name = self._config.pet_name if self._config else "图图助手"
        lbl_title = QLabel(pet_name)
        lbl_title.setObjectName("TitleLabel")
        font_t = QFont()
        font_t.setPointSize(13)
        font_t.setWeight(QFont.Weight.Bold)
        lbl_title.setFont(font_t)

        lbl_sub = QLabel("智能助手 · 贴心陪伴")
        lbl_sub.setObjectName("SubTitleLabel")
        font_s = QFont()
        font_s.setPointSize(9)
        lbl_sub.setFont(font_s)

        title_col.addWidget(lbl_title)
        title_col.addWidget(lbl_sub)
        layout.addLayout(title_col)
        layout.addStretch()

        # 清空按钮
        clear_btn = QPushButton("清空")
        clear_btn.setObjectName("ClearButton")
        clear_btn.setFixedSize(56, 30)
        clear_btn.setToolTip("清空聊天记录")
        clear_btn.clicked.connect(self._on_clear)
        layout.addWidget(clear_btn)

        return bar

    def _build_input_bar(self) -> QWidget:
        """底部输入区：圆角 InputFrame 包裹输入框 + 按钮"""
        bar = QWidget()
        bar.setObjectName("InputBar")
        bar.setFixedHeight(76)

        outer = QHBoxLayout(bar)
        outer.setContentsMargins(12, 10, 12, 10)
        outer.setSpacing(8)

        # 输入框外层圆角 Frame
        frame = QFrame()
        frame.setObjectName("InputFrame")
        frame_layout = QHBoxLayout(frame)
        frame_layout.setContentsMargins(4, 4, 4, 4)
        frame_layout.setSpacing(0)

        self._input = _InputEdit()
        self._input.setObjectName("InputTextEdit")
        self._input.setPlaceholderText("输入消息...（Enter 发送，Shift+Enter 换行）")
        self._input.enter_pressed.connect(self._on_send)
        frame_layout.addWidget(self._input)

        outer.addWidget(frame, stretch=1)

        # 发送 / 停止 按钮
        self._send_btn = QPushButton("发送")
        self._send_btn.setObjectName("SendButton")
        self._send_btn.setFixedSize(72, 54)
        self._send_btn.clicked.connect(self._on_btn_click)
        outer.addWidget(self._send_btn)

        return bar

    def _apply_style(self):
        self.setStyleSheet(load_stylesheet(self._theme))

    # ── 消息渲染 ──────────────────────────────────────────────

    def _add_welcome(self):
        pet_name = self._config.pet_name if self._config else "AI 助手"
        msg = f"你好！我是{pet_name}，有什么我可以帮到你的吗？😊"
        if not self._executor.ai_configured:
            msg += "\n\n💡 当前未配置 AI API，请在 .env 中填写 AI_API_KEY 等，才能使用 AI 问答。"
        self._append_bubble(msg, "assistant")

    def _append_bubble(self, text: str, role: str) -> MessageBubble:
        """在消息列表末尾插入气泡，返回气泡控件引用"""
        bubble = MessageBubble(text=text, role=role)
        pos = self._msg_layout.count() - 1   # 插入到 stretch 之前
        self._msg_layout.insertWidget(pos, bubble)
        self._scroll_to_bottom()
        return bubble

    def _scroll_to_bottom(self):
        """延迟一帧滚动到底"""
        QTimer.singleShot(0, lambda: self._scroll.verticalScrollBar().setValue(
            self._scroll.verticalScrollBar().maximum()
        ))

    def _show_loading(self, base_text: str = "执行中"):
        """插入临时 loading 气泡，并保存引用"""
        self._remove_loading()   # 防止重复
        self._loading_bubble = self._append_bubble(base_text, "loading")

    def _update_loading_text(self, text: str):
        """更新 loading 气泡文案（AI 流程开始时调用）"""
        if self._loading_bubble:
            self._loading_bubble._base_text = text

    def _remove_loading(self):
        """移除 loading 气泡并停止动画"""
        if self._loading_bubble:
            self._loading_bubble.stop_dots()
            self._loading_bubble.setParent(None)
            self._loading_bubble.deleteLater()
            self._loading_bubble = None

    # ── 按钮状态机 ────────────────────────────────────────────

    def _set_btn_state(self, state: str):
        """
        切换按钮显示状态。
        state: "idle" | "running"
        """
        self._btn_state = state
        if state == _BTN_RUNNING:
            self._send_btn.setText("停止")
            self._send_btn.setObjectName("StopButton")
        else:
            self._send_btn.setText("发送")
            self._send_btn.setObjectName("SendButton")
        # 强制刷新 QSS（objectName 变更后需重新 polish）
        self._send_btn.style().unpolish(self._send_btn)
        self._send_btn.style().polish(self._send_btn)

    def _on_btn_click(self):
        """统一按钮点击处理：根据当前状态决定发送还是停止"""
        if self._btn_state == _BTN_RUNNING:
            self._do_stop()
        else:
            self._on_send()

    # ── 发送流程 ──────────────────────────────────────────────

    def _on_send(self):
        """用户按 Enter 或点击发送"""
        text = self._input.toPlainText().strip()
        if not text:
            return

        # 如果有旧任务在运行，先取消
        if self._btn_state == _BTN_RUNNING:
            self._do_stop()
            return

        self._input.clear()
        self._set_active()

        # 生成本次任务 ID
        task_id = uuid.uuid4().hex[:8]
        self._current_task_id = task_id

        # 渲染用户气泡
        self._append_bubble(text, "user")

        # 切换按钮、宠物状态、显示 loading
        self._set_btn_state(_BTN_RUNNING)
        self._notify_pet_state("thinking")
        self._show_loading("正在处理")

        # 后台执行
        self._executor.execute(text, task_id)
        logger.debug(f"发送指令：{text!r}  task_id={task_id}")

    def _do_stop(self):
        """用户点击停止：取消任务，恢复 UI"""
        logger.info(f"用户停止任务 task_id={self._current_task_id}")
        self._executor.cancel_current_task()

        # 使当前 task_id 失效，后续回调将被丢弃
        self._current_task_id = ""

        self._remove_loading()
        self._append_bubble("⏹ 已停止当前操作。", "assistant")
        self._set_btn_state(_BTN_IDLE)
        self._notify_pet_state("idle")
        self._input.setFocus()

    # ── 执行回调（含 task_id 校验）───────────────────────────

    def _on_result(self, task_id: str, reply: str):
        """后台线程正常返回结果"""
        if task_id != self._current_task_id:
            logger.debug(f"丢弃旧任务结果 task_id={task_id}")
            return

        self._remove_loading()
        self._append_bubble(reply, "assistant")
        self._set_btn_state(_BTN_IDLE)

        # AI 回复：speaking → 2 秒后 idle；本地回复：直接 idle
        # 通过检测 reply 首字符判断来源（loading 切换为"思考中"后标志 AI 流程）
        if getattr(self, "_is_ai_request", False):
            self._notify_pet_state("speaking")
            self._idle_timer.start(_IDLE_RESTORE_MS)
            self._is_ai_request = False
        else:
            self._notify_pet_state("idle")

        self._input.setFocus()
        logger.debug(f"收到回复 task_id={task_id}：{reply[:40]!r}...")

    def _on_error(self, task_id: str, error_msg: str):
        """后台线程出错"""
        if task_id != self._current_task_id:
            logger.debug(f"丢弃旧任务错误 task_id={task_id}")
            return

        self._remove_loading()
        self._append_bubble(f"⚠️ {error_msg}", "assistant")
        self._set_btn_state(_BTN_IDLE)
        self._notify_pet_state("idle")
        self._input.setFocus()

    def _on_ai_start(self, task_id: str):
        """后台线程确认进入 AI 流程"""
        if task_id != self._current_task_id:
            return
        self._is_ai_request = True
        self._update_loading_text("正在思考")
        logger.debug("进入 AI 流程，loading → 正在思考")

    def _on_finished(self, task_id: str):
        """
        线程结束（无论成功/失败/取消）。
        作为安全兜底：若按钮仍处于 running 状态（异常情况），
        强制恢复 idle。
        """
        if task_id != self._current_task_id:
            return
        if self._btn_state == _BTN_RUNNING:
            logger.warning("线程结束但按钮仍为 running，强制恢复")
            self._remove_loading()
            self._set_btn_state(_BTN_IDLE)
            self._notify_pet_state("idle")

    # ── 清空 ──────────────────────────────────────────────────

    def _on_clear(self):
        """清空全部消息气泡并重新显示欢迎语"""
        # 如有任务进行，先停止
        if self._btn_state == _BTN_RUNNING:
            self._do_stop()

        for i in reversed(range(self._msg_layout.count())):
            item = self._msg_layout.itemAt(i)
            if item and isinstance(item.widget(), MessageBubble):
                w = item.widget()
                w.setParent(None)
                w.deleteLater()

        self._loading_bubble = None
        self._add_welcome()

    # ── 辅助方法 ──────────────────────────────────────────────

    def _notify_pet_state(self, state: str):
        if self._pet_state_cb:
            try:
                self._pet_state_cb(state)
            except Exception as e:
                logger.warning(f"宠物状态切换失败：{e}")

    def _restore_idle(self):
        self._notify_pet_state("idle")

    def _set_active(self):
        if self._state_manager:
            try:
                self._state_manager.set_state("active")
            except Exception as e:
                logger.warning(f"StateManager 切换失败：{e}")

    def closeEvent(self, event: QCloseEvent):
        self._idle_timer.stop()
        super().closeEvent(event)
