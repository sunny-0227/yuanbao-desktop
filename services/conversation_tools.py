"""单一工具边界：参数校验、确认、实际执行、任务状态与结果审计。"""

import asyncio
import json
import re
import sqlite3
import time
import uuid
from dataclasses import asdict
from datetime import datetime

from app.conversation_state import ConversationStore
from services.app_launch_service import LaunchOutcome, observe_launch
from services.command_router import CommandResult
from services.todo_service import parse_reminder


def string(description, **extra):
    return {"type": "string", "description": description, "maxLength": 4000, **extra}


def integer(description):
    return {"type": "integer", "description": description, "minimum": 1, "maximum": 2147483647}


# 名称、描述、字段、必填字段。模型只能调用这里列出的能力，没有shell或任意代码入口。
DEFINITIONS = [
    (
        "find_apps",
        "查找本机实际软件位置，返回候选项ID；不能声称扫描了整块磁盘。",
        {"name": string("软件名")},
        ["name"],
    ),
    (
        "open_app",
        "启动已识别软件。名称不明确时先列候选；可使用find_apps返回的candidate_id。",
        {"name": string("软件名，可省略以沿用当前软件"), "candidate_id": string("候选项ID")},
        [],
    ),
    ("app_status", "检查刚才软件的真实进程和可见窗口，不会重新启动。", {}, []),
    ("focus_app", "尝试把刚才软件已存在的窗口切到前台。", {}, []),
    (
        "assistant_power",
        "查询或请求改变元宝助手的工作状态，不是让电脑关机或睡眠。",
        {"mode": string("模式", enum=["status", "sleep", "wake"])},
        ["mode"],
    ),
    (
        "open_path",
        "打开用户在对话中明确给出的绝对文件/快捷方式路径，不能编造路径。",
        {"path": string("用户明确提供的完整路径")},
        ["path"],
    ),
    (
        "open_folder",
        "打开常用文件夹，不需要用户手动配置。",
        {"kind": string("文件夹", enum=["截图", "桌面", "下载", "文档", "图片"])},
        ["kind"],
    ),
    (
        "open_browser",
        "请求系统默认浏览器打开网页，只支持http/https地址。",
        {"url": string("网页地址，可省略")},
        [],
    ),
    (
        "create_reminder",
        "创建提醒。text包含时间与内容；缺信息会追问并保留草稿。",
        {"text": string("例如十分钟后提醒我喝水")},
        ["text"],
    ),
    (
        "update_reminder",
        "修改指定或刚才的提醒，没提到的字段保留。",
        {
            "id": integer("提醒ID，不填沿用当前提醒"),
            "time_text": string("自然时间，例如半小时后、明天下午3点"),
            "title": string("新的提醒内容"),
        },
        [],
    ),
    ("list_reminders", "查询真实提醒记录。", {}, []),
    (
        "delete_reminder",
        "删除指定或刚才的提醒，需要用户确认。",
        {"id": integer("提醒ID，不填沿用当前提醒")},
        [],
    ),
    (
        "complete_reminder",
        "将指定或刚才的提醒标为完成。",
        {"id": integer("提醒ID，不填沿用当前提醒")},
        [],
    ),
    ("save_note", "保存一条笔记。", {"content": string("笔记内容")}, ["content"]),
    ("list_notes", "查询已有笔记。", {}, []),
    (
        "edit_note",
        "修改指定或刚才的笔记。",
        {"id": integer("笔记ID，可省略"), "content": string("新的内容")},
        ["content"],
    ),
    ("delete_note", "删除指定或刚才的笔记，需要确认。", {"id": integer("笔记ID，可省略")}, []),
    (
        "desktop_action",
        "调用明确的桌面功能，参数只允许定义字段。关机、关闭软件、清空资料需要确认。",
        {
            "action": string(
                "操作",
                enum=[
                    "status",
                    "datetime",
                    "screenshot",
                    "mute",
                    "unmute",
                    "volume_up",
                    "volume_down",
                    "lock",
                    "media",
                    "search",
                    "calculate",
                    "mkdir",
                    "weather",
                    "close_app",
                    "clear_notes",
                    "recycle",
                    "shutdown",
                    "cancel_shutdown",
                ],
            ),
            "name": string("要关闭的软件名"),
            "query": string("搜索词"),
            "engine": string("搜索引擎", enum=["", "bing", "baidu", "google"]),
            "expression": string("算术表达式"),
            "path": string("新文件夹路径"),
            "city": string("天气城市"),
            "key": string("媒体操作", enum=["next", "previous", "play_pause"]),
            "amount": {"type": "integer", "minimum": 1, "maximum": 100},
            "seconds": {"type": "integer", "minimum": 60, "maximum": 86400},
            "restart": {"type": "boolean"},
        },
        ["action"],
    ),
    (
        "ask_user",
        "缺少必要信息或对象不明确时追问。不能代替实际操作。",
        {"question": string("简短、具体的问题")},
        ["question"],
    ),
    ("cancel_pending", "取消当前尚未执行的选择、草稿或确认。", {}, []),
    ("retry_last", "重试当前会话上一项明确操作；危险操作仍需重新确认。", {}, []),
]
SCHEMAS = [
    {
        "type": "function",
        "function": {
            "name": name,
            "description": desc,
            "parameters": {
                "type": "object",
                "properties": props,
                "required": required,
                "additionalProperties": False,
            },
        },
    }
    for name, desc, props, required in DEFINITIONS
]
SPEC = {name: (props, required) for name, _, props, required in DEFINITIONS}
READ_ONLY = {
    "find_apps",
    "app_status",
    "list_reminders",
    "list_notes",
    "ask_user",
    "cancel_pending",
}
SAFE_DESKTOP = {"status", "datetime", "calculate", "weather"}
DANGEROUS = {"close_app", "clear_notes", "recycle", "shutdown"}


def validate(name, args):
    if not isinstance(name, str) or name not in SPEC or not isinstance(args, dict):
        raise ValueError("工具或参数格式无效")
    props, required = SPEC[name]
    if set(args) - set(props) or set(required) - set(args):
        raise ValueError("工具参数缺失或包含未定义字段")
    for key, value in args.items():
        spec = props[key]
        expected = {"string": str, "integer": int, "boolean": bool}[spec["type"]]
        if type(value) is not expected:
            raise ValueError(f"{key}的类型不正确")
        if isinstance(value, str) and (
            (not value.strip() and "" not in spec.get("enum", []))
            or len(value) > spec.get("maxLength", 4000)
        ):
            raise ValueError(f"{key}不能为空或过长")
        if "enum" in spec and value not in spec["enum"]:
            raise ValueError(f"{key}不在允许范围")
        if type(value) is int and not spec.get("minimum", value) <= value <= spec.get(
            "maximum", value
        ):
            raise ValueError(f"{key}超出允许范围")


class ConversationTools:
    def __init__(
        self,
        dispatcher,
        db,
        session,
        context,
        cancel,
        power_state=None,
        on_status=lambda text: None,
    ):
        self.dispatcher = dispatcher
        self.store = ConversationStore(db, session)
        self.state = self.store.load()
        self.unsettled = self.store.has_unsettled()
        self.context, self.cancel = context, cancel
        self.power_state = power_state
        self.on_status = on_status
        self.results = []
        self.executed = False
        self.call_count = 0
        self.initial_choices = {e["id"] for e in self.state.get("choices", [])}
        self.initial_selection_pending = self.state.get("awaiting", {}).get("kind") == "app_choice"
        awaiting = self.state.get("awaiting", {})
        if awaiting and time.time() - awaiting.get("created_at", 0) > 600:
            self.state.pop("awaiting", None)
        self.user_text = next((r["content"] for r in reversed(context) if r["role"] == "user"), "")

    def context_state(self):
        state = dict(self.state)
        if state.get("confirmation"):
            state["confirmation"] = {k: v for k, v in state["confirmation"].items() if k != "token"}
        events, size = [], 0
        for event in reversed(self.store.recent()):
            event["result"] = self.model_result(event["result"])
            event["arguments"] = {
                k: v[:1000] if isinstance(v, str) else v for k, v in event["arguments"].items()
            }
            length = len(json.dumps(event, ensure_ascii=False))
            if events and size + length > 16000:
                break
            events.insert(0, event)
            size += length
        return {
            "current_task": state,
            "actual_tool_events": events,
            "local_time": datetime.now().isoformat(timespec="seconds"),
            "has_unsettled_operation": self.unsettled,
        }

    @staticmethod
    def model_result(result):
        value = dict(result)
        if value.get("confirmation"):
            value["confirmation"] = {k: v for k, v in value["confirmation"].items() if k != "token"}
        if isinstance(value.get("message"), str):
            value["message"] = value["message"][:8000]
        for field in ("notes", "reminders"):
            if field in value:
                value[field] = [
                    {k: v[:300] if isinstance(v, str) else v for k, v in row.items()}
                    for row in value[field][:20]
                ]
        return value

    def execute(self, name, arguments, approved=False):
        if self.cancel.is_set():
            raise asyncio.CancelledError()
        self.call_count += 1
        if self.call_count > 12:
            result = self._result("error", "本轮操作已达到上限，已停止继续执行。")
            self.results.append(result)
            return result
        try:
            validate(name, arguments)
        except ValueError as exc:
            result = self._result("error", str(exc))
            self.results.append(result)
            return result
        mutating = name not in READ_ONLY and not (
            name == "desktop_action" and arguments.get("action") in SAFE_DESKTOP
        )
        if name == "assistant_power" and arguments.get("mode") == "status":
            mutating = False
        if mutating and re.match(
            r"^(?:请)?(?:(?:不要|别|不用|不需要|禁止)(?:再|替我|帮我)?(?:打开|启动|运行|删除|清空|关闭|设置|创建|执行|保存|修改)|解释|讨论|翻译|帮我写一段)",
            self.user_text,
        ):
            result = self._result(
                "error", "当前消息包含否定或讨论意图，没有执行更改。请明确要操作的对象。"
            )
            self.results.append(result)
            return result
        arguments = dict(arguments)
        if name in ("delete_note", "delete_reminder") and "id" not in arguments:
            kind = "note" if name == "delete_note" else "reminder"
            focus = self.state.get("focus", {})
            if focus.get("kind") != kind or not focus.get("id"):
                result = self._result("needs_input", "请先指定要删除的记录编号。")
                self.results.append(result)
                return result
            arguments["id"] = focus["id"]
        danger = name in ("delete_note", "delete_reminder") or (
            name == "desktop_action" and arguments["action"] in DANGEROUS
        )
        if danger and not approved:
            token = uuid.uuid4().hex
            self.state["confirmation"] = {
                "token": token,
                "name": name,
                "arguments": arguments,
                "created_at": time.time(),
            }
            result = self._result(
                "confirmation_required",
                "这项操作尚未执行，需要你确认。",
                confirmation=self.state["confirmation"],
            )
            ident = self.store.start(name, arguments)
            self.store.finish(ident, result, self.state)
            self.results.append(result)
            return result
        ident = self.store.start(name, arguments)
        if self.cancel.is_set():
            self.store.finish(ident, self._result("cancelled", "操作在执行前已取消。"), self.state)
            raise asyncio.CancelledError()
        self.on_status("正在执行本机操作")
        self.executed = True
        try:
            # API工具在独立线程调用，Windows COM必须在实际执行线程初始化。
            initialized = False
            try:
                import pythoncom

                pythoncom.CoInitialize()
                initialized = True
            except ImportError:
                pass
            try:
                result = self._perform(name, arguments)
            finally:
                if initialized:
                    pythoncom.CoUninitialize()
        except Exception as exc:
            result = self._result("error", str(exc))
        if (
            mutating
            and name != "retry_last"
            and result["status"] not in ("needs_input", "confirmation_required")
        ):
            self.state["last_action"] = {"name": name, "arguments": arguments}
        if approved:
            result["confirmed_by_user"] = True
        result["changes_state"] = mutating
        result["tool"] = name
        try:
            self.store.finish(ident, result, self.state)
        except (OSError, sqlite3.Error):
            result = self._result(
                "uncertain", "操作可能已经执行，但结果记录未能保存；请先核实，不要自动重复操作。"
            )
        self.results.append(result)
        return result

    @staticmethod
    def _result(status, message, **data):
        return {"status": status, "message": message, **data}

    def _launch_result(self, outcome):
        self.state["last_app"] = asdict(outcome)
        self.state["focus"] = {"kind": "app", "name": outcome.name, "target": outcome.target}
        self.state.pop("awaiting", None)
        return self._result(outcome.status, str(outcome), app=asdict(outcome))

    def _perform(self, name, args):
        apps = self.dispatcher.apps
        if name == "assistant_power":
            if args["mode"] == "status":
                actual = self.power_state() if self.power_state else "unknown"
                return self._result(
                    "completed",
                    "助手当前状态："
                    + {"active": "工作中", "idle": "省电待机", "sleep": "休眠"}.get(
                        actual, "暂未取得实际状态"
                    ),
                )
            return self._result(
                "handoff",
                "已请求助手" + ("进入休眠。" if args["mode"] == "sleep" else "恢复工作。"),
                power=args["mode"],
            )
        if name == "find_apps":
            candidates = apps._discovery.find_candidates(args["name"])
            choices = [{"id": uuid.uuid4().hex, **entry} for entry in candidates]
            self.state["choices"] = choices
            self.state["focus"] = {"kind": "app_choices", "name": args["name"]}
            text = "\n".join(
                f"{i + 1}. {e.get('display_name', args['name'])} — {e.get('path') or e.get('command') or e.get('url')}"
                for i, e in enumerate(choices)
            )
            return self._result(
                "completed" if choices else "not_found",
                text or f"自动查找后未找到「{args['name']}」。",
                candidates=choices,
            )
        if name == "open_app":
            selected = None
            if args.get("candidate_id"):
                selected = next(
                    (e for e in self.state.get("choices", []) if e["id"] == args["candidate_id"]),
                    None,
                )
                if not selected:
                    raise ValueError("候选项已失效，请重新查找软件")
                if len(self.state.get("choices", [])) > 1 and (
                    not self.initial_selection_pending
                    or args["candidate_id"] not in self.initial_choices
                ):
                    self.state["awaiting"] = {"kind": "app_choice", "created_at": time.time()}
                    return self._result(
                        "needs_input",
                        "有多个软件位置，请先选择候选项，尚未启动。",
                        candidates=self.state["choices"],
                    )
            elif args.get("name"):
                # 有效的用户配置仍可用，失效时统一走自动发现。
                configured = None
                try:
                    configured = apps._lookup(args["name"])
                except ValueError:
                    pass
                if configured:
                    selected = configured
                else:
                    found = self._perform("find_apps", {"name": args["name"]})
                    if len(found["candidates"]) == 1:
                        selected = found["candidates"][0]
                    elif found["candidates"]:
                        self.state["awaiting"] = {
                            "kind": "app_choice",
                            "created_at": time.time(),
                            "name": args["name"],
                        }
                        return self._result(
                            "needs_input",
                            "找到多个位置，暂未启动。请选择一个：\n" + found["message"],
                            candidates=found["candidates"],
                        )
                    else:
                        return found
            elif self.state.get("last_app"):
                prior = self.state["last_app"]
                selected = {
                    "display_name": prior["name"],
                    "path": prior["target"],
                    "category": "apps",
                }
            if not selected:
                return self._result("needs_input", "你想打开哪个软件？")
            if selected.get("category") in ("folders", "websites"):
                raise ValueError("这个候选项不是软件，请使用文件夹工具或明确提供文件路径")
            path = selected.get("path") or selected.get("command")
            from services.app_launch_service import launch_application

            outcome = launch_application(
                path,
                selected.get("display_name", path),
                selected.get("arguments", ""),
                selected.get("working_dir", ""),
            )
            return self._launch_result(outcome)
        if name in ("app_status", "focus_app"):
            previous = self.state.get("last_app")
            if not previous:
                return self._result("needs_input", "当前会话没有实际启动记录。你指的是哪个软件？")
            outcome = LaunchOutcome(**previous)
            current = observe_launch(outcome.name, outcome.target, activate=name == "focus_app")
            if current.status in ("window", "process") or outcome.status != "failed":
                outcome = current
            return self._launch_result(outcome)
        if name == "open_path":
            path = args["path"]
            supplied = any(
                path.casefold() in r["content"].casefold()
                for r in self.context
                if r["role"] == "user"
            )
            if not supplied:
                raise ValueError("该路径不是用户明确提供的，不能按模型猜测的路径执行")
            message = apps.open_path(path)
            if apps.last_launch:
                return self._launch_result(apps.last_launch)
            return self._result("requested", message)
        if name == "open_folder":
            message = apps.open_entry(args["kind"])
            return self._result(
                "error" if message.startswith(("⚠", "已自动查找")) else "requested", message
            )
        if name == "open_browser":
            url = args.get("url", "")
            if url and not url.startswith(("https://", "http://")):
                raise ValueError("只支持http或https网页地址")
            message = apps.open_browser(url)
            return self._result("error" if message.startswith("⚠") else "requested", message)
        if name == "create_reminder":
            text = args["text"]
            try:
                parsed = parse_reminder(text)
            except ValueError as exc:
                self.state["awaiting"] = {
                    "kind": "reminder",
                    "text": text,
                    "created_at": time.time(),
                }
                self.state["focus"] = {"kind": "reminder_draft"}
                return self._result("needs_input", str(exc) + "。请补充缺少的信息。")
            ident = self.dispatcher.todos.add(**parsed)
            self.state["last_reminder"] = ident
            self.state["focus"] = {"kind": "reminder", "id": ident}
            self.state.pop("awaiting", None)
            return self._result(
                "completed",
                f"已设置提醒 #{ident}：{parsed['title']}\n{parsed['remind_time']}",
                reminder={"id": ident, **parsed},
            )
        if name in ("update_reminder", "delete_reminder", "complete_reminder"):
            focus = self.state.get("focus", {})
            ident = args.get("id") or (focus.get("id") if focus.get("kind") == "reminder" else None)
            row = next((r for r in self.dispatcher.todos.all() if r["id"] == ident), None)
            if not row:
                return self._result(
                    "needs_input", "没有找到当前提醒，请先查看提醒列表或指定提醒编号。"
                )
            if name == "delete_reminder":
                message = self.dispatcher.todos.delete_todo(ident)
                self.state.pop("last_reminder", None)
            elif name == "complete_reminder":
                self.dispatcher.todos.complete(ident)
                message = f"已完成提醒 #{ident}。"
            else:
                title = args.get("title", row["title"])
                if not args.get("time_text") and not args.get("title"):
                    return self._result("needs_input", "你想修改提醒的时间还是内容？")
                update = (
                    parse_reminder(args["time_text"] + "提醒我" + title)
                    if args.get("time_text")
                    else dict(row)
                )
                if args.get("time_text") and not re.search(r"每天|每周|每隔", args["time_text"]):
                    update["recurrence"] = row["recurrence"]
                with self.dispatcher.todos.db.connect() as conn:
                    conn.execute(
                        "UPDATE todos SET title=?,remind_time=?,recurrence=?,status='pending',notified_at=NULL WHERE id=?",
                        (title, update["remind_time"], update["recurrence"], ident),
                    )
                self.state["last_reminder"] = ident
                self.state["focus"] = {"kind": "reminder", "id": ident}
                message = f"已修改提醒 #{ident}：{title}\n{update['remind_time']}"
            return self._result("completed", message)
        if name == "list_reminders":
            return self._result(
                "completed",
                self.dispatcher.todos.list_todos(),
                reminders=self.dispatcher.todos.all()[:30],
            )
        if name == "save_note":
            message = self.dispatcher.notes.add_note(args["content"])
            # 以本事务实际返回的编号关联，不靠列表第一条猜测。
            ident = int(re.search(r"#(\d+)", message)[1])
            self.state["last_note"] = ident
            self.state["focus"] = {"kind": "note", "id": ident}
            return self._result("completed", message, note_id=ident)
        if name == "list_notes":
            self.state["focus"] = {"kind": "notes_list"}
            return self._result(
                "completed",
                self.dispatcher.notes.list_notes(),
                notes=self.dispatcher.notes.all()[:30],
            )
        if name in ("edit_note", "delete_note"):
            focus = self.state.get("focus", {})
            ident = args.get("id") or (focus.get("id") if focus.get("kind") == "note" else None)
            if not any(r["id"] == ident for r in self.dispatcher.notes.all()):
                return self._result("needs_input", "请先指定要修改或删除的笔记。")
            if name == "edit_note":
                self.dispatcher.notes.update(ident, args["content"])
                return self._result("completed", f"已修改笔记 #{ident}。")
            self.dispatcher.notes.delete(ident)
            self.state.pop("last_note", None)
            return self._result("completed", f"已删除笔记 #{ident}。")
        if name == "desktop_action":
            action = args["action"]
            data = {k: v for k, v in args.items() if k != "action"}
            required = {
                "close_app": "name",
                "search": "query",
                "calculate": "expression",
                "mkdir": "path",
                "weather": "city",
                "media": "key",
            }
            if action in required and not data.get(required[action]):
                return self._result("needs_input", f"还需要提供{required[action]}，操作没有执行。")
            if action in ("volume_up", "volume_down"):
                data.setdefault("amount", 10)
            if action == "search":
                data.setdefault("engine", "")
            if action == "shutdown":
                data.setdefault("seconds", 60)
                data.setdefault("restart", False)
            if action == "weather":
                from services.weather_service import weather

                message = asyncio.run(weather(data["city"], self.cancel))
            else:
                message = self.dispatcher.execute(CommandResult(True, action, data))
            status = (
                "error"
                if str(message).startswith(("⚠", "未能", "找不到", "没有找到"))
                else "completed"
            )
            return self._result(status, str(message))
        if name == "ask_user":
            self.state["awaiting"] = {
                "kind": "app_choice"
                if self.state.get("focus", {}).get("kind") == "app_choices"
                else "question",
                "question": args["question"],
                "created_at": time.time(),
            }
            return self._result("needs_input", args["question"])
        if name == "cancel_pending":
            self.state.pop("awaiting", None)
            self.state.pop("confirmation", None)
            self.state.pop("last_action", None)
            self.state.pop("focus", None)
            return self._result("completed", "已取消尚未执行的任务；已经完成的操作保持原状。")
        if name == "retry_last":
            if self.unsettled:
                return self._result(
                    "uncertain",
                    "之前有操作缺少完成记录，暂不重复执行。请先查询实际结果，或明确给出新的操作指令。",
                )
            last = self.state.get("last_action")
            if not last:
                return self._result("needs_input", "当前会话没有可重试的操作，请说明要做什么。")
            return self.execute(last["name"], last["arguments"])
        raise ValueError("工具未实现")

    def approve(self, token):
        pending = self.state.get("confirmation")
        if not pending or pending["token"] != token or time.time() - pending["created_at"] > 300:
            return self._result("error", "确认已失效，操作没有执行。")
        self.state.pop("confirmation", None)
        self.store.save(self.state)
        return self.execute(pending["name"], pending["arguments"], approved=True)

    def authoritative_reply(self, proposed=""):
        # 执行后的文字以实际工具结果为准，不让模型把失败或未知改写成成功。
        if not self.results:
            return proposed
        facts = "\n\n".join(r["message"] for r in self.results[-6:])
        # 查询事实后仍允许模型解释和分析；执行回执本身不能被改写成另一个结果。
        if (
            proposed.strip()
            and proposed.strip() != facts.strip()
            and all(not r.get("changes_state") and r["status"] == "completed" for r in self.results)
            and not re.search(r"已(?:经)?(?:打开|启动|删除|创建|设置)|正在打开", proposed)
        ):
            return facts + "\n\n" + proposed
        return facts
