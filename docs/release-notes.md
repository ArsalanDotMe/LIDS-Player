Early preview of LIDS Player, a language-learning media player inspired by [umlx5h/LLPlayer](https://github.com/umlx5h/LLPlayer).

- Redesigned player with dual subtitles, a searchable transcript, word lookup, and line repeat.
- Speech subtitle generation, translation, OCR, and SRT export.
- Native Windows x64 and macOS Apple Silicon builds. Linux users can [build and run from source](https://github.com/ArsalanDotMe/LIDS-Player/blob/main/docs/building.md#linux-build-and-run-from-source).

Download the ZIP for your platform. On Windows, extract the entire folder before opening `LIDS Player.exe`. On macOS, move `LIDS Player.app` to Applications. The macOS preview is ad-hoc signed and is not notarized; macOS may require approval in Privacy & Security. Windows builds are unsigned.

This is an early preview. Settings and behavior may change. Speech models download separately. The Windows build uses faster-whisper; whisper.cpp and Tesseract can be configured separately. Account-backed translation and subtitle providers need your own credentials.

`SHA256SUMS.txt` lists archive checksums. `LGPL-sources.tar.gz` supplies matching Qt/PySide6/Shiboken sources. Custom FFmpeg sources, build manifests, and dependency notices are included in the app under `third_party`. The first-party code is MIT-licensed; dependencies retain their own licenses.
