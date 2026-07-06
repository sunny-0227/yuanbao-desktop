"""
AI 问答本地缓存服务
将 AI 回复缓存到 data/chat_cache.json，避免相同问题重复请求。

设计原则：
- 缓存开关由 AIConfig.enable_ai_cache 控制；关闭时 get/save 均为空操作
- 以问题的规范化文本为 key（去空格、统一小写），提高命中率
- 缓存文件不存在时自动创建；JSON 损坏时备份为 .bak 并重置
- 缓存条目包含 answer 和 created_at，便于后续做过期清理
- 所有文件操作全部捕获异常，不影响主程序运行
"""

import json
import os
from datetime import datetime
from typing import Optional

from app.app_context import resource_path, data_path
from app.logger import setup_logger

logger = setup_logger()

# 缓存文件路径：使用 data_path 保证打包后写入 exe 同目录（而非 _MEIPASS 临时目录）
_CACHE_PATH = data_path(os.path.join("data", "chat_cache.json"))

# 缓存 key 的最大长度（超长 key 直接截断，防止文件膨胀）
_MAX_KEY_LEN = 200


# ── 私有工具函数 ──────────────────────────────────────────────

def _normalize_key(question: str) -> str:
    """
    将问题文本规范化为缓存 key：
    去除首尾空格、统一转小写、压缩内部空白。
    超长时截断为前 _MAX_KEY_LEN 个字符。
    """
    key = " ".join(question.strip().lower().split())
    return key[:_MAX_KEY_LEN]


def _load_cache() -> dict:
    """
    从 chat_cache.json 加载缓存字典。
    文件不存在时返回空字典；
    JSON 损坏时自动备份为 .bak 并重置，不崩溃。
    """
    if not os.path.exists(_CACHE_PATH):
        return {}
    try:
        with open(_CACHE_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except json.JSONDecodeError:
        # 文件损坏：备份后重置
        backup_path = _CACHE_PATH + ".bak"
        try:
            os.replace(_CACHE_PATH, backup_path)
            logger.warning(f"chat_cache.json 格式异常，已备份到 {backup_path}，重置为空缓存")
            # 立即写入空缓存，避免下次加载前程序异常时再次触发备份逻辑
            _save_cache({})
        except Exception as backup_err:
            logger.error(f"备份/重置 chat_cache.json 失败：{backup_err}")
        return {}
    except Exception as e:
        logger.error(f"加载缓存文件失败：{e}")
        return {}


def _save_cache(cache: dict) -> None:
    """将缓存字典写入 chat_cache.json，目录不存在时自动创建。"""
    try:
        os.makedirs(os.path.dirname(_CACHE_PATH), exist_ok=True)
        with open(_CACHE_PATH, "w", encoding="utf-8") as f:
            json.dump(cache, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.error(f"保存缓存文件失败：{e}")


# ── 服务类 ────────────────────────────────────────────────────

class CacheService:
    """
    AI 问答本地缓存服务。

    enable 参数对应 config.json 的 ai.enable_ai_cache 开关。
    关闭时，get_cached_answer 始终返回 None，save_answer 为空操作，
    对调用方透明，无需在外部判断开关状态。

    使用方式：
        cache = CacheService(enable=config.ai.enable_ai_cache)
        answer = cache.get_cached_answer(user_text)
        if answer is None:
            answer = ai_service.ask_ai(user_text)
            cache.save_answer(user_text, answer)
    """

    def __init__(self, enable: bool = True):
        # 是否启用缓存
        self._enable = enable
        if enable:
            logger.debug("AI 回复缓存已启用")
        else:
            logger.debug("AI 回复缓存已关闭（config: enable_ai_cache=false）")

    # ── 公开接口 ─────────────────────────────────────────────

    def get_cached_answer(self, question: str) -> Optional[str]:
        """
        查询缓存。
        命中时返回缓存的回答字符串；未命中或缓存关闭时返回 None。
        """
        if not self._enable or not question.strip():
            return None
        try:
            cache = _load_cache()
            key   = _normalize_key(question)
            entry = cache.get(key)
            if entry and isinstance(entry, dict):
                answer = entry.get("answer", "")
                if answer:
                    logger.debug(f"缓存命中：{key[:40]!r}…")
                    return answer
        except Exception as e:
            logger.error(f"读取缓存失败：{e}")
        return None

    def save_answer(self, question: str, answer: str) -> None:
        """
        保存一条问答到缓存。
        缓存关闭、问题或答案为空时静默跳过。
        """
        if not self._enable:
            return
        if not question.strip() or not answer.strip():
            return
        try:
            cache = _load_cache()
            key   = _normalize_key(question)
            cache[key] = {
                "answer":     answer,
                "created_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
            }
            _save_cache(cache)
            logger.debug(f"缓存已保存：{key[:40]!r}…  ({len(cache)} 条)")
        except Exception as e:
            logger.error(f"保存缓存失败：{e}")

    def clear(self) -> None:
        """清空全部缓存（调试 / 用户主动清除时使用）"""
        try:
            _save_cache({})
            logger.debug("AI 回复缓存已清空")
        except Exception as e:
            logger.error(f"清空缓存失败：{e}")

    @property
    def enabled(self) -> bool:
        """返回缓存是否已启用"""
        return self._enable
