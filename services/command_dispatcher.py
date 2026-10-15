"""指令服务组合；确认操作由控制器批准后才进入执行。"""

import os
from datetime import datetime
from pathlib import Path

from app.config import AppConfig
from services.app_command_service import AppCommandService
from services.app_discovery_service import AppDiscoveryService
from services.command_router import CommandRouter
from services.monitor_service import MonitorService
from services.note_service import NoteService
from services.screenshot_service import ScreenshotService
from services.search_service import SearchService
from services.system_service import SystemCommandService, VolumeService
from services.todo_service import TodoService
from services.tools_service import ToolsService


class CommandDispatcher:
    def __init__(self, config=None, todo_service=None, db=None):
        self.config = config or AppConfig()
        self.router = CommandRouter()
        self.todos = todo_service or TodoService(db)
        self.notes = NoteService(db)
        self.apps = AppCommandService(self.config, AppDiscoveryService())
        self.tools = ToolsService(self.config, self.apps)

    def execute(self, command):
        a, d = command.action, command.data
        if a == "datetime":
            return (
                datetime.now().strftime("今天是 %Y年%m月%d日，%H:%M:%S，")
                + "星期"
                + "一二三四五六日"[datetime.now().weekday()]
            )
        if a == "status":
            return MonitorService().check_all()
        if a == "screenshot":
            return ScreenshotService(self.config.screenshot).take_screenshot()
        if a in ("mute", "unmute", "volume_up", "volume_down"):
            volume = VolumeService()
            return (
                getattr(volume, a)(step=d["amount"] / 100)
                if "amount" in d
                else getattr(volume, a)()
            )
        if a == "lock":
            return SystemCommandService().lock_screen()
        if a == "open":
            name = d["name"]
            path = Path(os.path.expandvars(name)).expanduser()
            if path.is_absolute() and path.exists():
                if not hasattr(os, "startfile"):
                    raise RuntimeError("打开本地文件仅支持 Windows")
                os.startfile(str(path))
                return "已打开本地文件。"
            return self.apps.open_entry(name)
        if a == "find_app":
            return self.apps.find_entry_path(d["name"])
        if a == "search":
            return SearchService(self.config.search).search_web(d["query"], d["engine"])
        if a == "add_todo":
            return self.todos.add_todo_from_text(d["text"])
        if a == "todos":
            return self.todos.list_todos()
        if a == "delete_todo":
            return self.todos.delete_todo(d["id"])
        if a == "complete_todo":
            self.todos.complete(d["id"])
            return "已完成待办。"
        if a == "add_note":
            return self.notes.add_note(d["content"])
        if a == "notes":
            return self.notes.list_notes()
        if a == "clear_notes":
            return self.notes.clear_notes()
        return self.tools.execute(a, d)
