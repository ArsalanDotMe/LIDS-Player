"""Create a deterministic video with audio and embedded subtitles."""
from pathlib import Path
import subprocess
from llplayer.services import ffmpeg
folder = Path(__file__).resolve().parents[1] / 'artifacts'
folder.mkdir(exist_ok=True)
(folder / 'primary.srt').write_text('1\n00:00:00,000 --> 00:00:02,500\nWelcome to LLPlayer.\n\n2\n00:00:03,000 --> 00:00:05,500\nSelect a word to look it up.\n\n3\n00:00:06,000 --> 00:00:08,000\nLearn at your own pace.\n')
(folder / 'secondary.srt').write_text('1\n00:00:00,000 --> 00:00:02,500\nBienvenue dans LLPlayer.\n\n2\n00:00:03,000 --> 00:00:05,500\nSélectionnez un mot pour le rechercher.\n\n3\n00:00:06,000 --> 00:00:08,000\nApprenez à votre rythme.\n')
subprocess.run([ffmpeg(), '-y', '-loglevel', 'error', '-f', 'lavfi', '-i', 'testsrc2=size=960x540:rate=24',
                '-f', 'lavfi', '-i', 'sine=frequency=440:sample_rate=48000', '-i', str(folder / 'primary.srt'),
                '-t', '8', '-map', '0:v', '-map', '1:a', '-map', '2:s', '-c:v', 'mpeg4', '-pix_fmt', 'yuv420p',
                '-c:a', 'aac', '-c:s', 'mov_text', str(folder / 'test-video.mp4')], check=True)

for kind, suffix in [('video', 'mp4'), ('audio', 'm4a')]:
    subprocess.run([ffmpeg(), '-nostdin', '-y', '-loglevel', 'error', '-i', str(folder / 'test-video.mp4'),
                    '-map', '0:v' if kind == 'video' else '0:a', '-c', 'copy', str(folder / (kind + '-only.' + suffix))], check=True)
