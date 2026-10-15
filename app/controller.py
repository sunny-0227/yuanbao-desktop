"""应用控制器：UI 只发信号；服务生命周期与业务状态集中在这里。"""

import asyncio
import copy
from datetime import datetime

from PySide6.QtCore import QObject, QTimer, Signal, Slot

from app.config import ConfigStore, apply_environment
from app.state_manager import StateManager
from app.storage import Database
from services.ai_service import AIService
from services.audio_service import AudioService
from services.auto_sleep_service import AutoSleepService
from services.chat_history import ChatHistory
from services.command_dispatcher import CommandDispatcher
from services.local_command_executor import LocalCommandExecutor
from services.weather_service import weather


class AppController(QObject):
    message = Signal(str, str)
    partial = Signal(str)
    status = Signal(str)
    busy = Signal(bool)
    history_changed = Signal()
    data_changed = Signal()
    confirmation = Signal(object)
    config_changed = Signal(object)
    notification = Signal(str, str)
    reminder = Signal(object)
    pet_state = Signal(str)
    session_loaded = Signal(object)
    audio_state = Signal(str)
    closed = Signal()
    service_result = Signal(str, object)
    service_error = Signal(str, str)

    def __init__(self, config, db=None, store=None, parent=None):
        super().__init__(parent)
        self.config = config
        self.store = store or ConfigStore()
        self.db = db or Database()
        self.state = StateManager()
        self.history = ChatHistory(self.db)
        self.dispatcher = CommandDispatcher(config, db=self.db)
        self.ai = AIService(config, self.db)
        self.executor = LocalCommandExecutor(self)
        self.audio = AudioService(config.voice, self)
        self.monitor = AutoSleepService(self.state, config.behavior, self)
        self.current = ""
        self.auxiliary = {}
        self.pending = None
        self.buffer = ""
        self.closing = False
        prior = self.history.sessions()
        self.active_session = prior[0]["id"] if prior else self.history.create()
        self.executor.result.connect(self._result)
        self.executor.error.connect(self._error)
        self.executor.chunk.connect(self._chunk)
        self.executor.status.connect(self._status)
        self.executor.finished.connect(self._finished)
        self.audio.recognized.connect(self.send)
        self.audio.state_changed.connect(self._audio_state)
        self.audio.error.connect(lambda error: self.message.emit("error", error))
        self.audio.wake.connect(self._wake)
        self.state.add_listener(self._power_changed)
        self.reminder_timer = QTimer(self)
        self.reminder_timer.setSingleShot(True)
        self.reminder_timer.timeout.connect(self._reminders)
        self.stream_timer = QTimer(self)
        self.stream_timer.setInterval(50)
        self.stream_timer.timeout.connect(self._flush)
        self.schedule_reminders()
        QTimer.singleShot(1000, self.audio.resume_wake)

    @Slot(str)
    def send(self, text):
        text = text.strip()
        if not text or self.closing:
            return
        if self.current:
            self.status.emit("请先停止当前任务，再发送新消息")
            return
        self.pending = None
        self.audio.stop()
        self.state.touch_interaction()
        try:
            self.history.append(self.active_session, "user", text)
        except Exception as exc:
            self.message.emit("error", "消息未能保存，操作没有执行：" + str(exc))
            return
        self.message.emit("user", text)
        self.history_changed.emit()
        command = self.dispatcher.router.route(text)
        if command.confirmation:
            self.pending = (command, self.active_session)
            self.confirmation.emit(command)
            self.status.emit("等待你确认操作")
            return
        if command.action in ("sleep", "wake"):
            if command.action == "sleep":
                self.state.set_state("sleep", manual=True, reason="手动休眠")
                self._reply("已进入休眠，点击助手或托盘“恢复工作”即可唤醒。")
            else:
                self.state.touch_interaction()
                self._reply("已恢复工作。")
            return
        self._execute(command)

    @Slot(bool)
    def confirm(self, accepted):
        pending, self.pending = self.pending, None
        if not pending:
            return
        command, session = pending
        if session != self.active_session:
            return
        if accepted:
            self._execute(command)
        else:
            self._reply("已取消，本次操作没有执行。")

    def _execute(self, command):
        context = self.history.context(self.active_session)
        self.buffer = ""
        dispatcher, ai = self.dispatcher, self.ai

        def work(cancel, chunk, status):
            if command.action == "weather":
                return asyncio.run(weather(command.data["city"], cancel))
            if command.handled:
                status("正在执行本地指令")
                return dispatcher.execute(command)
            return ai.ask(context, cancel, chunk, status)

        self.audio.inhibit_wake(True)
        try:
            self.current = self.executor.submit(work)
        except RuntimeError as exc:
            self.audio.inhibit_wake(False)
            self.message.emit("error", str(exc))
            return
        if not command.handled:
            self.stream_timer.start()
        self.busy.emit(True)
        self.pet_state.emit("thinking" if not command.handled else "working")
        self.status.emit("正在处理")

    @Slot(str, object)
    def _result(self, ident, value):
        if ident in self.auxiliary:
            self.service_result.emit(self.auxiliary[ident], value)
            self.data_changed.emit()
            self.schedule_reminders()
            return
        if ident != self.current:
            return
        if value:
            self._reply(str(value))
            self.audio.speak(str(value))
        self.data_changed.emit()
        self.schedule_reminders()

    def _reply(self, text):
        try:
            self.history.append(self.active_session, "assistant", text)
        except Exception as exc:
            self.message.emit("error", "回复未能保存：" + str(exc))
        self.message.emit("assistant", text)
        self.history_changed.emit()

    @Slot(str, str)
    def _error(self, ident, text):
        if ident in self.auxiliary:
            self.service_error.emit(self.auxiliary[ident], text)
            return
        if ident == self.current:
            self.message.emit("error", text)

    @Slot(str, str)
    def _chunk(self, ident, text):
        if ident == self.current:
            self.buffer += text

    def _flush(self):
        if self.buffer:
            self.partial.emit(self.buffer)

    @Slot(str, str)
    def _status(self, ident, text):
        if ident == self.current:
            self.status.emit(text)

    @Slot(str)
    def _finished(self, ident):
        self.auxiliary.pop(ident, None)
        if ident == self.current:
            self.current = ""
            self.buffer = ""
            self.stream_timer.stop()
            self.partial.emit("")
            self.busy.emit(False)
            self.status.emit("可以继续输入")
            self.pet_state.emit(self.state.get_pet_state())
            self.audio.inhibit_wake(False)

    @Slot()
    def cancel(self):
        self.pending = None
        if self.current:
            self.executor.cancel(self.current)
            self.current = ""
            self.buffer = ""
            self.stream_timer.stop()
            self.partial.emit("")
            self.busy.emit(False)
            self.message.emit("system", "已取消接收本次结果；已经执行的本地操作不会撤回。")
        self.audio.stop()
        self.status.emit("已停止，可以重新发送")
        self.pet_state.emit(self.state.get_pet_state())
        self.audio.inhibit_wake(False)

    @Slot()
    def new_session(self):
        self.cancel()
        self.active_session = self.history.create()
        self.session_loaded.emit([])
        self.history_changed.emit()

    @Slot(str)
    def load_session(self, ident):
        self.cancel()
        self.active_session = ident
        self.session_loaded.emit(self.history.messages(ident))

    @Slot(str)
    def delete_session(self, ident):
        self.cancel()
        self.history.delete(ident)
        if ident == self.active_session:
            self.new_session()
        self.history_changed.emit()

    @Slot()
    def voice(self):
        if self.audio.state == "recording":
            self.audio.finish_recording()
        elif self.audio.state in ("recognizing", "speaking"):
            self.audio.stop()
        elif not self.current:
            self.state.touch_interaction()
            self.audio.record()

    @Slot()
    def _wake(self):
        if (
            self.state.get_state() == "active"
            and not self.current
            and self.audio.state == "idle"
            and not self.closing
        ):
            self.voice()

    @Slot(str)
    def _audio_state(self, state):
        self.audio_state.emit(state)
        if state != "idle":
            self.pet_state.emit(
                "listening"
                if state == "recording"
                else "thinking"
                if state == "recognizing"
                else "speaking"
            )
        elif not self.current:
            self.pet_state.emit(self.state.get_pet_state())

    def _power_changed(self, old, new):
        self.audio.set_allowed(new == "active")
        if new == "sleep":
            self.cancel()
            self.reminder_timer.stop()
        elif old == "sleep":
            self.schedule_reminders()
        self.pet_state.emit(self.state.get_pet_state())
        label = {"active": "活跃", "idle": "省电", "sleep": "休眠"}[new]
        self.status.emit(label + (" · " + self.state.reason if self.state.reason else ""))
        self.notification.emit("助手状态", label + "：" + self.state.reason)

    def schedule_reminders(self):
        if self.closing or self.state.get_state() == "sleep":
            return
        rows = [r for r in self.dispatcher.todos.all() if r["status"] == "pending"]
        if not rows:
            self.reminder_timer.stop()
            return
        due = min(datetime.fromisoformat(r["remind_time"]) for r in rows)
        delay = max(200, min(86400000, int((due - datetime.now()).total_seconds() * 1000)))
        self.reminder_timer.start(delay)

    def _reminders(self):
        try:
            rows = self.dispatcher.todos.check_due_todos()
            for row in rows:
                self.reminder.emit(row)
            self.data_changed.emit()
            if self.dispatcher.todos.check_due_todos():
                self.reminder_timer.start(30000)
            else:
                self.schedule_reminders()
        except Exception as exc:
            self.message.emit("error", "提醒检测失败：" + str(exc))
            self.reminder_timer.start(30000)

    def reminder_shown(self, ident):
        self.dispatcher.todos.acknowledge(ident)
        self.schedule_reminders()

    @Slot(object)
    def save_config(self, config):
        from services.startup_service import set_autostart

        try:
            if config.ui.autostart != self.config.ui.autostart:
                set_autostart(config.ui.autostart)
            effective = apply_environment(copy.deepcopy(config))
            self.store.save(config)
            if (
                effective.ai != self.config.ai
                or effective.ai_endpoints != self.config.ai_endpoints
                or effective.offline_ai_url != self.config.offline_ai_url
                or effective.offline_ai_model != self.config.offline_ai_model
            ):
                self.cancel()
            self.config = effective
            self.dispatcher = CommandDispatcher(self.config, db=self.db)
            self.ai = AIService(self.config, self.db)
            if self.audio.config != self.config.voice:
                self.audio.update_config(self.config.voice)
            self.monitor.update_config(self.config.behavior)
            self.config_changed.emit(self.config)
            self.status.emit("设置已保存并生效")
            self.data_changed.emit()
        except Exception as exc:
            self.notification.emit("设置保存失败", str(exc))

    def background(self, name, function):
        try:
            ident = self.executor.submit(function)
        except RuntimeError as exc:
            self.service_error.emit(name, str(exc))
            return None
        self.auxiliary[ident] = name
        return ident

    def manage(self, kind, action, value):
        service = self.dispatcher.todos if kind == "todos" else self.dispatcher.notes

        def work(cancel, chunk, status):
            if action == "add":
                return (
                    service.add_todo_from_text(value)
                    if kind == "todos"
                    else service.add_note(value)
                )
            if action == "delete":
                return (
                    service.delete_todo(value["id"])
                    if kind == "todos"
                    else service.delete(value["id"])
                )
            if action == "edit":
                return service.update(value["id"], value["content"])
            if action in ("complete", "snooze"):
                return getattr(service, action)(value["id"])
            raise ValueError("未知记录操作")

        self.background("library", work)

    def scan(self):
        from services.app_discovery_service import AppDiscoveryService

        def work(cancel, chunk, status):
            discovery = AppDiscoveryService()
            index = discovery.build_app_index()
            if not cancel.is_set():
                discovery.save_app_index(index)
            return discovery.count_summary(index)

        self.background("scan", work)

    def test_ai(self, config):
        # 与正式请求使用相同配置优先级和客户端，结果只用于连接诊断。
        service = AIService(apply_environment(copy.deepcopy(config)), self.db)
        self.background(
            "test_ai",
            lambda cancel, chunk, status: service.ask(
                [{"role": "user", "content": "请用一句话回复连接测试成功"}], cancel
            ),
        )

    def devices(self):
        from services.voice_recorder_service import VoiceRecorderService

        self.background("devices", lambda cancel, chunk, status: VoiceRecorderService.devices())

    @Slot()
    def shutdown(self):
        if self.closing:
            return
        self.closing = True
        self.reminder_timer.stop()
        self.stream_timer.stop()
        self.cancel()
        self.monitor.shutdown()
        self.executor.shutdown()
        self.audio.shutdown()
        self.closed.emit()
