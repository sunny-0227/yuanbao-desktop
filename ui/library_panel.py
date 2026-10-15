"""提醒与笔记管理面板，只发送操作意图，由控制器提交事务。"""

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QHBoxLayout,
    QHeaderView,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)


class LibraryPanel(QWidget):
    action = Signal(str, object)
    query_changed = Signal(str)

    def __init__(self, kind, parent=None):
        super().__init__(parent)
        self.kind = kind
        layout = QVBoxLayout(self)
        layout.setContentsMargins(22, 20, 22, 20)
        title = QLabel("待办与提醒" if kind == "todos" else "随手笔记")
        title.setObjectName("PageTitle")
        layout.addWidget(title)
        hint = QLabel(
            "提醒弹出后仍可标记完成；循环提醒自动安排下一次。"
            if kind == "todos"
            else "零散想法保存在这台电脑，随时查找和修改。"
        )
        hint.setObjectName("Hint")
        hint.setWordWrap(True)
        layout.addWidget(hint)
        self.search = QLineEdit()
        self.search.setPlaceholderText("搜索内容")
        self.search.textChanged.connect(self.query_changed.emit)
        layout.addWidget(self.search)
        self.table = QTableWidget(0, 4 if kind == "todos" else 3)
        self.table.setHorizontalHeaderLabels(
            ["编号", "内容", "提醒时间 / 循环", "状态"]
            if kind == "todos"
            else ["编号", "内容", "创建时间"]
        )
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.table.verticalHeader().hide()
        layout.addWidget(self.table, 1)
        actions = QHBoxLayout()
        add = QPushButton("新增提醒" if kind == "todos" else "新增笔记")
        add.setObjectName("Primary")
        add.clicked.connect(self._add)
        actions.addWidget(add)
        for label, name in (
            (("完成", "complete"), ("稍后10分钟", "snooze"))
            if kind == "todos"
            else (("编辑", "edit"),)
        ):
            button = QPushButton(label)
            button.clicked.connect(lambda checked=False, a=name: self._selected(a))
            actions.addWidget(button)
        delete = QPushButton("删除")
        delete.clicked.connect(lambda: self._selected("delete"))
        actions.addWidget(delete)
        actions.addStretch()
        layout.addLayout(actions)

    def set_rows(self, rows):
        query = self.search.text().casefold()
        rows = [r for r in rows if query in str(r.get("title", r.get("content", ""))).casefold()]
        selected = self.ident()
        self.table.setRowCount(len(rows))
        for index, row in enumerate(rows):
            if self.kind == "todos":
                recurrence = {"daily": "每天", "weekly": "每周", "": "单次"}.get(
                    row["recurrence"], "间隔循环"
                )
                status = {"pending": "待提醒", "notified": "已提醒", "completed": "已完成"}[
                    row["status"]
                ]
                values = [row["id"], row["title"], row["remind_time"] + " / " + recurrence, status]
            else:
                values = [row["id"], row["content"], row["created_at"]]
            for col, value in enumerate(values):
                self.table.setItem(index, col, QTableWidgetItem(str(value)))
            if row["id"] == selected:
                self.table.selectRow(index)
        self.table.resizeRowsToContents()

    def ident(self):
        row = self.table.currentRow()
        item = self.table.item(row, 0) if row >= 0 else None
        return int(item.text()) if item else None

    def _add(self):
        prompt = (
            "例如：每天18:30提醒我休息、十分钟后提醒我喝水" if self.kind == "todos" else "笔记内容"
        )
        text, ok = QInputDialog.getMultiLineText(self, "新增", prompt)
        if ok and text.strip():
            self.action.emit("add", text)

    def _selected(self, action):
        ident = self.ident()
        if ident is None:
            return
        if (
            action == "delete"
            and QMessageBox.question(self, "删除记录", "确定删除选中的记录？")
            != QMessageBox.StandardButton.Yes
        ):
            return
        value = {"id": ident}
        if action == "edit":
            row = self.table.currentRow()
            text, ok = QInputDialog.getMultiLineText(
                self, "编辑笔记", "内容", self.table.item(row, 1).text()
            )
            if not ok or not text.strip():
                return
            value["content"] = text
        self.action.emit(action, value)
