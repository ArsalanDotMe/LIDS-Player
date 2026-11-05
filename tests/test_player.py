from pathlib import Path
import os
import pytest
from PySide6.QtCore import Qt
from PySide6.QtMultimedia import QMediaPlayer
from llplayer.app import Window
from llplayer.core import Cue, Timeline, Settings
from llplayer import services


@pytest.fixture
def window(qtbot, tmp_path):
    widget = Window(Settings(tmp_path / 'settings.json'))
    qtbot.addWidget(widget)
    widget.show()
    yield widget
    widget.close()


def test_dual_subtitles_search_seek_and_copy(window, qtbot):
    window.timelines = [Timeline([Cue(0, 2000, 'Hello world'), Cue(3000, 5000, 'Second line')]),
                        Timeline([Cue(0, 2000, 'こんにちは')])]
    window.tick()
    assert window.labels[0].text() == 'Hello world'
    assert window.labels[1].text() == 'こんにちは'
    window.refresh_sidebar()
    assert window.transcript_model.rowCount() == 2
    window.search.setText('second')
    assert window.transcript_model.rowCount() == 1
    window.copy_subtitles()
    from PySide6.QtWidgets import QApplication
    assert QApplication.clipboard().text() == 'Hello world\nこんにちは'
    window.set_offset(0, 2500)
    assert window.labels[0].text() == ''


def test_real_media_playback(window, qtbot):
    source = Path(__file__).parent.parent / 'artifacts' / 'test-video.mp4'
    if not source.exists():
        pytest.skip('Run scripts/make_fixture.py first')
    errors = []
    frames = []
    window.player.errorOccurred.connect(lambda *args: errors.append(args))
    window.video.video_item.videoSink().videoFrameChanged.connect(lambda frame: frames.append(frame.isValid()))
    window.open_media(str(source))
    qtbot.waitUntil(lambda: window.player.position() > 500, timeout=15000)
    assert window.player.duration() >= 7000
    qtbot.waitUntil(lambda: any(frames), timeout=5000)
    window.load_subtitles(str(source.parent / 'primary.srt'), 0)
    window.load_subtitles(str(source.parent / 'secondary.srt'), 1)
    qtbot.waitUntil(lambda: len(window.timelines[1].cues) == 3, timeout=5000)
    window.player.pause()
    window.player.setPosition(3500)
    qtbot.waitUntil(lambda: abs(window.player.position() - 3500) < 200, timeout=5000)
    window.player.setPlaybackRate(1.5)
    assert window.player.playbackRate() == 1.5
    assert not errors
    qtbot.wait(300)
    window.grab().save(str(source.parent / 'macos-player.png'))


def test_av1_playback_and_seek(window, qtbot):
    source = Path(os.environ.get('LLPLAYER_TEST_AV1', 'artifacts/av1-10bit.mkv'))
    if not source.is_file():
        pytest.skip('Set LLPLAYER_TEST_AV1 to a local AV1 file')
    frames = []
    sink = window.video.video_item.videoSink()
    sink.videoFrameChanged.connect(lambda frame: frames.append(frame.startTime()) if frame.isValid() else None)
    window.open_media(str(source))
    qtbot.waitUntil(lambda: len(set(frames)) >= 5, timeout=15000)
    window.player.setPosition(60000)
    qtbot.waitUntil(lambda: any(59_000_000 <= time <= 65_000_000 for time in frames), timeout=15000)
    window.player.pause()
    assert sink.videoFrame().isValid()
    assert not sink.videoFrame().toImage().isNull()
    assert not window.player.errorString()


def test_stale_track_results_are_ignored(window, qtbot, monkeypatch):
    import time
    def slow_load(_path, **_kwargs):
        time.sleep(.15)
        return Timeline([Cue(0, 1000, 'stale')])
    monkeypatch.setattr(Timeline, 'load', slow_load)
    window.load_subtitles('old.srt', 0)
    window.select_track(0, 0)
    qtbot.wait(300)
    assert not window.timelines[0].cues


def test_embedded_subtitles():
    source = Path(__file__).parent.parent / 'artifacts' / 'test-video.mp4'
    if not source.exists():
        pytest.skip('Run scripts/make_fixture.py first')
    tracks = services.subtitle_tracks(str(source))
    assert len(tracks) == 1
    timeline = services.extract_subtitles(str(source), tracks[0]['index'])
    assert timeline.cues[0].text == 'Welcome to LLPlayer.'
    assert timeline.cues[0].start == 0


def test_pgs_bitmap_palette_and_clear():
    import io
    from PIL import Image
    source = Path(__file__).parent.parent / 'artifacts' / 'bitmap.sup'
    if not source.exists():
        pytest.skip('Run scripts/make_bitmap_fixture.py first')
    timeline = services.extract_subtitles(str(source), 0)
    assert len(timeline.cues) == 1
    cue = timeline.cues[0]
    assert (cue.start, cue.end) == (1000, 4000)
    image = Image.open(io.BytesIO(cue.image))
    assert image.size == (120, 30)
    assert image.getpixel((5, 5)) == (255, 255, 255, 255)


def test_loading_track_disables_generated_replacement(window, qtbot, tmp_path):
    source = tmp_path / 'manual.srt'
    Timeline([Cue(0, 2000, 'Manual subtitle')]).export(str(source))
    window.translate.setChecked(True)
    window.load_subtitles(str(source), 1)
    qtbot.waitUntil(lambda: bool(window.timelines[1].cues), timeout=2000)
    assert not window.translation_enabled
    assert window.timelines[1].cues[0].text == 'Manual subtitle'


def test_position_and_size_shortcuts(window):
    old = window.settings.data['font_size']
    action = next(action for action in window.actions if action.text() == 'Larger subtitles')
    action.trigger()
    assert window.settings.data['font_size'] == old + 2
    window.focus_search()
    assert window.sidebar.isVisible()


def test_delay_survives_loading(window, qtbot, tmp_path):
    source = tmp_path / 'delayed.srt'
    Timeline([Cue(0, 2000, 'Delayed subtitle')]).export(str(source))
    window.offset_boxes[0].setValue(500)
    window.load_subtitles(str(source), 0)
    qtbot.waitUntil(lambda: bool(window.timelines[0].cues), timeout=2000)
    assert window.timelines[0].offset == 500
    window.tick()
    assert window.labels[0].text() == ''


def test_transcript_word_lookup_respects_language_and_timing(window, qtbot, monkeypatch):
    from PySide6.QtCore import QPoint
    from PySide6.QtWidgets import QTextBrowser

    received = []
    def translate(translator, word):
        received.append((word, translator.settings["source"], translator.settings["target"]))
        return "quiet"
    monkeypatch.setattr(services.Translator, "translate", translate)
    window.timelines = [Timeline([Cue(1250, 3000, "The room was quiet.")]),
                        Timeline([Cue(1000, 2850, "Calme ici.")])]
    window.set_offset(1, 100)
    window.search.setText("room")
    assert window.transcript_model.rowCount() == 1
    rect = window.cue_list.visualRect(window.transcript_model.index(0, 0))
    qtbot.mouseClick(window.cue_list.viewport(), Qt.MouseButton.LeftButton,
                     pos=rect.topLeft() + QPoint(74, 17))
    qtbot.waitUntil(lambda: received == [("Calme", "fr", "en")])
    result = window.lookup_dialog.findChild(QTextBrowser)
    qtbot.waitUntil(lambda: result.toPlainText() == "quiet")
    window.lookup_dialog.close()


def test_transcript_keeps_reading_position_until_follow_resumes(window, qtbot):
    window.timelines[1] = Timeline([Cue(i * 1000, (i + 1) * 1000, f"Line {i}") for i in range(80)])
    window.refresh_sidebar()
    window.cue_list.setFocus()
    qtbot.keyClick(window.cue_list, Qt.Key.Key_PageDown)
    reading_row = window.cue_list.currentIndex().row()
    assert window.back_to_line.isVisible()
    window.highlight_transcript(55000)
    window.refresh_sidebar()
    assert window.cue_list.currentIndex().row() == reading_row
    window.back_to_line.click()
    window.highlight_transcript(55000)
    assert window.cue_list.currentIndex().row() == 55
    assert not window.back_to_line.isVisible()


def test_compact_transcript_and_empty_search(window, qtbot):
    window.resize(720, 580)
    qtbot.waitUntil(lambda: window.splitter.orientation() == Qt.Orientation.Vertical)
    window.search.setText("No such dialogue")
    assert window.transcript_empty.isVisible()
    assert window.transcript_empty.text() == "No matching lines."
    window.resize(1100, 710)
    qtbot.waitUntil(lambda: window.splitter.orientation() == Qt.Orientation.Horizontal)


def test_subtitle_sheets_can_be_dismissed_without_losing_delay(window, qtbot):
    from PySide6.QtWidgets import QPushButton
    panel = window.track_dialog
    panel.show()
    window.offset_boxes[1].setValue(350)
    search = window.download_subtitles(1)
    qtbot.mouseClick(search.findChild(QPushButton, "close"), Qt.MouseButton.LeftButton)
    assert not search.isVisible() and panel.isVisible()
    qtbot.mouseClick(panel.findChild(QPushButton, "close"), Qt.MouseButton.LeftButton)
    assert not panel.isVisible()
    panel.show()
    window.timing_dialog.show()
    window.offset_boxes[1].setFocus()
    qtbot.keyClick(window.offset_boxes[1], Qt.Key.Key_Escape)
    assert not window.timing_dialog.isVisible() and panel.isVisible()
    qtbot.keyClick(panel, Qt.Key.Key_Escape)
    assert not panel.isVisible()
    assert window.timelines[1].offset == 350
