"""录音、识别、播报互斥，回调通过 QObject 信号进入主线程。"""

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Event

from PySide6.QtCore import QObject, QTimer, Signal, Slot

from services.asr_service import ASRService
from services.tts_service import TTSService
from services.voice_recorder_service import VoiceRecorderService
from services.wake_service import WakeService


class AudioService(QObject):
    state_changed = Signal(str)
    recognized = Signal(str)
    error = Signal(str)
    wake = Signal()
    _wake_stopped = Signal()
    _state = Signal(str, str)
    _recognized = Signal(str, str)
    _error = Signal(str, str)

    def __init__(self, config, parent=None):
        super().__init__(parent)
        self.config = config
        self.pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="YuanbaoAudio")
        self.cancel = Event()
        self.stop_record = Event()
        self.state = "idle"
        self.generation = ""
        self.closed = False
        self.allowed = True
        self.wake_permitted = True
        self.wake_failed = False
        self.waker = WakeService(self.wake.emit, self.error.emit, self._wake_stopped.emit)
        self._wake_stopped.connect(lambda: QTimer.singleShot(100, self.resume_wake))
        self._state.connect(self._on_state)
        self._recognized.connect(self._on_recognized)
        self._error.connect(self._on_error)
        self.error.connect(self._wake_error)

    @Slot(str)
    def _wake_error(self, message):
        if message.startswith("语音唤醒不可用"):
            self.wake_failed = True

    @Slot(str, str)
    def _on_state(self, generation, state):
        if generation == self.generation:
            self.state = state
            self.state_changed.emit(state)
            if state == "idle":
                self.resume_wake()

    @Slot(str, str)
    def _on_recognized(self, generation, text):
        if generation == self.generation and text.strip():
            self.recognized.emit(text)

    @Slot(str, str)
    def _on_error(self, generation, error):
        if generation == self.generation:
            self.error.emit(error)

    def pause_wake(self):
        self.waker.stop()

    def resume_wake(self):
        if (
            self.allowed
            and self.wake_permitted
            and not self.closed
            and not self.wake_failed
            and self.config.wake_enabled
            and self.config.voice_enabled
            and self.state == "idle"
        ):
            if (
                self.waker.thread
                and self.waker.thread.is_alive()
                and self.waker.stop_event.is_set()
            ):
                QTimer.singleShot(250, self.resume_wake)
            else:
                self.waker.start(self.config)

    def inhibit_wake(self, inhibited):
        self.wake_permitted = not inhibited
        if inhibited:
            self.pause_wake()
        else:
            self.resume_wake()

    def set_allowed(self, allowed):
        self.allowed = allowed
        if not allowed:
            self.stop()
        else:
            self.resume_wake()

    def update_config(self, config):
        self.stop()
        self.config = config
        self.wake_failed = False
        self.resume_wake()

    def _submit(self, kind, function):
        import uuid

        self.stop()
        self.cancel = Event()
        generation, token = uuid.uuid4().hex, self.cancel
        self.generation = generation
        self.state = kind
        self.state_changed.emit(kind)

        def work():
            initialized = False
            try:
                try:
                    import pythoncom

                    pythoncom.CoInitialize()
                    initialized = True
                except ImportError:
                    pass
                self.waker.close()
                if not token.is_set():
                    function(generation, token)
            except Exception as exc:
                if not token.is_set():
                    self._error.emit(generation, str(exc))
            finally:
                if initialized:
                    pythoncom.CoUninitialize()
                self._state.emit(generation, "idle")

        self.pool.submit(work)

    def record(self):
        if not self.config.voice_enabled or self.config.asr_provider == "none":
            self.error.emit("请在设置中启用并配置语音识别")
            return
        self.stop_record = Event()
        stop, config = self.stop_record, self.config

        def work(generation, token):
            path = VoiceRecorderService().record(
                stop, token, int(config.input_device) if config.input_device else None
            )
            if not path:
                return
            try:
                self._state.emit(generation, "recognizing")
                text = ASRService(config).transcribe(path, token)
                if not token.is_set():
                    self._recognized.emit(generation, text)
            finally:
                Path(path).unlink(missing_ok=True)

        self._submit("recording", work)

    def finish_recording(self):
        self.stop_record.set()

    def speak(self, text):
        if self.config.tts_enabled and self.allowed:
            config = self.config
            self._submit(
                "speaking", lambda generation, token: TTSService(config).speak(text, token)
            )

    def stop(self):
        self.cancel.set()
        self.pause_wake()
        self.state = "idle"
        self.generation = ""
        self.state_changed.emit("idle")

    def shutdown(self):
        self.closed = True
        self.stop()
        self.pool.shutdown(wait=True, cancel_futures=True)
        self.waker.close()
