"""Package a built macOS app in a verified, compressed drag-to-install DMG."""
import argparse
from pathlib import Path
import platform
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--app', type=Path, default=ROOT / 'dist/LIDS Player.app')
    parser.add_argument('--output', type=Path,
                        default=ROOT / f'LIDS-Player-macOS-{platform.machine()}.dmg')
    args = parser.parse_args()
    if sys.platform != 'darwin':
        parser.error('DMG packaging requires macOS.')
    app = args.app.resolve()
    if not (app / 'Contents/Info.plist').is_file():
        parser.error(f'Build the macOS app first: {app}')
    output = args.output.resolve()
    if output.suffix != '.dmg':
        parser.error('--output must end in .dmg')
    output.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(['codesign', '--verify', '--deep', '--strict', str(app)], check=True)
    with tempfile.TemporaryDirectory(prefix='lids-dmg-') as temporary:
        staging = Path(temporary) / 'LIDS Player'
        staging.mkdir()
        subprocess.run(['ditto', str(app), str(staging / app.name)], check=True)
        (staging / 'Applications').symlink_to('/Applications', target_is_directory=True)
        subprocess.run(['hdiutil', 'create', '-volname', 'LIDS Player',
                        '-srcfolder', str(staging), '-fs', 'HFS+', '-format', 'UDZO',
                        '-ov', str(output)], check=True)
    subprocess.run(['hdiutil', 'verify', str(output)], check=True)
    print(f'Created {output}')


if __name__ == '__main__':
    main()
