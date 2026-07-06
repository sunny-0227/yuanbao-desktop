"""
QSS 样式加载模块
提供深色和浅色两套主题
"""


_DARK_QSS = """
/* ── 全局 ── */
QWidget {
    background-color: #1e1e2e;
    color: #cdd6f4;
    font-family: "Microsoft YaHei", "PingFang SC", sans-serif;
}

/* ── 标题栏 ── */
#TitleBar {
    background-color: #181825;
    border-bottom: 1px solid #313244;
}
#TitleLabel {
    color: #cba6f7;
}
#ClearButton {
    background-color: #313244;
    color: #a6adc8;
    border: none;
    border-radius: 6px;
    font-size: 12px;
}
#ClearButton:hover {
    background-color: #45475a;
    color: #cdd6f4;
}

/* ── 聊天滚动区 ── */
#ChatScrollArea {
    border: none;
    background-color: #1e1e2e;
}
#MsgContainer {
    background-color: #1e1e2e;
}

/* ── 消息气泡 ── */
#UserBubble {
    background-color: #89b4fa;
    color: #1e1e2e;
    border-radius: 14px;
    padding: 8px 14px;
    max-width: 280px;
}
#AssistantBubble {
    background-color: #313244;
    color: #cdd6f4;
    border-radius: 14px;
    padding: 8px 14px;
    max-width: 300px;
}

/* ── 输入栏 ── */
#InputBar {
    background-color: #181825;
    border-top: 1px solid #313244;
}
#InputTextEdit {
    background-color: #313244;
    color: #cdd6f4;
    border: 1px solid #45475a;
    border-radius: 10px;
    padding: 6px 10px;
    font-size: 13px;
}
#InputTextEdit:focus {
    border: 1px solid #89b4fa;
}
#SendButton {
    background-color: #89b4fa;
    color: #1e1e2e;
    border: none;
    border-radius: 10px;
    font-size: 14px;
    font-weight: bold;
}
#SendButton:hover {
    background-color: #74c7ec;
}
#SendButton:pressed {
    background-color: #5c8fd8;
}

/* ── 滚动条 ── */
QScrollBar:vertical {
    background: #1e1e2e;
    width: 6px;
    border-radius: 3px;
}
QScrollBar::handle:vertical {
    background: #45475a;
    border-radius: 3px;
    min-height: 20px;
}
QScrollBar::add-line:vertical,
QScrollBar::sub-line:vertical {
    height: 0px;
}
"""

_LIGHT_QSS = """
/* ── 全局 ── */
QWidget {
    background-color: #eff1f5;
    color: #4c4f69;
    font-family: "Microsoft YaHei", "PingFang SC", sans-serif;
}

/* ── 标题栏 ── */
#TitleBar {
    background-color: #e6e9ef;
    border-bottom: 1px solid #ccd0da;
}
#TitleLabel {
    color: #7287fd;
}
#ClearButton {
    background-color: #ccd0da;
    color: #5c5f77;
    border: none;
    border-radius: 6px;
    font-size: 12px;
}
#ClearButton:hover {
    background-color: #bcc0cc;
}

/* ── 聊天滚动区 ── */
#ChatScrollArea {
    border: none;
    background-color: #eff1f5;
}
#MsgContainer {
    background-color: #eff1f5;
}

/* ── 消息气泡 ── */
#UserBubble {
    background-color: #1e66f5;
    color: #ffffff;
    border-radius: 14px;
    padding: 8px 14px;
    max-width: 280px;
}
#AssistantBubble {
    background-color: #dce0e8;
    color: #4c4f69;
    border-radius: 14px;
    padding: 8px 14px;
    max-width: 300px;
}

/* ── 输入栏 ── */
#InputBar {
    background-color: #e6e9ef;
    border-top: 1px solid #ccd0da;
}
#InputTextEdit {
    background-color: #ffffff;
    color: #4c4f69;
    border: 1px solid #ccd0da;
    border-radius: 10px;
    padding: 6px 10px;
    font-size: 13px;
}
#InputTextEdit:focus {
    border: 1px solid #1e66f5;
}
#SendButton {
    background-color: #1e66f5;
    color: #ffffff;
    border: none;
    border-radius: 10px;
    font-size: 14px;
    font-weight: bold;
}
#SendButton:hover {
    background-color: #5277d4;
}
#SendButton:pressed {
    background-color: #1453c2;
}

/* ── 滚动条 ── */
QScrollBar:vertical {
    background: #eff1f5;
    width: 6px;
    border-radius: 3px;
}
QScrollBar::handle:vertical {
    background: #bcc0cc;
    border-radius: 3px;
    min-height: 20px;
}
QScrollBar::add-line:vertical,
QScrollBar::sub-line:vertical {
    height: 0px;
}
"""


def load_stylesheet(theme: str = "dark") -> str:
    """根据主题名返回对应的 QSS 字符串"""
    if theme == "light":
        return _LIGHT_QSS
    return _DARK_QSS
