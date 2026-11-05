"""Collect installed dependency license texts and pinned upstream notices.

Use --fetch-missing to retrieve absent upstream license documents.
"""
import argparse
from importlib.metadata import distributions, version
from pathlib import Path
import shutil
import sys
import httpx
from packaging.utils import canonicalize_name

ROOT = Path(__file__).resolve().parents[1]
# These are license documents, not implementation code. Keep the exact versions.
UPSTREAM = {
    'ctranslate2': ('4.8.5', 'https://raw.githubusercontent.com/OpenNMT/CTranslate2/v4.8.5/LICENSE'),
    'flatbuffers': ('25.12.19', 'https://raw.githubusercontent.com/google/flatbuffers/v25.12.19/LICENSE'),
    'tokenizers': ('0.23.3', 'https://raw.githubusercontent.com/huggingface/tokenizers/v0.23.3/LICENSE'),
    'python': ('3.12.13', 'https://raw.githubusercontent.com/python/cpython/v3.12.13/LICENSE'),
    'qt-lgpl': ('6.12.0', 'https://raw.githubusercontent.com/qt/qtbase/v6.12.0/LICENSES/LGPL-3.0-only.txt'),
    'qt-gpl-reference': ('6.12.0', 'https://raw.githubusercontent.com/qt/qtbase/v6.12.0/LICENSES/GPL-3.0-only.txt'),
}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--fetch-missing', action='store_true')
    args = parser.parse_args()
    target = ROOT / 'third_party/licenses'
    target.mkdir(parents=True, exist_ok=True)
    records = []
    for dist in sorted(distributions(), key=lambda d: d.metadata['Name'].lower()):
        name = canonicalize_name(dist.metadata['Name'])
        if name == 'llplayer-cross':
            continue
        files = []
        for path in dist.files or []:
            if any(word in path.name.lower() for word in ('license', 'copying', 'notice')):
                original = Path(dist.locate_file(path))
                if original.is_file():
                    output = target / name / str(path).replace('/', '__').replace('\\', '__')
                    output.parent.mkdir(exist_ok=True)
                    shutil.copyfile(original, output)
                    files.append(str(output.relative_to(ROOT)))
        records.append({'package': name, 'version': dist.version, 'files': files})
    for name, (expected_version, url) in UPSTREAM.items():
        package = 'PySide6' if name.startswith('qt-') else name
        actual = '.'.join(map(str, sys.version_info[:3])) if name == 'python' else version(package)
        if actual != expected_version:
            raise SystemExit(f'Re-audit {name}: pinned notices are for {expected_version}, installed version is {actual}')
        output = target / name / 'LICENSE-upstream.txt'
        output.parent.mkdir(exist_ok=True)
        record = {'package': name, 'version': expected_version, 'source': url}
        if not output.exists() and args.fetch_missing:
            try:
                response = httpx.get(url, follow_redirects=True, timeout=30)
                response.raise_for_status()
                output.write_bytes(response.content)
            except httpx.HTTPError as error:
                record['error'] = type(error).__name__
        if output.exists():
            record['file'] = str(output.relative_to(ROOT))
        else:
            record['missing'] = True
        records.append(record)
    for name in ('COPYING.LGPLv2.1', 'COPYING.LGPLv3', 'COPYING.GPLv2', 'COPYING.GPLv3', 'LICENSE.md'):
        path = ROOT / '.tools/ffmpeg-8.0.1' / name
        if path.exists():
            output = target / 'ffmpeg' / name
            output.parent.mkdir(exist_ok=True)
            shutil.copyfile(path, output)
    missing = [r['package'] for r in records if r.get('missing')]
    print(f'Collected license documents for {len(records)} package/source entries. Missing: {missing}')
    if missing:
        sys.exit(1)


if __name__ == '__main__':
    main()
