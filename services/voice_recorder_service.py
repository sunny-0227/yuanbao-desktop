"""
语音录音服务
使用 sounddevice + wave 录制麦克风输入，保存为 WAV 文件。
优先使用 sounddevice，不可用时返回友好提示。
不做持续后台监听，不做唤醒词，必须显式 start/stop。
"""

import os
import wave
import threading
from datetime import datetime
from typing import Callable, Optional

from app.app_context import data_path
from app.logger import setup_logger

logger = setup_logger()

# 录音参数
_SAMPLERATE  = 16000   # 16kHz（ASR 友好）
_CHANNELS    = 1       # 单声道
_DTYPE       = "int16"
_VOICE_DIR   = "voice_records"


class VoiceRecorderService:
    """
    麦克风录音服务。

    使用方式：
        recorder = VoiceRecorderService()
        recorder.set_callbacks(on_start=..., on_done=..., on_error=...)
        recorder.start_recording()
        # ...
        path = recorder.stop_recording()   # 返回 wav 文件路径

    非 Windows 也可用（sounddevice 跨平台），
    sounddevice 不可用时回调 on_error 并不崩溃。
    """

    def __init__(self):
        self._recording  = False
        self._cancelled  = False
        self._frames: list = []
        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._done_path: str = ""        # 最后一次录音路径

        self._on_start: Optional[Callable]       = None
        self._on_done:  Optional[Callable[[str], None]] = None   # 参数：文件路径
        self._on_error: Optional[Callable[[str], None]] = None   # 参数：错误信息

    # ── 公开接口 ──────────────────────────────────────────────

    def set_callbacks(
        self,
        on_start: Optional[Callable]              = None,
        on_done:  Optional[Callable[[str], None]] = None,
        on_error: Optional[Callable[[str], None]] = None,
    ):
        self._on_start = on_start
        self._on_done  = on_done
        self._on_error = on_error

    def start_recording(self) -> bool:
        """
        开始录音（后台线程）。
        返回 True 表示成功启动，False 表示已在录音或不可用。
        """
        if self._recording:
            logger.debug("已在录音中，忽略重复 start_recording()")
            return False

        self._frames     = []
        self._cancelled  = False
        self._done_path  = ""
        self._stop_event.clear()
        self._recording  = True

        self._thread = threading.Thread(
            target=self._record_worker,
            daemon=True,
            name="VoiceRecorder",
        )
        self._thread.start()
        return True

    def stop_recording(self) -> str:
        """
        停止录音，等待线程结束，返回保存的 wav 文件路径（空字符串表示失败）。
        """
        if not self._recording:
            return ""
        self._stop_event.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=5.0)
        return self._done_path

    def cancel_recording(self):
        """取消录音（不保存文件）"""
        self._cancelled = True
        self._stop_event.set()

    def is_recording(self) -> bool:
        return self._recording

    # ── 内部录音线程 ──────────────────────────────────────────

    def _record_worker(self):
        """后台录音线程"""
        self._fire_cb(self._on_start, None)

        try:
            import sounddevice as sd   # type: ignore
        except ImportError:
            self._recording = False
            msg = "sounddevice 未安装，无法录音（pip install sounddevice）"
            logger.warning(msg)
            self._fire_cb(self._on_error, msg)
            return

        # 检查麦克风
        try:
            devices = sd.query_devices()
            has_input = any(
                d.get("max_input_channels", 0) > 0
                for d in (devices if isinstance(devices, list) else [devices])
            )
            if not has_input:
                raise RuntimeError("未检测到可用麦克风")
        except Exception as e:
            self._recording = False
            msg = f"未检测到可用麦克风，请检查录音设备。({e})"
            logger.warning(msg)
            self._fire_cb(self._on_error, msg)
            return

        frames = []
        try:
            import numpy as np   # type: ignore

            def _callback(indata, _frames, _time, status):
                if status:
                    logger.debug(f"录音状态：{status}")
                frames.append(indata.copy())

            with sd.InputStream(
                samplerate=_SAMPLERATE,
                channels=_CHANNELS,
                dtype=_DTYPE,
                callback=_callback,
            ):
                logger.debug("录音开始")
                self._stop_event.wait()   # 阻塞直到 stop() 或 cancel()

            logger.debug("录音结束")

        except Exception as e:
            self._recording = False
            msg = f"录音出错：{e}"
            logger.error(msg)
            self._fire_cb(self._on_error, msg)
            return
        finally:
            self._recording = False

        if self._cancelled or not frames:
            logger.debug("录音已取消或无数据，不保存文件")
            return

        # 保存 wav
        try:
            import numpy as np
            save_path = self._save_wav(frames, np)
            self._done_path = save_path
            logger.info(f"录音已保存：{save_path}")
            self._fire_cb(self._on_done, save_path)
        except Exception as e:
            msg = f"保存录音文件失败：{e}"
            logger.error(msg)
            self._fire_cb(self._on_error, msg)

    def _save_wav(self, frames: list, np) -> str:
        """将 frames 拼接并保存为 wav 文件，返回文件路径"""
        voice_dir = data_path(_VOICE_DIR)
        os.makedirs(voice_dir, exist_ok=True)

        timestamp = datetime.now().strftime("voice_%Y%m%d_%H%M%S")
        file_path = os.path.join(voice_dir, f"{timestamp}.wav")

        audio_data = np.concatenate(frames, axis=0)

        with wave.open(file_path, "wb") as wf:
            wf.setnchannels(_CHANNELS)
            wf.setsampwidth(2)          # int16 = 2 bytes
            wf.setframerate(_SAMPLERATE)
            wf.writeframes(audio_data.tobytes())

        return file_path

    def _fire_cb(self, cb, arg):
        """主线程安全回调"""
        if cb is None:
            return
        try:
            from PySide6.QtCore import QTimer
            if arg is None:
                QTimer.singleShot(0, cb)
            else:
                QTimer.singleShot(0, lambda: cb(arg))
        except Exception as e:
            logger.debug(f"VoiceRecorder callback 触发失败：{e}")
