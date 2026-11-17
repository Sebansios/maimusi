#!/usr/bin/env python3
"""Copy licence notices of the frozen engine's runtime into a folder.

Run with the engine's Python: collect_licenses.py <output-dir>
Copies each distribution's licence files, the Python licence, full LGPL/GPL
texts (Kiwi is LGPL) and where to get the LGPL sources for relinking.
"""
import importlib.metadata as md
import json
import shutil
import sys
import sysconfig
from pathlib import Path

RUNTIME = ("kiwipiepy", "kiwipiepy_model", "numpy", "tqdm", "pint", "flexcache", "flexparser",
           "platformdirs", "typing_extensions", "regex", "korean_lunar_calendar", "pyinstaller")
HERE = Path(__file__).resolve().parent


def main():
    out = Path(sys.argv[1])
    out.mkdir(parents=True, exist_ok=True)
    components = []
    for name in RUNTIME:
        dist = md.distribution(name)
        meta = dist.metadata
        components.append({
            "name": meta["Name"], "version": dist.version,
            "license": meta.get("License-Expression") or meta.get("License", ""),
        })
        for f in dist.files or []:
            parts = Path(str(f)).parts
            if any(p.lower().startswith(("license", "licence", "copying", "notice", "authors")) for p in parts):
                src = Path(dist.locate_file(f))
                if src.is_file():
                    dst = out / name / Path(str(f)).name
                    dst.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(src, dst)
    # macOS framework builds keep it in the stdlib, Windows builds in the
    # installation root (with the notices for the bundled OpenSSL, libffi and
    # Microsoft runtime).
    for py_license in (Path(sysconfig.get_paths()["stdlib"]) / "LICENSE.txt",
                       Path(sys.base_prefix) / "LICENSE.txt"):
        if py_license.is_file():
            shutil.copy2(py_license, out / "Python-LICENSE.txt")
            break
    else:
        sys.exit("Python LICENSE.txt not found")
    for text in (HERE / "license-texts").glob("*.txt"):
        shutil.copy2(text, out / text.name)
    (out / "components.json").write_text(json.dumps(components, indent=2, ensure_ascii=False), encoding="utf-8")
    sources = {
        "Kiwi / kiwipiepy (LGPL)": "https://github.com/bab2min/kiwipiepy/tree/v0.22.2",
        "Kiwi model (LGPL)": "https://pypi.org/project/kiwipiepy-model/0.22.1/#files",
        "note": ("The engine loads these as separate, replaceable files inside "
                 "engine\\_internal in the installation folder; rebuild with windows/build_engine.ps1."
                 if sys.platform == "win32" else
                 "The engine loads these as separate, replaceable files inside "
                 "Contents/Helpers/hangul-engine/_internal; rebuild with macos/build_engine.sh."),
    }
    (out / "source-locations.json").write_text(json.dumps(sources, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"   {len(components)} components -> {out}")


if __name__ == "__main__":
    main()
