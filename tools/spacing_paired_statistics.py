"""Paired, text-free spacing statistics from a complete comparison report.

Requires compare_spacing.py --detail all and a valid, stable runtime. No engine
or corpus text is loaded. Per-corpus/mode/preference bootstrap draws are paired;
micro F1 is recomputed from summed TP/FP/FN, never averaged across sentences.

--document-map NAME=JSON optionally supplies source-bound document clusters:
{"source_sha256": "<report source SHA>", "rows": [
  {"document_sha256": "<opaque document SHA>", "compact_sha256": "<optional SHA>"}
]}
Rows must cover the complete source in its original order. Source SHA and row
count are checked; supplied compact hashes are also checked against restore
inputs. Without a map, the unit is explicitly a sentence. Output contains only
aggregate metrics, configured corpus labels, source/model hashes and methods.
"""
import argparse
from collections import defaultdict
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import re
import sys

import numpy as np

HEX = re.compile(r"[0-9a-f]{64}\Z")
GROUP_KEYS = ("corpus", "mode", "preference")


class ReportValidationError(ValueError):
    """A fixed, input-free diagnostic suitable for command-line output."""


def digest(value):
    return hashlib.sha256(value).hexdigest()


def require(condition, message):
    if not condition:
        raise ReportValidationError(message)


def integer(value):
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def source_row(row, selected):
    prefix = row["corpus"] + ":"
    suffix = ":" + row["mode"] + ":" + row["preference"]
    identifier = row.get("id", "")
    require(isinstance(identifier, str) and identifier.startswith(prefix) and identifier.endswith(suffix),
            "row identifier does not match its group")
    number = identifier[len(prefix):-len(suffix)]
    require(number.isascii() and number.isdigit() and 1 <= int(number) <= selected,
            "row identifier is outside the selected source")
    return int(number) - 1


def validate_report(report):
    require(report.get("schema_version") == 2, "unsupported comparison report schema")
    runtime = report.get("runtime", {})
    require(runtime.get("valid") is True and runtime.get("violations") == [],
            "a report with verified valid runtime is required")
    for side in ("baseline", "candidate"):
        metadata = report.get(side, {})
        require(metadata.get("engine_source_stable") is True, "engine sources were unstable")
        start, finish = metadata.get("refiner_started"), metadata.get("refiner_finished")
        require(start == finish, "refiner state changed during evaluation")
        require(not isinstance(start, dict) or not (start.get("error") or start.get("status") == "error"),
                "refiner runtime reported an error")
    rows, detail = report.get("sentences"), report.get("detail", {})
    require(isinstance(rows, list) and bool(rows), "a nonempty comparison report is required")
    require(detail.get("mode") == "all" and detail.get("omitted") == 0
            and detail.get("included") == detail.get("evaluated") == len(rows),
            "complete --detail all rows are required")
    sources = {}
    for source in report.get("sources", []):
        name = source.get("name")
        require(isinstance(name, str) and name not in sources, "invalid or duplicated source label")
        require(isinstance(source.get("sha256"), str) and HEX.fullmatch(source["sha256"]),
                "invalid source fingerprint")
        require(integer(source.get("available")) and integer(source.get("selected"))
                and 0 < source["selected"] <= source["available"], "invalid source row counts")
        sources[name] = source
    groups, seen = defaultdict(list), set()
    for row in rows:
        require(all(isinstance(row.get(k), str) for k in GROUP_KEYS), "invalid row group")
        key = tuple(row[k] for k in GROUP_KEYS)
        require(key[0] in sources, "row refers to an unknown source")
        index = source_row(row, sources[key[0]]["selected"])
        require((key, index) not in seen, "duplicate sentence in a comparison group")
        seen.add((key, index))
        for side in ("baseline", "candidate"):
            measurement = row.get(side, {})
            require("error" not in measurement and measurement.get("characters_altered") is False,
                    "error or character-changing rows cannot be silently excluded")
            require(isinstance(measurement.get("exact"), bool), "invalid exact-match measurement")
            require(all(integer(measurement.get(k)) for k in ("tp", "fp", "fn", "boundary_distance")),
                    "invalid boundary counts")
            require(measurement["boundary_distance"] == measurement["fp"] + measurement["fn"],
                    "inconsistent boundary distance")
        groups[key].append((index, row))
    expected = {}
    for group in report.get("groups", []):
        key = tuple(group.get(k) for k in GROUP_KEYS)
        require(key not in expected, "duplicate aggregate group")
        expected[key] = group
    require(set(groups) == set(expected), "sentence and aggregate groups differ")
    for key, items in groups.items():
        items.sort(key=lambda item: item[0])
        for side in ("baseline", "candidate"):
            aggregate = expected[key].get(side, {})
            require(aggregate.get("count") == len(items) and aggregate.get("errors") == 0
                    and aggregate.get("characters_altered") == 0, "aggregate row counts are inconsistent")
            require(all(aggregate.get(k) == sum(row[side][k] for _, row in items)
                        for k in ("exact", "tp", "fp", "fn", "boundary_distance")),
                    "aggregate metrics do not match sentence rows")
    return sources, groups


def validate_document_maps(document_maps, sources, groups):
    checked_rows = {}
    for name, mapping in document_maps.items():
        require(name in sources, "document map refers to an unknown source")
        source = sources[name]
        require(mapping.get("source_sha256") == source["sha256"], "document map source hash mismatch")
        rows = mapping.get("rows")
        require(isinstance(rows, list) and len(rows) == source["available"],
                "document map must cover every original source row")
        for row in rows:
            require(isinstance(row, dict) and isinstance(row.get("document_sha256"), str)
                    and HEX.fullmatch(row["document_sha256"]), "invalid opaque document hash")
            if "compact_sha256" in row:
                require(isinstance(row["compact_sha256"], str) and HEX.fullmatch(row["compact_sha256"]),
                        "invalid compact-text fingerprint")
        checked = set()
        for key, items in groups.items():
            if key[0] == name and key[1] == "restore":
                for index, result in items:
                    if "compact_sha256" in rows[index]:
                        require(rows[index]["compact_sha256"] == result.get("input_sha256"),
                                "document map row order or compact hash mismatch")
                        checked.add(index)
        checked_rows[name] = len(checked)
    return checked_rows


def micro_f1(tp, fp, fn):
    denominator = 2 * tp + fp + fn
    return np.divide(2 * tp, denominator, out=np.ones_like(denominator, dtype=float), where=denominator != 0)


def rates(totals):
    """Columns: exact baseline/candidate/delta, micro-F1 baseline/candidate/delta."""
    baseline_exact, candidate_exact = totals[..., 1] / totals[..., 0], totals[..., 2] / totals[..., 0]
    baseline_f1 = micro_f1(totals[..., 3], totals[..., 4], totals[..., 5])
    candidate_f1 = micro_f1(totals[..., 6], totals[..., 7], totals[..., 8])
    return np.stack((baseline_exact, candidate_exact, candidate_exact - baseline_exact,
                     baseline_f1, candidate_f1, candidate_f1 - baseline_f1), axis=-1)


def bootstrap(cluster_totals, samples, confidence, seed):
    if len(cluster_totals) < 2:
        return None
    rng = np.random.default_rng(seed)
    values = np.empty((samples, 6), dtype=float)
    # Bound temporary sampled contributions independently of corpus size.
    batch = max(1, min(64, 500_000 // len(cluster_totals)))
    for start in range(0, samples, batch):
        stop = min(samples, start + batch)
        selected = rng.integers(0, len(cluster_totals), size=(stop - start, len(cluster_totals)))
        totals = cluster_totals[selected].sum(axis=1)
        values[start:stop] = rates(totals)
    alpha = (1 - confidence) / 2
    return np.quantile(values, [alpha, 1 - alpha], axis=0, method="linear")


def engine_identity(metadata):
    identity = {k: metadata[k] for k in ("engine_sha256", "engine_fingerprint_version") if k in metadata}
    state = metadata.get("refiner_started")
    if isinstance(state, dict):
        identity["refiner"] = {k: state[k] for k in ("loaded", "status", "model_sha256", "confidence_threshold",
                                                    "removal_threshold")
                               if k in state}
    return identity


def summarize(report, *, document_maps=None, samples=5000, confidence=.95, seed=20261002):
    require(integer(samples) and samples >= 100, "at least 100 bootstrap samples are required")
    require(isinstance(confidence, (int, float)) and not isinstance(confidence, bool)
            and math.isfinite(confidence) and 0 < confidence < 1, "confidence must lie strictly between 0 and 1")
    require(integer(seed), "seed must be a nonnegative integer")
    sources, groups = validate_report(report)
    document_maps = document_maps or {}
    checked_rows = validate_document_maps(document_maps, sources, groups)
    results = []
    for key, items in sorted(groups.items()):
        mapping = document_maps.get(key[0])
        units = ([mapping["rows"][index]["document_sha256"] for index, _ in items] if mapping else
                 [str(index) for index, _ in items])
        labels, inverse = np.unique(units, return_inverse=True)
        contributions = np.array([
            [1, row["baseline"]["exact"], row["candidate"]["exact"],
             *(row[side][metric] for side in ("baseline", "candidate") for metric in ("tp", "fp", "fn"))]
            for _, row in items], dtype=np.int64)
        cluster_totals = np.zeros((len(labels), 9), dtype=np.int64)
        np.add.at(cluster_totals, inverse, contributions)
        totals = cluster_totals.sum(axis=0)
        observed = rates(totals)
        group_seed = int.from_bytes(hashlib.sha256(json.dumps([seed, *key], ensure_ascii=False).encode()).digest()[:4], "big")
        intervals = bootstrap(cluster_totals, samples, confidence, group_seed)
        estimates = {}
        for metric, offset in (("exact_rate", 0), ("boundary_f1", 3)):
            estimates[metric] = {
                side: {"value": float(observed[offset + i]),
                       "ci": intervals[:, offset + i].tolist() if intervals is not None else None}
                for i, side in enumerate(("baseline", "candidate", "delta"))}
        before, after = contributions[:, 1].astype(bool), contributions[:, 2].astype(bool)
        baseline_distance = contributions[:, 4] + contributions[:, 5]
        candidate_distance = contributions[:, 7] + contributions[:, 8]
        sizes = cluster_totals[:, 0]
        results.append({**dict(zip(GROUP_KEYS, key)), "sentences": len(items),
                        "resampling": {"unit": "document" if mapping else "sentence", "units": len(labels),
                                       "minimum_unit_sentences": int(sizes.min()), "maximum_unit_sentences": int(sizes.max()),
                                       "seed": group_seed, "confidence_interval_available": intervals is not None,
                                       "limitation": ("Document clusters can share speakers or source conditions; this is not a speaker-independent interval."
                                                      if mapping else "Sentence resampling assumes independent sentences; within-document dependence is not modeled.")},
                        "exact_pairs": {"both_correct": int(np.sum(before & after)),
                                        "both_incorrect": int(np.sum(~before & ~after)),
                                        "improved": int(np.sum(~before & after)),
                                        "regressed": int(np.sum(before & ~after)),
                                        "discordant": int(np.sum(before != after))},
                        "boundary_distance_pairs": {"improved": int(np.sum(candidate_distance < baseline_distance)),
                                                    "regressed": int(np.sum(candidate_distance > baseline_distance)),
                                                    "tied": int(np.sum(candidate_distance == baseline_distance))},
                        "boundary_counts": {side: dict(zip(("tp", "fp", "fn"), map(int, totals[offset:offset + 3])))
                                            for side, offset in (("baseline", 3), ("candidate", 6))},
                        **estimates})
    return {"schema_version": 1, "created_at": datetime.now(timezone.utc).isoformat(),
            "method": {"bootstrap": "paired nonparametric percentile", "samples": samples, "confidence": confidence,
                       "seed": seed, "random_generator": "NumPy PCG64", "numpy_version": np.__version__,
                       "grouping": list(GROUP_KEYS), "delta": "candidate minus baseline; rates on a 0-to-1 scale",
                       "f1": "micro F1 recomputed from summed TP/FP/FN in each paired draw; no-boundary denominator yields 1",
                       "exact": "correct sentences divided by sampled sentence count, including variable cluster sizes",
                       "pairing": "the same sampled units are used for baseline and candidate",
                       "intervals": "pointwise per group and metric; not adjusted for multiple comparisons",
                       "limits": "Intervals condition on these models and this evaluation sample. They do not adjust for model selection on the evaluated sample or establish corpus quality, absence of upstream training overlap, or population-wide improvement.",
                       "insufficient_clusters": "Fewer than two resampling units yields null confidence intervals."},
            "baseline": engine_identity(report["baseline"]), "candidate": engine_identity(report["candidate"]),
            "sources": [{k: source[k] for k in ("name", "sha256", "available", "selected")} for source in sources.values()],
            "document_maps": [{"corpus": name, "source_sha256": mapping["source_sha256"], "rows": len(mapping["rows"]),
                               "restore_compact_hashes_checked": checked_rows[name],
                               "alignment": "source SHA and original row ordinal; compact hashes checked where restore inputs are available"}
                              for name, mapping in sorted(document_maps.items())],
            "corpus_files_read": False, "model_inference_performed": False,
            "sentence_rows_or_document_ids_emitted": False, "groups": results}


def named_path(value):
    name, separator, filename = value.partition("=")
    if not separator or not name or not filename:
        raise argparse.ArgumentTypeError("expected NAME=PATH")
    return name, Path(filename)


def markdown(report):
    def percent(value):
        return f"{value * 100:.3f}"

    def delta_interval(metric):
        interval = metric["delta"]["ci"]
        bounds = f"[{percent(interval[0])}, {percent(interval[1])}]" if interval is not None else "unavailable"
        return f"{percent(metric['delta']['value'])} {bounds}"

    def safe(value):
        return value.replace("|", "\\|").replace("\n", " ").replace("\r", " ")

    lines = ["# Paired spacing statistics", "", "All scores are percentages; deltas and confidence intervals are percentage points.",
             f"Paired percentile bootstrap: {report['method']['samples']:,} draws; {report['method']['confidence'] * 100:g}% pointwise intervals.", "",
             "| Corpus | Mode | Preference | Sentences | Resampling | Exact improved / regressed | Exact delta [CI] | Boundary F1 baseline / candidate | F1 delta [CI] |",
             "|---|---|---|---:|---|---:|---:|---:|---:|"]
    for group in report["groups"]:
        unit = group["resampling"]
        lines.append("| " + " | ".join([
            *(safe(group[k]) for k in GROUP_KEYS), str(group["sentences"]), f"{unit['units']} {unit['unit']} units",
            f"{group['exact_pairs']['improved']} / {group['exact_pairs']['regressed']}", delta_interval(group["exact_rate"]),
            f"{percent(group['boundary_f1']['baseline']['value'])} / {percent(group['boundary_f1']['candidate']['value'])}",
            delta_interval(group["boundary_f1"])]) + " |")
    lines += ["", "Sentence intervals do not model within-document dependence. Document intervals may still share speakers and are not speaker-independent.",
              "Intervals are conditional on this sample and are not corrected for multiple comparisons. Fewer than two units yields no interval.",
              "No corpus text, sentence rows, or document identifiers are included.", ""]
    if "comparison_report_sha256" in report:
        lines += [f"Comparison report SHA-256: `{report['comparison_report_sha256']}`", ""]
    return "\n".join(lines)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("report", type=Path)
    parser.add_argument("--document-map", action="append", type=named_path, default=[])
    parser.add_argument("--samples", type=int, default=5000)
    parser.add_argument("--confidence", type=float, default=.95)
    parser.add_argument("--seed", type=int, default=20261002)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--markdown", type=Path)
    args = parser.parse_args(argv)
    raw = args.report.read_bytes()
    maps, map_hashes = {}, {}
    for name, path in args.document_map:
        require(name not in maps, "duplicate document map label")
        contents = path.read_bytes()
        maps[name], map_hashes[name] = json.loads(contents), digest(contents)
    report = summarize(json.loads(raw), document_maps=maps, samples=args.samples, confidence=args.confidence, seed=args.seed)
    report.update(comparison_report_sha256=digest(raw), statistics_tool_sha256=digest(Path(__file__).read_bytes()))
    for mapping in report["document_maps"]:
        mapping["sha256"] = map_hashes[mapping["corpus"]]
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if args.markdown:
        args.markdown.parent.mkdir(parents=True, exist_ok=True)
        args.markdown.write_text(markdown(report), encoding="utf-8")
    print(json.dumps({"groups": len(report["groups"]), "comparison_report_sha256": report["comparison_report_sha256"],
                      "corpus_files_read": False, "bootstrap_samples": args.samples}))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except ReportValidationError as exc:
        print(f"Statistics failed: {exc}.", file=sys.stderr)
        raise SystemExit(2)
    except Exception as exc:
        print(f"Statistics failed ({type(exc).__name__}); input-bearing details suppressed.", file=sys.stderr)
        raise SystemExit(2)
