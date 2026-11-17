"""Fetch the pinned public spacing evaluation corpora, or verify them offline.

    python tools/fetch_spacing_corpora.py
    python tools/fetch_spacing_corpora.py --check
    python tools/fetch_spacing_corpora.py --output /path/to/evaluation-corpora

Only GSD test/dev, Kaist test, README and license files are downloaded from fixed
Git commits. The SHA-256 manifest below is independent of cached provenance.
Both existing cache entries and new downloads must match it. Existing invalid
files or provenance are reported rather than overwritten. --check performs no
network requests or writes and also requires the provenance file to be present.

curl provides normal certificate-verified HTTPS here because the development
Mac's Python urllib certificate store cannot validate these downloads. Neither
certificate verification nor HTTPS redirect restrictions are disabled. No large
repository clone, training split or model download is involved.

Each dataset directory's provenance.json records the repository, exact commit,
test filename/hash, all three file hashes, license, genre and sentence count.
GSD dev has a separate dev-provenance.json in the same GSD directory; its role
records the original experiment's split usage, not the timing of a later fetch.
These descriptions follow the pinned source README; retain README/LICENSE when
sharing or reusing the corpus and observe their CC BY-SA 4.0 conditions.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile


CORPORA = {
    "gsd": {
        "repository": "https://github.com/UniversalDependencies/UD_Korean-GSD",
        "commit": "7628157f2ba54e0580b2c03e22f1a9f5b111d7e7",
        "file": "ko_gsd-ud-test.conllu",
        "license": "CC BY-SA 4.0",
        "genre": "news blog",
        "sentences": 989,
        "source_sha256": "3d1df99bda4800235e14bcfd915baf706eafa1a3935a75ffd32420a51e57f5aa",
        "files_sha256": {
            "ko_gsd-ud-test.conllu": "3d1df99bda4800235e14bcfd915baf706eafa1a3935a75ffd32420a51e57f5aa",
            "README.md": "6d68b7128f8851fd343b81ea049a743b0351c918022fac9bd7ed302464f98007",
            "LICENSE.txt": "899b1804a12ebc090b96339614eede1b64b686721b650a71430b55b5235f7f79",
        },
    },
    "kaist": {
        "repository": "https://github.com/UniversalDependencies/UD_Korean-Kaist",
        "commit": "5e2cfb9a30a71e2091b6905f8f79bc2e6d4b6b28",
        "file": "ko_kaist-ud-test.conllu",
        "license": "CC BY-SA 4.0",
        "genre": "news fiction academic",
        "sentences": 2287,
        "source_sha256": "fd94dc89afb01d1f7f340a46d567e0f27ae6903a70d7b6f650b49f7427f83b97",
        "files_sha256": {
            "README.md": "1219e86b630204112ced11c61a7922634d4f03372dce3cfb3488e8187f6ac2fb",
            "LICENSE.txt": "899b1804a12ebc090b96339614eede1b64b686721b650a71430b55b5235f7f79",
            "ko_kaist-ud-test.conllu": "fd94dc89afb01d1f7f340a46d567e0f27ae6903a70d7b6f650b49f7427f83b97",
        },
    },
    "gsd-dev": {
        "repository": "https://github.com/UniversalDependencies/UD_Korean-GSD",
        "commit": "7628157f2ba54e0580b2c03e22f1a9f5b111d7e7",
        "file": "ko_gsd-ud-dev.conllu",
        "license": "CC BY-SA 4.0",
        "genre": "news blog",
        "sentences": 950,
        "source_sha256": "8f7c4e24bbf6db2b0df8007068eb2d56d5ad8a5539360589d0f15a8c17034566",
        "role": "untouched round 2 independent evaluation; acquired before candidate measurement",
    },
}


def verify_file(path, expected):
    actual = hashlib.sha256(path.read_bytes()).hexdigest()
    if actual != expected:
        raise ValueError(f"SHA-256 mismatch: {path.name}; expected {expected}, found {actual}")


def download_file(url, target, expected):
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=target.parent, prefix=f".{target.name}.",
                                         suffix=".download", delete=False) as handle:
            temporary = Path(handle.name)
        subprocess.run([
            "curl", "--fail", "--location", "--silent", "--show-error",
            "--proto", "=https", "--proto-redir", "=https", "--tlsv1.2",
            "--retry", "2", "--connect-timeout", "20", "--max-time", "120",
            "--output", str(temporary), "--url", url,
        ], check=True)
        verify_file(temporary, expected)
        # If another process filled this cache while curl ran, preserve it and
        # require the same hash instead of replacing any pre-existing content.
        if target.exists():
            verify_file(target, expected)
        else:
            os.replace(temporary, target)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def prepare_corpus(name, output, check):
    metadata = CORPORA[name]
    family = "gsd" if name == "gsd-dev" else name
    directory = output / f"ud-korean-{family}-{metadata['commit'][:7]}"
    provenance = directory / ("dev-provenance.json" if name == "gsd-dev" else "provenance.json")
    hashes = metadata.get("files_sha256") or {
        **{filename: CORPORA[family]["files_sha256"][filename] for filename in ("README.md", "LICENSE.txt")},
        metadata["file"]: metadata["source_sha256"],
    }
    if provenance.exists():
        if json.loads(provenance.read_text(encoding="utf-8")) != metadata:
            raise ValueError(f"Provenance differs from the pinned manifest: {directory.name}")
    elif check:
        raise FileNotFoundError(f"Missing provenance: {directory.name}/{provenance.name}")
    if not check:
        directory.mkdir(parents=True, exist_ok=True)
    downloaded = []
    for filename, expected in hashes.items():
        path = directory / filename
        if path.exists():
            verify_file(path, expected)
        elif check:
            raise FileNotFoundError(f"Missing corpus file: {directory.name}/{filename}")
        else:
            repository = metadata["repository"].removeprefix("https://github.com/")
            url = f"https://raw.githubusercontent.com/{repository}/{metadata['commit']}/{filename}"
            download_file(url, path, expected)
            downloaded.append(filename)
    if not check and not provenance.exists():
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=directory,
                                             prefix=".provenance.", suffix=".json", delete=False) as handle:
                temporary = Path(handle.name)
                json.dump(metadata, handle, ensure_ascii=False, indent=2)
                handle.write("\n")
            os.replace(temporary, provenance)
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
    # Read the public metadata back as well as checking every data file above.
    if json.loads(provenance.read_text(encoding="utf-8")) != metadata:
        raise ValueError(f"Provenance readback failed: {directory.name}")
    return {"name": name, "directory": directory.name, "commit": metadata["commit"],
            "verified_files": len(hashes),
            "source_sha256": metadata["source_sha256"], "downloaded": downloaded}


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--output", type=Path,
                        default=Path(__file__).resolve().parents[1] / "build" / "evaluation-corpora")
    parser.add_argument("--check", action="store_true", help="verify existing data and metadata; no writes or network")
    parser.add_argument("--corpus", choices=tuple(CORPORA), action="append", help="default: gsd, kaist and gsd-dev")
    args = parser.parse_args()
    try:
        results = [prepare_corpus(name, args.output, args.check)
                   for name in dict.fromkeys(args.corpus or CORPORA)]
    except (OSError, ValueError, subprocess.CalledProcessError) as exc:
        parser.exit(1, f"Corpus verification failed: {exc}\n")
    print(json.dumps({"mode": "offline-check" if args.check else "fetch-or-check", "corpora": results}, indent=2))


if __name__ == "__main__":
    main()
