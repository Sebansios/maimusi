from types import SimpleNamespace

import pytest

from hangul_ime.refinement_policy import protect_refined_boundaries


def token(form, *, tag="NNG", start=0, end=None, id=10):
    return SimpleNamespace(form=form, tag=tag, start=start,
                           end=start + len(form) if end is None else end, id=id)


@pytest.mark.parametrize("baseline,proposed,tag", [
    ("알잘딱깔센", "알잘딱 깔센", "NNG"),
    ("서울대학병원", "서울 대학병원", "NNP"),
])
def test_exact_dictionary_noun_interior_cannot_gain_spaces(baseline, proposed, tag):
    entry = token(baseline, tag=tag)
    assert protect_refined_boundaries(baseline, proposed, lambda text: [entry], lambda id: entry) == baseline


@pytest.mark.parametrize("entry", [None, token(""), token("다른말"), token("쟝똘꾸핑낑", tag="NNP")])
def test_unknown_or_mismatched_dictionary_entries_cannot_protect_whole_string(entry):
    baseline, proposed = "쟝똘꾸핑낑", "쟝똘 꾸핑낑"
    assert protect_refined_boundaries(baseline, proposed, lambda text: [token(text)], lambda id: entry) == proposed


@pytest.mark.parametrize("baseline,proposed,analysis", [
    ("사과 나무", "사 과 나무", token("사과나무", end=5)),
    ("사과\t나무", "사 과\t나무", token("사과나무", end=5)),
    ("세종시", "세 종시", token("세종", end=3)),
    ("기다림", "기 다림", token("기다림", tag="VV")),
])
def test_only_exact_space_free_noun_surfaces_are_eligible(baseline, proposed, analysis):
    def must_not_lookup(identifier):
        raise AssertionError("ineligible token must never be accepted as dictionary evidence")
    assert protect_refined_boundaries(baseline, proposed, lambda text: [analysis], must_not_lookup) == proposed


def test_only_interior_insertions_are_blocked():
    entry = token("나무", start=2)
    result = protect_refined_boundaries("새말나무그림", "새 말 나 무 그림", lambda text: [entry], lambda id: entry)
    assert result == "새 말 나무 그림"


@pytest.mark.parametrize("baseline,proposed", [
    ("슬퍼ㅠㅠ오늘", "슬퍼ㅠ ㅠ 오늘"),
    ("슬퍼 ㅠㅠ 오늘", "슬퍼ㅠㅠ오늘"),
    ("간나", "가 ᆫ 나"),
])
def test_jamo_neighbors_keep_baseline_boundaries_in_both_directions(baseline, proposed):
    assert protect_refined_boundaries(baseline, proposed, lambda text: [], lambda id: None) == baseline


def test_unchanged_result_never_needs_analysis():
    def unused(value):
        raise AssertionError("no edit requires no lookup")
    assert protect_refined_boundaries("가 나", "가 나", unused, unused) == "가 나"


def test_character_change_is_rejected():
    with pytest.raises(ValueError):
        protect_refined_boundaries("가나", "가다", lambda text: [], lambda id: None)
