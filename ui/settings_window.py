"""分类设置面板：配置校验、设备选择、快捷入口与备用模型。"""

import copy
from pathlib import Path

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from app.config import validate_config


class SettingsWindow(QWidget):
    save_requested = Signal(object)
    test_requested = Signal(object)
    scan_requested = Signal()
    devices_requested = Signal()

    def __init__(self, config, parent=None):
        super().__init__(parent)
        self.config = copy.deepcopy(config)
        self.controls = {}
        root = QVBoxLayout(self)
        root.setContentsMargins(22, 20, 22, 20)
        title = QLabel("按你的习惯工作")
        title.setObjectName("PageTitle")
        root.addWidget(title)
        hint = QLabel("保存在用户数据目录。环境变量中的密钥和模型优先于这里的设置。")
        hint.setWordWrap(True)
        hint.setObjectName("Hint")
        root.addWidget(hint)
        self.tabs = QTabWidget()
        root.addWidget(self.tabs, 1)
        ai = self._page("AI 连接")
        self._combo(ai, "ai.provider", "连接方式", ["direct", "freellmapi", "none"])
        self._line(ai, "ai.base_url", "API 根地址", "https://…/v1")
        self._line(ai, "ai.api_key", "API 密钥", "可通过 AI_API_KEY 配置", secret=True)
        self._line(ai, "ai.model", "模型名称")
        self._check(ai, "ai.enable_ai_cache", "启用24小时请求缓存（包含会话上下文）")
        self._line(ai, "offline_ai_url", "离线模型接口", "例如 http://localhost:11434/v1")
        self._line(ai, "offline_ai_model", "离线模型名称", "需要已安装、已运行的本地模型")
        ai.addRow(QLabel("额度由服务商管理；遇到限流或连接失败按下方顺序切换。"))
        self.endpoints = self._table(["根地址", "模型", "密钥"], min_height=140)
        ai.addRow("备用接口", self.endpoints)
        ai.addRow(self._table_buttons(self.endpoints))
        test = QPushButton("测试当前 AI 连接")
        test.clicked.connect(self._test)
        ai.addRow(test)
        voice = self._page("语音")
        self._check(voice, "voice.voice_enabled", "启用语音输入")
        self._combo(voice, "voice.asr_provider", "识别方式", ["none", "online", "whisper", "auto"])
        self._line(voice, "voice.asr_url", "ASR API 根地址", "支持 /audio/transcriptions 的接口")
        self._line(voice, "voice.asr_key", "ASR 密钥", secret=True)
        self._line(voice, "voice.asr_model", "在线 ASR 模型")
        self._line(voice, "voice.offline_model", "Whisper 模型", "已下载的模型目录或缓存名称")
        self._combo(voice, "voice.input_device", "麦克风", [""])
        device_button = QPushButton("识别可用麦克风")
        device_button.clicked.connect(self.devices_requested.emit)
        voice.addRow(device_button)
        self._check(voice, "voice.tts_enabled", "播报回复与提醒")
        self._combo(voice, "voice.tts_provider", "播报方式", ["edge", "system"])
        self._line(voice, "voice.tts_voice", "Edge 音色")
        self._spin(voice, "voice.tts_max_chars", "最大播报字数", 20, 2000)
        self._check(voice, "voice.wake_enabled", "启用离线语音唤醒（活跃时监听）")
        self._line(voice, "voice.wake_word", "唤醒词")
        self._line(voice, "voice.wake_model_path", "Vosk 中文模型目录")
        voice.addRow(QLabel("Edge 需要联网；system 使用系统离线语音。休眠/省电时关闭麦克风。"))
        power = self._page("轻量运行")
        self._check(power, "behavior.auto_sleep_enabled", "启用自动省电与高负载休眠")
        self._spin(power, "behavior.idle_sleep_minutes", "空闲分钟（0关闭）", 0, 1440)
        self._spin(power, "behavior.cpu_sleep_threshold", "CPU 休眠阈值 %", 1, 100)
        self._line(power, "behavior.blacklist_processes", "休眠软件", "例如 game.exe, blender.exe")
        self._line(
            power,
            "behavior.whitelist_processes",
            "软件白名单",
            "名单冲突时白名单优先，CPU高负载规则仍有效",
        )
        power.addRow(QLabel("连续两次高负载才休眠；负载恢复后自动醒来，手动休眠需手动恢复。"))
        appearance = self._page("形象与界面")
        self._combo(appearance, "ui.theme", "主题", ["light", "dark"])
        self._spin(appearance, "ui.font_size", "字号", 10, 24)
        self._spin(appearance, "ui.window_width", "工作台宽度", 840, 2400)
        self._spin(appearance, "ui.window_height", "工作台高度", 560, 1800)
        self._check(appearance, "ui.always_on_top", "工作台置顶")
        self._check(appearance, "ui.pet_visible", "显示桌面形象")
        self._spin(appearance, "ui.pet_size", "形象大小", 64, 240)
        self._spin(appearance, "ui.pet_opacity", "形象透明度", 0.2, 1.0, floating=True)
        self._combo(appearance, "ui.pet_skin", "形象皮肤", ["default", "peach", "night"])
        self._check(appearance, "ui.edge_collapse", "靠边时收起为迷你图标")
        self._check(appearance, "ui.autostart", "Windows 开机启动（延迟显示形象）")
        tools = self._page("快捷入口")
        self._combo(tools, "search.engine", "搜索引擎", ["bing", "baidu", "google"])
        self._line(tools, "screenshot.save_dir", "截图保存目录", "为空时使用用户图片目录")
        self.apps = self._table(["软件名称", "程序路径"], min_height=150)
        self.folders = self._table(["文件夹名称", "路径"], min_height=150)
        tools.addRow("常用软件", self.apps)
        tools.addRow(self._table_buttons(self.apps, "app"))
        tools.addRow("常用文件夹", self.folders)
        tools.addRow(self._table_buttons(self.folders, "folder"))
        scan = QPushButton("重新扫描桌面 / 开始菜单入口")
        scan.clicked.connect(self.scan_requested.emit)
        tools.addRow(scan)
        self.scan_label = QLabel("扫描结果保存在本机，不上传应用路径。")
        self.scan_label.setWordWrap(True)
        tools.addRow(self.scan_label)
        footer = QHBoxLayout()
        self.status = QLabel("")
        self.status.setObjectName("Status")
        self.status.setWordWrap(True)
        footer.addWidget(self.status, 1)
        reset = QPushButton("撤销未保存修改")
        reset.clicked.connect(lambda: self.set_config(self.config))
        footer.addWidget(reset)
        save = QPushButton("保存并应用")
        save.setObjectName("Primary")
        save.clicked.connect(self._save)
        footer.addWidget(save)
        root.addLayout(footer)
        self.set_config(config)

    def _page(self, title):
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        content = QWidget()
        form = QFormLayout(content)
        form.setContentsMargins(20, 20, 20, 20)
        form.setSpacing(14)
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        scroll.setWidget(content)
        self.tabs.addTab(scroll, title)
        return form

    def _line(self, form, key, label, placeholder="", secret=False):
        widget = QLineEdit()
        widget.setPlaceholderText(placeholder)
        widget.setAccessibleName(label)
        if secret:
            widget.setEchoMode(QLineEdit.EchoMode.Password)
        self.controls[key] = widget
        form.addRow(label, widget)

    def _combo(self, form, key, label, options):
        widget = QComboBox()
        for value in options:
            widget.addItem("系统默认" if value == "" else value, value)
        self.controls[key] = widget
        form.addRow(label, widget)

    def _check(self, form, key, label):
        widget = QCheckBox(label)
        self.controls[key] = widget
        form.addRow(widget)

    def _spin(self, form, key, label, low, high, floating=False):
        widget = QDoubleSpinBox() if floating else QSpinBox()
        widget.setRange(low, high)
        if floating:
            widget.setSingleStep(0.05)
        self.controls[key] = widget
        form.addRow(label, widget)

    def _table(self, labels, min_height):
        table = QTableWidget(0, len(labels))
        table.setHorizontalHeaderLabels(labels)
        table.setMinimumHeight(min_height)
        table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        table.verticalHeader().hide()
        return table

    def _table_buttons(self, table, browse=None):
        widget = QWidget()
        row = QHBoxLayout(widget)
        row.setContentsMargins(0, 0, 0, 0)
        add = QPushButton("添加")

        def add_row():
            if browse == "app":
                path, _ = QFileDialog.getOpenFileName(
                    self, "选择软件", "", "程序 (*.exe);;所有文件 (*)"
                )
            elif browse == "folder":
                path = QFileDialog.getExistingDirectory(self, "选择文件夹")
            else:
                path = ""
            if browse and not path:
                return
            index = table.rowCount()
            table.insertRow(index)
            for col in range(table.columnCount()):
                value = Path(path).stem if col == 0 and path else path if col == 1 else ""
                table.setItem(index, col, QTableWidgetItem(value))

        add.clicked.connect(add_row)
        row.addWidget(add)
        remove = QPushButton("移除选中")
        remove.clicked.connect(
            lambda: table.removeRow(table.currentRow()) if table.currentRow() >= 0 else None
        )
        row.addWidget(remove)
        row.addStretch()
        return widget

    @staticmethod
    def _get(config, key):
        for part in key.split("."):
            config = getattr(config, part)
        return config

    @staticmethod
    def _set(config, key, value):
        parts = key.split(".")
        for part in parts[:-1]:
            config = getattr(config, part)
        setattr(config, parts[-1], value)

    def set_config(self, config):
        self.config = copy.deepcopy(config)
        for key, widget in self.controls.items():
            value = self._get(config, key)
            if isinstance(widget, QCheckBox):
                widget.setChecked(value)
            elif isinstance(widget, QComboBox):
                index = widget.findData(value)
                if index < 0:
                    widget.addItem(str(value), value)
                    index = widget.count() - 1
                widget.setCurrentIndex(index)
            elif isinstance(widget, (QSpinBox, QDoubleSpinBox)):
                widget.setValue(value)
            else:
                widget.setText(", ".join(value) if isinstance(value, list) else str(value))
        for table, rows, keys in (
            (self.apps, config.quick_apps, ("name", "command")),
            (self.folders, config.quick_folders, ("name", "path")),
            (self.endpoints, config.ai_endpoints, ("base_url", "model", "api_key")),
        ):
            table.setRowCount(len(rows))
            for r, entry in enumerate(rows):
                for col, key in enumerate(keys):
                    table.setItem(r, col, QTableWidgetItem(entry.get(key, "")))

    def read(self):
        config = copy.deepcopy(self.config)
        for key, widget in self.controls.items():
            if isinstance(widget, QCheckBox):
                value = widget.isChecked()
            elif isinstance(widget, QComboBox):
                value = widget.currentData()
            elif isinstance(widget, (QSpinBox, QDoubleSpinBox)):
                value = widget.value()
            else:
                value = widget.text().strip()
                if key.endswith("processes"):
                    value = [v.strip() for v in value.split(",") if v.strip()]
            self._set(config, key, value)
        for table, name, keys in (
            (self.apps, "quick_apps", ("name", "command")),
            (self.folders, "quick_folders", ("name", "path")),
            (self.endpoints, "ai_endpoints", ("base_url", "model", "api_key")),
        ):
            rows = []
            for r in range(table.rowCount()):
                entry = {
                    key: table.item(r, col).text().strip() if table.item(r, col) else ""
                    for col, key in enumerate(keys)
                }
                if any(entry.values()):
                    if not entry[keys[0]]:
                        raise ValueError("快捷入口或备用接口有未填写名称/地址的行")
                    rows.append(entry)
            setattr(config, name, rows)
        validate_config(config)
        return config

    def _save(self):
        try:
            self.save_requested.emit(self.read())
        except Exception as exc:
            QMessageBox.warning(self, "请检查设置", str(exc))

    def _test(self):
        try:
            self.test_requested.emit(self.read())
            self.status.setText("正在测试连接…")
        except Exception as exc:
            QMessageBox.warning(self, "请检查设置", str(exc))

    def set_devices(self, devices):
        widget = self.controls["voice.input_device"]
        selected = widget.currentData()
        widget.clear()
        widget.addItem("系统默认", "")
        for ident, name in devices:
            widget.addItem(name, ident)
        widget.setCurrentIndex(max(0, widget.findData(selected)))
