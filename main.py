"""元宝桌面助手启动入口；初始化、连接信号、退出资源清理。"""

import copy
import shutil
import sys
from pathlib import Path


def main():
    from dotenv import load_dotenv
    from PySide6.QtCore import QLockFile, QTimer
    from PySide6.QtWidgets import QApplication, QMessageBox

    from app.app_context import data_path, get_base_path
    from app.config import ConfigStore
    from app.controller import AppController
    from app.identity import APP_NAME, APP_VERSION, ORGANIZATION
    from app.logger import setup_logger
    from app.storage import Database
    from ui.floating_pet import FloatingPetWindow
    from ui.main_window import MainWindow
    from ui.reminder_popup import ReminderPopup
    from ui.style import apply_theme
    from ui.tray_menu import TrayMenu, app_icon

    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setOrganizationName(ORGANIZATION)
    app.setApplicationVersion(APP_VERSION)
    app.setQuitOnLastWindowClosed(False)
    # 明确 .env 查找路径，双击 exe 不依赖工作目录。
    env_root = (
        Path(sys.executable).parent if getattr(sys, "frozen", False) else Path(get_base_path())
    )
    load_dotenv(env_root / ".env", override=False)
    load_dotenv(data_path(".env"), override=False)
    Path(data_path()).mkdir(parents=True, exist_ok=True)
    lock = QLockFile(data_path("instance.lock"))
    lock.setStaleLockTime(0)
    if not lock.tryLock(100):
        QMessageBox.information(None, "元宝已经在运行", "请从系统托盘打开助手。")
        return 0
    logger = setup_logger()
    try:
        store = ConfigStore()
        config = store.load()
        logger = setup_logger(level=config.log_level)
        if config.ui.autostart:
            from services.startup_service import set_autostart

            try:
                set_autostart(True)
            except Exception as exc:
                logger.warning("更新元宝开机启动项失败：%s", exc)
        db = Database()
        legacy_root = env_root / "data"
        if legacy_root.resolve() != Path(data_path()).resolve():
            db.migrate_legacy(legacy_root)
            for name in ("app_index.json", "user_custom_entries.json"):
                source, target = legacy_root / name, Path(data_path(name))
                if source.exists() and not target.exists():
                    shutil.copy2(source, target)
    except Exception as exc:
        logger.exception("启动配置或数据加载失败")
        QMessageBox.critical(
            None, "无法启动元宝", f"原配置和数据已保留，请检查：\n{exc}\n\n用户目录：{data_path()}"
        )
        return 1

    apply_theme(app, config)
    app.setWindowIcon(app_icon())
    controller = AppController(config, db, store)
    window = MainWindow(store.load(environment=False))
    pet = FloatingPetWindow(config.ui)
    tray = TrayMenu(config)
    popups = {}
    mute_snapshot = None
    quitting = False

    def open_chat():
        controller.state.touch_interaction()
        window.open()

    def open_settings():
        window.open(3)

    def update_lists():
        try:
            window.chat.update_sessions(controller.history.sessions(), controller.active_session)
            window.todos.set_rows(controller.dispatcher.todos.all())
            window.notes.set_rows(controller.dispatcher.notes.all())
        except Exception as exc:
            logger.exception("列表读取失败")
            window.chat.add_message("error", str(exc))

    def confirm(command):
        descriptions = {
            "recycle": "清空回收站，删除的内容无法从回收站恢复。",
            "clear_notes": "删除全部本地笔记。",
            "shutdown": "安排系统关机或重启，请先保存工作。",
            "close_app": "请求关闭指定软件。",
            "delete_todo": "删除指定提醒。",
        }
        answer = QMessageBox.question(
            window,
            "确认操作",
            descriptions.get(command.action, command.data.get("summary", "确定执行这个操作？")),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        controller.confirm(answer == QMessageBox.StandardButton.Yes)

    def update_config(value):
        apply_theme(app, value)
        window.apply_config(value)
        window.settings.set_config(store.load(environment=False))
        window.settings.status.setText("设置已保存并生效")
        pet.apply_config(value.ui)
        tray.pet_action.blockSignals(True)
        tray.pet_action.setChecked(value.ui.pet_visible)
        tray.pet_action.blockSignals(False)
        if tray.mute_action.isChecked():
            toggle_mute(True)

    def change_ui(name, value):
        cfg = store.load(environment=False)
        setattr(cfg.ui, name, value)
        controller.save_config(cfg)

    def save_position(x, y):
        cfg = store.load(environment=False)
        cfg.ui.pet_x, cfg.ui.pet_y = x, y
        try:
            store.save(cfg)
            controller.config.ui.pet_x, controller.config.ui.pet_y = x, y
        except Exception as exc:
            tray.notify("位置保存失败", str(exc))

    def toggle_mute(muted):
        nonlocal mute_snapshot
        voice = copy.deepcopy(controller.config.voice)
        if muted:
            mute_snapshot = (voice.tts_enabled, voice.wake_enabled)
            voice.tts_enabled = voice.wake_enabled = False
        elif mute_snapshot:
            voice.tts_enabled, voice.wake_enabled = mute_snapshot
            mute_snapshot = None
        controller.audio.update_config(voice)
        window.chat.status_label.setText("静音模式已开启" if muted else "已恢复语音设置")

    def show_reminder(todo):
        try:
            if todo["id"] in popups:
                return
            popup = ReminderPopup(todo)
            popups[todo["id"]] = popup
            popup.action.connect(
                lambda action, ident: (
                    controller.manage("todos", action, {"id": ident})
                    if action != "dismiss"
                    else None
                )
            )
            popup.destroyed.connect(lambda obj=None, ident=todo["id"]: popups.pop(ident, None))
            popup.show()
            controller.reminder_shown(todo["id"])
            tray.notify("到点提醒", todo["title"])
            controller.audio.speak("到点提醒：" + todo["title"])
        except Exception as exc:
            logger.exception("提醒展示失败")
            tray.notify("提醒展示失败", str(exc))

    def service_result(name, value):
        if name == "devices":
            window.settings.set_devices(value)
        elif name == "scan":
            window.settings.scan_label.setText(
                f"识别到 {value[0]} 个软件、{value[1]} 个文件夹、{value[2]} 个网页入口。可直接按名称打开。"
            )
        elif name == "test_ai":
            window.settings.status.setText("连接成功：" + (value or "")[:100])
        elif name == "library":
            window.chat.status_label.setText(value or "记录已更新")

    def service_error(name, text):
        if name in ("test_ai", "scan", "devices"):
            window.settings.status.setText(text)
        else:
            QMessageBox.warning(window, "操作未完成", text)

    def quit_app():
        nonlocal quitting
        if quitting:
            return
        quitting = True
        window.hide()
        pet.hide()
        tray.hide()
        for popup in list(popups.values()):
            popup.close()
        controller.shutdown()
        app.quit()

    window.chat.send_requested.connect(controller.send)
    window.chat.cancel_requested.connect(controller.cancel)
    window.chat.voice_requested.connect(controller.voice)
    window.chat.new_requested.connect(controller.new_session)
    window.chat.load_requested.connect(controller.load_session)
    window.chat.delete_requested.connect(controller.delete_session)
    controller.message.connect(window.chat.add_message)
    controller.partial.connect(window.chat.set_partial)
    controller.busy.connect(window.chat.set_busy)
    controller.status.connect(window.chat.status_label.setText)
    controller.session_loaded.connect(window.chat.load_messages)
    controller.history_changed.connect(update_lists)
    controller.data_changed.connect(update_lists)
    controller.confirmation.connect(confirm)
    controller.config_changed.connect(update_config)
    controller.notification.connect(tray.notify)
    controller.reminder.connect(show_reminder)
    controller.pet_state.connect(pet.set_pet_state)
    controller.audio_state.connect(window.chat.set_audio_state)
    controller.service_result.connect(service_result)
    controller.service_error.connect(service_error)
    for kind, panel in (("todos", window.todos), ("notes", window.notes)):
        panel.action.connect(lambda action, value, k=kind: controller.manage(k, action, value))
        panel.query_changed.connect(lambda _: update_lists())
    window.settings.save_requested.connect(controller.save_config)
    window.settings.test_requested.connect(controller.test_ai)
    window.settings.scan_requested.connect(controller.scan)
    window.settings.devices_requested.connect(controller.devices)
    for source in (pet, tray):
        source.open_requested.connect(open_chat)
        source.settings_requested.connect(open_settings)
        source.sleep_requested.connect(
            lambda: controller.state.set_state("sleep", manual=True, reason="手动休眠")
        )
        source.wake_requested.connect(controller.state.touch_interaction)
        source.quit_requested.connect(quit_app)
    pet.position_changed.connect(save_position)
    pet.skin_requested.connect(lambda skin: change_ui("pet_skin", skin))
    pet.hidden_requested.connect(lambda: change_ui("pet_visible", False))
    tray.pet_toggled.connect(lambda value: change_ui("pet_visible", value))
    tray.mute_toggled.connect(toggle_mute)
    tray.voice_requested.connect(lambda: (open_chat(), controller.voice()))
    window.closed_to_tray.connect(lambda: controller.audio.stop())
    app.aboutToQuit.connect(controller.shutdown)
    update_lists()
    window.chat.load_messages(controller.history.messages(controller.active_session))
    if "--autostart" in sys.argv:
        pet.hide()
        QTimer.singleShot(10000, lambda: pet.show() if controller.config.ui.pet_visible else None)
    else:
        open_chat()
    if not Path(data_path("app_index.json")).exists():
        QTimer.singleShot(10000, controller.scan)
    try:
        return app.exec()
    finally:
        controller.shutdown()
        lock.unlock()


if __name__ == "__main__":
    import multiprocessing

    multiprocessing.freeze_support()
    sys.exit(main())
