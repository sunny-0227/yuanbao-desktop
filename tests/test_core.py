import json
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta

import pytest

from app.app_context import data_path, resource_path
from app.config import ConfigStore, config_from_dict
from app.state_manager import StateManager
from services.cache_service import CacheService
from services.chat_history import ChatHistory
from services.command_router import CommandRouter
from services.note_service import NoteService
from services.todo_service import TodoService, parse_reminder
from services.tools_service import calculate


@pytest.mark.parametrize(
    "text,action",
    [
        ("取消静音", "unmute"),
        ("取消消音", "unmute"),
        ("静音", "mute"),
        ("帮我打开微信", "open"),
        ("截图", "screenshot"),
        ("十分钟后提醒我喝水", "add_todo"),
        ("明天下午3点提醒我开会", "add_todo"),
        ("查看提醒", "todos"),
        ("清空回收站", "recycle"),
        ("计算 1+2*3", "calculate"),
        ("10分钟后关机", "shutdown"),
        ("查询上海天气", "weather"),
        ("取消关机", "cancel_shutdown"),
    ],
)
def test_routing(text, action):
    assert CommandRouter().route(text).action == action


@pytest.mark.parametrize(
    "text",
    [
        "不要截图",
        "别锁屏",
        "取消静音是什么意思",
        "解释一下锁屏功能",
        "我今天看了一个截图",
        "你能写一段关于静音的代码吗",
        "为什么要清空笔记",
    ],
)
def test_no_accidental_execution(text):
    assert not CommandRouter().route(text).handled


def test_confirmation():
    assert CommandRouter().route("清空笔记").confirmation
    assert CommandRouter().route("关闭微信").confirmation


def test_packaged_user_config(tmp_path, monkeypatch):
    bundle = tmp_path / "bundle"
    bundle.mkdir()
    (bundle / "config.json").write_text(json.dumps({"voice_enabled": False}))
    monkeypatch.setattr(sys, "_MEIPASS", str(bundle), raising=False)
    monkeypatch.setenv("YUANBAO_DATA_DIR", str(tmp_path / "user"))
    store = ConfigStore()
    cfg = store.load(environment=False)
    assert not cfg.voice.voice_enabled
    cfg.search.engine = "google"
    store.save(cfg)
    assert ConfigStore().load(environment=False).search.engine == "google"
    assert json.loads((bundle / "config.json").read_text()) == {"voice_enabled": False}
    assert data_path("data/notes.json") == data_path("notes.json")
    assert resource_path("assets") == str(bundle / "assets")


@pytest.mark.parametrize(
    "raw",
    [
        {"ui": {"pet_size": 1}},
        {"behavior": {"cpu_sleep_threshold": 101}},
        {"ui": {"font_size": "12"}},
        {"ai_endpoints": ["invalid"]},
        [],
    ],
)
def test_invalid_config(raw):
    with pytest.raises(ValueError):
        config_from_dict(raw)


def test_manual_sleep():
    state = StateManager()
    state.set_state("sleep", manual=True)
    assert not state.set_state("idle")
    assert state.get_state() == "sleep"
    state.touch_interaction()
    assert state.get_state() == "active"
    assert not state.manual_sleep


def test_natural_reminders():
    now = datetime(2026, 10, 14, 12)
    assert parse_reminder("十分钟后提醒我喝水", now)["remind_time"] == "2026-10-14 12:10:00"
    assert parse_reminder("明天下午3点提醒我开会", now)["remind_time"] == "2026-10-15 15:00:00"
    daily = parse_reminder("每天18:30提醒我休息", now)
    assert daily["recurrence"] == "daily"
    assert daily["title"] == "休息"
    assert parse_reminder("每周一9点提醒我开会", now)["remind_time"] == "2026-10-19 09:00:00"
    assert parse_reminder("每隔30分钟提醒我休息", now)["recurrence"] == "interval:1800"


@pytest.mark.parametrize(
    "text",
    [
        "提醒我2026-13-01 20:00开会",
        "提醒我2020-01-01 20:00开会",
        "今天9点提醒我喝水",
        "提醒我25:00喝水",
    ],
)
def test_invalid_reminder_not_silently_changed(text):
    with pytest.raises(ValueError):
        parse_reminder(text, datetime(2026, 10, 14, 12))


def test_due_acknowledgement(db):
    service = TodoService(db)
    ident = service.add("开会", (datetime.now() + timedelta(minutes=2)).isoformat())
    future = datetime.now() + timedelta(minutes=3)
    assert service.check_due_todos(future)[0]["id"] == ident
    assert service.all()[0]["status"] == "pending"
    service.acknowledge(ident, future)
    assert service.all()[0]["status"] == "notified"
    service.complete(ident)
    assert service.all()[0]["status"] == "completed"


def test_repeat_skips_missed_occurrences(db):
    service = TodoService(db)
    due = datetime.now() + timedelta(minutes=1)
    ident = service.add("喝水", due.isoformat(), "interval:60")
    service.acknowledge(ident, due + timedelta(minutes=10, seconds=5))
    row = service.all()[0]
    assert row["status"] == "pending"
    assert datetime.fromisoformat(row["remind_time"]) > due + timedelta(minutes=10, seconds=5)


def test_concurrent_note_writes(db):
    service = NoteService(db)
    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(lambda i: service.add_note(f"note-{i}"), range(40)))
    assert len(service.all()) == 40
    assert len({r["id"] for r in service.all()}) == 40


def test_failed_write_not_success(db, monkeypatch):
    service = NoteService(db)

    def fail():
        raise OSError("disk full")

    monkeypatch.setattr(db, "connect", fail)
    with pytest.raises(OSError):
        service.add_note("must not say saved")


def test_history_survives_reload(db):
    history = ChatHistory(db)
    ident = history.create()
    history.append(ident, "user", "写一段介绍")
    history.append(ident, "assistant", "这是一段介绍")
    history.append(ident, "user", "改短一点")
    assert len(ChatHistory(db).context(ident)) == 3
    history.delete(ident)
    assert history.messages(ident) == []


def test_cache_fingerprint_and_ttl(db):
    cache = CacheService(True, db)
    a = CacheService.key("a" * 200 + "first", "m1", "endpoint")
    b = CacheService.key("a" * 200 + "second", "m1", "endpoint")
    c = CacheService.key("a" * 200 + "first", "m2", "endpoint")
    assert len({a, b, c}) == 3
    cache.save(a, "answer")
    assert cache.get(a) == "answer"
    cache.ttl = -1
    assert cache.get(a) is None


def test_legacy_migration(db, tmp_path):
    (tmp_path / "notes.json").write_text(json.dumps([{"content": "old", "created_at": "2026"}]))
    (tmp_path / "todos.json").write_text(
        json.dumps([{"title": "old reminder", "remind_time": "2026-10-14 10:00", "status": "done"}])
    )
    db.migrate_legacy(tmp_path)
    db.migrate_legacy(tmp_path)
    assert len(NoteService(db).all()) == 1
    assert TodoService(db).all()[0]["status"] == "notified"
    assert (tmp_path / "notes.json").exists()


def test_failed_migration_rolls_back(db, tmp_path):
    (tmp_path / "notes.json").write_text(json.dumps([{"content": "old"}]))
    (tmp_path / "todos.json").write_text("bad json")
    with pytest.raises(ValueError):
        db.migrate_legacy(tmp_path)
    assert NoteService(db).all() == []


@pytest.mark.parametrize(
    "text", ['__import__("os").system("echo hi")', "10**100000", "True+1", "x+1"]
)
def test_calculator_rejects_code(text):
    with pytest.raises(ValueError):
        calculate(text)


def test_calculator():
    assert calculate("(2+3)*4") == "20"


def test_renamed_app_keeps_legacy_data_directory(tmp_path, monkeypatch):
    from app.app_context import get_data_base_path

    monkeypatch.delenv("YUANBAO_DATA_DIR", raising=False)
    monkeypatch.delenv("TUTU_DATA_DIR", raising=False)
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    legacy = tmp_path / "TutuAssistant"
    legacy.mkdir()
    (legacy / "config.json").write_text("{}")
    assert get_data_base_path() == str(legacy)
    current = tmp_path / "Yuanbao"
    current.mkdir()
    (current / "config.json").write_text("{}")
    assert get_data_base_path() == str(current)


def test_new_data_override_wins_and_legacy_override_remains(tmp_path, monkeypatch):
    from app.app_context import get_data_base_path

    monkeypatch.setenv("TUTU_DATA_DIR", str(tmp_path / "old"))
    monkeypatch.setenv("YUANBAO_DATA_DIR", str(tmp_path / "new"))
    assert get_data_base_path() == str(tmp_path / "new")
    monkeypatch.delenv("YUANBAO_DATA_DIR")
    assert get_data_base_path() == str(tmp_path / "old")


def test_legacy_brand_config_preserves_user_settings():
    cfg = config_from_dict(
        {
            "app_name": "轻量化桌面AI效率助手",
            "pet_name": "图图助手",
            "wake_word": "图图图图",
            "ai": {"system_prompt": "你叫图图助手，请回答简短一些。", "model": "custom-model"},
            "search": {"engine": "google"},
        }
    )
    assert cfg.app_name == "元宝桌面助手"
    assert cfg.pet_name == "元宝"
    assert cfg.voice.wake_word == "元宝元宝"
    assert cfg.ai.system_prompt == "你叫元宝，请回答简短一些。"
    assert cfg.ai.model == "custom-model"
    assert cfg.search.engine == "google"
