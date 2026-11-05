"""LLPlayer's desktop component library. Qt supplies input, focus and accessibility."""
from pathlib import Path

from PySide6.QtCore import Qt, QSize
from PySide6.QtGui import QColor, QIcon, QPalette
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFileDialog,
    QFrame, QGraphicsScene, QGraphicsView, QHBoxLayout, QFormLayout, QGridLayout,
    QInputDialog, QLabel, QLineEdit, QListView, QListWidget, QListWidgetItem,
    QMainWindow, QMenu, QMessageBox, QPushButton, QScrollArea, QSizePolicy, QSlider,
    QSpinBox, QSplitter, QStackedWidget, QStyle, QStyledItemDelegate, QTextBrowser,
    QVBoxLayout, QWidget, QWidgetAction,
)

ASSETS = Path(__file__).parent / "assets"
SHELL = "#151a24"
PANEL = "#1c2330"
EDGE = "#354053"
TEXT = "#eef4ff"
MUTED = "#a9b7cb"
ACCENT = "#85bdff"
ACTIVE = "#253951"


def glyph(name):
    return QIcon(str(ASSETS / (name + ".svg")))


class Button(QPushButton):
    def __init__(self, label, callback=None, *, kind="secondary", symbol=None):
        super().__init__(label)
        self.setProperty("variant", kind)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setAutoDefault(False)
        if symbol:
            self.setIcon(glyph(symbol))
            self.setIconSize(QSize(18, 18))
        if callback:
            self.clicked.connect(callback)


class IconButton(Button):
    def __init__(self, name, label, callback=None):
        super().__init__("", callback, kind="tool", symbol=name)
        self.setObjectName(name)
        self.setAccessibleName(label)
        self.setToolTip(label)
        self.setFixedSize(34, 32)


def dialog_header(dialog, title, layout):
    row = QHBoxLayout()
    heading = QLabel(title)
    heading.setObjectName("Heading")
    row.addWidget(heading, 1)
    row.addWidget(IconButton("close", f"Close {dialog.windowTitle()}", dialog.reject))
    layout.addLayout(row)


class Choice(QComboBox):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setView(QListView())
        self.setCursor(Qt.CursorShape.PointingHandCursor)


def install(app):
    if app.property("llplayerTheme"):
        return
    app.setProperty("llplayerTheme", True)
    app.setStyle("Fusion")
    palette = QPalette()
    for role, color in {
        "Window": SHELL, "WindowText": TEXT, "Base": "#141b27", "AlternateBase": PANEL,
        "Text": TEXT, "Button": PANEL, "ButtonText": TEXT, "Highlight": ACTIVE,
        "HighlightedText": TEXT, "PlaceholderText": MUTED, "ToolTipBase": PANEL,
        "ToolTipText": TEXT, "BrightText": TEXT, "Link": ACCENT,
    }.items():
        palette.setColor(getattr(QPalette.ColorRole, role), QColor(color))
    app.setPalette(palette)
    app.setStyleSheet(stylesheet())


def stylesheet(background=SHELL, accent=ACCENT):
    rules = (ASSETS / "components.qss").read_text()
    for token, value in {"shell": background, "panel": PANEL, "edge": EDGE, "text": TEXT,
                         "muted": MUTED, "accent": accent, "active": ACTIVE,
                         "assets": ASSETS.as_posix()}.items():
        rules = rules.replace("@" + token, value)
    return rules


class Titlebar(QWidget):
    """Let the OS handle dragging and zooming on the empty part of the bar."""
    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self.window().windowHandle():
            self.window().windowHandle().startSystemMove()
        else:
            super().mousePressEvent(event)

    def mouseDoubleClickEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            window = self.window()
            window.showNormal() if window.isMaximized() else window.showMaximized()
        else:
            super().mouseDoubleClickEvent(event)


def hide_macos_title(window):
    """Keep the file title in Window menus while drawing it once in the toolbar."""
    import ctypes
    objc = ctypes.CDLL("/usr/lib/libobjc.A.dylib")
    objc.sel_registerName.argtypes = [ctypes.c_char_p]
    objc.sel_registerName.restype = ctypes.c_void_p
    getter = ctypes.CFUNCTYPE(ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p)(
        ("objc_msgSend", objc))
    setter = ctypes.CFUNCTYPE(None, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_long)(
        ("objc_msgSend", objc))
    nswindow = getter(int(window.winId()), objc.sel_registerName(b"window"))
    if nswindow:
        setter(nswindow, objc.sel_registerName(b"setTitleVisibility:"), 1)
