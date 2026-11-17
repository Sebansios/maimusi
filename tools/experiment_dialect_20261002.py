"""Bounded, aggregate-only probes; does not enable Kiwi's large dialect model.

Input corpora stay local and no source sentences are included in the JSON.
The production spacer is loaded from a pinned Git revision so concurrent
working-tree edits cannot silently change the baseline implementation.
"""
import argparse
import hashlib
import json
import resource
import statistics
import subprocess
import sys
import time
import types
from pathlib import Path


AUTHORED = [
    "고마워용 잘 쓸게용", "오늘 뭐 하세용", "이거 어떻게 하는 거예용",
    "정말 좋아욤", "오늘 밥 먹었어유", "여기 진짜 맛있네유",
    "그게 아니랑께", "나도 모르것다", "너 어디 가는겨", "집에 왔슈",
    "내 말 맞쥬", "오늘은 먼저 갈게여", "의약품의 복용 방법을 설명했다",
    "용을 그렸다", "사용 목적을 적으세요", "세종대왕은 한글을 창제했다",
]


def boundaries(text):
    result, position = set(), 0
    for char in text:
        if char == " ":
            result.add(position)
        else:
            position += 1
    return result


def evaluate(spacer, lines):
    tp = fp = fn = exact = changed = 0
    elapsed, outputs = [], []
    for gold in lines:
        source = gold.replace(" ", "")
        before = time.perf_counter()
        result = spacer.space(source)
        elapsed.append((time.perf_counter() - before) * 1000)
        expected, predicted = boundaries(gold), boundaries(result)
        tp += len(expected & predicted)
        fp += len(predicted - expected)
        fn += len(expected - predicted)
        exact += result == gold
        changed += result.replace(" ", "") != source
        outputs.append(result)
    return dict(count=len(lines), exact=exact, tp=tp, fp=fp, fn=fn,
                f1=2 * tp / max(1, 2 * tp + fp + fn),
                p50_ms=statistics.median(elapsed),
                p95_ms=sorted(elapsed)[int(len(elapsed) * .95)],
                character_changes=changed), outputs


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--git-ref", default="HEAD")
    parser.add_argument("--baseline-engine", type=Path,
                        help="Frozen initial working-tree engine directory; preferred over Git HEAD")
    parser.add_argument("--endings", choices=("internet", "all"), default="all")
    parser.add_argument("--gsd", type=Path, required=True)
    parser.add_argument("--local-core", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    commit = subprocess.check_output(["git", "rev-parse", args.git_ref], text=True).strip()
    if args.baseline_engine:
        sys.path.insert(0, str(args.baseline_engine.resolve()))
        source = (args.baseline_engine / "hangul_ime/release_spacing.py").read_text(encoding="utf-8")
        baseline_identity = "frozen initial working tree"
    else:
        source = subprocess.check_output([
            "git", "show", f"{commit}:engine/hangul_ime/release_spacing.py"], text=True)
        baseline_identity = commit
    module = types.ModuleType("hangul_ime._experimental_baseline")
    exec(compile(source, f"{commit}:release_spacing.py", "exec"), module.__dict__)
    gsd_bytes = args.gsd.read_bytes()
    corpora = {"ud_gsd_test": [line[len("# text = "):]
                               for line in gsd_bytes.decode().splitlines()
                               if line.startswith("# text = ")], "authored": AUTHORED}
    if args.local_core:
        for name in ("dialect", "dialogue", "dialogue22", "messenger"):
            path = args.local_core / "data_nikl" / f"{name}.test.txt"
            corpora[name] = [line.strip() for line in path.read_text(encoding="utf-8").splitlines()
                             if line.strip()][:500]
    spacer = module.KiwiSpacer()
    baseline, original = {}, {}
    for name, lines in corpora.items():
        baseline[name], original[name] = evaluate(spacer, lines)
    # POS-aware alternatives inherit the existing ending's language model
    # identity and retain a negative prior. These are experiments, not defaults.
    registrations = {}
    endings = [("용", -2), ("욤", -2)]
    if args.endings == "all":
        endings.append(("유", -3))
    for suffix, score in endings:
        registrations[suffix] = len(spacer.kiwi.add_re_rule("EF", "요$", suffix, score))
    spacer.kiwi.tokenize("한글 입력 준비")
    candidate = {}
    for name, lines in corpora.items():
        metrics, outputs = evaluate(spacer, lines)
        metrics["changed_outputs"] = sum(a != b for a, b in zip(original[name], outputs))
        metrics["exact_gains"] = sum(a != gold and b == gold
                                     for a, b, gold in zip(original[name], outputs, lines))
        metrics["exact_losses"] = sum(a == gold and b != gold
                                      for a, b, gold in zip(original[name], outputs, lines))
        metrics["boundary_improved"] = sum(
            len(boundaries(b) ^ boundaries(gold)) < len(boundaries(a) ^ boundaries(gold))
            for a, b, gold in zip(original[name], outputs, lines))
        metrics["boundary_worsened"] = sum(
            len(boundaries(b) ^ boundaries(gold)) > len(boundaries(a) ^ boundaries(gold))
            for a, b, gold in zip(original[name], outputs, lines))
        candidate[name] = metrics
    import kiwipiepy
    report = dict(kiwipiepy=kiwipiepy.__version__, baseline=baseline_identity,
                  baseline_module_sha256=hashlib.sha256(source.encode()).hexdigest(),
                  gsd_sha256=hashlib.sha256(gsd_bytes).hexdigest(),
                  source="UD Korean-GSD 7628157f2ba54e0580b2c03e22f1a9f5b111d7e7",
                  registrations=registrations, baseline_metrics=baseline, ending_variants=candidate,
                  max_rss_platform_units=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
