"""Native study controls shared by setup, settings and the player."""
import html
from pathlib import Path

from PySide6.QtCore import QAbstractListModel, QModelIndex, QEvent, QLocale, QPointF, QRect, QSize, Qt, Signal
from PySide6.QtGui import QColor, QFont, QFontMetrics, QIcon, QPixmap, QTextDocument
from .components import (
    Choice as QComboBox, QCheckBox, QDialog, QDialogButtonBox, QFormLayout, QLabel, QPushButton,
    QStyledItemDelegate, QStyle, QVBoxLayout, QWidget, QListView,
)
from .subtitle_text import token_at
from .components import IconButton


def language_name(code):
    language = QLocale.codeToLanguage(code)
    return QLocale.languageToString(language)


class LanguageFields(QWidget):
    def __init__(self, settings):
        super().__init__()
        form = QFormLayout(self)
        form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapAllRows)
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        form.setVerticalSpacing(10)
        form.setContentsMargins(0, 0, 0, 0)
        self.boxes = []
        languages = sorted((QLocale.languageToString(lang), QLocale.languageToCode(lang))
                           for lang in QLocale.Language if QLocale.languageToCode(lang))
        for key, label in (("primary_language", "Primary language · I speak"), ("secondary_language", "Secondary language · I’m learning")):
            box = QComboBox()
            for name, code in languages:
                box.addItem(name, code)
            box.setCurrentIndex(box.findData(settings.data[key]))
            form.addRow(label, box)
            self.boxes.append(box)
        self.fallback = QCheckBox()
        self.fallback.setChecked(settings.data["auto_translate"])
        form.addRow(self.fallback)
        for box in self.boxes:
            box.currentIndexChanged.connect(self.update_fallback_label)
        self.update_fallback_label()

    def update_fallback_label(self):
        primary, secondary = (box.currentText() for box in self.boxes)
        self.fallback.setText(f"Translate {primary} into {secondary}\nwhen {secondary} subtitles are missing.")

    def save(self, settings):
        primary, secondary = (box.currentData() for box in self.boxes)
        if not primary or not secondary or primary == secondary:
            return False
        settings.data.update(primary_language=primary, secondary_language=secondary, languages_chosen=True,
                             auto_translate=self.fallback.isChecked())
        return True


class LanguageSetup(QDialog):
    def __init__(self, settings, parent):
        super().__init__(parent)
        self.setWindowTitle("Choose your languages")
        layout = QVBoxLayout(self)
        self.setMinimumWidth(400)
        layout.setSpacing(18)
        layout.setContentsMargins(28, 24, 28, 24)
        title = QLabel("Choose your languages")
        title.setObjectName("Heading")
        layout.addWidget(title)
        self.fields = LanguageFields(settings)
        layout.addWidget(self.fields)
        buttons = QDialogButtonBox()
        start = buttons.addButton("Start watching", QDialogButtonBox.ButtonRole.AcceptRole)
        start.setObjectName("PrimaryAction")
        start.setDefault(True)
        for box in self.fields.boxes:
            box.currentIndexChanged.connect(lambda: start.setEnabled(
                self.fields.boxes[0].currentData() != self.fields.boxes[1].currentData()))
        def finish():
            if self.fields.save(settings):
                settings.save()
                self.accept()
        buttons.accepted.connect(finish)
        layout.addWidget(buttons)


def icon_button(name, label, callback, layout):
    button = IconButton(name, label, callback)
    layout.addWidget(button)
    return button


class TranscriptModel(QAbstractListModel):
    """Expose cue data directly. Only visible rows need text layout or bitmap decoding."""
    lines_role = int(Qt.ItemDataRole.UserRole) + 1

    def __init__(self, parent):
        super().__init__(parent)
        self.rows = []

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.rows)

    def data(self, index, role):
        if not index.isValid():
            return None
        start, end, lines, image = self.rows[index.row()]
        if role == Qt.ItemDataRole.DisplayRole:
            seconds = max(0, start) // 1000
            return f"{seconds // 60}:{seconds % 60:02}  " + "  ".join(text for _, text in lines)
        if role == Qt.ItemDataRole.UserRole:
            return (start, end)
        if role == self.lines_role:
            return lines
        if role == Qt.ItemDataRole.DecorationRole and image:
            pixmap = QPixmap()
            pixmap.loadFromData(image)
            return QIcon(pixmap)
        return None

    def replace(self, rows):
        if len(rows) != len(self.rows):
            self.beginResetModel()
            self.rows = rows
            self.endResetModel()
            return
        previous, self.rows = self.rows, rows
        first = next((i for i, (old, new) in enumerate(zip(previous, rows)) if old != new), None)
        if first is not None:
            last = next(i for i in range(len(rows) - 1, first - 1, -1) if previous[i] != rows[i])
            self.dataChanged.emit(self.index(first, 0), self.index(last, 0))


class TranscriptList(QListView):
    browsing = Signal()

    def event(self, event):
        if (event.type() == QEvent.Type.ShortcutOverride and not event.modifiers()
                and event.key() in (Qt.Key.Key_Up, Qt.Key.Key_Down)):
            event.accept()
            return True
        return super().event(event)

    def wheelEvent(self, event):
        self.browsing.emit()
        super().wheelEvent(event)

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_F10 and event.modifiers() == Qt.KeyboardModifier.ShiftModifier:
            if self.currentIndex().isValid():
                self.customContextMenuRequested.emit(self.visualRect(self.currentIndex()).center())
            return
        if event.key() in (Qt.Key.Key_Up, Qt.Key.Key_Down, Qt.Key.Key_PageUp, Qt.Key.Key_PageDown,
                           Qt.Key.Key_Home, Qt.Key.Key_End):
            self.browsing.emit()
        super().keyPressEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            point = event.position().toPoint()
            index = self.indexAt(point)
            if index.isValid() and self.itemDelegate().word(point, index):
                event.accept()
                return
        super().mouseReleaseEvent(event)


class TranscriptDelegate(QStyledItemDelegate):
    def __init__(self, parent):
        super().__init__(parent)
        self._row_heights = {}
        self._metric_font = None
        self._metrics = {}

    wordClicked = Signal(str, int)
    lines_role = TranscriptModel.lines_role

    def document(self, index, width):
        doc = QTextDocument()
        doc.setDocumentMargin(0)
        font = self.parent().font()
        font.setPixelSize(14)
        doc.setDefaultFont(font)
        pieces = []
        for slot, text in index.data(self.lines_role):
            color = "#eff4ff" if slot == 1 else "#b2c1d7"
            style = "font-weight:600;font-size:14px" if slot == 1 else "font-weight:400;font-size:13px"
            pieces.append(f'<span style="color:{color};{style}">{html.escape(text)}</span>')
        doc.setHtml("<br>".join(pieces))
        doc.setTextWidth(max(40, width - 78))
        return doc

    def sizeHint(self, option, index):
        width = self.parent().viewport().width()
        font = self.parent().font()
        if font != self._metric_font:
            self._metric_font = font
            self._row_heights.clear()
            for slot in (0, 1):
                line_font = QFont(font)
                line_font.setPixelSize(14 if slot else 13)
                line_font.setWeight(QFont.Weight.DemiBold if slot else QFont.Weight.Normal)
                self._metrics[slot] = QFontMetrics(line_font)
        lines = index.data(self.lines_role)
        key = (width, tuple(tuple(line) for line in lines))
        if key not in self._row_heights:
            if len(self._row_heights) >= 5000:
                self._row_heights.clear()
            bounds = QRect(0, 0, max(40, width - 78), 100000)
            flags = Qt.TextFlag.TextWordWrap | Qt.TextFlag.TextWrapAnywhere
            height = sum(self._metrics[slot].boundingRect(bounds, flags, " ".join(text.split()) or " ").height()
                         for slot, text in lines)
            self._row_heights[key] = max(50, height + 40)
        return QSize(0, self._row_heights[key])

    def paint(self, painter, option, index):
        rect = option.rect
        painter.save()
        if option.state & QStyle.StateFlag.State_Selected:
            painter.fillRect(rect, QColor("#253951"))
            painter.fillRect(rect.x(), rect.y(), 3, rect.height(), QColor("#85bdff"))
        painter.setPen(QColor("#282f3c"))
        painter.drawLine(rect.bottomLeft(), rect.bottomRight())
        painter.translate(rect.topLeft())
        painter.setPen(QColor("#adc1da"))
        clock_font = painter.font()
        clock_font.setFamily("Menlo")
        clock_font.setPixelSize(11)
        painter.setFont(clock_font)
        painter.drawText(18, 29, index.data().split(" ", 1)[0])
        painter.translate(70, 15)
        image = index.data(Qt.ItemDataRole.DecorationRole)
        if image and not any(text for _, text in index.data(self.lines_role)):
            painter.drawPixmap(0, 0, image.pixmap(QSize(max(50, rect.width()-80), 30)))
        else:
            self.document(index, rect.width()).drawContents(painter)
        painter.restore()

    def word(self, point, index):
        rect = self.parent().visualRect(index)
        doc = self.document(index, rect.width())
        at = doc.documentLayout().hitTest(QPointF(point - rect.topLeft()) - QPointF(70, 15),
                                          Qt.HitTestAccuracy.ExactHit)
        if at < 0:
            return
        for slot, text in index.data(self.lines_role):
            units = text.encode("utf-16-le")
            if at * 2 < len(units):
                offset = len(units[:at * 2].decode("utf-16-le", errors="ignore"))
                word = token_at(text, offset)
                if word:
                    self.wordClicked.emit(word, slot)
                    return True
            at -= len(units) // 2 + 1
