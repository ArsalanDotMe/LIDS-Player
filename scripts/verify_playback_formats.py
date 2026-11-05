"""Verify the packaged player against all synthetic format fixtures."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tests'))
from format_cases import CASES


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('executable', type=Path)
    parser.add_argument('--mode', choices=('default', 'software', 'both'), default='both')
    args = parser.parse_args()
    failures = []
    modes = ('default', 'software') if args.mode == 'both' else (args.mode,)
    for mode in modes:
        folder = ROOT / 'artifacts/format-smoke' / mode
        folder.mkdir(parents=True, exist_ok=True)
        env = dict(os.environ)
        env.pop('QT_FFMPEG_DECODING_HW_DEVICE_TYPES', None)
        if mode == 'software':
            env['QT_FFMPEG_DECODING_HW_DEVICE_TYPES'] = ','
        for name, _video, _audio in CASES:
            source = ROOT / 'artifacts/formats' / name
            if not source.is_file():
                raise SystemExit(f'Missing fixture: {source}')
            report = folder / (name + '.json')
            report.unlink(missing_ok=True)
            # Decode audio for verification without playing test tones aloud.
            report.with_suffix('.settings.json').write_text(json.dumps({'default_volume': 0}))
            try:
                result = subprocess.run([str(args.executable.resolve()), str(source), '--position', '2000',
                                         '--smoke-test', str(report)], env=env, capture_output=True, timeout=30)
                report.with_suffix('.log').write_bytes(result.stdout + result.stderr)
                data = json.loads(report.read_text()) if report.is_file() else {}
                passed = (result.returncode == 0 and data.get('valid_video_image')
                          and data.get('video_frame_count', 0) >= 4
                          and data.get('last_video_frame_us', 0) >= 2_000_000
                          and data.get('audio_decoded_bytes', 0) > 0 and not data.get('error'))
            except subprocess.TimeoutExpired:
                passed = False
            print(f'{mode}: {name}: {"PASS" if passed else "FAIL"}', flush=True)
            if not passed:
                failures.append((mode, name))
    if failures:
        raise SystemExit(f'Playback failures: {failures}')
    print(f'Passed {len(modes) * len(CASES)} packaged playback checks.')


if __name__ == '__main__':
    main()
