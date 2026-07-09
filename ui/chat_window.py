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
    │  [ InputFrame: TextEdit ] [语音] [发送/停止] │
    └─────────────────────────────────┘

按钮状态机总览：
    文字闲置：    发送(idle)  语音(idle)
    任务执行中：  停止(running) 语音(disabled)
    录音中：      发送(disabled) 停止录音(recording)
    语音识别中：  发送(disabled) 语音(disabled)
    TTS播报中：   发送(idle) 语音(disabled/tts)

任务取消机制（task_id）：
    每次发送时生成唯一 task_id（uuid4 前 8 位）。
    所有回调均携带 task_id；ChatWindow 比对 self._current_task_id，
    不一致则丢弃（旧任务或已被取消的任务）。
"""

import uuid
import threading
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
from services.tts_service import TTSService
from services.voice_recorder_service import VoiceRecorderService
from services.asr_service import ASRService
from app.logger import setup_logger

if TYPE_CHECKING:
    from app.state_manager import StateManager
    from app.config import AppConfig

logger = setup_logger()

# 宠物恢复 idle 的延迟（ms）
_IDLE_RESTORE_MS = 2000

# 发送按钮状态标识
_BTN_IDLE    = "idle"
_BTN_RUNNING = "running"

# 语音按钮状态标识
_VOICE_IDLE       = "voice_idle"       # 显示"语音"，可点击
_VOICE_RECORDING  = "voice_recording"  # 显示"停止"，点击停止录音
_VOICE_RECOGNIZING = "voice_recognizing" # 显示"识别中"，禁用
_VOICE_TTS        = "voice_tts"        # TTS播报中，显示"播报中"，点击停止TTS
_VOICE_DISABLED   = "voice_disabled"   # 任务执行中禁用


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

    def __init__(self, theme: str = "dark", config: "AppConfig | None" = None,
                 todo_service=None, parent=None):
        super().__init__(parent)
        self.setObjectName("ChatWindow")
        self._theme  = theme
        self._config = config

        self._state_manager: Optional["StateManager"] = None
        self._pet_state_cb: Optional[Callable[[str], None]] = None

        # AI 回复后恢复 idle 的定时器
        self._idle_timer = QTimer(self)
        self._idle_timer.setSingleShot(True)
        self._idle_timer.timeout.connect(self._restore_idle)

        # ── 任务状态 ──────────────────────────────────────────
        self._btn_state: str        = _BTN_IDLE
        self._voice_state: str      = _VOICE_IDLE
        self._current_task_id: str  = ""
        self._loading_bubble: Optional[MessageBubble] = None
        self._is_ai_request: bool   = False

        # ── 异步执行器 ────────────────────────────────────────
        self._executor = LocalCommandExecutor(config=config, todo_service=todo_service)
        self._executor.connect_result(self._on_result)
        self._executor.connect_error(self._on_error)
        self._executor.connect_ai_start(self._on_ai_start)
        self._executor.connect_finished(self._on_finished)

        # ── 语音服务 ──────────────────────────────────────────
        vc = config.voice if config else None
        self._tts = TTSService(
            enabled=vc.tts_enabled      if vc else True,
            provider=vc.tts_provider    if vc else "edge",
            voice=vc.tts_voice          if vc else "zh-CN-XiaoxiaoNeural",
            max_chars=vc.tts_max_chars  if vc else 200,
        )
        self._tts.set_callbacks(
            on_start=self._on_tts_start,
            on_done=self._on_tts_done,
        )

        self._recorder = VoiceRecorderService()
        self._recorder.set_callbacks(
            on_start=self._on_recorder_start,
            on_done=self._on_recorder_done,
            on_error=self._on_recorder_error,
        )

        asr_provider = vc.asr_provider if vc else "none"
        self._asr = ASRService(provider=asr_provider)

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

    def set_user_message_handler(self, handler: Callable[[str], str]):
        self.set_ai_handler(handler)

    def open(self):
        """显示并激活窗口"""
        if self.isHidden():
            self.show()
        self.raise_()
        self.activateWindow()
        self._set_active()

    def trigger_voice_input(self):
        """由外部（托盘菜单）触发语音输入"""
        self.open()
        if self._voice_state == _VOICE_IDLE:
            self._on_voice_btn_click()

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

        avatar = QLabel("🤖")
        avatar.setFixedSize(34, 34)
        avatar.setAlignment(Qt.AlignmentFlag.AlignCenter)
        font_a = QFont(); font_a.setPointSize(18)
        avatar.setFont(font_a)
        layout.addWidget(avatar)

        title_col = QVBoxLayout()
        title_col.setSpacing(1)
        title_col.setContentsMargins(0, 0, 0, 0)

        pet_name = self._config.pet_name if self._config else "图图助手"
        lbl_title = QLabel(pet_name)
        lbl_title.setObjectName("TitleLabel")
        font_t = QFont(); font_t.setPointSize(13); font_t.setWeight(QFont.Weight.Bold)
        lbl_title.setFont(font_t)

        lbl_sub = QLabel("智能助手 · 贴心陪伴")
        lbl_sub.setObjectName("SubTitleLabel")
        font_s = QFont(); font_s.setPointSize(9)
        lbl_sub.setFont(font_s)

        title_col.addWidget(lbl_title)
        title_col.addWidget(lbl_sub)
        layout.addLayout(title_col)
        layout.addStretch()

        clear_btn = QPushButton("清空")
        clear_btn.setObjectName("ClearButton")
        clear_btn.setFixedSize(56, 30)
        clear_btn.setToolTip("清空聊天记录")
        clear_btn.clicked.connect(self._on_clear)
        layout.addWidget(clear_btn)

        return bar

    def _build_input_bar(self) -> QWidget:
        """底部输入区：输入框 + 语音按钮 + 发送/停止按钮"""
        bar = QWidget()
        bar.setObjectName("InputBar")
        bar.setFixedHeight(76)

        outer = QHBoxLayout(bar)
        outer.setContentsMargins(12, 10, 12, 10)
        outer.setSpacing(6)

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

        # 语音按钮
        self._voice_btn = QPushButton("语音")
        self._voice_btn.setObjectName("VoiceButton")
        self._voice_btn.setFixedSize(52, 54)
        self._voice_btn.setToolTip("点击开始语音输入")
        self._voice_btn.clicked.connect(self._on_voice_btn_click)
        outer.addWidget(self._voice_btn)

        # 发送 / 停止 按钮
        self._send_btn = QPushButton("发送")
        self._send_btn.setObjectName("SendButton")
        self._send_btn.setFixedSize(62, 54)
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
        bubble = MessageBubble(text=text, role=role)
        pos = self._msg_layout.count() - 1
        self._msg_layout.insertWidget(pos, bubble)
        self._scroll_to_bottom()
        return bubble

    def _scroll_to_bottom(self):
        QTimer.singleShot(0, lambda: self._scroll.verticalScrollBar().setValue(
            self._scroll.verticalScrollBar().maximum()
        ))

    def _show_loading(self, base_text: str = "正在处理"):
        self._remove_loading()
        self._loading_bubble = self._append_bubble(base_text, "loading")

    def _update_loading_text(self, text: str):
        if self._loading_bubble:
            self._loading_bubble._base_text = text

    def _remove_loading(self):
        if self._loading_bubble:
            self._loading_bubble.stop_dots()
            self._loading_bubble.setParent(None)
            self._loading_bubble.deleteLater()
            self._loading_bubble = None

    # ── 发送按钮状态机 ────────────────────────────────────────

    def _set_btn_state(self, state: str):
        """切换发送按钮显示状态并联动语音按钮"""
        self._btn_state = state
        if state == _BTN_RUNNING:
            self._send_btn.setText("停止")
            self._send_btn.setObjectName("StopButton")
            # 任务执行中禁用语音按钮（除非处于 TTS 状态）
            if self._voice_state not in (_VOICE_TTS,):
                self._set_voice_btn_state(_VOICE_DISABLED)
        else:
            self._send_btn.setText("发送")
            self._send_btn.setObjectName("SendButton")
            # 任务结束，如果语音按钮是被任务禁用的，恢复为 idle
            if self._voice_state == _VOICE_DISABLED:
                self._set_voice_btn_state(_VOICE_IDLE)
        self._refresh_btn_style(self._send_btn)

    def _on_btn_click(self):
        if self._btn_state == _BTN_RUNNING:
            self._do_stop()
        else:
            self._on_send()

    # ── 语音按钮状态机 ────────────────────────────────────────

    def _set_voice_btn_state(self, state: str):
        """切换语音按钮状态"""
        self._voice_state = state
        if state == _VOICE_IDLE:
            self._voice_btn.setText("语音")
            self._voice_btn.setObjectName("VoiceButton")
            self._voice_btn.setEnabled(True)
            self._voice_btn.setToolTip("点击开始语音输入")
        elif state == _VOICE_RECORDING:
            self._voice_btn.setText("停止")
            self._voice_btn.setObjectName("VoiceStopButton")
            self._voice_btn.setEnabled(True)
            self._voice_btn.setToolTip("点击停止录音")
        elif state == _VOICE_RECOGNIZING:
            self._voice_btn.setText("识别中")
            self._voice_btn.setObjectName("VoiceDisabledButton")
            self._voice_btn.setEnabled(False)
        elif state == _VOICE_TTS:
            self._voice_btn.setText("播报中")
            self._voice_btn.setObjectName("VoiceDisabledButton")
            self._voice_btn.setEnabled(True)   # 可点击以停止播报
            self._voice_btn.setToolTip("点击停止语音播报")
        elif state == _VOICE_DISABLED:
            self._voice_btn.setText("语音")
            self._voice_btn.setObjectName("VoiceDisabledButton")
            self._voice_btn.setEnabled(False)
        self._refresh_btn_style(self._voice_btn)

    def _refresh_btn_style(self, btn: QPushButton):
        """强制刷新 QSS（objectName 变更后重新 polish）"""
        btn.style().unpolish(btn)
        btn.style().polish(btn)

    def _on_voice_btn_click(self):
        """语音按钮点击分发"""
        state = self._voice_state

        if state == _VOICE_IDLE:
            self._start_voice_input()
        elif state == _VOICE_RECORDING:
            self._stop_voice_input()
        elif state == _VOICE_TTS:
            self._stop_tts()
        # _VOICE_RECOGNIZING / _VOICE_DISABLED：按钮已禁用，不响应

    # ── 发送流程 ──────────────────────────────────────────────

    def _on_send(self):
        """用户按 Enter 或点击发送"""
        text = self._input.toPlainText().strip()
        if not text:
            return

        if self._btn_state == _BTN_RUNNING:
            self._do_stop()
            return

        self._input.clear()
        self._set_active()

        task_id = uuid.uuid4().hex[:8]
        self._current_task_id = task_id

        self._append_bubble(text, "user")
        self._set_btn_state(_BTN_RUNNING)
        self._notify_pet_state("thinking")
        self._show_loading("正在处理")

        self._executor.execute(text, task_id)
        logger.debug(f"发送指令：{text!r}  task_id={task_id}")

    def _do_stop(self):
        """用户点击停止：取消任务，恢复 UI"""
        logger.info(f"用户停止任务 task_id={self._current_task_id}")
        self._executor.cancel_current_task()
        self._current_task_id = ""

        self._remove_loading()
        self._append_bubble("⏹ 已停止当前操作。", "assistant")
        self._set_btn_state(_BTN_IDLE)
        self._notify_pet_state("idle")
        self._input.setFocus()

    # ── 执行回调 ──────────────────────────────────────────────

    def _on_result(self, task_id: str, reply: str):
        if task_id != self._current_task_id:
            logger.debug(f"丢弃旧任务结果 task_id={task_id}")
            return

        self._remove_loading()
        self._append_bubble(reply, "assistant")
        self._set_btn_state(_BTN_IDLE)

        if getattr(self, "_is_ai_request", False):
            self._notify_pet_state("speaking")
            self._idle_timer.start(_IDLE_RESTORE_MS)
            self._is_ai_request = False
        else:
            self._notify_pet_state("idle")

        # TTS 播报
        vc = self._config.voice if self._config else None
        if vc and vc.tts_enabled:
            self._tts.speak(reply)

        self._input.setFocus()
        logger.debug(f"收到回复 task_id={task_id}：{reply[:40]!r}...")

    def _on_error(self, task_id: str, error_msg: str):
        if task_id != self._current_task_id:
            return
        self._remove_loading()
        self._append_bubble(f"⚠️ {error_msg}", "assistant")
        self._set_btn_state(_BTN_IDLE)
        self._notify_pet_state("idle")
        self._input.setFocus()

    def _on_ai_start(self, task_id: str):
        if task_id != self._current_task_id:
            return
        self._is_ai_request = True
        self._update_loading_text("图图正在思考")
        logger.debug("进入 AI 流程，loading → 图图正在思考")

    def _on_finished(self, task_id: str):
        if task_id != self._current_task_id:
            return
        if self._btn_state == _BTN_RUNNING:
            logger.warning("线程结束但按钮仍为 running，强制恢复")
            self._remove_loading()
            self._set_btn_state(_BTN_IDLE)
            self._notify_pet_state("idle")

    # ── 语音输入流程 ──────────────────────────────────────────

    def _start_voice_input(self):
        """开始录音"""
        vc = self._config.voice if self._config else None

        # 检查语音功能是否启用
        if vc and not vc.voice_enabled:
            self._append_bubble(
                "当前未启用语音功能，请在设置中开启。", "assistant"
            )
            return

        # 防自激：TTS 播报中禁止录音
        if self._tts.is_speaking():
            self._append_bubble("图图正在播报，请稍等播报结束后再说。", "assistant")
            return

        # 启动录音
        ok = self._recorder.start_recording()
        if not ok:
            self._append_bubble("⚠️ 无法启动录音，请稍后再试。", "assistant")

    def _stop_voice_input(self):
        """停止录音，进入识别流程"""
        self._set_voice_btn_state(_VOICE_RECOGNIZING)
        self._update_loading_text("正在识别语音")
        # 在后台线程中 stop_recording 然后 transcribe
        threading.Thread(
            target=self._do_asr,
            daemon=True,
            name="ASRWorker",
        ).start()

    def _do_asr(self):
        """后台：停止录音 → ASR 识别 → 填入输入框"""
        try:
            file_path = self._recorder.stop_recording()
            logger.debug(f"录音文件：{file_path!r}")

            text = self._asr.transcribe(file_path)

            # 回主线程处理结果
            from PySide6.QtCore import QTimer
            QTimer.singleShot(0, lambda: self._on_asr_done(text))
        except Exception as e:
            logger.error(f"ASR 流程异常：{e}")
            from PySide6.QtCore import QTimer
            QTimer.singleShot(0, lambda: self._on_asr_done(f"⚠️ 语音识别出错：{e}"))

    def _on_asr_done(self, text: str):
        """ASR 结果回调（主线程）"""
        self._remove_loading()
        self._set_voice_btn_state(_VOICE_IDLE)

        # ASR 未配置或识别失败：直接展示提示
        if text.startswith("当前未配置") or text.startswith("录音文件") \
                or text.startswith("⚠️") or text.startswith("Whisper") \
                or text.startswith("在线"):
            self._append_bubble(text, "assistant")
            return

        # 识别成功：填入输入框并自动发送
        logger.info(f"ASR 识别结果：{text!r}")
        self._input.setPlainText(text)
        self._on_send()

    # ── 录音回调（主线程安全，由 VoiceRecorderService QTimer 触发）────

    def _on_recorder_start(self):
        """录音开始"""
        self._set_voice_btn_state(_VOICE_RECORDING)
        self._show_loading("正在聆听")
        logger.debug("录音已开始")

    def _on_recorder_done(self, file_path: str):
        """录音文件保存完成（此时已由 _stop_voice_input 触发 ASR，这里不重复处理）"""
        logger.debug(f"录音保存完成：{file_path}")

    def _on_recorder_error(self, msg: str):
        """录音出错"""
        self._remove_loading()
        self._set_voice_btn_state(_VOICE_IDLE)
        self._append_bubble(f"⚠️ {msg}", "assistant")

    # ── TTS 回调 ──────────────────────────────────────────────

    def _on_tts_start(self):
        """TTS 开始播报（主线程）"""
        vc = self._config.voice if self._config else None
        if vc and vc.pause_mic_during_tts:
            self._set_voice_btn_state(_VOICE_TTS)
        logger.debug("TTS 开始播报")

    def _on_tts_done(self):
        """TTS 播报结束（主线程）"""
        if self._voice_state == _VOICE_TTS:
            self._set_voice_btn_state(_VOICE_IDLE)
        logger.debug("TTS 播报结束")

    def _stop_tts(self):
        """停止 TTS 播报"""
        self._tts.stop()
        self._set_voice_btn_state(_VOICE_IDLE)
        logger.debug("用户停止 TTS 播报")

    # ── 清空 ──────────────────────────────────────────────────

    def _on_clear(self):
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
        if self._tts.is_speaking():
            self._tts.stop()
        if self._recorder.is_recording():
            self._recorder.cancel_recording()
        super().closeEvent(event)
