#!/usr/bin/env python3
"""후보 창 기본 글꼴(Noto Sans/Serif CJK KR Regular)을 빌드 입력으로 준비한다.

    python3 macos/tools/prepare_fonts.py [build/fonts] [--sans NotoSansCJK.ttc] [--serif NotoSerifCJK-Regular.ttc]

Noto CJK 글꼴 모음(.ttc, SIL OFL 1.1)에서 한국어(KR) Regular 하나씩만 꺼내, 후보 창에 나오는
글자만 남긴 부분 글꼴(.otf)로 저장하고 fonts.json에 버전·저작권·SHA-256을 남긴다.
남기는 글자: 한글(음절·자모), 로마자 표기용 라틴 문자, 문장 부호·기호, KS X 1001 한자 4,888자.
그 밖의 확장 한자는 macOS가 다른 글꼴로 대신 그린다. 전체 글꼴(41 MB)을 넣으면 설치 파일이
약 34 MB 커지고, 이 부분 글꼴은 약 10 MB 커진다.
결과물은 Git에 넣지 않는다(빌드 입력, 모델과 같은 취급). .otf를 직접 주면 그것을 줄인다.

확장 한자가 처음 나올 때 앱이 받는 전체 글꼴도 full/에 만든다(파일 이름에 판 번호).
이것을 FULL_BASE 주소에 올려야 한다:
    npx wrangler r2 object put maimusi/maimusi/fonts/<파일> --file build/fonts/full/<파일> --remote
"""
import argparse
import hashlib
import json
from pathlib import Path
import shutil

from fontTools import subset
from fontTools.ttLib import TTCollection, TTFont

FONTS = Path.home() / "Library" / "Fonts"
FULL_BASE = "https://dl.sebansios.com/maimusi/fonts/"
WANTED = {
    "sans": ("Noto Sans CJK KR", "NotoSansCJKkr-Regular.otf", FONTS / "NotoSansCJK.ttc"),
    "serif": ("Noto Serif CJK KR", "NotoSerifCJKkr-Regular.otf", FONTS / "NotoSerifCJK-Regular.ttc"),
}


def extract(source: Path, family: str, dest: Path) -> TTFont:
    if source.suffix.lower() == ".otf":
        shutil.copyfile(source, dest)
        return TTFont(dest)
    for font in TTCollection(source).fonts:
        name = font["name"]
        if name.getDebugName(1) == family and name.getDebugName(2) == "Regular":
            font.save(dest)
            return TTFont(dest)
    raise SystemExit(f"{family} Regular not found in {source.name}")


# 한글, 라틴(로마자 표기 ŏ·ŭ·ā 등 포함), 문장 부호·기호, 원문자, 전각.
RANGES = [(0x20, 0x24F), (0x250, 0x2FF), (0x300, 0x36F), (0x1100, 0x11FF), (0x1E00, 0x1EFF),
          (0x2000, 0x2BFF), (0x3000, 0x303F), (0x3130, 0x318F), (0x3200, 0x33FF), (0xA960, 0xA97F),
          (0xAC00, 0xD7A3), (0xD7B0, 0xD7FF), (0xFE30, 0xFE4F), (0xFF00, 0xFFEF)]


def ks_x_1001_hanja():
    raw = bytes(b for hi in range(0xCA, 0xFE) for lo in range(0xA1, 0xFF) for b in (hi, lo))
    return {ord(c) for c in raw.decode("euc-kr", errors="ignore")
            if 0x4E00 <= ord(c) <= 0x9FFF or 0xF900 <= ord(c) <= 0xFAFF}


def shrink(path: Path):
    unicodes = {c for start, end in RANGES for c in range(start, end + 1)} | ks_x_1001_hanja()
    options = subset.Options()
    options.layout_features = ["*"]
    options.name_IDs = ["*"]
    options.name_languages = ["*"]
    options.notdef_outline = True
    font = TTFont(path)
    subsetter = subset.Subsetter(options)
    subsetter.populate(unicodes=unicodes)
    subsetter.subset(font)
    font.save(path)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("out", nargs="?", default=str(Path(__file__).resolve().parents[2] / "build" / "fonts"))
    parser.add_argument("--sans", type=Path, default=WANTED["sans"][2])
    parser.add_argument("--serif", type=Path, default=WANTED["serif"][2])
    args = parser.parse_args()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    record = []
    (out / "full").mkdir(exist_ok=True)
    for key, source in (("sans", args.sans), ("serif", args.serif)):
        family, filename, _ = WANTED[key]
        extract(source, family, out / filename)
        full_version = TTFont(out / filename)["name"].getDebugName(5).split(";")[0].replace("Version ", "")
        full_name = filename.replace(".otf", f"-{full_version}.otf")
        shutil.copyfile(out / filename, out / "full" / full_name)
        full_bytes = (out / "full" / full_name).read_bytes()
        shrink(out / filename)
        font = TTFont(out / filename)
        name = font["name"]
        record.append({
            "file": filename,
            "family": family,
            "version": name.getDebugName(5),
            "copyright": name.getDebugName(0),
            "license": "SIL Open Font License 1.1",
            "subset": "Hangul, Latin for romanization, punctuation and symbols, KS X 1001 hanja",
            "source": source.name,
            "sha256": hashlib.sha256((out / filename).read_bytes()).hexdigest(),
            "bytes": (out / filename).stat().st_size,
            "full": {
                "file": full_name,
                "url": FULL_BASE + full_name,
                "sha256": hashlib.sha256(full_bytes).hexdigest(),
                "bytes": len(full_bytes),
            },
        })
        print(f"{filename}  {record[-1]['version']}  {record[-1]['sha256'][:16]}")
    (out / "fonts.json").write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
