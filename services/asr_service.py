"""
ASR（语音识别）服务 — 第一阶段接口占位

设计说明：
- 第一阶段 asr_provider=none，只保存录音文件，不做语音转文字
- 预留 whisper 和 online 结构，后续可方便接入 faster-whisper 或在线 API
- 所有异常捕获，不崩溃

后续扩展指引：
    接入 faster-whisper：在 _transcribe_whisper() 中实现
    接入在线 ASR：     在 _transcribe_online() 中实现
    修改 asr_provider：  在 config.json 或 .env 中设置 ASR_PROVIDER=whisper
"""

import os
from app.logger import setup_logger

logger = setup_logger()

# 用户友好提示常量
_MSG_NOT_CONFIGURED = (
    "当前未配置语音识别服务，请在设置中选择 ASR_PROVIDER。\n"
    "（录音文件已保存，配置后可重新识别）"
)
_MSG_FILE_NOT_FOUND = "录音文件不存在，无法识别。"


class ASRService:
    """
    语音识别服务（第一阶段：接口占位）。

    provider 说明：
        none    → 不识别，返回友好提示（默认）
        whisper → 本地 Whisper 模型（待实现）
        online  → 在线 ASR API（待实现）

    使用方式：
        asr = ASRService(provider="none")
        text = asr.transcribe("/path/to/voice.wav")
    """

    def __init__(self, provider: str = "none"):
        self._provider = provider.lower().strip()
        logger.debug(f"ASRService 初始化，provider={self._provider!r}")

    # ── 公开接口 ──────────────────────────────────────────────

    def transcribe(self, file_path: str) -> str:
        """
        识别音频文件，返回识别文本。
        失败或未配置时返回友好提示字符串（非异常）。
        """
        if not file_path or not os.path.exists(file_path):
            logger.warning(f"ASR：文件不存在 {file_path!r}")
            return _MSG_FILE_NOT_FOUND

        try:
            if self._provider == "none":
                return _MSG_NOT_CONFIGURED

            if self._provider == "whisper":
                return self._transcribe_whisper(file_path)

            if self._provider == "online":
                return self._transcribe_online(file_path)

            logger.warning(f"ASR：未知 provider={self._provider!r}")
            return _MSG_NOT_CONFIGURED

        except Exception as e:
            logger.error(f"ASR 识别异常（{file_path}）：{e}")
            return f"语音识别出错：{e}"

    # ── 预留实现（后续扩展）──────────────────────────────────

    def _transcribe_whisper(self, file_path: str) -> str:
        """
        使用本地 Whisper / faster-whisper 模型识别。
        第一阶段未实现，返回提示。

        后续扩展示例（faster-whisper）：
            from faster_whisper import WhisperModel
            model = WhisperModel("small", device="cpu", compute_type="int8")
            segments, _ = model.transcribe(file_path, language="zh")
            return "".join(s.text for s in segments)
        """
        logger.info("ASR whisper provider 尚未实现，请参考代码注释接入 faster-whisper")
        return (
            "Whisper 语音识别尚未配置。\n"
            "如需启用，请安装 faster-whisper 并在代码中实现 _transcribe_whisper()。"
        )

    def _transcribe_online(self, file_path: str) -> str:
        """
        使用在线 ASR API 识别（如讯飞、百度、阿里等）。
        第一阶段未实现，返回提示。

        后续扩展示例（以讯飞为例）：
            import requests
            # 构造 API 请求...
            resp = requests.post(api_url, files={"audio": open(file_path, "rb")}, ...)
            return resp.json()["result"]
        """
        logger.info("ASR online provider 尚未实现，请参考代码注释接入在线 ASR")
        return (
            "在线语音识别尚未配置。\n"
            "如需启用，请在 .env 中填写 ASR_API_KEY 并在代码中实现 _transcribe_online()。"
        )
