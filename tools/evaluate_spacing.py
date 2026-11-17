"""Synthetic, reviewed acceptance fixtures; no user input collection.

Run with PYTHONPATH=engine and the engine Python. Output JSON to stdout.
"""
import json
from pathlib import Path
import statistics
import time
from hangul_ime.release_spacing import KiwiSpacer


def boundaries(text):
    offset, result = 0, set()
    for char in text:
        if char == " ":
            result.add(offset)
        else:
            offset += 1
    return result


def main():
    cases = json.loads((Path(__file__).resolve().parents[1] /
                       "engine/tests/spacing_cases.json").read_text(encoding="utf-8"))
    start = time.perf_counter()
    spacer = KiwiSpacer()
    report = {"startup_ms": (time.perf_counter() - start) * 1000,
              "groups": {}, "failures": []}
    for case in cases:
        source, accepted = case["source"], case["accepted"]
        result = spacer.space(source)
        timings = []
        for _ in range(20):
            start = time.perf_counter()
            spacer.space(source)
            timings.append((time.perf_counter() - start) * 1000)
        predicted = boundaries(result)
        gold = max((boundaries(a) for a in accepted),
                   key=lambda b: 2 * len(b & predicted) / max(1, len(b) + len(predicted)))
        group = report["groups"].setdefault(case["category"],
                  {"count": 0, "exact": 0, "tp": 0, "fp": 0, "fn": 0, "times": []})
        group["count"] += 1
        group["exact"] += result in accepted
        group["tp"] += len(predicted & gold)
        group["fp"] += len(predicted - gold)
        group["fn"] += len(gold - predicted)
        group["times"].extend(timings)
        if result not in accepted:
            report["failures"].append(dict(case, actual=result))
    for group in report["groups"].values():
        samples = sorted(group.pop("times"))
        group["p50_ms"] = statistics.median(samples)
        group["p95_ms"] = samples[int(len(samples) * .95)]
        group["boundary_f1"] = 2 * group["tp"] / max(1, 2 * group["tp"] + group["fp"] + group["fn"])
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
