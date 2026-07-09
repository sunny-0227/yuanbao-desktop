"""
本地意图识别路由模块

设计目标：
    不依赖固定完整句子白名单，改用"意图分类 + 关键词组 + 参数提取 + 置信度评分"。
    置信度 >= 0.65 时本地处理；< 0.65 时交给 AI。

置信度计算原则：
    - 命中核心动作词  +0.6
    - 命中意图关键词  +0.2 ~ +0.3（可叠加，最多到 0.95）
    - 命中 AI 强意图词（写、生成、总结等）  -0.5
    - 命中 AI 弱意图词（为什么、怎么做等）  -0.2

识别优先级（由高到低）：
    1. date_time   — 日期时间查询
    2. screenshot  — 截图
    3. system_control — 系统控制（静音/音量/锁屏）
    4. system_status  — 系统状态查询
    5. quick_open  — 打开应用或文件夹
    6. web_search  — 网页搜索
    7. todo        — 待办提醒
    8. quick_note  — 快速笔记
    9. ai_chat     — 兜底
"""

import json
import os
import re
from dataclasses import dataclass, field
from typing import Optional

from app.app_context import resource_path
from app.logger import setup_logger

logger = setup_logger()

# 规则文件路径（只读配置，用 resource_path）
_RULES_PATH = resource_path(os.path.join("data", "command_rules.json"))

# 本地处理置信度阈值
_CONFIDENCE_THRESHOLD = 0.65


# ── 数据结构 ──────────────────────────────────────────────────

@dataclass
class CommandResult:
    """
    意图识别结果。

    字段说明：
        handled     是否由本地处理（confidence >= 阈值）
        type        意图分类：date_time / quick_open / web_search /
                              quick_note / todo / screenshot /
                              system_status / system_control / ai_chat
        action      具体动作，例如 current_weekday / open_folder / add_note
        message     给用户的确认文案（可为空，由 dispatcher 或 service 生成）
        data        从输入中提取的参数字典
        confidence  置信度 0.0~1.0
    """
    handled:    bool
    type:       str
    action:     Optional[str]  = None
    message:    str            = ""
    data:       Optional[dict] = field(default=None)
    confidence: float          = 0.0


# ── 路由器 ────────────────────────────────────────────────────

class CommandRouter:
    """
    本地意图识别路由器。

    实例化时从 command_rules.json 加载规则。
    外部调用 route(text) 获取 CommandResult。

    使用方式：
        router = CommandRouter()
        result = router.route("今天周几")
        # result.type == "date_time", result.action == "current_weekday"
    """

    def __init__(self):
        self._rules: dict = {}
        self._load_rules()

    # ── 规则加载 ──────────────────────────────────────────────

    def _load_rules(self):
        """
        从 command_rules.json 加载规则。
        文件不存在或损坏时使用内置最小规则，保证程序可运行。
        """
        if not os.path.exists(_RULES_PATH):
            logger.warning(f"规则文件不存在：{_RULES_PATH}，使用内置最小规则")
            self._rules = {}
            return
        try:
            with open(_RULES_PATH, "r", encoding="utf-8") as f:
                self._rules = json.load(f)
            logger.debug("意图规则加载成功")
        except json.JSONDecodeError as e:
            backup = _RULES_PATH + ".bak"
            try:
                os.replace(_RULES_PATH, backup)
                logger.error(f"command_rules.json 格式异常，已备份到 {backup}：{e}")
            except OSError as be:
                logger.error(f"备份规则文件失败：{be}")
            self._rules = {}
        except IOError as e:
            logger.error(f"读取规则文件失败：{e}")
            self._rules = {}

    # ── 公开接口 ──────────────────────────────────────────────

    def route(self, text: str) -> CommandResult:
        """
        对用户输入进行意图识别，返回 CommandResult。

        参数：
            text: 用户原始输入
        """
        if not text or not text.strip():
            return CommandResult(handled=False, type="ai_chat", confidence=0.0)

        norm = _normalize(text)

        # 计算 AI 意图惩罚分（越高说明越像 AI 创作请求）
        ai_penalty = self._calc_ai_penalty(norm)

        # 按优先级依次尝试各意图识别器
        candidates = [
            self._match_date_time(norm),
            self._match_screenshot(norm),
            self._match_system_control(norm),
            self._match_system_status(norm),
            self._match_quick_open(norm, text),
            self._match_web_search(norm, text),
            self._match_todo(norm, text),
            self._match_quick_note(norm, text),
        ]

        # 选出置信度最高的候选
        best: Optional[CommandResult] = None
        for c in candidates:
            if c is None:
                continue
            # 施加 AI 意图惩罚
            # date_time/screenshot 等只在强意图词出现时才打折降级（弱意图词不影响）
            if c.type in ("date_time", "screenshot"):
                adjusted = c.confidence - (ai_penalty if ai_penalty >= 0.5 else 0.0)
            else:
                adjusted = c.confidence - ai_penalty
            c = CommandResult(
                handled=c.handled, type=c.type, action=c.action,
                message=c.message, data=c.data,
                confidence=max(0.0, min(1.0, adjusted)),
            )
            if best is None or c.confidence > best.confidence:
                best = c

        # 置信度达到阈值 → 本地处理
        if best and best.confidence >= _CONFIDENCE_THRESHOLD:
            logger.debug(
                f"意图命中：type={best.type}  action={best.action}  "
                f"conf={best.confidence:.2f}  input={text!r}"
            )
            return CommandResult(
                handled=True, type=best.type, action=best.action,
                message=best.message, data=best.data, confidence=best.confidence,
            )

        # 置信度不足 → ai_chat
        logger.debug(
            f"意图未命中（最高置信度={best.confidence if best else 0:.2f}），"
            f"转 ai_chat：{text!r}"
        )
        return CommandResult(
            handled=False, type="ai_chat",
            message=text.strip(), confidence=0.0,
        )

    # ── AI 意图惩罚 ───────────────────────────────────────────

    def _calc_ai_penalty(self, norm: str) -> float:
        """
        计算 AI 意图惩罚分。
        强意图词（写、生成、总结等）惩罚 0.5；弱意图词惩罚 0.2。
        两类最多分别叠加一次（避免单句多词惩罚过度）。
        """
        indicators = self._rules.get("ai_chat_indicators", {})
        strong_words = indicators.get("strong", [])
        weak_words   = indicators.get("weak", [])

        has_strong = any(_normalize(w) in norm for w in strong_words)
        has_weak   = any(_normalize(w) in norm for w in weak_words)

        penalty = 0.0
        if has_strong:
            penalty += 0.5
        if has_weak and not has_strong:
            # 弱意图惩罚：仅在无强意图时叠加（强意图已足以转 AI）
            penalty += 0.2
        return penalty

    # ── 各意图识别器 ──────────────────────────────────────────

    def _match_date_time(self, norm: str) -> Optional[CommandResult]:
        """
        日期时间意图识别。
        先检查 action patterns，再检查时间关键词 + 查询动词组合。
        """
        dt_rules = self._rules.get("date_time", {})
        time_kws  = [_normalize(w) for w in dt_rules.get("time_keywords", [])]
        query_vbs = [_normalize(w) for w in dt_rules.get("query_verbs", [])]

        # 1. 精确 pattern 匹配（按 pattern 长度降序，优先匹配最长、最精确的）
        all_patterns: list[tuple[str, str]] = []
        for act_rule in dt_rules.get("actions", []):
            action   = act_rule.get("action", "")
            for p in act_rule.get("patterns", []):
                all_patterns.append((_normalize(p), action))
        # 按 pattern 长度降序，避免短 pattern（如"周几"）遮蔽长 pattern（如"明天周几"）
        all_patterns.sort(key=lambda x: len(x[0]), reverse=True)

        for p, action in all_patterns:
            if p in norm:
                return CommandResult(
                    handled=True, type="date_time",
                    action=action, confidence=0.95,
                )

        # 2. 时间关键词 + 查询动词组合（置信度 0.75）
        has_time_kw  = any(kw in norm for kw in time_kws)
        has_query_vb = any(vb in norm for vb in query_vbs)
        if has_time_kw and has_query_vb:
            # 推断最接近的 action
            action = self._infer_datetime_action(norm)
            return CommandResult(
                handled=True, type="date_time",
                action=action, confidence=0.75,
            )

        # 3. 只有时间关键词（置信度 0.65，仍尝试）
        if has_time_kw:
            action = self._infer_datetime_action(norm)
            return CommandResult(
                handled=True, type="date_time",
                action=action, confidence=0.65,
            )

        return None

    def _infer_datetime_action(self, norm: str) -> str:
        """根据规范化输入推断最合适的日期时间 action"""
        if "明天" in norm and ("星期" in norm or "周" in norm or "礼拜" in norm):
            return "tomorrow_weekday"
        if ("星期" in norm or "周几" in norm or "礼拜" in norm) and "今天" in norm:
            return "current_weekday"
        if "几点" in norm or "时间" in norm or "时刻" in norm:
            return "current_time"
        if "几号" in norm or "日期" in norm or "哪天" in norm:
            return "current_date"
        if "明天" in norm:
            return "tomorrow_weekday"
        return "current_datetime"

    def _match_screenshot(self, norm: str) -> Optional[CommandResult]:
        """截图意图识别"""
        keywords = [_normalize(k) for k in
                    self._rules.get("screenshot", {}).get("keywords", [])]
        if any(kw in norm for kw in keywords):
            return CommandResult(
                handled=True, type="screenshot",
                action="take_screenshot", confidence=0.9,
            )
        return None

    def _match_system_control(self, norm: str) -> Optional[CommandResult]:
        """系统控制意图识别（静音/音量/锁屏）"""
        ctrl = self._rules.get("system_control", {})

        def _hit(kws: list) -> bool:
            return any(_normalize(k) in norm for k in kws)

        if _hit(ctrl.get("mute_keywords", [])):
            return CommandResult(handled=True, type="system_control",
                                 action="mute", confidence=0.9)
        if _hit(ctrl.get("unmute_keywords", [])):
            return CommandResult(handled=True, type="system_control",
                                 action="unmute", confidence=0.9)
        if _hit(ctrl.get("volume_up_keywords", [])):
            amount = _extract_number(norm, default=10)
            return CommandResult(handled=True, type="system_control",
                                 action="volume_up",
                                 data={"amount": amount}, confidence=0.9)
        if _hit(ctrl.get("volume_down_keywords", [])):
            amount = _extract_number(norm, default=10)
            return CommandResult(handled=True, type="system_control",
                                 action="volume_down",
                                 data={"amount": amount}, confidence=0.9)
        if _hit(ctrl.get("lock_keywords", [])):
            return CommandResult(handled=True, type="system_control",
                                 action="lock_screen", confidence=0.9)
        return None

    def _match_system_status(self, norm: str) -> Optional[CommandResult]:
        """系统状态查询意图识别"""
        ss = self._rules.get("system_status", {})

        def _hit(kws: list) -> bool:
            return any(_normalize(k) in norm for k in kws)

        prefix_kws  = [_normalize(p) for p in ss.get("query_prefix", [])]
        has_prefix  = any(p in norm for p in prefix_kws)

        if _hit(ss.get("full_keywords", [])):
            return CommandResult(handled=True, type="system_status",
                                 action="full_status", confidence=0.88)

        if _hit(ss.get("cpu_keywords", [])):
            conf = 0.85 if has_prefix else 0.72
            return CommandResult(handled=True, type="system_status",
                                 action="cpu_status", confidence=conf)
        if _hit(ss.get("memory_keywords", [])):
            conf = 0.85 if has_prefix else 0.72
            return CommandResult(handled=True, type="system_status",
                                 action="memory_status", confidence=conf)
        if _hit(ss.get("disk_keywords", [])):
            conf = 0.85 if has_prefix else 0.72
            return CommandResult(handled=True, type="system_status",
                                 action="disk_status", confidence=conf)
        if _hit(ss.get("battery_keywords", [])):
            conf = 0.85 if has_prefix else 0.72
            return CommandResult(handled=True, type="system_status",
                                 action="battery_status", confidence=conf)
        return None

    def _match_quick_open(self, norm: str, raw: str) -> Optional[CommandResult]:
        """
        打开应用 / 文件夹意图识别。

        置信度策略：
        - 命中已知别名（folder_aliases / app_aliases）：0.90
        - 有动作词但目标名未知：0.80（高于阈值 0.65，交由 AppCommandService 查找）
          → AppCommandService 会按 user_custom > config > app_index > 系统工具 顺序查找
          → 找不到时给出友好提示，不会静默失败
        """
        qo    = self._rules.get("quick_open", {})
        verbs = [_normalize(v) for v in qo.get("verbs", [])]

        has_verb = any(v in norm for v in verbs)
        if not has_verb:
            return None

        # 先尝试匹配文件夹别名（优先度高于应用）
        folder_aliases = qo.get("folder_aliases", {})
        for alias, action in folder_aliases.items():
            if _normalize(alias) in norm:
                return CommandResult(
                    handled=True, type="quick_open",
                    action="open_folder",
                    data={"target_name": alias},
                    confidence=0.9,
                )

        # 再尝试匹配应用别名
        app_aliases = qo.get("app_aliases", {})
        for alias, action in app_aliases.items():
            if _normalize(alias) in norm:
                return CommandResult(
                    handled=True, type="quick_open",
                    action="open_app",
                    data={"target_name": alias, "app_action": action},
                    confidence=0.9,
                )

        # 动作词存在但目标名未知：
        # 提取目标名后交由 AppCommandService 动态查找（app_index + user_custom）
        target = _extract_open_target(raw, qo.get("verbs", []))
        if not target:
            return None  # 无法提取目标名，交 AI 处理

        return CommandResult(
            handled=True, type="quick_open",
            action="open_unknown",
            data={"target_name": target},
            confidence=0.80,  # 高于阈值，由 AppCommandService 决定能否处理
        )

    def _match_web_search(self, norm: str, raw: str) -> Optional[CommandResult]:
        """网页搜索意图识别"""
        ws   = self._rules.get("web_search", {})
        verbs = [_normalize(v) for v in ws.get("verbs", [])]

        for v in verbs:
            if v in norm:
                # 提取搜索词：关键词后的内容
                query  = _extract_after_verbs(raw, ws.get("verbs", []))
                engine = _infer_engine(norm)
                return CommandResult(
                    handled=True, type="web_search",
                    action="search_web",
                    data={"query": query, "engine": engine},
                    confidence=0.88,
                )
        return None

    def _match_todo(self, norm: str, raw: str) -> Optional[CommandResult]:
        """待办提醒意图识别"""
        td = self._rules.get("todo", {})

        # 删除提醒
        del_kws = [_normalize(k) for k in td.get("delete_keywords", [])]
        if any(k in norm for k in del_kws):
            m = re.search(r"第?\s*(\d+)\s*[条个项]?", raw)
            todo_id = int(m.group(1)) if m else None
            return CommandResult(
                handled=True, type="todo",
                action="delete_todo",
                data={"todo_id": todo_id},
                confidence=0.9,
            )

        # 查看提醒
        list_kws = [_normalize(k) for k in td.get("list_keywords", [])]
        if any(k in norm for k in list_kws):
            return CommandResult(
                handled=True, type="todo",
                action="list_todo", confidence=0.9,
            )

        # 新增提醒
        add_vbs = [_normalize(v) for v in td.get("add_verbs", [])]
        if any(v in norm for v in add_vbs):
            return CommandResult(
                handled=True, type="todo",
                action="add_todo",
                data={"raw_text": raw},
                confidence=0.88,
            )

        return None

    def _match_quick_note(self, norm: str, raw: str) -> Optional[CommandResult]:
        """快速笔记意图识别"""
        qn = self._rules.get("quick_note", {})

        # 清空笔记
        clear_kws = [_normalize(k) for k in qn.get("clear_keywords", [])]
        if any(k in norm for k in clear_kws):
            return CommandResult(
                handled=True, type="quick_note",
                action="clear_notes", confidence=0.9,
            )

        # 查看笔记
        list_kws = [_normalize(k) for k in qn.get("list_keywords", [])]
        if any(k in norm for k in list_kws):
            return CommandResult(
                handled=True, type="quick_note",
                action="list_notes", confidence=0.9,
            )

        # 新增笔记
        add_vbs = [_normalize(v) for v in qn.get("add_verbs", [])]
        for v in add_vbs:
            if _normalize(v) in norm:
                content = _extract_after_verbs(raw, qn.get("add_verbs", []))
                return CommandResult(
                    handled=True, type="quick_note",
                    action="add_note",
                    data={"content": content},
                    confidence=0.88,
                )

        return None

    # ── 调试工具 ──────────────────────────────────────────────

    def test_route(self, text: str) -> str:
        """调试：返回识别结果摘要字符串"""
        r = self.route(text)
        return (
            f"input={text!r}  handled={r.handled}  type={r.type}  "
            f"action={r.action}  conf={r.confidence:.2f}  data={r.data}"
        )


# ── 纯函数工具 ────────────────────────────────────────────────

def _normalize(text: str) -> str:
    """
    标准化文本：
    - 去除前后空格
    - 统一中文标点 → 英文（问号、冒号、逗号）
    - 转小写
    - 去掉多余空格和全角空格
    """
    if not text:
        return ""
    t = text.strip()
    # 中文标点统一化
    t = t.replace("？", "?").replace("！", "!").replace("，", ",")
    t = t.replace("。", ".").replace("：", ":").replace("；", ";")
    t = t.lower()
    t = t.replace(" ", "").replace("\u3000", "")
    return t


def _extract_after_verbs(raw: str, verbs: list) -> str:
    """
    提取动作词之后的内容。
    按 verb 长度降序尝试，优先匹配较长的动作词，避免短词遮蔽。
    返回去除首尾标点空格后的字符串。
    """
    sorted_verbs = sorted(verbs, key=len, reverse=True)
    raw_lower = raw.lower()
    for v in sorted_verbs:
        idx = raw_lower.find(v.lower())
        if idx != -1:
            after = raw[idx + len(v):]
            return after.strip(" \t：:，,。.、?？")
    return raw.strip()


def _extract_open_target(raw: str, verbs: list) -> str:
    """
    从"打开 xxx"类句子中提取目标名称。
    比 _extract_after_verbs 更严格：
    1. 去除动作词后面的语气助词（"一下""帮我""给我"等）
    2. 去除尾部标点
    3. 若提取结果包含 AI 指示词（如"帮我写""生成"），返回空（交给 AI）
    """
    _NOISE_PREFIX = ["一下", "帮我", "给我", "帮忙", "请", "你帮"]
    _AI_SIGNS     = ["写", "生成", "做一个", "分析", "总结", "翻译",
                     "解释", "推荐", "建议", "计划", "方案"]

    target = _extract_after_verbs(raw, verbs)
    if not target:
        return ""

    # 去除语气前缀
    for noise in _NOISE_PREFIX:
        if target.startswith(noise):
            target = target[len(noise):].strip()

    # 如果包含 AI 类动词，说明是要 AI 来做，不是打开软件
    for sign in _AI_SIGNS:
        if sign in target:
            return ""

    return target.strip()


def _extract_number(norm: str, default: int = 10) -> int:
    """从规范化文本中提取第一个数字，提取失败时返回 default"""
    m = re.search(r"(\d+)", norm)
    return int(m.group(1)) if m else default


def _infer_engine(norm: str) -> str:
    """根据规范化文本推断搜索引擎"""
    if "百度" in norm:
        return "baidu"
    if "必应" in norm or "bing" in norm:
        return "bing"
    if "谷歌" in norm or "google" in norm:
        return "google"
    return ""  # 空字符串表示使用 SearchService 默认引擎
