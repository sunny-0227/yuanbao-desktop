"""
TTS（文字转语音）服务
支持 edge-tts（在线，中文效果好）和 pyttsx3（离线系统 TTS）两个 provider。
所有播报在后台线程执行，不阻塞 PySide6 UI。

防自激设计：
- is_speaking() 供 ChatWindow 检测，播报中禁止开始录音
- stop() 立即终止当前播报
"""

import os
import threading
import tempfile
from typing import Callable, Optional

from app.logger import setup_logger

logger = setup_logger()

# 默认配置
_DEFAULT_VOICE    = "zh-CN-XiaoxiaoNeural"
_DEFAULT_MAX_CHARS = 200
_TOO_LONG_MSG     = "回答内容较长，我已显示在窗口中。"


class TTSService:
    """
    文字转语音服务。

    provider 选择逻辑：
        "edge"   → edge-tts（在线，异步，中文效果好）
        "system" → pyttsx3（离线，系统 TTS）
        其他     → 静默不播报

    使用方式：
        tts = TTSService(
            enabled=True,
            provider="edge",
            voice="zh-CN-XiaoxiaoNeural",
            max_chars=200,
        )
        tts.set_callbacks(on_start=lambda: ..., on_done=lambda: ...)
        tts.speak("你好")
    """

    def __init__(
        self,
        enabled:   bool = True,
        provider:  str  = "edge",
        voice:     str  = _DEFAULT_VOICE,
        max_chars: int  = _DEFAULT_MAX_CHARS,
    ):
        self._enabled   = enabled
        self._provider  = provider
        self._voice     = voice
        self._max_chars = max_chars

        self._speaking   = False
        self._stop_event = threading.Event()
        self._lock       = threading.Lock()
        self._thread: Optional[threading.Thread] = None

        # 回调（在后台线程结束后通过 Qt QTimer.singleShot 安全回调主线程）
        self._on_start: Optional[Callable] = None
        self._on_done:  Optional[Callable] = None

    # ── 公开接口 ──────────────────────────────────────────────

    def set_callbacks(
        self,
        on_start: Optional[Callable] = None,
        on_done:  Optional[Callable] = None,
    ):
        """注册播报开始 / 结束回调（在主线程执行）"""
        self._on_start = on_start
        self._on_done  = on_done

    def speak(self, text: str):
        """
        后台播报文字。
        若当前已在播报，先停止再开始新播报。
        若 text 超过 max_chars，截断后加"[已截断]"或播报提示语。
        """
        if not self._enabled:
            logger.debug("TTS 未启用，跳过播报")
            return

        text = text.strip()
        if not text:
            return

        # 截断过长文本
        if len(text) > self._max_chars:
            logger.debug(f"TTS 文本过长（{len(text)} 字），截断到 {self._max_chars}")
            text = _TOO_LONG_MSG

        with self._lock:
            # 停止旧的播报线程
            if self._speaking:
                self._stop_event.set()
                if self._thread and self._thread.is_alive():
                    self._thread.join(timeout=1.0)

            self._stop_event.clear()
            self._speaking = True
            self._thread = threading.Thread(
                target=self._run,
                args=(text,),
                daemon=True,
                name="TTSWorker",
            )
            self._thread.start()

    def stop(self):
        """立即停止当前播报"""
        with self._lock:
            if self._speaking:
                self._stop_event.set()
                logger.debug("TTS stop() 已调用")

    def is_speaking(self) -> bool:
        """返回当前是否正在播报"""
        return self._speaking

    # ── 内部执行 ──────────────────────────────────────────────

    def _run(self, text: str):
        """后台线程入口：选择 provider 执行播报"""
        self._fire_callback(self._on_start)
        try:
            if self._provider == "edge":
                self._speak_edge(text)
            elif self._provider == "system":
                self._speak_pyttsx3(text)
            else:
                logger.debug(f"TTS provider={self._provider!r} 不支持，跳过")
        except Exception as e:
            logger.warning(f"TTS 播报失败（不影响程序）：{e}")
        finally:
            with self._lock:
                self._speaking = False
            self._fire_callback(self._on_done)

    def _speak_edge(self, text: str):
        """使用 edge-tts 播报（异步 → 同步封装）"""
        try:
            import edge_tts       # type: ignore
            import asyncio
            import pygame         # type: ignore  （用于播放 mp3）
        except ImportError as e:
            logger.debug(f"edge-tts / pygame 不可用，降级到 pyttsx3：{e}")
            self._speak_pyttsx3(text)
            return

        tmp_file = None
        try:
            # edge-tts 输出 mp3，保存到临时文件后用 pygame 播放
            tmp_file = tempfile.NamedTemporaryFile(
                suffix=".mp3", delete=False, prefix="tts_"
            )
            tmp_path = tmp_file.name
            tmp_file.close()

            # 同步运行异步的 edge-tts
            async def _tts_async():
                communicate = edge_tts.Communicate(text, self._voice)
                await communicate.save(tmp_path)

            asyncio.run(_tts_async())

            if self._stop_event.is_set():
                return

            # pygame 播放 mp3
            pygame.mixer.init()
            pygame.mixer.music.load(tmp_path)
            pygame.mixer.music.play()

            # 等待播放完毕或收到 stop 信号
            while pygame.mixer.music.get_busy():
                if self._stop_event.is_set():
                    pygame.mixer.music.stop()
                    break
                import time
                time.sleep(0.05)

            pygame.mixer.music.unload()

        except Exception as e:
            logger.debug(f"edge-tts 播放失败，降级到 pyttsx3：{e}")
            self._speak_pyttsx3(text)
        finally:
            if tmp_file and os.path.exists(tmp_path):
                try:
                    os.unlink(tmp_path)
                except Exception:
                    pass

    def _speak_pyttsx3(self, text: str):
        """使用 pyttsx3 离线 TTS 播报"""
        try:
            import pyttsx3   # type: ignore
        except ImportError:
            logger.warning("pyttsx3 不可用，TTS 功能不可用（pip install pyttsx3）")
            return

        try:
            engine = pyttsx3.init()
            # 尝试设置中文语速
            engine.setProperty("rate", 180)

            if self._stop_event.is_set():
                return

            engine.say(text)
            engine.runAndWait()
            engine.stop()
        except Exception as e:
            logger.warning(f"pyttsx3 播报失败：{e}")

    def _fire_callback(self, cb: Optional[Callable]):
        """在主线程安全触发回调（通过 QTimer.singleShot）"""
        if cb is None:
            return
        try:
            from PySide6.QtCore import QTimer
            QTimer.singleShot(0, cb)
        except Exception as e:
            logger.debug(f"TTS callback 触发失败：{e}")
