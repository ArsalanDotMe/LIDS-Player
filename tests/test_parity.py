import io
from pathlib import Path
import threading
import time
from PIL import Image, ImageDraw, ImageFont
import pytest
from PySide6.QtCore import Qt
from PySide6.QtGui import QTextCursor
from llplayer.app import Window, SettingsDialog
from llplayer.core import Settings, Timeline, Cue, DEFAULT_SHORTCUTS
from llplayer import services
from llplayer.subtitle_text import SubtitleLabel, styled_ass, token_at
from llplayer.native_tools import executable


@pytest.fixture
def window(qtbot, tmp_path):
    instance = Window(Settings(tmp_path / 'settings.json'))
    qtbot.addWidget(instance)
    instance.show()
    yield instance
    for extra in instance.extra_windows:
        extra.close()
    instance.close()


def test_ass_styles_and_escaping(window):
    cue = Cue(0, 3000, 'Bold red <img>', markup=styled_ass(r'{\b1}Bold {\b0\1c&H0000FF&}red <img>'))
    window.timelines[0] = Timeline([cue])
    window.tick()
    assert window.labels[0].text() == 'Bold red <img>'
    cursor = QTextCursor(window.labels[0].document())
    cursor.setPosition(1)
    assert cursor.charFormat().fontWeight() >= 600
    cursor.setPosition(7)
    assert cursor.charFormat().foreground().color().name() == '#ff0000'
    assert '&lt;img&gt;' in styled_ass('<img>')
    assert '<b>' not in styled_ass(r'{\bord2}ordinary')


def test_word_click_and_drag_selection(qtbot):
    label = SubtitleLabel('Hello world')
    qtbot.addWidget(label)
    label.resize(500, 90)
    label.show()
    words = []
    label.wordClicked.connect(words.append)
    cursor = QTextCursor(label.document())
    cursor.setPosition(2)
    point = label.cursorRect(cursor).center()
    qtbot.mouseClick(label.viewport(), Qt.MouseButton.LeftButton, pos=point)
    assert words == ['Hello']
    cursor.setPosition(0)
    start = label.cursorRect(cursor).center()
    cursor.setPosition(5)
    end = label.cursorRect(cursor).center()
    qtbot.mousePress(label.viewport(), Qt.MouseButton.LeftButton, pos=start)
    qtbot.mouseMove(label.viewport(), pos=end)
    qtbot.mouseRelease(label.viewport(), Qt.MouseButton.LeftButton, pos=end)
    assert len(words) == 1


def test_native_japanese_segmentation():
    if not executable('llplayer-native'):
        pytest.skip('Build native language helper first')
    word = token_at('私は日本語を勉強しています', 4)
    assert word == '日本語'
    assert token_at('hello café', 7) == 'café'


def subtitle_image():
    image = Image.new('RGB', (900, 140), 'white')
    ImageDraw.Draw(image).text((20, 35), 'Learning with subtitles', fill='black', font=ImageFont.load_default(size=45))
    data = io.BytesIO()
    image.save(data, format='PNG')
    return data.getvalue()


def test_native_ocr():
    if not executable('llplayer-native'):
        pytest.skip('Build native language helper first')
    text = services.ocr_image(subtitle_image(), 'eng', 'Apple Vision')
    assert 'Learning with subtitles' in text


def test_tesseract_ocr():
    if not executable('tesseract'):
        pytest.skip('Tesseract unavailable')
    assert 'Learning with subtitles' in services.ocr_image(subtitle_image(), 'eng', 'Tesseract')


def test_bitmap_publishes_before_final_result():
    source = Path(__file__).parents[1] / 'artifacts/bitmap.sup'
    events = []
    cancel = threading.Event()
    timeline = services.extract_subtitles(str(source), 0, emit=events.append, cancel=cancel)
    assert events[0].image
    assert events[0].end > 4000  # First frame is displayable before its clear event.
    assert events[-1].end == 4000
    assert timeline.cues[0].end == 4000
    assert not cancel.is_set()


def test_streaming_track_updates_sidebar_before_completion(window, qtbot, monkeypatch, tmp_path):
    source = tmp_path / 'stream.sup'
    source.touch()
    completed = threading.Event()
    monkeypatch.setattr(services, 'subtitle_tracks', lambda _path: [{'index': 0}])
    def extract(_path, _index, emit=None, cancel=None):
        cue = Cue(0, 2000, 'First line')
        emit(cue)
        completed.wait(30)
        return Timeline([cue, Cue(3000, 4000, 'Later line')])
    monkeypatch.setattr(services, 'extract_subtitles', extract)
    window.load_subtitles(str(source), 0)
    try:
        qtbot.waitUntil(lambda: window.transcript_model.rowCount() == 1, timeout=10000)
        assert not completed.is_set()
    finally:
        completed.set()
    qtbot.waitUntil(lambda: window.transcript_model.rowCount() == 2, timeout=10000)


def test_new_actions_and_visibility(window):
    assert set(DEFAULT_SHORTCUTS) == {action.text() for action in window.actions}
    window.timelines[0] = Timeline([Cue(0, 2000, 'Visible')])
    window.tick()
    window.toggle_subtitles(0)
    assert window.labels[0].text() == ''
    window.toggle_subtitles(0)
    assert window.labels[0].text() == 'Visible'
    window.settings.data.update(subtitle_horizontal=30, subtitle_vertical=20, subtitle_anchor='Top', font_family='Helvetica')
    window.apply_theme()
    assert window.video.placement == (30, 20, 'Top')
    window.reset_subtitle_position()
    assert window.video.placement == (50, 85, 'Center')


def test_settings_exposes_speech_and_style_controls(window, qtbot):
    dialog = SettingsDialog(window.settings, window)
    qtbot.addWidget(dialog)
    assert {'asr_device', 'asr_chunk_seconds', 'asr_gpu', 'ocr_engine', 'font_family', 'subtitle_anchor'} <= set(dialog.fields)
    dialog.fields['asr_chunk_seconds'].setValue(3)
    dialog.fields['ocr_engine'].setCurrentText('Apple Vision')
    dialog.commit()
    assert window.settings.data['asr_chunk_seconds'] == 3
    assert window.settings.data['ocr_engine'] == 'Apple Vision'


def test_provider_profiles_remember_independent_credentials(window, qtbot):
    dialog = SettingsDialog(window.settings, window)
    qtbot.addWidget(dialog)
    dialog.fields['provider'].setCurrentText('OpenAI')
    dialog.fields['model'].setText('test-model')
    dialog.fields['api_key'].setText('first-test-key')
    dialog.fields['provider'].setCurrentText('DeepL')
    assert dialog.fields['endpoint'].text() == 'https://api-free.deepl.com'
    dialog.fields['api_key'].setText('second-test-key')
    dialog.fields['provider'].setCurrentText('OpenAI')
    assert dialog.fields['api_key'].text() == 'first-test-key'
    assert dialog.fields['model'].text() == 'test-model'
    dialog.commit()
    assert window.settings.data['provider_profiles']['DeepL']['api_key'] == 'second-test-key'


def test_secondary_asr_streaming_and_configured_chunk(window, qtbot, monkeypatch):
    window.settings.data.update(asr_track='Secondary', asr_chunk_seconds=3)
    window.source = 'controlled-source'
    received = []
    def transcribe(source, start, duration, settings, emit=None, cancel=None):
        received.append((start, duration))
        cue = Cue(start * 1000, (start + duration) * 1000, 'Generated secondary')
        emit(cue)
        return [cue]
    monkeypatch.setattr(services, 'transcribe_chunk', transcribe)
    window.asr.setChecked(True)
    qtbot.waitUntil(lambda: bool(window.timelines[1].cues), timeout=2000)
    window.asr.setChecked(False)
    assert received[0] == (0, 3)
    assert window.timelines[1].cues[0].text == 'Generated secondary'
    assert not window.timelines[0].cues


def test_secondary_to_primary_translation_and_original_sidebar(window, qtbot, monkeypatch):
    monkeypatch.setattr(services.Translator, 'translate', lambda _self, text, context=(): 'Translated ' + text)
    window.settings.data['translation_track'] = 'Secondary'
    window.timelines[1] = Timeline([Cue(0, 3000, 'Original text')])
    window.translate.setChecked(True)
    qtbot.waitUntil(lambda: bool(window.timelines[0].cues), timeout=2000)
    assert window.timelines[0].cues[0].text == 'Translated Original text'
    window.toggle_original()
    assert 'Original text' in window.transcript_model.index(0, 0).data()
    assert 'Translated' not in window.transcript_model.index(0, 0).data()


def test_nonmodal_word_popup(window, qtbot, monkeypatch):
    monkeypatch.setattr(services.Translator, 'translate', lambda *_args: 'A word definition')
    window.lookup('word')
    qtbot.waitUntil(lambda: window.lookup_dialog.findChild(__import__('PySide6.QtWidgets', fromlist=['QTextBrowser']).QTextBrowser).toPlainText() == 'A word definition', timeout=2000)
    assert not window.lookup_dialog.isModal()
    window.lookup_dialog.close()


def media_path():
    return Path(__file__).parents[1] / 'artifacts/test-video.mp4'


def test_recording_produces_playable_media(window, qtbot, tmp_path):
    import av
    window.open_media(str(media_path()))
    qtbot.waitUntil(lambda: window.player.duration() >= 7000, timeout=10000)
    window.player.pause()
    window.player.setPosition(0)
    output = tmp_path / 'recording.mkv'
    window.playback.start_recording(output)
    qtbot.wait(1400)
    window.playback.stop_recording()
    with av.open(str(output)) as container:
        assert container.streams.video and container.streams.audio
        frame = next(container.decode(video=0))
        assert frame.width == 960
        assert .4 < container.duration / 1_000_000 < 4


def test_audio_delay_reverse_zoom_and_frame_step(window, qtbot):
    from PySide6.QtMultimedia import QMediaPlayer
    window.open_media(str(media_path()))
    qtbot.waitUntil(lambda: window.player.position() > 500, timeout=10000)
    window.adjust_audio_delay(200)
    qtbot.waitUntil(lambda: window.playback.audio_player.playbackState() == QMediaPlayer.PlaybackState.PlayingState, timeout=10000)
    qtbot.wait(400)
    assert abs(window.player.position() - window.playback.audio_player.position() - 200) < 300
    window.player.pause()
    window.player.setPosition(3500)
    window.playback.toggle_reverse()
    qtbot.wait(300)
    assert window.player.position() < 3450
    window.playback.toggle_reverse()
    old = window.player.position()
    window.step_frame(1)
    assert window.player.position() > old
    window.zoom(.4)
    assert window.video.video_item.scale() == 1.4
    window.rotate()
    assert window.video.video_item.rotation() == 90
    window.reset_playback()
    assert window.video.video_item.scale() == 1
    assert window.video.video_item.rotation() == 0
    assert window.playback.audio_delay == 0


def test_non_utf8_and_frame_based_subtitles(tmp_path):
    japanese = tmp_path / 'japanese.srt'
    japanese.write_bytes('1\n00:00:00,000 --> 00:00:02,000\n日本語を勉強しています\n'.encode('cp932'))
    timeline = Timeline.load(str(japanese))
    assert timeline.cues[0].text == '日本語を勉強しています'
    microdvd = tmp_path / 'frames.sub'
    microdvd.write_text('{25}{75}First line|Second line\n')
    cues = Timeline.load(str(microdvd), fps=25).cues
    assert (cues[0].start, cues[0].end) == (1000, 3000)
    assert cues[0].text == 'First line\nSecond line'


def test_opensubtitles_login_search_download_contract(monkeypatch):
    import httpx
    calls = []
    def post(url, **kwargs):
        calls.append((url, kwargs))
        payload = {'token': 'controlled-token'} if url.endswith('/login') else {'link': 'https://example.test/subtitle.srt'}
        return httpx.Response(200, json=payload, request=httpx.Request('POST', url))
    def get(url, **kwargs):
        calls.append((url, kwargs))
        if '/subtitles' in url:
            return httpx.Response(200, json={'data': [{'attributes': {'files': [{'file_id': 123, 'file_name': 'movie.srt'}]}}]}, request=httpx.Request('GET', url))
        return httpx.Response(200, content=b'1\n00:00:00,000 --> 00:00:02,000\nDownloaded text\n', request=httpx.Request('GET', url))
    monkeypatch.setattr(services.httpx, 'post', post)
    monkeypatch.setattr(services.httpx, 'get', get)
    provider = services.OpenSubtitles(dict(__import__('llplayer.core', fromlist=['DEFAULTS']).DEFAULTS, opensubtitles_key='controlled-key'))
    assert provider.login('test-user', 'test-password') == 'controlled-token'
    assert provider.search('Movie', 'ja')[0]['attributes']['files'][0]['file_id'] == 123
    assert b'Downloaded text' in provider.download(123)
    assert calls[1][1]['headers']['Authorization'] == 'Bearer controlled-token'
    assert calls[1][1]['params']['languages'] == 'ja'


def test_downloaded_subtitles_are_loaded(window, qtbot, monkeypatch, tmp_path):
    from PySide6.QtWidgets import QListWidget, QPushButton
    window.media_path = "Movie.mkv"
    window.settings.data['opensubtitles_key'] = 'controlled-key'
    monkeypatch.setattr(services.OpenSubtitles, 'search', lambda *_args: [{'attributes': {'release': 'Movie', 'files': [{'file_id': 1, 'file_name': 'movie.srt'}]}}])
    monkeypatch.setattr(services.OpenSubtitles, 'download', lambda *_args: b'1\n00:00:00,000 --> 00:00:02,000\nDownloaded text\n')
    dialog = window.download_subtitles(1)
    results = dialog.findChild(QListWidget)
    qtbot.waitUntil(lambda: results.count() == 1)
    results.setCurrentRow(0)
    next(b for b in dialog.findChildren(QPushButton) if b.text() == "Load subtitles").click()
    qtbot.waitUntil(lambda: bool(window.timelines[1].cues), timeout=2000)
    assert window.timelines[1].cues[0].text == 'Downloaded text'
    assert not window.timelines[0].cues


def test_clone_preserves_tracks_and_independent_settings(window, qtbot):
    window.timelines = [Timeline([Cue(0, 3000, 'One')]), Timeline([Cue(0, 3000, 'Two')])]
    window.timelines[1].offset = 300
    # A real source activates clone behavior; no file playback is needed here.
    window.source = str(media_path())
    clone = window.new_window(True)
    qtbot.addWidget(clone)
    assert clone.timelines[1].offset == 300
    assert clone.timelines[0].cues[0].text == 'One'
    clone.timelines[0].cues[0].text = 'Changed'
    clone.settings.data['font_size'] = 40
    assert window.timelines[0].cues[0].text == 'One'
    assert window.settings.data['font_size'] != 40
    clone.close()


@pytest.mark.parametrize('codec', ['h264', 'hevc'])
def test_h264_and_hevc_native_playback(window, qtbot, codec):
    path = media_path().parent / (codec + '.mp4')
    if not path.exists():
        pytest.skip('Generate macOS format fixtures first')
    frames = []
    window.video.video_item.videoSink().videoFrameChanged.connect(lambda frame: frames.append(frame.isValid()))
    window.open_media(str(path))
    qtbot.waitUntil(lambda: window.player.position() > 300 and any(frames), timeout=10000)
    assert not window.player.errorString()
    window.player.pause()
    window.player.setPosition(2000)
    qtbot.waitUntil(lambda: abs(window.player.position() - 2000) < 200, timeout=3000)


@pytest.mark.parametrize('name', ['bitmap-dvd.mks', 'bitmap-dvb.ts', 'bitmap-xsub.avi'])
def test_other_bitmap_codecs(name):
    path = media_path().parent / name
    if not path.exists():
        pytest.skip('Generate format fixtures first')
    tracks = services.subtitle_tracks(str(path))
    timeline = services.extract_subtitles(str(path), tracks[0]['index'])
    assert len(timeline.cues) == 1
    cue = timeline.cues[0]
    assert cue.start == 1000
    assert 3900 <= cue.end <= 4100
    assert Image.open(io.BytesIO(cue.image)).size == (120, 30)


def test_seek_to_unindexed_late_bitmap(window, qtbot):
    path = media_path().parent / 'late-bitmap.sup'
    if not path.exists():
        pytest.skip('Generate format fixtures first')
    window.subtitle_sources[0] = (str(path), 0)
    window.read_completed[0] = False
    window.prioritize_subtitles(62000)
    qtbot.waitUntil(lambda: bool(window.timelines[0].active(62000)), timeout=5000)
    assert window.timelines[0].cues[0].start == 61000
    assert window.timelines[0].cues[0].end == 64000


def test_mixed_embedded_styled_and_bitmap_subtitles(window, qtbot):
    path = media_path().parent / 'mixed-subtitles.mkv'
    if not path.exists():
        pytest.skip('Generate format fixtures first')
    window.open_media(str(path))
    qtbot.waitUntil(lambda: len(window.tracks) == 2, timeout=5000)
    window.select_track(0, 1)
    window.select_track(1, 2)
    qtbot.waitUntil(lambda: bool(window.timelines[0].cues) and bool(window.timelines[1].cues), timeout=5000)
    assert '<b>' in window.timelines[0].cues[0].markup
    assert window.timelines[1].cues[0].image
    window.player.pause()
    window.player.setPosition(1500)
    window.tick()
    assert 'Bold' in window.labels[0].text()
    assert window.bitmap_labels[1].isVisible()


def test_disabled_bitmap_cannot_reappear_after_seek(window, qtbot):
    window.subtitle_sources[0] = (str(media_path().parent / 'late-bitmap.sup'), 0)
    window.read_completed[0] = False
    window.select_track(0, 0)
    window.prioritize_subtitles(62000)
    qtbot.wait(300)
    assert window.subtitle_sources[0] is None
    assert not window.timelines[0].cues


def test_loop_rotation_fit_and_live_window_preferences(window):
    loop = next(action for action in window.actions if action.text() == 'Loop media')
    loop.trigger()
    assert window.player.loops() == -1
    loop.trigger()
    assert window.player.loops() == 1
    window.rotate()
    item = window.video.video_item
    rotated = item.mapRectToScene(item.boundingRect())
    assert abs(rotated.width() - window.video.viewport().width()) < 2
    assert abs(rotated.height() - window.video.viewport().height()) < 2
    window.settings.data['always_on_top'] = True
    window.apply_theme()
    assert window.windowFlags() & Qt.WindowType.WindowStaysOnTopHint


def test_bing_unavailable_endpoint_has_actionable_error(monkeypatch):
    import httpx
    client = httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(404)))
    monkeypatch.setattr(services.httpx, 'Client', lambda **kwargs: client)
    from llplayer.core import DEFAULTS
    with pytest.raises(RuntimeError, match='Use Azure'):
        services.Translator(dict(DEFAULTS,provider='Bing')).translate('Hello')


def test_resize_shortcuts_handle_both_text_and_bitmap(window):
    image = subtitle_image()
    window.timelines = [Timeline([Cue(0, 3000, 'Text')]), Timeline([Cue(0, 3000, image=image, canvas=(960, 540))])]
    old_text = window.settings.data['font_size']
    old_bitmap = window.settings.data['secondary_bitmap_scale']
    action = next(action for action in window.actions if action.text() == 'Larger subtitles')
    action.trigger()
    assert window.settings.data['font_size'] == old_text + 2
    assert window.settings.data['secondary_bitmap_scale'] == old_bitmap + 4
    assert window.settings.data['bitmap_scale'] == 100


def test_adaptive_video_and_audio_streams(window, qtbot, tmp_path):
    from PySide6.QtMultimedia import QMediaPlayer
    source = services.ResolvedURL(str(media_path().parent / 'video-only.mp4'), str(media_path().parent / 'audio-only.m4a'))
    window.open_media(source)
    qtbot.waitUntil(lambda: window.player.position() > 300 and window.playback.audio_player.playbackState() == QMediaPlayer.PlaybackState.PlayingState, timeout=10000)
    assert window.player.activeAudioTrack() == -1
    assert window.playback.audio_player.activeAudioTrack() == 0
    assert window.playback.audio_player.audioOutput() == window.audio
    window.player.setPlaybackRate(1.5)
    assert window.playback.audio_player.playbackRate() == 1.5
    output = tmp_path / 'audio.wav'
    services.audio_chunk(source, 0, 1, output)
    import wave
    with wave.open(str(output)) as audio:
        assert audio.getframerate() == 16000
        assert audio.getnchannels() == 1
        assert 0.95 <= audio.getnframes() / audio.getframerate() <= 1.05
        assert any(audio.readframes(audio.getnframes()))


def test_custom_aspect_and_audio_device_settings(window, qtbot):
    from PySide6.QtMultimedia import QMediaDevices
    window.settings.data.update(video_aspect='Custom', custom_aspect='4:3', default_volume=65)
    window.apply_theme()
    size = window.video.video_item.size()
    assert abs(size.width() / size.height() - 4/3) < 0.001
    dialog = SettingsDialog(window.settings, window)
    qtbot.addWidget(dialog)
    devices = QMediaDevices.audioOutputs()
    if devices:
        identifier = bytes(devices[0].id()).hex()
        dialog.fields['audio_device'].setCurrentIndex(dialog.fields['audio_device'].findData(identifier))
    dialog.commit()
    window.apply_theme()
    if devices:
        assert bytes(window.audio.device().id()).hex() == window.settings.data['audio_device']
    window.settings.data['audio_device'] = 'disconnected-device'
    window.apply_audio_device()
    assert window.audio.device().id() == QMediaDevices.defaultAudioOutput().id()
    window.toggle_aspect_ratio()
    assert window.video.aspect == 'Stretch'
    window.toggle_aspect_ratio()
    assert window.video.aspect == 'Auto'


def test_ocr_track_preserves_bitmap_canvas(window, qtbot, monkeypatch):
    from PySide6.QtWidgets import QInputDialog
    cue = Cue(1000, 4000, image=subtitle_image(), canvas=(1920, 1080))
    window.timelines[0] = Timeline([cue])
    monkeypatch.setattr(QInputDialog, 'getItem', lambda *args, **kwargs: ('Primary', True))
    monkeypatch.setattr(services, 'ocr_image', lambda *args: 'Recognized words')
    window.ocr_track()
    qtbot.waitUntil(lambda: window.timelines[0].cues[0].text == 'Recognized words', timeout=3000)
    assert window.timelines[0].cues[0].canvas == (1920, 1080)
    assert window.timelines[0].cues[0].image == cue.image
