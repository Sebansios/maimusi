"""Authored acceptance cases: literal text, spelling and slang are preserved.

Jamo/emoticon attachment is intentionally kept; these are spacing acceptance
examples, not a claim that informal spelling is normative Korean.
"""
import json
from pathlib import Path
import pytest
from hangul_ime.release_spacing import default_spacer
from hangul_ime.spacing_preferences import SpacingPreferences

CASES = json.loads(Path(__file__).with_name("spacing_cases.json").read_text(encoding="utf-8"))


@pytest.mark.parametrize("case", CASES, ids=lambda c: c["source"])
def test_reviewed_spacing(case):
    result = default_spacer().space(case["source"])
    assert result in case["accepted"]
    assert result.replace(" ", "") == case["source"].replace(" ", "")
    assert default_spacer().space(result) == result


@pytest.mark.parametrize("source", ["킹 받네", "숲 세권", "주린 이", "PC 방"])
def test_manual_boundaries_survive_dictionary(source):
    result = default_spacer().space(source)
    assert set(_boundaries(source)) <= set(_boundaries(result))
    assert default_spacer().space(source, SpacingPreferences(enabled=False)) == source


def _boundaries(text):
    position = 0
    for char in text:
        if char == " ":
            yield position
        else:
            position += 1


@pytest.mark.parametrize("source", [
    "오늘foo_bar값을봤어", "https://example.com/주린이?x=1",
    "C:\\Users\\public\\file.txt", "a+b@example.com", "v1.2.3", "3.5kg",
])
def test_protected_identifiers_are_opaque(source):
    assert default_spacer().space(source) == source
