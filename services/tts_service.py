"""Edge 在线播报、系统离线播报，播放结束释放通道与临时文件。"""

import asyncio
import re
import tempfile
import time
from pathlib import Path


class TTSService:
    def __init__(self, config):
        self.config = config

    def speak(self, text, cancel):
        if not self.config.tts_enabled or cancel.is_set():
            return
        text = re.sub(r"```.*?```", "代码已显示在对话中。", text, flags=re.S)
        text = re.sub(r"[\*_#`]", "", text)[: self.config.tts_max_chars]
        if self.config.tts_provider == "system":
            return self._system(text, cancel)
        try:
            return asyncio.run(self._edge(text, cancel))
        except asyncio.CancelledError:
            return
        except Exception:
            if not cancel.is_set():
                return self._system(text, cancel)

    async def _edge(self, text, cancel):
        import edge_tts
        import pygame

        with tempfile.TemporaryDirectory(prefix="yuanbao-tts-") as directory:
            path = str(Path(directory) / "speech.mp3")
            task = asyncio.create_task(edge_tts.Communicate(text, self.config.tts_voice).save(path))
            try:
                while not task.done():
                    if cancel.is_set():
                        task.cancel()
                        raise asyncio.CancelledError()
                    await asyncio.sleep(0.05)
                await task
                if cancel.is_set():
                    return
                pygame.mixer.init()
                pygame.mixer.music.load(path)
                pygame.mixer.music.play()
                while pygame.mixer.music.get_busy() and not cancel.is_set():
                    await asyncio.sleep(0.05)
            finally:
                if not task.done():
                    task.cancel()
                    try:
                        await task
                    except asyncio.CancelledError:
                        pass
                if pygame.mixer.get_init():
                    pygame.mixer.music.stop()
                    pygame.mixer.music.unload()
                    pygame.mixer.quit()

    def _system(self, text, cancel):
        import pyttsx3

        engine = pyttsx3.init()
        try:
            engine.say(text)
            engine.startLoop(False)
            while engine.isBusy() and not cancel.is_set():
                engine.iterate()
                time.sleep(0.02)
        finally:
            engine.stop()
            try:
                engine.endLoop()
            except RuntimeError:
                pass
