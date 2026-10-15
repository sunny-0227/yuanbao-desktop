import threading

from conftest import wait_for

from app.config import AppConfig, ConfigStore
from app.controller import AppController


def make_controller(db, tmp_path):
    cfg = AppConfig()
    cfg.voice.voice_enabled = cfg.voice.tts_enabled = cfg.voice.wake_enabled = False
    cfg.behavior.auto_sleep_enabled = False
    store = ConfigStore(tmp_path / "config.json")
    store.save(cfg)
    return AppController(cfg, db, store)


def test_chat_and_follow_up(qt_core, db, tmp_path, monkeypatch):
    controller = make_controller(db, tmp_path)
    contexts = []

    def answer(context, cancel, chunk, status):
        contexts.append(context)
        chunk("reply")
        return "reply"

    monkeypatch.setattr(controller.ai, "ask", answer)
    try:
        controller.send("帮我写一段介绍")
        wait_for(qt_core, lambda: not controller.current)
        controller.send("改短一点")
        wait_for(qt_core, lambda: not controller.current)
        assert [row["role"] for row in contexts[1]] == ["user", "assistant", "user"]
        assert len(controller.history.messages(controller.active_session)) == 4
    finally:
        controller.shutdown()


def test_confirmation_and_cancel(qt_core, db, tmp_path, monkeypatch):
    controller = make_controller(db, tmp_path)
    invoked = []
    monkeypatch.setattr(
        controller.dispatcher, "execute", lambda cmd: invoked.append(cmd.action) or "done"
    )
    try:
        controller.send("清空回收站")
        assert controller.pending is not None
        assert invoked == []
        controller.confirm(False)
        assert invoked == []
        controller.send("清空回收站")
        controller.confirm(True)
        wait_for(qt_core, lambda: not controller.current)
        assert invoked == ["recycle"]
    finally:
        controller.shutdown()


def test_old_results_do_not_pollute_new_session(qt_core, db, tmp_path, monkeypatch):
    controller = make_controller(db, tmp_path)
    started = threading.Event()

    def answer(context, cancel, chunk, status):
        started.set()
        cancel.wait(1)
        return "late old reply"

    monkeypatch.setattr(controller.ai, "ask", answer)
    try:
        old_session = controller.active_session
        controller.send("帮我写一段内容")
        assert started.wait(1)
        controller.new_session()
        wait_for(qt_core, lambda: not controller.executor.jobs)
        assert controller.history.messages(controller.active_session) == []
        assert controller.history.messages(old_session) == [
            {"role": "user", "content": "帮我写一段内容"}
        ]
    finally:
        controller.shutdown()


def test_settings_do_not_cancel_chat_for_theme(qt_core, db, tmp_path, monkeypatch):
    controller = make_controller(db, tmp_path)
    invoked = []
    monkeypatch.setattr(controller, "cancel", lambda: invoked.append(True))
    try:
        new_cfg = controller.store.load(environment=False)
        new_cfg.ui.theme = "dark"
        controller.save_config(new_cfg)
        assert invoked == []
        assert controller.store.load(environment=False).ui.theme == "dark"
    finally:
        controller.shutdown()


def test_reminder_empty_does_not_poll(qt_core, db, tmp_path):
    controller = make_controller(db, tmp_path)
    try:
        controller._reminders()
        assert not controller.reminder_timer.isActive()
    finally:
        controller.shutdown()


def test_idle_has_no_stream_polling(qt_core, db, tmp_path):
    controller = make_controller(db, tmp_path)
    try:
        assert not controller.stream_timer.isActive()
    finally:
        controller.shutdown()


def test_unsaved_input_not_executed(qt_core, db, tmp_path, monkeypatch):
    controller = make_controller(db, tmp_path)
    errors = []
    controller.message.connect(lambda role, text: errors.append(role))

    def fail(*args):
        raise OSError("disk full")

    monkeypatch.setattr(controller.history, "append", fail)
    try:
        controller.send("截图")
        assert not controller.current
        assert errors == ["error"]
    finally:
        controller.shutdown()
