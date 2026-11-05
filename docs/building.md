# Building LIDS Player

The app uses LGPL Qt/FFmpeg components alongside MIT first-party code. Keep their
license notices and use the checked native-library configuration when packaging.
See [THIRD_PARTY_NOTICES.md](../THIRD_PARTY_NOTICES.md) for distribution terms.

## Linux: build and run from source

On Debian or Ubuntu, install the system dependencies:

```sh
sudo apt-get update
sudo apt-get install -y git build-essential pkg-config ffmpeg tesseract-ocr \
  tesseract-ocr-eng libegl1 libopengl0 libxcb-cursor0 libxcb-icccm4 libxcb-keysyms1 libxkbcommon-x11-0 libpulse0
```

Install [uv](https://docs.astral.sh/uv/getting-started/installation/), then:

```sh
git clone https://github.com/ArsalanDotMe/LIDS-Player.git
cd LIDS-Player
uv sync --python 3.12.13 --extra asr --extra dev --locked
uv run --no-sync llplayer
# Or open a video with two subtitle files:
uv run --no-sync llplayer /path/to/video.mkv --primary /path/to/first.srt --secondary /path/to/second.srt
```

Run this from a desktop session. Set `LLPLAYER_FFMPEG` if FFmpeg is outside PATH.
The stock dependencies are enough to run from source. The steps below prepare
custom native libraries for packaging; they aren't needed for ordinary use.
There is no Linux binary in the early release.

## macOS and Linux native packaging

Install Python 3.12, uv, a C/C++ compiler, make, pkg-config and dav1d development files.
Linux also needs zlib and GnuTLS development headers, and nasm on x86. macOS uses the system
Secure Transport framework. Install Tesseract and the native dependencies (`brew install tesseract pkg-config dav1d` on macOS, `tesseract-ocr`, `tesseract-ocr-eng` and `libdav1d-dev` on Debian/Ubuntu). CMake is used for whisper.cpp; the preparation script can run it through uv.

From the repository root:

```sh
uv sync --python 3.12.13 --extra asr --extra dev --locked
uv run --no-sync python scripts/make_assets.py
uv run --no-sync python scripts/build_lgpl_ffmpeg.py
uv run --no-sync python scripts/build_qt_ffmpeg.py
PKG_CONFIG_PATH="$PWD/.tools/ffmpeg/lib/pkgconfig" \
  uv pip install --python .venv/bin/python --no-binary av --reinstall-package av 'av==16.1.0'
uv run --no-sync python scripts/build_tools.py
uv run --no-sync python scripts/build.py
```

The output is `dist/LIDS Player.app` on macOS and `dist/LIDS Player` on Linux. The macOS
bundle is locally signed, not notarized for public distribution.

The FFmpeg recipe disables GPL/nonfree codecs and builds shared libraries. The
PyAV source build links to those libraries. The packaging checks reject known
unsupported codec flags and unexpected Qt modules, and include dependency
licenses and the custom FFmpeg source archive.

A later `uv sync` can replace the custom PyAV build or Qt libraries with stock wheels. Rebuild
PyAV, rerun `scripts/build_qt_ffmpeg.py`, and rerun the checks before packaging. `--no-sync` preserves the prepared
environment while running tools.

Qt's FFmpeg 9 build requires dav1d development files (`brew install dav1d` on
macOS, `libdav1d-dev` on Debian/Ubuntu). It replaces the wheel's FFmpeg libraries
with the same ABI and includes software AV1 decoding. H.264/HEVC hardware
acceleration remains enabled. AV1 uses dav1d even on Macs without AV1 hardware.

For an existing compatible FFmpeg build, pass its executable with
`python scripts/build.py --ffmpeg /path/to/ffmpeg`. Its libraries and distribution
terms still need to meet the same requirements.

## Windows

Source runs require Python 3.12, uv, and FFmpeg on PATH:

```powershell
uv sync --python 3.12.13 --extra asr --extra dev --locked
uv run --no-sync llplayer
```

For release packaging, the Windows workflow builds LGPL FFmpeg and dav1d from
source with Visual Studio Build Tools and MSYS2, rebuilds PyAV against those
libraries, checks the collected libraries, and verifies the packaged player.
See `.github/workflows/release.yml` for the complete toolchain and commands.
The early Windows build uses faster-whisper for speech recognition. Tesseract
and whisper.cpp can be configured separately in Settings.

## Tests

An FFmpeg executable must be available through `.tools/ffmpeg/bin/ffmpeg`, the
`LLPLAYER_FFMPEG` environment variable, or `PATH`.

```sh
uv run --no-sync python scripts/make_fixture.py
uv run --no-sync python scripts/make_bitmap_fixture.py
uv run --no-sync python scripts/make_format_fixtures.py
LLPLAYER_FIXTURE_FFMPEG=/path/to/development/ffmpeg uv run --no-sync python scripts/make_playback_fixtures.py
uv run --no-sync pytest -q
```

The common-format generator needs a development FFmpeg with libvpx, libsvtav1,
libvorbis, libopus, libmp3lame and libtheora encoders. This executable generates
synthetic test files only; packaging continues to use the audited FFmpeg build.
CI requires all 21 files and runs playback with both default and software decoding.
The matrix covers H.264, HEVC (8/10-bit), AV1 (10-bit), VP8, VP9 (8/10-bit),
MPEG-4 Part 2, MPEG-2, WMV2, MJPEG, ProRes, FLV and Theora across MP4, MKV,
WebM, MOV, AVI, TS, MPEG, WMV, FLV and Ogg. Audio includes AAC, AC-3, E-AC-3,
DTS, FLAC, Opus, Vorbis, PCM, MP2, MP3 and WMA. Each case verifies changing
video frames, non-silent decoded audio, and forward/backward seeking.

Verify the built macOS app with the same files:

```sh
uv run --no-sync python scripts/verify_playback_formats.py "dist/LIDS Player.app/Contents/MacOS/LIDS Player"
```

Use `dist/LIDS Player/LIDS Player` on Linux under Xvfb. The packaged checks produce
JSON reports, screenshots and logs in `artifacts/format-smoke/` for both modes.
These are synthetic compatibility checks; they do not cover every codec profile,
damaged file, encrypted media, or every device/platform combination.

Fixtures are generated in ignored `artifacts/`. Native GUI tests need a graphical
session; Linux CI uses Xvfb. Optional live-service checks accept a speech recording
you have permission to use:

```sh
uv run --no-sync python scripts/verify_services.py --speech /path/to/recording.wav
```

The macOS tool build compiles the MIT Swift Vision/tokenization helper and whisper.cpp with embedded Metal kernels, then bundles Tesseract and its dependent libraries. No Homebrew installation is required on the user’s Mac. Model weights are downloaded separately. The format-fixture generator uses the macOS system H.264/HEVC encoders and a small FFmpeg API helper for bitmap codecs.

For a packaged offline check, add `--smoke-tools --smoke-asr /path/to/speech.wav --smoke-whisper-model /path/to/ggml-tiny.bin` to the playback smoke command. Cache the faster-whisper model first, then set `HF_HUB_OFFLINE=1`. These checks exercise both OCR and speech engines in the bundle.
