#!/usr/bin/env python3
"""Fill @KEY@ placeholders: render.py TEMPLATE OUTPUT KEY=VALUE...

@STYLE@ is replaced by packaging/macos/resources/style.css.part. Fails if a
placeholder is left unfilled, so a missing product field never ships.
"""
import re
import sys
from pathlib import Path

src, dst, *pairs = sys.argv[1:]
values = dict(p.split("=", 1) for p in pairs)
style = Path(__file__).parent / "macos" / "resources" / "style.css.part"
values.setdefault("STYLE", style.read_text(encoding="utf-8").strip())
text = Path(src).read_text(encoding="utf-8")
text = re.sub(r"@([A-Z0-9_]+)@", lambda m: values.get(m.group(1), m.group(0)), text)
left = sorted(set(re.findall(r"@[A-Z0-9_]+@", text)))
if left:
    sys.exit(f"{src}: unfilled {' '.join(left)}")
Path(dst).write_text(text, encoding="utf-8")
