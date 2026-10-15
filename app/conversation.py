"""唯一对话入口。联网理解、离线快捷请求、追问和确认共用工具与会话状态。"""

import re
from dataclasses import dataclass

from services.ai_service import AIError
from services.command_router import CommandResult
from services.conversation_tools import ConversationTools


@dataclass
class ConversationReply:
    text: str
    confirmation: CommandResult | None = None
    power: str | None = None

    def __str__(self):
        return self.text


class ConversationCoordinator:
    def __init__(self, dispatcher, ai, db, power_state=None):
        self.dispatcher, self.ai, self.db = dispatcher, ai, db
        self.power_state = power_state

    @staticmethod
    def _reply(text, tools):
        pending = next(
            (
                r.get("confirmation")
                for r in reversed(tools.results)
                if r["status"] == "confirmation_required"
            ),
            None,
        )
        command = None
        if pending:
            arguments = pending["arguments"]
            if pending["name"] == "desktop_action":
                summary = {
                    "clear_notes": "删除全部本地笔记？",
                    "recycle": "清空系统回收站？",
                    "close_app": "请求关闭「" + arguments.get("name", "指定软件") + "」？",
                    "shutdown": ("安排重启电脑？" if arguments.get("restart") else "安排关机？")
                    + "请先保存工作。",
                }.get(arguments["action"], "确认执行这项操作？")
            else:
                summary = (
                    ("删除笔记" if pending["name"] == "delete_note" else "删除提醒")
                    + " #"
                    + str(arguments.get("id", ""))
                    + "？"
                )
            command = CommandResult(
                True, "agent_confirm", {"token": pending["token"], "summary": summary}, True
            )
        power = next((r.get("power") for r in reversed(tools.results) if r.get("power")), None)
        return ConversationReply(text or "", command, power)

    def respond(self, session, context, cancel, chunk, status, decision=None):
        tools = ConversationTools(
            self.dispatcher, self.db, session, context, cancel, self.power_state, status
        )
        if decision:
            result = (
                tools.approve(decision.data["token"])
                if decision.action == "agent_confirm"
                else tools.execute("cancel_pending", {})
            )
            return self._reply(result["message"], tools)
        text = tools.user_text.strip().rstrip("。！!？?")
        # 明确取消必须即时生效，不依赖模型连接，也不接受模型自行批准确认。
        if text in ("算了", "取消", "先不用了", "先不用", "不弄了", "不用了", "停止这个任务"):
            result = tools.execute("cancel_pending", {})
            return self._reply(result["message"], tools)
        if self.ai.is_configured():
            try:
                answer = self.ai.converse(context, cancel, tools, chunk, status)
                if answer is None:
                    return None
                return self._reply(answer, tools)
            except AIError:
                if tools.executed:
                    return self._reply(
                        tools.authoritative_reply() + "\n模型连接中断，没有自动重试已执行的操作。",
                        tools,
                    )
                offline = self._offline(text, tools)
                if offline is not None:
                    return self._reply(offline, tools)
                raise
        offline = self._offline(text, tools)
        if offline is not None:
            return self._reply(offline, tools)
        return self._reply(
            "请先在设置中连接支持工具调用的AI模型，才能理解这类连续对话。明确的软件启动、提醒、笔记等本机操作仍可直接使用。",
            tools,
        )

    def _offline(self, text, tools):
        """未配置/断网时的有限能力，不能假冒完整自然语言助手。"""
        awaiting = tools.state.get("awaiting", {})
        command = self.dispatcher.router.route(text)
        selection = re.fullmatch(r"第?([一二三四五六七八九十\d]+)个?(?:吧|那个)?", text)
        if awaiting.get("kind") == "app_choice" and selection:
            value = selection[1]
            index = int(value) if value.isdigit() else "一二三四五六七八九十".find(value) + 1
            choices = tools.state.get("choices", [])
            if not 1 <= index <= len(choices):
                return "这个序号不在刚才的候选列表中，请重新选择。"
            return tools.execute("open_app", {"candidate_id": choices[index - 1]["id"]})["message"]
        if awaiting.get("kind") == "reminder" and not command.handled:
            return tools.execute("create_reminder", {"text": awaiting["text"] + " " + text})[
                "message"
            ]
        change = re.fullmatch(r"(?:改成|改为|改到|换成)\s*(.+)", text)
        if tools.state.get("focus", {}).get("kind") == "reminder" and change:
            return tools.execute("update_reminder", {"time_text": change[1]})["message"]
        if text in ("再试一次", "重新试试", "重试"):
            return tools.execute("retry_last", {})["message"]
        if text in (
            "没有弹窗",
            "没弹出来",
            "没有打开",
            "没打开",
            "怎么没弹出来",
        ) and tools.state.get("last_app"):
            return tools.execute("app_status", {})["message"]
        if text in ("把它切到前台", "切到前台") and tools.state.get("last_app"):
            return tools.execute("focus_app", {})["message"]
        if not command.handled:
            return None
        action, data = command.action, command.data
        if action in ("sleep", "wake"):
            return tools.execute("assistant_power", {"mode": action})["message"]
        direct = {
            "open": ("open_app", {"name": data.get("name", "")}),
            "open_path": ("open_path", {"path": data.get("path", "")}),
            "check_open": ("app_status", {}),
            "find_app": ("find_apps", {"name": data.get("name", "")}),
            "add_todo": ("create_reminder", {"text": data.get("text", "")}),
            "todos": ("list_reminders", {}),
            "delete_todo": ("delete_reminder", data),
            "complete_todo": ("complete_reminder", data),
            "add_note": ("save_note", data),
            "notes": ("list_notes", {}),
        }
        if action == "open" and data["name"] in (
            "截图",
            "截图目录",
            "截图文件夹",
            "桌面",
            "下载",
            "下载目录",
            "文档",
            "图片",
        ):
            kind = data["name"].replace("目录", "").replace("文件夹", "")
            return tools.execute("open_folder", {"kind": kind})["message"]
        if action == "open" and data["name"] in ("浏览器", "默认浏览器"):
            # 浏览器同样经过受控工具，不在普通聊天里假装启动。
            return tools.execute("open_browser", {})["message"]
        name, args = direct.get(action, ("desktop_action", {"action": action, **data}))
        return tools.execute(name, args)["message"]
