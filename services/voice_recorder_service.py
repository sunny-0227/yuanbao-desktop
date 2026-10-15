"""录音资源只在用户录音时创建，最长 30 秒，停止必关闭音频流。"""

import time
import uuid
import wave
from pathlib import Path

from app.app_context import data_path


class VoiceRecorderService:
    def record(self, stop, cancel, device=None):
        try:
            import numpy as np
            import sounddevice as sd
        except ImportError as exc:
            raise RuntimeError("录音需要安装 sounddevice 和 numpy") from exc
        chunks = []

        def callback(indata, frames, stamp, status):
            # 回调只复制数据，禁止文件 IO、识别或操作界面。
            chunks.append(indata.copy())

        with sd.InputStream(
            samplerate=16000, channels=1, dtype="int16", device=device or None, callback=callback
        ):
            start = time.monotonic()
            while not stop.is_set() and not cancel.is_set() and time.monotonic() - start < 30:
                time.sleep(0.05)
        if cancel.is_set():
            return ""
        if not chunks:
            raise RuntimeError("没有录到声音，请检查输入设备")
        path = Path(data_path("voice")) / (uuid.uuid4().hex + ".wav")
        path.parent.mkdir(parents=True, exist_ok=True)
        with wave.open(str(path), "wb") as stream:
            stream.setnchannels(1)
            stream.setsampwidth(2)
            stream.setframerate(16000)
            stream.writeframes(np.concatenate(chunks).tobytes())
        return str(path)

    @staticmethod
    def devices():
        import sounddevice as sd

        return [
            (str(i), d["name"])
            for i, d in enumerate(sd.query_devices())
            if d["max_input_channels"] > 0
        ]
