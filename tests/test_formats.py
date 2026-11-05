"""Exercise decoded output rather than trusting the playback clock."""
import os
from pathlib import Path

import av
import pytest
from PySide6.QtMultimedia import QAudioBufferOutput
from llplayer.app import Window
from llplayer.core import Settings
from format_cases import CASES


@pytest.mark.parametrize('name,video_codec,audio_codec', CASES)
def test_common_format_playback(qtbot, tmp_path, name, video_codec, audio_codec):
    source = Path(__file__).resolve().parents[1] / 'artifacts/formats' / name
    if not source.is_file():
        if os.environ.get('LLPLAYER_REQUIRE_FORMAT_FIXTURES'):
            pytest.fail(f'Missing required format fixture: {name}')
        pytest.skip('Run scripts/make_playback_fixtures.py')
    with av.open(str(source)) as media:
        assert media.streams.video[0].codec_context.name == {'flv1': 'flv'}.get(video_codec, video_codec)
        assert media.streams.audio[0].codec_context.name in (
            ('mp3', 'mp3float') if audio_codec == 'mp3' else (audio_codec,))
        if '10bit' in name or name.startswith('hevc10'):
            assert media.streams.video[0].codec_context.format.name == 'yuv420p10le'
    window = Window(Settings(tmp_path / 'settings.json'))
    qtbot.addWidget(window)
    window.show()
    frames, audio = [], []
    output = QAudioBufferOutput(window)
    window.player.setAudioBufferOutput(output)
    output.audioBufferReceived.connect(lambda buffer: audio.append(bytes(buffer.constData())) if buffer.isValid() else None)
    sink = window.video.video_item.videoSink()
    sink.videoFrameChanged.connect(lambda frame: frames.append(frame.startTime()) if frame.isValid() else None)
    try:
        window.open_media(str(source))
        qtbot.waitUntil(lambda: len(set(frames)) >= 4 and any(any(data) for data in audio), timeout=12000)
        image = sink.videoFrame().toImage()
        assert not image.isNull()
        # The moving test pattern must produce more than one solid colour.
        assert len({image.pixelColor(x, y).rgba() for x in range(20, image.width(), 40)
                    for y in range(20, image.height(), 40)}) > 5
        for position in (4000, 1000):
            frames.clear()
            audio.clear()
            window.player.setPosition(position)
            qtbot.waitUntil(lambda: len(set(frames)) >= 3 and
                           any(position * 1000 <= time < (position + 1500) * 1000 for time in frames)
                           and any(any(data) for data in audio), timeout=10000)
        window.player.pause()
        assert sink.videoFrame().isValid()
        assert not window.player.errorString()
    finally:
        window.close()
