"""One dark, high-contrast Qt theme for Live2D Reader and every dialog."""
from __future__ import annotations

from PySide6.QtGui import QColor, QFont, QPalette
from PySide6.QtWidgets import QApplication, QStyleFactory


# White/bold text over charcoal, near-black and navy throughout.
# Explicit popup styling is critical for QComboBox drop-down items on Windows.
DARK_STYLESHEET = """
QWidget {
    color: #FFFFFF;
    font-weight: 700;
}
QMainWindow, QDialog, QFrame, QScrollArea, QTabWidget, QWidget#meshConfig {
    background-color: #1B2028;
}
QGroupBox {
    background-color: #202834;
    border: 1px solid #455467;
    border-radius: 5px;
    margin-top: 16px;
    padding: 11px 7px 7px 7px;
    font-weight: 700;
}
QGroupBox::title {
    subcontrol-origin: margin;
    subcontrol-position: top left;
    left: 10px;
    padding: 0 4px;
    color: #FFFFFF;
}
QLabel, QCheckBox, QRadioButton {
    color: #FFFFFF;
    background: transparent;
}
QPushButton {
    background: #29384C;
    color: #FFFFFF;
    font-weight: 700;
    border: 1px solid #526379;
    border-radius: 5px;
    padding: 7px 11px;
    min-height: 24px;
}
QPushButton:hover { background: #364E69; border-color: #7086A1; }
QPushButton:pressed { background: #14263B; }
QPushButton:disabled { color: #FFFFFF; background: #303740; border-color: #424A54; }
QLineEdit, QTextEdit, QPlainTextEdit,
QSpinBox, QDoubleSpinBox, QComboBox {
    background-color: #101820;
    color: #FFFFFF;
    selection-color: #FFFFFF;
    selection-background-color: #355D86;
    border: 1px solid #58677A;
    border-radius: 4px;
    padding: 5px 7px;
    font-weight: 700;
    min-height: 23px;
}
QLineEdit:disabled, QSpinBox:disabled,
QDoubleSpinBox:disabled, QComboBox:disabled {
    background-color: #292F38;
    color: #FFFFFF;
    border-color: #475260;
}
QLineEdit:focus, QSpinBox:focus,
QDoubleSpinBox:focus, QComboBox:focus {
    border-color: #94B7E7;
}
QComboBox::drop-down {
    border: 0;
    border-left: 1px solid #526379;
    background-color: #243448;
    width: 25px;
}
QComboBox QAbstractItemView,
QComboBox QListView, QComboBox QTreeView {
    background-color: #101820;
    color: #FFFFFF;
    selection-color: #FFFFFF;
    selection-background-color: #365D86;
    border: 1px solid #68788D;
    outline: none;
    font-weight: 700;
}
QComboBox QAbstractItemView::item {
    background-color: #101820;
    color: #FFFFFF;
    padding: 5px;
    min-height: 24px;
}
QComboBox QAbstractItemView::item:selected,
QComboBox QAbstractItemView::item:hover {
    background-color: #355D86;
    color: #FFFFFF;
}
QListWidget, QTreeWidget, QTreeView, QTableView, QListView {
    background-color: #101820;
    alternate-background-color: #18212D;
    color: #FFFFFF;
    selection-background-color: #355D86;
    selection-color: #FFFFFF;
    border: 1px solid #48576A;
    outline: none;
}
QTreeView::item:selected, QListView::item:selected {
    background-color: #355D86;
    color: #FFFFFF;
}
QTreeView::item:hover, QListView::item:hover {
    background-color: #273C54;
    color: #FFFFFF;
}
QHeaderView::section {
    background-color: #303945;
    color: #FFFFFF;
    border: 1px solid #445163;
    padding: 7px;
    font-weight: 700;
}
QTabWidget::pane {
    background-color: #1B2028;
    border: 1px solid #3C4A5A;
}
QTabBar::tab {
    background-color: #28364A;
    color: #FFFFFF;
    border: 1px solid #455569;
    padding: 10px 16px;
    font-weight: 700;
}
QTabBar::tab:selected { background-color: #12263E; color: #FFFFFF; }
QTabBar::tab:hover { background-color: #35506B; }
QMenuBar, QMenu {
    background-color: #1B2028;
    color: #FFFFFF;
    border: 1px solid #425066;
    font-weight: 700;
}
QMenuBar::item:selected, QMenu::item:selected {
    background-color: #355D86;
    color: #FFFFFF;
}
QScrollBar:vertical, QScrollBar:horizontal {
    background: #151B24;
    border: none;
    width: 13px;
    height: 13px;
}
QScrollBar::handle:vertical, QScrollBar::handle:horizontal {
    background: #556579;
    border-radius: 5px;
    min-height: 28px;
    min-width: 28px;
}
QScrollBar::handle:vertical:hover, QScrollBar::handle:horizontal:hover {
    background: #788CA3;
}
QScrollBar::add-line, QScrollBar::sub-line,
QScrollBar::add-page, QScrollBar::sub-page {
    background: none;
    border: none;
    width: 0;
    height: 0;
}
QSplitter::handle {
    background: #485C75;
    border: 1px solid #243345;
}
QSplitter::handle:hover { background: #7590B1; }
QProgressBar {
    background: #101820;
    color: #FFFFFF;
    border: 1px solid #516073;
    border-radius: 3px;
    text-align: center;
    font-weight: 700;
}
QProgressBar::chunk { background: #436B96; }
QToolTip {
    color: #FFFFFF;
    background-color: #182331;
    border: 1px solid #60748D;
    font-weight: 700;
    padding: 5px;
}
"""


def apply_dark_theme(app: QApplication) -> None:
    """Ensure dialogs and combo popups inherit the same dark Qt palette."""
    app.setStyle(QStyleFactory.create("Fusion"))
    palette = QPalette()
    palette.setColor(QPalette.ColorRole.Window, QColor("#1B2028"))
    palette.setColor(QPalette.ColorRole.WindowText, QColor("#FFFFFF"))
    palette.setColor(QPalette.ColorRole.Base, QColor("#101820"))
    palette.setColor(QPalette.ColorRole.AlternateBase, QColor("#18212D"))
    palette.setColor(QPalette.ColorRole.ToolTipBase, QColor("#182331"))
    palette.setColor(QPalette.ColorRole.ToolTipText, QColor("#FFFFFF"))
    palette.setColor(QPalette.ColorRole.Text, QColor("#FFFFFF"))
    palette.setColor(QPalette.ColorRole.Button, QColor("#29384C"))
    palette.setColor(QPalette.ColorRole.ButtonText, QColor("#FFFFFF"))
    palette.setColor(QPalette.ColorRole.BrightText, QColor("#FFFFFF"))
    palette.setColor(QPalette.ColorRole.Highlight, QColor("#355D86"))
    palette.setColor(QPalette.ColorRole.HighlightedText, QColor("#FFFFFF"))
    palette.setColor(QPalette.ColorRole.PlaceholderText, QColor("#D4DDEB"))
    for role in (QPalette.ColorRole.WindowText, QPalette.ColorRole.Text,
                 QPalette.ColorRole.ButtonText, QPalette.ColorRole.HighlightedText):
        palette.setColor(QPalette.ColorGroup.Disabled, role, QColor("#FFFFFF"))
    palette.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.Base,
                     QColor("#292F38"))
    palette.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.Button,
                     QColor("#303740"))
    app.setPalette(palette)
    font = QFont("Segoe UI", 10)
    font.setBold(True)
    app.setFont(font)
    app.setStyleSheet(DARK_STYLESHEET)
