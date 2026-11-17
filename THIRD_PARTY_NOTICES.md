# Third-party notices

This input method is built from original code by Sebansios plus the
open-source components below. Original source in this repository is published
with rights reserved; see the root `LICENSE` notice. Official binary releases
are provided under their accompanying end user license agreement (template:
`packaging/LICENSE.txt.in`). Each component listed here
remains under its own licence, which prevails for that component. Full
licence texts ship in the `Licenses` folder: inside the app under
`Contents/Resources/Licenses/` on macOS, in the installation folder
(`C:\Program Files\Maimusi\<version>\Licenses\`) on Windows.

## Built into the input method

| Component | Use | Licence |
|---|---|---|
| unicode-segmentation 1.12.0 | grapheme-safe manual segment boundaries | MIT OR Apache-2.0 |

unicode-segmentation is vendored without source changes at
`core/vendor/unicode-segmentation-1.12.0`, from
https://static.crates.io/crates/unicode-segmentation/unicode-segmentation-1.12.0.crate.
The archive SHA-256 is
`f6ccf251212114b54433ec949fd6a7841275f9ada20dddd2f29e9ceea4501493`,
verified against the crates.io index. Its MIT and Apache-2.0 license texts
ship in `Licenses/unicode-segmentation/`.

## Fonts (Windows)

No font ships with the Windows version (0.5.3 build 33 and later). The
candidate window, the settings and the input mode icon use the system's
Malgun Gothic, and Batang for the 한지 candidate look.


## Fonts (macOS)

| Component | Use | Licence |
|---|---|---|
| Noto Sans CJK KR 2.004 Regular, © 2014-2021 Adobe | candidate window (default) | SIL Open Font License 1.1 |
| Noto Serif CJK KR 2.003 Regular, © 2017-2024 Adobe | candidate window (‘한지’ preset) | SIL Open Font License 1.1 |

Both fonts are subsets made with fontTools (`macos/tools/prepare_fonts.py`):
Hangul, Latin for romanization, punctuation and symbols, and the 4,888 hanja
of KS X 1001. Characters outside the subset are drawn by macOS font fallback.
They ship in `Contents/Resources/Fonts/` and are registered for the input
method process only; they are not installed into the system. The licence
text with the copyright lines is in `Licenses/fonts/NotoCJK-OFL.txt`.
## Spacing models trained on the NIKL corpora (모두의 말뭉치)

이 프로그램의 띄어쓰기 모델은 국립국어원 「모두의 말뭉치」(지역어 말뭉치 2021, 일상 대화 말뭉치
2020–2024, 메신저 말뭉치, 구어 말뭉치, 온라인 대화 말뭉치 2021, 온라인 게시 자료 말뭉치 2022,
비출판물 말뭉치)를 이용하여 학습하였습니다.

The spacing models below were trained on corpora provided by the National
Institute of Korean Language (NIKL), whose approval for publishing these
results was granted on 2026-10-14. They contain numerical statistics and
weights, not corpus text. They are not covered by any open-source licence and
may only be redistributed as part of this software.

| File | Use | Training data |
|---|---|---|
| `spacing.hspm` (macOS `Contents/Resources/`, Windows installation folder) | built-in light engine (Intel Macs, sandboxed Windows apps, and while the main engine loads) | NIKL regional dialect 2021, messenger, daily conversation 2021–2022 (about 30,000 sentences) |
| `hangul_ime/models/boundary-refiner.npz` (macOS `Contents/Helpers/HangulEngine.app/...`, Windows `engine\_internal\`) | boundary refiner applied after Kiwi | the NIKL corpora listed above (about 660,000 sentences) |

## Kiwi engine helper (macOS `Contents/Helpers/HangulEngine.app`, Windows `engine\MaimusiEngine.exe`)

| Component | Version | Licence |
|---|---|---|
| Kiwi / kiwipiepy (Korean morphological analyser) | 0.22.2 | LGPL (texts in `Licenses/engine/`) |
| kiwipiepy_model (Kiwi language model) | 0.22.1 | LGPL v3 |
| Python runtime | 3.13 | PSF License |
| NumPy | 2.5.3 | BSD-3-Clause and others |
| Pint, flexcache, flexparser | 0.25.2 / 0.3 / 0.4 | BSD |
| regex | 2026.2.28 | Apache-2.0 and CNRI-Python |
| tqdm | 4.70.1 | MPL-2.0 and MIT |
| platformdirs | 4.11.11 | MIT |
| typing_extensions | 4.16.0 | PSF-2.0 |
| korean-lunar-calendar | 0.4.0 | MIT |
| PyInstaller bootloader | 6.19.0 | GPL-2.0 with bootloader exception |
| OpenSSL (Windows: `libcrypto-3.dll`, `libssl-3.dll`, part of the Python runtime) | 3.x | Apache-2.0 |
| libffi (Windows: `libffi-8.dll`, part of the Python runtime) | 3.x | MIT |
| Microsoft Visual C++ Runtime and Universal C Runtime (Windows: `VCRUNTIME140*.dll`, `ucrtbase.dll`, `api-ms-win-*.dll`) | 14.x | redistributable under the Microsoft Visual Studio license terms |

The Python runtime licence is in `Licenses/engine/Python-LICENSE.txt`. On
Windows it also contains the notices for the libraries bundled with the
Windows build of Python (OpenSSL, libffi, bzip2, xz, zlib, mpdecimal and
others) and the conditions for the Microsoft Distributable Code.

Kiwi and its model are loaded as separate files that can be replaced; their
sources are listed in `Licenses/engine/source-locations.json`. Kiwi's source
code is available at https://github.com/bab2min/Kiwi and
https://github.com/bab2min/kiwipiepy. To use a modified Kiwi on macOS, replace
the library files inside `Contents/Helpers/HangulEngine.app` and re-sign the
app ad hoc (`codesign --force --deep --sign - <app>`). On Windows, Kiwi is
the extension module `engine\_internal\_kiwipiepy.pyd` and its model is in
`engine\_internal\kiwipiepy_model\` in the installation folder; replace them
with a build of the same kiwipiepy interface (the files are not signed, so
nothing else needs to change), or rebuild the whole engine with
`windows/build_engine.ps1`. The engine starts again with the next input.

## Conversion data (`hangul_ime/converter_data`)

| Data | Licence |
|---|---|
| Unicode Emoji 17.0 `emoji-test.txt` | Unicode License v3 |
| Unicode CLDR 48.2 annotations (ko, en) | Unicode License v3 |
| Unicode Unihan 17.0 (kKoreanEducationHanja, kHanyuPinlu, kGradeLevel, variant fields; derived tables `hanja-usage-unihan-17.0.tsv`, `hanja-forms.tsv`) | Unicode License v3 |
| libhangul 0.2.0 `hanja.txt` (data file only, not the library) | BSD-3-Clause (header of the file) |

Upstream copyright lines in these notices belong to the upstream authors.

## Informal spacing vocabulary (`hangul_ime/spacing_data`)

The reviewed 78-entry noun subset in `open-korean-text-slangs.tsv` is derived
from Open Korean Text's `noun/slangs.txt`, commit
`74cc4ae7d3dab232747cd5ddb723e4b73c476e4f`.
Copyright 2014 Twitter, Inc. Licensed under Apache-2.0. Changes: selected noun
entries, excluded predicates/phrases/single syllables, added Kiwi POS and scores.
The complete license ships as `Licenses/engine/LICENSE-open-korean-text.txt`.
Source URL, source hash and selection rules are in `spacing_data/README.md`.
The other noun list and morphology variants were authored for this project.
