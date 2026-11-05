from llplayer.core import Cue, Timeline, Settings


def test_overlap_offset_and_navigation():
    timeline = Timeline([Cue(1000, 3000, 'Hello'), Cue(2000, 4000, 'World')])
    timeline.offset = 500
    assert timeline.active(2500) == timeline.cues
    assert timeline.active(4500) == []
    assert timeline.adjacent(1500, 1) == 2500
    assert timeline.adjacent(2500, -1) == 1500
    assert timeline.search('WORLD')[0].text == 'World'


def test_subtitle_roundtrip(tmp_path):
    timeline = Timeline([Cue(1000, 2500, '日本語\nHello')])
    timeline.offset = -200
    path = tmp_path / 'out.srt'
    timeline.export(str(path))
    loaded = Timeline.load(str(path))
    assert loaded.cues == [Cue(800, 2300, '日本語\nHello', markup='日本語<br>Hello')]


def test_settings_atomic_and_private(tmp_path):
    path = tmp_path / 'config' / 'settings.json'
    settings = Settings(path)
    settings.data['target'] = 'ja'
    settings.save()
    assert Settings(path).data['target'] == 'ja'
    import os
    if os.name != "nt":
        assert path.stat().st_mode & 0o777 == 0o600


def test_legacy_study_preset_upgrades_once_without_changing_custom_colors(tmp_path):
    import json
    from llplayer.core import DEFAULTS, LEGACY_STUDY_STYLE

    path = tmp_path / "settings.json"
    original = dict(LEGACY_STUDY_STYLE, sidebar_track=0, primary_language="en", secondary_language="et")
    path.write_text(json.dumps(original))
    upgraded = Settings(path)
    assert upgraded.data["sidebar_track"] == 2
    assert upgraded.data["secondary_color"] == DEFAULTS["secondary_color"]
    assert upgraded.data["secondary_language"] == "et"
    path.write_text(json.dumps(dict(original, secondary_color="#ffcc44")))
    assert Settings(path).data["secondary_color"] == "#ffcc44"
