"""
指令分发器
根据 CommandRouter 识别出的 type / action，分发给对应 Service 执行，
并将执行结果（字符串）返回给聊天窗口展示。

与 CommandRouter 的职责分工：
    CommandRouter  — 纯意图识别，返回 CommandResult（不执行任何 IO）
    CommandDispatcher — 纯执行调度，不做意图识别

新增 Service 时：在 __init__ 中注册，在 _dispatch() 增加对应 type 分支即可。
"""

from services.command_router import CommandRouter, CommandResult
from services.app_command_service import AppCommandService
from services.search_service import SearchService
from services.note_service import NoteService
from services.screenshot_service import ScreenshotService
from services.monitor_service import MonitorService
from services.system_service import VolumeService, SystemCommandService
from services.todo_service import TodoService
from services.date_time_service import DateTimeService
from app.config import AppConfig
from app.logger import setup_logger
from typing import Optional

logger = setup_logger()

_NOT_IMPLEMENTED_MSG = "该功能正在开发中，敬请期待。"


class CommandDispatcher:
    """
    统一指令分发入口。

    使用方式：
        dispatcher = CommandDispatcher(config=app_config)
        reply = dispatcher.handle("今天周几")
        # 非空字符串 → 本地处理结果
        # 空字符串   → 未命中本地规则，由 LocalCommandExecutor 转交 AI

    可通过 todo_service 参数注入外部 TodoService 实例，
    与 main.py 定时弹窗逻辑共用同一数据对象。
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
        self._datetime_svc   = DateTimeService()
        self._todo_svc       = todo_service if todo_service is not None else TodoService()

    # ── 公开接口 ──────────────────────────────────────────────

    def handle(self, text: str) -> str:
        """
        接收用户原始输入，返回执行结果字符串。
        返回空字符串 → 交给 AI。
        """
        try:
            result: CommandResult = self._router.route(text)
        except Exception as e:
            logger.error(f"CommandRouter 意图识别异常：{e}")
            return ""   # 识别失败时降级到 AI

        if not result.handled:
            return ""   # ai_chat，由 LocalCommandExecutor 调用 AI

        try:
            return self._dispatch(result, raw_text=text)
        except Exception as e:
            logger.error(f"指令分发执行异常：type={result.type}  action={result.action}  {e}")
            return f"⚠️ 执行出错：{e}"

    # ── 内部分发 ──────────────────────────────────────────────

    def _dispatch(self, result: CommandResult, raw_text: str = "") -> str:
        """根据 type / action 路由到对应 Service"""
        t      = result.type
        action = result.action or ""
        data   = result.data or {}

        # ── 日期时间（本地，零延迟）────────────────────────────
        if t == "date_time":
            return self._datetime_svc.query(action)

        # ── 截图 ────────────────────────────────────────────────
        if t == "screenshot":
            return self._screenshot_svc.take_screenshot()

        # ── 系统控制 ────────────────────────────────────────────
        if t == "system_control":
            return self._handle_system_control(action, data)

        # ── 系统状态 ────────────────────────────────────────────
        if t == "system_status":
            return self._handle_system_status(action)

        # ── 打开应用 / 文件夹 ────────────────────────────────────
        if t == "quick_open":
            return self._handle_quick_open(action, data)

        # ── 网页搜索 ────────────────────────────────────────────
        if t == "web_search":
            query  = data.get("query", "")
            engine = data.get("engine", "")
            return self._search_svc.search_web(query, engine=engine)

        # ── 待办提醒 ────────────────────────────────────────────
        if t == "todo":
            return self._handle_todo(action, data, raw_text)

        # ── 快速笔记 ────────────────────────────────────────────
        if t == "quick_note":
            return self._handle_quick_note(action, data)

        logger.warning(f"未知 type/action：type={t}  action={action}")
        return _NOT_IMPLEMENTED_MSG

    # ── 各类型处理器 ──────────────────────────────────────────

    def _handle_system_control(self, action: str, data: dict) -> str:
        if action == "mute":
            return self._volume_svc.mute()
        if action == "unmute":
            return self._volume_svc.unmute()
        if action == "volume_up":
            step = data.get("amount", 10) / 100.0
            return self._volume_svc.volume_up(step=step)
        if action == "volume_down":
            step = data.get("amount", 10) / 100.0
            return self._volume_svc.volume_down(step=step)
        if action == "lock_screen":
            return self._syscmd_svc.lock_screen()
        return _NOT_IMPLEMENTED_MSG

    def _handle_system_status(self, action: str) -> str:
        if action == "full_status":
            return self._monitor_svc.check_all()
        if action == "cpu_status":
            return self._monitor_svc.check_cpu()
        if action == "memory_status":
            return self._monitor_svc.check_memory()
        if action == "disk_status":
            return self._monitor_svc.check_disk()
        if action == "battery_status":
            return self._monitor_svc.check_battery()
        # 兜底：未细分则返回综合状态
        return self._monitor_svc.check_all()

    def _handle_quick_open(self, action: str, data: dict) -> str:
        target = data.get("target_name", "")

        if action == "open_folder":
            return self._app_cmd.open_folder(target)

        if action == "open_app":
            # app_action 是规则文件中 app_aliases 对应的 action 字符串
            app_action = data.get("app_action", "")
            # 特殊：浏览器用专用方法（可带 URL）
            if app_action == "open_browser":
                return self._app_cmd.open_browser()
            # 通用：把 target_name 当作应用名传入 open_app
            return self._app_cmd.open_app(target)

        # open_unknown：target 未在配置中，尝试直接当应用名
        if action == "open_unknown" and target:
            result = self._app_cmd.open_app(target)
            if "暂未找到" in result:
                result = self._app_cmd.open_folder(target)
            return result

        return f"暂未找到「{target}」，请在 config.json 中添加对应配置。"

    def _handle_todo(self, action: str, data: dict, raw_text: str) -> str:
        if action == "add_todo":
            return self._todo_svc.add_todo_from_text(raw_text)
        if action == "list_todo":
            return self._todo_svc.list_todos()
        if action == "delete_todo":
            todo_id = data.get("todo_id")
            if todo_id is None:
                return "⚠️ 请告诉我要删除第几条提醒，例如：删除提醒 1"
            return self._todo_svc.delete_todo(int(todo_id))
        return _NOT_IMPLEMENTED_MSG

    def _handle_quick_note(self, action: str, data: dict) -> str:
        if action == "add_note":
            return self._note_svc.add_note(data.get("content", ""))
        if action == "list_notes":
            return self._note_svc.list_notes()
        if action == "clear_notes":
            return self._note_svc.clear_notes()
        return _NOT_IMPLEMENTED_MSG
