#!/usr/bin/env python3
"""Fail if a build artifact or the source tree contains personal markers.

Markers are gathered at run time and never printed or written anywhere:
the home directory path, the login name, the global git user name/email,
and anything in PRIVACY_MARKERS (";"-separated). Scanned: every file, the
members of .zip/.pkg-like archives found, and, when PyInstaller is importable,
the embedded archives of frozen executables.

Usage: privacy_scan.py PATH...   (directories skip .git, target, build, .venv)
"""
import os
import subprocess
import sys
import zipfile
from pathlib import Path


# Account names that are common words; matching them would flag every file.
GENERIC_NAMES = {"user", "users", "admin", "administrator", "owner", "guest", "default", "public", "home"}


def markers():
    home = str(Path.home())
    found = {home, home.replace("\\", "/"), os.environ.get("USER", "")}
    for name in (Path.home().name, os.environ.get("USERNAME", "")):
        if name.lower() not in GENERIC_NAMES:
            found.add(name)
    # Windows machine names often carry the owner's name (e.g. NAME-PC).
    computer = os.environ.get("COMPUTERNAME", "")
    found.add(computer)
    found.update(part for part in computer.replace("_", "-").split("-") if part.upper() not in ("PC", "DESKTOP", "LAPTOP"))
    for key in ("user.name", "user.email"):
        try:
            value = subprocess.run(["git", "config", "--global", key], capture_output=True, text=True).stdout.strip()
        except OSError:
            value = ""
        found.add(value)
        if "@" in value:
            found.add(value.split("@")[0])
    found.update(os.environ.get("PRIVACY_MARKERS", "").split(";"))
    # Short markers would match random bytes; keep meaningful ones only.
    found = {m for m in found if len(m) >= 4}
    variants = found | {m.lower() for m in found} | {m.upper() for m in found}
    # Windows binaries and resources store text as UTF-16.
    return sorted({m.encode() for m in variants} | {m.encode("utf-16-le") for m in variants})


def scan_bytes(data, marks):
    return any(m in data for m in marks)


def scan_frozen(path, marks):
    try:
        from PyInstaller.archive.readers import CArchiveReader
    except ImportError:
        return []
    hits = []
    try:
        archive = CArchiveReader(str(path))
    except Exception:
        return []
    import marshal
    for name in archive.toc:
        try:
            raw = archive.extract(name)
        except Exception:
            continue
        if raw and scan_bytes(raw, marks):
            hits.append(f"{path}::{name}")
    try:
        pyz = archive.open_embedded_archive("PYZ.pyz")
        for name in pyz.toc:
            code = pyz.extract(name)
            if code is not None and scan_bytes(marshal.dumps(code), marks):
                hits.append(f"{path}::PYZ::{name}")
    except Exception:
        pass
    return hits


SKIP_DIRS = {".git", "target", "__pycache__", ".venv", "build"}


def scan(root, marks):
    hits = []
    if root.is_file():
        paths = [root]
    else:
        paths = [p for p in root.rglob("*")
                 if p.is_file() and not p.is_symlink() and not SKIP_DIRS & set(p.relative_to(root).parts[:-1])]
    for p in paths:
        rel = str(p.relative_to(root)) if root.is_dir() else p.name
        if scan_bytes(rel.encode(), marks):
            hits.append(f"(file name) {rel}")
        try:
            data = p.read_bytes()
        except OSError:
            continue
        if scan_bytes(data, marks):
            hits.append(rel)
        if data[:4] == b"PK\x03\x04":
            try:
                with zipfile.ZipFile(p) as z:
                    for member in z.namelist():
                        if scan_bytes(member.encode(), marks) or scan_bytes(z.read(member), marks):
                            hits.append(f"{rel}::{member}")
            except zipfile.BadZipFile:
                pass
        # Frozen executables: Mach-O (macOS) or PE (Windows) with a PyInstaller archive.
        if (data[:4] in (b"\xcf\xfa\xed\xfe", b"\xca\xfe\xba\xbe") or data[:2] == b"MZ") \
                and b"MEI\014\013\012\013\016" in data:
            hits.extend(scan_frozen(p, marks))
    return hits


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if not args:
        print(__doc__)
        return 2
    marks = markers()
    total = []
    for a in args:
        total.extend(scan(Path(a).resolve(), marks))
    if total:
        print(f"privacy scan FAILED: {len(total)} location(s) contain a personal marker:")
        for h in total[:200]:
            # Location only; the matching marker is never printed.
            print("  " + h)
        return 1
    print(f"privacy scan passed ({len(marks)} markers, {len(args)} path(s))")
    return 0


if __name__ == "__main__":
    sys.exit(main())
