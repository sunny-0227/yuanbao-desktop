import asyncio
import json
from threading import Event

import httpx
import pytest

from app.config import AppConfig
from app.conversation import ConversationCoordinator
from app.conversation_state import ConversationStore
from services import app_launch_service as launching
from services.ai_service import AIError, AIService, ModelTurn
from services.chat_history import ChatHistory
from services.command_dispatcher import CommandDispatcher
from services.conversation_tools import ConversationTools


def system(db, online=False):
    cfg = AppConfig()
    if online:
        cfg.ai.api_key = "test"
    dispatcher = CommandDispatcher(cfg, db=db)
    ai = AIService(cfg, db)
    coordinator = ConversationCoordinator(dispatcher, ai, db)
    history = ChatHistory(db)
    session = history.create()
    return coordinator, history, session


def say(engine, history, session, text, decision=None):
    if decision is None:
        history.append(session, "user", text)
    answer = engine.respond(
        session, history.context(session), Event(), lambda t: None, lambda t: None, decision
    )
    if answer and answer.text:
        history.append(session, "assistant", answer.text)
    return answer


def call(name, args, ident="call-1"):
    return ModelTurn(
        "",
        [
            {
                "id": ident,
                "type": "function",
                "function": {"name": name, "arguments": json.dumps(args, ensure_ascii=False)},
            }
        ],
    )


def test_reminder_followups_keep_content_and_modify_same_record(db):
    engine, history, session = system(db)
    assert "补充" in say(engine, history, session, "十分钟后提醒我").text
    assert not engine.dispatcher.todos.all()
    assert "喝水" in say(engine, history, session, "喝水").text
    original = engine.dispatcher.todos.all()[0]
    assert "已修改" in say(engine, history, session, "改成半小时后").text
    changed = engine.dispatcher.todos.all()[0]
    assert changed["id"] == original["id"] and changed["title"] == "喝水"
    assert changed["remind_time"] > original["remind_time"]
    other = history.create()
    say(engine, history, other, "改成半小时后")
    assert engine.dispatcher.todos.all() == [changed]


def test_cancellation_discards_draft_and_does_not_create_reminder(db):
    engine, history, session = system(db)
    say(engine, history, session, "十分钟后提醒我")
    say(engine, history, session, "算了")
    say(engine, history, session, "喝水")
    assert not engine.dispatcher.todos.all()
    assert not ConversationStore(db, session).load().get("awaiting")


def test_unknown_wording_uses_real_tool_call_and_result(db, monkeypatch):
    engine, history, session = system(db, True)
    seen = []

    async def request(endpoint, messages, chunk, tools=None):
        seen.append(messages.copy())
        if len(seen) == 1:
            return call("save_note", {"content": "下午记得拿快递"})
        assert messages[-1]["role"] == "tool"
        assert json.loads(messages[-1]["content"])["status"] == "completed"
        return ModelTurn("已经记录")

    monkeypatch.setattr(engine.ai, "_request", request)
    answer = say(engine, history, session, "快递这事先替我存着，下午要拿")
    assert "已记录" in answer.text
    assert engine.dispatcher.notes.all()[0]["content"] == "下午记得拿快递"
    assert len(seen) == 2
    assert seen[0][1]["content"].startswith("会话任务状态")
    events = ConversationStore(db, session).recent()
    assert events[-1]["name"] == "save_note" and events[-1]["status"] == "completed"


def test_duplicate_tool_request_within_turn_is_not_executed_twice(db, monkeypatch):
    engine, history, session = system(db, True)
    rounds = []

    async def request(endpoint, messages, chunk, tools=None):
        rounds.append(1)
        if len(rounds) <= 2:
            return call(
                "create_reminder", {"text": "十分钟后提醒我喝水"}, "call-" + str(len(rounds))
            )
        return ModelTurn("完成")

    monkeypatch.setattr(engine.ai, "_request", request)
    say(engine, history, session, "稍后十分钟提醒我喝水")
    assert len(engine.dispatcher.todos.all()) == 1


def test_endpoint_failure_after_effect_does_not_replay_or_failover(db, monkeypatch):
    engine, history, session = system(db, True)
    engine.ai.config.ai_endpoints = [
        {"base_url": "https://backup.example/v1", "api_key": "test", "model": "backup"}
    ]
    seen = []

    async def request(endpoint, messages, chunk, tools=None):
        seen.append(endpoint["model"])
        if len(seen) == 1:
            return call("save_note", {"content": "只保存一次"})
        raise httpx.ConnectError("disconnected")

    monkeypatch.setattr(engine.ai, "_request", request)
    answer = say(engine, history, session, "替我存一下只保存一次")
    assert len(engine.dispatcher.notes.all()) == 1
    assert len(seen) == 2 and "backup" not in seen
    assert "实际结果" in answer.text


def test_destructive_model_tool_requires_exact_once_confirmation(db, monkeypatch):
    engine, history, session = system(db, True)
    engine.dispatcher.notes.add_note("不能静默删除")

    async def request(endpoint, messages, chunk, tools=None):
        return call("desktop_action", {"action": "clear_notes"})

    monkeypatch.setattr(engine.ai, "_request", request)
    reply = say(engine, history, session, "这些笔记都不要留了，全部清空")
    assert reply.confirmation and engine.dispatcher.notes.all()
    approved = say(engine, history, session, "", reply.confirmation)
    assert "已清空" in approved.text and not engine.dispatcher.notes.all()
    assert "失效" in say(engine, history, session, "", reply.confirmation).text


def test_missing_or_unknown_tool_never_executes(db, monkeypatch):
    engine, history, session = system(db, True)

    async def request(endpoint, messages, chunk, tools=None):
        return call("run_shell", {"code": "anything"})

    monkeypatch.setattr(engine.ai, "_request", request)
    assert "无效" in say(engine, history, session, "执行个操作").text
    assert not ConversationStore(db, session).recent()


def test_claim_without_actual_call_is_not_success(db, monkeypatch):
    engine, history, session = system(db, True)

    async def request(endpoint, messages, chunk, tools=None):
        return ModelTurn("已经打开了，PID 1234")

    monkeypatch.setattr(engine.ai, "_request", request)
    answer = say(engine, history, session, "把微信调出来")
    assert "没有执行本机操作" in answer.text
    assert "1234" not in answer.text


def test_state_and_executions_survive_restart(db):
    engine, history, session = system(db)
    say(engine, history, session, "十分钟后提醒我喝水")
    fresh = ConversationCoordinator(
        CommandDispatcher(engine.dispatcher.config, db=db), engine.ai, db
    )
    say(fresh, history, session, "改成半小时后")
    assert len(fresh.dispatcher.todos.all()) == 1
    assert (
        ConversationStore(db, session).load()["last_reminder"]
        == fresh.dispatcher.todos.all()[0]["id"]
    )


def test_invalid_parameters_and_cancellation_block_mutations(db):
    engine, history, session = system(db)
    history.append(session, "user", "记下这件事")
    token = Event()
    tools = ConversationTools(engine.dispatcher, db, session, history.context(session), token)
    assert tools.execute("save_note", {"content": "x", "shell": "bad"})["status"] == "error"
    token.set()
    with pytest.raises(asyncio.CancelledError):
        tools.execute("save_note", {"content": "never save"})
    assert not engine.dispatcher.notes.all()


def test_no_start_record_failure_prevents_side_effect(db, monkeypatch):
    engine, history, session = system(db)
    history.append(session, "user", "记下x")
    tools = ConversationTools(engine.dispatcher, db, session, history.context(session), Event())
    monkeypatch.setattr(
        tools.store, "start", lambda *args: (_ for _ in ()).throw(OSError("disk full"))
    )
    with pytest.raises(OSError):
        tools.execute("save_note", {"content": "never save"})
    assert not engine.dispatcher.notes.all()


def test_choice_selection_and_window_followup_use_same_app(db, tmp_path, monkeypatch):
    engine, history, session = system(db)
    paths = [tmp_path / "first.exe", tmp_path / "second.exe"]
    for p in paths:
        p.touch()
    monkeypatch.setattr(engine.dispatcher.apps, "_lookup", lambda name: None)
    monkeypatch.setattr(
        engine.dispatcher.apps._discovery,
        "find_candidates",
        lambda name: [{"category": "apps", "display_name": "软件", "path": str(p)} for p in paths],
    )
    launched = []

    def launch(path, name, *args):
        launched.append(path)
        return launching.LaunchOutcome(name, path, "requested")

    monkeypatch.setattr(launching, "launch_application", launch)
    assert "请选择" in say(engine, history, session, "打开软件").text
    say(engine, history, session, "第二个")
    assert launched == [str(paths[1])]
    from services import conversation_tools

    monkeypatch.setattr(
        conversation_tools,
        "observe_launch",
        lambda name, path, activate=False: launching.LaunchOutcome(name, path, "process"),
    )
    assert "尚未检测到可见窗口" in say(engine, history, session, "没有弹窗").text
    assert launched == [str(paths[1])]
    assert "可重试" in say(engine, history, history.create(), "再试一次").text


def test_model_gets_actual_state_not_prior_invented_reply(db, monkeypatch):
    engine, history, session = system(db, True)
    ConversationStore(db, session).save(
        {
            "last_app": {
                "name": "微信",
                "target": "D:/Weixin.exe",
                "status": "requested",
                "detail": "",
            }
        }
    )
    history.append(session, "assistant", "旧回复：已经打开了")
    seen = []

    async def request(endpoint, messages, chunk, tools=None):
        seen.append(messages)
        return call("app_status", {}) if len(seen) == 1 else ModelTurn("好的")

    from services import conversation_tools

    monkeypatch.setattr(
        conversation_tools,
        "observe_launch",
        lambda name, path, activate=False: launching.LaunchOutcome(name, path, "requested"),
    )
    monkeypatch.setattr(engine.ai, "_request", request)
    answer = say(engine, history, session, "真的打开了吗")
    assert "暂未确认" in answer.text
    assert "actual_tool_events" in seen[0][1]["content"]


def test_http_stream_reassembles_function_arguments_without_showing_fake_preamble(db, monkeypatch):
    ai = AIService(AppConfig(), db)
    events = [
        {
            "choices": [
                {
                    "delta": {
                        "content": "我已经打开了",
                        "tool_calls": [
                            {
                                "index": 0,
                                "id": "x",
                                "type": "function",
                                "function": {"name": "open_app", "arguments": '{"na'},
                            }
                        ],
                    }
                }
            ]
        },
        {
            "choices": [
                {"delta": {"tool_calls": [{"index": 0, "function": {"arguments": 'me":"微信"}'}}]}}
            ]
        },
    ]
    body = (
        "".join("data: " + json.dumps(e, ensure_ascii=False) + "\n\n" for e in events)
        + "data: [DONE]\n\n"
    )
    payloads = []

    def respond(request):
        payloads.append(json.loads(request.content))
        return httpx.Response(
            200, headers={"content-type": "text/event-stream"}, content=body.encode()
        )

    client = httpx.AsyncClient
    monkeypatch.setattr(
        httpx,
        "AsyncClient",
        lambda **kwargs: client(transport=httpx.MockTransport(respond), **kwargs),
    )
    chunks = []
    turn = asyncio.run(
        ai._request(
            {"base_url": "https://test.example/v1", "model": "test"},
            [],
            chunks.append,
            tools=[{"type": "function"}],
        )
    )
    assert not chunks
    assert json.loads(turn.tool_calls[0]["function"]["arguments"]) == {"name": "微信"}
    assert payloads[0]["tools"] and payloads[0]["tool_choice"] == "auto"


def test_switch_topic_does_not_modify_old_reminder(db):
    engine, history, session = system(db)
    say(engine, history, session, "十分钟后提醒我喝水")
    before = engine.dispatcher.todos.all()
    say(engine, history, session, "记一下 明天取快递")
    response = say(engine, history, session, "改成半小时后")
    assert engine.dispatcher.todos.all() == before
    assert "请先" in response.text


def test_model_cannot_pick_ambiguous_candidate_in_same_turn(db, tmp_path, monkeypatch):
    engine, history, session = system(db)
    paths = [tmp_path / "a.exe", tmp_path / "b.exe"]
    for path in paths:
        path.touch()
    history.append(session, "user", "打开软件")
    tools = ConversationTools(engine.dispatcher, db, session, history.context(session), Event())
    monkeypatch.setattr(
        engine.dispatcher.apps._discovery,
        "find_candidates",
        lambda name: [{"display_name": "软件", "path": str(p)} for p in paths],
    )
    found = tools.execute("find_apps", {"name": "软件"})
    monkeypatch.setattr(
        launching,
        "launch_application",
        lambda *args: pytest.fail("model silently chose a location"),
    )
    result = tools.execute("open_app", {"candidate_id": found["candidates"][0]["id"]})
    assert result["status"] == "needs_input"


def test_probe_rejects_text_only_model_and_checks_structured_tool(db, monkeypatch):
    engine, _, _ = system(db, True)

    async def text_only(endpoint, messages, chunk, tools=None):
        return ModelTurn("连接测试成功")

    monkeypatch.setattr(engine.ai, "_request", text_only)
    with pytest.raises(AIError, match="没有返回"):
        engine.ai.test_tool_support(Event())

    async def supports_tools(endpoint, messages, chunk, tools=None):
        nonce = tools[0]["function"]["parameters"]["properties"]["nonce"]["enum"][0]
        return call("connection_probe", {"nonce": nonce})

    monkeypatch.setattr(engine.ai, "_request", supports_tools)
    assert "结构化工具调用" in engine.ai.test_tool_support(Event())
    assert not engine.dispatcher.notes.all() and not engine.dispatcher.todos.all()


def test_delete_confirmation_freezes_record_id(db):
    engine, history, session = system(db)
    say(engine, history, session, "十分钟后提醒我喝水")
    old = engine.dispatcher.todos.all()[0]["id"]
    response = say(engine, history, session, "取消提醒" + str(old))
    assert response.confirmation
    pending = ConversationStore(db, session).load()["confirmation"]
    assert pending["arguments"]["id"] == old
    # 在确认之外新增另一条提醒，不能改变确认时绑定的目标。
    new = engine.dispatcher.todos.add("新提醒", "2099-01-01 12:00:00")
    state = ConversationStore(db, session).load()
    state["focus"] = {"kind": "reminder", "id": new}
    ConversationStore(db, session).save(state)
    say(engine, history, session, "", response.confirmation)
    assert [r["id"] for r in engine.dispatcher.todos.all()] == [new]


def test_changing_daily_reminder_keeps_recurrence(db):
    engine, history, session = system(db)
    say(engine, history, session, "每天18:30提醒我喝水")
    say(engine, history, session, "改成半小时后")
    assert engine.dispatcher.todos.all()[0]["recurrence"] == "daily"


def test_read_tool_results_can_be_explained_in_same_conversation(db, monkeypatch):
    engine, history, session = system(db, True)
    monkeypatch.setattr(engine.dispatcher, "execute", lambda cmd: "实际内存使用率：80%")
    rounds = []

    async def request(endpoint, messages, chunk, tools=None):
        rounds.append(1)
        if len(rounds) == 1:
            return call("desktop_action", {"action": "status"})
        return ModelTurn("内存占用较高，可以先检查哪些应用占用较多。")

    monkeypatch.setattr(engine.ai, "_request", request)
    answer = say(engine, history, session, "电脑有点卡，帮我看一下并解释原因")
    assert "80%" in answer.text and "检查哪些应用" in answer.text


def test_unfinished_execution_is_not_retried_after_restart(db):
    engine, history, session = system(db)
    say(engine, history, session, "记一下 只保存一次")
    ConversationStore(db, session).start("save_note", {"content": "执行状态未知"})
    answer = say(engine, history, session, "再试一次")
    assert "暂不重复执行" in answer.text
    assert len(engine.dispatcher.notes.all()) == 1


def test_online_followup_uses_real_record_created_offline(db, monkeypatch):
    engine, history, session = system(db)
    say(engine, history, session, "记一下 原来的内容")
    ident = engine.dispatcher.notes.all()[0]["id"]
    engine.ai.config.ai.api_key = "test"
    turns = []

    async def request(endpoint, messages, chunk, tools=None):
        turns.append(messages)
        if len(turns) == 1:
            snapshot = json.loads(messages[1]["content"].split("：", 1)[1])
            assert snapshot["current_task"]["focus"] == {"kind": "note", "id": ident}
            assert snapshot["actual_tool_events"][-1]["name"] == "save_note"
            return call("edit_note", {"content": "去拿快递"})
        return ModelTurn("完成")

    monkeypatch.setattr(engine.ai, "_request", request)
    say(engine, history, session, "刚才那条换成去拿快递")
    notes = engine.dispatcher.notes.all()
    assert len(notes) == 1 and notes[0]["id"] == ident and notes[0]["content"] == "去拿快递"


def test_needs_input_stops_later_model_actions(db, monkeypatch):
    engine, history, session = system(db, True)

    async def request(endpoint, messages, chunk, tools=None):
        first = call("create_reminder", {"text": "十分钟后提醒我"}, "a").tool_calls[0]
        second = call("save_note", {"content": "不能擅自保存"}, "b").tool_calls[0]
        return ModelTurn("", [first, second])

    monkeypatch.setattr(engine.ai, "_request", request)
    say(engine, history, session, "十分钟后提醒我")
    assert not engine.dispatcher.notes.all() and not engine.dispatcher.todos.all()


def test_cancellation_after_effect_keeps_facts_without_more_calls(db, monkeypatch):
    engine, history, session = system(db, True)
    history.append(session, "user", "记下一件事")
    token = Event()
    calls = []

    async def request(endpoint, messages, chunk, tools=None):
        calls.append(1)
        if len(calls) == 1:
            return call("save_note", {"content": "已发生的事实"})
        token.set()
        await asyncio.sleep(10)
        raise AssertionError("request should be cancelled")

    monkeypatch.setattr(engine.ai, "_request", request)
    assert (
        engine.respond(session, history.context(session), token, lambda t: None, lambda t: None)
        is None
    )
    assert len(engine.dispatcher.notes.all()) == 1
    assert ConversationStore(db, session).recent()[-1]["status"] == "completed"


def test_non_streaming_tool_response_allows_null_content(db, monkeypatch):
    ai = AIService(AppConfig(), db)
    client = httpx.AsyncClient

    def handler(request):
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "content": None,
                            "tool_calls": call("list_reminders", {}).tool_calls,
                        }
                    }
                ]
            },
        )

    monkeypatch.setattr(
        httpx,
        "AsyncClient",
        lambda **kwargs: client(transport=httpx.MockTransport(handler), **kwargs),
    )
    turn = asyncio.run(
        ai._request(
            {"base_url": "https://test.example/v1", "model": "test"},
            [],
            lambda t: None,
            tools=[{"type": "function"}],
        )
    )
    assert turn.content == "" and turn.tool_calls[0]["function"]["name"] == "list_reminders"


def test_deleted_session_is_not_resurrected_by_late_tool_result(db):
    engine, history, session = system(db)
    store = ConversationStore(db, session)
    ident = store.start("save_note", {"content": "old task"})
    history.delete(session)
    store.finish(
        ident, {"status": "completed", "message": "late"}, {"focus": {"kind": "note", "id": 1}}
    )
    assert store.load() == {} and store.recent() == []
    with pytest.raises(RuntimeError, match="会话已删除"):
        store.start("save_note", {"content": "cannot execute"})


@pytest.mark.parametrize(
    "answer",
    [
        "是呀，我是 AI。可以帮你打开软件、设置提醒。",
        "如果微信已经打开，可以看看任务栏。",
        "我没有打开软件。",
        "你可以在日志里查找“已打开”这句话。",
        "我的形象已经设置为长毛金虎斑猫。",
        "PID 是进程编号，例如 PID: 1234。",
    ],
)
def test_chitchat_explanation_does_not_require_tool_receipt(db, monkeypatch, answer):
    engine, history, session = system(db, True)

    async def request(endpoint, messages, chunk, tools=None):
        return ModelTurn(answer)

    monkeypatch.setattr(engine.ai, "_request", request)
    assert say(engine, history, session, "你是AI吗").text == answer
    assert not ConversationStore(db, session).recent()


@pytest.mark.parametrize(
    "answer", ["已经打开微信。", "我已经帮你打开微信。", "✅ 已创建提醒。", "I've launched WeChat."]
)
def test_direct_execution_claim_still_needs_real_receipt(db, monkeypatch, answer):
    engine, history, session = system(db, True)

    async def request(endpoint, messages, chunk, tools=None):
        return ModelTurn(answer)

    monkeypatch.setattr(engine.ai, "_request", request)
    assert "没有执行本机操作" in say(engine, history, session, "打开微信").text


def test_model_snapshot_compacts_candidate_metadata_but_keeps_local_state(db):
    engine, history, session = system(db)
    store = ConversationStore(db, session)
    entry = {
        "id": "choice-1",
        "display_name": "工作台",
        "path": "D:/client.exe",
        "aliases": ["metadata" * 1000],
        "source": "registry_install",
    }
    store.save(
        {
            "choices": [entry],
            "focus": {"kind": "app_choices"},
            "last_action": {"name": "save_note", "arguments": {"content": "正文" * 4000}},
        }
    )
    tools = ConversationTools(engine.dispatcher, db, session, [], Event())
    snapshot = tools.context_state()
    assert snapshot["current_task"]["choices"][0]["id"] == "choice-1"
    assert "aliases" not in snapshot["current_task"]["choices"][0]
    assert len(json.dumps(snapshot, ensure_ascii=False)) < 1000
    assert store.load()["last_action"]["arguments"]["content"] == "正文" * 4000
