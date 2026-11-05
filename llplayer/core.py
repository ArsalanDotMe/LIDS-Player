"""Subtitle timeline and persistent settings, independent of the UI."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import bisect
import json
import os
import re
import sys
import tempfile
import pysubs2


@dataclass
class Cue:
    start: int
    end: int
    text: str = ""
    image: bytes | None = None
    markup: str = ""
    original_text: str = ""
    canvas: tuple[int, int] | None = None


class Timeline:
    def __init__(self, cues=()):
        self.cues = sorted(cues, key=lambda cue: cue.start)
        self.starts = [cue.start for cue in self.cues]
        self.offset = 0
        self.latest_ends = []
        latest = -float("inf")
        for cue in self.cues:
            latest = max(latest, cue.end)
            self.latest_ends.append(latest)

    def window(self, start, end):
        """Indexes of cues that might intersect this interval, including overlaps."""
        return range(bisect.bisect_right(self.latest_ends, start - self.offset),
                     bisect.bisect_left(self.starts, end - self.offset))

    def active(self, position: int) -> list[Cue]:
        position -= self.offset
        # Include overlapping cues, rather than assuming only one event is active.
        start = bisect.bisect_right(self.latest_ends, position)
        stop = bisect.bisect_right(self.starts, position)
        return [cue for cue in self.cues[start:stop] if cue.end > position]

    def adjacent(self, position: int, direction: int) -> int | None:
        position -= self.offset
        index = (bisect.bisect_right(self.starts, position + 100) if direction > 0
                 else bisect.bisect_left(self.starts, position - 100) - 1)
        return self.starts[index] + self.offset if 0 <= index < len(self.starts) else None

    def search(self, query: str) -> list[Cue]:
        return [cue for cue in self.cues if query.casefold() in cue.text.casefold()]

    @classmethod
    def load(cls, path: str, encoding='auto', fps=None):
        raw = Path(path).read_bytes()
        if encoding != 'auto':
            text = raw.decode(encoding)
        else:
            try:
                text = raw.decode('utf-8-sig')
            except UnicodeDecodeError:
                from charset_normalizer import from_bytes
                decoded = from_bytes(raw).best()
                if decoded is None:
                    raise ValueError('Could not detect subtitle encoding; choose one in Settings.')
                text = str(decoded)
        subs = pysubs2.SSAFile.from_string(text.replace("\r\n", "\n").replace("\r", "\n"), fps=fps or 25)
        from .subtitle_text import styled_ass
        return cls(Cue(s.start, s.end, s.plaintext, markup=styled_ass(s.text)) for s in subs if not s.is_comment)

    def export(self, path: str):
        subs = pysubs2.SSAFile()
        subs.events = [pysubs2.SSAEvent(start=max(0, c.start + self.offset),
                                      end=max(1, c.end + self.offset), text=c.text.replace("\n", r"\N"))
                       for c in self.cues if c.text.strip()]
        subs.save(path, format_="srt")


DEFAULT_SHORTCUTS = {
    "Play / pause": ["Space"], "Open media": ["Ctrl+O"], "Open URL": ["Ctrl+L"],
    "Primary subtitles": ["Ctrl+1"], "Secondary subtitles": ["Ctrl+2"],
    "Previous subtitle": ["Up"], "Next subtitle": ["Down"],
    "Seek backward": ["Left"], "Seek forward": ["Right"],
    "Fullscreen": (["Meta+Ctrl+F", "F", "F11"] if sys.platform == "darwin" else ["F11", "F"]), "Settings": ["Ctrl+,"], "Cheat sheet": ["F1"],
    "Copy subtitles": ["Ctrl+C"], "Sidebar": ["Ctrl+B"], "Mute": ["M"],
    "Next file": ["Alt+Right"], "Previous file": ["Alt+Left"],
    "Search subtitles": ["Ctrl+F"], "Always on top": ["Ctrl+T"],
    "Subtitles up": ["Shift+Up"], "Subtitles down": ["Shift+Down"],
    "Larger subtitles": ["Shift+Right"], "Smaller subtitles": ["Shift+Left"],
    "Larger secondary": ["Ctrl+Shift+Right"], "Smaller secondary": ["Ctrl+Shift+Left"],
    "More subtitle spacing": ["Ctrl+Shift+Up"], "Less subtitle spacing": ["Ctrl+Shift+Down"],
    "Copy primary": [], "Copy secondary": [], "Automatic copy": ["Ctrl+A"],
    "Switch sidebar track": [], "Download subtitles": [], "Export subtitles": [],
    "New window": ["Ctrl+N"], "Clone window": ["Ctrl+Shift+N"], "Restart": [],
    "Debug information": ["Ctrl+Shift+D"], "Copy media path": [], "Paste media": ["Ctrl+V"],
    "Original sidebar text": [], "Play": [], "Pause": [], "Stop": ["Ctrl+Shift+S"],
    "Volume up": ["+"], "Volume down": ["-"], "Current subtitle": ["Ctrl+Up"],
    "Primary visibility": [], "Secondary visibility": [], "All subtitle visibility": ["V"],
    "Larger primary": [], "Smaller primary": [], "Reset subtitle position": [],
    "Primary delay up": [], "Primary delay down": [], "Secondary delay up": [], "Secondary delay down": [],
    "Frame forward": ["."], "Frame backward": [","], "Loop media": ["L"],
    "Speed up": ["]"], "Speed down": ["["], "Normal speed": ["Backspace"],
    "Seek start": ["Home"], "Seek end": ["End"], "Rotate video": ["R"],
    "Audio delay up": [], "Audio delay down": [], "Audio delay up large": [], "Audio delay down large": [],
    "Secondary previous subtitle": [], "Secondary current subtitle": [], "Secondary next subtitle": [],
    "Reverse playback": [], "Record": ["Ctrl+R"], "Zoom in": ["Ctrl+="], "Zoom out": ["Ctrl+-"],
    "Reset zoom": [], "Reset rotation": [], "Reset delay": [], "Reset all": [],
    "Audio visibility": [], "Video visibility": [], "Keep aspect ratio": [], "Video acceleration": [],
    "Reload media": [], "Show controls": [], "Hide controls": [],
    "Seek forward medium": [], "Seek backward medium": [], "Seek forward large": [], "Seek backward large": [],
    "Fullscreen on": [], "Fullscreen off": [],
    "Screenshot": ["Ctrl+S"], "Open current folder": [], "Close window": ["Ctrl+W"], "Quit": ["Ctrl+Q"],
}
DEFAULTS = dict(theme_version=1, auto_translate=False, primary_language="en", secondary_language="fr", languages_chosen=False, target="en", source="auto", audio_device="", audio_languages="", default_volume=80, video_aspect="Auto", custom_aspect="16:9", online_quality="Compatible", provider="Google", endpoint="http://localhost:11434",
                model="llama3.2", api_key="", font_size=22, secondary_size=28, bottom=28,
                gap=5, accent="#85bdff", background="#151a24", auto_copy=False,
                auto_pause=False, asr_engine="faster-whisper", asr_model="tiny",
                whisper_cli="whisper-cli", whisper_model="", ocr_language="eng",
                search_url="https://www.google.com/search?q={word}",
                opensubtitles_key="", opensubtitles_token="", shortcuts=DEFAULT_SHORTCUTS,
                subtitle_encoding="auto", font_family="", secondary_font_family="", font_bold=False, secondary_bold=True,
                font_italic=False, secondary_italic=False, primary_color="#dbe6f5", secondary_color="#ffffff",
                subtitle_background="#090e17", subtitle_opacity=93, subtitle_stroke="#000000", subtitle_stroke_width=0,
                font_stretch=100, secondary_font_stretch=100, font_weight=0, secondary_font_weight=0,
                subtitle_safe_margin=2, sidebar_original=False, sidebar_track=2, always_on_top=False, subtitle_horizontal=50,
                subtitle_vertical=85, subtitle_anchor="Center", bitmap_scale=100, secondary_bitmap_scale=100,
                asr_chunk_seconds=20, asr_device="auto", asr_compute="default", asr_threads=4,
                asr_beam_size=5, asr_translate=False, asr_gpu=True, asr_track="Primary", translation_track="Primary", ocr_engine="Auto",
                pause_on_lookup=True, audio_delay=0, video_acceleration=True, context_lines=3, translation_prompt="", azure_region="", provider_profiles={},
                search_urls='{"Dictionary":"https://en.wiktionary.org/wiki/{word}"}')


# The original shipped preset emphasized the spoken language. Migrate that
# complete preset once without treating individual custom values as defaults.
LEGACY_STUDY_STYLE = dict(background="#17191f", accent="#8cb8ff", primary_color="#ffffff",
                          secondary_color="#8cb8ff", font_size=28, secondary_size=23,
                          font_bold=True, secondary_bold=False, subtitle_stroke_width=1,
                          subtitle_background="#000000", subtitle_opacity=65, gap=8)


class Settings:
    def __init__(self, path: Path):
        self.path = path
        self.data = json.loads(json.dumps(DEFAULTS))
        try:
            stored = json.loads(path.read_text())
            self.data.update(stored)
            if "theme_version" not in stored and all(stored.get(k) == v for k, v in LEGACY_STUDY_STYLE.items()):
                self.data.update({k: DEFAULTS[k] for k in LEGACY_STUDY_STYLE})
                if stored.get("sidebar_track") == 0:
                    self.data["sidebar_track"] = DEFAULTS["sidebar_track"]
        except (FileNotFoundError, ValueError):
            pass
        self.data["shortcuts"] = {**DEFAULT_SHORTCUTS, **self.data.get("shortcuts", {})}

    def save(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, name = tempfile.mkstemp(dir=self.path.parent)
        try:
            if hasattr(os, "fchmod"):
                os.fchmod(fd, 0o600)
            with os.fdopen(fd, "w") as stream:
                json.dump(self.data, stream, indent=2)
            os.replace(name, self.path)
        finally:
            if os.path.exists(name):
                os.unlink(name)


def clean_ass(value: str) -> str:
    return re.sub(r"\{[^}]*\}", "", value).replace(r"\N", "\n").replace(r"\n", "\n")
