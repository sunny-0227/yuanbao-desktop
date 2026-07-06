"""
AI 问答服务
使用 httpx 调用兼容 OpenAI Chat Completions 格式的大模型 API。

设计原则：
- API 配置优先从环境变量读取（.env），其次从 AIConfig 对象读取
- 提供 ask_ai(user_text) 简单接口，屏蔽底层 HTTP 细节
- 未配置 API Key 时返回友好提示，不抛异常
- 请求超时 30 秒；网络/API 异常全部捕获并返回友好字符串
- API Key 不写死在代码里，全部来自环境变量或 config 注入
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


class AIService:
    """
    AI 问答服务（httpx 实现，兼容 OpenAI Chat Completions 接口）。

    支持所有兼容 OpenAI 接口的服务商：
      - OpenAI（gpt-4o / gpt-4o-mini）
      - DeepSeek（deepseek-chat）
      - 本地 Ollama（http://localhost:11434/v1）
      - 任何兼容接口（通过 base_url 指定）

    使用方式：
        svc = AIService(config=app_config.ai)
        reply = svc.ask_ai("帮我写一封请假邮件")
    """

    def __init__(self, config: Optional[AIConfig] = None):
        self._config = config or AIConfig()
        # 环境变量优先级高于 config 文件
        self._api_key  = os.getenv("AI_API_KEY")  or self._config.api_key
        self._base_url = (
            os.getenv("AI_API_BASE_URL") or
            os.getenv("AI_BASE_URL")     or
            self._config.base_url        or
            "https://api.openai.com/v1"
        )
        self._model = (
            os.getenv("AI_MODEL_NAME") or
            os.getenv("AI_MODEL")      or
            self._config.model         or
            "gpt-4o-mini"
        )
        # 使用 AIConfig 中的 system_prompt，若与默认相同则无需覆盖
        self._system_prompt = self._config.system_prompt or _DEFAULT_SYSTEM_PROMPT

    # ── 公开接口 ──────────────────────────────────────────────

    def ask_ai(self, user_text: str) -> str:
        """
        发送用户问题，返回 AI 回复字符串。
        所有异常均在内部捕获，不会向外抛出。

        参数：
            user_text: 用户输入的原始文本

        返回：
            AI 回复字符串；失败时返回友好提示
        """
        # 未配置 API Key 时直接返回提示
        if not self._api_key:
            logger.warning("AI API Key 未配置")
            return "当前未配置 AI API，请在 .env 中填写模型配置。"

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
        """
        try:
            import httpx  # 延迟导入，避免未安装时启动崩溃
        except ImportError:
            logger.error("未安装 httpx，无法调用 AI")
            return "AI 功能需要安装 httpx，请运行：pip install httpx"

        # 拼接请求 URL（去掉末尾斜杠后加路径）
        base = self._base_url.rstrip("/")
        url  = f"{base}/chat/completions"

        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type":  "application/json",
        }
        payload = {
            "model":       self._model,
            "messages":    messages,
            "temperature": self._config.temperature,
            "max_tokens":  self._config.max_tokens,
        }

        logger.debug(f"AI 请求：model={self._model}  url={url}")

        try:
            with httpx.Client(timeout=_TIMEOUT_SECONDS) as client:
                resp = client.post(url, headers=headers, json=payload)

            # 处理 HTTP 错误状态码
            if resp.status_code == 401:
                logger.error("AI API Key 无效或已过期（401）")
                return "⚠️ AI API Key 无效，请检查 .env 中的配置。"
            if resp.status_code == 429:
                logger.warning("AI API 请求频率超限（429）")
                return "⚠️ 请求太频繁，请稍后再试。"
            if resp.status_code >= 500:
                logger.error(f"AI 服务端错误：{resp.status_code}")
                return f"⚠️ AI 服务暂时不可用（{resp.status_code}），请稍后再试。"

            resp.raise_for_status()

            data   = resp.json()
            reply  = data["choices"][0]["message"]["content"]
            logger.debug(f"AI 回复长度：{len(reply)} 字符")
            return reply.strip()

        except httpx.TimeoutException:
            logger.error("AI 请求超时（>30s）")
            return "⚠️ AI 响应超时，请稍后再试。"
        except httpx.ConnectError:
            logger.error("AI API 连接失败（网络不可达）")
            return "⚠️ 无法连接 AI 服务，请检查网络或 API 地址配置。"
        except (KeyError, IndexError, ValueError) as e:
            logger.error(f"AI 响应解析失败：{e}")
            return "⚠️ AI 返回了无法解析的数据，请稍后重试。"
        except Exception as e:
            logger.error(f"AI 调用异常：{e}")
            return f"⚠️ AI 服务出错：{e}"
