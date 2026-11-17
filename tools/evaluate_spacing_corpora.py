"""Aggregate-only local evaluation; never stores corpus source sentences."""
import argparse
import json
from pathlib import Path
import statistics
import time
from hangul_ime.release_spacing import KiwiSpacer
from evaluate_spacing import boundaries


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("data_root", type=Path,
                        help="Reference core directory with data_nikl and data_web")
    root = parser.parse_args().data_root
    spacer, report = KiwiSpacer(), {}
    for name in ("dialect", "dialogue", "dialogue22", "messenger", "web"):
        relative = "data_web/test.txt" if name == "web" else f"data_nikl/{name}.test.txt"
        lines = [line.strip() for line in (root / relative).read_text(encoding="utf-8").splitlines()
                 if line.strip()][:500]
        tp = fp = fn = exact = changes = 0
        times = []
        for gold in lines:
            source = gold.replace(" ", "")
            start = time.perf_counter()
            result = spacer.space(source)
            times.append((time.perf_counter() - start) * 1000)
            expected, predicted = boundaries(gold), boundaries(result)
            tp += len(expected & predicted)
            fp += len(predicted - expected)
            fn += len(expected - predicted)
            exact += result == gold
            changes += result.replace(" ", "") != source
        report[name] = dict(count=len(lines), exact=exact,
                            f1=2 * tp / max(1, 2 * tp + fp + fn),
                            p50_ms=statistics.median(times),
                            p95_ms=sorted(times)[int(len(times) * .95)],
                            character_changes=changes)
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
