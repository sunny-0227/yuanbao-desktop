"""提醒弹窗不自动完成任务；允许完成、稍后提醒或关闭。"""

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QDialog, QHBoxLayout, QLabel, QPushButton, QVBoxLayout


class ReminderPopup(QDialog):
    action = Signal(str, int)

    def __init__(self, todo, parent=None):
        super().__init__(parent)
        self.todo = todo
        self.setWindowTitle("元宝 · 到点提醒")
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self.setMinimumWidth(360)
        layout = QVBoxLayout(self)
        title = QLabel(todo["title"])
        title.setObjectName("PageTitle")
        title.setWordWrap(True)
        layout.addWidget(title)
        layout.addWidget(QLabel(todo["remind_time"]))
        buttons = QHBoxLayout()
        for label, action in (
            ("完成", "complete"),
            ("10分钟后提醒", "snooze"),
            ("稍后处理", "dismiss"),
        ):
            button = QPushButton(label)
            button.clicked.connect(lambda checked=False, a=action: self._act(a))
            buttons.addWidget(button)
        layout.addLayout(buttons)

    def _act(self, action):
        self.action.emit(action, self.todo["id"])
        self.close()
