"""Windows 无头界面结构检查，不执行真实电脑控制、联网或录音。"""

import os
import sys
from pathlib import Path

os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def main():
    from PySide6.QtGui import QPixmap
    from PySide6.QtWidgets import QApplication

    from app.config import AppConfig
    from ui.floating_pet import FloatingPetWindow
    from ui.main_window import MainWindow
    from ui.reminder_popup import ReminderPopup
    from ui.style import apply_theme

    app = QApplication([])
    cfg = AppConfig()
    cfg.ui.pet_visible = False
    for theme in ("light", "dark"):
        cfg.ui.theme = theme
        apply_theme(app, cfg)
        window = MainWindow(cfg)
        window.chat.add_message("user", "测试消息")
        window.chat.add_message("assistant", "### 回答\n\n```python\nprint(1)\n```")
        window.chat.set_partial("继续输出")
        window.chat.set_partial("")
        window.settings.set_config(cfg)
        window.settings.read()
        for index in range(4):
            window.nav.setCurrentRow(index)
            window.render(QPixmap(window.size()))
        pet = FloatingPetWindow(cfg.ui)
        for state in ("idle", "listening", "thinking", "speaking", "working", "sleep"):
            pet.set_pet_state(state)
            pet.render(QPixmap(pet.size()))
        pet.show()
        pet.set_pet_state("idle")
        assert len(pet.animation_frames) > 1
        assert pet.animation_timer.isActive()
        for _ in range(len(pet.animation_frames) - 1):
            pet._advance_animation()
        assert pet.animation_direction == -1
        pet.render(QPixmap(pet.size()))
        for _ in range(len(pet.animation_frames) - 1):
            pet._advance_animation()
        assert pet.animation_index == 0 and pet.animation_direction == 1
        pet.set_pet_state("sleep")
        assert not pet.animation_timer.isActive()
        for state in ("listening", "thinking", "speaking", "working"):
            pet.set_pet_state(state)
            assert pet.animation_index == 0
            assert pet.animation_timer.isActive()
            pet._advance_animation()
            assert pet.animation_index == 1
            pet.render(QPixmap(pet.size()))
        pet.collapsed = True
        pet._sync_animation()
        assert not pet.animation_timer.isActive()
        pet._expand()
        assert pet.animation_timer.isActive()
        pet.set_pet_state("idle")
        pet.hide()
        assert not pet.animation_timer.isActive()
        reminder = ReminderPopup({"id": 1, "title": "测试提醒", "remind_time": "2026-10-14 18:30"})
        reminder.render(QPixmap(reminder.size()))
        window.deleteLater()
        pet.deleteLater()
        reminder.deleteLater()
        app.processEvents()
    print("Windows UI smoke checks passed")


if __name__ == "__main__":
    if sys.platform != "win32":
        raise SystemExit("此检查按项目约定仅在 Windows 执行")
    main()
