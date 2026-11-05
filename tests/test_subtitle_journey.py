import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLineEdit, QListWidget, QPushButton

from llplayer import services
from llplayer.app import Window
from llplayer.core import Cue, Settings, Timeline


def test_search_redirect_download_and_load_selected_language(qtbot, tmp_path, monkeypatch):
    requests = []
    contents = b"1\n00:00:01,000 --> 00:00:03,000\nTere hommikust!\n"

    class Provider(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def reply(self, payload):
            self.send_response(200)
            self.end_headers()
            self.wfile.write(json.dumps(payload).encode())

        def do_GET(self):
            requests.append((self.path, self.headers.get("Api-Key")))
            if self.path.startswith("/api/v1/subtitles?"):
                self.send_response(301)
                self.send_header("Location", "/canonical")
                self.end_headers()
            elif self.path == "/canonical":
                self.reply({"data": [{"attributes": {"release": "Backrooms", "files": [
                    {"file_name": "Backrooms.et.srt", "file_id": 7}]}}]})
            elif self.path == "/subtitle.srt":
                self.send_response(200)
                self.end_headers()
                self.wfile.write(contents)
            else:
                self.send_error(404)

        def do_POST(self):
            requests.append((self.path, self.headers.get("Authorization")))
            body = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
            if self.path != "/api/v1/download" or body != {"file_id": 7}:
                self.send_error(400)
                return
            self.reply({"link": f"http://127.0.0.1:{self.server.server_port}/subtitle.srt"})

    server = ThreadingHTTPServer(("127.0.0.1", 0), Provider)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    settings = Settings(tmp_path / "settings.json")
    settings.data.update(languages_chosen=True, secondary_language="et",
                         opensubtitles_key="test-key", opensubtitles_token="test-token")
    monkeypatch.setattr(services.OpenSubtitles, "base", f"http://127.0.0.1:{server.server_port}/api/v1")
    w = Window(settings)
    qtbot.addWidget(w)
    w.show()
    try:
        w.timelines[0] = Timeline([Cue(1000, 3000, "Good morning!")])
        w.media_path = "Backrooms.2026.1080p.WEBRip.mkv"
        dlg = w.download_subtitles(1)
        assert dlg.findChild(QLineEdit).text() == "Backrooms"
        results = dlg.findChild(QListWidget)
        qtbot.waitUntil(lambda: results.count() == 1)
        next(b for b in dlg.findChildren(QPushButton) if b.text() == "Load subtitles").click()
        qtbot.waitUntil(lambda: len(w.timelines[1].cues) == 1)
        assert w.timelines[0].active(1500)[0].text == "Good morning!"
        assert w.timelines[1].active(1500)[0].text == "Tere hommikust!"
        assert requests == [("/api/v1/subtitles?languages=et&query=backrooms", "test-key"),
                            ("/canonical", "test-key"), ("/api/v1/download", "Bearer test-token"),
                            ("/subtitle.srt", None)]
    finally:
        server.shutdown()
        server.server_close()
        w.close()


def test_translation_replacement_and_independent_delay(qtbot, tmp_path, monkeypatch):
    w = Window(Settings(tmp_path / "settings.json"))
    qtbot.addWidget(w)
    gate = threading.Event()
    started = threading.Event()

    def translate(_translator, text, _context=()):
        if text == "Previous track":
            started.set()
            gate.wait(2)
        return "ET " + text

    monkeypatch.setattr(services.Translator, "translate", translate)
    try:
        w.timelines[0] = Timeline([Cue(0, 2000, "Previous track")])
        w.translate.setChecked(True)
        qtbot.waitUntil(started.is_set)
        w.offset_boxes[1].setValue(850)
        w.offset_boxes[0].setValue(-100)
        replacement = tmp_path / "english.srt"
        Timeline([Cue(0, 2000, "New track")]).export(str(replacement))
        w.load_subtitles(str(replacement), 0)
        gate.set()
        qtbot.waitUntil(lambda: w.read_completed[0] and bool(w.timelines[1].cues) and not w.jobs)
        assert [cue.text for cue in w.timelines[1].cues] == ["ET New track"]
        assert w.timelines[1].offset == 850
        assert w.timelines[0].offset == -100
    finally:
        gate.set()
        w.close()


def test_translated_track_has_a_source_and_can_be_reselected(qtbot, tmp_path, monkeypatch):
    settings = Settings(tmp_path / "prefs")
    settings.data.update(languages_chosen=True, primary_language="en", secondary_language="et")
    w = Window(settings)
    qtbot.addWidget(w)
    monkeypatch.setattr(services.Translator, "translate", lambda *_: "Tere")
    w.timelines[0] = Timeline([Cue(0, 2000, "Hello")])
    w.translate.setChecked(True)
    qtbot.waitUntil(lambda: bool(w.timelines[1].cues))
    combo = w.track_boxes[1]
    translated = combo.currentIndex()
    assert combo.currentText() == "Translated from English"
    combo.setCurrentIndex(0)
    combo.activated.emit(0)
    assert not w.timelines[1].cues and not w.translate.isChecked()
    combo.setCurrentIndex(translated)
    combo.activated.emit(translated)
    qtbot.waitUntil(lambda: bool(w.timelines[1].cues))
    assert combo.currentIndex() == translated and w.translate.isChecked()
    w.close()


def test_connect_account_from_search_and_retry(qtbot, tmp_path, monkeypatch):
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication, QInputDialog
    from llplayer.app import SettingsDialog

    w = Window(Settings(tmp_path / "settings.json"))
    qtbot.addWidget(w)
    w.show()
    w.media_path = "Backrooms.2026.mkv"
    dlg = w.download_subtitles(0)
    assert dlg.findChild(QListWidget).count() == 0
    monkeypatch.setattr(QInputDialog, "getText", lambda *args: ("test-only", True))

    def login(provider, _name, _password):
        provider.base = "https://vip-api.opensubtitles.com/api/v1"
        return "test-token"

    calls = []
    def search(provider, title, language):
        calls.append((title, language, provider.base, provider.headers.get("Authorization")))
        return [{"attributes": {"files": [{"file_name": "release.srt", "file_id": 42}]}}]

    monkeypatch.setattr(services.OpenSubtitles, "login", login)
    monkeypatch.setattr(services.OpenSubtitles, "search", search)
    def configure():
        settings_dialog = QApplication.activeModalWidget()
        assert isinstance(settings_dialog, SettingsDialog)
        assert settings_dialog.sections.currentItem().text() == "Downloads"
        settings_dialog.fields["opensubtitles_key"].setText("test-only")
        settings_dialog.login_opensubtitles()
        qtbot.waitUntil(lambda: settings_dialog.fields["opensubtitles_token"].text() == "test-token")
        settings_dialog.commit()
    QTimer.singleShot(50, configure)
    next(b for b in dlg.findChildren(QPushButton) if b.text() == "Connect OpenSubtitles…").click()
    qtbot.waitUntil(lambda: dlg.findChild(QListWidget).count() == 1)
    assert calls == [("Backrooms", "en", "https://vip-api.opensubtitles.com/api/v1", "Bearer test-token")]
    w.close()


def test_fallback_prefers_embedded_and_survives_per_movie_off(qtbot, tmp_path, monkeypatch):
    prefs = Settings(tmp_path / "prefs")
    prefs.data.update(languages_chosen=True, primary_language="en", secondary_language="et", auto_translate=True)
    w = Window(prefs)
    qtbot.addWidget(w)
    monkeypatch.setattr(services, "subtitle_tracks", lambda _: [])
    monkeypatch.setattr(services, "extract_subtitles", lambda _, index, **kwargs: Timeline([Cue(0, 2000, str(index))]))
    monkeypatch.setattr(services.Translator, "translate", lambda *_: "Tere")
    english = dict(index=2, title="English", language="eng", codec="srt")
    estonian = dict(index=3, title="Estonian", language="est", codec="srt")
    try:
        w.set_tracks([english, estonian])
        qtbot.waitUntil(lambda: not w.jobs)
        assert w.track_boxes[1].currentData() == 3
        assert w.track_sources[1].text() == "Included in movie"
        assert not w.translation_enabled
        w.open_media(str(tmp_path / "next.mkv"))
        qtbot.waitUntil(lambda: not w.jobs)
        w.set_tracks([english])
        qtbot.waitUntil(lambda: bool(w.timelines[1].cues))
        assert w.track_sources[1].text() == "Translated from English"
        menu = w.change_buttons[1].menu()
        menu.aboutToShow.emit()
        next(a for a in menu.actions() if a.text() == "Off").trigger()
        assert not w.translate.isChecked()
        assert w.track_sources[1].text() == "Off"
        assert prefs.data["auto_translate"]
    finally:
        w.close()
