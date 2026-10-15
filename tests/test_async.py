import asyncio
import threading
import time
from threading import Event

from conftest import wait_for

from app.config import AppConfig
from services.ai_service import AIService
from services.local_command_executor import LocalCommandExecutor


def test_worker_signals_are_main_thread(qt_core):
    executor = LocalCommandExecutor()
    received = []
    main_thread = threading.get_ident()
    executor.result.connect(lambda ident, value: received.append((threading.get_ident(), value)))
    try:
        executor.submit(lambda cancel, chunk, status: threading.get_ident())
        wait_for(qt_core, lambda: bool(received))
        assert received[0][0] == main_thread
        assert received[0][1] != main_thread
    finally:
        executor.shutdown()


def test_cancel_then_submit(qt_core):
    executor = LocalCommandExecutor()
    results = []
    executor.result.connect(lambda ident, result: results.append(result))
    started = Event()

    def slow(cancel, chunk, status):
        started.set()
        while not cancel.is_set():
            time.sleep(0.01)
        return "old"

    try:
        ident = executor.submit(slow)
        assert started.wait(1)
        executor.cancel(ident)
        executor.submit(lambda cancel, chunk, status: "new")
        wait_for(qt_core, lambda: "new" in results)
        assert results == ["new"]
    finally:
        executor.shutdown()


def test_ai_passes_context_and_cancel(db, monkeypatch):
    cfg = AppConfig()
    cfg.ai.api_key = "test"
    service = AIService(cfg, db)
    seen = []

    async def request(endpoint, messages, chunk):
        seen.extend(messages)
        chunk("hi")
        return "hi"

    monkeypatch.setattr(service, "_request", request)
    context = [
        {"role": "user", "content": "first"},
        {"role": "assistant", "content": "prior"},
        {"role": "user", "content": "follow up"},
    ]
    assert service.ask(context, Event()) == "hi"
    assert seen[1:] == context

    async def slow(endpoint, messages, chunk):
        await asyncio.sleep(5)
        return "late"

    monkeypatch.setattr(service, "_request", slow)
    cancel = Event()
    timer = threading.Timer(0.1, cancel.set)
    timer.start()
    started = time.monotonic()
    assert service.ask(context, cancel) is None
    assert time.monotonic() - started < 1
    timer.join()


def test_failover_on_quota(db, monkeypatch):
    import httpx

    cfg = AppConfig()
    cfg.ai.api_key = "test"
    cfg.ai_endpoints = [{"base_url": "http://localhost:5555/v1", "model": "backup", "api_key": ""}]
    service = AIService(cfg, db)
    called = []

    async def request(endpoint, messages, chunk):
        called.append(endpoint["model"])
        if len(called) == 1:
            response = httpx.Response(429, request=httpx.Request("POST", "https://test.example"))
            raise httpx.HTTPStatusError("quota", request=response.request, response=response)
        chunk("backup answer")
        return "backup answer"

    monkeypatch.setattr(service, "_request", request)
    assert service.ask([{"role": "user", "content": "hello"}], Event()) == "backup answer"
    assert len(called) == 2


def test_power_hysteresis(qt_core):
    from app.config import BehaviorConfig
    from app.state_manager import StateManager
    from services.auto_sleep_service import AutoSleepService

    state = StateManager()
    monitor = AutoSleepService(state, BehaviorConfig())
    sample = {"cpu": 90, "processes": [], "foreground": "", "system_idle": None}
    try:
        monitor.evaluate(sample)
        assert state.get_state() == "active"
        monitor.evaluate(sample)
        assert state.get_state() == "sleep"
        sample["cpu"] = 30
        monitor.evaluate(sample)
        assert state.get_state() == "sleep"
        monitor.evaluate(sample)
        assert state.get_state() == "idle"
        state.set_state("sleep", manual=True)
        monitor.evaluate(sample)
        monitor.evaluate(sample)
        assert state.get_state() == "sleep"
    finally:
        monitor.shutdown()
