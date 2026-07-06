"""
轻量化桌面AI效率助手 - 应用入口
职责：初始化 QApplication、加载配置、创建并显示主窗口
"""

import sys
import os

# 加载 .env 文件（开发时使用，打包后不需要）
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass


def main():
    """应用主入口函数"""
    from PySide6.QtWidgets import QApplication
    from PySide6.QtCore import Qt, QTimer
    from PySide6.QtGui import QIcon

    from app.app_context import resource_path
    from app.config import load_config
    from app.utils import ensure_dirs
    from app.state_manager import StateManager
    from app.logger import setup_logger
    from ui.floating_pet import FloatingPetWindow
    from ui.tray_menu import TrayMenu
    from ui.chat_window import ChatWindow
    from ui.reminder_popup import ReminderPopup
    from ui.settings_window import SettingsWindow
    from services.todo_service import TodoService
    from services.auto_sleep_service import AutoSleepService

    # 高 DPI 缩放支持（Windows 4K 屏幕友好）
    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )

    # 加载配置文件（提前加载，供 setApplicationName 使用）
    config = load_config(resource_path("config.json"))

    # 根据 config.log_level 初始化日志级别（如 DEBUG / INFO / WARNING）
    logger = setup_logger(level=config.log_level)

    app = QApplication(sys.argv)
    app.setApplicationName(config.app_name)
    app.setApplicationVersion("1.0.0")
    app.setOrganizationName("TutuAI")
    # 所有窗口关闭后不自动退出（宠物窗口是 Tool 类型，不算主窗口）
    app.setQuitOnLastWindowClosed(False)

    # 设置应用图标（如果存在）
    icon_path = resource_path(os.path.join("assets", "icons", "app_icon.ico"))
    if os.path.exists(icon_path):
        app.setWindowIcon(QIcon(icon_path))

    # 确保运行时目录存在
    ensure_dirs()

    # ── 创建核心对象 ──────────────────────────────────────────
    pet_window    = FloatingPetWindow()
    state_manager = StateManager(initial_state="idle")

    # ── 状态变化监听：同步宠物显示 ────────────────────────────
    def _on_state_changed(old: str, new: str):
        # 同步宠物图片（idle→idle, sleep→sleep, active→idle）
        pet_window.set_pet_state(state_manager.get_pet_state())
        logger.debug(f"状态变化：{old} → {new}")

    state_manager.add_listener(_on_state_changed)

    # ── TodoService 统一实例化（聊天指令 + 定时弹窗共用同一对象）──
    todo_service = TodoService()

    # ── 聊天窗口（单例）──────────────────────────────────────
    chat_window = ChatWindow(
        theme=config.ui.theme,
        config=config,
        todo_service=todo_service,
    )
    chat_window.set_state_manager(state_manager)
    chat_window.set_pet_state_callback(pet_window.set_pet_state)

    # ── 设置窗口（非模态单例）────────────────────────────────
    settings_window = SettingsWindow(theme=config.ui.theme)

    # 打开对话的统一入口：同时记录交互（从 sleep/idle 恢复 active）
    def open_chat():
        state_manager.touch_interaction()
        chat_window.open()

    # ── 宠物窗口 ──────────────────────────────────────────────
    # 双击 → 打开聊天窗口
    pet_window.set_open_chat_callback(open_chat)
    # 单击 → 记录交互，从 sleep/idle 恢复 active
    pet_window.set_click_callback(state_manager.touch_interaction)
    pet_window.show()

    # ── 系统托盘 ──────────────────────────────────────────────
    tray = TrayMenu(config=config)
    tray.set_state_manager(state_manager)
    tray.set_callbacks(
        on_open_chat=open_chat,
        on_show_pet=pet_window.show,
        on_hide_pet=pet_window.hide,
        on_open_settings=settings_window.open,   # 绑定设置窗口入口
    )
    tray.show()

    # ── sleep 状态下隐藏聊天窗口 ──────────────────────────────
    def _on_state_for_chat(old: str, new: str):
        """进入 sleep 时自动隐藏聊天窗口，避免窗口悬挂"""
        if new == "sleep" and chat_window.isVisible():
            chat_window.hide()
            logger.info("进入 sleep，聊天窗口已隐藏")

    state_manager.add_listener(_on_state_for_chat)

    # ── 自动休眠检测（每 10 秒一次）────────────────────────────
    auto_sleep = AutoSleepService(
        state_manager=state_manager,
        config=config.behavior,
    )
    # sleep 时通过托盘气泡通知用户（解耦：AutoSleepService 不直接操作 UI）
    auto_sleep.set_sleep_notify_callback(tray.show_sleep_notification)

    _auto_sleep_timer = QTimer()
    _auto_sleep_timer.setInterval(10 * 1000)        # 每 10 秒检测一次
    _auto_sleep_timer.timeout.connect(auto_sleep.check)
    _auto_sleep_timer.start()
    logger.debug("自动休眠检测定时器已启动（10s 间隔）")

    # ── 待办到点提醒检测（每 30 秒一次）────────────────────────
    # 复用同一个弹窗实例（避免重复创建）
    _reminder_popup = ReminderPopup(todo={}, theme=config.ui.theme)

    def _check_reminders():
        """每 30 秒触发一次，检查到期提醒并弹窗通知"""
        try:
            due_todos = todo_service.check_due_todos()
            if not due_todos:
                return
            if len(due_todos) == 1:
                # 单条直接展示
                _reminder_popup.update_todo(due_todos[0])
            else:
                # 多条合并为一条展示：标题汇总，时间取第一条
                merged_title = "、".join(t.get("title", "") for t in due_todos)
                merged_todo  = {
                    "id":          due_todos[0].get("id"),
                    "title":       f"共 {len(due_todos)} 条提醒：{merged_title}",
                    "remind_time": due_todos[0].get("remind_time", ""),
                }
                _reminder_popup.update_todo(merged_todo)
            _reminder_popup.show_popup()
        except Exception as e:
            # 弹窗检测出错不应影响主程序运行
            logger.error(f"提醒检测异常：{e}")

    _reminder_timer = QTimer()
    _reminder_timer.setInterval(30 * 1000)   # 每 30 秒检查一次
    _reminder_timer.timeout.connect(_check_reminders)
    _reminder_timer.start()

    # 启动后立即检查一次，避免程序启动时已有到期任务被忽略
    _check_reminders()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
