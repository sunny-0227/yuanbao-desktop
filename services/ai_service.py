"""
AI 问答服务
使用 httpx 调用兼容 OpenAI Chat Completions 格式的大模型 API。

默认对接 FreeLLMAPI（本地 OpenAI-compatible 代理）：
  AI_API_BASE_URL=http://localhost:3001/v1
  AI_API_KEY=freellmapi-你的统一key
  AI_MODEL_NAME=auto

同时兼容任何 OpenAI-compatible 服务：
  - OpenAI 官方（https://api.openai.com/v1）
  - DeepSeek（https://api.deepseek.com/v1）
  - 本地 Ollama（http://localhost:11434/v1）

设计原则：
- 配置优先级：.env 环境变量 > config.json > 代码默认值
- is_configured() 供外部检查能否发请求（Key 非空即视为已配置）
- ask_ai() 永不抛异常，所有错误均返回用户可读的中文字符串
- httpx 延迟导入：未安装时启动不崩溃，调用时给出安装提示
- 不在代码中硬编码任何 API Key
"""

import os
from typing import Optional

from app.config import AIConfig
from app.logger import setup_logger

logger = setup_logger()

# ── 默认 system prompt（可被 AIConfig.system_prompt 覆盖）──────
_DEFAULT_SYSTEM_PROMPT = (
    "你是一个 Windows 桌面 AI 效率助手，主要帮助用户处理学习、办公、"
    "资料搜索、文案生成、内容总结、代码解释和日常效率问题。"
    "回答要简洁、实用，优先使用中文。"
)

# 请求超时时间（秒）
_TIMEOUT_SECONDS = 30

# FreeLLMAPI 默认接入地址（.env 中 AI_API_BASE_URL 可覆盖）
_DEFAULT_BASE_URL = "http://localhost:3001/v1"


class AIService:
    """
    AI 问答服务（httpx 实现，兼容 OpenAI Chat Completions 接口）。

    默认对接本地 FreeLLMAPI，也支持所有兼容 OpenAI 格式的服务商。
    通过 .env 配置三个环境变量即可切换后端：
        AI_API_BASE_URL   接口根地址（含 /v1）
        AI_API_KEY        服务 unified key
        AI_MODEL_NAME     模型名，填 auto 由代理自动选择

    使用方式：
        svc = AIService(config=app_config.ai)
        reply = svc.ask_ai("帮我写一封请假邮件")
    """

    def __init__(self, config: Optional[AIConfig] = None):
        self._config = config or AIConfig()

        # 环境变量优先级 > config.json > 代码默认值
        self._api_key = (
            os.getenv("AI_API_KEY") or
            self._config.api_key
        )
        self._base_url = (
            os.getenv("AI_API_BASE_URL") or
            os.getenv("AI_BASE_URL")     or
            self._config.base_url        or
            _DEFAULT_BASE_URL
        )
        self._model = (
            os.getenv("AI_MODEL_NAME") or
            os.getenv("AI_MODEL")      or
            self._config.model         or
            "auto"
        )
        self._system_prompt = self._config.system_prompt or _DEFAULT_SYSTEM_PROMPT

    # ── 公开接口 ──────────────────────────────────────────────

    def ask_ai(self, user_text: str) -> str:
        """
        发送用户问题，返回 AI 回复字符串。
        所有异常均在内部捕获，不会向外抛出。

        参数：
            user_text: 用户输入的原始文本

        返回：
            AI 回复字符串；失败时返回用户可读的中文提示
        """
        if not self._api_key:
            logger.warning("AI API Key 未配置")
            return (
                "当前未配置 FreeLLMAPI unified key，"
                "请在 .env 中填写 AI_API_KEY=freellmapi-你的统一key"
            )

        messages = [
            {"role": "system", "content": self._system_prompt},
            {"role": "user",   "content": user_text},
        ]
        return self._do_request(messages)

    def is_configured(self) -> bool:
        """返回是否已配置 API Key，供外部检查使用"""
        return bool(self._api_key)

    # ── 私有方法 ──────────────────────────────────────────────

    def _do_request(self, messages: list) -> str:
        """
        实际发起 HTTP 请求。
        使用 httpx 同步客户端，超时 30 秒。
        所有异常均在此处捕获并转换为友好字符串。

        注意：此方法在 LocalCommandExecutor._ExecuteThread 中被调用，
        始终运行于后台线程，不会阻塞 PySide6 UI 主线程。
        """
        try:
            import httpx
        except ImportError:
            logger.error("未安装 httpx，无法调用 AI")
            return "AI 功能需要安装 httpx，请运行：pip install httpx"

        # 去掉末尾斜杠，拼接标准路径
        base = self._base_url.rstrip("/")
        url  = f"{base}/chat/completions"

        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type":  "application/json",
        }
        payload = {
            "model":       self._model,       # "auto" 直接透传，由代理处理
            "messages":    messages,
            "temperature": self._config.temperature,
            "max_tokens":  self._config.max_tokens,
        }

        logger.debug(f"AI 请求：model={self._model}  url={url}")

        try:
            with httpx.Client(timeout=_TIMEOUT_SECONDS) as client:
                resp = client.post(url, headers=headers, json=payload)

            # ── 处理 HTTP 错误状态码 ────────────────────────────
            if resp.status_code == 401:
                logger.error("FreeLLMAPI unified key 无效（401）")
                return (
                    "⚠️ FreeLLMAPI unified key 无效，"
                    "请检查 Keys 页面复制的 key 是否完整填入 .env。"
                )
            if resp.status_code == 429:
                logger.warning("FreeLLMAPI 额度受限（429）")
                return (
                    "⚠️ 当前免费模型额度可能暂时受限，"
                    "请稍后重试或检查 fallback chain 配置。"
                )
            if resp.status_code >= 500:
                logger.error(f"FreeLLMAPI 服务端错误：{resp.status_code}")
                return f"⚠️ FreeLLMAPI 服务暂时不可用（{resp.status_code}），请稍后再试。"

            resp.raise_for_status()

            data  = resp.json()
            reply = data["choices"][0]["message"]["content"]
            logger.debug(f"AI 回复长度：{len(reply)} 字符")
            return reply.strip()

        except httpx.ConnectError:
            # 最常见：FreeLLMAPI 未启动或端口不对
            host = self._base_url.split("/v1")[0] if "/v1" in self._base_url else self._base_url
            logger.error(f"无法连接 FreeLLMAPI（ConnectError）：{self._base_url}")
            return (
                f"当前无法连接本地 FreeLLMAPI 服务，"
                f"请确认 {host} 已启动。"
            )
        except httpx.TimeoutException:
            logger.error("AI 请求超时（>30s）")
            return "⚠️ AI 响应超时（>30s），请检查 FreeLLMAPI 服务是否正常运行。"
        except (KeyError, IndexError, ValueError) as e:
            logger.error(f"AI 响应解析失败：{e}")
            return "⚠️ AI 返回了无法解析的数据，请稍后重试。"
        except Exception as e:
            logger.error(f"AI 调用异常：{e}")
            return f"⚠️ AI 服务出错：{e}"
