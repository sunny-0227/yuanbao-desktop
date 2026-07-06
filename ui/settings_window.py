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

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QFormLayout,
    QLabel, QLineEdit, QTextEdit, QComboBox, QCheckBox,
    QPushButton, QScrollArea, QFrame, QMessageBox,
    QSpinBox,
)
from PySide6.QtCore import Qt
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


# ── 主窗口 ──────────────────────────────────────────────────────

class SettingsWindow(QWidget):
    """
    设置窗口（非模态）。

    使用方式（在 main.py 中）：
        settings_win = SettingsWindow(theme=config.ui.theme)
        tray.set_callbacks(on_open_settings=settings_win.open, ...)

    调用 open() 而不是 show()，确保每次打开都刷新数据。
    """

    def __init__(self, theme: str = "dark", parent=None):
        super().__init__(parent)
        self._theme = theme
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

        # 缓存开关
        self._ai_cache_check = QCheckBox("启用 AI 回复本地缓存")
        self._ai_cache_check.setToolTip("开启后相同问题的 AI 回复会缓存到本地，加快响应速度")
        self._content_layout.addWidget(self._ai_cache_check)

        # API Key 说明（只读提示，不显示实际 key）
        tip = QLabel(
            "💡 AI API Key、模型名称、接口地址等敏感信息\n"
            "   请在项目根目录的 <b>.env</b> 文件中配置：\n"
            "   <code>AI_API_KEY=sk-xxxx</code>\n"
            "   <code>AI_API_BASE_URL=https://api.openai.com/v1</code>\n"
            "   <code>AI_MODEL_NAME=gpt-4o-mini</code>"
        )
        tip.setObjectName("TipLabel")
        tip.setTextFormat(Qt.TextFormat.RichText)
        tip.setWordWrap(True)
        tip.setContentsMargins(0, 4, 0, 0)
        self._content_layout.addWidget(tip)

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

        # AI 缓存
        enable_cache = raw.get("ai", {}).get("enable_ai_cache", True)
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

        logger.debug("SettingsWindow：配置已加载到 UI")

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

        # AI 缓存开关
        if "ai" not in raw:
            raw["ai"] = {}
        raw["ai"]["enable_ai_cache"] = self._ai_cache_check.isChecked()

        # 快捷应用
        raw["quick_apps"] = _lines_to_apps(
            self._quick_apps_edit.toPlainText()
        )

        # 快捷文件夹
        raw["quick_folders"] = _lines_to_folders(
            self._quick_folders_edit.toPlainText()
        )

        # ── 写入文件 ────────────────────────────────────────────
        try:
            _save_raw_config(raw)
            logger.info("SettingsWindow：配置已保存到 config.json")
            QMessageBox.information(
                self, "保存成功",
                "设置已保存，部分配置重启后生效。"
            )
        except Exception as e:
            logger.error(f"SettingsWindow：保存 config.json 失败：{e}")
            QMessageBox.critical(
                self, "保存失败",
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
QScrollBar:vertical {
    background: #eff1f5; width: 6px; border-radius: 3px;
}
QScrollBar::handle:vertical {
    background: #bcc0cc; border-radius: 3px; min-height: 20px;
}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
"""
