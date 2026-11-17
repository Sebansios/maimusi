"""Paired statistics are verified on synthetic count tables only."""
from copy import deepcopy
import importlib.util
import json
from pathlib import Path
import subprocess
import sys

import numpy as np
import pytest

TOOLS = Path(__file__).resolve().parents[2] / "tools"


def module(name):
    spec = importlib.util.spec_from_file_location(name, TOOLS / f"{name}.py")
    loaded = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(loaded)
    return loaded


evaluation = module("compare_spacing")
statistics = module("spacing_paired_statistics")


def make_report(pairs=None):
    # Each tuple is exact, TP, FP, FN. This table has an exact-match tie but a
    # boundary improvement, so the two notions cannot be accidentally conflated.
    pairs = pairs or [
        ((True, 1, 0, 0), (True, 1, 0, 0)),
        ((False, 0, 0, 1), (True, 1, 0, 0)),
        ((True, 1, 0, 0), (False, 0, 0, 1)),
        ((False, 0, 1, 1), (False, 0, 0, 1)),
    ]
    jobs, before, after = [], [], []
    for i, pair in enumerate(pairs, 1):
        jobs.append(dict(id=f"sample:{i:06d}:restore:default", corpus="sample", mode="restore",
                         preference="default", source=f"SENSITIVE_SYNTHETIC_{i}",
                         accepted=[f"SENSITIVE_SYNTHETIC_{i}"], authored=True, category="synthetic"))
        for counts, destination in zip(pair, (before, after)):
            exact, tp, fp, fn = counts
            destination.append(dict(exact=exact, tp=tp, fp=fp, fn=fn, boundary_distance=fp + fn,
                                    characters_altered=False, idempotent=True, elapsed_ms=1.,
                                    output_sha256=evaluation.sha(str(counts)), repeated_sha256=evaluation.sha(str(counts))))
    sources = [dict(name="sample", sha256=evaluation.sha(b"synthetic-source"), available=len(pairs), selected=len(pairs))]
    payload = lambda rows, value: {"metadata": {"engine_source_stable": True, "engine_sha256": value * 64}, "results": rows}
    return evaluation.build_report(jobs, sources, payload(before, "a"), payload(after, "b"), set(),
                                   include_fixture_text=True, detail="all")


def document_map(report, labels):
    return {"source_sha256": report["sources"][0]["sha256"],
            "rows": [dict(document_sha256=evaluation.sha(label), compact_sha256=row["input_sha256"])
                     for label, row in zip(labels, report["sentences"])]}


def test_exact_discordants_and_micro_f1_use_paired_counts():
    result = statistics.summarize(make_report(), samples=400)
    group = result["groups"][0]
    assert group["exact_pairs"] == dict(both_correct=1, both_incorrect=1, improved=1, regressed=1, discordant=2)
    assert group["boundary_distance_pairs"] == dict(improved=2, regressed=1, tied=1)
    assert group["exact_rate"]["delta"]["value"] == 0
    assert group["boundary_f1"]["baseline"]["value"] == pytest.approx(4 / 7)
    assert group["boundary_f1"]["candidate"]["value"] == pytest.approx(4 / 6)
    assert group["boundary_f1"]["delta"]["value"] == pytest.approx(4 / 6 - 4 / 7)
    assert group["resampling"]["unit"] == "sentence"
    assert group["resampling"]["units"] == 4


def test_identical_engines_have_exactly_zero_paired_delta_intervals():
    rows = [(True, 100, 0, 0), (False, 0, 2, 1), (False, 1, 0, 1)]
    result = statistics.summarize(make_report([(row, row) for row in rows]), samples=300)
    group = result["groups"][0]
    for metric in ("exact_rate", "boundary_f1"):
        assert group[metric]["delta"] == dict(value=0., ci=[0., 0.])
        assert group[metric]["baseline"]["ci"] == group[metric]["candidate"]["ci"]


def test_document_bootstrap_weights_sentences_and_keeps_clusters_whole():
    improve = ((False, 0, 0, 1), (True, 1, 0, 0))
    regress = ((True, 1, 0, 0), (False, 0, 0, 1))
    report = make_report([improve, improve, improve, regress])
    mapping = document_map(report, ["long", "long", "long", "short"])
    result = statistics.summarize(report, document_maps={"sample": mapping}, samples=1000)
    group = result["groups"][0]
    assert group["resampling"]["unit"] == "document" and group["resampling"]["units"] == 2
    assert (group["resampling"]["minimum_unit_sentences"], group["resampling"]["maximum_unit_sentences"]) == (1, 3)
    assert group["exact_rate"]["delta"] == dict(value=.5, ci=[-1., 1.])
    # Repeated long/short clusters produce denominators 6/4/2, never a mean
    # of the two cluster rates. The mixed draw must retain the observed .5.
    long = np.array([3, 0, 3, 0, 0, 3, 3, 0, 0])
    short = np.array([1, 1, 0, 1, 0, 0, 0, 0, 1])
    assert statistics.rates(np.stack([long * 2, long + short, short * 2]))[:, 2].tolist() == [1., .5, -1.]


def test_one_cluster_reports_unavailable_ci_and_zero_boundary_f1_is_defined():
    report = make_report([((True, 0, 0, 0), (True, 0, 0, 0))])
    group = statistics.summarize(report, samples=100)["groups"][0]
    assert group["boundary_f1"]["baseline"] == dict(value=1., ci=None)
    assert group["boundary_f1"]["delta"] == dict(value=0., ci=None)
    assert not group["resampling"]["confidence_interval_available"]


def test_bootstrap_is_reproducible_with_fixed_seed():
    report = make_report()
    first = statistics.summarize(report, samples=300, seed=42)
    second = statistics.summarize(report, samples=300, seed=42)
    assert first["groups"] == second["groups"]


@pytest.mark.parametrize("change", [
    lambda report: report["detail"].update(mode="changed"),
    lambda report: report["detail"].update(omitted=1),
    lambda report: report["runtime"].update(valid=False),
    lambda report: report["candidate"].update(engine_source_stable=False),
    lambda report: report["candidate"].update(refiner_finished={"loaded": False}),
    lambda report: report["sentences"][0]["candidate"].update(error="ValueError"),
    lambda report: report["sentences"][0]["candidate"].update(characters_altered=True),
    lambda report: report["sentences"][0]["candidate"].update(tp=-1),
    lambda report: report["sentences"][0]["candidate"].update(boundary_distance=3),
    lambda report: report["sentences"][0].update(id=report["sentences"][1]["id"]),
    lambda report: report["groups"][0]["candidate"].update(exact=999),
])
def test_invalid_reports_are_rejected_instead_of_dropping_failed_rows(change):
    report = make_report()
    change(report)
    with pytest.raises(ValueError):
        statistics.summarize(report, samples=100)


@pytest.mark.parametrize("change", [
    lambda mapping: mapping.update(source_sha256="0" * 64),
    lambda mapping: mapping["rows"].pop(),
    lambda mapping: mapping["rows"].reverse(),
    lambda mapping: mapping["rows"][0].update(document_sha256="raw-private-document-id"),
])
def test_document_mapping_requires_source_and_row_alignment(change):
    report = make_report()
    mapping = document_map(report, ["first", "first", "second", "second"])
    change(mapping)
    with pytest.raises(ValueError):
        statistics.summarize(report, document_maps={"sample": mapping}, samples=100)


def test_cli_emits_only_aggregates_and_hashes_even_if_input_contains_fixture_text(tmp_path):
    report = make_report()
    refiner = dict(loaded=True, status="loaded", model_sha256="c" * 64,
                   confidence_threshold=1.3, removal_threshold=6.0, error=None)
    report["candidate"].update(refiner_started=refiner, refiner_finished=refiner)
    mapping = document_map(report, ["first", "first", "second", "second"])
    source, map_path = tmp_path / "private-comparison.json", tmp_path / "private-document-map.json"
    output, markdown = tmp_path / "public-statistics.json", tmp_path / "public-statistics.md"
    source.write_text(json.dumps(report), encoding="utf-8")
    map_path.write_text(json.dumps(mapping), encoding="utf-8")
    run = subprocess.run([sys.executable, str(TOOLS / "spacing_paired_statistics.py"), str(source),
                          "--document-map", f"sample={map_path}", "--samples", "100", "--output", str(output),
                          "--markdown", str(markdown)], capture_output=True, text=True)
    assert run.returncode == 0, run.stderr
    encoded = output.read_text(encoding="utf-8") + markdown.read_text(encoding="utf-8") + run.stdout + run.stderr
    assert "SENSITIVE_SYNTHETIC" not in encoded and str(tmp_path) not in encoded
    for row in mapping["rows"]:
        assert row["document_sha256"] not in encoded
    actual = json.loads(output.read_text(encoding="utf-8"))
    assert actual["comparison_report_sha256"] == evaluation.sha(source.read_bytes())
    assert actual["document_maps"][0]["sha256"] == evaluation.sha(map_path.read_bytes())
    assert actual["document_maps"][0]["restore_compact_hashes_checked"] == 4
    assert actual["candidate"]["refiner"]["confidence_threshold"] == 1.3
    assert actual["candidate"]["refiner"]["removal_threshold"] == 6.0
    assert "percentage points" in markdown.read_text(encoding="utf-8")
    assert "2 document units" in markdown.read_text(encoding="utf-8")
    assert actual["corpus_files_read"] is False and actual["model_inference_performed"] is False


def test_domains_modes_and_preferences_are_never_pooled():
    report = make_report()
    second = deepcopy(report)
    for row in second["sentences"]:
        row.update(mode="preserve", preference="join")
        row["id"] = row["id"].replace(":restore:default", ":preserve:join")
    second["groups"][0].update(mode="preserve", preference="join")
    report["sentences"] += second["sentences"]
    report["groups"] += second["groups"]
    report["detail"].update(evaluated=8, included=8)
    result = statistics.summarize(report, samples=100)
    assert len(result["groups"]) == 2
    assert all(group["sentences"] == 4 for group in result["groups"])
    assert {group["mode"] for group in result["groups"]} == {"restore", "preserve"}
    assert {group["preference"] for group in result["groups"]} == {"default", "join"}
