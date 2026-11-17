r"""Paired spacing evaluation in isolated, sequential engine processes.

Example (run with the Python containing kiwipiepy)::

    python tools/compare_spacing.py --baseline-engine old/engine \
        --candidate-engine engine --corpus gsd=ko_gsd-ud-test.conllu \
        --fixtures authored=engine/tests/spacing_cases.json \
        --preferences 'join={"compound":"join"}' --output comparison.json \
        --require-no-regression --gate-corpus gsd

Text corpora contain one correctly spaced sentence per line. CoNLL-U uses its
original ``# text =`` fields, not a reconstruction of morphological tokens.
Corpus modes default to both restore (remove ASCII spaces) and preserve (feed
the reference unchanged); --mode selects either. Fixtures are JSON lists with
source/accepted and optional preferences/modes/category fields. Their default
mode is source; optional modes are source/restore/preserve. Accepted variants
must have identical non-space characters. --preferences NAME=JSON is repeatable
and defaults to default={}; a fixture's preferences override that setting.

Reports contain only generated IDs, hashes and metrics unless the caller
explicitly requests --include-fixture-text for authored fixtures. Corpus texts,
native sentence IDs, paths and exception messages are never emitted. A gate
checks individual sentences: improvements cannot offset another regression.
--detail changed (default) retains only rows whose output, repeated output or
error differs; --detail all retains every row. Aggregate and category metrics
and the regression gate always use all evaluated sentences.
Engine or refiner changes during evaluation invalidate the run independently
of the accuracy gate. Use --require-candidate-refiner when evaluating weights;
a missing or disabled candidate model then invalidates the run as well.
"""
import argparse
from collections import defaultdict
from copy import deepcopy
from dataclasses import asdict
from datetime import datetime, timezone
import hashlib
from importlib.metadata import PackageNotFoundError, version
import json
import math
from pathlib import Path
import os
import statistics
import subprocess
import sys
import time


def sha(value):
    return hashlib.sha256(value if isinstance(value, bytes) else value.encode()).hexdigest()


def compact(text):
    """Only ASCII spaces are editable; tabs, newlines and all other chars count."""
    return text.replace(" ", "")


def boundaries(text):
    offset, result = 0, set()
    for char in text:
        if char == " ":
            result.add(offset)
        else:
            offset += 1
    return result


def score(source, accepted, result, repeated):
    predicted = boundaries(result)
    # Choose one permitted reference by minimal boundary edit distance, with
    # stable ties. Do not mix TP from one reference with FP/FN from another.
    gold = min((boundaries(a) for a in accepted),
               key=lambda b: (len(b ^ predicted), sorted(b)))
    altered = compact(source) != compact(result)
    return {
        "exact": result in accepted,
        "characters_altered": altered,
        "idempotent": result == repeated,
        "tp": 0 if altered else len(gold & predicted),
        "fp": len(predicted) if altered else len(predicted - gold),
        "fn": len(gold) if altered else len(gold - predicted),
        "boundary_distance": None if altered else len(gold ^ predicted),
        "output_sha256": sha(result),
        "repeated_sha256": sha(repeated),
    }


def named_value(value):
    name, sep, content = value.partition("=")
    if not sep or not name or not content:
        raise argparse.ArgumentTypeError("expected NAME=VALUE")
    return name, content


def corpus_texts(path, raw=None):
    lines = (raw if raw is not None else path.read_bytes()).decode("utf-8-sig").splitlines()
    if path.suffix.lower() != ".conllu":
        return [line.strip() for line in lines if line.strip()]
    texts, current, has_tokens = [], None, False
    for line in [*lines, ""]:
        if line.startswith("# text = "):
            if current is not None:
                raise ValueError("CoNLL-U sentence has duplicate text fields")
            current = line[len("# text = "):].strip()
        elif line and not line.startswith("#"):
            has_tokens = True
        elif not line:
            if has_tokens or current is not None:
                if not current:
                    raise ValueError("CoNLL-U sentence is missing its original text field")
                texts.append(current)
            current, has_tokens = None, False
    return texts


def load_cases(corpora, fixtures, preferences, modes, limit):
    jobs, sources = [], []
    names = [name for name, _ in [*corpora, *fixtures]]
    if len(set(names)) != len(names):
        raise ValueError("source names must be unique")
    for authored, sources_in in ((False, corpora), (True, fixtures)):
        for name, filename in sources_in:
            path = Path(filename)
            raw = path.read_bytes()
            rows = json.loads(raw) if authored else [
                {"source": text, "accepted": [text]} for text in corpus_texts(path, raw)]
            if not isinstance(rows, list) or not rows:
                raise ValueError("every source must contain at least one sentence")
            selected = rows if limit is None else rows[:limit]
            sources.append({"name": name, "kind": "fixtures" if authored else "corpus",
                            "format": "json" if authored else path.suffix.lower(),
                            "sha256": sha(raw), "available": len(rows), "selected": len(selected),
                            "normalization": "line-edge stripping; ASCII-space-only restoration"})
            for index, row in enumerate(selected, 1):
                if not isinstance(row, dict) or not isinstance(row.get("source"), str):
                    raise ValueError("fixture source must be a string")
                accepted = row.get("accepted")
                if not isinstance(accepted, list) or not accepted or any(
                        not isinstance(a, str) or compact(a) != compact(row["source"])
                        for a in accepted):
                    raise ValueError("accepted variants must preserve the source characters")
                row_modes = row.get("modes", ["source"]) if authored else modes
                if not isinstance(row_modes, list) or not row_modes or any(
                        m not in ("source", "restore", "preserve") for m in row_modes):
                    raise ValueError("fixture modes must be a nonempty list of supported modes")
                overrides = row.get("preferences", {})
                if not isinstance(overrides, dict):
                    raise ValueError("fixture preferences must be an object")
                for mode in row_modes:
                    source = (compact(accepted[0]) if mode == "restore" else
                              accepted[0] if mode == "preserve" else row["source"])
                    for preference_name, setting in preferences.items():
                        jobs.append({"id": f"{name}:{index:06d}:{mode}:{preference_name}",
                                     "corpus": name, "mode": mode, "preference": preference_name,
                                     "source": source, "accepted": accepted,
                                     "authored": authored, "category": row.get("category") if authored else None,
                                     "preferences": {**setting, **overrides}})
    return jobs, sources


def engine_fingerprint(path):
    package = Path(path) / "hangul_ime"
    files = sorted(file for file in package.rglob("*") if file.is_file()
                   and "__pycache__" not in file.relative_to(package).parts
                   and file.suffix not in (".pyc", ".pyo") and file.name != ".DS_Store")
    if not any(file.suffix == ".py" for file in files):
        raise ValueError("engine must contain hangul_ime Python sources")
    digest = hashlib.sha256()
    for file in files:
        digest.update(file.relative_to(path).as_posix().encode() + b"\0" + file.read_bytes() + b"\0")
    return digest.hexdigest()


def worker(engine_path):
    request = json.load(sys.stdin)
    fingerprint = engine_fingerprint(engine_path)
    sys.path.insert(0, str(Path(engine_path).resolve()))
    from hangul_ime.release_spacing import KiwiSpacer
    from hangul_ime.spacing_preferences import SpacingPreferences
    started = time.perf_counter()
    spacer = KiwiSpacer()
    refiner_started = deepcopy(getattr(spacer, "refiner_info", None))
    startup_ms = (time.perf_counter() - started) * 1000
    settings, results = {}, []
    for job in request["jobs"]:
        # Errors contain only their type, since a library message might contain
        # input text. An error is a failed case, never an omitted observation.
        try:
            preference = SpacingPreferences.from_dict(job["preferences"])
            effective = asdict(preference)
            setting_id = sha(json.dumps(effective, sort_keys=True, ensure_ascii=False))
            settings[setting_id] = effective
            started = time.perf_counter()
            result = spacer.space(job["source"], preference)
            elapsed = (time.perf_counter() - started) * 1000
            repeated = spacer.space(result, preference)
            measurement = score(job["source"], job["accepted"], result, repeated)
            measurement.update(elapsed_ms=elapsed, settings_sha256=setting_id)
            if request["include_fixture_text"] and job["authored"]:
                measurement.update(output=result, repeated=repeated)
        except Exception as exc:
            measurement = {"error": type(exc).__name__}
        results.append(measurement)
    packages = {}
    for package in ("kiwipiepy", "kiwipiepy_model"):
        try:
            packages[package] = version(package)
        except PackageNotFoundError:
            packages[package] = None
    return {"metadata": {"engine_sha256": fingerprint,
                         "engine_fingerprint_version": 2,
                         "engine_sha256_scope": "all package files except __pycache__, .pyc, .pyo and .DS_Store",
                         "engine_source_stable": fingerprint == engine_fingerprint(engine_path),
                         "python": sys.version.split()[0], "packages": packages,
                         "startup_ms": startup_ms, "effective_settings": settings,
                         "refiner_started": refiner_started,
                         "refiner_finished": getattr(spacer, "refiner_info", None)},
            "results": results}


def run_engine(engine_path, jobs, include_fixture_text, timeout, refiner=None):
    """refiner: None inherits HANGUL_SPACING_REFINER; a path selects that file for
    this engine only; "none" points at a missing file so no refiner loads."""
    env = None
    if refiner is not None:
        env = dict(os.environ)
        env["HANGUL_SPACING_REFINER"] = (str(Path(engine_path).resolve() / ".no-refiner.npz")
                                         if refiner == "none" else str(Path(refiner).resolve()))
    # The worker speaks UTF-8 whatever the locale (cp949 on Korean Windows) or
    # PYTHONIOENCODING; stderr is never shown, so undecodable bytes are replaced.
    result = subprocess.run([sys.executable, str(Path(__file__).resolve()),
                             "--worker", str(Path(engine_path).resolve())],
                            input=json.dumps({"jobs": jobs, "include_fixture_text": include_fixture_text}),
                            encoding="utf-8", errors="replace", capture_output=True, timeout=timeout,
                            check=False, env=env)
    if result.returncode:
        # Do not forward stderr: dependency exceptions can expose corpus text.
        raise RuntimeError(f"engine worker failed with exit status {result.returncode}; stderr suppressed")
    try:
        payload = json.loads(result.stdout)
    except ValueError:
        raise RuntimeError("engine worker returned invalid JSON; output suppressed") from None
    if len(payload["results"]) != len(jobs):
        raise RuntimeError("engine worker returned the wrong sentence count")
    return payload


def aggregate(measurements):
    valid = [m for m in measurements if "error" not in m]
    tp, fp, fn = (sum(m[k] for m in valid) for k in ("tp", "fp", "fn"))
    times = sorted(m["elapsed_ms"] for m in valid)
    denominator = 2 * tp + fp + fn
    return {"count": len(measurements), "errors": len(measurements) - len(valid),
            "exact": sum(m["exact"] for m in valid),
            "exact_rate": sum(m["exact"] for m in valid) / len(measurements),
            "characters_altered": sum(m["characters_altered"] for m in valid),
            "non_idempotent": sum(not m["idempotent"] for m in valid),
            "tp": tp, "fp": fp, "fn": fn,
            "boundary_f1": (2 * tp / denominator if denominator else
                            0.0 if any(m["characters_altered"] for m in valid) else
                            1.0 if valid else None),
            "boundary_scored": len(valid),
            "boundary_distance": sum(m["boundary_distance"] or 0 for m in valid),
            "p50_ms": statistics.median(times) if times else None,
            "p95_ms": times[math.ceil(len(times) * .95) - 1] if times else None}


def changes(before, after):
    regression, improvement = [], []
    for name, before_bad, after_bad in (
        ("error", "error" in before, "error" in after),
        ("characters_altered", before.get("characters_altered", False), after.get("characters_altered", False)),
    ):
        if after_bad and not before_bad:
            regression.append(name)
        if before_bad and not after_bad:
            improvement.append(name)
    if "error" not in before and "error" not in after:
        for name, key in (("exact", "exact"), ("idempotence", "idempotent")):
            if before[key] and not after[key]:
                regression.append(name)
            if after[key] and not before[key]:
                improvement.append(name)
        a, b = before["boundary_distance"], after["boundary_distance"]
        if a is not None and b is not None:
            if b > a:
                regression.append("boundary_distance")
            if b < a:
                improvement.append("boundary_distance")
    return regression, improvement


def runtime_violations(baseline, candidate, require_candidate_refiner=False):
    violations = []
    for name, payload in (("baseline", baseline), ("candidate", candidate)):
        metadata = payload["metadata"]
        if not metadata["engine_source_stable"]:
            violations.append(f"{name}:engine_source_changed")
        started, finished = (metadata.get(f"refiner_{point}") for point in ("started", "finished"))
        if started != finished:
            violations.append(f"{name}:refiner_state_changed")
        if any(isinstance(state, dict) and (state.get("status") == "error" or state.get("error"))
               for state in (started, finished)):
            violations.append(f"{name}:refiner_error")
        if name == "candidate" and require_candidate_refiner and not all(
                isinstance(state, dict) and state.get("loaded") is True and state.get("status") == "loaded"
                for state in (started, finished)):
            violations.append("candidate:required_refiner_unavailable")
    return violations


def build_report(jobs, sources, baseline, candidate, gate_names, include_fixture_text=False, detail="changed",
                 require_candidate_refiner=False):
    if detail not in ("changed", "all"):
        raise ValueError("unsupported report detail")
    groups, sentences, regressions, improvements, violations = defaultdict(lambda: [[], []]), [], [], [], []
    categories = defaultdict(lambda: [[], []])
    for job, before, after in zip(jobs, baseline["results"], candidate["results"]):
        key = (job["corpus"], job["mode"], job["preference"])
        groups[key][0].append(before)
        groups[key][1].append(after)
        if job["authored"]:
            category_key = (*key, job["category"])
            categories[category_key][0].append(before)
            categories[category_key][1].append(after)
        worse, better = changes(before, after)
        row = {k: job[k] for k in ("id", "corpus", "mode", "preference", "category")}
        row.update(input_sha256=sha(job["source"]), reference_sha256=[sha(a) for a in job["accepted"]],
                   baseline=before, candidate=after, regression_reasons=worse, improvement_reasons=better)
        if include_fixture_text and job["authored"]:
            row.update(source=job["source"], accepted=job["accepted"])
        changed = any(before.get(k) != after.get(k)
                      for k in ("output_sha256", "repeated_sha256", "error"))
        if detail == "all" or changed:
            sentences.append(row)
        if worse:
            regressions.append(job["id"])
        if better:
            improvements.append(job["id"])
        if job["corpus"] in gate_names and (worse or "error" in after or after.get("characters_altered")):
            violations.append(job["id"])
    stable = baseline["metadata"]["engine_source_stable"] and candidate["metadata"]["engine_source_stable"]
    invalid = runtime_violations(baseline, candidate, require_candidate_refiner)
    return {"schema_version": 2, "created_at": datetime.now(timezone.utc).isoformat(),
            "evaluator_sha256": sha(Path(__file__).read_bytes()), "sources": sources,
            "baseline": baseline["metadata"], "candidate": candidate["metadata"],
            "metrics": {"boundary": "ASCII-space offsets; closest accepted boundary set",
                        "altered_characters": "excluded from aligned TP; all predicted/gold boundaries counted FP/FN",
                        "errors": "counted in exact denominator, excluded from boundary F1; always fail selected gate",
                        "latency": "first pass per case, excluding idempotence pass; sequential processes"},
            "groups": [{"corpus": k[0], "mode": k[1], "preference": k[2],
                        "baseline": aggregate(v[0]), "candidate": aggregate(v[1])} for k, v in groups.items()],
            "categories": [{"corpus": k[0], "mode": k[1], "preference": k[2], "category": k[3],
                            "baseline": aggregate(v[0]), "candidate": aggregate(v[1])}
                           for k, v in categories.items()],
            "detail": {"mode": detail, "evaluated": len(jobs), "included": len(sentences),
                       "omitted": len(jobs) - len(sentences)},
            "regressions": regressions, "improvements": improvements, "sentences": sentences,
            "runtime": {"valid": not invalid, "violations": invalid,
                        "candidate_refiner_required": require_candidate_refiner,
                        "policy": "stable engine sources and refiner identity/availability; no refiner errors"},
            "gate": {"enabled": bool(gate_names), "corpora": sorted(gate_names),
                     "passed": not violations and not invalid, "violations": violations,
                     "engine_source_stable": stable,
                     "runtime_valid": not invalid,
                     "policy": "valid runtime; no sentence-level worsening in boundary distance, exactness, character preservation or idempotence; no candidate errors/character changes"}}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--worker", help=argparse.SUPPRESS)
    parser.add_argument("--baseline-engine", type=Path)
    parser.add_argument("--candidate-engine", type=Path)
    parser.add_argument("--corpus", action="append", type=named_value, default=[])
    parser.add_argument("--fixtures", action="append", type=named_value, default=[])
    parser.add_argument("--preferences", action="append", type=named_value)
    parser.add_argument("--mode", choices=("restore", "preserve"), action="append")
    parser.add_argument("--limit", type=int, help="deterministic first N rows per source")
    parser.add_argument("--timeout", type=float, default=1800, help="seconds per isolated engine")
    parser.add_argument("--include-fixture-text", action="store_true")
    parser.add_argument("--detail", choices=("changed", "all"), default="changed",
                        help="sentence rows to retain; all metrics always include every case")
    parser.add_argument("--require-no-regression", action="store_true")
    parser.add_argument("--require-candidate-refiner", action="store_true",
                        help="invalidate the run unless candidate weights remain loaded throughout")
    parser.add_argument("--gate-corpus", action="append", help="repeat to select gated sources; default all")
    parser.add_argument("--baseline-refiner", help='refiner .npz for the baseline engine, or "none"')
    parser.add_argument("--candidate-refiner", help='refiner .npz for the candidate engine, or "none"')
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    if args.worker:
        for stream in (sys.stdin, sys.stdout):
            stream.reconfigure(encoding="utf-8")
        print(json.dumps(worker(args.worker), ensure_ascii=False))
        return 0
    if not args.baseline_engine or not args.candidate_engine or not (args.corpus or args.fixtures):
        parser.error("both engines and at least one --corpus or --fixtures are required")
    if args.limit is not None and args.limit < 1:
        parser.error("--limit must be positive")
    if args.timeout <= 0:
        parser.error("--timeout must be positive")
    if args.gate_corpus and not args.require_no_regression:
        parser.error("--gate-corpus requires --require-no-regression")
    preferences = {}
    for name, value in args.preferences or [("default", "{}")]:
        setting = json.loads(value)
        if not isinstance(setting, dict) or name in preferences:
            parser.error("preferences must be uniquely named JSON objects")
        preferences[name] = setting
    jobs, sources = load_cases(args.corpus, args.fixtures, preferences,
                               list(dict.fromkeys(args.mode or ["restore", "preserve"])), args.limit)
    all_names = {s["name"] for s in sources}
    gate_names = set(args.gate_corpus or all_names) if args.require_no_regression else set()
    if gate_names - all_names:
        parser.error("unknown --gate-corpus")
    baseline = run_engine(args.baseline_engine, jobs, args.include_fixture_text, args.timeout,
                          args.baseline_refiner)
    candidate = run_engine(args.candidate_engine, jobs, args.include_fixture_text, args.timeout,
                           args.candidate_refiner)
    report = build_report(jobs, sources, baseline, candidate, gate_names, args.include_fixture_text, args.detail,
                          args.require_candidate_refiner)
    report["selection"] = {"limit": args.limit, "corpus_modes": args.mode or ["restore", "preserve"],
                           "preferences": preferences, "fixture_text_included": args.include_fixture_text}
    output = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(output, encoding="utf-8")
    else:
        print(output, end="")
    return 1 if (not report["runtime"]["valid"] or
                 args.require_no_regression and not report["gate"]["passed"]) else 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"Evaluation failed ({type(exc).__name__}); input-bearing details suppressed.", file=sys.stderr)
        raise SystemExit(2)
