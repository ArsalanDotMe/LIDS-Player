"""Collect matching LGPL sources alongside release binaries."""
import hashlib
import json
from pathlib import Path
import tarfile

from download_source import fetch

ROOT = Path(__file__).resolve().parents[1]
VERSION = '6.12.0'


def main():
    output = ROOT / 'release-sources'
    sources = output / 'LGPL-sources'
    sources.mkdir(parents=True, exist_ok=True)
    base = f'https://download.qt.io/official_releases/qt/6.12/{VERSION}/submodules'
    urls = [f'{base}/{module}-everywhere-src-{VERSION}.tar.xz'
            for module in ('qtbase', 'qtsvg', 'qtmultimedia', 'qtshadertools')]
    urls.append(f'https://download.qt.io/official_releases/QtForPython/pyside6/PySide6-{VERSION}-src/pyside-setup-everywhere-src-{VERSION}.tar.xz')
    records = []
    for url in urls:
        target = sources / url.rsplit('/', 1)[-1]
        digest = fetch(url, target)
        records.append(dict(source=url, sha256=digest, file=target.name))
    (sources / 'SOURCES.json').write_text(json.dumps(records, indent=2) + '\n')
    (sources / 'README.txt').write_text(
        'Matching unmodified Qt/PySide6/Shiboken source for the preview binaries.\n'
        'Custom FFmpeg and dav1d source archives and build manifests are inside each app,\n'
        'under third_party/sources. The release repository includes all build scripts.\n'
        'Qt libraries remain dynamically linked and may be replaced with compatible builds.\n'
        'No restriction on reverse engineering for debugging library modifications is imposed.\n')
    for file in [*(ROOT / 'scripts').glob('*.py'), ROOT / 'scripts/llplayer.spec', ROOT / 'uv.lock', ROOT / 'THIRD_PARTY_NOTICES.md']:
        import shutil
        shutil.copy2(file, sources / file.name)
    with tarfile.open(output / 'LGPL-sources.tar.gz', 'w:gz') as archive:
        archive.add(sources, arcname=sources.name)
    # Upload just the archive. Keep collected input files available for inspection.
    print(output / 'LGPL-sources.tar.gz')


if __name__ == '__main__':
    main()
