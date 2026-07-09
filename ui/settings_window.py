"""
设置窗口模块
提供图形化界面让用户查看和修改 config.json 中的常用配置。

设计原则：
- 非模态窗口，不阻塞主程序运行
- 直接读写 config.json（原始 JSON），保留文件中已有字段和注释结构
- 不显示 AI API Key，只提示用户去 .env 中配置
- 读取/写入失败时显示友好错误提示，不崩溃
- 与 app/config.py 的 load_config() 保持字段名一致
"""

import json
import os
import threading

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QFormLayout,
    QLabel, QLineEdit, QTextEdit, QComboBox, QCheckBox,
    QPushButton, QScrollArea, QFrame, QMessageBox,
    QSpinBox, QFileDialog, QTableWidget, QTableWidgetItem,
    QHeaderView, QTabWidget,
)
from PySide6.QtCore import Qt, Signal, Slot
from PySide6.QtGui import QFont

from app.app_context import resource_path
from app.logger import setup_logger

logger = setup_logger()

# config.json 路径（与 main.py 保持一致）
_CONFIG_PATH = resource_path("config.json")

# 支持的搜索引擎列表（与 config.json 中 search.engines 对应）
_SEARCH_ENGINES = ["bing", "baidu", "google"]


def _load_raw_config() -> dict:
    """
    直接加载 config.json 为原始 dict，保留所有已有字段。
    文件不存在或解析失败时返回空 dict（调用方判断并提示）。
    """
    if not os.path.exists(_CONFIG_PATH):
        return {}
    try:
        with open(_CONFIG_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        logger.error(f"SettingsWindow 加载 config.json 失败：{e}")
        return {}


def _save_raw_config(data: dict) -> None:
    """
    将 dict 写回 config.json（保留缩进）。
    写入失败时抛出异常，由调用方捕获后弹窗提示。
    """
    os.makedirs(os.path.dirname(_CONFIG_PATH) or ".", exist_ok=True)
    with open(_CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


# ── 辅助：多行文本 ↔ list 互转 ─────────────────────────────────

def _list_to_lines(lst: list) -> str:
    """将列表转为每行一项的纯文本（用于黑名单进程编辑）"""
    return "\n".join(str(x) for x in lst if x)


def _lines_to_list(text: str) -> list:
    """将多行文本转为列表，自动去除空行和首尾空格"""
    return [line.strip() for line in text.splitlines() if line.strip()]


def _apps_to_lines(apps: list) -> str:
    """
    将 quick_apps 列表转为多行文本。
    每行格式：名称=命令
    """
    lines = []
    for item in apps:
        if isinstance(item, dict):
            name = item.get("name", "")
            cmd  = item.get("command", "")
            lines.append(f"{name}={cmd}")
    return "\n".join(lines)


def _lines_to_apps(text: str) -> list:
    """
    将多行"名称=命令"文本转为 quick_apps 列表 dict。
    跳过无法解析的行（无 = 号）。
    """
    result = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        if "=" in line:
            name, _, cmd = line.partition("=")
            result.append({"name": name.strip(), "command": cmd.strip()})
        else:
            logger.debug(f"quick_apps 行格式无效（跳过）：{line!r}")
    return result


def _folders_to_lines(folders: list) -> str:
    """
    将 quick_folders 列表转为多行文本。
    每行格式：名称=路径
    """
    lines = []
    for item in folders:
        if isinstance(item, dict):
            name = item.get("name", "")
            path = item.get("path", "")
            lines.append(f"{name}={path}")
    return "\n".join(lines)


def _lines_to_folders(text: str) -> list:
    """
    将多行"名称=路径"文本转为 quick_folders 列表 dict。
    """
    result = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        if "=" in line:
            name, _, path = line.partition("=")
            result.append({"name": name.strip(), "path": path.strip()})
        else:
            logger.debug(f"quick_folders 行格式无效（跳过）：{line!r}")
    return result


# ── 辅助：简单输入对话框 ──────────────────────────────────────────

def _simple_input_dialog(parent, title: str, label: str, default: str = "") -> tuple[str, bool]:
    """弹出简单的单行输入对话框，返回 (text, ok)"""
    from PySide6.QtWidgets import QInputDialog
    text, ok = QInputDialog.getText(parent, title, label, text=default)
    return text, ok


# ── 主窗口 ──────────────────────────────────────────────────────

class SettingsWindow(QWidget):
    """
    设置窗口（非模态）。

    使用方式（在 main.py 中）：
        settings_win = SettingsWindow(theme=config.ui.theme)
        tray.set_callbacks(on_open_settings=settings_win.open, ...)

    调用 open() 而不是 show()，确保每次打开都刷新数据。
    """

    _test_result           = Signal(bool, str)   # 测试 AI 连接结果
    _discovery_refresh_done = Signal(bool, str)  # 重新识别完成

    def __init__(self, theme: str = "dark", parent=None):
        super().__init__(parent)
        self._theme = theme
        self._test_result.connect(self._on_test_ai_done)
        self._discovery_refresh_done.connect(self._on_refresh_index_done)
        self._init_window()
        self._build_ui()
        self._apply_style()

    # ── 公开接口 ─────────────────────────────────────────────

    def open(self):
        """显示并激活窗口，同时重新加载最新配置"""
        self._load_into_ui()
        if self.isHidden():
            self.show()
        self.raise_()
        self.activateWindow()

    # ── 窗口初始化 ────────────────────────────────────────────

    def _init_window(self):
        self.setWindowTitle("设置 - 轻量化桌面AI效率助手")
        self.resize(560, 700)
        self.setMinimumSize(480, 500)

    def _build_ui(self):
        """构建完整 UI 布局"""
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # 标题栏
        root.addWidget(self._build_title_bar())

        # 可滚动内容区
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setFrameShape(QFrame.Shape.NoFrame)

        content = QWidget()
        content.setObjectName("SettingsContent")
        self._content_layout = QVBoxLayout(content)
        self._content_layout.setContentsMargins(24, 16, 24, 16)
        self._content_layout.setSpacing(20)

        # ── 各分区 ────────────────────────────────────────────
        self._build_search_section()
        self._build_behavior_section()
        self._build_screenshot_section()
        self._build_ai_section()
        self._build_quick_apps_section()
        self._build_quick_folders_section()
        self._build_blacklist_section()
        self._build_voice_section()
        self._build_discovery_section()

        self._content_layout.addStretch()
        scroll.setWidget(content)
        root.addWidget(scroll, stretch=1)

        # 底部按钮栏
        root.addWidget(self._build_bottom_bar())

    def _build_title_bar(self) -> QWidget:
        bar = QWidget()
        bar.setObjectName("TitleBar")
        bar.setFixedHeight(50)
        layout = QHBoxLayout(bar)
        layout.setContentsMargins(20, 0, 16, 0)

        title = QLabel("⚙️  设置")
        title.setObjectName("TitleLabel")
        f = QFont()
        f.setPointSize(14)
        f.setBold(True)
        title.setFont(f)
        layout.addWidget(title)
        layout.addStretch()
        return bar

    def _section_label(self, text: str) -> QLabel:
        """返回分区标题 QLabel"""
        lbl = QLabel(text)
        lbl.setObjectName("SectionLabel")
        f = QFont()
        f.setPointSize(11)
        f.setBold(True)
        lbl.setFont(f)
        return lbl

    def _divider(self) -> QFrame:
        """返回水平分隔线"""
        line = QFrame()
        line.setFrameShape(QFrame.Shape.HLine)
        line.setObjectName("Divider")
        return line

    # ── 各配置分区 UI 构建 ─────────────────────────────────────

    def _build_search_section(self):
        self._content_layout.addWidget(self._section_label("🔍 搜索引擎"))
        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        form.setHorizontalSpacing(16)
        form.setVerticalSpacing(10)

        self._search_engine_box = QComboBox()
        self._search_engine_box.addItems(_SEARCH_ENGINES)
        self._search_engine_box.setToolTip("发起网页搜索时使用的默认搜索引擎")
        form.addRow("默认搜索引擎：", self._search_engine_box)

        self._content_layout.addLayout(form)
        self._content_layout.addWidget(self._divider())

    def _build_behavior_section(self):
        self._content_layout.addWidget(self._section_label("😴 休眠行为"))
        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        form.setHorizontalSpacing(16)
        form.setVerticalSpacing(10)

        # 空闲分钟数
        self._idle_spin = QSpinBox()
        self._idle_spin.setRange(0, 1440)
        self._idle_spin.setSuffix(" 分钟")
        self._idle_spin.setToolTip("超过该时间无操作后自动进入 idle；0 表示禁用")
        form.addRow("空闲休眠时间：", self._idle_spin)

        # CPU 阈值
        self._cpu_spin = QSpinBox()
        self._cpu_spin.setRange(0, 100)
        self._cpu_spin.setSuffix(" %")
        self._cpu_spin.setToolTip("CPU 占用超过该值时自动进入 sleep 模式")
        form.addRow("CPU 休眠阈值：", self._cpu_spin)

        self._content_layout.addLayout(form)
        self._content_layout.addWidget(self._divider())

    def _build_screenshot_section(self):
        self._content_layout.addWidget(self._section_label("📷 截图"))
        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        form.setHorizontalSpacing(16)
        form.setVerticalSpacing(10)

        self._screenshot_dir_edit = QLineEdit()
        self._screenshot_dir_edit.setPlaceholderText(
            "留空则自动使用 ~/Pictures/TutuAssistantScreenshots"
        )
        self._screenshot_dir_edit.setToolTip(
            "截图保存目录，支持 Windows 环境变量如 %USERPROFILE%"
        )
        form.addRow("截图保存目录：", self._screenshot_dir_edit)

        self._content_layout.addLayout(form)
        self._content_layout.addWidget(self._divider())

    def _build_ai_section(self):
        self._content_layout.addWidget(self._section_label("🤖 AI 配置"))
        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        form.setHorizontalSpacing(16)
        form.setVerticalSpacing(10)

        # AI 接入方式
        self._ai_provider_box = QComboBox()
        self._ai_provider_box.addItems(["none", "freellmapi", "direct"])
        self._ai_provider_box.setToolTip(
            "none = 禁用AI\n"
            "freellmapi = 本地代理（推荐，需先启动 FreeLLMAPI）\n"
            "direct = 直连 OpenAI / DeepSeek 等"
        )
        form.addRow("接入方式：", self._ai_provider_box)

        # API Base URL
        self._ai_base_url_edit = QLineEdit()
        self._ai_base_url_edit.setPlaceholderText(
            "FreeLLMAPI: http://localhost:3001/v1  |  OpenAI: https://api.openai.com/v1"
        )
        self._ai_base_url_edit.setToolTip("也可在 .env 中设置 AI_API_BASE_URL（优先级更高）")
        form.addRow("API 地址：", self._ai_base_url_edit)

        # API Key（可切换显示/隐藏）
        key_row = QHBoxLayout()
        self._ai_key_edit = QLineEdit()
        self._ai_key_edit.setPlaceholderText("建议留空，在 .env 中配置 AI_API_KEY")
        self._ai_key_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self._ai_key_edit.setToolTip("填写后会保存到 config.json（明文）；建议改用 .env 文件")
        key_row.addWidget(self._ai_key_edit)
        self._ai_key_toggle = QPushButton("显示")
        self._ai_key_toggle.setFixedWidth(48)
        self._ai_key_toggle.setCheckable(True)
        self._ai_key_toggle.toggled.connect(self._toggle_key_visibility)
        key_row.addWidget(self._ai_key_toggle)
        key_widget = QWidget()
        key_widget.setLayout(key_row)
        form.addRow("API Key：", key_widget)

        # 模型名称
        self._ai_model_edit = QLineEdit()
        self._ai_model_edit.setPlaceholderText(
            "FreeLLMAPI: auto  |  OpenAI: gpt-4o-mini  |  DeepSeek: deepseek-chat"
        )
        self._ai_model_edit.setToolTip("也可在 .env 中设置 AI_MODEL_NAME（优先级更高）")
        form.addRow("模型名称：", self._ai_model_edit)

        # AI 缓存开关
        self._ai_cache_check = QCheckBox("启用 AI 回复本地缓存（相同问题不重复请求）")
        form.addRow("", self._ai_cache_check)

        self._content_layout.addLayout(form)

        # .env 说明
        tip = QLabel(
            "💡 敏感信息（API Key）推荐在 <b>.env</b> 文件中配置，优先级高于此处：\n"
            "   AI_API_KEY=freellmapi-你的key\n"
            "   AI_API_BASE_URL=http://localhost:3001/v1\n"
            "   AI_MODEL_NAME=auto"
        )
        tip.setObjectName("TipLabel")
        tip.setTextFormat(Qt.TextFormat.RichText)
        tip.setWordWrap(True)
        tip.setContentsMargins(0, 4, 0, 4)
        self._content_layout.addWidget(tip)

        # 测试 AI 连接按钮
        self._test_ai_btn = QPushButton("🔗  测试 AI 连接")
        self._test_ai_btn.setObjectName("TestAIButton")
        self._test_ai_btn.setFixedHeight(32)
        self._test_ai_btn.setToolTip("使用当前配置发送一条测试消息，验证 AI 是否可用")
        self._test_ai_btn.clicked.connect(self._on_test_ai)
        self._content_layout.addWidget(self._test_ai_btn)

        self._content_layout.addWidget(self._divider())

    def _build_quick_apps_section(self):
        self._content_layout.addWidget(self._section_label("🚀 快捷应用"))

        hint = QLabel("每行格式：名称=命令或路径，例如：\n微信=%USERPROFILE%\\AppData\\...\\WeChat.exe")
        hint.setObjectName("HintLabel")
        hint.setWordWrap(True)
        self._content_layout.addWidget(hint)

        self._quick_apps_edit = QTextEdit()
        self._quick_apps_edit.setMinimumHeight(120)
        self._quick_apps_edit.setMaximumHeight(200)
        self._quick_apps_edit.setPlaceholderText("名称=命令")
        self._content_layout.addWidget(self._quick_apps_edit)
        self._content_layout.addWidget(self._divider())

    def _build_quick_folders_section(self):
        self._content_layout.addWidget(self._section_label("📂 快捷文件夹"))

        hint = QLabel("每行格式：名称=路径，例如：\n项目=%USERPROFILE%\\Projects")
        hint.setObjectName("HintLabel")
        hint.setWordWrap(True)
        self._content_layout.addWidget(hint)

        self._quick_folders_edit = QTextEdit()
        self._quick_folders_edit.setMinimumHeight(120)
        self._quick_folders_edit.setMaximumHeight(200)
        self._quick_folders_edit.setPlaceholderText("名称=路径")
        self._content_layout.addWidget(self._quick_folders_edit)
        self._content_layout.addWidget(self._divider())

    def _build_blacklist_section(self):
        self._content_layout.addWidget(self._section_label("🚫 黑名单进程"))

        hint = QLabel("每行一个进程名（含扩展名），检测到时助手自动进入休眠：\n"
                       "例如：steam.exe")
        hint.setObjectName("HintLabel")
        hint.setWordWrap(True)
        self._content_layout.addWidget(hint)

        self._blacklist_edit = QTextEdit()
        self._blacklist_edit.setMinimumHeight(100)
        self._blacklist_edit.setMaximumHeight(160)
        self._blacklist_edit.setPlaceholderText("steam.exe\nblender.exe")
        self._content_layout.addWidget(self._blacklist_edit)

    def _build_voice_section(self):
        self._content_layout.addWidget(self._divider())
        self._content_layout.addWidget(self._section_label("🎤 语音设置"))

        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        form.setHorizontalSpacing(16)
        form.setVerticalSpacing(10)

        # 是否启用语音功能（录音入口）
        self._voice_enabled_check = QCheckBox("启用语音输入（聊天窗口显示语音按钮）")
        form.addRow("", self._voice_enabled_check)

        # TTS 启用
        self._tts_enabled_check = QCheckBox("启用语音播报（AI 回复后朗读）")
        form.addRow("", self._tts_enabled_check)

        # TTS provider
        self._tts_provider_box = QComboBox()
        self._tts_provider_box.addItems(["edge", "system"])
        self._tts_provider_box.setToolTip(
            "edge = edge-tts（在线，中文效果好）\n"
            "system = pyttsx3（离线，系统 TTS）"
        )
        form.addRow("播报引擎：", self._tts_provider_box)

        # TTS voice
        self._tts_voice_edit = QLineEdit()
        self._tts_voice_edit.setPlaceholderText("zh-CN-XiaoxiaoNeural")
        self._tts_voice_edit.setToolTip("edge-tts 音色名称，仅当引擎为 edge 时生效")
        form.addRow("播报音色：", self._tts_voice_edit)

        # TTS max chars
        self._tts_max_chars_spin = QSpinBox()
        self._tts_max_chars_spin.setRange(20, 1000)
        self._tts_max_chars_spin.setSuffix(" 字")
        self._tts_max_chars_spin.setToolTip("超过此字数只播报提示语，不播报全文")
        form.addRow("最大播报字数：", self._tts_max_chars_spin)

        # ASR provider
        self._asr_provider_box = QComboBox()
        self._asr_provider_box.addItems(["none", "whisper", "online"])
        self._asr_provider_box.setToolTip(
            "none = 不进行语音识别，仅保存录音\n"
            "whisper = 本地 Whisper 模型（需先安装 faster-whisper）\n"
            "online = 在线 ASR API（需自行实现接口）"
        )
        form.addRow("语音识别：", self._asr_provider_box)

        self._content_layout.addLayout(form)

        # 提示文案
        tip1 = QLabel(
            "💡 当前版本不支持唤醒词，语音输入需点击「语音」按钮手动启动。"
        )
        tip1.setObjectName("HintLabel")
        tip1.setWordWrap(True)
        self._content_layout.addWidget(tip1)

        tip2 = QLabel(
            "💡 ASR 第一阶段为预留能力，选择 none 时只保存录音文件，不进行语音转文字。\n"
            "   选择 whisper 或 online 需在代码中完成对应实现。"
        )
        tip2.setObjectName("HintLabel")
        tip2.setWordWrap(True)
        self._content_layout.addWidget(tip2)

    def _build_discovery_section(self):
        self._content_layout.addWidget(self._divider())
        self._content_layout.addWidget(self._section_label("🔍 常用入口识别"))

        hint = QLabel(
            "图图助手会自动扫描你的桌面快捷方式、开始菜单等位置，\n"
            "识别常用软件、文件夹和网页入口，保存在本机 data/app_index.json。"
        )
        hint.setObjectName("HintLabel")
        hint.setWordWrap(True)
        self._content_layout.addWidget(hint)

        # 操作按钮行
        btn_row = QHBoxLayout()
        self._refresh_index_btn = QPushButton("🔄 重新识别常用入口")
        self._refresh_index_btn.setObjectName("DiscoveryButton")
        self._refresh_index_btn.setFixedHeight(32)
        self._refresh_index_btn.setToolTip("重新扫描桌面 / 开始菜单快捷方式")
        self._refresh_index_btn.clicked.connect(self._on_refresh_index)
        btn_row.addWidget(self._refresh_index_btn)

        self._add_app_btn = QPushButton("➕ 手动添加软件")
        self._add_app_btn.setObjectName("DiscoveryButton")
        self._add_app_btn.setFixedHeight(32)
        self._add_app_btn.setToolTip("选择 .exe 文件并填写名称，永久保存到 user_custom_entries.json")
        self._add_app_btn.clicked.connect(self._on_add_custom_app)
        btn_row.addWidget(self._add_app_btn)

        self._add_folder_btn = QPushButton("📂 手动添加文件夹")
        self._add_folder_btn.setObjectName("DiscoveryButton")
        self._add_folder_btn.setFixedHeight(32)
        self._add_folder_btn.setToolTip("选择文件夹并填写名称，永久保存到 user_custom_entries.json")
        self._add_folder_btn.clicked.connect(self._on_add_custom_folder)
        btn_row.addWidget(self._add_folder_btn)
        btn_row.addStretch()
        self._content_layout.addLayout(btn_row)

        # 识别结果 Tab 展示
        self._discovery_tabs = QTabWidget()
        self._discovery_tabs.setObjectName("DiscoveryTabs")
        self._discovery_tabs.setFixedHeight(200)

        for tab_name in ("软件", "文件夹", "网页", "系统工具"):
            table = QTableWidget(0, 3)
            table.setObjectName(f"DiscoveryTable_{tab_name}")
            table.setHorizontalHeaderLabels(["名称", "路径 / URL", "来源"])
            table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
            table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
            table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
            table.verticalHeader().setVisible(False)
            table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
            table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
            self._discovery_tabs.addTab(table, tab_name)

        self._content_layout.addWidget(self._discovery_tabs)

        # 状态标签
        self._discovery_status = QLabel("点击「重新识别」或重启程序以加载识别结果。")
        self._discovery_status.setObjectName("HintLabel")
        self._content_layout.addWidget(self._discovery_status)

        # 初始加载已有索引
        self._load_discovery_into_ui()

    def _load_discovery_into_ui(self):
        """从 app_index.json 加载数据填充表格"""
        try:
            from services.app_discovery_service import AppDiscoveryService
            svc   = AppDiscoveryService()
            index = svc.load_app_index()

            category_map = {
                0: ("apps",         "path"),
                1: ("folders",      "path"),
                2: ("websites",     "url"),
                3: ("system_tools", "command"),
            }
            for tab_idx, (category, path_key) in category_map.items():
                table: QTableWidget = self._discovery_tabs.widget(tab_idx)
                table.setRowCount(0)
                for name, entry in index.get(category, {}).items():
                    row = table.rowCount()
                    table.insertRow(row)
                    table.setItem(row, 0, QTableWidgetItem(entry.get("display_name", name)))
                    table.setItem(row, 1, QTableWidgetItem(entry.get(path_key, "")))
                    table.setItem(row, 2, QTableWidgetItem(entry.get("source", "")))

            n_apps    = len(index.get("apps", {}))
            n_folders = len(index.get("folders", {}))
            n_web     = len(index.get("websites", {}))
            self._discovery_status.setText(
                f"共识别到 {n_apps} 个软件、{n_folders} 个文件夹、{n_web} 个网页入口。"
            )
        except Exception as e:
            self._discovery_status.setText(f"加载识别结果失败：{e}")
            logger.warning(f"SettingsWindow 加载 app_index 失败：{e}")

    def _on_refresh_index(self):
        """后台重新扫描并刷新列表"""
        self._refresh_index_btn.setEnabled(False)
        self._refresh_index_btn.setText("识别中…")

        def _worker():
            try:
                from services.app_discovery_service import AppDiscoveryService
                svc   = AppDiscoveryService()
                index = svc.refresh_index()
                self._discovery_refresh_done.emit(True, "")
            except Exception as e:
                self._discovery_refresh_done.emit(False, str(e))

        threading.Thread(target=_worker, daemon=True).start()

    @Slot(bool, str)
    def _on_refresh_index_done(self, ok: bool, err: str):
        self._refresh_index_btn.setEnabled(True)
        self._refresh_index_btn.setText("🔄 重新识别常用入口")
        if ok:
            self._load_discovery_into_ui()
        else:
            self._discovery_status.setText(f"识别失败：{err}")

    def _on_add_custom_app(self):
        """手动选择 exe 并添加到 user_custom_entries.json"""
        path, _ = QFileDialog.getOpenFileName(
            self, "选择软件程序", "",
            "程序文件 (*.exe);;所有文件 (*)"
        )
        if not path:
            return
        default_name = os.path.splitext(os.path.basename(path))[0]
        name, ok = _simple_input_dialog(self, "添加软件", "显示名称：", default_name)
        if not ok or not name.strip():
            return
        try:
            from services.app_command_service import _save_custom_entries, _load_custom_entries
            data = _load_custom_entries()
            data["apps"][name.strip()] = {
                "display_name": name.strip(),
                "path":         path,
                "arguments":    "",
                "working_dir":  "",
                "source":       "user_custom",
                "aliases":      [name.strip()],
                "confidence":   1.0,
            }
            _save_custom_entries(data)
            QMessageBox.information(self, "添加成功", f"已添加「{name.strip()}」")
            self._load_discovery_into_ui()
        except Exception as e:
            QMessageBox.warning(self, "添加失败", str(e))

    def _on_add_custom_folder(self):
        """手动选择文件夹并添加到 user_custom_entries.json"""
        path = QFileDialog.getExistingDirectory(self, "选择文件夹", "")
        if not path:
            return
        default_name = os.path.basename(path) or path
        name, ok = _simple_input_dialog(self, "添加文件夹", "显示名称：", default_name)
        if not ok or not name.strip():
            return
        try:
            from services.app_command_service import _save_custom_entries, _load_custom_entries
            data = _load_custom_entries()
            data["folders"][name.strip()] = {
                "display_name": name.strip(),
                "path":         path,
                "source":       "user_custom",
                "aliases":      [name.strip()],
                "confidence":   1.0,
            }
            _save_custom_entries(data)
            QMessageBox.information(self, "添加成功", f"已添加「{name.strip()}」")
            self._load_discovery_into_ui()
        except Exception as e:
            QMessageBox.warning(self, "添加失败", str(e))

    def _build_bottom_bar(self) -> QWidget:
        bar = QWidget()
        bar.setObjectName("BottomBar")
        bar.setFixedHeight(60)
        layout = QHBoxLayout(bar)
        layout.setContentsMargins(20, 0, 20, 0)
        layout.addStretch()

        # 重置按钮（重新从文件加载，丢弃未保存的改动）
        reset_btn = QPushButton("重新加载")
        reset_btn.setObjectName("ResetButton")
        reset_btn.setFixedSize(88, 34)
        reset_btn.setToolTip("丢弃当前改动，重新从 config.json 读取")
        reset_btn.clicked.connect(self._load_into_ui)
        layout.addWidget(reset_btn)

        layout.addSpacing(8)

        save_btn = QPushButton("保存设置")
        save_btn.setObjectName("SaveButton")
        save_btn.setFixedSize(88, 34)
        save_btn.clicked.connect(self._on_save)
        layout.addWidget(save_btn)

        return bar

    # ── 样式 ──────────────────────────────────────────────────

    def _apply_style(self):
        if self._theme == "light":
            self.setStyleSheet(_LIGHT_SETTINGS_QSS)
        else:
            self.setStyleSheet(_DARK_SETTINGS_QSS)

    # ── 数据加载 / 保存 ───────────────────────────────────────

    def _load_into_ui(self):
        """从 config.json 读取数据并填充到各控件"""
        raw = _load_raw_config()
        if not raw:
            QMessageBox.warning(
                self, "读取失败",
                f"无法读取配置文件：\n{_CONFIG_PATH}\n\n将显示默认值，保存后会创建新文件。"
            )

        # 搜索引擎
        engine = raw.get("search", {}).get("engine", "bing")
        idx = self._search_engine_box.findText(engine)
        self._search_engine_box.setCurrentIndex(max(0, idx))

        # 休眠行为
        behavior = raw.get("behavior", {})
        self._idle_spin.setValue(int(behavior.get("idle_sleep_minutes", 10)))
        self._cpu_spin.setValue(int(behavior.get("cpu_sleep_threshold", 80)))

        # 截图目录
        self._screenshot_dir_edit.setText(
            raw.get("screenshot", {}).get("save_dir", "")
        )

        # AI 配置
        ai = raw.get("ai", {})
        provider = ai.get("provider", "freellmapi")
        idx = self._ai_provider_box.findText(provider)
        self._ai_provider_box.setCurrentIndex(max(0, idx))
        self._ai_base_url_edit.setText(ai.get("base_url", ""))
        self._ai_key_edit.setText(ai.get("api_key", ""))
        self._ai_model_edit.setText(ai.get("model", ""))
        enable_cache = ai.get("enable_ai_cache", True)
        self._ai_cache_check.setChecked(bool(enable_cache))

        # 快捷应用
        self._quick_apps_edit.setPlainText(
            _apps_to_lines(raw.get("quick_apps", []))
        )

        # 快捷文件夹
        self._quick_folders_edit.setPlainText(
            _folders_to_lines(raw.get("quick_folders", []))
        )

        # 黑名单进程
        self._blacklist_edit.setPlainText(
            _list_to_lines(behavior.get("blacklist_processes", []))
        )

        # 语音配置（顶层字段）
        self._voice_enabled_check.setChecked(bool(raw.get("voice_enabled", True)))
        self._tts_enabled_check.setChecked(bool(raw.get("tts_enabled", True)))
        tts_provider = raw.get("tts_provider", "edge")
        tts_idx = self._tts_provider_box.findText(tts_provider)
        self._tts_provider_box.setCurrentIndex(max(0, tts_idx))
        self._tts_voice_edit.setText(raw.get("tts_voice", "zh-CN-XiaoxiaoNeural"))
        self._tts_max_chars_spin.setValue(int(raw.get("tts_max_chars", 200)))
        asr_provider = raw.get("asr_provider", "none")
        asr_idx = self._asr_provider_box.findText(asr_provider)
        self._asr_provider_box.setCurrentIndex(max(0, asr_idx))

        logger.debug("SettingsWindow：配置已加载到 UI")

    def _toggle_key_visibility(self, checked: bool):
        """切换 API Key 显示/隐藏"""
        if checked:
            self._ai_key_edit.setEchoMode(QLineEdit.EchoMode.Normal)
            self._ai_key_toggle.setText("隐藏")
        else:
            self._ai_key_edit.setEchoMode(QLineEdit.EchoMode.Password)
            self._ai_key_toggle.setText("显示")

    def _on_test_ai(self):
        """测试当前 AI 连接是否可用"""
        import threading

        base_url = self._ai_base_url_edit.text().strip()
        api_key  = self._ai_key_edit.text().strip()
        model    = self._ai_model_edit.text().strip() or "auto"

        # 优先使用界面填写的值；为空时回落到环境变量
        import os
        base_url = base_url or os.getenv("AI_API_BASE_URL", "http://localhost:3001/v1")
        api_key  = api_key  or os.getenv("AI_API_KEY", "")
        model    = model    or os.getenv("AI_MODEL_NAME", "auto")

        self._test_ai_btn.setEnabled(False)
        self._test_ai_btn.setText("测试中…")

        def _do_test():
            try:
                import httpx
                payload = {
                    "model": model,
                    "messages": [{"role": "user", "content": "你好，请回复'测试成功'两个字"}],
                    "max_tokens": 20,
                    "stream": False,
                }
                headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
                resp = httpx.post(
                    f"{base_url.rstrip('/')}/chat/completions",
                    json=payload, headers=headers,
                    timeout=12.0,
                )
                if resp.status_code == 200:
                    data = resp.json()
                    text = data["choices"][0]["message"]["content"].strip()
                    return True, f"连接成功 ✅\n\nAI 回复：{text}"
                else:
                    return False, f"连接失败：HTTP {resp.status_code}\n{resp.text[:200]}"
            except Exception as e:
                return False, f"连接失败：{e}"

        from PySide6.QtCore import QMetaObject, Q_ARG

        def _worker():
            ok, msg = _do_test()
            self._test_result.emit(ok, msg)

        threading.Thread(target=_worker, daemon=True).start()

    @Slot(bool, str)
    def _on_test_ai_done(self, ok: bool, msg: str):
        """测试结果回调（在主线程执行）"""
        self._test_ai_btn.setEnabled(True)
        self._test_ai_btn.setText("🔗  测试 AI 连接")
        if ok:
            QMessageBox.information(self, "AI 连接测试", msg)
        else:
            QMessageBox.warning(self, "AI 连接测试", msg)

    def _on_save(self):
        """读取当前控件值，合并回原始 JSON 并写入文件"""
        # 先加载原始 JSON（保留其他字段，如 app_name、log_level 等）
        raw = _load_raw_config()

        # ── 写回各字段 ─────────────────────────────────────────
        # 搜索引擎
        if "search" not in raw:
            raw["search"] = {}
        raw["search"]["engine"] = self._search_engine_box.currentText()

        # 休眠行为
        if "behavior" not in raw:
            raw["behavior"] = {}
        raw["behavior"]["idle_sleep_minutes"] = self._idle_spin.value()
        raw["behavior"]["cpu_sleep_threshold"] = self._cpu_spin.value()
        raw["behavior"]["blacklist_processes"] = _lines_to_list(
            self._blacklist_edit.toPlainText()
        )

        # 截图目录
        if "screenshot" not in raw:
            raw["screenshot"] = {}
        raw["screenshot"]["save_dir"] = self._screenshot_dir_edit.text().strip()

        # AI 配置（完整写入）
        if "ai" not in raw:
            raw["ai"] = {}
        raw["ai"]["provider"]        = self._ai_provider_box.currentText()
        raw["ai"]["base_url"]        = self._ai_base_url_edit.text().strip()
        raw["ai"]["api_key"]         = self._ai_key_edit.text().strip()
        raw["ai"]["model"]           = self._ai_model_edit.text().strip()
        raw["ai"]["enable_ai_cache"] = self._ai_cache_check.isChecked()

        # 快捷应用
        raw["quick_apps"] = _lines_to_apps(
            self._quick_apps_edit.toPlainText()
        )

        # 快捷文件夹
        raw["quick_folders"] = _lines_to_folders(
            self._quick_folders_edit.toPlainText()
        )

        # 语音配置（顶层字段）
        raw["voice_enabled"]  = self._voice_enabled_check.isChecked()
        raw["tts_enabled"]    = self._tts_enabled_check.isChecked()
        raw["tts_provider"]   = self._tts_provider_box.currentText()
        raw["tts_voice"]      = self._tts_voice_edit.text().strip() or "zh-CN-XiaoxiaoNeural"
        raw["tts_max_chars"]  = self._tts_max_chars_spin.value()
        raw["asr_provider"]   = self._asr_provider_box.currentText()

        # ── 写入文件 ────────────────────────────────────────────
        try:
            _save_raw_config(raw)
            logger.info("SettingsWindow：配置已保存到 config.json")
            QMessageBox.information(
                self, "✅ 保存成功",
                "设置已保存到 config.json。\n\n"
                "• AI Key / Base URL / Model 也可在 .env 中覆盖（优先级更高）\n"
                "• 部分配置（如 AI 连接）重启后生效"
            )
        except Exception as e:
            logger.error(f"SettingsWindow：保存 config.json 失败：{e}")
            QMessageBox.critical(
                self, "❌ 保存失败",
                f"写入配置文件失败：\n{e}\n\n请检查文件权限或磁盘空间。"
            )


# ── 内嵌 QSS 样式 ────────────────────────────────────────────────

_DARK_SETTINGS_QSS = """
QWidget {
    background-color: #1e1e2e;
    color: #cdd6f4;
    font-family: "Microsoft YaHei", "PingFang SC", sans-serif;
    font-size: 13px;
}
#TitleBar {
    background-color: #181825;
    border-bottom: 1px solid #313244;
}
#TitleLabel { color: #cba6f7; }
#BottomBar {
    background-color: #181825;
    border-top: 1px solid #313244;
}
#SectionLabel { color: #89dceb; margin-top: 4px; }
#HintLabel    { color: #6c7086; font-size: 12px; }
#TipLabel     { color: #a6adc8; font-size: 12px;
                background-color: #181825;
                border: 1px solid #313244;
                border-radius: 6px;
                padding: 8px; }
#Divider { color: #313244; }
QLineEdit, QTextEdit, QSpinBox, QComboBox {
    background-color: #313244;
    color: #cdd6f4;
    border: 1px solid #45475a;
    border-radius: 6px;
    padding: 4px 8px;
}
QLineEdit:focus, QTextEdit:focus, QSpinBox:focus, QComboBox:focus {
    border: 1px solid #89b4fa;
}
QCheckBox { color: #cdd6f4; }
QCheckBox::indicator {
    width: 16px; height: 16px;
    border: 1px solid #45475a;
    border-radius: 4px;
    background: #313244;
}
QCheckBox::indicator:checked {
    background: #89b4fa;
    border: 1px solid #89b4fa;
}
QComboBox::drop-down { border: none; }
QComboBox QAbstractItemView {
    background-color: #313244;
    color: #cdd6f4;
    selection-background-color: #45475a;
}
#SaveButton {
    background-color: #89b4fa;
    color: #1e1e2e;
    border: none;
    border-radius: 8px;
    font-weight: bold;
}
#SaveButton:hover  { background-color: #74c7ec; }
#SaveButton:pressed{ background-color: #5c8fd8; }
#ResetButton {
    background-color: #45475a;
    color: #cdd6f4;
    border: none;
    border-radius: 8px;
}
#ResetButton:hover { background-color: #585b70; }
#TestAIButton {
    background-color: #313244;
    color: #a6e3a1;
    border: 1px solid #a6e3a1;
    border-radius: 8px;
    padding: 0 12px;
}
#TestAIButton:hover  { background-color: #3d4058; }
#TestAIButton:pressed{ background-color: #282a36; }
#TestAIButton:disabled { color: #6c7086; border-color: #6c7086; }
#DiscoveryButton {
    background-color: #313244;
    color: #89dceb;
    border: 1px solid #45475a;
    border-radius: 8px;
    padding: 0 10px;
}
#DiscoveryButton:hover  { background-color: #3d4058; border-color: #89dceb; }
#DiscoveryButton:pressed{ background-color: #282a36; }
#DiscoveryButton:disabled { color: #6c7086; }
#DiscoveryTabs::pane { border: 1px solid #313244; border-radius: 4px; }
#DiscoveryTabs QTabBar::tab {
    background: #181825; color: #a6adc8;
    padding: 4px 12px; border-radius: 4px 4px 0 0;
}
#DiscoveryTabs QTabBar::tab:selected { background: #313244; color: #cdd6f4; }
QTableWidget { background: #181825; color: #cdd6f4;
               gridline-color: #313244; border: none; }
QHeaderView::section { background: #313244; color: #89b4fa;
                        border: none; padding: 4px; }
QScrollBar:vertical {
    background: #1e1e2e; width: 6px; border-radius: 3px;
}
QScrollBar::handle:vertical {
    background: #45475a; border-radius: 3px; min-height: 20px;
}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
"""

_LIGHT_SETTINGS_QSS = """
QWidget {
    background-color: #eff1f5;
    color: #4c4f69;
    font-family: "Microsoft YaHei", "PingFang SC", sans-serif;
    font-size: 13px;
}
#TitleBar {
    background-color: #e6e9ef;
    border-bottom: 1px solid #ccd0da;
}
#TitleLabel { color: #7287fd; }
#BottomBar {
    background-color: #e6e9ef;
    border-top: 1px solid #ccd0da;
}
#SectionLabel { color: #209fb5; margin-top: 4px; }
#HintLabel    { color: #9ca0b0; font-size: 12px; }
#TipLabel     { color: #6c6f85; font-size: 12px;
                background-color: #e6e9ef;
                border: 1px solid #ccd0da;
                border-radius: 6px;
                padding: 8px; }
#Divider { color: #ccd0da; }
QLineEdit, QTextEdit, QSpinBox, QComboBox {
    background-color: #ffffff;
    color: #4c4f69;
    border: 1px solid #ccd0da;
    border-radius: 6px;
    padding: 4px 8px;
}
QLineEdit:focus, QTextEdit:focus, QSpinBox:focus, QComboBox:focus {
    border: 1px solid #1e66f5;
}
QCheckBox { color: #4c4f69; }
QCheckBox::indicator {
    width: 16px; height: 16px;
    border: 1px solid #ccd0da;
    border-radius: 4px;
    background: #ffffff;
}
QCheckBox::indicator:checked {
    background: #1e66f5;
    border: 1px solid #1e66f5;
}
QComboBox::drop-down { border: none; }
QComboBox QAbstractItemView {
    background-color: #ffffff;
    color: #4c4f69;
    selection-background-color: #dce0e8;
}
#SaveButton {
    background-color: #1e66f5;
    color: #ffffff;
    border: none;
    border-radius: 8px;
    font-weight: bold;
}
#SaveButton:hover  { background-color: #5277d4; }
#SaveButton:pressed{ background-color: #1453c2; }
#ResetButton {
    background-color: #ccd0da;
    color: #4c4f69;
    border: none;
    border-radius: 8px;
}
#ResetButton:hover { background-color: #bcc0cc; }
#TestAIButton {
    background-color: #e6e9ef;
    color: #179299;
    border: 1px solid #179299;
    border-radius: 8px;
    padding: 0 12px;
}
#TestAIButton:hover  { background-color: #dce0e8; }
#TestAIButton:pressed{ background-color: #ccd0da; }
#TestAIButton:disabled { color: #9ca0b0; border-color: #9ca0b0; }
#DiscoveryButton {
    background-color: #e6e9ef; color: #179299;
    border: 1px solid #ccd0da; border-radius: 8px; padding: 0 10px;
}
#DiscoveryButton:hover  { background-color: #dce0e8; border-color: #179299; }
#DiscoveryButton:pressed{ background-color: #ccd0da; }
#DiscoveryButton:disabled { color: #9ca0b0; }
#DiscoveryTabs::pane { border: 1px solid #ccd0da; border-radius: 4px; }
#DiscoveryTabs QTabBar::tab {
    background: #e6e9ef; color: #6c6f85;
    padding: 4px 12px; border-radius: 4px 4px 0 0;
}
#DiscoveryTabs QTabBar::tab:selected { background: #ffffff; color: #4c4f69; }
QTableWidget { background: #ffffff; color: #4c4f69;
               gridline-color: #ccd0da; border: none; }
QHeaderView::section { background: #e6e9ef; color: #1e66f5;
                        border: none; padding: 4px; }
QScrollBar:vertical {
    background: #eff1f5; width: 6px; border-radius: 3px;
}
QScrollBar::handle:vertical {
    background: #bcc0cc; border-radius: 3px; min-height: 20px;
}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
"""
