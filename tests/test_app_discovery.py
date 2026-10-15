from types import SimpleNamespace

import pytest

from app.config import AppConfig
from services import app_command_service as commands
from services import app_discovery_service as discovery
from services import app_launch_service as launching
from services.command_router import CommandRouter


def make_exe(tmp_path, name="Weixin.exe"):
    path = tmp_path / "custom installation" / name
    path.parent.mkdir(exist_ok=True, parents=True)
    path.write_bytes(b"not an executable; never run in tests")
    return str(path)


def service_with_inventory(tmp_path, monkeypatch, inventory):
    service = discovery.AppDiscoveryService()
    service._index_path = str(tmp_path / "index.json")
    monkeypatch.setattr(
        service, "scan_shortcuts", lambda: {"apps": [], "folders": [], "websites": []}
    )
    monkeypatch.setattr(service, "scan_registered_apps", lambda: inventory)
    monkeypatch.setattr(service, "scan_running_apps", lambda: [])
    return service


def test_stale_default_replaced_by_actual_installation_and_cached(tmp_path, monkeypatch):
    actual = make_exe(tmp_path)
    inventory = [{"display_name": "微信", "path": actual, "source": "registry_install"}]
    service = service_with_inventory(tmp_path, monkeypatch, inventory)
    cfg = AppConfig()
    cfg.quick_apps = [{"name": "微信", "command": str(tmp_path / "old default" / "WeChat.exe")}]
    launcher = commands.AppCommandService(cfg, service)
    monkeypatch.setattr(commands, "is_windows", lambda: True)
    opened = []
    monkeypatch.setattr(launching, "is_windows", lambda: True)
    monkeypatch.setattr(launching.os, "startfile", opened.append, raising=False)
    monkeypatch.setattr(
        launching,
        "observe_launch",
        lambda name, path, activate=False: launching.LaunchOutcome(name, path, "window"),
    )
    assert "可见窗口" in launcher.open_entry("微信")
    assert opened == [actual]
    assert actual in launcher.find_entry_path("微信")
    assert opened == [actual]  # 查询不再次启动软件
    monkeypatch.setattr(
        service, "build_app_index", lambda: pytest.fail("valid cached path rescanned")
    )
    assert service.resolve_entry("WeChat")["path"] == actual


def test_moved_cached_application_is_rediscovered(tmp_path, monkeypatch):
    old = make_exe(tmp_path)
    entries = [{"display_name": "微信", "path": old, "source": "registry_install"}]
    service = service_with_inventory(tmp_path, monkeypatch, entries)
    assert service.resolve_entry("微信")["path"] == old
    from pathlib import Path

    new = Path(old).with_name("WeChat.exe")
    Path(old).rename(new)
    entries[0]["path"] = str(new)
    assert service.resolve_entry("微信")["path"] == str(new)


def test_valid_explicit_config_keeps_priority(tmp_path, monkeypatch):
    path = make_exe(tmp_path)
    service = service_with_inventory(tmp_path, monkeypatch, [])
    monkeypatch.setattr(service, "resolve_entry", lambda name: pytest.fail("valid config ignored"))
    cfg = AppConfig()
    cfg.quick_apps = [{"name": "微信", "command": path}]
    assert commands.AppCommandService(cfg, service)._lookup("微信")["path"] == path


def test_ambiguous_installations_are_not_launched(tmp_path, monkeypatch):
    first, second = make_exe(tmp_path), make_exe(tmp_path, "WeChat.exe")
    entries = [
        {"display_name": "微信", "path": p, "source": "desktop_shortcut"} for p in [first, second]
    ]
    service = service_with_inventory(tmp_path, monkeypatch, entries)
    monkeypatch.setattr(commands, "is_windows", lambda: True)
    monkeypatch.setattr(
        commands, "_startfile", lambda path: pytest.fail("ambiguous application launched")
    )
    reply = commands.AppCommandService(AppConfig(), service).open_entry("微信")
    assert "多个" in reply and first in reply and second in reply


def test_duplicate_sources_for_same_target_are_not_ambiguous(tmp_path, monkeypatch):
    path = make_exe(tmp_path)
    entries = [
        {"display_name": "微信", "path": path, "source": source}
        for source in ["registry_install", "desktop_shortcut", "running_process"]
    ]
    service = service_with_inventory(tmp_path, monkeypatch, entries)
    assert service.resolve_entry("微信")["path"] == path


def test_nested_shortcuts_and_desktop_executables(tmp_path, monkeypatch):
    root = tmp_path / "relocated desktop"
    nested = root / "Tools" / "Office" / "Tencent"
    nested.mkdir(parents=True)
    shortcut = nested / "微信.lnk"
    shortcut.touch()
    exe = make_exe(root, "PortableTool.exe")
    target = make_exe(tmp_path)
    monkeypatch.setattr(discovery.platform, "system", lambda: "Windows")
    monkeypatch.setattr(discovery, "_scan_sources", lambda: [("desktop_shortcut", str(root))])
    monkeypatch.setattr(
        discovery,
        "_parse_lnk",
        lambda path, source: {
            "display_name": "微信",
            "path": target,
            "entry_type": "app",
            "source": source,
            "arguments": "--profile work",
        },
    )
    result = discovery.AppDiscoveryService().scan_shortcuts()
    assert {a["path"] for a in result["apps"]} == {target, exe}
    assert next(a for a in result["apps"] if a["path"] == target)["arguments"] == "--profile work"


def test_executable_extraction_never_uses_uninstaller_or_shell(tmp_path):
    path = make_exe(tmp_path)
    assert discovery._safe_executable('"' + path + '",0') == path
    assert discovery._safe_executable(path + " --some-argument") == path
    uninstall = make_exe(tmp_path, "Uninstall.exe")
    assert discovery._safe_executable(uninstall) == ""
    assert discovery._safe_executable("cmd /c start " + path) == ""
    assert (
        discovery.AppDiscoveryService._find_installed_exe(
            str(__import__("pathlib").Path(path).parent), "微信"
        )
        == path
    )


def fake_registry(monkeypatch, nodes):
    import sys

    class Key:
        def __init__(self, data):
            self.data = data

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

    calls = []

    def open_key(root, path, reserved=0, access=0):
        calls.append((root, path, access))
        if (root, path) not in nodes:
            raise FileNotFoundError(path)
        return Key(nodes[root, path])

    def value(key, name):
        if name not in key.data.get("values", {}):
            raise FileNotFoundError(name)
        return key.data["values"][name], 1

    registry = SimpleNamespace(
        HKEY_CURRENT_USER=1,
        HKEY_LOCAL_MACHINE=2,
        KEY_READ=1,
        KEY_WOW64_64KEY=256,
        KEY_WOW64_32KEY=512,
        OpenKey=open_key,
        QueryValueEx=value,
        QueryInfoKey=lambda k: (len(k.data.get("children", [])), 0, 0),
        EnumKey=lambda k, i: k.data["children"][i],
    )
    monkeypatch.setitem(sys.modules, "winreg", registry)
    return calls


def test_registry_current_user_machine_and_both_views(tmp_path, monkeypatch):
    path = make_exe(tmp_path)
    app = r"Software\Microsoft\Windows\CurrentVersion\App Paths"
    uninstall = r"Software\Microsoft\Windows\CurrentVersion\Uninstall"
    nodes = {
        (1, app): {"children": ["Weixin.exe"]},
        (1, app + r"\Weixin.exe"): {"values": {"": '"' + path + '"'}},
        (2, uninstall): {"children": ["CustomWeChat"]},
        (2, uninstall + r"\CustomWeChat"): {
            "values": {"DisplayName": "微信", "DisplayIcon": '"' + path + '",0'}
        },
    }
    calls = fake_registry(monkeypatch, nodes)
    monkeypatch.setattr(discovery.platform, "system", lambda: "Windows")
    found = discovery.AppDiscoveryService().scan_registered_apps()
    assert {a["display_name"] for a in found} == {"微信", "Weixin"}
    assert {a["path"] for a in found} == {path}
    assert any(root == 1 and access == 257 for root, _, access in calls)
    assert any(root == 2 and access == 513 for root, _, access in calls)


def test_redirected_desktop_and_onedrive_are_scan_sources(tmp_path, monkeypatch):
    branch = r"Software\Microsoft\Windows\CurrentVersion\Explorer\User Shell Folders"
    moved = str(tmp_path / "Desktop on another drive")
    fake_registry(monkeypatch, {(1, branch): {"values": {"Desktop": moved}}})
    monkeypatch.setenv("OneDrive", str(tmp_path / "OneDrive"))
    sources = discovery._scan_sources()
    assert ("desktop_shortcut", moved) in sources
    assert ("desktop_shortcut", str(tmp_path / "OneDrive" / "Desktop")) in sources


def test_wechat_helper_process_is_not_aliased_as_wechat():
    assert "微信" in discovery._build_aliases("Weixin")
    assert "微信" not in discovery._build_aliases("WeChatAppEx")
    assert "WeChat" not in discovery._build_aliases("微信输入法")


@pytest.mark.parametrize("text", ["你找下我微信路径", "帮我查一下微信的安装位置", "微信路径在哪里"])
def test_path_queries_stay_local(text):
    result = CommandRouter().route(text)
    assert result.action == "find_app" and result.data["name"] == "微信"


def test_open_desktop_app_by_icon_name():
    assert CommandRouter().route("打开桌面上的微信").data["name"] == "微信"
    assert not CommandRouter().route("不要打开微信").handled
    assert not CommandRouter().route("解释一下如何找微信路径").handled


def test_shortcut_arguments_survive_reindexing_and_launch(tmp_path, monkeypatch):
    path = make_exe(tmp_path)
    service = service_with_inventory(
        tmp_path,
        monkeypatch,
        [
            {
                "display_name": "微信",
                "path": path,
                "source": "start_menu",
                "arguments": "--profile work",
                "working_dir": str(tmp_path),
            }
        ],
    )
    monkeypatch.setattr(commands, "is_windows", lambda: True)
    calls = []
    monkeypatch.setattr(commands, "_launch_exe", lambda *args: calls.append(args) or "opened")
    assert commands.AppCommandService(AppConfig(), service).open_entry("微信") == "opened"
    assert calls == [(path, "微信", "--profile work", str(tmp_path))]


@pytest.mark.skipif(__import__("sys").platform != "win32", reason="真实快捷方式解析仅在Windows验证")
def test_real_windows_shortcut_to_custom_location(tmp_path):
    import os
    import sys

    import pythoncom
    import win32com.client

    pythoncom.CoInitialize()
    try:
        link = tmp_path / "My Desktop App.lnk"
        shortcut = win32com.client.Dispatch("WScript.Shell").CreateShortcut(str(link))
        shortcut.TargetPath = sys.executable
        shortcut.Arguments = "--version"
        shortcut.WorkingDirectory = str(tmp_path)
        shortcut.Save()
        entry = discovery._parse_lnk(str(link), "desktop_shortcut")
        assert entry is not None
        assert os.path.normcase(entry["path"]) == os.path.normcase(sys.executable)
        assert entry["arguments"] == "--version"
        assert entry["working_dir"] == str(tmp_path)
    finally:
        pythoncom.CoUninitialize()
