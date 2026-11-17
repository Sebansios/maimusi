#!/usr/bin/env python3
"""매무시 업데이트 정보(서명된 JSON) 만들기·검증. 형식과 출시 순서는 docs/UPDATES.md.

  keygen --id ID --out DIR
      Ed25519 키 한 쌍을 만든다. 개인키는 DIR/ID.key(권한 600)에 쓰고 공개키를 출력한다.
      개인키는 저장소·Drive에 두지 않는다.
  sign --platform macos|windows --file 설치파일 --key DIR/ID.key [--url URL] [--notes 파일]
       [--page URL] [--minimum-os 13.0] [--arch arm64 --arch x86_64] [--out 경로]
      versions.json의 제품·빌드 번호로 업데이트 정보를 만들고 서명한다.
  verify 업데이트정보 [--file 설치파일] [--platform P] [--keys packaging/update-keys.json]
      앱과 같은 규칙으로 서명·형식을 확인하고, 설치 파일을 주면 크기·SHA-256도 대조한다.

서명은 "maimusi-update/1\\n" + payload 바이트에 대한 Ed25519 서명이다.
"""
from __future__ import annotations

import argparse
import base64
import datetime as _dt
import hashlib
import json
import os
import re
import sys
from pathlib import Path

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey
from cryptography.hazmat.primitives.serialization import Encoding, PrivateFormat, PublicFormat, NoEncryption

ROOT = Path(__file__).resolve().parent.parent
FORMAT = "maimusi-update"
VERSION = 1
DOMAIN = b"maimusi-update/1\n"
MAX_MANIFEST = 64 * 1024
MAX_NOTES = 8
MAX_NOTE = 200
DOWNLOAD_BASE = "https://dl.sebansios.com/maimusi/"
PAGE = "https://sebansios.com/maimusi"
PLATFORMS = ("macos", "windows")
KEY_ID = re.compile(r"^[a-z0-9][a-z0-9-]{0,31}$")


def b64(data: bytes) -> str:
    return base64.b64encode(data).decode("ascii")


def unb64(text: str) -> bytes:
    return base64.b64decode(text.encode("ascii"), validate=True)


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def load_keys(path: Path) -> dict[str, bytes]:
    data = json.loads(path.read_text(encoding="utf-8"))
    keys = {k: unb64(v) for k, v in data.get("keys", {}).items()}
    for k, v in keys.items():
        if not KEY_ID.match(k) or len(v) != 32:
            raise SystemExit(f"bad public key entry: {k}")
    return keys


def keygen(args) -> int:
    if not KEY_ID.match(args.id):
        raise SystemExit("key id: lowercase letters, digits and '-' only")
    out = Path(args.out).expanduser()
    out.mkdir(parents=True, exist_ok=True)
    os.chmod(out, 0o700)
    target = out / f"{args.id}.key"
    if target.exists():
        raise SystemExit(f"{target} exists; refusing to overwrite a signing key")
    key = Ed25519PrivateKey.generate()
    private = key.private_bytes(Encoding.Raw, PrivateFormat.Raw, NoEncryption())
    public = key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
    body = json.dumps({"id": args.id, "private": b64(private), "public": b64(public)}, indent=2) + "\n"
    fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(body)
    print(f"{args.id} {b64(public)}")
    return 0


def read_notes(path: str | None) -> list[str]:
    if not path:
        return []
    notes = []
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        line = re.sub(r"^\s*[-*•]\s*", "", line).strip()
        if line:
            notes.append(line)
    if len(notes) > MAX_NOTES or any(len(n) > MAX_NOTE for n in notes):
        raise SystemExit(f"notes: at most {MAX_NOTES} lines of {MAX_NOTE} characters")
    return notes


def build_payload(args) -> dict:
    versions = json.loads((ROOT / "versions.json").read_text(encoding="utf-8"))
    file = Path(args.file)
    url = args.url or DOWNLOAD_BASE + file.name
    if not url.startswith("https://") and not url.startswith("http://127.0.0.1:"):
        raise SystemExit("download url must be https")
    if url.startswith("http://"):
        print("warning: loopback http url; only the app's --test-update accepts it", file=sys.stderr)
    payload = {
        "format": FORMAT,
        "version": VERSION,
        "platform": args.platform,
        "channel": "stable",
        "product": versions["product"],
        "label": versions.get("release_label", ""),
        "build": int(versions["build"]),
        "published": _dt.date.today().isoformat(),
        "notes": read_notes(args.notes),
        "page": args.page or PAGE,
        "file": {"name": file.name, "url": url, "bytes": file.stat().st_size, "sha256": sha256_file(file)},
    }
    if args.minimum_os:
        payload["minimum_os"] = args.minimum_os
    if args.arch:
        payload["architectures"] = sorted(set(args.arch))
    return payload


def sign(args) -> int:
    key_data = json.loads(Path(args.key).expanduser().read_text(encoding="utf-8"))
    key_id = key_data["id"]
    key = Ed25519PrivateKey.from_private_bytes(unb64(key_data["private"]))
    public = key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
    keys = load_keys(Path(args.keys))
    if keys.get(key_id) != public:
        raise SystemExit(f"key {key_id} is not in {args.keys}; the app would reject this manifest")
    payload = json.dumps(build_payload(args), ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    envelope = {
        "format": FORMAT,
        "key": key_id,
        "payload": b64(payload),
        "signature": b64(key.sign(DOMAIN + payload)),
    }
    text = json.dumps(envelope, indent=2) + "\n"
    if len(text.encode()) > MAX_MANIFEST:
        raise SystemExit("manifest too large")
    if args.out:
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.out).write_text(text, encoding="utf-8")
    else:
        sys.stdout.write(text)
    return 0


def verify_manifest(data: bytes, keys: dict[str, bytes], platform: str | None = None,
                    allow_loopback: bool = False) -> dict:
    """앱(Updater.swift)과 같은 규칙. 통과하면 payload를 돌려준다."""
    if len(data) > MAX_MANIFEST:
        raise ValueError("manifest too large")
    envelope = json.loads(data)
    if envelope.get("format") != FORMAT:
        raise ValueError("not a maimusi-update file")
    public = keys.get(envelope.get("key", ""))
    if public is None:
        raise ValueError("unknown signing key")
    payload = unb64(envelope["payload"])
    try:
        Ed25519PublicKey.from_public_bytes(public).verify(unb64(envelope["signature"]), DOMAIN + payload)
    except InvalidSignature:
        raise ValueError("bad signature") from None
    info = json.loads(payload)
    if info.get("format") != FORMAT or info.get("version") != VERSION:
        raise ValueError("unsupported payload version")
    if info.get("platform") not in PLATFORMS or (platform and info["platform"] != platform):
        raise ValueError("wrong platform")
    if info.get("channel") != "stable":
        raise ValueError("not a stable release")
    file = info.get("file", {})
    url = str(file.get("url", ""))
    if not (url.startswith("https://") or (allow_loopback and url.startswith("http://127.0.0.1:"))) or not re.fullmatch(r"[0-9a-f]{64}", file.get("sha256", "")):
        raise ValueError("bad file entry")
    if not isinstance(info.get("build"), int) or info["build"] <= 0:
        raise ValueError("bad build")
    return info


def verify(args) -> int:
    info = verify_manifest(Path(args.manifest).read_bytes(), load_keys(Path(args.keys)), args.platform)
    print(f"OK {info['platform']} {info['product']} {info['label']} build {info['build']} -> {info['file']['url']}")
    if args.file:
        path = Path(args.file)
        if path.stat().st_size != info["file"]["bytes"] or sha256_file(path) != info["file"]["sha256"]:
            print("FILE MISMATCH", file=sys.stderr)
            return 1
        print(f"OK file {path.name} {info['file']['bytes']} bytes")
    return 0


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    k = sub.add_parser("keygen")
    k.add_argument("--id", required=True)
    k.add_argument("--out", required=True)
    s = sub.add_parser("sign")
    s.add_argument("--platform", choices=PLATFORMS, required=True)
    s.add_argument("--file", required=True)
    s.add_argument("--key", required=True)
    s.add_argument("--keys", default=str(ROOT / "packaging/update-keys.json"))
    s.add_argument("--url")
    s.add_argument("--notes")
    s.add_argument("--page")
    s.add_argument("--minimum-os")
    s.add_argument("--arch", action="append")
    s.add_argument("--out")
    v = sub.add_parser("verify")
    v.add_argument("manifest")
    v.add_argument("--file")
    v.add_argument("--platform", choices=PLATFORMS)
    v.add_argument("--keys", default=str(ROOT / "packaging/update-keys.json"))
    args = p.parse_args(argv)
    return {"keygen": keygen, "sign": sign, "verify": verify}[args.cmd](args)


if __name__ == "__main__":
    raise SystemExit(main())
