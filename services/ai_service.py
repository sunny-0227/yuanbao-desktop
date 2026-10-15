"""流式多轮 AI 客户端：取消、限流切换、离线端点与明确错误。"""

import asyncio
import json

from app.config import AppConfig
from services.cache_service import CacheService


class AIError(RuntimeError):
    pass


class AIService:
    def __init__(self, config=None, db=None):
        config = config or AppConfig()
        self.config = config
        self.cache = CacheService(config.ai.enable_ai_cache, db)
        self.last_usage = {}

    def endpoints(self):
        ai = self.config.ai
        if ai.provider == "none":
            return []
        default = (
            "http://localhost:3001/v1"
            if ai.provider == "freellmapi"
            else "https://api.openai.com/v1"
        )
        endpoints = [{"base_url": ai.base_url or default, "api_key": ai.api_key, "model": ai.model}]
        endpoints += self.config.ai_endpoints
        if self.config.offline_ai_url and self.config.offline_ai_model:
            endpoints += [
                {
                    "base_url": self.config.offline_ai_url,
                    "api_key": "",
                    "model": self.config.offline_ai_model,
                }
            ]
        return endpoints

    def is_configured(self):
        return bool(self.endpoints()) and any(
            e.get("api_key") or e["base_url"].startswith(("http://localhost", "http://127.0.0.1"))
            for e in self.endpoints()
        )

    async def _request(self, endpoint, messages, on_chunk):
        import httpx

        headers = (
            {"Authorization": "Bearer " + endpoint["api_key"]} if endpoint.get("api_key") else {}
        )
        payload = {
            "model": endpoint["model"],
            "messages": messages,
            "stream": True,
            "temperature": self.config.ai.temperature,
            "max_tokens": self.config.ai.max_tokens,
        }
        async with httpx.AsyncClient(timeout=httpx.Timeout(30, connect=10)) as client:
            async with client.stream(
                "POST",
                endpoint["base_url"].rstrip("/") + "/chat/completions",
                headers=headers,
                json=payload,
            ) as response:
                if response.status_code >= 400:
                    await response.aread()
                    response.raise_for_status()
                if "text/event-stream" not in response.headers.get("content-type", ""):
                    data = json.loads(await response.aread())
                    answer = data["choices"][0]["message"]["content"]
                    self.last_usage = data.get("usage", {})
                    if not isinstance(answer, str) or not answer.strip():
                        raise AIError("接口没有返回有效文字")
                    on_chunk(answer)
                    return answer
                parts = []
                async for line in response.aiter_lines():
                    if not line.startswith("data:"):
                        continue
                    value = line[5:].strip()
                    if value == "[DONE]":
                        break
                    data = json.loads(value)
                    if data.get("usage"):
                        self.last_usage = data["usage"]
                    for choice in data.get("choices", []):
                        chunk = choice.get("delta", {}).get("content") or ""
                        if chunk:
                            if not isinstance(chunk, str):
                                raise AIError("接口流式内容不是文字")
                            parts.append(chunk)
                            on_chunk(chunk)
                if not parts:
                    raise AIError("接口没有返回文字内容")
                return "".join(parts)

    async def _run(self, context, cancel, on_chunk, on_status):
        import httpx

        messages = [{"role": "system", "content": self.config.ai.system_prompt}] + context
        errors = []
        for index, endpoint in enumerate(self.endpoints()):
            if cancel.is_set():
                raise asyncio.CancelledError()
            key = self.cache.key(
                messages,
                endpoint["model"],
                endpoint["base_url"],
                temperature=self.config.ai.temperature,
                max_tokens=self.config.ai.max_tokens,
            )
            cached = self.cache.get(key)
            if cached:
                on_chunk(cached)
                return cached
            on_status("正在连接模型" if not index else "正在切换备用模型")
            received = False

            def chunk(value):
                nonlocal received
                received = True
                on_chunk(value)

            request = asyncio.create_task(self._request(endpoint, messages, chunk))
            try:
                while not request.done():
                    if cancel.is_set():
                        request.cancel()
                        try:
                            await request
                        except asyncio.CancelledError:
                            pass
                        raise asyncio.CancelledError()
                    await asyncio.sleep(0.05)
                answer = await request
                if not cancel.is_set():
                    self.cache.save(key, answer)
                return answer
            except httpx.HTTPStatusError as exc:
                code = exc.response.status_code
                errors.append(f"接口 {index + 1}：HTTP {code}")
                if received or code not in (401, 403, 408, 429, 500, 502, 503, 504):
                    break
            except (
                httpx.RequestError,
                AIError,
                ValueError,
                KeyError,
                IndexError,
                TypeError,
            ) as exc:
                errors.append(f"接口 {index + 1}：{type(exc).__name__}")
                if received:
                    break
        raise AIError("AI 暂时不可用。请检查接口地址、密钥、模型或额度。" + "；".join(errors))

    def ask(self, context, cancel, on_chunk=lambda text: None, on_status=lambda text: None):
        if not self.is_configured():
            raise AIError("请在设置中配置 AI 接口、密钥和模型；本地指令仍可使用。")
        try:
            return asyncio.run(self._run(context, cancel, on_chunk, on_status))
        except asyncio.CancelledError:
            return None
