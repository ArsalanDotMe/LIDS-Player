"""Generate synthetic common-format samples with a development FFmpeg.

LLPLAYER_FIXTURE_FFMPEG selects an encoder-enabled FFmpeg. It is used only to
generate test files and must never be substituted for the audited bundle tools.
"""
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tests'))
from format_cases import CASES
from llplayer.services import ffmpeg


def main():
    encoder = os.environ.get('LLPLAYER_FIXTURE_FFMPEG', ffmpeg())
    folder = ROOT / 'artifacts/formats'
    folder.mkdir(parents=True, exist_ok=True)
    # VideoToolbox encoders are available on macOS. Development FFmpeg builds
    # elsewhere can use libx264/libx265 to produce the same playback inputs.
    codecs = dict(h264='h264_videotoolbox' if sys.platform == 'darwin' else 'libx264',
                  hevc='hevc_videotoolbox' if sys.platform == 'darwin' else 'libx265',
                  vp8='libvpx', vp9='libvpx-vp9', av1='libsvtav1',
                  theora='libtheora', flv1='flv')
    for name, video, audio in CASES:
        ten_bit = '10bit' in name or name.startswith('hevc10')
        pixel_format = 'yuv420p10le' if ten_bit else 'yuv420p'
        if video == 'prores':
            pixel_format = 'yuv422p10le'
        extra = []
        if video in ('h264', 'hevc') and sys.platform == 'darwin':
            extra += ['-allow_sw', '1']
        if video == 'hevc' and name.endswith('.mp4'):
            extra += ['-tag:v', 'hvc1']
        if video in ('vp8', 'vp9'):
            extra += ['-deadline', 'realtime', '-cpu-used', '8', '-b:v', '500k']
            if ten_bit:
                extra += ['-profile:v', '2']
        if video == 'av1':
            extra += ['-preset', '12', '-crf', '45']
        if video == 'mpeg2video':
            extra += ['-b:v', '800k']
        audio_encoder = dict(opus='libopus', vorbis='libvorbis', mp3='libmp3lame').get(audio, audio)
        if audio in ('ac3', 'eac3', 'dca'):
            extra += ['-ac', '6']
        if audio == 'dca':
            extra += ['-strict', '-2']
        subprocess.run([encoder, '-nostdin', '-y', '-loglevel', 'error',
                        '-f', 'lavfi', '-i', 'testsrc2=size=320x240:rate=24',
                        '-f', 'lavfi', '-i', 'sine=frequency=440:sample_rate=48000',
                        '-t', '8', '-c:v', codecs.get(video, video), '-pix_fmt', pixel_format,
                        *extra, '-c:a', audio_encoder, '-threads', '2', str(folder / name)], check=True)
        print(name, flush=True)


if __name__ == '__main__':
    main()
