# Licensing scope and third-party notices

The root `LICENSE` and the `MIT` package metadata cover the current first-party
Python source, build/test scripts, documentation and newly authored icon and
tone fixture. They do not relicense dependencies, model weights, external tools,
third-party license documents, or material in earlier Git commits.

The original LLPlayer implementation was distributed under GPL. Its code and
assets have been removed from the current tree. No permission to relicense that
historical implementation is asserted.

## Runtime components

| Component | Source license / distribution terms | Notes |
| --- | --- | --- |
| PySide6, Shiboken, Qt Core/Gui/Widgets/Network/Multimedia/Svg | LGPL-3.0 option for the modules used | Dynamically linked, unmodified. GPL-only virtual keyboard and unused QML/PDF components are excluded from app packaging. |
| PyAV | BSD-3-Clause source | Release build must use the source build against audited LGPL FFmpeg, not assume the stock wheel's native libraries are permissive. |
| FFmpeg utility and PyAV libraries | LGPL-2.1-or-later for the supplied custom build | Built from FFmpeg 8.0.1, without GPL/nonfree codecs or x264/x265. Recipe, checksum and source archive are recorded. |
| Qt's FFmpeg | LGPL-2.1-or-later | Custom 9.0.1 build with dav1d software AV1 decoding; source archive, checksum and build manifest included. |
| dav1d | BSD-2-Clause | Software AV1 decoder, dynamically linked; COPYING included. |
| Janome | Apache-2.0 with bundled dictionary notices | Japanese segmentation; included NOTICE preserves MeCab IPADIC/NAIST/ICOT terms. |
| charset-normalizer | MIT | Legacy subtitle encoding detection. |
| whisper.cpp / ggml | MIT | Pinned unmodified speech engine; Metal kernels embedded on macOS. |
| Tesseract / Leptonica | Apache-2.0 / BSD-2-Clause | Bundled OCR and native dependencies retain their collected notices. English language data is separate Apache-2.0 data. |
| pysubs2 | MIT | Subtitle parsing and writing. |
| HTTPX, HTTPCore, IDNA | BSD-3-Clause | Network requests; dependent packages retain their own terms. |
| yt-dlp source package | Unlicense | Third-party/extracted site content is not covered by that license. |
| Pillow | MIT-CMU | Also includes third-party image-codec notices. |
| faster-whisper, CTranslate2, ONNX Runtime | MIT | Speech inference; ONNX Runtime's ThirdPartyNotices are included. |
| Hugging Face Hub, tokenizers, hf-xet, FlatBuffers | Apache-2.0 | Download/tokenization/inference support. |
| NumPy | BSD-3-Clause and bundled permissive licenses | See the collected upstream license files for the actual binary distribution. |
| certifi | MPL-2.0 | Separate certificate-data component. |
| tqdm | MPL-2.0 and MIT | License text describes which portions each license covers. |
| Python | PSF license and included third-party terms | The interpreter is not MIT-licensed by this repository. |

The dependency versions are pinned in `uv.lock`. Package metadata alone does not
fully describe a native wheel. Build instructions and native-library checks are
in `docs/building.md` and `scripts/`. License-document source URLs and pinned
versions are recorded in `scripts/collect_notices.py`.

License texts are in `third_party/licenses/`. Pillow's binary license document
includes its native image-library terms. For FreeType we select the FreeType
License option, not the alternative GPL option. Portions of this software use
the FreeType Project (https://freetype.org/); its copyright notices and license
are reproduced in Pillow's collected license document. The bundled liblzma is a
library; GPL notices in its upstream text also discuss separate build/scripts
that are not the shipped library. PyInstaller is a development tool
under GPL with a bootloader exception permitting distribution of applications
under other licenses. Its exception and license text are included. The presence
of a GPL license document in the notices does not change the first-party license.

## Downloads and external tools

Whisper models, user-selected model repositories, Tesseract language data, online
media and translation-service responses are separate inputs. Check their actual
licenses and service terms before redistributing them. No speech model or
third-party recording is committed or bundled as a first-party asset.

The macOS bundle includes Tesseract, its native dependencies and English data, plus whisper.cpp. The app calls them through ordinary process arguments and files. Their licenses remain their own; collected native OCR notices and the pinned whisper.cpp source revision are in `third_party/licenses/`. Apple Vision and NaturalLanguage are system frameworks supplied by macOS. The MIT grant does not grant trademark rights to the LLPlayer name or to
third-party brands.

## Before distributing a native app

A native app is a collection of components under multiple licenses, not an
MIT-only artifact. In particular:

- Retain the first-party MIT notice and all applicable dependency copyright,
  license and third-party attribution documents.
- For LGPL components, preserve users' ability to replace/relink the libraries
  and debug modifications. Do not impose reverse-engineering restrictions that
  conflict with those rights. The bundle uses dynamic libraries and no custom
  anti-replacement protection, but signing/notarization and any installer terms
  must also be assessed.
- Supply the exact corresponding source and build materials required by the
  LGPL versions and distribution method you choose. The custom FFmpeg source
  archive and recipe are included in the local bundle. Matching Qt/PySide/Shiboken source is supplied in the release asset
  `LGPL-sources.tar.gz`. Custom FFmpeg source and build manifests accompany
  each app in `third_party/sources`, with dav1d source in the Windows build.
  The release commit contains the packaging scripts.
- Re-audit the actual artifacts for each operating system and dependency update.
  macOS findings do not clear Windows or Linux wheels.

No public-distribution legal clearance or patent/trademark clearance is claimed.
