<p align="center"><img src="llplayer/assets/icon.svg" alt="LIDS Player logo" width="112"></p>

# LIDS Player

Language Immersion via Dual Subtitles. A native media player for language learning on macOS, Windows and Linux. Watch with dual subtitles, generate speech subtitles, translate dialogue, and look up words as you go.

## Run

Tagged releases provide macOS and Linux archives after the checks pass. The macOS app is not notarized. Windows can currently be run from source.

Requires Python 3.12 or 3.13 and [uv](https://docs.astral.sh/uv/).

```sh
uv sync --extra asr --extra dev
uv run llplayer
uv run llplayer /path/to/video.mkv --primary /path/to/learning.srt --secondary /path/to/native.srt
```

To run directly from the source checkout:

```sh
.venv/bin/python run.py
```

The macOS build includes Python, Qt, an LGPL-only FFmpeg utility, yt-dlp, both Whisper engines, Tesseract with English data, and macOS Vision OCR. Models download when first used. It is locally ad-hoc signed. The release workflow builds macOS and Linux packages. Windows packaging remains in development.

Running from source requires an FFmpeg executable for speech extraction and bitmap subtitles. Set `LLPLAYER_FFMPEG` to its path, or use the local source-build recipe in [the build instructions](docs/building.md). Ordinary video playback uses Qt's multimedia backend.

## Use

On first launch, choose the primary language you speak and the secondary language you’re learning. Change either in Settings → Languages.

Open or drop a video, audio file, or subtitle file. Shift-drop loads secondary subtitles. LIDS Player selects matching embedded tracks. In language setup or Settings → Languages, enable translation if you want LLPlayer to translate the primary track whenever subtitles in your learning language are missing. Open Subtitles to see both sources. Each row’s Change menu lets you select a track, find or load subtitles, generate them from speech, translate the other language, or turn the row off. More contains timing and export. Each delay shifts only its own track.

Click a transcript timestamp to seek, or a word in either language to look it up. The transcript pairs overlapping cues and searches both languages as you type. Select text on either subtitle and right-click to copy, translate, or search. Enable automatic copying in Settings for browser dictionary extensions such as Yomitan and 10ten.

Generate speech subtitles publishes results while it works, starting near playback. The chunk length defaults to 20 seconds and can be changed in Settings. Seeking prioritizes the new position. Either track can receive speech subtitles or supply the text for translation. Context length and translation prompts are configurable. Image-based subtitles are prepared for lookup around the current position. Export SRT saves text, OCR, ASR, or translated results with the current delay applied.

Settings controls independent subtitle fonts, outlines, colors, placement and bitmap scales, multiple word searches, translation profiles, speech engines, OCR language, credentials, and keyboard shortcuts. Multiple shortcuts can be separated by semicolons. F1 opens the cheat sheet.

## Features

| Feature | Implementation |
| --- | --- |
| Local video/audio, network video, speed, seeking, audio tracks, volume, fullscreen | Qt Multimedia with its FFmpeg backend; audio output selection, language priority, delay, looping, frame stepping, reverse, recording, zoom, rotation and custom aspect ratios |
| Online sites | yt-dlp resolves combined or separate video/audio streams; a local transport preserves request headers, seeking and HLS resources |
| Dual text subtitles | Embedded tracks through PyAV; SRT, ASS/SSA, VTT and other text formats through pysubs2 |
| Dual bitmap subtitles | FFmpeg palette-aware PGS, DVD/VobSub, DVB and XSUB conversion, displayed in the video and sidebar |
| Subtitle seeking, search, delay, repeat line, pause at end | Independent primary/secondary timelines |
| Speech recognition | faster-whisper and bundled whisper.cpp with Metal acceleration on macOS; incremental results and downloadable models |
| OCR | Bundled Tesseract with language downloads, plus Apple Vision on macOS |
| Translation | Google, Bing, Azure, DeepL, DeepLX, Ollama and OpenAI-compatible endpoints |
| LLM translation providers | OpenAI, LM Studio, KoboldCpp, Claude gateway, LiteLLM and custom compatible endpoints |
| Context-aware translation | Configurable preceding lines and prompt accompany each LLM request |
| Word translation and custom browser search | Click a word for lookup, or select text and use its context menu; Japanese word segmentation included |
| Browser dictionary extensions | Clipboard workflow |
| Subtitle downloader | OpenSubtitles REST API, with API key, account sign-in and language selection |
| SRT export | Text, speech, OCR and translations |
| Dark theme and shortcut customization | Persistent settings and built-in cheat sheet |

ASS inline bold, italic, underline, strikeout and color remain selectable. Bitmap cues appear as decoding progresses, and seeking prioritizes the new position. Advanced ASS animation and typesetting are outside the original app’s supported inline styles. New, clone and restart window actions preserve playback workflows.

## Service setup

Google uses a public translation endpoint. The Bing public endpoint currently returns 404; its adapter reports this and suggests Azure or another provider. Availability and rate limits belong to those services. For other providers, set the base URL, model, target language code and key in Settings. Examples:

| Provider | Base URL |
| --- | --- |
| OpenAI | `https://api.openai.com/v1` |
| Ollama | `http://localhost:11434` |
| LM Studio | `http://localhost:1234/v1` |
| DeepL Free | `https://api-free.deepl.com` |
| Azure | Your Azure Translator endpoint |

Claude uses an OpenAI-compatible gateway. Set the Azure region in Settings when your resource requires it. Credentials are saved in the user's app configuration directory with owner-only file permissions on Unix. They are not stored in the repository or OS keychain.

Use Settings > Speech & OCR > Download Whisper model to save a model for either engine. For faster-whisper, choose a model name such as `tiny`, `base` or `small`, or a local model directory. The first run downloads it from Hugging Face. The macOS bundle includes `whisper-cli` and Tesseract. For source runs, prepare them with `scripts/build_tools.py` or configure executable paths. Select a local GGML model or download one in Settings. Tesseract includes English; download other languages in Settings using codes such as `jpn`. Apple Vision uses macOS’s installed recognition languages.

## Tests and builds

```sh
uv run --no-sync python scripts/make_fixture.py
uv run --no-sync python scripts/make_bitmap_fixture.py
uv run --no-sync python scripts/make_format_fixtures.py  # macOS/Linux native development setup
uv run --no-sync pytest -q
```

Build a native app using the audited-library recipe in [docs/building.md](docs/building.md). The build script refuses known GPL/nonfree codec flags and excludes unused GPL-only Qt components.

Tests exercise native MPEG-4/H.264/HEVC playback and seeking, text and PGS/DVD/DVB/XSUB subtitles, inline styles, lookup, OCR, cancellation, adaptive audio, header-protected streaming, recording, translation and OpenSubtitles contracts. Both speech engines have also been checked with real speech on macOS, including Metal. Account-backed services require credentials for live acceptance; their controlled tests do not establish live account access. macOS native GUI tests require access to the window server. Linux tests run with Xvfb in CI.

`--smoke-test /absolute/report.json` writes a playback report and screenshot after 3.5 seconds, then exits. Use it with a media path and both subtitle paths to test a packaged app.

The current first-party code, documentation and authored assets are licensed under [MIT](LICENSE). The app was inspired by umlx5h's LLPlayer; its original code and assets are no longer included in the current tree. The original project retains its own license and identity.

Dependencies retain their own licenses, including LGPL components. A bundled app is not wholly MIT-licensed. Read [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md) before distributing a build; source-delivery and other LGPL obligations still need release-specific handling.
