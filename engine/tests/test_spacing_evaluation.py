"""Evaluator contracts use tiny fake engines; these tests never load Kiwi."""
import importlib.util
import json
from pathlib import Path
import subprocess
import sys

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "tools" / "compare_spacing.py"
SPEC = importlib.util.spec_from_file_location("compare_spacing", SCRIPT)
evaluation = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(evaluation)


def fake_engine(path, outputs):
    package = path / "hangul_ime"
    package.mkdir(parents=True)
    (package / "__init__.py").write_text("", encoding="utf-8")
    (package / "spacing_preferences.py").write_text(
        "from dataclasses import dataclass\n"
        "@dataclass\n"
        "class SpacingPreferences:\n"
        "    compound: str = 'model'\n"
        "    @classmethod\n"
        "    def from_dict(cls, values):\n"
        "        return cls(**values)\n", encoding="utf-8")
    (package / "release_spacing.py").write_text(
        f"OUTPUTS = {outputs!r}\n"
        "class KiwiSpacer:\n"
        "    def space(self, text, preferences):\n"
        "        return OUTPUTS.get(text, text)\n", encoding="utf-8")
    return path


def test_boundary_scores_permitted_variants_and_non_space_characters():
    result = evaluation.score("가나다", ["가 나다", "가나 다"], "가나 다", "가나 다")
    assert result["exact"] and result["idempotent"]
    assert (result["tp"], result["fp"], result["fn"], result["boundary_distance"]) == (1, 0, 0, 0)
    altered = evaluation.score("가\t나", ["가\t나"], "가나", "가나")
    assert altered["characters_altered"]
    assert altered["boundary_distance"] is None
    assert altered["tp"] == 0
    altered["elapsed_ms"] = 1
    assert evaluation.aggregate([altered])["boundary_f1"] == 0


def test_load_conllu_uses_original_text_and_rejects_missing_reference(tmp_path):
    corpus = tmp_path / "data.conllu"
    corpus.write_text("# sent_id = native-secret-id\n# text = 가 나.\n1\tirrelevant\n\n"
                      "# text = 다라!\n1\tignored\n", encoding="utf-8")
    assert evaluation.corpus_texts(corpus) == ["가 나.", "다라!"]
    corpus.write_text("# sent_id = s1\n1\t가\n", encoding="utf-8")
    with pytest.raises(ValueError, match="missing"):
        evaluation.corpus_texts(corpus)


def test_modes_preferences_source_hash_and_fixture_overrides(tmp_path):
    corpus = tmp_path / "source.txt"
    corpus.write_text("  가 나  \n\n다 라\n", encoding="utf-8")
    fixtures = tmp_path / "fixtures.json"
    fixtures.write_text(json.dumps([{"source": "마 바", "accepted": ["마바"],
                                     "modes": ["source", "restore", "preserve"],
                                     "preferences": {"compound": "join"}}]), encoding="utf-8")
    jobs, sources = evaluation.load_cases(
        [("written", str(corpus))], [("authored", str(fixtures))],
        {"default": {}, "separate": {"compound": "separate"}}, ["restore", "preserve"], 1)
    assert len(jobs) == 10
    assert [job["source"] for job in jobs[:4]] == ["가나", "가나", "가 나", "가 나"]
    assert all(job["preferences"] == {"compound": "join"} for job in jobs[4:])
    assert sources[0]["sha256"] == evaluation.sha(corpus.read_bytes())
    assert sources[0]["available"] == 2 and sources[0]["selected"] == 1
    assert str(corpus) not in json.dumps(sources)


def test_fixture_spelling_changes_cannot_disguise_spacing_accuracy(tmp_path):
    fixtures = tmp_path / "fixtures.json"
    fixtures.write_text(json.dumps([{"source": "가나", "accepted": ["가다"]}]), encoding="utf-8")
    with pytest.raises(ValueError, match="preserve"):
        evaluation.load_cases([], [("bad", str(fixtures))], {"default": {}}, ["restore"], None)


def test_paired_workers_gate_individual_regression_and_hide_text(tmp_path):
    # Equal aggregate quality is insufficient: row 1 regresses while row 2
    # improves by the same amount. Same module name in two roots tests isolation.
    baseline = fake_engine(tmp_path / "baseline", {"가나다": "가 나다", "라마바": "라마바"})
    candidate = fake_engine(tmp_path / "candidate", {"가나다": "가나다", "라마바": "라 마바"})
    corpus = tmp_path / "private.txt"
    corpus.write_text("가 나다\n라 마바\n", encoding="utf-8")
    report_path = tmp_path / "report.json"
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--baseline-engine", str(baseline),
         "--candidate-engine", str(candidate), "--corpus", f"written={corpus}",
         "--mode", "restore", "--require-no-regression", "--output", str(report_path)],
        capture_output=True, text=True)
    assert result.returncode == 1, result.stderr
    encoded = report_path.read_text(encoding="utf-8")
    assert all(text not in encoded for text in ("가 나다", "라 마바", str(corpus)))
    report = json.loads(encoded)
    assert report["groups"][0]["baseline"]["boundary_f1"] == report["groups"][0]["candidate"]["boundary_f1"]
    assert report["regressions"] == ["written:000001:restore:default"]
    assert report["improvements"] == ["written:000002:restore:default"]
    assert report["gate"]["violations"] == report["regressions"]
    assert not report["gate"]["passed"]
    assert report["baseline"]["engine_sha256"] != report["candidate"]["engine_sha256"]


def test_idempotence_regression_is_gated_and_authored_text_is_opt_in(tmp_path):
    baseline = fake_engine(tmp_path / "baseline", {"가나다": "가나 다"})
    candidate = fake_engine(tmp_path / "candidate", {"가나다": "가나 다", "가나 다": "가 나 다"})
    fixtures = tmp_path / "fixtures.json"
    fixtures.write_text(json.dumps([{"source": "가나다", "accepted": ["가나 다"]}]), encoding="utf-8")
    jobs, sources = evaluation.load_cases([], [("authored", str(fixtures))], {"default": {}}, ["restore"], None)
    before = evaluation.run_engine(baseline, jobs, False, 10)
    after = evaluation.run_engine(candidate, jobs, False, 10)
    report = evaluation.build_report(jobs, sources, before, after, {"authored"})
    assert report["sentences"][0]["regression_reasons"] == ["idempotence"]
    assert not report["gate"]["passed"]
    assert "output" not in after["results"][0]
    disclosed = evaluation.run_engine(candidate, jobs, True, 10)
    authored = evaluation.build_report(jobs, sources, before, disclosed, set(), True)
    assert authored["sentences"][0]["source"] == "가나다"
    assert authored["sentences"][0]["candidate"]["output"] == "가나 다"


@pytest.mark.parametrize("io_encoding", ["utf-8", "latin-1"])
def test_worker_speaks_utf8_whatever_pythonioencoding_says(tmp_path, monkeypatch, io_encoding):
    monkeypatch.setenv("PYTHONIOENCODING", io_encoding)
    engine = fake_engine(tmp_path / "engine", {"가나다": "가나 다"})
    fixtures = tmp_path / "fixtures.json"
    fixtures.write_text(json.dumps([{"source": "가나다", "accepted": ["가나 다"]}]), encoding="utf-8")
    jobs, _ = evaluation.load_cases([], [("authored", str(fixtures))], {"default": {}}, ["restore"], None)
    payload = evaluation.run_engine(engine, jobs, True, 10)
    assert payload["results"][0]["output"] == "가나 다"


def test_worker_errors_are_counted_not_dropped_or_leaked(tmp_path):
    engine = fake_engine(tmp_path / "broken", {})
    (engine / "hangul_ime" / "release_spacing.py").write_text(
        "class KiwiSpacer:\n"
        "    def space(self, text, preferences):\n"
        "        raise ValueError(text)\n", encoding="utf-8")
    corpus = tmp_path / "private.txt"
    corpus.write_text("비밀 문장\n", encoding="utf-8")
    jobs, sources = evaluation.load_cases([("written", str(corpus))], [], {"default": {}}, ["restore"], None)
    payload = evaluation.run_engine(engine, jobs, False, 10)
    assert payload["results"] == [{"error": "ValueError"}]
    report = evaluation.build_report(jobs, sources, payload, payload, {"written"})
    assert report["groups"][0]["candidate"]["errors"] == 1
    assert report["groups"][0]["candidate"]["exact_rate"] == 0
    assert report["groups"][0]["candidate"]["boundary_f1"] is None
    assert not report["gate"]["passed"]
    assert "비밀" not in json.dumps(report, ensure_ascii=False)


def test_gate_selection_and_source_changes(tmp_path):
    corpus = tmp_path / "source.txt"
    corpus.write_text("가 나\n", encoding="utf-8")
    jobs, sources = evaluation.load_cases([("informal", str(corpus))], [], {"default": {}}, ["restore"], None)
    before = evaluation.score("가나", ["가 나"], "가 나", "가 나")
    after = evaluation.score("가나", ["가 나"], "가나", "가나")
    before["elapsed_ms"] = after["elapsed_ms"] = 1
    baseline = {"metadata": {"engine_source_stable": True}, "results": [before]}
    candidate = {"metadata": {"engine_source_stable": True}, "results": [after]}
    report = evaluation.build_report(jobs, sources, baseline, candidate, {"written"})
    assert report["regressions"] and report["gate"]["passed"]
    candidate["metadata"]["engine_source_stable"] = False
    assert not evaluation.build_report(jobs, sources, baseline, candidate, {"written"})["gate"]["passed"]


def test_engine_fingerprint_covers_runtime_lexicons_but_not_caches(tmp_path):
    engine = fake_engine(tmp_path / "engine", {})
    original = evaluation.engine_fingerprint(engine)
    data = engine / "hangul_ime" / "spacing_data"
    data.mkdir()
    lexicon = data / "words.tsv"
    lexicon.write_text("새말\tNNG\n", encoding="utf-8")
    added = evaluation.engine_fingerprint(engine)
    assert added != original
    lexicon.write_text("다른새말\tNNG\n", encoding="utf-8")
    updated = evaluation.engine_fingerprint(engine)
    assert updated != added
    cache = engine / "hangul_ime" / "__pycache__"
    cache.mkdir()
    (cache / "compiled.pyc").write_bytes(b"cache depends on interpreter")
    (engine / "hangul_ime" / ".DS_Store").write_bytes(b"finder metadata")
    assert evaluation.engine_fingerprint(engine) == updated


def test_changed_detail_preserves_full_aggregates_and_fixture_categories(tmp_path):
    fixtures = tmp_path / "fixtures.json"
    fixtures.write_text(json.dumps([
        {"source": "가나", "accepted": ["가 나"], "category": "slang"},
        {"source": "다라", "accepted": ["다 라"], "category": "slang"},
        {"source": "마바사", "accepted": ["마바사"], "category": "dialect"},
    ]), encoding="utf-8")
    jobs, sources = evaluation.load_cases([], [("fixtures", str(fixtures))], {"default": {}}, [], None)
    def payload(outputs):
        results = []
        for job, output in zip(jobs, outputs):
            row = evaluation.score(job["source"], job["accepted"], output, output)
            row["elapsed_ms"] = 1
            results.append(row)
        return {"metadata": {"engine_source_stable": True}, "results": results}
    before = payload(["가나", "다라", "마 바사"])
    after = payload(["가 나", "다라", "마바 사"])
    short = evaluation.build_report(jobs, sources, before, after, {"fixtures"})
    full = evaluation.build_report(jobs, sources, before, after, {"fixtures"}, detail="all")
    assert short["detail"] == {"mode": "changed", "evaluated": 3, "included": 2, "omitted": 1}
    assert full["detail"]["included"] == 3
    assert [r["id"] for r in short["sentences"]] == [jobs[0]["id"], jobs[2]["id"]]
    # Row 3 changes output without changing its distance/exactness; retain it.
    assert not short["sentences"][1]["improvement_reasons"]
    assert not short["sentences"][1]["regression_reasons"]
    for key in ("groups", "categories", "gate", "regressions", "improvements"):
        assert short[key] == full[key]
    slang = next(row for row in short["categories"] if row["category"] == "slang")
    assert slang["baseline"]["count"] == slang["candidate"]["count"] == 2
    assert slang["baseline"]["exact"] == 0 and slang["candidate"]["exact"] == 1


def refiner_state(**updates):
    return dict(loaded=True, status="loaded", model_sha256="a" * 64,
                confidence_threshold=3.0, error=None) | updates


@pytest.mark.parametrize("finished,reason", [
    (refiner_state(loaded=False, status="error", error="ValueError"), "refiner_error"),
    (refiner_state(model_sha256="b" * 64), "refiner_state_changed"),
    (refiner_state(confidence_threshold=4.0), "refiner_state_changed"),
    (refiner_state(loaded=False, status="disabled"), "refiner_state_changed"),
    (None, "refiner_state_changed"),
])
def test_refiner_runtime_changes_invalidate_even_identical_outputs(finished, reason):
    baseline = {"metadata": {"engine_source_stable": True}}
    candidate = {"metadata": {"engine_source_stable": True,
                               "refiner_started": refiner_state(), "refiner_finished": finished}}
    violations = evaluation.runtime_violations(baseline, candidate)
    assert f"candidate:{reason}" in violations
    assert "candidate:refiner_state_changed" in violations


def test_missing_model_is_allowed_only_when_not_required_and_errors_are_never_valid():
    baseline = {"metadata": {"engine_source_stable": True}}
    candidate = {"metadata": {"engine_source_stable": True}}
    assert not evaluation.runtime_violations(baseline, candidate)
    assert evaluation.runtime_violations(baseline, candidate, True) == [
        "candidate:required_refiner_unavailable"]
    for state in (refiner_state(), refiner_state(loaded=False, status="missing"),
                  refiner_state(loaded=False, status="error", error="BadZipFile")):
        candidate["metadata"].update(refiner_started=state, refiner_finished=state)
        expected = state["status"] == "error"
        assert bool(evaluation.runtime_violations(baseline, candidate)) == expected
        assert bool(evaluation.runtime_violations(baseline, candidate, True)) == (not state["loaded"])


@pytest.mark.parametrize("require_model,mutate", [(False, True), (True, False)])
def test_cli_rejects_refiner_fallback_or_required_missing_model_without_accuracy_gate(
        tmp_path, require_model, mutate):
    baseline = fake_engine(tmp_path / "baseline", {})
    candidate = fake_engine(tmp_path / "candidate", {})
    if mutate:
        # Mutate the same dictionary in place: the worker must snapshot initial
        # state, rather than retaining a reference that changes with the model.
        (candidate / "hangul_ime" / "release_spacing.py").write_text(
            "class KiwiSpacer:\n"
            "    def __init__(self):\n"
            f"        self.refiner_info = {refiner_state()!r}\n"
            "    def space(self, text, preferences):\n"
            "        self.refiner_info.update(loaded=False, status='error', error='ValueError')\n"
            "        return text\n", encoding="utf-8")
    corpus = tmp_path / "corpus.txt"
    corpus.write_text("비밀문장\n", encoding="utf-8")
    output = tmp_path / "report.json"
    command = [sys.executable, str(SCRIPT), "--baseline-engine", str(baseline),
               "--candidate-engine", str(candidate), "--corpus", f"corpus={corpus}",
               "--mode", "restore", "--output", str(output)]
    if require_model:
        command.append("--require-candidate-refiner")
    run = subprocess.run(command, capture_output=True, text=True)
    assert run.returncode == 1, run.stderr
    report = json.loads(output.read_text(encoding="utf-8"))
    assert report["groups"][0]["baseline"]["exact"] == report["groups"][0]["candidate"]["exact"] == 1
    assert not report["runtime"]["valid"] and not report["gate"]["passed"]
    assert not report["gate"]["enabled"]  # Runtime validity is independent.
    assert report["runtime"]["candidate_refiner_required"] == require_model
    if mutate:
        assert report["candidate"]["refiner_started"]["loaded"] is True
        assert report["candidate"]["refiner_finished"]["loaded"] is False
    assert "비밀" not in output.read_text(encoding="utf-8")
