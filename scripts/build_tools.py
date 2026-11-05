"""Prepare bundled speech/OCR tools without changing the first-party MIT license.

On macOS, build the MIT native helper and whisper.cpp with Metal, and package
Apache-licensed Tesseract plus its English data. A compiler, cmake, pkg-config
and Tesseract installation are required on the build machine, not the user's Mac.
"""
import argparse
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
WHISPER_REVISION = '4da27c41cebadb3cbbcd2563e9c7cbc8d84bdcad'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--whisper-source', type=Path)
    args = parser.parse_args()
    tools = ROOT / '.tools'
    binary = tools / 'bin'
    binary.mkdir(exist_ok=True, parents=True)
    if sys.platform == 'darwin':
        subprocess.run(['swiftc', str(ROOT / 'native/main.swift'), '-O', '-o', str(binary / 'llplayer-native')], check=True)
    source = args.whisper_source
    if source is None:
        source = tools / ('whisper.cpp-' + WHISPER_REVISION)
        if not source.exists():
            archive = tools / 'whisper.cpp.tar.gz'
            url = f'https://codeload.github.com/ggml-org/whisper.cpp/tar.gz/{WHISPER_REVISION}'
            urllib.request.urlretrieve(url, archive)
            with tarfile.open(archive) as package:
                package.extractall(tools, filter='data')
    build = tools / 'whisper.cpp/build'
    cmake = [shutil.which('cmake')] if shutil.which('cmake') else ['uv', 'tool', 'run', '--from', 'cmake', 'cmake']
    flags = ['-DWHISPER_BUILD_TESTS=OFF', '-DCMAKE_BUILD_TYPE=Release', '-DGGML_METAL_EMBED_LIBRARY=ON',
             '-DGGML_METAL=' + ('ON' if sys.platform == 'darwin' else 'OFF')]
    subprocess.run([*cmake, '-S', str(source.resolve()), '-B', str(build), *flags], check=True)
    subprocess.run([*cmake, '--build', str(build), '--target', 'whisper-cli', '-j', '4'], check=True)
    suffix = '.exe' if sys.platform == 'win32' else ''
    shutil.copy2(build / 'bin' / ('whisper-cli' + suffix), binary / ('whisper-cli' + suffix))
    notice = ROOT / 'third_party/licenses/whisper.cpp'
    notice.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source / 'LICENSE', notice / 'LICENSE')
    (notice / 'SOURCE.txt').write_text(f'https://github.com/ggml-org/whisper.cpp\nRevision: {WHISPER_REVISION}\nUnmodified source; Metal enabled on macOS.\n')
    tesseract = shutil.which('tesseract')
    if not tesseract:
        raise SystemExit('Install Tesseract on the build machine to prepare the OCR bundle.')
    shutil.copy2(tesseract, binary / ('tesseract' + suffix))
    listing = subprocess.check_output([tesseract, '--list-langs'], text=True, stderr=subprocess.STDOUT)
    import re
    match = re.search(r'List of available languages in "([^"]+)"', listing)
    if not match:
        raise SystemExit('Cannot locate Tesseract language data.')
    data = Path(match.group(1))
    target = tools / 'tessdata'
    target.mkdir(exist_ok=True)
    for language in ('eng', 'osd'):
        shutil.copy2(data / (language + '.traineddata'), target)
    if sys.platform == 'darwin':
        # Preserve license documents of Homebrew libraries recursively referenced
        # by Tesseract. System Apple libraries are provided by macOS, not copied.
        pending, visited = [Path(tesseract).resolve()], set()
        while pending:
            library = pending.pop()
            if library in visited:
                continue
            visited.add(library)
            parts = library.parts
            if 'Cellar' in parts:
                index = parts.index('Cellar')
                package = Path(*parts[:index + 3])
                destination = ROOT / 'third_party/licenses/native-ocr' / ('-'.join(parts[index + 1:index + 3]))
                destination.mkdir(parents=True, exist_ok=True)
                for file in package.rglob('*'):
                    if file.is_file() and any(name in file.name.upper() for name in ('LICENSE', 'COPYING', 'NOTICE')):
                        shutil.copyfile(file, destination / str(file.relative_to(package)).replace('/', '__'))
            dependencies = subprocess.check_output(['otool', '-L', str(library)], text=True)
            for line in dependencies.splitlines()[1:]:
                name = line.strip().split(' (', 1)[0]
                if name.startswith('/opt/homebrew/'):
                    pending.append(Path(name).resolve())
    print('Prepared bundled speech and OCR tools.')


if __name__ == '__main__':
    main()
