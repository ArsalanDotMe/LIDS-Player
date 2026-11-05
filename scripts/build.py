"""Build a native app after checking its FFmpeg and PyAV licensing inputs.

This is a technical gate, not legal approval for public distribution. Read
THIRD_PARTY_NOTICES.md and docs/building.md before shipping a bundle.
"""
import argparse
import os
from pathlib import Path
import subprocess
import sys
from check_licenses import inspect_native_libraries

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--ffmpeg', type=Path, default=ROOT / ('.tools/ffmpeg/bin/ffmpeg.exe' if sys.platform == 'win32' else '.tools/ffmpeg/bin/ffmpeg'),
                        help='Audited LGPL-only FFmpeg executable to bundle')
    args = parser.parse_args()
    executable = args.ffmpeg.resolve()
    if not executable.is_file():
        raise SystemExit('Supply an audited LGPL-only FFmpeg executable with --ffmpeg.')
    version = subprocess.run([str(executable), '-version'], capture_output=True, text=True, check=True)
    legal = subprocess.run([str(executable), '-L'], capture_output=True, text=True, check=True)
    config = version.stdout + version.stderr
    if any(flag in config.split() for flag in ('--enable-gpl', '--enable-nonfree', '--enable-libx264', '--enable-libx265')):
        raise SystemExit('The FFmpeg executable has uncleared GPL/nonfree codec flags. Refusing to package it.')
    if 'GNU Lesser General Public' not in legal.stdout + legal.stderr:
        raise SystemExit('The FFmpeg executable did not report an LGPL license.')
    result = inspect_native_libraries()
    if result['blockers']:
        raise SystemExit('\n'.join(result['blockers']))
    subprocess.run([sys.executable, str(ROOT / 'scripts/collect_notices.py')], check=True)
    subprocess.run([sys.executable, str(ROOT / 'scripts/check_licenses.py')], check=True)
    env = dict(os.environ, LLPLAYER_BUILD_FFMPEG=str(executable))
    subprocess.run([sys.executable, '-m', 'PyInstaller', '--noconfirm', '--clean',
                    str(ROOT / 'scripts/llplayer.spec')], cwd=ROOT, env=env, check=True)
    # Post-build check catches auto-collected GPL-only Qt components and codecs.
    for path in (ROOT / 'dist').rglob('*'):
        if path.is_file() and any(name in path.name.lower() for name in ('virtualkeyboard', 'libx264', 'libx265', 'qtcharts', 'qtdatavisualization', 'qtgraphs', 'qtquick3d')):
            raise SystemExit(f'Unexpected restricted component in output: {path}')
    bundle = ROOT / 'dist' / ('LIDS Player.app' if sys.platform == 'darwin' else 'LIDS Player')
    subprocess.run([sys.executable, str(ROOT / 'scripts/check_bundle.py'), str(bundle)], check=True)
    print('Native licensing checks passed. This bundle still contains separately licensed LGPL components.')


if __name__ == '__main__':
    main()
