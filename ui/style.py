"""
QSS 样式模块
提供深色科技风和浅色两套主题，所有样式集中在此，不散落在业务逻辑中。

常量说明：
    CHAT_WINDOW_STYLE      完整窗口 QSS（deep dark 基调）
    SEND_BUTTON_STYLE      发送按钮附加样式（蓝紫渐变）
    STOP_BUTTON_STYLE      停止按钮附加样式（橙红警示）
    USER_BUBBLE_STYLE      用户气泡附加背景（QLabel setStyleSheet 用）
    ASSISTANT_BUBBLE_STYLE 助手气泡附加背景
    LOADING_BUBBLE_STYLE   执行中临时气泡
"""

# ─────────────────────────────────────────────────────────────────
#  深色主题（默认）
# ─────────────────────────────────────────────────────────────────

_DARK_QSS = """
/* ══ 全局基础 ═══════════════════════════════════════════════════ */
QWidget {
    background-color: #13131f;
    color: #d0d6f0;
    font-family: "Microsoft YaHei UI", "PingFang SC", "Segoe UI", sans-serif;
    font-size: 13px;
}

/* ══ 聊天窗口主体 ════════════════════════════════════════════════ */
#ChatWindow {
    background-color: #13131f;
    border-radius: 12px;
}

/* ══ 顶部标题栏 ══════════════════════════════════════════════════ */
#TitleBar {
    background-color: #1a1a2e;
    border-bottom: 1px solid #2a2a45;
    min-height: 56px;
    max-height: 56px;
}
#TitleLabel {
    color: #c8a8f8;
    font-size: 15px;
    font-weight: 600;
}
#SubTitleLabel {
    color: #6a7090;
    font-size: 11px;
}
#ClearButton {
    background-color: transparent;
    color: #6a7090;
    border: 1px solid #2e2e50;
    border-radius: 8px;
    font-size: 12px;
    padding: 4px 12px;
    min-width: 44px;
}
#ClearButton:hover {
    background-color: #2a2a45;
    color: #c8a8f8;
    border-color: #5a4a80;
}
#ClearButton:pressed {
    background-color: #3a3060;
}

/* ══ 聊天消息滚动区 ══════════════════════════════════════════════ */
#ChatScrollArea {
    border: none;
    background-color: transparent;
}
#ChatScrollArea > QWidget > QWidget {
    background-color: transparent;
}
#MsgContainer {
    background-color: #13131f;
}

/* ══ 消息气泡（主容器行）════════════════════════════════════════ */
#BubbleRow {
    background-color: transparent;
}

/* 用户气泡 - 右侧蓝紫渐变 */
#UserBubble {
    background: qlineargradient(
        x1:0, y1:0, x2:1, y2:1,
        stop:0 #6c63ff, stop:1 #4a90d9
    );
    color: #ffffff;
    border-radius: 16px 4px 16px 16px;
    padding: 10px 14px;
}

/* 助手气泡 - 左侧深色半透明 */
#AssistantBubble {
    background-color: #1e2040;
    color: #d0d6f0;
    border-radius: 4px 16px 16px 16px;
    border: 1px solid #2a2a50;
    padding: 10px 14px;
}

/* 临时 loading 气泡 */
#LoadingBubble {
    background-color: #1a1a35;
    color: #5a6090;
    border-radius: 4px 16px 16px 16px;
    border: 1px dashed #2a2a55;
    padding: 8px 14px;
    font-style: italic;
}

/* 助手头像小圆 */
#AvatarLabel {
    background-color: #2d2058;
    color: #c8a8f8;
    border-radius: 16px;
    font-size: 14px;
    font-weight: bold;
}

/* ══ 输入区 ════════════════════════════════════════════════════ */
#InputBar {
    background-color: #1a1a2e;
    border-top: 1px solid #2a2a45;
    padding: 0px;
}
#InputFrame {
    background-color: #1f1f38;
    border: 1px solid #2e2e55;
    border-radius: 14px;
}
#InputFrame:hover {
    border-color: #4a3a7a;
}
#InputTextEdit {
    background-color: transparent;
    color: #d0d6f0;
    border: none;
    border-radius: 14px;
    padding: 8px 12px;
    font-size: 13px;
    selection-background-color: #4a3a7a;
}
#InputTextEdit:focus {
    outline: none;
}

/* 发送按钮 - 蓝紫渐变 */
#SendButton {
    background: qlineargradient(
        x1:0, y1:0, x2:1, y2:1,
        stop:0 #7c5cbf, stop:1 #4a8ed4
    );
    color: #ffffff;
    border: none;
    border-radius: 12px;
    font-size: 13px;
    font-weight: bold;
    padding: 0px;
    min-width: 64px;
    min-height: 40px;
}
#SendButton:hover {
    background: qlineargradient(
        x1:0, y1:0, x2:1, y2:1,
        stop:0 #9070d8, stop:1 #5aa0e8
    );
}
#SendButton:pressed {
    background: qlineargradient(
        x1:0, y1:0, x2:1, y2:1,
        stop:0 #5a40a0, stop:1 #3070b0
    );
}

/* 停止按钮 - 橙红警示 */
#StopButton {
    background: qlineargradient(
        x1:0, y1:0, x2:1, y2:1,
        stop:0 #c0392b, stop:1 #e67e22
    );
    color: #ffffff;
    border: none;
    border-radius: 12px;
    font-size: 13px;
    font-weight: bold;
    padding: 0px;
    min-width: 64px;
    min-height: 40px;
}
#StopButton:hover {
    background: qlineargradient(
        x1:0, y1:0, x2:1, y2:1,
        stop:0 #e04535, stop:1 #f39030
    );
}
#StopButton:pressed {
    background: qlineargradient(
        x1:0, y1:0, x2:1, y2:1,
        stop:0 #922b21, stop:1 #b0601a
    );
}

/* ── 复制按钮 ── */
#CopyButton {
    background: transparent;
    color: #55557a;
    border: none;
    font-size: 10px;
    padding: 0px 4px;
    border-radius: 4px;
}
#CopyButton:hover {
    background: #23233a;
    color: #a0a0cc;
}
#CopyButton:pressed {
    background: #1a1a2e;
    color: #89b4fa;
}

/* ── 语音按钮 ── */
#VoiceButton {
    background: qlineargradient(x1:0,y1:0,x2:1,y2:1,
        stop:0 #1e2d45, stop:1 #1a3a3a);
    color: #74c7ec;
    border: 1px solid #3a5a7a;
    border-radius: 12px;
    font-size: 12px; font-weight: bold;
    min-width: 44px; min-height: 40px;
}
#VoiceButton:hover {
    background: qlineargradient(x1:0,y1:0,x2:1,y2:1,
        stop:0 #253550, stop:1 #204040);
    border-color: #74c7ec;
}
#VoiceButton:pressed {
    background: #131c2a;
}
#VoiceStopButton {
    background: qlineargradient(x1:0,y1:0,x2:1,y2:1,
        stop:0 #3a1a2a, stop:1 #2a1a3a);
    color: #f38ba8;
    border: 1px solid #7a3a5a;
    border-radius: 12px;
    font-size: 12px; font-weight: bold;
    min-width: 44px; min-height: 40px;
}
#VoiceStopButton:hover {
    background: qlineargradient(x1:0,y1:0,x2:1,y2:1,
        stop:0 #501a2a, stop:1 #3a1a50);
    border-color: #f38ba8;
}
#VoiceDisabledButton {
    background: #1a1a2e;
    color: #45475a;
    border: 1px solid #313244;
    border-radius: 12px;
    font-size: 11px;
    min-width: 44px; min-height: 40px;
}

/* ══ 滚动条 ════════════════════════════════════════════════════ */
QScrollBar:vertical {
    background: transparent;
    width: 5px;
    border-radius: 3px;
    margin: 0px;
}
QScrollBar::handle:vertical {
    background: #2e2e55;
    border-radius: 3px;
    min-height: 24px;
}
QScrollBar::handle:vertical:hover {
    background: #4a3a7a;
}
QScrollBar::add-line:vertical,
QScrollBar::sub-line:vertical {
    height: 0px;
}
QScrollBar::add-page:vertical,
QScrollBar::sub-page:vertical {
    background: transparent;
}
"""

# ─────────────────────────────────────────────────────────────────
#  浅色主题
# ─────────────────────────────────────────────────────────────────

_LIGHT_QSS = """
QWidget {
    background-color: #f0f2fa;
    color: #3a3d5a;
    font-family: "Microsoft YaHei UI", "PingFang SC", "Segoe UI", sans-serif;
    font-size: 13px;
}
#ChatWindow { background-color: #f0f2fa; border-radius: 12px; }
#TitleBar {
    background-color: #e4e7f5;
    border-bottom: 1px solid #c8cce0;
    min-height: 56px; max-height: 56px;
}
#TitleLabel { color: #6040c0; font-size: 15px; font-weight: 600; }
#SubTitleLabel { color: #8890b0; font-size: 11px; }
#ClearButton {
    background-color: transparent;
    color: #8890b0; border: 1px solid #c0c5dc;
    border-radius: 8px; font-size: 12px; padding: 4px 12px; min-width: 44px;
}
#ClearButton:hover { background-color: #d8ddf2; color: #6040c0; border-color: #a098d8; }
#ChatScrollArea { border: none; background-color: transparent; }
#MsgContainer { background-color: #f0f2fa; }
#BubbleRow { background-color: transparent; }
#UserBubble {
    background: qlineargradient(x1:0,y1:0,x2:1,y2:1,stop:0 #7c5cbf,stop:1 #4a8ed4);
    color: #ffffff; border-radius: 16px 4px 16px 16px; padding: 10px 14px;
}
#AssistantBubble {
    background-color: #ffffff; color: #3a3d5a;
    border-radius: 4px 16px 16px 16px;
    border: 1px solid #d0d4e8; padding: 10px 14px;
}
#LoadingBubble {
    background-color: #e8eaf5; color: #9098b8;
    border-radius: 4px 16px 16px 16px;
    border: 1px dashed #c0c5dc; padding: 8px 14px; font-style: italic;
}
#AvatarLabel {
    background-color: #d8d0f0; color: #6040c0;
    border-radius: 16px; font-size: 14px; font-weight: bold;
}
#InputBar { background-color: #e4e7f5; border-top: 1px solid #c8cce0; }
#InputFrame {
    background-color: #ffffff; border: 1px solid #c8cce0; border-radius: 14px;
}
#InputTextEdit {
    background-color: transparent; color: #3a3d5a; border: none;
    border-radius: 14px; padding: 8px 12px; font-size: 13px;
}
#SendButton {
    background: qlineargradient(x1:0,y1:0,x2:1,y2:1,stop:0 #7c5cbf,stop:1 #4a8ed4);
    color: #ffffff; border: none; border-radius: 12px;
    font-size: 13px; font-weight: bold;
    min-width: 64px; min-height: 40px;
}
#SendButton:hover { background: qlineargradient(x1:0,y1:0,x2:1,y2:1,stop:0 #9070d8,stop:1 #5aa0e8); }
#StopButton {
    background: qlineargradient(x1:0,y1:0,x2:1,y2:1,stop:0 #c0392b,stop:1 #e67e22);
    color: #ffffff; border: none; border-radius: 12px;
    font-size: 13px; font-weight: bold;
    min-width: 64px; min-height: 40px;
}
#StopButton:hover { background: qlineargradient(x1:0,y1:0,x2:1,y2:1,stop:0 #e04535,stop:1 #f39030); }
#CopyButton {
    background: transparent; color: #9a9cbf;
    border: none; font-size: 10px; padding: 0px 4px; border-radius: 4px;
}
#CopyButton:hover { background: #dce0ee; color: #5a5d8a; }
#CopyButton:pressed { background: #c8cce0; color: #4a4d7a; }
#VoiceButton {
    background: qlineargradient(x1:0,y1:0,x2:1,y2:1,stop:0 #dce8f8,stop:1 #d0eaea);
    color: #1e66a0; border: 1px solid #a0c4dc;
    border-radius: 12px; font-size: 12px; font-weight: bold;
    min-width: 44px; min-height: 40px;
}
#VoiceButton:hover { background: #c8dff0; border-color: #1e66a0; }
#VoiceButton:pressed { background: #b0cce0; }
#VoiceStopButton {
    background: qlineargradient(x1:0,y1:0,x2:1,y2:1,stop:0 #f8dce0,stop:1 #ead0d8);
    color: #a0001e; border: 1px solid #dca0b0;
    border-radius: 12px; font-size: 12px; font-weight: bold;
    min-width: 44px; min-height: 40px;
}
#VoiceStopButton:hover { background: #f0c8d0; border-color: #a0001e; }
#VoiceDisabledButton {
    background: #e6e9ef; color: #9ca0b0; border: 1px solid #ccd0da;
    border-radius: 12px; font-size: 11px;
    min-width: 44px; min-height: 40px;
}
QScrollBar:vertical { background: transparent; width: 5px; border-radius: 3px; }
QScrollBar::handle:vertical { background: #c0c5dc; border-radius: 3px; min-height: 24px; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0px; }
"""


def load_stylesheet(theme: str = "dark") -> str:
    """根据主题名返回对应的 QSS 字符串"""
    if theme == "light":
        return _LIGHT_QSS
    return _DARK_QSS
