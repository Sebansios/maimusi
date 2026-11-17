#!/usr/bin/env python3
"""서명된 업데이트 정보를 순서대로 만들고 올린다(docs/UPDATES.md 「출시 순서」).

  python3 tools/publish_update.py --platform macos --key /path/to/signing-key.key --file build/dist/Maimusi-0.5.4.pkg --notes notes.txt [--publish]

1. 설치 파일이 공개 주소(dl.sebansios.com/maimusi/<이름>)에 이미 있고 크기·SHA-256이 같은지 확인한다.
   없거나 다르면 멈춘다. 업데이트 정보가 먼저 올라가면 앱이 받을 수 없는 파일을 알리게 된다.
2. 지금 올라가 있는 업데이트 정보가 있으면 서명을 확인하고, 새 빌드가 그보다 높은지 본다(실수로 낮은 판을
   덮어쓰지 않게). --allow-same-build로만 같은 빌드를 다시 올린다(설명만 고칠 때).
3. versions.json의 번호로 서명해 build/dist/update/<플랫폼>.json에 쓰고 앱과 같은 규칙으로 검증한다.
4. --publish를 주면 R2(버킷 maimusi, 키 maimusi/update/<플랫폼>.json)에 올리고, 공개 주소에서 다시 받아
   바이트가 같은지·서명이 맞는지 확인한다. --publish가 없으면 올릴 명령만 보여 준다.

서명 개인키는 --key 또는 MAIMUSI_UPDATE_KEY 환경변수로 지정한다.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shlex
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import update_manifest as um  # noqa: E402

ROOT = um.ROOT
PUBLIC = "https://dl.sebansios.com/maimusi/"
BUCKET_PREFIX = "maimusi/maimusi/"
HEADERS = {"User-Agent": "Maimusi-release", "Cache-Control": "no-cache"}


def fetch(url: str, limit: int | None = None) -> bytes | None:
    request = urllib.request.Request(url, headers=HEADERS)
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            return response.read(limit + 1 if limit else -1)
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return None
        raise


def remote_sha256(url: str) -> tuple[int, str] | None:
    request = urllib.request.Request(url, headers=HEADERS)
    h = hashlib.sha256()
    size = 0
    try:
        with urllib.request.urlopen(request, timeout=120) as response:
            for chunk in iter(lambda: response.read(1 << 20), b""):
                h.update(chunk)
                size += len(chunk)
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return None
        raise
    return size, h.hexdigest()


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--platform", choices=um.PLATFORMS, required=True)
    p.add_argument("--file", required=True, help="올린 것과 같은 설치 파일")
    p.add_argument("--notes", help="알림에 보일 설명(한 줄에 하나, 최대 8줄)")
    p.add_argument("--key", default=os.environ.get("MAIMUSI_UPDATE_KEY"),
                   help="서명 개인키 경로 (또는 MAIMUSI_UPDATE_KEY)")
    p.add_argument("--keys", default=str(ROOT / "packaging/update-keys.json"), help="시험용")
    p.add_argument("--out-dir", default=str(ROOT / "build/dist/update"), help="시험용")
    p.add_argument("--minimum-os", default="13.0", help="macOS만. 빈 문자열이면 생략")
    p.add_argument("--allow-same-build", action="store_true")
    p.add_argument("--publish", action="store_true", help="R2에 올리고 공개 주소에서 확인")
    p.add_argument("--wrangler", default=os.environ.get("WRANGLER", "npx wrangler"))
    args = p.parse_args(argv)
    if not args.key:
        p.error("--key 또는 MAIMUSI_UPDATE_KEY로 서명 개인키를 지정하세요")
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(line_buffering=True)  # 멈춤 메시지(stderr)와 순서가 맞게

    subprocess.run([sys.executable, str(ROOT / "tools/versions.py"), "check"], check=True)
    file = Path(args.file)
    keys = um.load_keys(Path(args.keys))
    name = f"{args.platform}.json"
    manifest_url = PUBLIC + "update/" + name

    # 1. 설치 파일이 먼저 공개돼 있어야 한다.
    local = (file.stat().st_size, um.sha256_file(file))
    print(f"설치 파일 공개 주소 확인: {PUBLIC + file.name}")
    remote = remote_sha256(PUBLIC + file.name)
    if remote is None:
        print("멈춤: 설치 파일이 아직 공개 주소에 없다. 먼저 올리고 해시를 대조한다.", file=sys.stderr)
        return 1
    if remote != local:
        print(f"멈춤: 공개된 설치 파일이 다르다(공개 {remote[0]} B {remote[1][:12]}…, 로컬 {local[0]} B {local[1][:12]}…).",
              file=sys.stderr)
        return 1
    print(f"  같음: {local[0]} B, sha256 {local[1]}")

    # 2. 지금 올라가 있는 판보다 높아야 한다.
    current = fetch(manifest_url, um.MAX_MANIFEST)
    build = int(json.loads((ROOT / "versions.json").read_text())["build"])
    if current is not None:
        try:
            info = um.verify_manifest(current, keys, args.platform)
            print(f"지금 올라가 있는 판: {info['product']} {info['label']} build {info['build']}")
            if build < info["build"] or (build == info["build"] and not args.allow_same_build):
                print(f"멈춤: 새 빌드 {build}가 올라가 있는 빌드 {info['build']}보다 높지 않다.", file=sys.stderr)
                return 1
        except ValueError as e:
            print(f"경고: 올라가 있는 업데이트 정보를 검증하지 못함({e}). 덮어쓴다.", file=sys.stderr)
    else:
        print("올라가 있는 업데이트 정보 없음(처음 올림).")

    # 3. 서명과 검증.
    out = Path(args.out_dir) / name
    sign = ["sign", "--platform", args.platform, "--file", str(file), "--key", args.key, "--keys", args.keys,
            "--out", str(out)]
    if args.notes:
        sign += ["--notes", args.notes]
    if args.platform == "macos" and args.minimum_os:
        sign += ["--minimum-os", args.minimum_os]
    um.main(sign)
    info = um.verify_manifest(out.read_bytes(), keys, args.platform)
    if info["file"]["sha256"] != local[1] or info["file"]["url"] != PUBLIC + file.name:
        print("멈춤: 서명한 정보가 설치 파일과 맞지 않는다.", file=sys.stderr)
        return 1
    app = ROOT / "build/macos.noindex/HangulSpacing.app/Contents/MacOS/HangulSpacing"
    if args.platform == "macos" and app.exists():
        subprocess.run([str(app), "--verify-update", str(out), args.keys], check=True)
    print(f"서명함: {out} ({info['product']} {info['label']} build {info['build']}, 설명 {len(info['notes'])}줄)")

    # 4. 올리기와 공개 주소 대조.
    put = shlex.split(args.wrangler) + ["r2", "object", "put", BUCKET_PREFIX + "update/" + name, "--file", str(out),
                                        "--content-type", "application/json", "--cache-control", "max-age=300",
                                        "--remote"]
    if not args.publish:
        print("올리지 않음(--publish 없음). 올릴 명령:\n  " + shlex.join(put))
        return 0
    subprocess.run(put, check=True)
    published = fetch(manifest_url + "?v=" + local[1][:8], um.MAX_MANIFEST)
    if published != out.read_bytes():
        print("경고: 공개 주소의 업데이트 정보가 방금 올린 것과 다르다(캐시일 수 있다). 몇 분 뒤 다시 확인한다.",
              file=sys.stderr)
        return 1
    um.verify_manifest(published, keys, args.platform)
    print(f"올림: {manifest_url} — 설치된 앱이 다음 확인 때(하루 안) 알린다.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
