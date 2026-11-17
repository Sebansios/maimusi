"""Policy dispatch spies; no external model, corpus, or personal path required."""
import pytest

from hangul_ime.release_spacing import KiwiSpacer
from hangul_ime.spacing_preferences import SpacingPreferences


class RecordingKiwi:
    def __init__(self):
        self.calls = []

    def space(self, text):
        self.calls.append(text)
        return text

    def tokenize(self, text, **kwargs):
        return []

    def morpheme(self, identifier):
        return None


class RecordingRefiner:
    def __init__(self):
        self.calls = []

    def refine(self, text, **kwargs):
        self.calls.append(text)
        return text


def make_spacer():
    # Skip model loading: these tests observe dispatch, not artifact loading.
    spacer = KiwiSpacer.__new__(KiwiSpacer)
    spacer.kiwi = RecordingKiwi()
    spacer.refiner = RecordingRefiner()
    spacer.refiner_status = "loaded"
    spacer.refiner_error = None
    spacer.refiner_sha256 = "synthetic"
    spacer.refiner_threshold = 1.3
    spacer.refiner_removal_threshold = 1.0
    return spacer


@pytest.mark.parametrize("compound", ["join", "separate"])
@pytest.mark.parametrize("spaces", ["preserve", "normalize"])
def test_explicit_compound_mode_bypasses_refiner_without_disabling_model(compound, spaces):
    spacer = make_spacer()
    health = dict(spacer.refiner_info)
    preferences = SpacingPreferences(compound=compound, existing_spaces=spaces)
    result = spacer.space("가 나,다 라", preferences)
    assert result == ("가 나,다 라" if spaces == "preserve" else "가나,다라")
    assert spacer.kiwi.calls == (["가 나", "다 라"] if spaces == "preserve" else ["가나", "다라"])
    assert spacer.refiner.calls == []
    assert spacer.refiner_info == health


def test_returning_to_model_policy_still_uses_the_loaded_refiner():
    spacer = make_spacer()
    model = spacer.refiner
    spacer.space("가 나", SpacingPreferences(compound="join"))
    assert model.calls == []
    spacer.space("가나", SpacingPreferences(compound="model"))
    assert model.calls == ["가나"]
    assert spacer.refiner is model and spacer.refiner_status == "loaded"


@pytest.mark.parametrize("preferences", [
    SpacingPreferences(auxiliaries="join"),
    SpacingPreferences(number_units="join"),
    SpacingPreferences(short_words="model"),
])
def test_other_style_preferences_do_not_silently_trigger_compound_bypass(preferences):
    spacer = make_spacer()
    spacer.space("가나", preferences)
    assert spacer.refiner.calls == ["가나"]


def test_default_model_input_is_independent_of_single_manual_spaces():
    spacer = make_spacer()
    spacer.kiwi.space = lambda text: text.replace("다라", "다 라")
    spacer.space("가나,다라")
    spacer.space("가 나,다라")
    assert spacer.refiner.calls == ["가나,다 라", "가나,다 라"]
