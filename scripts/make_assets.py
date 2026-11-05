"""Render the authored SVG icon and generate a deterministic test tone.

No original LLPlayer assets, recordings, fonts, speech models or TTS voices are
used. The tone exercises audio transport, not speech-recognition accuracy.
"""
import math
from pathlib import Path
import struct
import wave
from PySide6.QtCore import Qt
from PySide6.QtGui import QImage, QPainter
from PySide6.QtSvg import QSvgRenderer

ROOT = Path(__file__).resolve().parents[1]


def main():
    folder = ROOT / 'llplayer/assets'
    image = QImage(512, 512, QImage.Format.Format_ARGB32)
    image.fill(Qt.GlobalColor.transparent)
    painter = QPainter(image)
    QSvgRenderer(str(folder / 'icon.svg')).render(painter)
    painter.end()
    if not image.save(str(folder / 'icon.png')):
        raise RuntimeError('Could not save icon')
    fixture = ROOT / 'tests/fixtures/tone.wav'
    fixture.parent.mkdir(exist_ok=True)
    rate = 16000
    with wave.open(str(fixture), 'wb') as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(rate)
        output.writeframes(b''.join(struct.pack('<h', round(5000 * math.sin(2 * math.pi * 440 * n / rate))) for n in range(rate * 2)))


if __name__ == '__main__':
    main()
