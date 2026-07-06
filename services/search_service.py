"""
网页搜索服务
调用系统默认浏览器打开搜索结果页，支持 bing / baidu / google。

职责：
- 拼接搜索 URL（关键词做 URL 编码，支持中文）
- 使用 webbrowser.open 打开浏览器（跨平台可用，不需要平台判断）
- 从 SearchConfig 读取默认引擎和各引擎 URL 模板
- 所有异常捕获后返回友好字符串，不崩溃
"""

import webbrowser
from urllib.parse import quote
from typing import Optional

from app.config import SearchConfig
from app.logger import setup_logger

logger = setup_logger()

# 内置兜底引擎配置，当 config 未传入时使用
_DEFAULT_ENGINES: dict[str, str] = {
    "bing":   "https://www.bing.com/search?q=",
    "baidu":  "https://www.baidu.com/s?wd=",
    "google": "https://www.google.com/search?q=",
}
_DEFAULT_ENGINE = "bing"


class SearchService:
    """
    网页搜索服务。

    实例化时可传入 SearchConfig，否则使用内置默认配置。

    使用方式：
        service = SearchService(config=app_config.search)
        reply = service.search_web("Python 教程")
        # → "已为你搜索：Python 教程。"
    """

    def __init__(self, config: Optional[SearchConfig] = None):
        self._config = config

    # ── 公开接口 ──────────────────────────────────────────────

    def search_web(self, keyword: str, engine: str = "") -> str:
        """
        在浏览器中打开指定关键词的搜索结果页。

        参数：
            keyword: 搜索关键词，支持中文
            engine:  搜索引擎名称，为空时使用 config 中配置的默认引擎

        返回：
            展示给用户的结果字符串
        """
        keyword = keyword.strip() if keyword else ""
        if not keyword:
            return "请输入要搜索的内容。"

        # 确定使用的引擎
        resolved_engine = self._resolve_engine(engine)

        # 拼接搜索 URL（关键词做 URL 编码，safe="" 确保中文也被编码）
        base_url = self._get_base_url(resolved_engine)
        encoded  = quote(keyword, safe="")
        url      = base_url + encoded

        logger.debug(f"搜索：engine={resolved_engine}  keyword={keyword!r}  url={url}")

        try:
            # webbrowser.open 在 Windows/Mac/Linux 上均可调用系统默认浏览器
            webbrowser.open(url)
            engine_label = self._engine_label(resolved_engine)
            return f"已为你搜索：{keyword}。\n（使用 {engine_label}）"
        except Exception as e:
            logger.error(f"打开浏览器失败：{e}")
            return f"⚠️ 打开浏览器失败：{e}\n你可以手动访问：{url}"

    def get_supported_engines(self) -> list[str]:
        """返回当前支持的所有搜索引擎名称列表"""
        engines = self._config.engines if self._config else _DEFAULT_ENGINES
        return list(engines.keys())

    # ── 内部工具 ──────────────────────────────────────────────

    def _resolve_engine(self, engine: str) -> str:
        """
        确定最终使用的引擎名称。
        优先级：调用方传入的 engine > config.engine > 内置默认 bing。
        未知引擎名称时自动降级到 bing。
        """
        engines = self._config.engines if self._config else _DEFAULT_ENGINES

        # 调用方明确指定了引擎
        if engine and engine.lower() in engines:
            return engine.lower()

        # 使用 config 中配置的默认引擎
        if self._config and self._config.engine in engines:
            return self._config.engine

        return _DEFAULT_ENGINE

    def _get_base_url(self, engine: str) -> str:
        """返回指定引擎的搜索 URL 前缀，未知引擎返回 bing"""
        engines = self._config.engines if self._config else _DEFAULT_ENGINES
        return engines.get(engine, _DEFAULT_ENGINES["bing"])

    @staticmethod
    def _engine_label(engine: str) -> str:
        """将引擎 key 转为显示名称"""
        labels = {
            "bing":   "必应 Bing",
            "baidu":  "百度",
            "google": "谷歌 Google",
        }
        return labels.get(engine, engine.capitalize())
