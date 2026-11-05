"""Build an LGPL-only FFmpeg utility and shared libraries on macOS or Linux.

Requires a C/C++ compiler, make, pkg-config and development zlib headers.
Windows releases need an independently audited toolchain/build instead.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tarfile
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
VERSION = '8.0.1'
URL = f'https://ffmpeg.org/releases/ffmpeg-{VERSION}.tar.xz'
SHA256 = '05ee0b03119b45c0bdb4df654b96802e909e0a752f72e4fe3794f487229e5a41'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--jobs', type=int, default=min(4, os.cpu_count() or 1))
    args = parser.parse_args()
    if sys.platform not in ('darwin', 'linux'):
        raise SystemExit('This build recipe supports macOS and Linux only. Windows release packaging remains gated.')
    tools = ROOT / '.tools'
    tools.mkdir(exist_ok=True)
    archive = tools / f'ffmpeg-{VERSION}.tar.xz'
    if not archive.exists():
        with urllib.request.urlopen(URL, timeout=120) as response, archive.open('wb') as output:
            while chunk := response.read(1024 * 1024):
                output.write(chunk)
    if hashlib.sha256(archive.read_bytes()).hexdigest() != SHA256:
        raise SystemExit('FFmpeg source archive checksum mismatch')
    source = tools / f'ffmpeg-{VERSION}'
    if not source.exists():
        with tarfile.open(archive) as package:
            package.extractall(tools, filter='data')
    prefix = tools / 'ffmpeg'
    flags = [f'--prefix={prefix}', '--enable-shared', '--disable-static', '--disable-autodetect',
             '--disable-gpl', '--disable-nonfree', '--disable-doc', '--disable-debug', '--enable-zlib']
    if sys.platform == 'darwin':
        flags += ['--enable-securetransport', '--enable-videotoolbox', '--enable-audiotoolbox']
    else:
        # Network HTTPS on Linux requires separately installed OpenSSL headers.
        flags += ['--enable-gnutls']
    subprocess.run([str(source / 'configure'), *flags], cwd=source, check=True)
    subprocess.run(['make', f'-j{args.jobs}'], cwd=source, check=True)
    subprocess.run(['make', 'install'], cwd=source, check=True)
    (tools / 'ffmpeg-build.json').write_text(json.dumps({
        'version': VERSION, 'source': URL, 'source_sha256': hashlib.sha256(archive.read_bytes()).hexdigest(),
        'configure': flags, 'platform': sys.platform,
        'notice': 'Source archive and build recipe must accompany any distributed FFmpeg binaries.'
    }, indent=2) + '\n')
    print(prefix / 'bin/ffmpeg')


if __name__ == '__main__':
    main()
