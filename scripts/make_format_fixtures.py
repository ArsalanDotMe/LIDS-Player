"""Generate extra local format fixtures. macOS uses system VideoToolbox encoders."""
from pathlib import Path
import subprocess
import sys
from llplayer.services import ffmpeg

ROOT = Path(__file__).resolve().parents[1]
folder = ROOT / 'artifacts'
folder.mkdir(exist_ok=True)
(folder / 'styled.ass').write_text(r'''[Script Info]
ScriptType: v4.00+
PlayResX: 960
PlayResY: 540
[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,Helvetica,28,&H00FFFFFF,&H00FFFFFF,&H00000000,&H00000000,0,0,0,0,100,100,0,0,1,1,0,2,10,10,20,1
[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
Dialogue: 0,0:00:00.00,0:00:03.00,Default,,0,0,0,,{\b1}Bold {\b0\i1}italic {\i0\u1}underlined {\u0\1c&H0000FF&}red
Dialogue: 0,0:00:03.00,0:00:06.00,Default,,0,0,0,,日本語を勉強しています
''')
subprocess.run([ffmpeg(), '-nostdin', '-y', '-loglevel', 'error', '-i', str(folder / 'test-video.mp4'),
                '-i', str(folder / 'styled.ass'), '-i', str(folder / 'bitmap.sup'), '-map', '0:v', '-map', '0:a', '-map', '1:s', '-map', '2:s',
                '-c', 'copy', str(folder / 'mixed-subtitles.mkv')], check=True)
if sys.platform == 'darwin':
    for codec in ['h264', 'hevc']:
        subprocess.run([ffmpeg(), '-nostdin', '-y', '-loglevel', 'error', '-i', str(folder / 'test-video.mp4'), '-t', '4',
                        '-map', '0:v', '-map', '0:a', '-c:v', codec + '_videotoolbox', '-allow_sw', '1', '-c:a', 'copy',
                        *(['-tag:v', 'hvc1'] if codec == 'hevc' else []), str(folder / (codec + '.mp4'))], check=True)
if (folder / 'h264.mp4').exists():
    subprocess.run([ffmpeg(), '-nostdin', '-y', '-loglevel', 'error', '-i', str(folder / 'h264.mp4'),
                    '-c', 'copy', '-hls_time', '1', '-hls_list_size', '0', '-f', 'hls', str(folder / 'stream.m3u8')], check=True)
# Build tiny bitmap samples using the public AVSubtitle encoder API. This avoids
# losing duration information when transcoding PGS display/clear events.
import os, shlex
prefix = ROOT / '.tools/ffmpeg'
env = dict(os.environ, PKG_CONFIG_PATH=str(prefix / 'lib/pkgconfig'))
flags = shlex.split(subprocess.check_output(['pkg-config', '--cflags', '--libs', 'libavformat', 'libavcodec', 'libavutil'], env=env, text=True))
helper = ROOT / '.tools/bin/subtitle-fixture'
subprocess.run(['cc', str(ROOT / 'native/subtitle_fixture.c'), '-o', str(helper), *flags, '-Wl,-rpath,' + str(prefix / 'lib')], check=True)
for codec, muxer, output in [('dvdsub', 'matroska', 'bitmap-dvd.mks'), ('dvbsub', 'mpegts', 'bitmap-dvb.ts'), ('xsub', 'avi', 'bitmap-xsub.avi')]:
    subprocess.run([str(helper), codec, muxer, str(folder / output)], check=True)
# A late subtitle forces the seek-priority path to use absolute stream times.
import struct
payload = bytearray((folder / 'bitmap.sup').read_bytes())
position = 0
while position < len(payload):
    pts, dts = struct.unpack_from('>II', payload, position + 2)
    struct.pack_into('>II', payload, position + 2, pts + 60 * 90000, dts + 60 * 90000)
    size = struct.unpack_from('>H', payload, position + 11)[0]
    position += 13 + size
(folder / 'late-bitmap.sup').write_bytes(payload)
