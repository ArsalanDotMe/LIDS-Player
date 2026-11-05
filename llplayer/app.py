from __future__ import annotations
import argparse
import html
import json
import re
from pathlib import Path
import sys
import tempfile
import threading
import os
import copy
from dataclasses import replace
from urllib.parse import quote

from PySide6.QtCore import Qt, QUrl, QTimer, QRunnable, QThreadPool, QObject, Signal, QEvent, QLocale, QStandardPaths, QSizeF, QRectF
from PySide6.QtGui import QAction, QKeySequence, QPixmap, QDesktopServices, QImage, QIcon, QFont, QCursor
from .components import (QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QSlider, QSplitter, QListWidget, QListWidgetItem, QLineEdit,
    QFileDialog, QInputDialog, QMessageBox, Choice as QComboBox, QDialog, QFormLayout, QSpinBox,
    QDialogButtonBox, QCheckBox, QScrollArea, QMenu, QTextBrowser, QGraphicsView, QGraphicsScene, QFrame, QStackedWidget, QSizePolicy)
from PySide6.QtMultimedia import QMediaPlayer, QAudioOutput, QMediaDevices, QAudioBufferOutput
from PySide6.QtMultimediaWidgets import QGraphicsVideoItem
from . import components as ui
from .core import Settings, Timeline, Cue, DEFAULT_SHORTCUTS
from . import services
from .subtitle_text import SubtitleLabel
from .native_tools import executable
from .playback import PlaybackTools
from .media_proxy import MediaProxy
from .study_ui import LanguageFields, LanguageSetup, TranscriptDelegate, TranscriptList, TranscriptModel, icon_button, language_name


class VideoCanvas(QGraphicsView):
    """Composite selectable subtitles over video on all three platforms."""
    def __init__(self):
        super().__init__()
        self.setScene(QGraphicsScene(self))
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setBackgroundBrush(Qt.GlobalColor.black)
        self.video_item = QGraphicsVideoItem()
        self.scene().addItem(self.video_item)
        self.proxy = None
        self.placement = (50, 85, "Center")
        self.safe_margin = 2
        self.aspect = "Auto"
        self.custom_aspect = "16:9"
        self.setMinimumSize(360, 240)

    def set_subtitles(self, widget):
        self.proxy = self.scene().addWidget(widget)
        self.proxy.setZValue(1)
        self.arrange()

    def arrange(self):
        width, height = self.viewport().width(), self.viewport().height()
        self.setSceneRect(QRectF(0, 0, width, height))
        rotated = round(self.video_item.rotation()) % 180 != 0
        item_width, item_height = (height, width) if rotated else (width, height)
        # A chosen display ratio stretches the decoded image inside a fitted box.
        ratio = self.custom_aspect if self.aspect == 'Custom' else self.aspect
        if ':' in ratio:
            left, right = (float(value) for value in ratio.split(':'))
            desired = left / right
            item_width, item_height = min(item_width, item_height * desired), min(item_height, item_width / desired)
            self.video_item.setAspectRatioMode(Qt.AspectRatioMode.IgnoreAspectRatio)
        elif self.aspect == 'Stretch':
            self.video_item.setAspectRatioMode(Qt.AspectRatioMode.IgnoreAspectRatio)
        else:
            self.video_item.setAspectRatioMode(Qt.AspectRatioMode.KeepAspectRatio)
        self.video_item.setSize(QSizeF(item_width, item_height))
        self.video_item.setTransformOriginPoint(self.video_item.boundingRect().center())
        self.video_item.setPos((width - item_width) / 2, (height - item_height) / 2)
        if self.proxy:
            self.proxy.widget().setFixedWidth(width)
            box = self.proxy.widget()
            for label in box.findChildren(SubtitleLabel):
                maximum = max(60, width - 48)
                text_width = max((label.fontMetrics().horizontalAdvance(line) for line in label.text().splitlines()), default=0)
                label.setFixedWidth(min(maximum, text_width + 32))
            box.adjustSize()
            horizontal, vertical, anchor = self.placement
            box_height = self.proxy.widget().height()
            y = height * vertical / 100 - ({"Top": 0, "Center": box_height / 2, "Bottom": box_height}.get(anchor, box_height / 2))
            if self.placement == (50, 85, "Center") and self.aspect == "Auto":
                native = self.video_item.nativeSize()
                if native.width() > 0 and native.height() > 0:
                    picture_height = min(height, width * native.height() / native.width())
                    bottom = (height + picture_height) / 2
                    y = bottom - box_height + box.layout().contentsMargins().bottom() - picture_height * .05
            if 0 <= vertical <= 100:
                margin = height * self.safe_margin / 100
                y = max(margin, min(y, height - margin - box_height))
            self.proxy.setPos((horizontal - 50) * width / 100, y)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.arrange()


class Signals(QObject):
    finished = Signal(object)
    error = Signal(str)
    progress = Signal(object)


class Job(QRunnable):
    def __init__(self, function, streaming=False):
        super().__init__()
        self.function = function
        self.streaming = streaming
        self.signals = Signals()

    def run(self):
        from shiboken6 import isValid
        try:
            result = self.function(self.signals.progress.emit) if self.streaming else self.function()
        except Exception as error:
            if isValid(self.signals):
                self.signals.error.emit(str(error))
        else:
            if isValid(self.signals):
                self.signals.finished.emit(result)


class SettingsDialog(QDialog):
    def __init__(self, settings, parent=None, owner=None):
        super().__init__(parent)
        self.owner = owner or parent
        self.account_base = settings.data.get("opensubtitles_base", "")
        self.setWindowTitle("Settings")
        self.resize(640, 650)
        self.settings = settings
        self.fields = {}
        self._profiles = json.loads(json.dumps(settings.data["provider_profiles"]))
        self._provider = settings.data["provider"]
        layout = QVBoxLayout(self)
        content = QHBoxLayout()
        layout.addLayout(content, 1)
        sections = QListWidget()
        self.sections = sections
        sections.setAccessibleName("Settings sections")
        sections.setFixedWidth(135)
        pages = QStackedWidget()
        content.addWidget(sections)
        content.addWidget(pages, 1)
        sections.currentRowChanged.connect(pages.setCurrentIndex)

        def add_page(widget, name):
            sections.addItem(name)
            pages.addWidget(widget)

        self.languages = LanguageFields(settings)
        language_page = QWidget()
        language_layout = QVBoxLayout(language_page)
        heading = QLabel("Languages")
        heading.setObjectName("Heading")
        language_layout.addWidget(heading)
        language_layout.addWidget(self.languages)
        language_layout.addStretch()
        add_page(language_page, "Languages")
        groups = {
            "Subtitles": ["font_size", "secondary_size", "subtitle_encoding", "bottom", "gap", "font_family", "secondary_font_family", "font_stretch", "secondary_font_stretch", "font_weight", "secondary_font_weight", "font_bold", "secondary_bold", "font_italic", "secondary_italic", "primary_color", "secondary_color", "subtitle_background", "subtitle_opacity", "subtitle_stroke", "subtitle_stroke_width", "subtitle_safe_margin", "subtitle_horizontal", "subtitle_vertical", "subtitle_anchor", "bitmap_scale", "secondary_bitmap_scale", "auto_copy", "auto_pause", "pause_on_lookup", "search_url", "search_urls", "accent", "background"],
            "Translation": ["provider", "source", "target", "endpoint", "model", "api_key", "azure_region", "translation_track", "context_lines", "translation_prompt"],
            "Speech & OCR": ["asr_engine", "asr_model", "whisper_cli", "whisper_model", "asr_chunk_seconds", "asr_device", "asr_compute", "asr_threads", "asr_beam_size", "asr_translate", "asr_gpu", "asr_track", "ocr_engine", "ocr_language"],
            "Downloads": ["opensubtitles_key", "opensubtitles_token"],
            "Playback": ["online_quality", "audio_device", "audio_languages", "default_volume", "video_aspect", "custom_aspect", "audio_delay", "video_acceleration", "always_on_top"],
        }
        labels = {"audio_languages": "Preferred audio languages (comma-separated codes)", "default_volume": "Startup volume (%)", "custom_aspect": "Custom aspect ratio (width:height)", "asr_device": "faster-whisper device", "asr_gpu": "whisper.cpp GPU acceleration", "asr_translate": "Translate speech into English", "subtitle_vertical": "Vertical position (%)", "subtitle_horizontal": "Horizontal position (%)", "subtitle_anchor": "Vertical alignment", "search_urls": "Additional searches (JSON)", "bottom": "Bottom margin", "gap": "Subtitle spacing", "auto_copy": "Copy current subtitle automatically",
                  "auto_pause": "Pause at subtitle end", "search_url": "Word search URL ({word})", "source": "Source language (auto or code)",
                  "target": "Target language code", "endpoint": "API base URL", "whisper_model": "whisper.cpp model path",
                  "asr_model": "faster-whisper model", "secondary_size": "Secondary font size", "font_size": "Primary font size"}
        for group, keys in groups.items():
            page = QWidget()
            form = QFormLayout(page)
            form.setContentsMargins(18, 12, 18, 16)
            form.setVerticalSpacing(8)
            title = QLabel(group)
            title.setObjectName("Heading")
            form.addRow(title)
            for key in keys:
                value = settings.data[key]
                choices = {"video_aspect": ["Auto", "Stretch", "16:9", "4:3", "1:1", "21:9", "Custom"], "online_quality": ["Compatible", "Highest"], "asr_device": ["auto", "cpu", "cuda"], "asr_compute": ["default", "int8", "float16", "float32"],
                           "ocr_engine": ["Auto", "Tesseract", "Apple Vision"], "subtitle_anchor": ["Top", "Center", "Bottom"], "asr_track": ["Primary", "Secondary"], "translation_track": ["Primary", "Secondary"]}
                if key == 'audio_device':
                    field = QComboBox()
                    field.addItem('System default', '')
                    for device in QMediaDevices.audioOutputs():
                        field.addItem(device.description(), bytes(device.id()).hex())
                    index = field.findData(value)
                    field.setCurrentIndex(max(0, index))
                elif key in choices:
                    field = QComboBox()
                    field.addItems(choices[key])
                    field.setCurrentText(value)
                elif key in ("provider", "asr_engine"):
                    field = QComboBox()
                    field.addItems(["Google", "Bing", "DeepL", "DeepLX", "Azure", "Ollama", "OpenAI", "LM Studio", "KoboldCpp", "Claude", "LiteLLM", "OpenAI compatible"]
                                   if key == "provider" else ["faster-whisper", "whisper.cpp"])
                    field.setCurrentText(value)
                elif isinstance(value, bool):
                    field = QCheckBox()
                    field.setChecked(value)
                elif isinstance(value, int):
                    field = QSpinBox()
                    low, high = {"default_volume": (0, 100), "asr_chunk_seconds": (2, 120), "asr_threads": (1, 64), "asr_beam_size": (1, 20), "context_lines": (0, 100),
                                 "subtitle_opacity": (0, 100), "subtitle_stroke_width": (0, 12), "subtitle_safe_margin": (0, 40), "font_weight": (0, 900), "secondary_font_weight": (0, 900), "font_stretch": (50, 200), "secondary_font_stretch": (50, 200), "subtitle_horizontal": (0, 100), "subtitle_vertical": (-25, 150),
                                 "audio_delay": (-10000, 10000), "bitmap_scale": (10, 300), "secondary_bitmap_scale": (10, 300)}.get(key, (0 if key in ("bottom", "gap") else 8, 200))
                    field.setRange(low, high)
                    field.setValue(value)
                else:
                    field = QLineEdit(str(value))
                    if "key" in key or "token" in key:
                        field.setEchoMode(QLineEdit.EchoMode.Password)
                self.fields[key] = field
                form.addRow(labels.get(key, key.replace("_", " ").capitalize()), field)
            if group == "Downloads":
                login = ui.Button("Sign in to OpenSubtitles…")
                login.clicked.connect(self.login_opensubtitles)
                form.addRow(login)
            if group == "Translation":
                note = QLabel("Google needs no key. For other providers, set the base URL, model and key as needed.\nLocal models receive the preceding subtitles as context.")
                note.setWordWrap(True)
                form.addRow(note)
            if group == "Speech & OCR":
                note = QLabel("faster-whisper downloads the selected model on first use.\nThe app includes native speech and OCR tools. Choose a model before generating subtitles.")
                note.setWordWrap(True)
                form.addRow(note)
                download = ui.Button("Download Whisper model…")
                download.clicked.connect(self.download_model)
                form.addRow(download)
                ocr_download = ui.Button("Download OCR language…")
                ocr_download.clicked.connect(self.download_ocr_language)
                form.addRow(ocr_download)
            scroll_page = QScrollArea()
            scroll_page.setWidgetResizable(True)
            scroll_page.setWidget(page)
            add_page(scroll_page, group)
        self.fields["provider"].currentTextChanged.connect(self.change_provider)
        page = QWidget()
        form = QFormLayout(page)
        self.bindings = {}
        for action, defaults in DEFAULT_SHORTCUTS.items():
            field = QLineEdit("; ".join(settings.data["shortcuts"].get(action, defaults)))
            self.bindings[action] = field
            form.addRow(action, field)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(page)
        add_page(scroll, "Shortcuts")
        sections.setCurrentRow(0)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.commit)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def change_provider(self, provider):
        keys = ('endpoint', 'model', 'api_key', 'azure_region')
        self._profiles[self._provider] = {key: self.fields[key].text() for key in keys}
        defaults = {'Google': {}, 'Bing': {}, 'DeepL': {'endpoint': 'https://api-free.deepl.com'},
                    'Ollama': {'endpoint': 'http://localhost:11434', 'model': 'llama3.2'},
                    'OpenAI': {'endpoint': 'https://api.openai.com/v1'},
                    'LM Studio': {'endpoint': 'http://localhost:1234/v1'},
                    'LiteLLM': {'endpoint': 'http://localhost:4000/v1'}}
        values = self._profiles.get(provider, defaults.get(provider, {}))
        for key in keys:
            self.fields[key].setText(values.get(key, ''))
        self._provider = provider

    def download_model(self):
        name, ok = QInputDialog.getItem(self, "Download Whisper model", "Model", ["tiny", "base", "small", "medium", "large-v3", "tiny.en", "base.en", "small.en", "medium.en"], 0, False)
        if not ok:
            return
        folder = QFileDialog.getExistingDirectory(self, "Choose model folder")
        if not folder:
            return
        engine = self.fields["asr_engine"].currentText()
        self.owner.statusBar().showMessage("Downloading " + name + " model…")
        owner = self.owner
        def done(path):
            from shiboken6 import isValid
            if isValid(self):
                self.fields["asr_model" if engine == "faster-whisper" else "whisper_model"].setText(path)
                QMessageBox.information(self, "Model ready", "The model is ready. Save settings to use it.")
            owner.statusBar().showMessage("Model downloaded")
        owner.task(lambda: services.download_model(engine, name, folder), done)

    def login_opensubtitles(self):
        if not self.fields['opensubtitles_key'].text():
            QMessageBox.information(self, 'OpenSubtitles', 'Enter your OpenSubtitles API key first.')
            return
        username, ok = QInputDialog.getText(self, 'OpenSubtitles', 'Username')
        if not ok:
            return
        password, ok = QInputDialog.getText(self, 'OpenSubtitles', 'Password', QLineEdit.EchoMode.Password)
        if not ok:
            return
        provider = services.OpenSubtitles(dict(self.settings.data, opensubtitles_key=self.fields['opensubtitles_key'].text()))
        owner = self.owner
        def signed_in(token):
            from shiboken6 import isValid
            if isValid(self):
                self.account_base = provider.base
                self.fields['opensubtitles_token'].setText(token)
                owner.statusBar().showMessage('Signed in. Save settings to keep this session.')
        owner.task(lambda: provider.login(username, password), signed_in)

    def download_ocr_language(self):
        language, ok = QInputDialog.getText(self, "Download OCR language", "Tesseract language code", text=self.fields["ocr_language"].text())
        if ok and language:
            owner = self.owner
            owner.statusBar().showMessage("Downloading OCR language…")
            owner.task(lambda: services.download_ocr_language(language), lambda _path: owner.statusBar().showMessage("OCR language ready"))

    def commit(self):
        try:
            left, right = (float(value) for value in self.fields['custom_aspect'].text().split(':'))
            if not 0.05 <= left / right <= 20:
                raise ValueError('Use a valid aspect ratio, such as 16:9.')
            searches = json.loads(self.fields["search_urls"].text())
            if not isinstance(searches, dict) or any(not isinstance(v, str) or not v.startswith(("https://", "http://")) or "{word}" not in v for v in searches.values()):
                raise ValueError("Each search needs an HTTP URL containing {word}.")
        except (ValueError, TypeError, ZeroDivisionError) as error:
            QMessageBox.warning(self, "Search settings", str(error))
            return
        if not self.languages.save(self.settings):
            QMessageBox.warning(self, "Languages", "Choose two different languages.")
            return
        for key, field in self.fields.items():
            if isinstance(field, QComboBox):
                value = field.currentData() if key == 'audio_device' else field.currentText()
            elif isinstance(field, QCheckBox):
                value = field.isChecked()
            elif isinstance(field, QSpinBox):
                value = field.value()
            else:
                value = field.text().strip()
            self.settings.data[key] = value
        self._profiles[self._provider] = {key: self.fields[key].text() for key in ("endpoint", "model", "api_key", "azure_region")}
        self.settings.data["opensubtitles_base"] = self.account_base
        self.settings.data["provider_profiles"] = self._profiles
        self.settings.data["shortcuts"] = {name: [key.strip() for key in field.text().split(";") if key.strip()]
                                           for name, field in self.bindings.items()}
        self.settings.save()
        self.accept()


class Window(QMainWindow):
    def __init__(self, settings=None):
        super().__init__()
        location = Path(QStandardPaths.writableLocation(QStandardPaths.StandardLocation.AppConfigLocation))
        self.settings = settings or Settings(location / "settings.json")
        self.setWindowTitle("LIDS Player")
        ui.install(QApplication.instance())
        self.unified_header = sys.platform == "darwin" and hasattr(Qt.WindowType, "ExpandedClientAreaHint")
        if self.unified_header:
            self.setWindowFlag(Qt.WindowType.ExpandedClientAreaHint)
            self.setWindowFlag(Qt.WindowType.NoTitleBarBackgroundHint)
        self.setAttribute(Qt.WidgetAttribute.WA_ContentsMarginsRespectsSafeArea, False)
        self.resize(1280, 760)
        self.setAcceptDrops(True)
        self.pool = QThreadPool(self)
        self.pool.setMaxThreadCount(4)
        self.jobs = set()
        self._closing = False
        self.generation = 0
        self.track_generation = [0, 0]
        self.discovery_revisions = self.track_generation.copy()
        self.tracks_discovered = False
        self.timelines = [Timeline(), Timeline()]
        self.source = ""
        self.original_source = ""
        self.media_proxy = None
        self.url_request = 0
        self.media_path = ""
        self.tracks = []
        self.translation_enabled = False
        self.fallback_active = False
        self.translation_run = 0
        self.translating = set()
        self.translated_cues = set()
        self.asr_enabled = False
        self.asr_busy = False
        self.asr_cancel = threading.Event()
        self.asr_run = 0
        self.asr_ranges = set()
        self.ocr_pending = set()
        self.ocr_processed = set()
        self.read_cancels = [threading.Event(), threading.Event()]
        self.hidden_subtitles = [False, False]
        self.extra_windows = []
        self.show_original = self.settings.data["sidebar_original"]
        self.lookup_dialog = None
        self.subtitle_sources = [None, None]
        self.read_completed = [True, True]
        self.asr_active_start = None
        self.last_position = 0
        self.slice_cancels = [threading.Event(), threading.Event()]
        self._last_markup = [None, None]
        self._rotation = 0
        self._zoom = 1.0
        self._render_fps = 24
        self.last_primary = ""
        self.last_cues = []
        self.loop_cue = None
        self.actions = []
        self.player = QMediaPlayer(self)
        self.audio = QAudioOutput(self)
        self.audio.setVolume(self.settings.data["default_volume"] / 100)
        self.media_devices = QMediaDevices(self)
        self.media_devices.audioOutputsChanged.connect(self.apply_audio_device)
        self.player.setAudioOutput(self.audio)
        self.video = VideoCanvas()
        self.video.setMinimumSize(300, 160)
        self.player.setVideoOutput(self.video.video_item)
        self.player.positionChanged.connect(self.position_changed)
        self.player.durationChanged.connect(lambda value: self.seek.setRange(0, value))
        self.player.playbackStateChanged.connect(self.state_changed)
        self.player.errorOccurred.connect(lambda _error, text: self.statusBar().showMessage(text))
        self.player.tracksChanged.connect(self.refresh_audio)
        self.build_ui()
        self.playback = PlaybackTools(self)
        self.install_actions()
        self.video.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.video.customContextMenuRequested.connect(self.media_menu)
        self.apply_theme()
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, self.settings.data["always_on_top"])
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.tick)
        self.timer.start(200)

    def showEvent(self, event):
        super().showEvent(event)
        if self.unified_header:
            ui.hide_macos_title(self)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if not hasattr(self, "sidebar"):
            return
        narrow = event.size().width() < 790
        orientation = Qt.Orientation.Vertical if narrow else Qt.Orientation.Horizontal
        if self.splitter.orientation() != orientation:
            self.close_transcript.setVisible(not narrow)
            header = self.transcript_header
            header.setDirection(QVBoxLayout.Direction.LeftToRight if narrow else QVBoxLayout.Direction.TopToBottom)
            margins = (14, 5, 14, 5) if narrow else (18, 18, 18, 12)
            header.setContentsMargins(*margins)
            header.setStretch(1, int(narrow))
            self.splitter.setOrientation(orientation)
            extent = event.size().height() if narrow else event.size().width()
            panel = min(195 if narrow else 324, extent // 3)
            self.splitter.setSizes([extent - panel, panel])

    def button(self, text, callback, layout):
        button = ui.Button(text, callback)
        layout.addWidget(button)
        return button

    def build_ui(self):
        root = QWidget()
        root.setAttribute(Qt.WidgetAttribute.WA_ContentsMarginsRespectsSafeArea, False)
        self.setCentralWidget(root)
        layout = QVBoxLayout(root)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        titlebar = ui.Titlebar()
        titlebar.setObjectName("Titlebar")
        titlebar.setFixedHeight(46)
        top = QHBoxLayout(titlebar)
        top.setSpacing(8)
        top.setContentsMargins(84 if self.unified_header else 16, 0, 14, 0)
        brand = QLabel("LIDS Player")
        brand.setObjectName("Brand")
        top.addWidget(brand)
        divider = QLabel()
        divider.setFixedSize(1, 14)
        divider.setObjectName("Divider")
        top.addWidget(divider)
        self.media_title = QLabel("")
        self.media_title.setObjectName("MediaTitle")
        self.media_title.setTextFormat(Qt.TextFormat.PlainText)
        self.media_title.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        top.addWidget(self.media_title, 1)
        icon_button("folder", "Open media", self.open_file, top)
        icon_button("settings", "Settings", self.open_settings, top)
        self.panel_button = icon_button("panel", "Toggle transcript", lambda: self.sidebar.setVisible(not self.sidebar.isVisible()), top)
        self.panel_button.setCheckable(True)
        self.panel_button.setChecked(True)
        menu_button = icon_button("menu", "Menu", lambda: None, top)
        self.toolbar_menu = QMenu(self)
        menu_button.setMenu(self.toolbar_menu)
        layout.addWidget(titlebar)
        self.splitter = QSplitter()
        self.splitter.setHandleWidth(1)
        self.splitter.setChildrenCollapsible(False)
        layout.addWidget(self.splitter, 1)
        stage = QWidget()
        stage_layout = QVBoxLayout(stage)
        stage_layout.setSpacing(0)
        stage_layout.setContentsMargins(0, 0, 0, 0)
        self.debug_label = QLabel()
        self.debug_label.hide()
        stage_layout.addWidget(self.debug_label)
        self.stage_pages = QStackedWidget()
        stage_layout.addWidget(self.stage_pages, 1)
        welcome = QWidget()
        welcome.setObjectName("Welcome")
        opening = QVBoxLayout(welcome)
        opening.setAlignment(Qt.AlignmentFlag.AlignCenter)
        mark = QLabel()
        mark.setAlignment(Qt.AlignmentFlag.AlignCenter)
        mark.setPixmap(QIcon(str(Path(__file__).parent / "assets/icon.png")).pixmap(64, 64))
        opening.addWidget(mark)
        title = QLabel("Open a video or audio file")
        title.setObjectName("Heading")
        opening.addWidget(title)
        choices = QHBoxLayout()
        opening.addLayout(choices)
        self.button("Open file…", self.open_file, choices).setObjectName("PrimaryAction")
        self.button("Open URL…", self.open_url, choices)
        self.stage_pages.addWidget(welcome)
        self.stage_pages.addWidget(self.video)
        self.subtitle_box = QWidget()
        subtitles_layout = QVBoxLayout(self.subtitle_box)
        self.labels = []
        self.bitmap_labels = []
        for slot in range(2):
            bitmap = QLabel()
            bitmap.setAlignment(Qt.AlignmentFlag.AlignCenter)
            bitmap.hide()
            subtitles_layout.addWidget(bitmap)
            self.bitmap_labels.append(bitmap)
            label = SubtitleLabel()
            label.wordClicked.connect(lambda text, s=slot: self.lookup(text, s))
            label.setTextFormat(Qt.TextFormat.PlainText)
            label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            label.setWordWrap(True)
            label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            label.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
            label.customContextMenuRequested.connect(lambda pos, s=slot: self.word_menu(s, pos))
            subtitles_layout.addWidget(label, 0, Qt.AlignmentFlag.AlignHCenter)
            self.labels.append(label)
        subtitles_layout.insertWidget(0, self.labels[1], 0, Qt.AlignmentFlag.AlignHCenter)
        subtitles_layout.insertWidget(0, self.bitmap_labels[1])
        self.video.set_subtitles(self.subtitle_box)
        self.splitter.addWidget(stage)
        self.sidebar = QWidget()
        sidebar_layout = QVBoxLayout(self.sidebar)
        self.sidebar.setObjectName("Transcript")
        sidebar_layout.setContentsMargins(0, 0, 0, 0)
        sidebar_layout.setSpacing(0)
        head = QWidget()
        head.setObjectName("TranscriptHead")
        self.transcript_header = QVBoxLayout(head)
        head_layout = self.transcript_header
        head_layout.setContentsMargins(18, 18, 18, 12)
        head_layout.setSpacing(14)
        sidebar_layout.addWidget(head)
        heading_row = QHBoxLayout()
        head_layout.addLayout(heading_row)
        heading = QLabel("Transcript")
        heading.setObjectName("Heading")
        heading_row.addWidget(heading, 1)
        self.close_transcript = icon_button("close", "Close transcript", self.panel_button.click, heading_row)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search dialogue")
        self.search.textChanged.connect(self.refresh_sidebar)
        self.search.setClearButtonEnabled(True)
        self.search.setAccessibleName("Search dialogue")
        self.search.addAction(ui.glyph("search"), QLineEdit.ActionPosition.LeadingPosition)
        self.search.setFixedHeight(38)
        head_layout.addWidget(self.search)
        self.sidebar_slot = QComboBox()
        self.sidebar_slot.addItems(["Primary subtitles", "Secondary subtitles", "Both languages"])
        self.sidebar_slot.currentIndexChanged.connect(self.refresh_sidebar)
        self.sidebar_slot.currentIndexChanged.connect(lambda value: self.settings.data.__setitem__("sidebar_track", value))
        self.sidebar_slot.setObjectName("TrackFilter")
        head_layout.addWidget(self.sidebar_slot)
        self.follow_transcript = True
        self.cue_list = TranscriptList()
        self.transcript_model = TranscriptModel(self.cue_list)
        self.cue_list.setModel(self.transcript_model)
        self.cue_list.setLayoutMode(TranscriptList.LayoutMode.Batched)
        self.cue_list.setBatchSize(48)
        self.transcript_delegate = TranscriptDelegate(self.cue_list)
        self.transcript_delegate.wordClicked.connect(self.lookup)
        self.cue_list.setItemDelegate(self.transcript_delegate)
        self.cue_list.setVerticalScrollMode(QListWidget.ScrollMode.ScrollPerPixel)
        self.cue_list.clicked.connect(self.seek_item)
        self.cue_list.activated.connect(self.seek_item)
        self.cue_list.setAccessibleName("Transcript lines")
        self.cue_list.setToolTip("Click a time to seek or a word to look it up.")
        self.cue_list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.cue_list.customContextMenuRequested.connect(self.sidebar_menu)
        self.transcript_empty = QLabel()
        self.transcript_empty.setWordWrap(True)
        self.transcript_empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.transcript_empty.setObjectName("Muted")
        sidebar_layout.addWidget(self.transcript_empty, 1)
        sidebar_layout.addWidget(self.cue_list, 1)
        self.back_to_line = self.button("Back to current line", lambda: self.set_transcript_follow(True), sidebar_layout)
        self.back_to_line.hide()
        self.cue_list.browsing.connect(lambda: self.set_transcript_follow(False))
        self.cue_list.verticalScrollBar().sliderPressed.connect(lambda: self.set_transcript_follow(False))
        self.sidebar_slot.setCurrentIndex(self.settings.data["sidebar_track"])
        self.splitter.addWidget(self.sidebar)
        self.splitter.setSizes([947, 332])
        self.controls = QWidget()
        self.controls.setObjectName("Controls")
        self.controls.setFixedHeight(94)
        controls = QVBoxLayout(self.controls)
        controls.setContentsMargins(24, 12, 24, 14)
        controls.setSpacing(7)
        stage_layout.addWidget(self.controls)
        timeline = QHBoxLayout()
        timeline.setSpacing(12)
        self.time = QLabel("0:00")
        self.time.setObjectName("Clock")
        timeline.addWidget(self.time)
        self.seek = QSlider(Qt.Orientation.Horizontal)
        self.seek.setAccessibleName("Playback position")
        self.seek.actionTriggered.connect(lambda _: self.player.setPosition(self.seek.sliderPosition()))
        timeline.addWidget(self.seek, 1)
        self.end_time = QLabel("0:00")
        self.end_time.setObjectName("Clock")
        timeline.addWidget(self.end_time)
        controls.addLayout(timeline)
        deck = ui.QGridLayout()
        deck.setContentsMargins(0, 0, 0, 0)
        controls.addLayout(deck)
        deck.setColumnStretch(0, 1)
        deck.setColumnStretch(2, 1)
        left = QHBoxLayout()
        deck.addLayout(left, 0, 0, Qt.AlignmentFlag.AlignLeft)
        speaker = icon_button("sound", "Volume", None, left)
        volume_menu = QMenu(speaker)
        mute = volume_menu.addAction("Mute")
        mute.setCheckable(True)
        mute.toggled.connect(self.audio.setMuted)
        self.audio.mutedChanged.connect(mute.setChecked)
        self.volume = QSlider(Qt.Orientation.Horizontal)
        self.volume.setAccessibleName("Volume")
        self.volume.setRange(0, 100)
        self.volume.setValue(self.settings.data["default_volume"])
        self.volume.setFixedWidth(130)
        self.volume.valueChanged.connect(lambda value: self.audio.setVolume(value / 100))
        slider_action = ui.QWidgetAction(volume_menu)
        slider_action.setDefaultWidget(self.volume)
        volume_menu.addAction(slider_action)
        speaker.setMenu(volume_menu)
        self.speed = ui.Button("1×", kind="quiet")
        self.speed.setAccessibleName("Playback speed")
        rates = QMenu(self.speed)
        for rate in (0.5, 0.75, 1, 1.25, 1.5, 2):
            action = rates.addAction(f"{rate:g}×")
            action.setCheckable(True)
            action.triggered.connect(lambda checked=False, r=rate: self.player.setPlaybackRate(r))
        def mark_current_rate():
            for action in rates.actions():
                action.setChecked(action.text() == self.speed.text())
        rates.aboutToShow.connect(mark_current_rate)
        self.speed.setMenu(rates)
        self.player.playbackRateChanged.connect(lambda rate: self.speed.setText(f"{rate:g}×"))
        left.addWidget(self.speed)
        middle = QHBoxLayout()
        middle.setSpacing(10)
        deck.addLayout(middle, 0, 1)
        icon_button("prev", "Previous line", lambda: self.subtitle_seek(-1, self.study_slot()), middle)
        self.play_button = icon_button("play", "Play", self.toggle_play, middle)
        self.play_button.setFixedSize(42, 42)
        icon_button("next", "Next line", lambda: self.subtitle_seek(1, self.study_slot()), middle)
        row = QHBoxLayout()
        deck.addLayout(row, 0, 2, Qt.AlignmentFlag.AlignRight)
        foot = QWidget()
        foot.setObjectName("TranscriptFoot")
        foot.setFixedHeight(50)
        foot_layout = QHBoxLayout(foot)
        foot_layout.setContentsMargins(16, 8, 16, 8)
        self.loop = ui.Button("Repeat line", kind="quiet", symbol="repeat")
        self.loop.setCheckable(True)
        self.loop.toggled.connect(self.set_loop)
        foot_layout.addWidget(self.loop)
        foot_layout.addStretch()
        sidebar_layout.addWidget(foot)
        self.track_dialog = QDialog(self)
        self.track_dialog.setWindowTitle("Subtitles")
        self.track_dialog.setWindowModality(Qt.WindowModality.WindowModal)
        self.track_dialog.resize(400, 210)
        track_layout = QVBoxLayout(self.track_dialog)
        track_layout.setContentsMargins(18, 14, 18, 18)
        track_layout.setSpacing(9)
        ui.dialog_header(self.track_dialog, "Subtitles", track_layout)
        self.track_headings = {}
        self.track_sources = {}
        self.change_buttons = {}
        subtitles = self.button("Subtitles", self.track_dialog.show, row)
        subtitles.setProperty("variant", "quiet")
        subtitles.setIcon(QIcon(str(Path(__file__).parent / "assets/subs.svg")))
        icon_button("full", "Fullscreen", self.fullscreen, row)
        self.timing_dialog = QDialog(self.track_dialog)
        self.timing_dialog.setWindowTitle("Subtitle timing")
        self.timing_dialog.setWindowModality(Qt.WindowModality.WindowModal)
        timing_layout = QVBoxLayout(self.timing_dialog)
        ui.dialog_header(self.timing_dialog, "Subtitle timing", timing_layout)
        timing_form = QFormLayout()
        timing_layout.addLayout(timing_form)
        self.timing_labels = []
        self.track_boxes = []
        self.offset_boxes = []
        for slot in range(2):
            combo = QComboBox(self.track_dialog)
            combo.hide()
            combo.addItem("Off", None)
            combo.currentIndexChanged.connect(lambda _, s=slot: self.update_track_source(s))
            combo.activated.connect(lambda index, s=slot: self.select_track(s, index))
            self.track_boxes.append(combo)
            label = QLabel()
            offset = QSpinBox()
            offset.setRange(-600000, 600000)
            offset.setSingleStep(100)
            offset.setSuffix(" ms")
            offset.valueChanged.connect(lambda value, s=slot: self.set_offset(s, value))
            timing_form.addRow(label, offset)
            self.timing_labels.append(label)
            self.offset_boxes.append(offset)

        for slot in (1, 0):
            track_row = QHBoxLayout()
            track_layout.addLayout(track_row)
            description = QVBoxLayout()
            track_row.addLayout(description, 1)
            heading = QLabel()
            heading.setObjectName("SectionTitle")
            source = QLabel()
            source.setObjectName("Muted")
            source.setWordWrap(True)
            source.setTextFormat(Qt.TextFormat.PlainText)
            description.addWidget(heading)
            description.addWidget(source)
            self.track_headings[slot] = heading
            self.track_sources[slot] = source
            change = ui.Button("Change…")
            menu = QMenu(change)
            menu.aboutToShow.connect(lambda s=slot, m=menu: self.populate_source_menu(s, m))
            change.setMenu(menu)
            track_row.addWidget(change)
            self.change_buttons[slot] = change

        self.asr = QCheckBox(self.track_dialog)
        self.asr.toggled.connect(self.toggle_asr)
        self.asr.hide()
        self.translate = QCheckBox(self.track_dialog)
        self.translate.toggled.connect(self.toggle_translation)
        self.translate.hide()
        self.live_ocr = QCheckBox(self.track_dialog)
        self.live_ocr.setChecked(True)
        self.live_ocr.hide()
        self.audio_tracks = QComboBox(self.track_dialog)
        self.audio_tracks.hide()

        footer = QHBoxLayout()
        track_layout.addLayout(footer)
        footer.addStretch()
        more = ui.Button("More", kind="quiet")
        more_menu = QMenu(more)
        more_menu.aboutToShow.connect(lambda: self.populate_more_menu(more_menu))
        more.setMenu(more_menu)
        footer.addWidget(more)
        self.update_language_labels()
        self.refresh_sidebar()
        self.controls.setEnabled(False)
        self.statusBar().setSizeGripEnabled(False)
        self.statusBar().hide()
        self.statusBar().messageChanged.connect(lambda text: self.statusBar().setVisible(bool(text)))

    def language_code(self, slot):
        return self.settings.data[("primary_language", "secondary_language")[slot]]

    def update_language_labels(self):
        for slot in range(2):
            name = language_name(self.language_code(slot))
            self.track_headings[slot].setText(name)
            self.change_buttons[slot].setAccessibleName(f"Change {name} subtitles")
            self.timing_labels[slot].setText(name)
            self.offset_boxes[slot].setAccessibleName(f"{name} subtitle delay")
            self.sidebar_slot.setItemText(slot, name)
            self.update_track_source(slot)
        self.sidebar_slot.setItemText(2, f"{language_name(self.language_code(1))} · {language_name(self.language_code(0))}")

    def update_track_source(self, slot):
        combo = self.track_boxes[slot]
        source = combo.currentData()
        if isinstance(source, int):
            label = "Included in movie"
            if combo.currentText() != language_name(self.language_code(slot)):
                label += " · " + combo.currentText()
        else:
            label = combo.currentText() or "Off"
        self.track_sources[slot].setText(label)

    def choose_source(self, slot, index):
        self.track_boxes[slot].setCurrentIndex(index)
        self.select_track(slot, index)

    def populate_source_menu(self, slot, menu):
        menu.clear()
        combo = self.track_boxes[slot]
        for index in range(1, combo.count()):
            data = combo.itemData(index)
            if isinstance(data, tuple) and data[0] in ("speech", "translation"):
                continue
            action = menu.addAction(combo.itemText(index))
            action.setCheckable(True)
            action.setChecked(index == combo.currentIndex())
            action.triggered.connect(lambda _, i=index: self.choose_source(slot, i))
        menu.addSeparator()
        menu.addAction("Find subtitles…", lambda: self.download_subtitles(slot))
        menu.addAction("Load file…", lambda: self.open_subtitles(slot))
        menu.addSeparator()
        for kind, label in (("speech", "Generate from speech"),
                            ("translation", "Translate from " + language_name(self.language_code(1-slot)))):
            action = menu.addAction(label)
            action.setCheckable(True)
            action.setChecked(combo.currentData() == (kind, slot))
            action.setEnabled(bool(self.source) if kind == "speech" else self.track_boxes[1-slot].currentIndex() > 0)
            action.triggered.connect(lambda _, k=kind, text=label: self.choose_generated_source(slot, k, text))
        menu.addSeparator()
        menu.addAction("Off", lambda: self.choose_source(slot, 0))

    def choose_generated_source(self, slot, kind, label):
        if (kind == "translation" and self.translate.isChecked() and slot != self.translation_slot()
                or kind == "speech" and self.asr.isChecked() and slot == self.asr_slot()):
            return
        self.show_generated_source(slot, kind, label)
        self.choose_source(slot, self.track_boxes[slot].currentIndex())

    def populate_more_menu(self, menu):
        menu.clear()
        menu.addAction("Adjust timing…", self.timing_dialog.show)
        exports = menu.addMenu("Export subtitles")
        for slot in (1, 0):
            action = exports.addAction(language_name(self.language_code(slot)))
            action.setEnabled(bool(self.timelines[slot].cues))
            action.triggered.connect(lambda _, s=slot: self.export_track(s))
        if self.audio_tracks.count() > 1:
            audio = menu.addMenu("Audio track")
            for i in range(self.audio_tracks.count()):
                action = audio.addAction(self.audio_tracks.itemText(i))
                action.setCheckable(True)
                action.setChecked(i == self.audio_tracks.currentIndex())
                action.triggered.connect(lambda _, index=i: self.choose_audio(index))

    def setup_languages(self):
        if not self.settings.data["languages_chosen"]:
            if not LanguageSetup(self.settings, self).exec():
                return False
            self.sidebar_slot.setCurrentIndex(2)
            self.update_language_labels()
        return True

    def study_slot(self):
        return 1 if self.timelines[1].cues else 0

    def apply_theme(self):
        s = self.settings.data
        from PySide6.QtGui import QColor
        background = s["background"] if QColor(s["background"]).isValid() else "#17191f"
        accent = s["accent"] if QColor(s["accent"]).isValid() else "#8cb8ff"
        self.setStyleSheet(ui.stylesheet(background, accent))
        for i, label in enumerate(self.labels):
            size = s['font_size'] if i == 0 else s['secondary_size']
            family = s['font_family'] if i == 0 else s['secondary_font_family']
            font = QFont(family or QApplication.font().family())
            font.setPixelSize(size)
            font.setBold(s['font_bold'] if i == 0 else s['secondary_bold'])
            font.setItalic(s['font_italic'] if i == 0 else s['secondary_italic'])
            font.setStretch(s['font_stretch'] if i == 0 else s['secondary_font_stretch'])
            weight = s['font_weight'] if i == 0 else s['secondary_font_weight']
            if weight:
                font.setWeight(QFont.Weight(weight))
            label.setFont(font)
            label.document().setDefaultFont(font)
            color = s['primary_color'] if i == 0 else s['secondary_color']
            bg = QColor(s['subtitle_background'])
            weight_css = font.weight()
            label.setStyleSheet(f"font-weight: {int(weight_css)}; font-size: {size}px; color: {color}; padding: 3px; background: rgba({bg.red()}, {bg.green()}, {bg.blue()}, {round(s['subtitle_opacity'] * 2.55)}); border-radius: 4px;")
            label.setOutline(s["subtitle_stroke"], s["subtitle_stroke_width"])
            label.update_height()
        self.video.aspect = s["video_aspect"]
        self.video.custom_aspect = s["custom_aspect"]
        self.apply_audio_device()
        self.video.safe_margin = s["subtitle_safe_margin"]
        self.video.placement = (s['subtitle_horizontal'], s['subtitle_vertical'], s['subtitle_anchor'])
        self.subtitle_box.layout().setSpacing(s["gap"])
        self.subtitle_box.layout().setContentsMargins(16, 8, 16, s["bottom"])
        self.subtitle_box.setStyleSheet("background: transparent;")
        self.video.arrange()
        if hasattr(self, "playback"):
            self.playback.set_audio_delay(s["audio_delay"])
        if bool(self.windowFlags() & Qt.WindowType.WindowStaysOnTopHint) != s['always_on_top']:
            visible = self.isVisible()
            self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, s['always_on_top'])
            if visible:
                self.show()

    def task(self, function, done, generation=None, failed=None, progress=None):
        job = Job(function, streaming=progress is not None)
        self.jobs.add(job)
        def finish(value):
            from shiboken6 import isValid
            self.jobs.discard(job)
            if self._closing or not isValid(self):
                return
            if generation is None or generation == self.generation:
                done(value)
        def error(message):
            from shiboken6 import isValid
            self.jobs.discard(job)
            if self._closing or not isValid(self):
                return
            if generation is None or generation == self.generation:
                self.statusBar().showMessage(message, 20000)
                if failed:
                    failed(message)
        if progress:
            job.signals.progress.connect(lambda value: progress(value) if not self._closing and (generation is None or generation == self.generation) else None)
        job.signals.finished.connect(finish)
        job.signals.error.connect(error)
        self.pool.start(job)

    def open_file(self):
        path, _ = QFileDialog.getOpenFileName(self, "Open media")
        if path:
            self.open_media(path)

    def open_url(self):
        url, ok = QInputDialog.getText(self, "Open URL", "Video URL")
        if ok and url:
            self.resolve_url(url)

    def resolve_url(self, url, subtitles=()):
        if url:
            self.statusBar().showMessage("Finding video…")
            generation = self.generation
            self.url_request += 1
            request_id = self.url_request
            def opened(result):
                if request_id != self.url_request:
                    return
                self.open_media(result[0], result[1])
                self.media_path = url
                for slot, path in enumerate(subtitles):
                    if path:
                        self.load_subtitles(path, slot)
            self.task(lambda: services.resolve_url(url, self.settings.data["online_quality"]), opened, generation)

    def open_media(self, source, title=None):
        self.set_transcript_follow(True)
        self.stage_pages.setCurrentWidget(self.video)
        self.controls.setEnabled(True)
        self.cancel_readers()
        self.generation += 1
        self.url_request += 1
        self.original_source = source
        if self.media_proxy:
            self.media_proxy.close()
            self.media_proxy = None
        if getattr(source, 'headers', None):
            self.media_proxy = MediaProxy()
            video = self.media_proxy.url_for(str(source), source.headers)
            audio = self.media_proxy.url_for(source.audio_url, source.headers) if source.audio_url else ''
            source = services.ResolvedURL(video, audio)
        self.source = source
        self.media_path = str(self.original_source)
        self.playback.external_audio = getattr(source, "audio_url", "")
        self.timelines = [Timeline(), Timeline()]
        for offset in self.offset_boxes:
            offset.setValue(0)
        self.track_generation = [value + 1 for value in self.track_generation]
        self.translate.setChecked(False)
        self.asr_ranges.clear()
        self.asr_enabled = False
        self.asr.setChecked(False)
        self.asr_busy = False
        self.translating.clear()
        self.translated_cues.clear()
        self.last_primary = ""
        self.last_cues = []
        self.loop.setChecked(False)
        self.tracks = []
        self.discovery_revisions = self.track_generation.copy()
        self.tracks_discovered = False
        self.live_ocr.setChecked(True)
        self.subtitle_sources = [None, None]
        self.read_completed = [True, True]
        self.ocr_pending.clear()
        self.ocr_processed.clear()
        for combo in self.track_boxes:
            combo.clear()
            combo.addItem("Off", None)
        self.media_title.setText(title or Path(source).name)
        self.media_title.setToolTip(self.media_title.text())
        self.setWindowTitle(self.media_title.text())
        self.player.setSource(QUrl(source) if source.startswith(("http://", "https://")) else QUrl.fromLocalFile(str(Path(source).resolve())))
        self.playback.set_audio_delay(self.settings.data["audio_delay"])
        self.player.play()
        self.refresh_sidebar()
        self.statusBar().clearMessage()
        self.task(lambda: services.subtitle_tracks(source), self.set_tracks, self.generation)
        if not source.startswith(("http://", "https://")):
            for suffix in (".srt", ".ass", ".vtt"):
                sidecar = Path(source).with_suffix(suffix)
                if sidecar.exists():
                    self.load_subtitles(str(sidecar), 0)
                    break

    def set_tracks(self, tracks):
        self.tracks = tracks
        self.tracks_discovered = True
        for slot, combo in enumerate(self.track_boxes):
            chosen = None
            for track in tracks:
                code = track.get("language", "")
                language = QLocale.codeToLanguage(code)
                label = track["title"]
                if language != QLocale.Language.AnyLanguage:
                    name = QLocale.languageToString(language)
                    label = name if label.casefold() in (name.casefold(), code.casefold()) else f"{name} · {label}"
                combo.addItem(label, track["index"])
                if chosen is None and code and language == QLocale.codeToLanguage(self.language_code(slot)):
                    chosen = combo.count() - 1
            if (chosen is not None and self.settings.data["languages_chosen"]
                    and self.track_generation[slot] == self.discovery_revisions[slot]
                    and combo.currentIndex() == 0):
                combo.setCurrentIndex(chosen)
                self.select_track(slot, chosen)
        self.apply_translation_fallback()
        self.statusBar().clearMessage()

    def apply_translation_fallback(self):
        if (self.tracks_discovered and self.settings.data["auto_translate"] and not self.translation_enabled
                and self.track_boxes[0].currentIndex() > 0 and self.track_boxes[1].currentIndex() == 0
                and self.read_completed[1] and self.track_generation[1] == self.discovery_revisions[1]):
            self.settings.data["translation_track"] = "Primary"
            self.translate.setChecked(True)
            self.fallback_active = True

    def apply_audio_device(self):
        wanted = self.settings.data['audio_device']
        devices = QMediaDevices.audioOutputs()
        device = next((device for device in devices if bytes(device.id()).hex() == wanted), QMediaDevices.defaultAudioOutput())
        if self.audio.device().id() != device.id():
            self.audio.setDevice(device)

    def choose_audio(self, index):
        self.audio_tracks.setCurrentIndex(index)
        if self.playback.external_audio:
            self.playback.audio_player.setActiveAudioTrack(index)
        else:
            self.player.setActiveAudioTrack(index)
            if self.playback.audio_delay:
                self.playback.audio_player.setActiveAudioTrack(index)

    def refresh_audio(self):
        self.audio_tracks.clear()
        from PySide6.QtMultimedia import QMediaMetaData
        audio_player = self.playback.audio_player if hasattr(self, "playback") and self.playback.external_audio else self.player
        for i, metadata in enumerate(audio_player.audioTracks()):
            self.audio_tracks.addItem(metadata.stringValue(QMediaMetaData.Key.Title) or f"Audio {i + 1}")
        self.audio_tracks.setCurrentIndex(audio_player.activeAudioTrack())
        if getattr(self, '_audio_preference_source', None) != audio_player.source() and audio_player.audioTracks():
            self._audio_preference_source = audio_player.source()
            preferred = [code.strip().lower() for code in self.settings.data['audio_languages'].split(',') if code.strip()]
            for code in preferred:
                match = next((i for i, meta in enumerate(audio_player.audioTracks()) if meta.stringValue(QMediaMetaData.Key.Language).lower().startswith(code) or (hasattr(meta.value(QMediaMetaData.Key.Language), 'bcp47Name') and meta.value(QMediaMetaData.Key.Language).bcp47Name().lower().startswith(code))), None)
                if match is not None:
                    self.choose_audio(match)
                    self.audio_tracks.setCurrentIndex(match)
                    break
        self.player.setActiveSubtitleTrack(-1)

    def open_subtitles(self, slot):
        path, _ = QFileDialog.getOpenFileName(self.track_dialog if self.track_dialog.isVisible() else self, "Load subtitles", filter="Subtitles (*.srt *.ass *.ssa *.vtt *.sub *.idx *.sup *.mks);;All files (*)")
        if path:
            self.load_subtitles(path, slot)

    def load_subtitles(self, path, slot):
        self.cancel_readers(slot)
        self.subtitle_sources[slot] = None
        if slot == self.asr_slot():
            self.asr.setChecked(False)
        if slot == 1 - self.translation_slot():
            self.translate.setChecked(False)
        self.track_generation[slot] += 1
        revision = self.track_generation[slot]
        self.read_completed[slot] = False
        self.timelines[slot] = Timeline()
        self.reset_dependent_translation(slot)
        def loaded(timeline):
            if revision != self.track_generation[slot]:
                return
            self.read_completed[slot] = True
            timeline.offset = self.offset_boxes[slot].value()
            self.timelines[slot] = timeline
            combo = self.track_boxes[slot]
            combo.addItem(Path(path).name, ("external", path))
            combo.setCurrentIndex(combo.count() - 1)
            if slot == 0:
                self.apply_translation_fallback()
            self.refresh_sidebar()
            self.tick()
        cancel = self.read_cancels[slot]
        from PySide6.QtMultimedia import QMediaMetaData
        fps = self.player.metaData().value(QMediaMetaData.Key.VideoFrameRate) or 25
        encoding = self.settings.data['subtitle_encoding']
        def partial(cue):
            if revision == self.track_generation[slot] and not cancel.is_set():
                if isinstance(cue, tuple):
                    self.subtitle_sources[slot] = cue
                else:
                    self.merge_cue(slot, cue)
        def load(emit):
            bitmap = Path(path).suffix.lower() in (".sup", ".mks", ".idx")
            if Path(path).suffix.lower() == ".sub":
                with open(path, "rb") as stream:
                    bitmap = stream.read(4) == b"\x00\x00\x01\xba"
            if bitmap:
                tracks = services.subtitle_tracks(path)
                emit((path, tracks[0]["index"]))
                return services.extract_subtitles(path, tracks[0]["index"], emit=emit, cancel=cancel)
            return Timeline.load(path, encoding=encoding, fps=float(fps))
        self.task(load, loaded, self.generation, self.track_error_handler(slot, revision), progress=partial)

    def track_error_handler(self, slot, revision):
        def failed(_message):
            if self.track_generation[slot] == revision:
                self.read_completed[slot] = True
                self.subtitle_sources[slot] = None
                self.track_boxes[slot].setCurrentIndex(0)
                self.timelines[slot] = Timeline()
                self.refresh_sidebar()
                self.tick()
        return failed

    def prioritize_subtitles(self, position):
        for slot, source in enumerate(self.subtitle_sources):
            if not source or self.read_completed[slot]:
                continue
            if self.timelines[slot].active(position):
                continue
            self.slice_cancels[slot].set()
            cancel = threading.Event()
            self.slice_cancels[slot] = cancel
            revision = self.track_generation[slot]
            def done(timeline, index=slot, rev=revision, token=cancel):
                if rev == self.track_generation[index] and not token.is_set():
                    for cue in timeline.cues:
                        self.merge_cue(index, cue)
            path, stream = source
            self.task(lambda path=path, stream=stream, token=cancel: services.extract_bitmap_subtitles(path, stream, cancel=token, start=max(0, position / 1000 - 30), duration=60), done, self.generation)

    def merge_cue(self, slot, cue):
        cues = list(self.timelines[slot].cues)
        key = lambda c: (c.start, c.image) if c.image else (c.start, c.text)
        match = next((i for i, c in enumerate(cues) if key(c) == key(cue)), None)
        if match is not None:
            previous = cues[match]
            if cue.image and previous.text and not cue.text:
                cue.text = previous.text
            if cue.end == 2147483647 and previous.end != 2147483647:
                return
            cues[match] = cue
        else:
            cues.append(cue)
        self.timelines[slot] = Timeline(cues)
        self.timelines[slot].offset = self.offset_boxes[slot].value()
        self.refresh_sidebar()


    def select_track(self, slot, index):
        self.cancel_readers(slot)
        self.subtitle_sources[slot] = None
        self.read_completed[slot] = True
        if slot == self.asr_slot():
            self.asr.setChecked(False)
        if slot == 1 - self.translation_slot():
            self.translate.setChecked(False)
        self.timelines[slot] = Timeline()
        self.reset_dependent_translation(slot)
        data = self.track_boxes[slot].itemData(index)
        self.track_generation[slot] += 1
        revision = self.track_generation[slot]
        if data is None:
            self.timelines[slot] = Timeline()
            self.timelines[slot].offset = self.offset_boxes[slot].value()
            self.refresh_sidebar()
            self.tick()
        elif isinstance(data, tuple):
            if data[0] == "translation":
                self.translate.setChecked(False)
                self.settings.data["translation_track"] = ("Secondary", "Primary")[slot]
                self.translate.setChecked(True)
            elif data[0] == "speech":
                self.asr.setChecked(False)
                self.settings.data["asr_track"] = ("Primary", "Secondary")[slot]
                self.asr.setChecked(True)
            elif data[0] == "snapshot":
                self.timelines[slot] = copy.deepcopy(data[1])
                self.refresh_sidebar()
                self.tick()
            else:
                self.load_subtitles(data[1], slot)
        else:
            self.statusBar().showMessage("Reading subtitles…")
            def done(timeline):
                if revision == self.track_generation[slot]:
                    self.read_completed[slot] = True
                    timeline.offset = self.offset_boxes[slot].value()
                    self.timelines[slot] = timeline
                    self.refresh_sidebar()
                    self.tick()
                    if slot == 0:
                        self.apply_translation_fallback()
                    self.statusBar().showMessage(f"Loaded {len(timeline.cues)} subtitles", 2500)
            source = self.source
            self.timelines[slot] = Timeline()
            codec = next((track.get("codec") for track in self.tracks if track["index"] == data), None)
            bitmap = codec in services.BITMAP_CODECS
            self.subtitle_sources[slot] = (source, data) if bitmap else None
            self.read_completed[slot] = False
            cancel = self.read_cancels[slot]
            def partial(cue):
                if revision == self.track_generation[slot] and not cancel.is_set():
                    self.merge_cue(slot, cue)
            if bitmap:
                self.task(lambda emit: services.extract_subtitles(source, data, emit=emit, cancel=cancel),
                          done, self.generation, self.track_error_handler(slot, revision), progress=partial)
            else:
                self.task(lambda: services.extract_subtitles(source, data, cancel=cancel), done, self.generation,
                          self.track_error_handler(slot, revision))

    def set_offset(self, slot, value):
        self.timelines[slot].offset = value
        self.refresh_sidebar()
        self.tick()

    def toggle_play(self):
        if self.playback.reverse:
            if self.playback.reverse_timer.isActive():
                self.playback.reverse_timer.stop()
                self.show_play_state(False)
            else:
                self.playback.reverse_timer.start()
                self.show_play_state(True)
            return
        if self.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
            self.player.pause()
        else:
            self.player.play()

    def state_changed(self, state):
        self.show_play_state(state == QMediaPlayer.PlaybackState.PlayingState)

    def show_play_state(self, playing):
        name = "pause" if playing else "play"
        self.play_button.setIcon(QIcon(str(Path(__file__).parent / "assets" / (name + ".svg"))))
        self.play_button.setAccessibleName(name.title())
        self.play_button.setToolTip(name.title())

    def position_changed(self, position):
        jump = abs(position - self.last_position) > 1500
        if jump:
            self.prioritize_subtitles(position)
            if self.asr_enabled and self.asr_busy and abs(position - self.last_position) > self.settings.data['asr_chunk_seconds'] * 1000:
                self.asr_ranges.discard(self.asr_active_start)
                self.asr_cancel.set()
                self.asr_cancel = threading.Event()
                self.asr_run += 1
                self.asr_busy = False
        self.last_position = position
        if not self.seek.isSliderDown():
            self.seek.setValue(position)
        def clock(value):
            seconds = value // 1000
            return f"{seconds // 3600}:{seconds // 60 % 60:02}:{seconds % 60:02}" if seconds >= 3600 else f"{seconds // 60}:{seconds % 60:02}"
        self.time.setText(clock(position))
        self.end_time.setText(clock(self.player.duration()))
        self.tick()

    def tick(self):
        if self._closing:
            return
        position = self.player.position()
        primary = self.timelines[0].active(position)
        for slot in range(2):
            active = primary if slot == 0 else self.timelines[slot].active(position)
            if self.hidden_subtitles[slot]:
                active = []
            text = "\n".join(c.text for c in active if c.text)
            markup = "<br>".join(c.markup or html.escape(c.text).replace("\n", "<br>") for c in active if c.text)
            if self._last_markup[slot] != (markup, text):
                self._last_markup[slot] = (markup, text)
                if markup:
                    self.labels[slot].setStyledText(markup)
                else:
                    self.labels[slot].setText("")
            images = [c.image for c in active if c.image and not c.text]
            bitmap = self.bitmap_labels[slot]
            if images:
                pixmap = QPixmap()
                pixmap.loadFromData(images[0])
                cue = next(c for c in active if c.image and not c.text)
                canvas = cue.canvas or (960, 540)
                native = self.video.video_item.nativeSize()
                native_width, native_height = native.width() or canvas[0], native.height() or canvas[1]
                ratio = min(self.video.viewport().width() / native_width, self.video.viewport().height() / native_height)
                scale = self.settings.data['bitmap_scale' if slot == 0 else 'secondary_bitmap_scale'] / 100
                width = max(1, round(pixmap.width() * native_width * ratio / canvas[0] * scale))
                height = max(1, round(pixmap.height() * native_height * ratio / canvas[1] * scale))
                bitmap.setPixmap(pixmap.scaled(width, height, Qt.AspectRatioMode.IgnoreAspectRatio, Qt.TransformationMode.SmoothTransformation))
                bitmap.show()
            else:
                bitmap.hide()
        if self.debug_label.isVisible():
            frame = self.video.video_item.videoSink().videoFrame()
            self.debug_label.setText(f"{frame.width()} × {frame.height()}  |  {position} / {self.player.duration()} ms  |  {self.player.playbackRate():g}×  |  ASR: {self.settings.data['asr_engine']}")
        self.video.arrange()
        text = "\n".join(c.text for c in primary)
        if text and text != self.last_primary:
            self.last_primary = text
            if self.settings.data["auto_copy"]:
                QApplication.clipboard().setText(text)
        self.highlight_transcript(position)
        if self.settings.data["auto_pause"] and self.last_cues and not primary and position >= self.last_cues[-1].end + self.timelines[0].offset:
            self.player.pause()
        self.last_cues = primary
        if self.loop_cue and position >= self.loop_cue.end + self.timelines[self.loop_slot].offset:
            self.player.setPosition(self.loop_cue.start + self.timelines[self.loop_slot].offset)
        if self.translation_enabled:
            self.schedule_translation(position)
        if self.live_ocr.isChecked():
            self.schedule_ocr(position)
        if self.asr_enabled and not self.asr_busy:
            self.schedule_asr(position)

    def set_transcript_follow(self, follow):
        self.follow_transcript = follow
        self.back_to_line.setVisible(not follow)
        if follow:
            self.search.clear()
            self.highlight_transcript(self.player.position())
            index = self.cue_list.currentIndex()
            if index.isValid():
                self.cue_list.scrollTo(index)

    def refresh_sidebar(self, *_args):
        scroll = self.cue_list.verticalScrollBar().value()
        selected = self.cue_list.currentIndex()
        selected_time = selected.data(Qt.ItemDataRole.UserRole)[0] if selected.isValid() else None
        current = []
        mode = self.sidebar_slot.currentIndex()
        slots = (1, 0) if mode == 2 else (mode,)
        events = sorted((cue.start + self.timelines[slot].offset, -slot, i, cue)
                        for slot in slots for i, cue in enumerate(self.timelines[slot].cues))
        rows = []
        for start, negative_slot, _, cue in events:
            slot = -negative_slot
            end = cue.end + self.timelines[slot].offset
            if rows and start < rows[-1][1] and slot not in rows[-1][2]:
                rows[-1][1] = max(end, rows[-1][1])
                rows[-1][2][slot] = cue
            else:
                rows.append([start, end, {slot: cue}])
        query = self.search.text().casefold()
        self.transcript_starts = []
        for start, end, cues in rows:
            lines = [(slot, cue.original_text if self.show_original and cue.original_text else cue.text)
                     for slot, cue in sorted(cues.items(), reverse=True)]
            caption = "  ".join(text for _, text in lines)
            if query not in caption.casefold():
                continue
            image = next((c.image for c in cues.values() if c.image and not c.text), None)
            current.append((start, end, lines, image))
            self.transcript_starts.append(start)
        self.transcript_model.replace(current)
        empty = not self.transcript_starts
        self.transcript_empty.setText("No matching lines." if query else "Load subtitles to see the transcript.")
        self.transcript_empty.setVisible(empty)
        self.cue_list.setVisible(not empty)
        if not self.follow_transcript:
            if selected_time in self.transcript_starts:
                self.cue_list.setCurrentIndex(self.transcript_model.index(self.transcript_starts.index(selected_time), 0))
            self.cue_list.verticalScrollBar().setValue(scroll)
        self.highlight_transcript(self.player.position())

    def highlight_transcript(self, position):
        if not self.follow_transcript:
            return
        from bisect import bisect_right
        row = bisect_right(getattr(self, "transcript_starts", []), position) - 1
        if row >= 0 and position >= self.transcript_model.rows[row][1]:
            row = -1
        index = self.transcript_model.index(row, 0)
        if index != self.cue_list.currentIndex():
            self.cue_list.setCurrentIndex(index)
        if index.isValid() and self.cue_list.isVisible() and not self.cue_list.viewport().rect().intersects(self.cue_list.visualRect(index)):
            self.cue_list.scrollTo(index, self.cue_list.ScrollHint.PositionAtCenter)

    def seek_item(self, item):
        self.player.setPosition(max(0, item.data(Qt.ItemDataRole.UserRole)[0]))

    def subtitle_seek(self, direction, slot=0):
        value = self.timelines[slot].adjacent(self.player.position(), direction)
        if value is not None:
            self.player.setPosition(max(0, value))

    def set_loop(self, enabled):
        self.loop_slot = self.study_slot()
        active = self.timelines[self.loop_slot].active(self.player.position())
        self.loop_cue = active[0] if enabled and active else None

    def copy_subtitles(self):
        QApplication.clipboard().setText("\n".join(label.text() for label in self.labels))

    def word_menu(self, slot, pos):
        label = self.labels[slot]
        text = label.selectedText() or label.text()
        self.show_word_menu(text, label.mapToGlobal(pos), slot)

    def sidebar_menu(self, pos):
        item = self.cue_list.indexAt(pos)
        if not item.isValid():
            item = self.cue_list.currentIndex()
        if not item.isValid():
            return
        from .native_tools import tokenize
        menu = QMenu(self.cue_list)
        menu.addAction("Go to line", lambda: self.seek_item(item))
        for slot, text in item.data(TranscriptDelegate.lines_role):
            if not text:
                continue
            group = menu.addMenu(language_name(self.language_code(slot)))
            words = group.addMenu("Look up a word")
            for word in dict.fromkeys(token["text"] for token in tokenize(text)):
                if any(char.isalnum() for char in word):
                    words.addAction(word, lambda checked=False, value=word, s=slot: self.lookup(value, s))
            group.addAction("Translate line", lambda checked=False, value=text, s=slot: self.lookup(value, s))
            group.addAction("Copy line", lambda checked=False, value=text: QApplication.clipboard().setText(value))
        menu.exec(self.cue_list.viewport().mapToGlobal(pos))

    def show_word_menu(self, text, pos, slot=1):
        if not text:
            return
        menu = QMenu(self)
        menu.addAction("Copy", lambda: QApplication.clipboard().setText(text))
        menu.addAction("Search in browser", lambda: QDesktopServices.openUrl(QUrl(self.settings.data["search_url"].replace("{word}", quote(text, safe="")))))
        try:
            searches = json.loads(self.settings.data['search_urls'])
        except ValueError:
            searches = {}
        for title, template in searches.items():
            menu.addAction(title, lambda checked=False, template=template: QDesktopServices.openUrl(QUrl(template.replace("{word}", quote(text, safe="")))))
        menu.addAction("Translate selection", lambda: self.lookup(text, slot))
        menu.exec(pos)

    def lookup(self, text, slot=1):
        if self.lookup_dialog:
            self.lookup_dialog.close()
        resume = self.settings.data["pause_on_lookup"] and self.player.isPlaying()
        generation = self.generation
        if self.settings.data['pause_on_lookup']:
            self.player.pause()
        position = self.player.position()
        dialog = QDialog(self)
        dialog.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        dialog.setWindowTitle("Word lookup")
        dialog.resize(340, 176)
        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(18, 16, 18, 14)
        original = QLabel(text)
        original.setObjectName("Heading")
        original.setWordWrap(True)
        original.setTextFormat(Qt.TextFormat.PlainText)
        original.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(original)
        language = QLabel(language_name(self.language_code(1-slot)))
        language.setObjectName("Muted")
        layout.addWidget(language)
        result = QTextBrowser()
        result.setObjectName("LookupResult")
        result.setFrameShape(QFrame.Shape.NoFrame)
        result.setAccessibleName("Translation")
        result.setPlainText('Translating…')
        layout.addWidget(result)
        row = QHBoxLayout()
        row.addStretch()
        def copy_word():
            QApplication.clipboard().setText(text)
            copy_button.setText("Copied")
        copy_button = self.button("Copy word", copy_word, row)
        self.button('Search in browser', lambda: QDesktopServices.openUrl(QUrl(self.settings.data['search_url'].replace('{word}', quote(text, safe='')))), row)
        layout.addLayout(row)
        self.lookup_dialog = dialog
        def dismissed(_code):
            if self.lookup_dialog is dialog:
                self.lookup_dialog = None
                if resume and not self._closing and self.generation == generation and self.player.position() == position:
                    self.player.play()
        dialog.finished.connect(dismissed)
        dialog.show()
        point = QCursor.pos()
        screen = QApplication.screenAt(point) or self.screen()
        bounds = screen.availableGeometry().adjusted(8, 8, -8, -8)
        frame = dialog.frameGeometry()
        x = max(bounds.left(), min(point.x(), bounds.right() - frame.width()))
        y = point.y() - frame.height() - 12
        if y < bounds.top():
            y = min(bounds.bottom() - frame.height(), point.y() + 18)
        dialog.move(x, max(bounds.top(), y))
        translator = services.Translator(dict(self.settings.data, source=self.language_code(slot), target=self.language_code(1-slot)))
        def display(value):
            from shiboken6 import isValid
            if isValid(result):
                result.setPlainText(value)
        retry = self.button("Try again", lambda: translate_word(), row)
        retry.hide()

        def failed(message):
            from shiboken6 import isValid
            if isValid(result):
                display("Translation unavailable.")
                result.setToolTip(message)
                retry.show()

        def translate_word():
            retry.hide()
            display("Translating…")
            self.task(lambda: translator.translate(text), display, failed=failed)
        translate_word()

    def show_generated_source(self, slot, kind, label):
        self.cancel_readers(slot)
        self.subtitle_sources[slot] = None
        self.read_completed[slot] = True
        combo = self.track_boxes[slot]
        source = (kind, slot)
        index = next((i for i in range(combo.count()) if combo.itemData(i) == source), -1)
        if index < 0:
            combo.addItem(label, source)
            index = combo.count() - 1
        combo.setItemText(index, label)
        combo.setCurrentIndex(index)
        self.update_track_source(slot)

    def reset_dependent_translation(self, slot):
        if self.translation_enabled and slot == self.translation_slot():
            self.toggle_translation(True)
        self.refresh_sidebar()

    def toggle_translation(self, enabled):
        self.translation_run += 1
        self.translating.clear()
        self.translated_cues.clear()
        self.translation_enabled = enabled
        if not enabled:
            self.fallback_active = False
        target = 1 - self.translation_slot()
        if enabled:
            if self.asr_enabled and self.asr_slot() == target:
                self.asr.setChecked(False)
            self.show_generated_source(target, "translation", "Translated from " + language_name(self.language_code(1-target)))
            self.track_generation[target] += 1
            self.timelines[target] = Timeline()
            self.translator = services.Translator(dict(self.settings.data, source=self.language_code(1-target), target=self.language_code(target)) if self.settings.data["languages_chosen"] else dict(self.settings.data))
        self.tick()

    def schedule_translation(self, position):
        translation_run = self.translation_run
        source_slot = self.translation_slot()
        target_slot = 1 - source_slot
        primary = self.timelines[source_slot]
        for index in primary.window(position, position + 15000):
            if len(self.translating) >= 3:
                break
            cue = primary.cues[index]
            key = (translation_run, cue.start, cue.end, cue.text)
            if (not cue.text or cue.end + primary.offset <= position or key in self.translating
                    or (cue.start, cue.end, cue.text) in self.translated_cues):
                continue
            self.translating.add(key)
            context = [c.text for c in primary.cues[max(0, index - self.settings.data["context_lines"]):index]]
            translator = self.translator
            revision = self.track_generation[target_slot]
            def done(text, c=cue, k=key, rev=revision):
                self.translating.discard(k)
                if self.translation_enabled and translation_run == self.translation_run and rev == self.track_generation[target_slot]:
                    self.timelines[target_slot] = Timeline(self.timelines[target_slot].cues + [Cue(c.start, c.end, text, original_text=c.text)])
                    self.timelines[target_slot].offset = self.offset_boxes[target_slot].value()
                    self.translated_cues.add((c.start, c.end, c.text))
                    self.refresh_sidebar()
            def failed(_message, k=key):
                self.translating.discard(k)
                if translation_run == self.translation_run:
                    self.translate.setChecked(False)
            self.task(lambda c=cue, ctx=context: translator.translate(c.text, ctx), done, self.generation, failed)

    def toggle_asr(self, enabled):
        self.asr_cancel.set()
        self.asr_cancel = threading.Event()
        self.asr_run += 1
        self.asr_busy = False
        if enabled and not self.source:
            self.asr.setChecked(False)
            self.statusBar().showMessage("Open media before generating subtitles")
            return
        self.asr_enabled = enabled
        if enabled:
            slot = self.asr_slot()
            if self.translation_enabled and 1 - self.translation_slot() == slot:
                self.translate.setChecked(False)
            self.show_generated_source(slot, "speech", "Generated from speech")
            self.track_generation[slot] += 1
            self.timelines[slot] = Timeline()
            self.asr_ranges.clear()
            self.reset_dependent_translation(slot)
            if slot == 0:
                self.apply_translation_fallback()
            self.statusBar().showMessage("Generating speech subtitles…")
        self.tick()

    def schedule_asr(self, position):
        slot = self.asr_slot()
        seconds = self.settings.data["asr_chunk_seconds"]
        start = position // (seconds * 1000) * seconds
        if start in self.asr_ranges:
            # Keep one chunk ahead while playback continues.
            start += seconds
        if start in self.asr_ranges or (self.player.duration() and start * 1000 >= self.player.duration()):
            return
        self.asr_busy = True
        self.asr_active_start = start
        self.asr_run += 1
        run_id, cancel = self.asr_run, self.asr_cancel
        self.asr_ranges.add(start)
        source, settings = self.source, dict(self.settings.data)
        revision = self.track_generation[slot]
        def done(cues):
            if run_id != self.asr_run:
                return
            self.asr_busy = False
            if self.asr_enabled and revision == self.track_generation[slot]:
                self.timelines[slot] = Timeline(list({(c.start, c.text): c for c in self.timelines[slot].cues + cues}.values()))
                self.timelines[slot].offset = self.offset_boxes[slot].value()
                self.refresh_sidebar()
                self.statusBar().showMessage("Speech subtitles ready", 2500)
        def failed(_message):
            if run_id != self.asr_run:
                return
            self.asr_busy = False
            self.asr_ranges.discard(start)
            self.asr.setChecked(False)
        def stream(emit):
            return services.transcribe_chunk(source, start, seconds, settings, emit=emit, cancel=cancel)
        def partial(cue):
            if self.asr_enabled and revision == self.track_generation[slot] and not cancel.is_set():
                if not any(c.start == cue.start and c.text == cue.text for c in self.timelines[slot].cues):
                    self.timelines[slot] = Timeline(self.timelines[slot].cues + [cue])
                    self.timelines[slot].offset = self.offset_boxes[slot].value()
                    self.refresh_sidebar()
        self.task(stream, done, self.generation, failed, progress=partial)

    def schedule_ocr(self, position):
        for slot, timeline in enumerate(self.timelines):
            nearby = (timeline.cues[i] for i in timeline.window(position, position + 15000))
            candidates = [c for c in nearby if c.image and not c.text and c.end + timeline.offset > position]
            for cue in candidates[:2]:
                key = (slot, id(cue))
                if key in self.ocr_pending or key in self.ocr_processed:
                    continue
                self.ocr_pending.add(key)
                language = self.settings.data["ocr_language"]
                revision = self.track_generation[slot]
                def done(text, c=cue, k=key, s=slot, rev=revision):
                    self.ocr_pending.discard(k)
                    if rev == self.track_generation[s]:
                        self.ocr_processed.add(k)
                        c.text = text
                        self.refresh_sidebar()
                def failed(_message, k=key):
                    self.ocr_pending.discard(k)
                    self.live_ocr.setChecked(False)
                self.task(lambda c=cue: services.ocr_image(c.image, language, self.settings.data["ocr_engine"]), done, self.generation, failed)

    def ocr_track(self):
        slot, ok = QInputDialog.getItem(self, "OCR subtitles", "Track", ["Primary", "Secondary"], 0, False)
        if not ok:
            return
        index = 0 if slot == "Primary" else 1
        cues = list(self.timelines[index].cues)
        language = self.settings.data["ocr_language"]
        revision = self.track_generation[index]
        def recognize():
            return Timeline(replace(c, text=services.ocr_image(c.image, language, self.settings.data["ocr_engine"])) if c.image else replace(c) for c in cues)
        def done(timeline):
            if revision == self.track_generation[index]:
                timeline.offset = self.offset_boxes[index].value()
                self.timelines[index] = timeline
                self.refresh_sidebar()
                self.statusBar().showMessage("OCR complete")
        self.statusBar().showMessage("Reading subtitle images…")
        self.task(recognize, done, self.generation)

    def export_subtitles(self):
        languages = [language_name(self.language_code(slot)) for slot in range(2)]
        name, ok = QInputDialog.getItem(self, "Export subtitles", "Language", languages, 0, False)
        if ok:
            self.export_track(languages.index(name))

    def export_track(self, slot):
        parent = self.track_dialog if self.track_dialog.isVisible() else self
        path, _ = QFileDialog.getSaveFileName(parent, "Export subtitles", f"subtitles.{self.language_code(slot)}.srt", "SubRip (*.srt)")
        if path:
            self.timelines[slot].export(path)
            self.statusBar().showMessage("Subtitles exported", 2500)

    def download_subtitles(self, slot=0):
        dialog = QDialog(self.track_dialog if self.track_dialog.isVisible() else self)
        dialog.setWindowTitle("Find subtitles")
        dialog.setWindowModality(Qt.WindowModality.WindowModal)
        dialog.resize(440, 350)
        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(18, 16, 18, 16)
        ui.dialog_header(dialog, f"Find {language_name(self.language_code(slot))} subtitles", layout)
        stem = Path(self.media_path).stem
        title = re.split(r"[._ ](?:19|20)\d{2}(?=[._ ]|$)", stem, maxsplit=1)[0] or stem
        query = QLineEdit(title.replace(".", " ").replace("_", " "))
        query.setAccessibleName("Film or episode")
        query.setClearButtonEnabled(True)
        query.setPlaceholderText("Film or episode")
        layout.addWidget(query)
        results = QListWidget()
        layout.addWidget(results)
        status = QLabel()
        status.setObjectName("Muted")
        status.setWordWrap(True)
        layout.addWidget(status)
        row = QHBoxLayout()
        layout.addLayout(row)
        def connect_account():
            settings_dialog = SettingsDialog(self.settings, dialog, owner=self)
            downloads = settings_dialog.sections.findItems("Downloads", Qt.MatchFlag.MatchExactly)[0]
            settings_dialog.sections.setCurrentItem(downloads)
            if settings_dialog.exec():
                self.update_language_labels()
                self.apply_theme()
                self.install_actions()
                run()

        setup = self.button("Connect OpenSubtitles…", connect_account, row)
        setup.setVisible(not self.settings.data["opensubtitles_key"])
        row.addStretch()
        search = self.button("Search", lambda: run(), row)
        load = self.button("Load subtitles", lambda: choose(), row)
        load.setObjectName("PrimaryAction")
        load.setEnabled(False)
        request = 0
        generation = self.generation
        revision = self.track_generation[slot]
        language = self.language_code(slot)

        def current():
            return dialog.isVisible() and generation == self.generation and revision == self.track_generation[slot]

        def add(label, value):
            item = QListWidgetItem(label)
            item.setData(Qt.ItemDataRole.UserRole, value)
            results.addItem(item)
            if results.count() == 1:
                results.setCurrentRow(0)

        def run():
            nonlocal request
            request += 1
            serial = request
            results.clear()
            setup.setVisible(not self.settings.data["opensubtitles_key"])
            title = query.text().strip()
            media = Path(self.media_path)
            if media.is_file():
                for path in sorted(media.parent.iterdir()):
                    if path.suffix.lower() in (".srt", ".vtt", ".ass", ".ssa", ".sup", ".idx") and title.casefold() in path.stem.casefold().replace(".", " ").replace("_", " "):
                        add(f"{path.name} · On this Mac" if sys.platform == "darwin" else f"{path.name} · Local file", str(path))
            if not self.settings.data["opensubtitles_key"]:
                local_status = "Local subtitles" if results.count() else "No local subtitles found."
                status.setText(local_status)
                return
            if not title:
                status.setText("Enter a film or episode title.")
                return
            status.setText("Searching online…")
            def found(entries):
                if not current() or serial != request:
                    return
                for entry in entries:
                    attrs = entry["attributes"]
                    for file in attrs.get("files", []):
                        add(attrs.get("release") or file["file_name"], int(file["file_id"]))
                status.setText("Choose a subtitle to load." if results.count() else "No matching subtitles.")
            def failed(message):
                if current() and serial == request:
                    status.setText(message)
            provider = services.OpenSubtitles(dict(self.settings.data))
            self.task(lambda: provider.search(title, language), found, generation, failed)

        def choose():
            item = results.currentItem()
            if not item or not current():
                return
            source = item.data(Qt.ItemDataRole.UserRole)
            if isinstance(source, str):
                dialog.accept()
                self.load_subtitles(source, slot)
                return
            status.setText("Downloading subtitles…")
            results.setEnabled(False)
            search.setEnabled(False)
            query.setEnabled(False)
            load.setEnabled(False)
            def saved(data):
                if current():
                    from hashlib import sha256
                    cache = Path(QStandardPaths.writableLocation(QStandardPaths.StandardLocation.CacheLocation)) / "subtitles"
                    path = cache / f"{source}-{sha256(data).hexdigest()[:12]}.srt"
                    try:
                        cache.mkdir(parents=True, exist_ok=True)
                        with tempfile.NamedTemporaryFile(dir=cache, delete=False) as stream:
                            stream.write(data)
                        os.replace(stream.name, path)
                    except OSError as error:
                        failed(str(error))
                        return
                    dialog.accept()
                    self.load_subtitles(str(path), slot)
            def failed(message):
                if current():
                    status.setText(message)
                    for widget in (results, search, query, load):
                        widget.setEnabled(True)
            provider = services.OpenSubtitles(dict(self.settings.data))
            self.task(lambda: provider.download(source), saved, generation, failed)

        results.currentItemChanged.connect(lambda item, _: load.setEnabled(item is not None))
        results.itemDoubleClicked.connect(lambda _: choose())
        query.returnPressed.connect(run)
        dialog.show()
        run()
        query.selectAll()
        query.setFocus()
        return dialog

    def open_settings(self):
        previous_languages = [self.language_code(slot) for slot in range(2)]
        previous_fallback = self.settings.data["auto_translate"]
        if SettingsDialog(self.settings, self).exec():
            self.update_language_labels()
            self.apply_theme()
            self.install_actions()
            for slot, previous in enumerate(previous_languages):
                if previous != self.language_code(slot) and self.tracks_discovered:
                    language = QLocale.codeToLanguage(self.language_code(slot))
                    track = next((t for t in self.tracks if t.get("language") and
                                  QLocale.codeToLanguage(t["language"]) == language), None)
                    index = self.track_boxes[slot].findData(track["index"]) if track else 0
                    self.choose_source(slot, index)
                    self.discovery_revisions[slot] = self.track_generation[slot]
            if previous_fallback != self.settings.data["auto_translate"]:
                if self.fallback_active and not self.settings.data["auto_translate"]:
                    self.choose_source(1, 0)
                elif self.track_boxes[1].currentIndex() == 0:
                    self.discovery_revisions[1] = self.track_generation[1]
            if self.asr_enabled:
                self.toggle_asr(False)
                self.toggle_asr(True)
            if self.translation_enabled:
                self.toggle_translation(True)
            self.apply_translation_fallback()

    def install_actions(self):
        bar = self.menuBar()
        for menu_action in bar.actions():
            menu = menu_action.menu()
            bar.removeAction(menu_action)
            if menu:
                menu.deleteLater()
        for action in self.actions:
            self.removeAction(action)
            action.deleteLater()
        self.actions = []
        callbacks = {
            "Play / pause": self.toggle_play, "Open media": self.open_file, "Open URL": self.open_url,
            "Primary subtitles": lambda: self.open_subtitles(0), "Secondary subtitles": lambda: self.open_subtitles(1),
            "Previous subtitle": lambda: self.subtitle_seek(-1), "Next subtitle": lambda: self.subtitle_seek(1),
            "Seek backward": lambda: self.player.setPosition(max(0, self.player.position() - 5000)),
            "Seek forward": lambda: self.player.setPosition(self.player.position() + 5000),
            "Fullscreen": self.fullscreen, "Settings": self.open_settings, "Cheat sheet": self.help,
            "Copy subtitles": self.copy_subtitles, "Sidebar": self.panel_button.click,
            "Mute": lambda: self.audio.setMuted(not self.audio.isMuted()),
            "Next file": lambda: self.adjacent_file(1), "Previous file": lambda: self.adjacent_file(-1),
            "Search subtitles": self.focus_search, "Always on top": self.always_on_top,
            "Subtitles up": lambda: self.adjust_subtitles("subtitle_vertical", -2),
            "Subtitles down": lambda: self.adjust_subtitles("subtitle_vertical", 2),
            "Larger subtitles": lambda: self.resize_subtitles((0, 1), 1),
            "Smaller subtitles": lambda: self.resize_subtitles((0, 1), -1),
            "Larger secondary": lambda: self.resize_subtitles((1,), 1),
            "Smaller secondary": lambda: self.resize_subtitles((1,), -1),
            "More subtitle spacing": lambda: self.adjust_subtitles("gap", 2),
            "Less subtitle spacing": lambda: self.adjust_subtitles("gap", -2),
            "Copy primary": lambda: QApplication.clipboard().setText(self.labels[0].text()),
            "Copy secondary": lambda: QApplication.clipboard().setText(self.labels[1].text()),
            "Automatic copy": self.toggle_auto_copy,
            "Switch sidebar track": lambda: self.sidebar_slot.setCurrentIndex((self.sidebar_slot.currentIndex() + 1) % 3),
            "Download subtitles": lambda: self.download_subtitles(self.study_slot()), "Export subtitles": self.export_subtitles,
            "New window": self.new_window, "Clone window": lambda: self.new_window(True), "Restart": self.restart,
            "Debug information": lambda: self.debug_label.setVisible(not self.debug_label.isVisible()),
            "Copy media path": lambda: QApplication.clipboard().setText(self.media_path), "Paste media": self.paste_media,
            "Original sidebar text": self.toggle_original, "Play": self.player.play, "Pause": self.player.pause,
            "Stop": self.player.stop, "Volume up": lambda: self.volume.setValue(self.volume.value() + 5),
            "Volume down": lambda: self.volume.setValue(self.volume.value() - 5), "Current subtitle": self.current_subtitle,
            "Primary visibility": lambda: self.toggle_subtitles(0), "Secondary visibility": lambda: self.toggle_subtitles(1),
            "All subtitle visibility": lambda: self.toggle_subtitles(),
            "Larger primary": lambda: self.resize_subtitles((0,), 1), "Smaller primary": lambda: self.resize_subtitles((0,), -1),
            "Reset subtitle position": self.reset_subtitle_position,
            "Primary delay up": lambda: self.offset_boxes[0].stepUp(), "Primary delay down": lambda: self.offset_boxes[0].stepDown(),
            "Secondary delay up": lambda: self.offset_boxes[1].stepUp(), "Secondary delay down": lambda: self.offset_boxes[1].stepDown(),
            "Frame forward": lambda: self.step_frame(1), "Frame backward": lambda: self.step_frame(-1),
            "Loop media": lambda: self.player.setLoops(1 if self.player.loops() == -1 else -1),
            "Speed up": lambda: self.player.setPlaybackRate(min(8, self.player.playbackRate() + .1)),
            "Speed down": lambda: self.player.setPlaybackRate(max(.1, self.player.playbackRate() - .1)),
            "Normal speed": lambda: self.player.setPlaybackRate(1), "Seek start": lambda: self.player.setPosition(0),
            "Seek end": lambda: self.player.setPosition(max(0, self.player.duration() - 100)), "Rotate video": self.rotate,
            "Audio delay up": lambda: self.adjust_audio_delay(100), "Audio delay down": lambda: self.adjust_audio_delay(-100),
            "Audio delay up large": lambda: self.adjust_audio_delay(1000), "Audio delay down large": lambda: self.adjust_audio_delay(-1000),
            "Secondary previous subtitle": lambda: self.subtitle_seek(-1, 1), "Secondary current subtitle": lambda: self.current_subtitle(1),
            "Secondary next subtitle": lambda: self.subtitle_seek(1, 1), "Reverse playback": self.playback.toggle_reverse,
            "Record": self.toggle_recording, "Zoom in": lambda: self.zoom(.1), "Zoom out": lambda: self.zoom(-.1),
            "Reset zoom": lambda: self.zoom(reset=True), "Reset rotation": self.reset_rotation,
            "Reset delay": self.reset_delays, "Reset all": self.reset_playback,
            "Audio visibility": lambda: self.audio.setMuted(not self.audio.isMuted()),
            "Video visibility": lambda: self.video.video_item.setVisible(not self.video.video_item.isVisible()),
            "Keep aspect ratio": self.toggle_aspect_ratio, "Video acceleration": self.toggle_video_acceleration,
            "Reload media": self.reload_media, "Show controls": lambda: self.controls_visible(True),
            "Hide controls": lambda: self.controls_visible(False),
            "Seek forward medium": lambda: self.player.setPosition(self.player.position() + 30000),
            "Seek backward medium": lambda: self.player.setPosition(max(0, self.player.position() - 30000)),
            "Seek forward large": lambda: self.player.setPosition(self.player.position() + 60000),
            "Seek backward large": lambda: self.player.setPosition(max(0, self.player.position() - 60000)),
            "Fullscreen on": self.showFullScreen, "Fullscreen off": self.showNormal,
            "Close window": self.close, "Screenshot": self.screenshot, "Open current folder": self.open_folder, "Quit": QApplication.instance().closeAllWindows,
        }
        for name, callback in callbacks.items():
            action = QAction(name, self)
            if name == "Settings":
                action.setMenuRole(QAction.MenuRole.PreferencesRole)
            elif name == "Quit":
                action.setMenuRole(QAction.MenuRole.QuitRole)
            else:
                action.setMenuRole(QAction.MenuRole.NoRole)
            action.setShortcuts([QKeySequence(key) for key in self.settings.data["shortcuts"].get(name, [])])
            action.triggered.connect(callback)
            self.addAction(action)
            self.actions.append(action)

        self.toolbar_menu.clear()
        commands = {action.text(): action for action in self.actions}
        groups = {
            "&File": ("New window", "Open media", "Open URL", "Reload media", "Close window", "Settings", "Quit"),
            "&Playback": ("Play / pause", "Previous subtitle", "Next subtitle", "Seek backward", "Seek forward", "Mute", "Speed up", "Speed down"),
            "&Subtitles": ("Primary subtitles", "Secondary subtitles", "Download subtitles", "Export subtitles", "Search subtitles"),
            "&View": ("Sidebar", "Fullscreen", "Always on top"),
            "&Window": ("Clone window",),
            "&Help": ("Cheat sheet",),
        }
        for title, names in groups.items():
            menu = bar.addMenu(title)
            toolbar_group = self.toolbar_menu.addMenu(title.replace("&", ""))
            for name in names:
                menu.addAction(commands[name])
                toolbar_group.addAction(commands[name])

    def media_menu(self, point):
        menu = QMenu(self)
        actions = {action.text(): action for action in self.actions}
        for name in ('Open media', 'Open URL', 'Paste media'):
            menu.addAction(actions[name])
        for title, names in {
            'Playback': ['Play / pause', 'Stop', 'Frame forward', 'Frame backward', 'Reverse playback', 'Loop media', 'Record', 'Screenshot'],
            'Subtitles': ['Primary subtitles', 'Secondary subtitles', 'Primary visibility', 'Secondary visibility', 'Export subtitles', 'Download subtitles'],
            'Video': ['Zoom in', 'Zoom out', 'Rotate video', 'Keep aspect ratio', 'Reset all'],
            'Window': ['New window', 'Clone window', 'Always on top', 'Fullscreen', 'Debug information', 'Restart', 'Show controls', 'Hide controls']
        }.items():
            group = menu.addMenu(title)
            for name in names:
                group.addAction(actions[name])
        menu.addAction(actions['Settings'])
        menu.addAction(actions['Cheat sheet'])
        menu.exec(self.video.mapToGlobal(point))

    def controls_visible(self, visible):
        self.controls.setVisible(visible)

    def adjust_audio_delay(self, delta):
        self.settings.data['audio_delay'] = max(-10000, min(10000, self.settings.data['audio_delay'] + delta))
        self.playback.set_audio_delay(self.settings.data['audio_delay'])
        self.statusBar().showMessage(f"Audio delay: {self.settings.data['audio_delay']} ms")

    def toggle_recording(self):
        try:
            if self.playback.recording:
                self.playback.stop_recording()
            else:
                path, _ = QFileDialog.getSaveFileName(self, 'Record media', 'recording.mkv', 'Matroska (*.mkv);;MP4 (*.mp4)')
                if path:
                    self.playback.start_recording(path)
        except Exception as error:
            self.statusBar().showMessage(str(error), 15000)

    def zoom(self, delta=0, reset=False):
        self._zoom = 1.0 if reset else max(.2, min(8, self._zoom + delta))
        self.video.video_item.setTransformOriginPoint(self.video.video_item.boundingRect().center())
        self.video.video_item.setScale(self._zoom)

    def reset_rotation(self):
        self._rotation = 0
        self.video.video_item.setRotation(0)
        self.video.arrange()

    def reset_delays(self):
        for offset in self.offset_boxes:
            offset.setValue(0)
        self.settings.data['audio_delay'] = 0
        self.playback.set_audio_delay(0)

    def reset_playback(self):
        self.zoom(reset=True)
        self.reset_rotation()
        self.reset_delays()
        self.player.setPlaybackRate(1)

    def toggle_aspect_ratio(self):
        self.settings.data['video_aspect'] = 'Stretch' if self.settings.data['video_aspect'] != 'Stretch' else 'Auto'
        self.video.aspect = self.settings.data['video_aspect']
        self.video.arrange()

    def toggle_video_acceleration(self):
        self.settings.data['video_acceleration'] = not self.settings.data['video_acceleration']
        self.settings.save()
        self.restart()

    def reload_media(self):
        source, position = self.player.source(), self.player.position()
        playing = self.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState
        def loaded(status):
            if status == QMediaPlayer.MediaStatus.LoadedMedia:
                self.player.mediaStatusChanged.disconnect(loaded)
                self.player.setPosition(position)
                if playing:
                    self.player.play()
        self.player.mediaStatusChanged.connect(loaded)
        self.player.setSource(QUrl())
        self.player.setSource(source)

    def asr_slot(self):
        return 0 if self.settings.data['asr_track'] == 'Primary' else 1

    def translation_slot(self):
        return 0 if self.settings.data['translation_track'] == 'Primary' else 1

    def cancel_readers(self, slot=None):
        for index in range(2) if slot is None else [slot]:
            self.slice_cancels[index].set()
            self.slice_cancels[index] = threading.Event()
            self.read_cancels[index].set()
            self.read_cancels[index] = threading.Event()

    def toggle_original(self):
        self.show_original = not self.show_original
        self.settings.data["sidebar_original"] = self.show_original
        self.refresh_sidebar()

    def toggle_subtitles(self, slot=None):
        slots = range(2) if slot is None else [slot]
        hidden = not self.hidden_subtitles[0] if slot is None else not self.hidden_subtitles[slot]
        for index in slots:
            self.hidden_subtitles[index] = hidden
        self.tick()

    def current_subtitle(self, slot=0):
        cues = self.timelines[slot].active(self.player.position())
        if cues:
            self.player.setPosition(cues[0].start + self.timelines[slot].offset)

    def reset_subtitle_position(self):
        self.settings.data.update(subtitle_horizontal=50, subtitle_vertical=85, subtitle_anchor="Center", bottom=28, gap=8)
        self.apply_theme()

    def step_frame(self, direction):
        from PySide6.QtMultimedia import QMediaMetaData
        fps = self.player.metaData().value(QMediaMetaData.Key.VideoFrameRate) or 24
        self.player.pause()
        self.player.setPosition(max(0, self.player.position() + round(direction * 1000 / float(fps))))

    def rotate(self):
        self._rotation = (self._rotation + 90) % 360
        self.video.video_item.setTransformOriginPoint(self.video.video_item.boundingRect().center())
        self.video.video_item.setRotation(self._rotation)
        self.video.arrange()

    def paste_media(self):
        text = QApplication.clipboard().text().strip()
        if text.startswith(("http://", "https://")):
            self.resolve_url(text)
        elif Path(text).is_file():
            self.open_media(text)

    def new_window(self, clone=False):
        config = Settings(self.settings.path)
        config.data = json.loads(json.dumps(self.settings.data))
        window = Window(config)
        self.extra_windows.append(window)
        window.show()
        if clone and self.source:
            window.open_media(copy.deepcopy(self.original_source or self.source), self.media_title.text())
            window.cancel_readers()
            window.track_generation = [revision + 1 for revision in window.track_generation]
            window.timelines = copy.deepcopy(self.timelines)
            for slot, snapshot in enumerate(window.timelines):
                window.track_boxes[slot].addItem("Cloned subtitles", ("snapshot", copy.deepcopy(snapshot)))
                window.track_boxes[slot].setCurrentIndex(window.track_boxes[slot].count() - 1)
            for index, timeline in enumerate(self.timelines):
                window.timelines[index].offset = timeline.offset
            position = self.player.position()
            playing = self.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState
            def restore():
                window.player.setPosition(position)
                if not playing:
                    window.player.pause()
            QTimer.singleShot(500, window, restore)
            window.refresh_sidebar()
        return window

    def restart(self):
        from PySide6.QtCore import QProcess
        self.settings.save()
        args = [] if getattr(sys, "frozen", False) else [str(Path(__file__).resolve().parents[1] / "run.py")]
        args += ["--config", str(self.settings.path), "--position", str(self.player.position())]
        if self.player.playbackState() != QMediaPlayer.PlaybackState.PlayingState:
            args.append("--paused")
        if self.media_path:
            args.append(self.media_path)
        started, _pid = QProcess.startDetached(sys.executable, args)
        if started:
            self.close()

    def focus_search(self):
        self.sidebar.show()
        self.panel_button.setChecked(True)
        self.search.setFocus()

    def always_on_top(self):
        enabled = bool(self.windowFlags() & Qt.WindowType.WindowStaysOnTopHint)
        self.settings.data["always_on_top"] = not enabled
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, not enabled)
        self.show()

    def resize_subtitles(self, slots, direction):
        for slot in slots:
            cues = self.timelines[slot].active(self.player.position()) or self.timelines[slot].cues[:1]
            bitmap = any(cue.image and not cue.text for cue in cues)
            if bitmap:
                key = 'bitmap_scale' if slot == 0 else 'secondary_bitmap_scale'
                self.settings.data[key] = max(10, min(300, self.settings.data[key] + direction * 4))
            else:
                key = 'font_size' if slot == 0 else 'secondary_size'
                self.settings.data[key] = max(8, min(200, self.settings.data[key] + direction * 2))
        self.apply_theme()
        self.tick()

    def adjust_subtitles(self, key, delta):
        minimum = 8 if key in ("font_size", "secondary_size") else -25 if key == "subtitle_vertical" else 0
        self.settings.data[key] = max(minimum, min(200, self.settings.data[key] + delta))
        self.apply_theme()

    def toggle_auto_copy(self):
        self.settings.data["auto_copy"] = not self.settings.data["auto_copy"]
        self.statusBar().showMessage("Automatic copying " + ("on" if self.settings.data["auto_copy"] else "off"))

    def screenshot(self):
        path, _ = QFileDialog.getSaveFileName(self, "Save screenshot", "lids-player.png", "PNG image (*.png)")
        if path:
            if self.video.grab().save(path):
                self.statusBar().showMessage("Screenshot saved")
            else:
                self.statusBar().showMessage("Could not save the screenshot")

    def open_folder(self):
        if Path(self.media_path).is_file():
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(Path(self.media_path).resolve().parent)))

    def adjacent_file(self, direction):
        path = Path(self.media_path)
        if path.is_file():
            files = sorted(p for p in path.parent.iterdir() if p.suffix.lower() in (".mp4", ".mkv", ".webm", ".mov", ".avi", ".mp3", ".wav", ".flac"))
            if path in files and 0 <= files.index(path) + direction < len(files):
                self.open_media(str(files[files.index(path) + direction]))

    def fullscreen(self):
        self.showNormal() if self.isFullScreen() else self.showFullScreen()

    def help(self):
        dialog = QDialog(self)
        dialog.setWindowTitle("LIDS Player help")
        dialog.resize(620, 650)
        layout = QVBoxLayout(dialog)
        text = QTextBrowser()
        rows = "".join(f"<tr><td>{html.escape(name)}</td><td>{html.escape(', '.join(keys))}</td></tr>" for name, keys in self.settings.data["shortcuts"].items())
        text.setHtml("<h2>Watch and learn</h2><p>Open a file or URL. Load two subtitle tracks, or generate speech subtitles and translate them. Click a sidebar line to seek. Select subtitle text and right-click to copy, search or translate it.</p>"
                     "<p>Use the delay controls to sync each track. Repeat line loops the current subtitle. Settings controls subtitle sizes, spacing, translation, speech recognition and shortcuts. Separate multiple shortcuts with semicolons.</p>"
                     "<p>For Yomitan or 10ten, enable automatic subtitle copying and use your browser extension's clipboard workflow.</p>"
                     "<table cellpadding='7'>" + rows + "</table>")
        layout.addWidget(text)
        dialog.exec()

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event):
        for url in event.mimeData().urls():
            self.open_document(url, 1 if event.modifiers() & Qt.KeyboardModifier.ShiftModifier else 0)

    def open_document(self, url, slot=0):
        path = url.toLocalFile()
        if Path(path).suffix.lower() in (".srt", ".ass", ".ssa", ".vtt", ".sub", ".idx", ".sup", ".mks"):
            self.load_subtitles(path, slot)
        elif path:
            self.open_media(path)
        elif url.scheme() in ("http", "https"):
            self.resolve_url(url.toString())

    def closeEvent(self, event):
        self._closing = True
        self.cancel_readers()
        self.asr_cancel.set()
        try:
            self.playback.close()
        except Exception:
            pass  # Closing must still release the player if a recording failed.
        self.player.stop()
        # Release the decoding engine while its Python-owned outputs are alive.
        # Leaving the source attached defers audio-renderer destruction until
        # widget teardown, where its disconnect callback can deadlock with Qt.
        self.player.setSource(QUrl())
        self.player.setAudioOutput(None)
        self.player.setVideoOutput(None)
        if self.media_proxy:
            self.media_proxy.close()
            self.media_proxy = None
        self.timer.stop()
        self.generation += 1
        self.settings.save()
        # Running workers retain their signal objects until completion. The pool
        # owns their lifetime, so shutdown cannot destroy a running QThread.
        super().closeEvent(event)


class PlayerApplication(QApplication):
    def __init__(self, argv):
        self.pending_documents = []
        self.document_handler = None
        super().__init__(argv)

    def event(self, event):
        if event.type() == QEvent.Type.FileOpen:
            if self.document_handler:
                self.document_handler(event.url())
            else:
                self.pending_documents.append(event.url())
            return True
        return super().event(event)


def main():
    parser = argparse.ArgumentParser(description="LIDS Player for macOS, Windows and Linux")
    parser.add_argument("media", nargs="?")
    parser.add_argument("--config", type=Path, help="Settings file for this window")
    parser.add_argument("--position", type=int, default=0, help="Start position in milliseconds")
    parser.add_argument("--paused", action="store_true")
    parser.add_argument("--primary")
    parser.add_argument("--secondary")
    parser.add_argument("--smoke-test", metavar="REPORT")
    parser.add_argument("--smoke-asr", metavar="AUDIO")
    parser.add_argument("--smoke-tools", action="store_true")
    parser.add_argument("--smoke-whisper-model", metavar="MODEL")
    args = parser.parse_args()
    app = PlayerApplication(sys.argv)
    app.setOrganizationName("LLPlayer")
    app.setApplicationName("LLPlayer")
    app.setWindowIcon(QIcon(str(Path(__file__).parent / "assets/icon.png")))
    location = Path(QStandardPaths.writableLocation(QStandardPaths.StandardLocation.AppConfigLocation))
    config = args.config or (Path(args.smoke_test).with_suffix('.settings.json') if args.smoke_test else location / 'settings.json')
    settings = Settings(config)
    if not settings.data['video_acceleration']:
        os.environ['QT_FFMPEG_DECODING_HW_DEVICE_TYPES'] = ','
        os.environ['LLPLAYER_FORCED_SOFTWARE_VIDEO'] = '1'
    elif os.environ.pop('LLPLAYER_FORCED_SOFTWARE_VIDEO', None):
        os.environ.pop('QT_FFMPEG_DECODING_HW_DEVICE_TYPES', None)
    window = Window(settings)
    window.show()
    if not args.smoke_test and not window.setup_languages():
        window.close()
        return
    app.document_handler = window.open_document
    for url in app.pending_documents:
        window.open_document(url)
    app.pending_documents.clear()
    smoke_frames, smoke_audio = [], []
    if args.smoke_test:
        window.video.video_item.videoSink().videoFrameChanged.connect(
            lambda frame: smoke_frames.append(frame.startTime()) if frame.isValid() else None)
        smoke_output = QAudioBufferOutput(window)
        window.player.setAudioBufferOutput(smoke_output)
        smoke_output.audioBufferReceived.connect(
            lambda buffer: smoke_audio.append(buffer.byteCount()) if buffer.isValid() else None)
    if args.position or args.paused:
        def restore(status):
            if status != QMediaPlayer.MediaStatus.LoadedMedia:
                return
            window.player.mediaStatusChanged.disconnect(restore)
            generation = window.generation
            def apply_start_position():
                if generation != window.generation or window._closing:
                    return
                if args.paused:
                    window.player.pause()
                window.player.setPosition(max(0, args.position))
            # The backend can still have a pending autoplay transition in this signal.
            QTimer.singleShot(0, apply_start_position)
        window.player.mediaStatusChanged.connect(restore)
    remote = args.media and args.media.startswith(('http://', 'https://'))
    if remote:
        window.resolve_url(args.media, (args.primary, args.secondary))
    else:
        if args.media:
            window.open_media(args.media)
        if args.primary:
            window.load_subtitles(args.primary, 0)
        if args.secondary:
            window.load_subtitles(args.secondary, 1)
    if args.smoke_test:
        def report():
            frames = window.video.video_item.videoSink().videoFrame()
            result = {"platform": sys.platform, "duration_ms": window.player.duration(),
                      "position_ms": window.player.position(), "valid_video_frame": frames.isValid(),
                      "video_frame_count": len(set(smoke_frames)),
                      "last_video_frame_us": frames.startTime() if frames.isValid() else None,
                      "valid_video_image": frames.isValid() and not frames.toImage().isNull(),
                      "has_audio": window.player.hasAudio(), "audio_decoded_bytes": sum(smoke_audio),
                      "primary_cues": len(window.timelines[0].cues), "secondary_cues": len(window.timelines[1].cues),
                      "error": window.player.errorString()}
            if args.smoke_asr:
                try:
                    result["asr"] = [cue.text for cue in services.transcribe_chunk(args.smoke_asr, 0, 15, dict(window.settings.data, source="en"))]
                except Exception as error:
                    result["asr_error"] = str(error)
            if args.smoke_tools:
                import io
                from PIL import Image, ImageDraw, ImageFont
                from .native_tools import tokenize
                image = Image.new('RGB', (900, 140), 'white')
                ImageDraw.Draw(image).text((20, 35), 'Learning with subtitles', fill='black', font=ImageFont.load_default(size=45))
                png = io.BytesIO()
                image.save(png, format='PNG')
                result['tools'] = {name: bool(executable(name)) for name in ('whisper-cli', 'tesseract', 'llplayer-native')}
                try:
                    result['japanese'] = [token['text'] for token in tokenize('私は日本語を勉強しています')]
                    result['ocr_tesseract'] = services.ocr_image(png.getvalue(), 'eng', 'Tesseract')
                    result['ocr_native'] = services.ocr_image(png.getvalue(), 'eng', 'Apple Vision')
                    if args.smoke_asr and args.smoke_whisper_model:
                        result['asr_metal'] = [cue.text for cue in services.transcribe_chunk(args.smoke_asr, 0, 15, dict(window.settings.data, source='en', asr_engine='whisper.cpp', whisper_model=args.smoke_whisper_model, asr_gpu=True))]
                except Exception as error:
                    result['tools_error'] = str(error)
            Path(args.smoke_test).write_text(json.dumps(result, indent=2))
            window.grab().save(str(Path(args.smoke_test).with_suffix(".png")))
            window.close()
            app.exit(0 if result["valid_video_image"] and result["video_frame_count"] > 1
                     and result["position_ms"] > 0 and not result['error']
                     and (not result['has_audio'] or result['audio_decoded_bytes'] > 0)
                     and not result.get("asr_error") and not result.get("tools_error") else 1)
        QTimer.singleShot(3500, report)
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
