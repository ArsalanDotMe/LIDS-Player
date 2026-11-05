# First-party MIT build recipe. Third-party components keep their own licenses.
import os
from pathlib import Path
import sys
from PyInstaller.utils.hooks import collect_all, collect_data_files

root = Path(SPECPATH).parent
ffmpeg = os.environ['LLPLAYER_BUILD_FFMPEG']
ct_data, ct_binaries, ct_hidden = collect_all('ctranslate2')
ja_data, ja_binaries, ja_hidden = collect_all('janome')
tool_binaries = []
for name in ('whisper-cli', 'tesseract', 'llplayer-native'):
    path = root / '.tools/bin' / (name + ('.exe' if sys.platform == 'win32' else ''))
    if path.exists():
        tool_binaries.append((str(path), 'llplayer/bin'))
    elif sys.platform == 'darwin':
        raise SystemExit('Run scripts/build_tools.py before packaging: missing ' + name)
data = ct_data + ja_data + collect_data_files('faster_whisper') + collect_data_files('yt_dlp')
data += [(str(root / 'llplayer/assets'), 'llplayer/assets'),
         (str(root / 'third_party'), 'third_party'), (str(root / 'LICENSE'), '.'),
         (str(root / 'THIRD_PARTY_NOTICES.md'), '.')]
if (root / '.tools/tessdata').is_dir():
    data.append((str(root / '.tools/tessdata'), 'llplayer/tessdata'))
archive = root / '.tools/ffmpeg-8.0.1.tar.xz'
if archive.exists():
    data.append((str(archive), 'third_party/sources'))
recipe = root / '.tools/ffmpeg-build.json'
if recipe.exists():
    data.append((str(recipe), 'third_party/sources'))
for name in ('ffmpeg-9.0.1.tar.xz', 'qt-ffmpeg-build.json'):
    source = root / '.tools' / name
    if not source.exists():
        raise SystemExit('Run scripts/build_qt_ffmpeg.py before packaging: missing ' + name)
    data.append((str(source), 'third_party/sources'))
if sys.platform == 'win32':
    for directory in (root / '.tools/ffmpeg/bin', root / '.tools/dav1d/bin', root / '.tools/zlib/bin'):
        tool_binaries += [(str(dll), 'llplayer/bin') for dll in directory.glob('*.dll')]
    for name in ('dav1d-1.5.1.tar.gz', 'dav1d-build.json', 'zlib-1.3.1.tar.gz', 'zlib-build.json', 'zlib-ffmpeg-header.patch'):
        data.append((str(root / '.tools' / name), 'third_party/sources'))
analysis = Analysis([str(root / 'run.py')], pathex=[str(root)],
    binaries=ct_binaries + ja_binaries + tool_binaries + [(ffmpeg, 'llplayer/bin')], datas=data,
    hiddenimports=['faster_whisper', *ct_hidden, *ja_hidden],
    excludes=['PySide6.QtWebEngineCore', 'PySide6.QtWebEngineWidgets',
              'PySide6.QtVirtualKeyboard', 'PySide6.QtPdf', 'PySide6.QtQuick', 'PySide6.QtQml'],
    noarchive=False)
# Qt's generic input-context plugin pulls in a GPL-only keyboard even when the
# application uses none of its APIs. Remove it and unrelated QML/PDF modules.
def keep(entry):
    path = entry[0].lower().replace('\\', '/')
    forbidden = ('virtualkeyboard', 'qtquick', 'qtqml', 'qtpdf', 'libqpdf.', 'qpdf.dll',
                 'qtcharts', 'qtdatavisualization', 'qtgraphs', 'qtquick3d')
    return not any(name in path for name in forbidden)
analysis.binaries = [entry for entry in analysis.binaries if keep(entry)]
analysis.datas = [entry for entry in analysis.datas if keep(entry)]
pyz = PYZ(analysis.pure)
exe = EXE(pyz, analysis.scripts, [], exclude_binaries=True, name='LIDS Player',
          debug=False, strip=False, upx=False, console=False,
          icon=str(root / 'llplayer/assets/icon.png'))
collection = COLLECT(exe, analysis.binaries, analysis.datas, strip=False, upx=False, name='LIDS Player')
if sys.platform == 'darwin':
    app = BUNDLE(collection, name='LIDS Player.app', icon=str(root / 'llplayer/assets/icon.png'),
                 bundle_identifier='com.lidsplayer.app',
                 info_plist={'CFBundleDocumentTypes': [{
                     'CFBundleTypeName': 'Media or subtitle file',
                     'CFBundleTypeRole': 'Viewer', 'LSHandlerRank': 'Alternate',
                     'CFBundleTypeExtensions': ['mkv', 'mp4', 'mov', 'webm', 'avi', 'mp3', 'm4a', 'wav', 'flac',
                                                'srt', 'vtt', 'ass', 'ssa', 'sub', 'sup', 'idx', 'mks'],
                 }]})
