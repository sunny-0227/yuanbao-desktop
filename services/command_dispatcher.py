"""
指令分发器
负责把 CommandRouter 识别出的 action 分发给对应的 Service 执行，
并将执行结果（字符串）返回给聊天窗口展示。

职责：
- 持有各 Service 实例
- 根据 CommandResult.action 调用对应执行方法
- 未识别的 action 返回通用提示，不崩溃

新增 Service 时：在 __init__ 中注册，在 _dispatch_local 添加分支即可。
"""

from services.command_router import CommandRouter, CommandResult
from services.app_command_service import AppCommandService
from services.search_service import SearchService
from services.note_service import NoteService
from services.screenshot_service import ScreenshotService
from services.monitor_service import MonitorService
from services.system_service import VolumeService, SystemCommandService
from services.todo_service import TodoService
from app.config import AppConfig
from app.logger import setup_logger
from typing import Optional

logger = setup_logger()

_NOT_IMPLEMENTED_MSG = "该功能正在开发中，敬请期待。"


class CommandDispatcher:
    """
    统一指令入口。

    使用方式：
        dispatcher = CommandDispatcher(config=app_config)
        reply = dispatcher.handle("打开记事本")
        # 非空字符串 → 本地指令执行结果（直接展示）
        # 空字符串   → 未命中本地规则，交给 AI

    可通过 todo_service 参数注入外部 TodoService 实例，
    实现与 main.py 定时弹窗逻辑共用同一数据对象。
    """

    def __init__(
        self,
        config: Optional["AppConfig"] = None,
        todo_service: Optional[TodoService] = None,
    ):
        self._router         = CommandRouter()
        self._app_cmd        = AppCommandService(config=config)
        self._search_svc     = SearchService(
            config=config.search if config else None
        )
        self._note_svc       = NoteService()
        self._screenshot_svc = ScreenshotService(
            config=config.screenshot if config else None
        )
        self._monitor_svc    = MonitorService()
        self._volume_svc     = VolumeService()
        self._syscmd_svc     = SystemCommandService()
        # 优先使用外部注入的实例；未注入时自建，保持向后兼容
        self._todo_svc       = todo_service if todo_service is not None else TodoService()

    def handle(self, text: str) -> str:
        """
        接收用户原始输入，返回回复字符串。
        返回空字符串表示"未命中本地规则，请调用 AI"。
        """
        result: CommandResult = self._router.route(text)

        if result.handled:
            return self._dispatch_local(result, raw_text=text)

        return ""

    def _dispatch_local(self, result: CommandResult, raw_text: str = "") -> str:
        """根据 action 分发到对应 Service，返回执行结果字符串"""
        action = result.action or ""
        data   = result.data or {}

        # ── quick_app ────────────────────────────────────────
        _app_name_map = {
            "open_wechat":      "微信",
            "open_browser":     None,       # 浏览器特殊处理
            "open_word":        "Word",
            "open_excel":       "Excel",
            "open_calculator":  "计算器",
            "open_notepad":     "记事本",
        }
        if action in _app_name_map:
            if action == "open_browser":
                return self._app_cmd.open_browser(data.get("url", ""))
            return self._app_cmd.open_app(_app_name_map[action])

        # ── quick_folder ─────────────────────────────────────
        _folder_name_map = {
            "open_folder_desktop":     "桌面",
            "open_folder_downloads":   "下载",
            "open_folder_documents":   "文档",
            "open_folder_pictures":    "图片",
            "open_folder_projects":    "项目",
            "open_folder_screenshots": "截图",
        }
        if action in _folder_name_map:
            return self._app_cmd.open_folder(_folder_name_map[action])

        # ── web_search ───────────────────────────────────────
        if action == "web_search":
            query  = data.get("query", "")
            engine = data.get("engine", "")
            return self._search_svc.search_web(query, engine=engine)

        # ── quick_note ───────────────────────────────────────
        if action == "add_note":
            return self._note_svc.add_note(data.get("content", ""))
        if action == "list_notes":
            return self._note_svc.list_notes()
        if action == "clear_notes":
            return self._note_svc.clear_notes()

        # ── screenshot ───────────────────────────────────────
        if action == "screenshot":
            return self._screenshot_svc.take_screenshot()

        # ── todo / reminder ──────────────────────────────────
        if action == "add_reminder":
            # 将原始输入文本传给 TodoService，由它完整解析时间和标题
            return self._todo_svc.add_todo_from_text(raw_text)
        if action == "list_reminders":
            return self._todo_svc.list_todos()
        if action == "delete_reminder":
            # CommandRouter 提取的序号字段名为 "index"
            rid = data.get("index") or data.get("id")
            if rid is None:
                return "⚠️ 请告诉我要删除第几条提醒，例如：删除提醒 1"
            return self._todo_svc.delete_todo(int(rid))

        # ── system_status（辅助功能）─────────────────────────
        if action == "system_status_all":
            return self._monitor_svc.check_all()
        if action == "check_cpu":
            return self._monitor_svc.check_cpu()
        if action == "check_memory":
            return self._monitor_svc.check_memory()
        if action == "check_disk":
            return self._monitor_svc.check_disk()
        if action == "check_battery":
            return self._monitor_svc.check_battery()

        # ── system_control ───────────────────────────────────
        if action == "lock_screen":
            return self._syscmd_svc.lock_screen()
        if action == "mute":
            return self._volume_svc.mute()
        if action == "unmute":
            return self._volume_svc.unmute()
        if action == "volume_up":
            # amount 来自 CommandRouter 提取的百分比整数（如 20），转为 0~1 小数
            step = data.get("amount", 10) / 100.0
            return self._volume_svc.volume_up(step=step)
        if action == "volume_down":
            step = data.get("amount", 10) / 100.0
            return self._volume_svc.volume_down(step=step)

        logger.warning(f"未知 action：{action}")
        return _NOT_IMPLEMENTED_MSG
