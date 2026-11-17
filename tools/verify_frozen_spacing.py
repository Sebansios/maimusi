"""Compare the frozen helper with source on public/authored acceptance fixtures."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys
from copy import deepcopy

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "engine"))
from hangul_ime.ime_service import Service


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--helper", type=Path, default=ROOT / (
        "build/macos.noindex/HangulSpacing.app/Contents/Helpers/"
        "HangulEngine.app/Contents/MacOS/HangulEngine"))
    parser.add_argument("--output", type=Path)
    parser.add_argument("--require-refiner", action="store_true")
    args = parser.parse_args()
    service = Service()
    source_refiner_started = deepcopy(service.spacer.refiner_info)
    requests, expected, sources = [], [], []

    def enqueue(request):
        request = dict(request, id=len(requests) + 1)
        requests.append(request)
        try:
            response = dict(service.handle(request), ok=True, id=request["id"])
        except Exception as exc:
            response = dict(ok=False, id=request["id"], error=type(exc).__name__)
        expected.append(response)

    for name in ("spacing_cases.json", "informal_development.json",
                 "informal_holdout.json", "informal_holdout_round2.json",
                 "compound_cases.json"):
        path = ROOT / "engine/tests" / name
        raw = path.read_bytes()
        rows = json.loads(raw)
        sources.append(dict(name=name, sha256=hashlib.sha256(raw).hexdigest(), count=len(rows)))
        enqueue(dict(op="configure", spacing={"compound": "join"} if name == "compound_cases.json" else {}))
        for row in rows:
            enqueue(dict(op="space", text=row["source"]))
    # Exercise the explicit compound style and the learned default separately:
    # an explicit compound preference intentionally uses the legacy path.
    enqueue(dict(op="space", text="학교 도서관 열람 시간 안내 " * 200))
    enqueue(dict(op="configure", spacing={}))
    enqueue(dict(op="space", text="오늘학교에가서책을읽었다.친구와이야기도나누었다." * 120))
    enqueue(dict(op="space", text="가" * 4097))
    enqueue(dict(op="configure", symbol_consonants=False))
    for word in ("/", "[", "]", "'", '"', "괄호", "[책 이름]", "알파", "오메가", "전각", "선문자", "ㅁ"):
        enqueue(dict(op="candidates", word=word))
    for word in ("특수문자", "겹화살괄호", "대문자알파"):
        enqueue(dict(op="space", text=word))
    enqueue(dict(op="configure", symbol_consonants=True))
    for word in ("ㅁ", "ㄷ", "ㅎ"):
        enqueue(dict(op="candidates", word=word))
    enqueue(dict(op="configure", symbol_consonants=False))
    enqueue(dict(op="ping"))
    run = subprocess.run([str(args.helper)], input="".join(
        json.dumps(r, ensure_ascii=False) + "\n" for r in requests),
        # The helper's protocol is UTF-8 whatever the locale; stderr is not used.
        encoding="utf-8", errors="replace", capture_output=True, timeout=90)
    replies = [json.loads(line) for line in run.stdout.splitlines() if line.strip()]
    ready = bool(replies and replies[0].get("op") == "ready" and replies[0].get("ok"))
    actual = replies[1:] if ready else replies
    mismatches = [i + 1 for i, (want, got) in enumerate(zip(expected, actual)) if want != got]
    source_refiner_finished = service.spacer.refiner_info
    frozen_refiner = replies[0].get("refiner") if ready else None
    frozen_refiner_finished = actual[-1].get("refiner") if actual else None
    refiner_matched = (source_refiner_started == source_refiner_finished == frozen_refiner
                       == frozen_refiner_finished
                       and source_refiner_finished.get("status") != "error")
    if args.require_refiner:
        refiner_matched = refiner_matched and source_refiner_finished.get("loaded") is True
    matched = (ready and run.returncode == 0 and len(actual) == len(expected)
               and not mismatches and refiner_matched)
    report = dict(passed=matched, ready=ready, returncode=run.returncode,
                  requests=len(expected), replies=len(actual), mismatch_ids=mismatches,
                  refiner_required=args.require_refiner, refiner_identity_matched=refiner_matched,
                  source_refiner_started=source_refiner_started,
                  source_refiner_finished=source_refiner_finished, frozen_refiner=frozen_refiner,
                  frozen_refiner_finished=frozen_refiner_finished,
                  helper_sha256=hashlib.sha256(args.helper.read_bytes()).hexdigest(),
                  fixture_sources=sources,
                  note="Source/frozen parity, not an accuracy estimate or installed-IME UI test.")
    output = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(output, encoding="utf-8")
    print(output, end="")
    return 0 if matched else 1


if __name__ == "__main__":
    raise SystemExit(main())
