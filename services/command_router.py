"""
用户输入路由模块
接收用户文本，识别是否为本地指令，返回 CommandResult。

职责：
- 加载 data/command_rules.json 中的指令规则（支持 type 分类）
- 对输入做预处理后逐条关键词匹配
- 命中规则 → 提取附加参数 → 返回 handled=True 的 CommandResult
- 未命中 → 返回 handled=False、type="ai_chat"

不在本模块实现：系统命令执行、AI 接口调用、UI 操作。

指令分类（type）：
    quick_app       打开常用应用
    quick_folder    打开常用文件夹
    screenshot      截图
    web_search      网页搜索（需提取搜索词）
    quick_note      快速笔记
    todo            提醒/待办
    system_status   系统状态查询
    system_control  系统控制（音量/锁屏等）
    ai_chat         未匹配，交给 AI
"""

import json
import os
import re
from dataclasses import dataclass, field
from typing import Optional

from app.app_context import resource_path
from app.logger import setup_logger

logger = setup_logger()

_RULES_PATH = resource_path(os.path.join("data", "command_rules.json"))


# ── 数据结构 ──────────────────────────────────────────────────

@dataclass
class CommandResult:
    """
    指令路由结果。

    字段说明：
        handled  是否命中本地指令规则
        type     分类标识：quick_app / quick_folder / screenshot /
                           web_search / quick_note / todo /
                           system_status / system_control / ai_chat
        message  展示给用户的确认/结果文本
        action   具体动作标识（如 "open_wechat"），未命中时为 None
        data     从输入中提取的参数字典，例如：
                   web_search  → {"query": "Python 教程"}
                   add_note    → {"content": "买咖啡"}
                   add_reminder→ {"time": "18:30", "content": "喝水"}
                   delete_reminder → {"index": 1}
                   volume_up   → {"amount": 10}
    """
    handled: bool
    type: str
    message: str
    action: Optional[str] = None
    data: Optional[dict] = field(default=None)


# ── 路由器 ────────────────────────────────────────────────────

class CommandRouter:
    """
    用户输入路由器。

    实例化时从 command_rules.json 加载规则。
    匹配策略：统一转小写 + 去空格后做"包含匹配"，首条命中即返回。

    使用方式：
        router = CommandRouter()
        result = router.route("搜索 Python 教程")
        # result.type == "web_search"
        # result.data == {"query": "Python 教程"}
    """

    def __init__(self):
        self._rules: list[dict] = []
        self._load_rules()

    # ── 规则加载 ──────────────────────────────────────────────

    def _load_rules(self):
        """
        加载规则文件。
        文件不存在时记录警告，规则保持空列表（不崩溃）；
        JSON 损坏时自动备份为 .bak 并重置，确保下次能正常加载。
        """
        if not os.path.exists(_RULES_PATH):
            logger.warning(f"指令规则文件不存在：{_RULES_PATH}（本地指令将不可用）")
            return
        try:
            with open(_RULES_PATH, "r", encoding="utf-8") as f:
                raw = json.load(f)
            self._rules = raw.get("rules", [])
            logger.debug(f"已加载 {len(self._rules)} 条指令规则")
        except json.JSONDecodeError as e:
            # JSON 损坏：备份后重置，使程序继续运行
            backup = _RULES_PATH + ".bak"
            try:
                os.replace(_RULES_PATH, backup)
                logger.error(f"command_rules.json 格式异常，已备份到 {backup}：{e}")
            except OSError as be:
                logger.error(f"备份 command_rules.json 失败：{be}")
        except IOError as e:
            logger.error(f"读取指令规则文件失败：{e}")

    # ── 路由入口 ──────────────────────────────────────────────

    def route(self, text: str) -> CommandResult:
        """
        对用户输入进行路由判断，返回 CommandResult。

        参数：
            text: 用户原始输入文本（保留原始格式用于参数提取）
        """
        stripped = text.strip() if text else ""
        if not stripped:
            return CommandResult(handled=False, type="ai_chat", message="")

        norm = _normalize(stripped)

        for rule in self._rules:
            action: str = rule.get("action", "")
            cmd_type: str = rule.get("type", "local_command")
            keywords: list[str] = rule.get("keywords", [])

            for kw in keywords:
                if _normalize(kw) in norm:
                    data = self._extract(action, cmd_type, stripped, kw)
                    msg  = self._build_message(action, cmd_type, stripped, data,
                                               rule.get("description", ""))
                    logger.debug(f"路由命中：input={stripped!r}  action={action}")
                    return CommandResult(
                        handled=True,
                        type=cmd_type,
                        message=msg,
                        action=action,
                        data=data or None,
                    )

        logger.debug(f"路由未命中，转 AI：{stripped!r}")
        return CommandResult(handled=False, type="ai_chat", message=stripped)

    # ── 参数提取 ──────────────────────────────────────────────

    def _extract(self, action: str, cmd_type: str,
                 text: str, matched_kw: str) -> dict:
        """
        根据 action/type 从原始文本中提取附加参数。
        每种类型只处理自己的提取逻辑，互不干扰。
        """
        params: dict = {}

        # ── 网页搜索：提取搜索词 + 引擎 ────────────────────────
        if cmd_type == "web_search":
            params["query"] = _extract_after_keyword(text, matched_kw)
            # 根据触发关键词推断用户希望使用的引擎
            kw_lower = matched_kw.lower()
            if "百度" in kw_lower:
                params["engine"] = "baidu"
            elif "必应" in kw_lower or "bing" in kw_lower:
                params["engine"] = "bing"
            elif "谷歌" in kw_lower or "google" in kw_lower:
                params["engine"] = "google"
            # 未指定引擎时不写入，让 SearchService 用默认值

        # ── 快速笔记：提取笔记内容 ───────────────────────────
        elif action == "add_note":
            content = _extract_after_keyword(text, matched_kw)
            if content:
                params["content"] = content

        # ── 提醒：提取时间和内容 ─────────────────────────────
        elif action == "add_reminder":
            time_str, content = _extract_reminder(text)
            if time_str:
                params["time"] = time_str
            if content:
                params["content"] = content

        elif action == "delete_reminder":
            # 提取序号，如"删除提醒 1"或"取消第2条提醒"
            m = re.search(r"第?\s*(\d+)\s*[条个项]?", text)
            if m:
                params["index"] = int(m.group(1))

        # ── 系统控制：提取音量调整幅度 ───────────────────────
        elif action in ("volume_up", "volume_down"):
            m = re.search(r"(\d+)\s*%?", text)
            params["amount"] = int(m.group(1)) if m else 10

        return params

    # ── 消息构建 ──────────────────────────────────────────────

    def _build_message(self, action: str, cmd_type: str,
                       text: str, data: dict, description: str) -> str:
        """根据 action 和提取到的参数，返回展示给用户的自然语言确认文字"""

        # ── 快捷应用 ─────────────────────────────────────────
        _app_msgs = {
            "open_wechat":      "好的，正在打开微信…",
            "open_browser":     "好的，正在打开浏览器…",
            "open_word":        "好的，正在打开 Word…",
            "open_excel":       "好的，正在打开 Excel…",
            "open_calculator":  "好的，正在打开计算器…",
            "open_notepad":     "好的，正在打开记事本…",
        }
        if action in _app_msgs:
            return _app_msgs[action]

        # ── 快捷文件夹 ───────────────────────────────────────
        _folder_msgs = {
            "open_folder_desktop":     "正在打开桌面…",
            "open_folder_downloads":   "正在打开下载文件夹…",
            "open_folder_documents":   "正在打开文档文件夹…",
            "open_folder_pictures":    "正在打开图片文件夹…",
            "open_folder_projects":    "正在打开项目目录…",
            "open_folder_screenshots": "正在打开截图目录…",
        }
        if action in _folder_msgs:
            return _folder_msgs[action]

        # ── 截图 ─────────────────────────────────────────────
        if action == "screenshot":
            return "好的，正在截图…"

        # ── 网页搜索 ─────────────────────────────────────────
        if action == "web_search":
            query = data.get("query", "")
            return f"好的，正在搜索「{query}」…" if query else "好的，正在打开搜索引擎…"

        # ── 快速笔记 ─────────────────────────────────────────
        if action == "add_note":
            content = data.get("content", "")
            return f"已记录：{content}" if content else "好的，请告诉我要记什么？"
        if action == "list_notes":
            return "正在查询笔记…"
        if action == "clear_notes":
            return "笔记已全部清空。"

        # ── 提醒 ─────────────────────────────────────────────
        if action == "add_reminder":
            t = data.get("time", "")
            c = data.get("content", "")
            if t and c:
                return f"好的，将在 {t} 提醒你：{c}"
            if c:
                return f"好的，已添加提醒：{c}（请补充时间）"
            return "好的，请告诉我提醒时间和内容。"
        if action == "list_reminders":
            return "正在查询提醒列表…"
        if action == "delete_reminder":
            idx = data.get("index")
            return f"已删除第 {idx} 条提醒。" if idx else "请告诉我要删除第几条提醒。"

        # ── 系统状态 ─────────────────────────────────────────
        _status_msgs = {
            "system_status_all": "正在获取电脑状态…",
            "check_cpu":         "正在查询 CPU 使用率…",
            "check_memory":      "正在查询内存使用情况…",
            "check_disk":        "正在查询硬盘使用情况…",
            "check_battery":     "正在查询电池电量…",
        }
        if action in _status_msgs:
            return _status_msgs[action]

        # ── 系统控制 ─────────────────────────────────────────
        if action == "lock_screen":
            return "好的，马上锁屏。"
        if action == "mute":
            return "已静音。"
        if action == "unmute":
            return "已取消静音。"
        if action == "volume_up":
            return f"音量增加 {data.get('amount', 10)}%。"
        if action == "volume_down":
            return f"音量降低 {data.get('amount', 10)}%。"

        # 兜底
        return f"已识别指令：{description}"

    # ── 调试工具 ──────────────────────────────────────────────

    def list_actions(self) -> list[str]:
        """返回所有已加载的 action 列表，方便调试"""
        return [r.get("action", "") for r in self._rules]

    def list_by_type(self, cmd_type: str) -> list[str]:
        """按 type 过滤，返回对应的 action 列表"""
        return [r["action"] for r in self._rules if r.get("type") == cmd_type]


# ── 纯函数工具 ────────────────────────────────────────────────

def _normalize(text: str) -> str:
    """
    统一预处理：转小写、去除空格和全角空格。
    匹配时用此函数处理输入和关键词，使匹配对大小写和空格不敏感。
    """
    return text.lower().replace(" ", "").replace("\u3000", "")


def _extract_after_keyword(text: str, keyword: str) -> str:
    """
    提取关键词之后的内容，去除常见标点前缀。
    例如："搜索 Python 教程" → "Python 教程"
         "帮我记一下：买咖啡" → "买咖啡"
    """
    idx = text.lower().find(keyword.lower())
    if idx == -1:
        return ""
    after = text[idx + len(keyword):]
    # 去掉开头的标点和空格
    return after.strip(" \t：:，,。.、")


def _extract_reminder(text: str) -> tuple[str, str]:
    """
    从提醒文本中提取时间和内容。

    支持格式：
        提醒我 18:30 喝水
        提醒我 2026-07-06 20:00 开会
        提醒我明天 9:00 吃药
        帮我提醒 下午3点 打电话

    返回：(time_str, content)，提取失败时对应字段为空字符串。
    """
    # 匹配 HH:MM 时间格式
    time_hm = re.search(r"\d{1,2}[：:]\d{2}", text)
    # 匹配"下午/上午 + 数字 + 点/时"格式
    time_cn = re.search(r"[上下]午\s*\d{1,2}\s*[点时]", text)
    # 匹配"明天/后天 + 时间"中的"明天/后天"
    day_word = re.search(r"(今天|明天|后天|大后天)", text)

    time_str = ""
    content  = ""

    if time_hm:
        time_str = time_hm.group(0)
        # 内容在时间之后
        content = text[time_hm.end():].strip(" ，,。.：:")
    elif time_cn:
        time_str = time_cn.group(0)
        content  = text[time_cn.end():].strip(" ，,。.：:")

    # 如果提取到日期词，拼在时间前面
    if day_word and time_str:
        time_str = day_word.group(0) + " " + time_str

    # 若内容仍为空，尝试取关键词后所有文字
    if not content:
        for kw in ["提醒我", "帮我提醒", "设个提醒", "添加提醒", "定个提醒"]:
            idx = text.find(kw)
            if idx != -1:
                after = text[idx + len(kw):].strip()
                # 去掉开头的时间部分，剩余即内容
                if time_str:
                    after = after.replace(time_str.strip(), "").strip(" ，,。.：:")
                if after:
                    content = after
                break

    return time_str, content
