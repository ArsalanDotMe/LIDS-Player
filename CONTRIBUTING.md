# Contributing

Use Python 3.12 and install the locked development dependencies:

```sh
uv sync --python 3.12 --extra asr --extra dev --locked
uv run python scripts/make_assets.py
uv run python scripts/make_fixture.py
uv run python scripts/make_bitmap_fixture.py
uv run pytest -q
```

Fixture generation requires an FFmpeg executable. Use the source-build recipe in
`docs/building.md` or set `LLPLAYER_FFMPEG` to a local executable.

Keep contributed code and assets compatible with the first-party license. Record
any third-party material, its origin, applicable license and changes. Dependency
metadata alone does not establish the license of bundled native binaries.
Consult `docs/building.md` before packaging an app.

A person must submit pull requests and review and test any AI-assisted changes.
Disclose the AI tool in the pull request description. Agents must not submit
pull requests or post comments on them.
