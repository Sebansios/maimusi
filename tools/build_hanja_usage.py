#!/usr/bin/env python3
"""Build converter_data/hanja-usage-unihan-17.0.tsv from the Unihan database.

Usage: build_hanja_usage.py <Unihan directory> <hanja dictionary> <output.tsv>

For every character used by the Hanja dictionary it records:
  edu   1 if it is one of the 1,800 Korean education hanja in its normative
        form (kKoreanEducationHanja, 2007 revision); glyph pairs that differ
        from KS X 1001 are listed separately in hanja-forms.tsv
  ks    1 if it is in KS X 1001 (encodable in EUC-KR), the Korean standard set
  freq  modern Chinese corpus count (kHanyuPinlu), the highest among the
        character and its variants so Korean forms such as 寧 count as 宁
  grade Hong Kong primary-school grade (kGradeLevel, 0 when absent)
Source: Unicode Unihan database (Unicode License v3).
"""
import re
import sys
from pathlib import Path


def is_hanja(c):
    o = ord(c)
    return 0x3400 <= o <= 0x4DBF or 0x4E00 <= o <= 0x9FFF or 0xF900 <= o <= 0xFAFF or 0x20000 <= o <= 0x3FFFF


def load(fields, directory):
    data = {f: {} for f in fields}
    for path in Path(directory).glob("Unihan_*.txt"):
        with path.open(encoding="utf-8") as handle:
            for line in handle:
                if line.startswith("#") or not line.strip():
                    continue
                code, field, value = line.rstrip("\n").split("\t", 2)
                if field in data:
                    data[field][chr(int(code[2:], 16))] = value
    return data


def main():
    unihan, dictionary, output = sys.argv[1:4]
    chars = set()
    with open(dictionary, encoding="utf-8") as handle:
        for line in handle:
            if line.startswith("#") or ":" not in line:
                continue
            chars.update(c for c in line.split(":", 2)[1] if is_hanja(c))
    variant_fields = ("kSimplifiedVariant", "kTraditionalVariant", "kZVariant", "kSemanticVariant", "kSpecializedSemanticVariant")
    data = load(("kKoreanEducationHanja", "kHanyuPinlu", "kGradeLevel") + variant_fields, unihan)

    def variants(c):
        out = {c}
        for f in variant_fields:
            out.update(chr(int(code, 16)) for code in re.findall(r"U\+([0-9A-F]+)", data[f].get(c, "")))
        return out

    def raw_freq(c):
        return sum(int(n) for n in re.findall(r"\((\d+)\)", data["kHanyuPinlu"].get(c, "")))

    rows = []
    for c in sorted(chars):
        try:
            c.encode("euc_kr")
            ks = 1
        except UnicodeEncodeError:
            ks = 0
        vs = variants(c)
        freq = max(raw_freq(v) for v in vs)
        edu_list = data["kKoreanEducationHanja"]
        edu = 1 if c in edu_list else 0
        grade = int(data["kGradeLevel"].get(c, "0"))
        rows.append(f"{c}\t{edu}\t{ks}\t{freq}\t{grade}")
    header = ("# Hanja usage data derived from the Unicode Unihan database 17.0.0\n"
              "# (Unicode License v3, see LICENSE-Unicode.txt). Columns: char, edu, ks, freq, grade\n")
    Path(output).write_text(header + "\n".join(rows) + "\n", encoding="utf-8")
    print(f"{len(rows)} characters -> {output}")


if __name__ == "__main__":
    main()
