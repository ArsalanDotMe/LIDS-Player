"""Build LGPL FFmpeg inputs with MSVC, then rebuild PyAV for Windows x64.

Run in an x64 Visual Studio environment with MSYS2 make/bash and NASM on PATH.
No third-party FFmpeg binaries are used.
"""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile

from download_source import fetch
from build_lgpl_ffmpeg import VERSION as AV_VERSION, URL as AV_URL, SHA256 as AV_SHA
from build_qt_ffmpeg import VERSION as QT_VERSION, URL as QT_URL, SHA256 as QT_SHA

ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / '.tools'
# Annotated dav1d 1.5.1 tag, pinned rather than following a moving branch.
DAV1D_REV = '3060ebf8dd26952579373084984daf70a54f5368'
ZLIB_REV = '925af44f3cde53c6b076611c297850091b5dc7bb'


def run(*command, **kwargs):
    subprocess.run(list(command), check=True, **kwargs)


def main():
    if sys.platform != 'win32':
        raise SystemExit('Run this recipe on Windows in the release toolchain.')
    TOOLS.mkdir(exist_ok=True)
    zlib_archive = TOOLS / 'zlib-1.3.1.tar.gz'
    zlib_url = f'https://codeload.github.com/madler/zlib/tar.gz/{ZLIB_REV}'
    zlib_sha = fetch(zlib_url, zlib_archive)
    with tarfile.open(zlib_archive) as package:
        package.extractall(TOOLS, filter='data')
    zlib_source = TOOLS / ('zlib-' + ZLIB_REV)
    zlib_prefix = TOOLS / 'zlib'
    run('cmake', '-S', str(zlib_source), '-B', str(TOOLS / 'zlib-build'), '-A', 'x64',
        '-DCMAKE_INSTALL_PREFIX=' + str(zlib_prefix), '-DZLIB_BUILD_EXAMPLES=OFF',
        '-DCMAKE_POLICY_VERSION_MINIMUM=3.5')
    run('cmake', '--build', str(TOOLS / 'zlib-build'), '--config', 'Release', '--target', 'install', '-j', '4')
    zlib_notice = ROOT / 'third_party/licenses/zlib-native'
    zlib_notice.mkdir(parents=True, exist_ok=True)
    shutil.copy2(zlib_source / 'README', zlib_notice / 'README')
    (TOOLS / 'zlib-build.json').write_text(json.dumps(dict(source=zlib_url, source_sha256=zlib_sha,
        revision=ZLIB_REV, build='MSVC shared'), indent=2))
    dav_archive = TOOLS / 'dav1d-1.5.1.tar.gz'
    dav_url = f'https://codeload.github.com/videolan/dav1d/tar.gz/{DAV1D_REV}'
    dav_sha = fetch(dav_url, dav_archive)
    with tarfile.open(dav_archive) as package:
        package.extractall(TOOLS, filter='data')
    dav_source = TOOLS / ('dav1d-' + DAV1D_REV)
    dav_prefix = TOOLS / 'dav1d'
    run('uv', 'tool', 'run', '--from', 'meson', '--with', 'ninja', 'meson', 'setup',
        str(TOOLS / 'dav1d-build'), str(dav_source), *(['--reconfigure'] if (TOOLS / 'dav1d-build/build.ninja').exists() else []), '--prefix', str(dav_prefix),
        '--buildtype=release', '--default-library=shared', '-Denable_tools=false', '-Denable_tests=false')
    run('uv', 'tool', 'run', '--from', 'meson', '--with', 'ninja', 'meson', 'compile', '-C', str(TOOLS / 'dav1d-build'))
    run('uv', 'tool', 'run', '--from', 'meson', '--with', 'ninja', 'meson', 'install', '-C', str(TOOLS / 'dav1d-build'))
    notice = ROOT / 'third_party/licenses/dav1d'
    notice.mkdir(parents=True, exist_ok=True)
    shutil.copy2(dav_source / 'COPYING', notice / 'COPYING')
    (TOOLS / 'dav1d-build.json').write_text(json.dumps(dict(source=dav_url, source_sha256=dav_sha,
        revision=DAV1D_REV, license='BSD-2-Clause', build='MSVC shared, tools/tests disabled'), indent=2))
    # MSYS bash supplies configure/make, while cl/link are the Visual Studio tools.
    bash = os.environ.get('LLPLAYER_MSYS_BASH', r'C:\msys64\usr\bin\bash.exe')
    env = dict(os.environ)
    env['PATH'] = str(dav_prefix / 'bin') + os.pathsep + str(zlib_prefix / 'bin') + os.pathsep + env['PATH']
    env['PKG_CONFIG_PATH'] = str(dav_prefix / 'lib/pkgconfig')
    for variable, folder in (('INCLUDE', 'include'), ('LIB', 'lib')):
        env[variable] = os.pathsep.join(str(prefix / folder) for prefix in (zlib_prefix, dav_prefix)) + os.pathsep + env.get(variable, '')
    env['MSYS2_PATH_TYPE'] = 'inherit'
    for version, url, sha, name in ((AV_VERSION, AV_URL, AV_SHA, 'ffmpeg'),
                                    (QT_VERSION, QT_URL, QT_SHA, 'qt-ffmpeg')):
        archive = TOOLS / f'ffmpeg-{version}.tar.xz'
        fetch(url, archive, sha)
        source = TOOLS / f'ffmpeg-{version}'
        with tarfile.open(archive) as package:
            package.extractall(TOOLS, filter='data')
        prefix = TOOLS / name
        flags = ['--toolchain=msvc', '--arch=x86_64', '--target-os=win64',
                 f'--prefix={prefix.as_posix()}', '--enable-shared', '--disable-static',
                 '--disable-autodetect', '--disable-gpl', '--disable-nonfree',
                 '--disable-doc', '--disable-debug', '--enable-schannel',
                 '--enable-mediafoundation', '--enable-d3d11va', '--enable-dxva2', '--enable-zlib']
        if name == 'qt-ffmpeg':
            flags += ['--disable-programs', '--disable-avdevice', '--disable-avfilter',
                      '--enable-libdav1d', '--disable-decoder=av1']
        import shlex
        command = 'export PATH="/usr/bin:$PATH"; ./configure ' + shlex.join(flags) + ' && make -j4 && make install'
        try:
            run(bash, '-c', command, cwd=source, env=env)
        except subprocess.CalledProcessError:
            log = source / 'ffbuild/config.log'
            if log.exists():
                print(log.read_text(errors='replace')[-24000:], flush=True)
            raise
        (TOOLS / (name + '-build.json')).write_text(json.dumps(dict(version=version, source=url,
            source_sha256=sha, configure=flags, platform=sys.platform), indent=2))
        destination = ROOT / '.venv/Lib/site-packages' / ('av' if name == 'ffmpeg' else 'PySide6')
        destination.mkdir(parents=True, exist_ok=True)
        for dll in (prefix / 'bin').glob('*.dll'):
            shutil.copy2(dll, destination)
        for dll in (zlib_prefix / 'bin').glob('*.dll'):
            shutil.copy2(dll, destination)
        if name == 'qt-ffmpeg':
            for dll in (dav_prefix / 'bin').glob('*.dll'):
                shutil.copy2(dll, destination)
    av_prefix = TOOLS / 'ffmpeg'
    env['INCLUDE'] = str(av_prefix / 'include') + os.pathsep + env.get('INCLUDE', '')
    env['LIB'] = str(av_prefix / 'lib') + os.pathsep + env.get('LIB', '')
    env['PATH'] = str(av_prefix / 'bin') + os.pathsep + env['PATH']
    run('uv', 'pip', 'install', '--no-binary', 'av', '--reinstall-package', 'av', 'av==16.1.0', env=env)
    # Reinstallation removes package-local DLLs. Restore only our checked build.
    for directory in (av_prefix / 'bin', zlib_prefix / 'bin'):
        for dll in directory.glob('*.dll'):
            shutil.copy2(dll, ROOT / '.venv/Lib/site-packages/av')
    qt_notice = ROOT / 'third_party/licenses/ffmpeg-qt'
    qt_notice.mkdir(parents=True, exist_ok=True)
    for filename in ('COPYING.LGPLv2.1', 'COPYING.LGPLv3', 'LICENSE.md'):
        shutil.copy2(TOOLS / f'ffmpeg-{QT_VERSION}' / filename, qt_notice / filename)
    run(sys.executable, str(ROOT / 'scripts/check_licenses.py'))


if __name__ == '__main__':
    main()
