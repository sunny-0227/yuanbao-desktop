"""在线 OpenAI-compatible 转写与 Faster-Whisper 按需识别。"""

import asyncio
import multiprocessing
import os
import time
from queue import Empty

from app.config import VoiceConfig


class ASRService:
    def __init__(self, config=None):
        self.config = config or VoiceConfig()

    def transcribe(self, file_path, cancel=None):
        from threading import Event

        cancel = cancel or Event()
        if not file_path or not os.path.isfile(file_path):
            raise ValueError("录音文件不存在")
        if cancel.is_set():
            return ""
        provider = self.config.asr_provider
        if provider == "none":
            raise ValueError("请先在设置中选择在线或本地语音识别")
        if provider in ("online", "auto"):
            try:
                return asyncio.run(self._online(file_path, cancel))
            except asyncio.CancelledError:
                return ""
            except Exception:
                if provider != "auto" or cancel.is_set():
                    raise
        return self._offline(file_path, cancel)

    async def _online(self, path, cancel):
        import httpx

        if not self.config.asr_url:
            raise ValueError("请配置语音识别 API 根地址")
        headers = {"Authorization": "Bearer " + self.config.asr_key} if self.config.asr_key else {}
        async with httpx.AsyncClient(timeout=30) as client:
            with open(path, "rb") as stream:
                task = asyncio.create_task(
                    client.post(
                        self.config.asr_url.rstrip("/") + "/audio/transcriptions",
                        headers=headers,
                        files={"file": ("voice.wav", stream, "audio/wav")},
                        data={"model": self.config.asr_model, "language": "zh"},
                    )
                )
                while not task.done():
                    if cancel.is_set():
                        task.cancel()
                        try:
                            await task
                        except asyncio.CancelledError:
                            pass
                        raise asyncio.CancelledError()
                    await asyncio.sleep(0.05)
                response = await task
                response.raise_for_status()
                return response.json()["text"].strip()

    def _offline(self, path, cancel):
        # 重模型在短生命周期子进程中运行；结束/取消后由 OS 释放完整模型内存。
        context = multiprocessing.get_context("spawn")
        output = context.Queue()
        process = context.Process(
            target=_whisper_worker, args=(path, self.config.offline_model, output), daemon=True
        )
        process.start()
        deadline = time.monotonic() + 120
        try:
            while True:
                if cancel.is_set():
                    return ""
                if time.monotonic() > deadline:
                    raise TimeoutError("本地语音识别超过120秒，请换用更小模型或在线接口")
                try:
                    ok, text = output.get(timeout=0.1)
                    if not ok:
                        raise RuntimeError(text)
                    return text
                except Empty:
                    if not process.is_alive():
                        raise RuntimeError("本地识别进程未返回结果，请检查模型与依赖") from None
        finally:
            if process.is_alive():
                process.terminate()
            process.join(timeout=5)
            if process.is_alive():
                process.kill()
                process.join()
            output.close()
            process.close()


def _whisper_worker(path, model_path, output):
    """子进程不导入 Qt 或加载配置，只完成一次转写。"""
    try:
        from faster_whisper import WhisperModel

        model = WhisperModel(model_path, device="cpu", compute_type="int8", local_files_only=True)
        segments, _ = model.transcribe(path, language="zh", beam_size=1, vad_filter=True)
        output.put((True, "".join(segment.text for segment in segments).strip()))
    except Exception as exc:
        output.put(
            (False, "本地识别不可用，请检查 requirements-voice-local.txt 与已下载模型：" + str(exc))
        )
