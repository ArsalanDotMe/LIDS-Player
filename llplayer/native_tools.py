"""Find bundled tools, with native macOS language services where available."""
from functools import lru_cache
import json
from pathlib import Path
import shutil
import subprocess
import sys
import re


def executable(name, configured=''):
    if configured and Path(configured).is_file():
        return configured
    suffix = '.exe' if sys.platform == 'win32' else ''
    for path in (Path(__file__).parent / 'bin' / (name + suffix),
                 Path(__file__).resolve().parents[1] / '.tools/bin' / (name + suffix)):
        if path.is_file():
            return str(path)
    return shutil.which(configured or name)


@lru_cache(maxsize=256)
def tokenize(text):
    if re.search(r'[\u3040-\u30ff]', text):
        from janome.tokenizer import Tokenizer
        global _japanese
        if _japanese is None:
            _japanese = Tokenizer()
        result, position = [], 0
        for token in _japanese.tokenize(text):
            start = text.find(token.surface, position)
            if start < 0:
                continue
            end = start + len(token.surface)
            result.append(dict(text=token.surface, start=start, end=end))
            position = end
        return result
    binary = executable('llplayer-native')
    if binary and sys.platform == 'darwin':
        result = subprocess.run([binary, 'tokens'], input=text, capture_output=True, text=True, timeout=10)
        if result.returncode == 0:
            return json.loads(result.stdout)
    # Unicode-aware fallback when native linguistic services are unavailable.
    return [dict(text=m.group(), start=m.start(), end=m.end()) for m in re.finditer(r"[^\W_]+(?:['’\-][^\W_]+)*", text)]


_japanese = None


def data_dir():
    import os
    override = os.environ.get('LLPLAYER_DATA_DIR')
    if override:
        return Path(override)
    from PySide6.QtCore import QStandardPaths
    return Path(QStandardPaths.writableLocation(QStandardPaths.StandardLocation.AppDataLocation))
