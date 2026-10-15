from types import SimpleNamespace

import pytest

from app.config import AppConfig
from services import app_command_service as commands
from services import app_launch_service as launching
from services.command_router import CommandRouter


@pytest.mark.parametrize(
    "text",
    [
        r'打开"C:\Users\ido\Downloads\Claude Setup (1).exe"这个',
        r'"C:\Users\ido\Downloads\Claude Setup (1).exe"打开',
        r"打开 C:\Users\ido\Downloads\Claude Setup (1).exe",
        "打开“C:\\Users\\ido\\Downloads\\Claude Setup (1).exe”",
    ],
)
def test_explicit_quoted_path_routes_to_real_local_execution(text):
    command = CommandRouter().route(text)
    assert command.action == "open_path"
    assert command.data["path"] == r"C:\Users\ido\Downloads\Claude Setup (1).exe"


@pytest.mark.parametrize("text", ["打开了嘛", "打开了吗？", "启动成功了吗", "打开了没"])
def test_open_status_followup_is_not_an_application_name(text):
    command = CommandRouter().route(text)
    assert command.action == "check_open"
    assert not command.data


@pytest.mark.parametrize("text", [r'不要打开"C:\app.exe"', r'解释一下打开"C:\app.exe"的意思'])
def test_quoted_path_does_not_override_negation_or_discussion(text):
    assert not CommandRouter().route(text).handled


def prepare_launch(tmp_path, monkeypatch):
    target = tmp_path / "custom app.exe"
    target.touch()
    monkeypatch.setattr(launching, "is_windows", lambda: True)
    requests = []
    monkeypatch.setattr(launching.os, "startfile", requests.append, raising=False)
    monkeypatch.setattr(launching, "_process_ids", lambda path: set())
    monkeypatch.setattr(launching, "_find_window", lambda pids, activate=False: False)
    return target, requests


def test_accepted_launch_request_is_not_reported_as_open_window(tmp_path, monkeypatch):
    target, requests = prepare_launch(tmp_path, monkeypatch)
    outcome = launching.launch_application(str(target), "测试软件", timeout=0)
    assert requests == [str(target)]
    assert outcome.status == "requested"
    assert "暂未确认" in str(outcome) and "已打开" not in str(outcome)


def test_running_process_without_window_is_reported_accurately(tmp_path, monkeypatch):
    target, _ = prepare_launch(tmp_path, monkeypatch)
    monkeypatch.setattr(launching, "_process_ids", lambda path: {123})
    outcome = launching.launch_application(str(target), "测试软件", timeout=0)
    assert outcome.status == "process"
    assert "尚未检测到可见窗口" in str(outcome)


def test_visible_window_is_required_for_window_confirmation(tmp_path, monkeypatch):
    target, _ = prepare_launch(tmp_path, monkeypatch)
    monkeypatch.setattr(launching, "_process_ids", lambda path: {123})
    monkeypatch.setattr(launching, "_find_window", lambda pids, activate=False: bool(pids))
    assert launching.launch_application(str(target), "测试软件", timeout=0).status == "window"


def test_missing_file_never_sends_request(tmp_path, monkeypatch):
    _, requests = prepare_launch(tmp_path, monkeypatch)
    assert (
        launching.launch_application(str(tmp_path / "missing.exe"), "测试软件", timeout=0).status
        == "failed"
    )
    assert not requests


def test_explicit_shortcut_resolves_target_arguments_and_working_directory(tmp_path, monkeypatch):
    target, requests = prepare_launch(tmp_path, monkeypatch)
    shortcut = tmp_path / "My App.lnk"
    shortcut.touch()
    monkeypatch.setattr(
        launching,
        "_parse_lnk",
        lambda path, source: {
            "path": str(target),
            "arguments": "--profile work",
            "working_dir": str(tmp_path),
        },
    )
    calls = []
    monkeypatch.setattr(
        launching.subprocess,
        "Popen",
        lambda args, **kw: calls.append((args, kw)) or SimpleNamespace(poll=lambda: None),
    )
    launching.launch_application(str(shortcut), "测试软件", timeout=0)
    assert not requests
    assert str(target) in calls[0][0] and "--profile work" in calls[0][0]
    assert calls[0][1] == {"shell": False, "cwd": str(tmp_path)}


def test_status_question_checks_existing_request_without_relaunch(tmp_path, monkeypatch):
    target, _ = prepare_launch(tmp_path, monkeypatch)
    service = commands.AppCommandService(AppConfig())
    service.last_launch = launching.LaunchOutcome("测试软件", str(target), "requested")
    monkeypatch.setattr(
        commands, "observe_launch", lambda name, path: launching.LaunchOutcome(name, path, "window")
    )
    monkeypatch.setattr(
        commands, "_launch_exe", lambda *args: pytest.fail("followup relaunched app")
    )
    assert "可见窗口" in service.check_last_launch()


def test_no_local_request_has_no_invented_success():
    service = commands.AppCommandService(AppConfig())
    assert "没有实际启动" in service.check_last_launch()


@pytest.mark.skipif(__import__("sys").platform != "win32", reason="原生Windows窗口验证")
def test_observer_finds_real_window_by_exact_process_path():
    import os
    import sys

    import win32con
    import win32gui

    hwnd = win32gui.CreateWindowEx(
        0,
        "STATIC",
        "Yuanbao launch verifier",
        win32con.WS_OVERLAPPEDWINDOW,
        0,
        0,
        120,
        80,
        0,
        0,
        0,
        None,
    )
    try:
        win32gui.ShowWindow(hwnd, win32con.SW_SHOWNOACTIVATE)
        win32gui.UpdateWindow(hwnd)
        pids = launching._process_ids(sys.executable)
        assert os.getpid() in pids
        assert launching._find_window({os.getpid()})
    finally:
        win32gui.DestroyWindow(hwnd)
