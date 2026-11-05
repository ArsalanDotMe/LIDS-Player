"""Checks that the technical release gate does not trust a license label alone."""
from pathlib import Path
import importlib.util
import sys
from types import SimpleNamespace
import pytest

SCRIPTS = Path(__file__).resolve().parents[1] / 'scripts'


@pytest.fixture
def builder(monkeypatch):
    monkeypatch.syspath_prepend(str(SCRIPTS))
    spec = importlib.util.spec_from_file_location('llplayer_build_gate', SCRIPTS / 'build.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize('flag', ['--enable-gpl', '--enable-nonfree', '--enable-libx264', '--enable-libx265'])
def test_build_rejects_uncleared_codecs_even_with_lgpl_text(builder, monkeypatch, tmp_path, flag):
    binary = tmp_path / 'ffmpeg'
    binary.write_text('placeholder')
    def run(args, **kwargs):
        if args[-1] == '-version':
            return SimpleNamespace(stdout='configuration: ' + flag, stderr='')
        if args[-1] == '-L':
            return SimpleNamespace(stdout='GNU Lesser General Public License', stderr='')
        pytest.fail('Packaging started before the native licensing gate passed')
    monkeypatch.setattr(builder.subprocess, 'run', run)
    monkeypatch.setattr(sys, 'argv', ['build.py', '--ffmpeg', str(binary)])
    with pytest.raises(SystemExit, match='uncleared'):
        builder.main()


def test_build_rejects_unknown_executable_license(builder, monkeypatch, tmp_path):
    binary = tmp_path / 'ffmpeg'
    binary.touch()
    monkeypatch.setattr(builder.subprocess, 'run', lambda *args, **kwargs: SimpleNamespace(stdout='unknown', stderr=''))
    monkeypatch.setattr(sys, 'argv', ['build.py', '--ffmpeg', str(binary)])
    with pytest.raises(SystemExit, match='did not report an LGPL license'):
        builder.main()


@pytest.mark.skipif(sys.platform == 'win32', reason='Windows native packaging remains gated')
def test_qt_ffmpeg_includes_common_format_decoders_and_demuxers(builder):
    from check_licenses import inspect_native_libraries
    reports = inspect_native_libraries()['libraries']
    qt_reports = [report for report in reports if 'PySide6' in report['path']]
    assert qt_reports
    assert all(report['software_av1'] for report in qt_reports), 'Run scripts/build_qt_ffmpeg.py'
    assert all(not report['missing_decoders'] for report in qt_reports)
    assert all(not report['missing_demuxers'] for report in qt_reports)


@pytest.mark.parametrize('missing', ['missing_decoders', 'missing_demuxers', 'software_av1'])
def test_packaging_rejects_missing_playback_support(builder, missing):
    from check_licenses import playback_blockers
    report = dict(codec_major=63, path='Qt/libavcodec', software_av1=True,
                  missing_decoders=[], missing_demuxers=[])
    report[missing] = False if missing == 'software_av1' else ['vp9' if missing == 'missing_decoders' else 'matroska']
    assert playback_blockers(report)
