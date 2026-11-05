"""Inspect a built bundle, separately from the development environment."""
import argparse
from pathlib import Path
import re
from check_licenses import inspect_avcodec, playback_blockers

ROOT = Path(__file__).resolve().parents[1]
QT_MODULES = {'Core', 'Gui', 'Widgets', 'Network', 'Multimedia', 'MultimediaWidgets',
              'OpenGL', 'OpenGLWidgets', 'Svg', 'DBus', 'Concurrent'}


def inspect_bundle(folder):
    reports, blockers, modules, seen = [], [], set(), set()
    for path in folder.rglob('*'):
        name = path.name
        module = None
        if name.startswith('Qt') and name.endswith('.framework'):
            module = name[2:-10]
        match = re.fullmatch(r'(?:lib)?Qt6([A-Za-z0-9]+)(?:\.dll|\.so(?:\.[0-9]+)*)', name)
        if match:
            module = match.group(1)
        if module:
            modules.add(module)
            if module not in QT_MODULES:
                blockers.append(f'Qt module outside the reviewed allowlist: {path}')
        if path.is_file():
            if any(term in name.lower() for term in ('virtualkeyboard', 'libx264', 'libx265')):
                blockers.append(f'Restricted component: {path}')
            if name.startswith(('libavcodec', 'avcodec')) and path.resolve() not in seen:
                seen.add(path.resolve())
                report = inspect_avcodec(path)
                report['path'] = str(path.relative_to(folder))
                reports.append(report)
                if report['risk_flags'] or not report['license'].startswith('LGPL'):
                    blockers.append(f'Uncleared FFmpeg library: {path}')
                blockers.extend(playback_blockers(report))
    if not reports:
        blockers.append('No bundled FFmpeg codec libraries inspected')
    return {'bundle': folder.name, 'qt_modules': sorted(modules), 'ffmpeg_libraries': reports,
            'blockers': blockers, 'scope': 'Technical native-library check, not complete distribution compliance or legal clearance.'}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('bundle', type=Path)
    args = parser.parse_args()
    report = inspect_bundle(args.bundle)
    print(f"Inspected {len(report['qt_modules'])} Qt modules and {len(report['ffmpeg_libraries'])} FFmpeg library copies; {len(report['blockers'])} blockers.")
    if report['blockers']:
        raise SystemExit('\n'.join(report['blockers']))
