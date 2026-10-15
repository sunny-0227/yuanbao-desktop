"""可选 Vosk 离线唤醒；模型需用户准备，不持续调用云 API。"""

import json
from pathlib import Path
from queue import Empty, Queue
from threading import Event, Thread


class WakeService:
    def __init__(self, on_wake, on_error, on_stopped=lambda: None):
        self.on_wake, self.on_error = on_wake, on_error
        self.on_stopped = on_stopped
        self.thread = None
        self.stop_event = Event()

    def start(self, config):
        if self.thread and self.thread.is_alive():
            return
        self.stop_event = Event()
        self.thread = Thread(target=self._run, args=(config,), daemon=True, name="YuanbaoWake")
        self.thread.start()

    def stop(self):
        self.stop_event.set()

    def close(self):
        self.stop()
        if self.thread:
            self.thread.join(timeout=5)

    def _run(self, config):
        try:
            import sounddevice as sd
            from vosk import KaldiRecognizer, Model

            if not Path(config.wake_model_path).is_dir():
                raise ValueError("请在设置中指定已解压的 Vosk 中文唤醒模型目录")
            model = Model(config.wake_model_path)
            recognizer = KaldiRecognizer(model, 16000)
            audio = Queue(maxsize=16)

            def callback(indata, frames, stamp, status):
                if not audio.full():
                    audio.put_nowait(bytes(indata))

            device = int(config.input_device) if config.input_device else None
            with sd.RawInputStream(
                samplerate=16000,
                blocksize=4000,
                channels=1,
                dtype="int16",
                device=device,
                callback=callback,
            ):
                while not self.stop_event.is_set():
                    try:
                        value = audio.get(timeout=0.25)
                    except Empty:
                        continue
                    if recognizer.AcceptWaveform(value):
                        text = json.loads(recognizer.Result()).get("text", "").replace(" ", "")
                        if config.wake_word.replace(" ", "") in text:
                            self.stop_event.set()
                            self.on_wake()
            del recognizer, model
        except Exception as exc:
            if not self.stop_event.is_set():
                self.on_error("语音唤醒不可用：" + str(exc))

        finally:
            self.on_stopped()
