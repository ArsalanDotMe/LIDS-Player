"""Selectable subtitle styling and word interaction, authored for this player."""
import html
import re
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QTextCursor, QTextBlockFormat, QTextCharFormat, QPen, QColor
from .components import QTextBrowser, QFrame, QSizePolicy


def styled_ass(raw):
    """Render supported ASS inline styles as safe HTML, preserving plain text."""
    state = dict(b=False, i=False, u=False, s=False, color=None)
    output = []
    for part in re.split(r'(\{[^}]*\})', raw):
        if part.startswith('{') and part.endswith('}'):
            for name, value in re.findall(r'\\(1?c|b|i|u|s)([^\\}]*)', part):
                if name in ('c', '1c'):
                    match = re.fullmatch(r'&H([0-9A-Fa-f]{1,6})&?', value)
                    if match:
                        color = int(match.group(1), 16)
                        state['color'] = f'#{color & 255:02x}{(color >> 8) & 255:02x}{(color >> 16) & 255:02x}'
                    elif not value:
                        state['color'] = None
                elif re.fullmatch(r"-?\d+", value.strip()):
                    state[name] = value.strip() != '0'
            if r'\r' in part:
                state = dict(b=False, i=False, u=False, s=False, color=None)
            continue
        text = html.escape(part.replace(r'\N', '\n').replace(r'\n', '\n').replace(r'\h', '\u00a0')).replace('\n', '<br>')
        for key, tag in [('b','b'), ('i','i'), ('u','u'), ('s','s')]:
            if state[key]:
                text = f'<{tag}>{text}</{tag}>'
        if state['color']:
            text = f'<span style="color:{state["color"]}">{text}</span>'
        output.append(text)
    return ''.join(output)


def token_at(text, position):
    """Use native linguistic boundaries for CJK when available."""
    if not text or position < 0 or position >= len(text):
        return ''
    if re.search(r'[\u3040-\u30ff\u3400-\u9fff]', text):
        from .native_tools import tokenize
        for token in tokenize(text):
            if token['start'] <= position < token['end']:
                return token['text']
    for match in re.finditer(r"[^\W_]+(?:['’\-][^\W_]+)*", text, re.UNICODE):
        if match.start() <= position < match.end():
            return match.group()
    return ''


class SubtitleLabel(QTextBrowser):
    wordClicked = Signal(str)

    def __init__(self, text=''):
        super().__init__()
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setReadOnly(True)
        self.setOpenLinks(False)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.document().setDocumentMargin(3)
        self._press = None
        self._outline = ("#000000", 0)
        self.setText(text)

    def text(self):
        return self.toPlainText()

    def selectedText(self):
        return self.textCursor().selectedText().replace('\u2029', '\n')

    def setText(self, text):
        self.setPlainText(text)
        self.center_text()

    def setStyledText(self, markup):
        self.setHtml(markup)
        self.center_text()

    def center_text(self):
        cursor = self.textCursor()
        cursor.select(QTextCursor.SelectionType.Document)
        style = QTextBlockFormat()
        style.setAlignment(Qt.AlignmentFlag.AlignCenter)
        cursor.mergeBlockFormat(style)
        cursor.clearSelection()
        self.setTextCursor(cursor)
        self.apply_outline()
        self.update_height()

    def setOutline(self, color, width):
        self._outline = (color, width)
        self.apply_outline()

    def apply_outline(self):
        color, width = self._outline
        cursor = QTextCursor(self.document())
        cursor.select(QTextCursor.SelectionType.Document)
        style = QTextCharFormat()
        style.setTextOutline(QPen(QColor(color), width) if width else QPen(Qt.PenStyle.NoPen))
        cursor.mergeCharFormat(style)

    def setAlignment(self, alignment):
        self.center_text()

    def setWordWrap(self, enabled):
        pass  # QTextBrowser wraps by default.

    def setTextFormat(self, format):
        pass  # Plain text and safe styled text use separate setters.

    def update_height(self):
        self.document().setTextWidth(max(1, self.viewport().width()))
        self.setFixedHeight(int(self.document().size().height() + 4) if self.text() else 0)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.update_height()

    def mousePressEvent(self, event):
        self._press = event.position().toPoint()
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event):
        super().mouseReleaseEvent(event)
        if event.button() != Qt.MouseButton.LeftButton or self._press is None:
            return
        if (event.position().toPoint() - self._press).manhattanLength() > 4 or self.textCursor().hasSelection():
            return
        cursor = self.cursorForPosition(event.position().toPoint())
        # QTextCursor positions are UTF-16 offsets; Python indexes code points.
        prefix = self.text().encode('utf-16-le')[:cursor.position() * 2].decode('utf-16-le', errors='ignore')
        word = token_at(self.text(), min(len(prefix), max(0, len(self.text()) - 1)))
        if word:
            self.wordClicked.emit(word)
