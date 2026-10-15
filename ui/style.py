"""应用级主题，所有窗口共享语义颜色与字号。"""

from PySide6.QtGui import QColor, QPalette

from ui.brand import THEMES


def apply_theme(app, config):
    colors = THEMES[config.ui.theme]
    palette = QPalette()
    palette.setColor(QPalette.ColorRole.Window, QColor(colors["bg"]))
    palette.setColor(QPalette.ColorRole.Base, QColor(colors["panel"]))
    palette.setColor(QPalette.ColorRole.WindowText, QColor(colors["text"]))
    palette.setColor(QPalette.ColorRole.Text, QColor(colors["text"]))
    palette.setColor(QPalette.ColorRole.Button, QColor(colors["panel"]))
    palette.setColor(QPalette.ColorRole.ButtonText, QColor(colors["text"]))
    palette.setColor(QPalette.ColorRole.Highlight, QColor(colors["primary"]))
    palette.setColor(QPalette.ColorRole.HighlightedText, QColor(colors["on_primary"]))
    app.setPalette(palette)
    app.setStyleSheet(
        """
        QWidget {font-family: "Microsoft YaHei", "PingFang SC", sans-serif;
                 font-size: %(font)spx; color: %(text)s;}
        QMainWindow, QDialog, #Workspace {background: %(bg)s;}
        QLabel#PageTitle {font-size: 24px; font-weight: 600;}
        QLabel#Hint, QLabel#Status {color: %(muted)s;}
        QPushButton {background: %(panel)s; border: 1px solid %(border)s;
                     padding: 8px 12px; border-radius: 7px;}
        QPushButton:hover {background: %(active)s; border-color: %(accent)s;}
        QPushButton:disabled {color: %(muted)s;}
        QPushButton#Primary {background: %(primary)s; color: %(on_primary)s; font-weight: 600;}
        QLineEdit, QTextEdit, QPlainTextEdit, QSpinBox, QDoubleSpinBox, QComboBox {
            background: %(panel)s; border: 1px solid %(border)s; border-radius: 6px;
            padding: 6px; selection-background-color: %(active)s;}
        QTextBrowser {background: %(panel)s; border: 1px solid %(border)s; border-radius: 10px; padding: 12px;}
        QTableWidget {background: %(panel)s; border: 1px solid %(border)s; gridline-color: %(border)s;}
        QHeaderView::section {background: %(active)s; padding: 8px; border: none;}
        QListWidget#Navigation {background: transparent; border: none; outline: none;}
        QListWidget#Navigation::item {padding: 14px 10px; margin-bottom: 6px; border-radius: 7px;}
        QListWidget#Navigation::item:selected {background: %(active)s; color: %(accent)s;}
        QScrollArea {border: none; background: transparent;}
        QScrollArea#ChatScroll {border: 1px solid %(border)s; border-radius: 10px; background: %(bg)s;}
        QWidget#ChatSurface {background: %(bg)s;}
        QFrame#UserBubble {background: %(active)s; border: none; border-radius: 12px;}
        QFrame#AssistantBubble {background: %(panel)s; border: 1px solid %(border)s; border-radius: 12px;}
        QFrame#ErrorBubble {background: %(gold_surface)s; border: none; border-radius: 12px;}
        QTextBrowser#BubbleText {background: transparent; border: none; padding: 0; border-radius: 0;}
        QFrame#ErrorBubble QTextBrowser, QFrame#ErrorBubble QLabel {color: %(on_gold)s;}
        QLabel#BubbleHint {font-weight: 600;}
        QLabel#UserAvatar {background: %(primary)s; color: %(on_primary)s; border-radius: 8px; font-weight: 600;}
        QLabel#ChatEmpty {color: %(muted)s; padding: 28px;}
        QTabWidget::pane {border: 1px solid %(border)s;}
        QTabBar::tab {padding: 8px 14px; background: %(panel)s;}
        QTabBar::tab:selected {background: %(active)s;}
        QCheckBox {spacing: 8px;}
        QCheckBox::indicator {width: 16px; height: 16px; border-radius: 4px;
            border: 1px solid %(border)s; background: %(panel)s;}
        QCheckBox::indicator:checked {background: %(primary)s; border-color: %(accent)s;}
        QLineEdit:focus, QTextEdit:focus, QPlainTextEdit:focus {border-color: %(accent)s;}
        QPushButton#Primary:hover {background: %(primary)s; border-color: %(accent)s;}
        QLabel#BrandBadge {background: %(gold_surface)s; color: %(on_gold)s;
            padding: 6px 10px; border-radius: 6px;}
        QToolTip {background: %(panel)s; color: %(text)s; border: 1px solid %(border)s;}
    """
        % {**colors, "font": config.ui.font_size}
    )
