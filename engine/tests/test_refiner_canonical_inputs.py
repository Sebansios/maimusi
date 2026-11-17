"""Canonical model inputs, manual layout, and rollback on synthetic text only.

Reuse the existing fake Kiwi/refiner fixture. These tests never load learned
weights or corpus files, and run against whichever hangul_ime is on PYTHONPATH.
"""
import pytest

from hangul_ime.release_spacing import KiwiSpacer
from hangul_ime.spacing_preferences import SpacingPreferences
from test_refiner_integration import fake_models  # noqa: F401; shared pytest fixture


@pytest.mark.parametrize("raw,first,feedback,manual,guarded", [
    ("가나,다라", "가나 ,다라", "가나 , 다라", "가 나 , 다 라", "가나 ,다라"),
    ("가나ㅋㅋ다라", "가나 ㅋㅋ다라", "가나 ㅋㅋ 다라", "가 나 ㅋㅋ 다 라", "가나ㅋㅋ다라"),
])
def test_punctuation_and_jamo_spaces_never_feed_back_into_the_model(
        fake_models, raw, first, feedback, manual, guarded):
    # This model adds another space only if its previous output leaks back
    # into the next baseline. A canonical baseline produces `first` before
    # the literal-jamo guard; manually typed spaces are still restored.
    outputs = {raw: first, first: feedback}
    spacer, refiner, _ = fake_models(lambda text: outputs.get(text, text))
    assert spacer.space(raw) == guarded
    assert spacer.space(guarded) == guarded
    assert spacer.space(manual) == manual
    assert [text for text, _ in refiner.calls] == [raw] * (2 if " " not in guarded else 1)


def test_noop_model_still_restores_manual_spaces_unless_normalizing(fake_models):
    spacer, refiner, _ = fake_models()
    source = " 가 나 , 다 라 "
    assert spacer.space(source) == source
    assert spacer.space(source, SpacingPreferences(existing_spaces="normalize")) == " 가나,다라 "
    # Edge spaces belong to the outer layout; interior manual spaces belong
    # to the final overlay, even when the model returns its input unchanged.
    assert [text for text, _ in refiner.calls] == ["가나,다라"]


def test_original_layout_and_protected_spans_survive_normalization(fake_models):
    spacer, refiner, _ = fake_models(lambda text: text.replace(" ", ""))
    source = ("  가 나  다 라\t마 바\r\n사 아 https://example.org/가나 "
              "foo@bar.test /tmp/가나.txt\n자 차 3.5kg ")
    expected = ("  가나  다라\t마바\r\n사아 https://example.org/가나 "
                "foo@bar.test /tmp/가나.txt\n자차 3.5kg ")
    prefs = SpacingPreferences(existing_spaces="normalize")
    assert spacer.space(source, prefs) == expected
    assert spacer.space(expected, prefs) == expected
    assert [text for text, _ in refiner.calls] == ["가나", "다라", "마바", "사아", "자차"] * 2


def test_only_generated_baseline_edge_and_repeated_spaces_are_cleaned(fake_models):
    spacer, refiner, _ = fake_models()
    spacer.kiwi.space = lambda text: "  " + text.replace("가나", "가  나") + "   "
    source, expected = " 가나  다라 ", " 가 나  다라 "
    assert spacer.space(source) == expected
    assert spacer.space(expected) == expected
    assert [text for text, _ in refiner.calls] == ["가 나", "다라"] * 2
    assert spacer.refiner is refiner and spacer.refiner_status == "loaded"


@pytest.mark.parametrize("mode,source,model_output,expected", [
    ("join", "교양 교육", "교양 교육", "교양교육"),
    ("separate", "교양교육", "교양교육", "교양 교육"),
])
def test_explicit_term_choice_overrides_model_and_manual_overlay_on_every_pass(
        fake_models, mode, source, model_output, expected):
    spacer, refiner, _ = fake_models(lambda text: model_output)
    prefs = SpacingPreferences(terms=[dict(category="custom", spaced="교양 교육",
                                          joined="교양교육", mode=mode)])
    assert spacer.space(source, prefs) == expected
    assert spacer.space(expected, prefs) == expected
    # Policy applies to both the canonical baseline and the final result.
    assert [text for text, _ in refiner.calls] == [expected] * (2 if mode == "join" else 1)


def test_middle_segment_failure_recomputes_entire_original_input_without_model(fake_models):
    def predict(text):
        if text.replace(" ", "") == "라마바":
            raise RuntimeError("synthetic model failure")
        return text.replace("가나다", "가 나 다")

    spacer, refiner, _ = fake_models(predict)
    kiwi_inputs = []

    def remember(text):
        kiwi_inputs.append(text)
        return text.replace("나다", "나 다").replace("마바", "마 바").replace("아자", "아 자")

    spacer.kiwi.space = remember
    source = "가 나다\t라 마바\n사 아자"
    assert spacer.space(source) == "가 나 다\t라 마 바\n사 아 자"
    assert [text for text, _ in refiner.calls] == ["가나 다", "라마 바"]
    assert kiwi_inputs[-3:] == ["가 나다", "라 마바", "사 아자"]
    assert spacer.refiner is None and spacer.refiner_status == "error"
    assert spacer.refiner_error == "RuntimeError"
    assert spacer.space("차 카타") == "차 카타"
    assert len(refiner.calls) == 2


def test_model_bypass_paths_keep_legacy_input_and_never_canonicalize(fake_models):
    spacer, refiner, _ = fake_models(lambda text: "unexpected model call")
    source = "가 나 , 다 라"
    assert spacer.space(source, preserve_phrase=True) == source
    assert spacer.space(source, SpacingPreferences(enabled=False)) == source
    assert spacer.space("hello world") == "hello world"
    assert refiner.calls == []
    legacy = KiwiSpacer(False)
    kiwi_inputs = []

    def remember(text):
        kiwi_inputs.append(text)
        return text

    legacy.kiwi.space = remember
    assert legacy.space(source) == source
    assert kiwi_inputs == ["가 나", "다 라"]


def test_accepted_manual_wording_skips_a_failing_model_and_stays_healthy(fake_models):
    def fail(text):
        raise RuntimeError("must not run on accepted manual wording")
    spacer, refiner, _ = fake_models(fail)
    health = dict(spacer.refiner_info)
    assert spacer.space("가 나, 다 라") == "가 나, 다 라"
    assert refiner.calls == []
    assert spacer.refiner_info == health


def test_partial_manual_wording_still_reaches_canonical_model(fake_models):
    spacer, refiner, _ = fake_models()
    spacer.kiwi.space = lambda text: text.replace("다라", "다 라")
    assert spacer.space("가 나다라") == "가 나다 라"
    assert [text for text, _ in refiner.calls] == ["가나다 라"]
    assert spacer.space("가 나다 라") == "가 나다 라"
    assert len(refiner.calls) == 1
