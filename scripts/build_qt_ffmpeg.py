"""Build Qt's FFmpeg ABI with software AV1 decoding and install it into PySide6.

Run after uv sync, before testing or packaging. PyAV keeps its separate FFmpeg 8
libraries. Requires pkg-config and dav1d development files.
"""
import argparse
import ctypes
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
VERSION = '9.0.1'
SHA256 = 'cf38e0e28c7e5605942c4a77755349b0145804a397af37eb1fb4c77cb237f635'
URL = f'https://ffmpeg.org/releases/ffmpeg-{VERSION}.tar.xz'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--jobs', type=int, default=min(6, os.cpu_count() or 1))
    args = parser.parse_args()
    if sys.platform not in ('darwin', 'linux'):
        raise SystemExit('Qt FFmpeg preparation supports macOS and Linux only.')
    import PySide6
    qt_lib = Path(PySide6.__file__).parent / 'Qt/lib'
    pattern = 'libavcodec.63.dylib' if sys.platform == 'darwin' else 'libavcodec.so.63'
    if not (qt_lib / pattern).exists():
        raise SystemExit('Qt FFmpeg ABI changed. Review this recipe before rebuilding.')
    subprocess.run(['pkg-config', '--exists', 'dav1d >= 1.0.0'], check=True)
    tools = ROOT / '.tools'
    tools.mkdir(exist_ok=True)
    archive = tools / f'ffmpeg-{VERSION}.tar.xz'
    if not archive.exists():
        with urllib.request.urlopen(URL, timeout=120) as response, archive.open('wb') as output:
            shutil.copyfileobj(response, output)
    if hashlib.sha256(archive.read_bytes()).hexdigest() != SHA256:
        raise SystemExit('FFmpeg source archive checksum mismatch')
    source = tools / f'ffmpeg-{VERSION}'
    if not source.exists():
        with tarfile.open(archive) as package:
            package.extractall(tools, filter='data')
    prefix = tools / 'qt-ffmpeg'
    flags = [f'--prefix={prefix}', '--enable-shared', '--disable-static',
             '--disable-autodetect', '--disable-gpl', '--disable-nonfree',
             '--disable-doc', '--disable-debug', '--disable-programs',
             '--disable-avdevice', '--disable-avfilter', '--enable-zlib',
             '--enable-libdav1d', '--disable-decoder=av1']
    # FFmpeg's native av1 decoder only supplies hardware decoding. Excluding it
    # makes Qt select dav1d instead of repeatedly retrying unsupported hardware.
    if sys.platform == 'darwin':
        flags += ['--enable-securetransport', '--enable-videotoolbox', '--enable-audiotoolbox']
    else:
        flags += ['--enable-gnutls']
    subprocess.run([str(source / 'configure'), *flags], cwd=source, check=True)
    subprocess.run(['make', f'-j{args.jobs}'], cwd=source, check=True)
    subprocess.run(['make', 'install'], cwd=source, check=True)
    libraries = list((prefix / 'lib').glob('*.dylib' if sys.platform == 'darwin' else '*.so*'))
    for library in libraries:
        target = qt_lib / library.name
        # Replace symlinks rather than following an upstream versioned alias.
        target.unlink(missing_ok=True)
        shutil.copy2(library.resolve(), target)
    codec = ctypes.CDLL(str(qt_lib / pattern))
    codec.avcodec_find_decoder_by_name.restype = ctypes.c_void_p
    if not codec.avcodec_find_decoder_by_name(b'libdav1d'):
        raise SystemExit('Software AV1 decoder missing after installation')
    manifest = dict(version=VERSION, source=URL, source_sha256=SHA256,
                    configure=flags, platform=sys.platform,
                    dav1d_version=subprocess.check_output(['pkg-config', '--modversion', 'dav1d'], text=True).strip())
    (tools / 'qt-ffmpeg-build.json').write_text(json.dumps(manifest, indent=2) + '\n')
    license_dir = ROOT / 'third_party/licenses/dav1d'
    license_dir.mkdir(parents=True, exist_ok=True)
    dav1d_prefix = Path(subprocess.check_output(['pkg-config', '--variable=prefix', 'dav1d'], text=True).strip())
    for notice in (dav1d_prefix / 'COPYING', dav1d_prefix / 'share/doc/dav1d/copyright',
                   dav1d_prefix / 'share/doc/libdav1d-dev/copyright'):
        if notice.exists():
            shutil.copy2(notice, license_dir / 'COPYING')
            break
    else:
        raise SystemExit('dav1d COPYING missing. Install its license notice before packaging.')
    ffmpeg_notices = ROOT / 'third_party/licenses/ffmpeg-qt'
    ffmpeg_notices.mkdir(parents=True, exist_ok=True)
    for name in ('COPYING.LGPLv2.1', 'COPYING.LGPLv3', 'LICENSE.md'):
        shutil.copy2(source / name, ffmpeg_notices / name)
    print('Qt FFmpeg installed with software AV1 decoding. Rebuild after uv sync.')


if __name__ == '__main__':
    main()
