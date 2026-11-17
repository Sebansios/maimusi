"""Optional model loading, layout boundaries, preferences, and safe fallback."""
import hashlib
import io
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from hangul_ime import release_spacing
from hangul_ime.boundary_refiner import BoundaryRefiner
from hangul_ime.release_spacing import KiwiSpacer
from hangul_ime.spacing_preferences import SpacingPreferences


class FakeKiwi:
    def __init__(self, **kwargs):
        pass

    def space(self, text):
        return text

    def tokenize(self, text, **kwargs):
        return []

    def morpheme(self, identifier):
        return None


class FakeRefiner:
    def __init__(self, predict=lambda text: text, metadata=None):
        self.predict = predict
        self.metadata = metadata or {}
        self.calls = []

    def refine(self, text, *, confidence_threshold, removal_threshold=None):
        self.calls.append((text, confidence_threshold))
        return self.predict(text)


@pytest.fixture
def fake_models(monkeypatch, tmp_path):
    monkeypatch.setattr("kiwipiepy.Kiwi", FakeKiwi)
    monkeypatch.setattr(release_spacing, "register_informal_vocabulary", lambda kiwi: None)
    monkeypatch.setattr(release_spacing, "_default_refiner_path", lambda: tmp_path / "absent.npz")
    monkeypatch.setattr(release_spacing, "_bundled_refiner_path", lambda: tmp_path / "absent-bundled.npz")
    monkeypatch.delenv("HANGUL_SPACING_REFINER", raising=False)

    def make(predict=lambda text: text, metadata=None, **kwargs):
        refiner = FakeRefiner(predict, metadata)
        path = tmp_path / "model.npz"
        path.write_bytes(b"synthetic integration fixture")
        monkeypatch.setattr(BoundaryRefiner, "load", lambda path: refiner)
        return KiwiSpacer(path, **kwargs), refiner, path
    return make


def test_disabled_bypasses_environment_and_missing_auto_is_legacy(fake_models, monkeypatch):
    assert KiwiSpacer().refiner_info == dict(loaded=False, status="missing", model_sha256=None,
                                           confidence_threshold=None, removal_threshold=None, error=None)
    monkeypatch.setenv("HANGUL_SPACING_REFINER", "/nonexistent/explicit/environment/path")
    spacer = KiwiSpacer(False)
    assert spacer.refiner_status == "disabled"
    assert spacer.space("한글 입력") == "한글 입력"


def test_bundled_refiner_is_used_only_without_a_user_file(fake_models, monkeypatch, tmp_path):
    fake_models()  # installs the fake loader
    bundled = tmp_path / "bundled.npz"
    bundled.write_bytes(b"bundled release model")
    monkeypatch.setattr(release_spacing, "_bundled_refiner_path", lambda: bundled)
    spacer = KiwiSpacer()
    assert spacer.refiner_status == "loaded"
    assert spacer.refiner_sha256 == hashlib.sha256(b"bundled release model").hexdigest()
    user = tmp_path / "user.npz"
    user.write_bytes(b"user-installed model")
    monkeypatch.setattr(release_spacing, "_default_refiner_path", lambda: user)
    assert KiwiSpacer().refiner_sha256 == hashlib.sha256(b"user-installed model").hexdigest()


def test_explicit_missing_fails_and_invalid_auto_falls_back(fake_models, monkeypatch, tmp_path):
    with pytest.raises(FileNotFoundError):
        KiwiSpacer(tmp_path / "does-not-exist.npz")
    broken = tmp_path / "broken.npz"
    broken.write_bytes(b"not a model")
    monkeypatch.setenv("HANGUL_SPACING_REFINER", str(broken))
    spacer = KiwiSpacer()
    assert spacer.refiner_status == "error"
    assert spacer.refiner_error == "BadZipFile"
    assert spacer.space("한글 입력") == "한글 입력"
    assert str(broken) not in json.dumps(spacer.refiner_info)


def test_model_fingerprint_metadata_threshold_and_override(fake_models, monkeypatch):
    spacer, refiner, path = fake_models(metadata={"confidence_threshold": 2.5})
    assert spacer.refiner_sha256 == hashlib.sha256(path.read_bytes()).hexdigest()
    assert spacer.refiner_threshold == 2.5
    assert spacer.refiner_info["loaded"] is True
    monkeypatch.setenv("HANGUL_SPACING_REFINER", str(path))
    assert KiwiSpacer().refiner_threshold == 2.5
    assert KiwiSpacer(refiner_threshold=4).refiner_threshold == 4
    assert fake_models()[0].refiner_threshold == 1.3


def test_service_ping_reports_model_health_after_runtime_failure(fake_models):
    from hangul_ime.ime_service import Service

    spacer, _, _ = fake_models(lambda text: text + "변경")
    service = Service.__new__(Service)
    service.spacer = spacer
    service.preferences = SpacingPreferences()
    started = service.handle({"op": "ping"})
    assert started["refiner"]["loaded"] is True
    assert service.handle({"op": "space", "text": "가나"})["text"] == "가나"
    finished = service.handle({"op": "ping"})
    assert finished["refiner"]["loaded"] is False
    assert finished["refiner"]["status"] == "error"
    assert finished["refiner"]["error"] == "ValueError"
    assert "가나" not in json.dumps(finished, ensure_ascii=False)


@pytest.mark.parametrize("value", [-1, float("nan"), float("inf"), True, "3"])
def test_bad_threshold_is_configuration_error(fake_models, value):
    with pytest.raises(ValueError):
        fake_models(metadata={"confidence_threshold": value})
    with pytest.raises(ValueError):
        KiwiSpacer(False, refiner_threshold=value)


def test_refiner_sees_punctuation_in_full_line_context(fake_models):
    spacer, refiner, _ = fake_models(lambda text: text.replace("가나", "가 나"))
    assert spacer.space("가나,다라!마바?") == "가 나,다라!마바?"
    assert refiner.calls == [("가나,다라!마바?", 1.3)]


def test_korean_period_without_space_reaches_refiner(fake_models):
    spacer, refiner, _ = fake_models(lambda text: text.replace("가나", "가 나"))
    assert spacer.space("가나.다라") == "가 나.다라"
    assert refiner.calls == [("가나.다라", 1.3)]


def test_manual_boundaries_are_restored_unless_normalizing(fake_models):
    spacer, _, _ = fake_models(lambda text: text.replace(" ", ""))
    assert spacer.space("가 나, 다 라") == "가 나, 다 라"
    assert spacer.space("가 나, 다 라", SpacingPreferences(existing_spaces="normalize")) == "가나,다라"


def test_disabled_and_phrase_preservation_never_call_refiner(fake_models):
    spacer, refiner, _ = fake_models(lambda text: "wrong")
    assert spacer.space("가나", SpacingPreferences(enabled=False)) == "가나"
    assert spacer.space("가나", preserve_phrase=True) == "가나"
    assert refiner.calls == []


def test_layout_protected_identifiers_and_edge_spaces_survive(fake_models):
    spacer, refiner, _ = fake_models(lambda text: text.replace("가나", "가 나"))
    source = "  가나!가나  가나\t가나\r\n가나 https://example.org/가나 foo@bar.test 가나 3.5kg\n"
    expected = "  가 나!가 나  가 나\t가 나\r\n가 나 https://example.org/가나 foo@bar.test 가 나 3.5kg\n"
    assert spacer.space(source) == expected
    assert all("https" not in text and "@" not in text and "3.5" not in text
               and "\t" not in text and "\n" not in text and "  " not in text
               for text, _ in refiner.calls)
    assert expected.replace(" ", "") == source.replace(" ", "")


def test_runtime_exception_keeps_baseline_and_only_error_type(fake_models):
    def fail(text):
        raise RuntimeError("PRIVATE: " + text)
    spacer, refiner, _ = fake_models(fail)
    assert spacer.space("비밀입력") == "비밀입력"
    assert spacer.space("다음입력") == "다음입력"
    assert len(refiner.calls) == 1
    assert spacer.refiner_info["loaded"] is False
    assert spacer.refiner_error == "RuntimeError"
    assert "비밀" not in json.dumps(spacer.refiner_info, ensure_ascii=False)


def test_later_segment_failure_rolls_entire_request_back_to_baseline(fake_models):
    def sometimes_fails(text):
        if text == "다라":
            raise RuntimeError("synthetic failure")
        return text.replace("가나", "가 나")
    spacer, refiner, _ = fake_models(sometimes_fails)
    assert spacer.space("가나\n다라") == "가나\n다라"
    assert len(refiner.calls) == 2
    assert spacer.refiner_status == "error"


def test_unchanged_unusual_baseline_layout_does_not_disable_model(fake_models):
    spacer, refiner, _ = fake_models()
    assert spacer._refine("가나", "가  나", SpacingPreferences()) == "가  나"
    assert spacer.refiner is refiner
    assert spacer.refiner_status == "loaded"
    assert spacer.space("다라") == "다라"
    assert len(refiner.calls) == 2


def test_removal_threshold_metadata_override_and_status(fake_models):
    spacer, _, _ = fake_models(metadata={"confidence_threshold": 1., "removal_threshold": 4.})
    assert spacer.refiner_threshold == 1.
    assert spacer.refiner_removal_threshold == 4.
    assert spacer.refiner_info["removal_threshold"] == 4.
    assert fake_models(metadata={"removal_threshold": 4.}, refiner_removal_threshold=6)[0].refiner_removal_threshold == 6.
    assert fake_models(metadata={"confidence_threshold": 2.5})[0].refiner_removal_threshold == 2.5


@pytest.mark.parametrize("value", [-1, float("nan"), float("inf"), True, "3"])
def test_invalid_removal_threshold_is_configuration_error(fake_models, value):
    with pytest.raises(ValueError):
        fake_models(metadata={"removal_threshold": value})
    with pytest.raises(ValueError):
        KiwiSpacer(False, refiner_removal_threshold=value)


@pytest.mark.parametrize("output", ["다른글자", " 가나", "가나 ", "가  나", "가\n나", None])
def test_invalid_model_output_falls_back_without_surface_changes(fake_models, output):
    spacer, _, _ = fake_models(lambda text: output)
    assert spacer.space("가나") == "가나"
    assert spacer.refiner_status == "error"
    assert spacer.refiner_error == "ValueError"


def test_registered_terms_are_reapplied_after_refiner(fake_models):
    spacer, refiner, _ = fake_models(lambda text: text.replace(" ", ""))
    prefs = SpacingPreferences(terms=[dict(category="custom", spaced="교양 교육",
                                          joined="교양교육", mode="separate")])
    assert spacer.space("교양교육", prefs) == "교양 교육"
    assert refiner.calls == [("교양 교육", 1.3)]
    prefs.terms[0]["mode"] = "join"
    refiner.predict = lambda text: text.replace("교양교육", "교양 교육")
    assert spacer.space("교양 교육", prefs) == "교양교육"


def test_auxiliary_preferences_override_model_with_real_analyzer():
    spacer = KiwiSpacer(False)
    spacer.refiner = FakeRefiner(lambda text: text.replace(" ", ""))
    spacer.refiner_threshold = 1.3
    assert spacer.space("읽어보다", SpacingPreferences(auxiliaries="separate")) == "읽어 보다"
    spacer.refiner.predict = lambda text: text.replace("읽어보다", "읽어 보다")
    assert spacer.space("읽어 보다", SpacingPreferences(auxiliaries="join")) == "읽어보다"


def test_work_limit_is_checked_before_inference(fake_models):
    spacer, refiner, _ = fake_models()
    with pytest.raises(ValueError):
        spacer.space("가" * 4097)
    assert refiner.calls == []
    assert spacer.space("가" * 4096) == "가" * 4096
    assert len(refiner.calls) == 1


@pytest.mark.parametrize("platform,parts", [
    ("darwin", ("Library", "Application Support")),
    ("linux", (".local", "share")),
])
def test_platform_default_path(monkeypatch, tmp_path, platform, parts):
    monkeypatch.setattr(release_spacing.sys, "platform", platform)
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    monkeypatch.delenv("XDG_DATA_HOME", raising=False)
    assert release_spacing._default_refiner_path() == tmp_path.joinpath(*parts, "HangulSpacing", "models", "boundary-refiner.npz")


def test_xdg_data_home(monkeypatch, tmp_path):
    monkeypatch.setattr(release_spacing.sys, "platform", "linux")
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    assert release_spacing._default_refiner_path() == tmp_path / "HangulSpacing/models/boundary-refiner.npz"


def test_service_ready_reports_non_sensitive_model_identity(monkeypatch, capsys):
    from hangul_ime import ime_service
    info = dict(loaded=True, status="loaded", model_sha256="a" * 64,
                confidence_threshold=1.3, error=None)
    monkeypatch.setattr(ime_service, "Service", lambda: SimpleNamespace(spacer=SimpleNamespace(refiner_info=info)))
    monkeypatch.setattr(ime_service.sys, "stdin", io.StringIO(""))
    assert ime_service.main() == 0
    assert json.loads(capsys.readouterr().out)["refiner"] == info


def test_service_reads_utf8_and_skips_a_leading_byte_order_mark(monkeypatch):
    # A .NET writer on a UTF-8 console (code page 65001) starts stdin with a BOM.
    from hangul_ime import ime_service

    class FakeService:
        spacer = SimpleNamespace(refiner_info=None)

        def handle(self, request):
            return {"text": request["text"]}

    requests = "".join(json.dumps({"id": n, "op": "space", "text": text}, ensure_ascii=False) + "\n"
                       for n, text in ((1, "가나다"), (2, "라마")))
    stdin = io.TextIOWrapper(io.BytesIO(("﻿" + requests).encode("utf-8")), encoding="cp949")
    written = io.BytesIO()
    stdout = io.TextIOWrapper(written, encoding="cp949")
    monkeypatch.setattr(ime_service, "Service", FakeService)
    monkeypatch.setattr(ime_service.sys, "stdin", stdin)
    monkeypatch.setattr(ime_service.sys, "stdout", stdout)
    assert ime_service.main() == 0
    stdout.flush()
    replies = [json.loads(line) for line in written.getvalue().decode("utf-8").splitlines()]
    assert replies[0]["op"] == "ready"
    assert replies[1:] == [{"text": "가나다", "id": 1, "ok": True}, {"text": "라마", "id": 2, "ok": True}]
