"""Reject unsupported native codec configurations before packaging."""
import ctypes
from pathlib import Path
import sys

RISK_FLAGS = ('--enable-gpl', '--enable-nonfree', '--enable-libx264', '--enable-libx265')
REQUIRED_DECODERS = (
    'h264', 'hevc', 'vp8', 'vp9', 'mpeg4', 'mpeg2video', 'wmv2', 'wmv3',
    'vc1', 'mjpeg', 'prores', 'theora', 'flv', 'aac', 'ac3', 'eac3', 'dca',
    'opus', 'vorbis', 'mp3', 'mp2', 'flac', 'pcm_s16le', 'wmav2',
)
REQUIRED_DEMUXERS = ('mov', 'matroska', 'avi', 'mpegts', 'mpeg', 'asf', 'flv', 'ogg')


def missing_demuxers(codec_path, major):
    if sys.platform == 'darwin':
        name = f'libavformat.{major}.dylib'
    elif sys.platform == 'win32':
        name = f'avformat-{major}.dll'
    else:
        name = f'libavformat.so.{major}'
    library = ctypes.CDLL(str(codec_path.parent / name))
    library.av_find_input_format.restype = ctypes.c_void_p
    library.av_find_input_format.argtypes = [ctypes.c_char_p]
    return [name for name in REQUIRED_DEMUXERS if not library.av_find_input_format(name.encode())]


def inspect_avcodec(path):
    library = ctypes.CDLL(str(path.resolve()))
    library.avcodec_license.restype = ctypes.c_char_p
    library.avcodec_configuration.restype = ctypes.c_char_p
    library.avcodec_version.restype = ctypes.c_uint
    library.avcodec_find_decoder_by_name.restype = ctypes.c_void_p
    library.avcodec_find_decoder_by_name.argtypes = [ctypes.c_char_p]
    license_text = library.avcodec_license().decode()
    config = library.avcodec_configuration().decode()
    flags = [flag for flag in RISK_FLAGS if flag in config.split()]
    software_av1 = any(library.avcodec_find_decoder_by_name(name)
                       for name in (b'libdav1d', b'libaom-av1'))
    major = library.avcodec_version() >> 16
    return {'path': str(path), 'license': license_text, 'configuration': config,
            'risk_flags': flags, 'software_av1': software_av1,
            'codec_major': major,
            'missing_decoders': [name for name in REQUIRED_DECODERS
                                 if not library.avcodec_find_decoder_by_name(name.encode())],
            'missing_demuxers': missing_demuxers(path, major)}


def playback_blockers(report):
    if report['codec_major'] != 63:
        return []
    missing = report['missing_decoders'] + report['missing_demuxers']
    if not report['software_av1']:
        missing.append('software AV1')
    return [f"Qt FFmpeg lacks playback support ({', '.join(missing)}): {report['path']}"] if missing else []


def loaded_avcodec_paths():
    if sys.platform == 'darwin':
        dyld = ctypes.CDLL(None)
        dyld._dyld_image_count.restype = ctypes.c_uint32
        dyld._dyld_get_image_name.argtypes = [ctypes.c_uint32]
        dyld._dyld_get_image_name.restype = ctypes.c_char_p
        return [Path(dyld._dyld_get_image_name(i).decode())
                for i in range(dyld._dyld_image_count())
                if b'libavcodec' in dyld._dyld_get_image_name(i)]
    if sys.platform == 'linux':
        return [Path(line.split()[-1]) for line in Path('/proc/self/maps').read_text().splitlines()
                if 'libavcodec' in line and '/' in line.split()[-1]]
    # Standard Windows wheel DLLs are inspected recursively below. Custom DLL
    # layouts need an explicit platform audit before distribution.
    return []


def inspect_native_libraries():
    import av
    import PySide6
    reports = []
    seen = set()
    for root in (Path(av.__file__).parent, Path(PySide6.__file__).parent):
        # Windows DLLs have different names; inspect them too when present.
        candidates = sorted(set(root.rglob('libavcodec*.dylib')) | set(root.rglob('libavcodec*.so*')) | set(root.rglob('avcodec*.dll')) | set(loaded_avcodec_paths()))
        for path in candidates:
            if path.resolve() not in seen:
                seen.add(path.resolve())
                reports.append(inspect_avcodec(path))
    blockers = [f"Uncleared FFmpeg codec flags: {item['path']} ({', '.join(item['risk_flags'])})"
                for item in reports if item['risk_flags'] or not item['license'].startswith('LGPL')]
    blockers += [problem for item in reports for problem in playback_blockers(item)]
    if not reports:
        blockers.append('No native FFmpeg libraries were inspected.')
    return {'libraries': reports, 'blockers': blockers}



if __name__ == '__main__':
    result = inspect_native_libraries()
    if result['blockers']:
        raise SystemExit('\n'.join(result['blockers']))
    print(f"Checked {len(result['libraries'])} native FFmpeg builds.")
