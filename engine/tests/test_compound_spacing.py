"""Compound preference must never turn an arbitrary noun phrase into one word."""
from types import SimpleNamespace

import pytest

from hangul_ime.release_spacing import default_spacer, KiwiSpacer
from hangul_ime.spacing_policy import apply_policy
from hangul_ime.spacing_preferences import SpacingPreferences


@pytest.fixture(scope="module")
def lexical_spacer():
    return KiwiSpacer(False)


@pytest.mark.parametrize("source", [
    "학교 도서관 열람 시간 안내",
    "사과 배 포도 바나나",
    "게임 개발 회사 직원",
    "인터넷 사용자 경험",
    "친구 엄마 학교 선생님",
    "서울 대학 병원",
    "자료 처리 시스템을 읽어 보다",
    "새로운 자료 처리 방법을 읽어 보다",
    "컴퓨터 정보 처리 시스템 구축 사업",
    "방송 통신 대학교",
    "병원 치료비",
    "회의 자료 검토 결과 보고",
    "식사 시간 운동 시간 수면 시간",
    "지역 주민 의견 수렴 절차",
    "행정 기관 담당 직원 연락 방법",
    "국립 중앙 박물관 전시 안내",
    "한국 대학교 사범 대학 입학 안내",
    "건설 공사 시행 계획",
    "전자 우편 주소",
    "공무원 연금 개혁 방안",
])
def test_unregistered_noun_phrases_are_not_joined(source, lexical_spacer):
    spacer = default_spacer()
    prefs = SpacingPreferences(compound="join")
    assert spacer.space(source, prefs) == source
    # Normalizing existing spaces must not revive the blind NNG+NNG rule.
    prefs.existing_spaces = "normalize"
    assert spacer.space(source.replace(" ", ""), prefs) == lexical_spacer.space(
        source.replace(" ", ""), SpacingPreferences(existing_spaces="normalize"))


@pytest.mark.parametrize("source,expected", [
    ("사과 나무 그림", "사과나무 그림"),
    ("국어 사전을 찾아봤다", "국어사전을 찾아봤다"),
    ("데이터 베이스 구축 사업", "데이터베이스 구축 사업"),
    ("돼지 갈비 정식", "돼지갈비 정식"),
    ("손목 시계 수리 비용", "손목시계 수리 비용"),
    ("국제 기구 회의 일정", "국제기구 회의 일정"),
    ("사과 나무 국어 사전 데이터 베이스", "사과나무 국어사전 데이터베이스"),
    ("국어 사전 편찬 사업 담당 직원", "국어사전 편찬 사업 담당 직원"),
])
def test_only_lexical_compound_span_is_joined(source, expected):
    spacer = default_spacer()
    prefs = SpacingPreferences(compound="join")
    result = spacer.space(source, prefs)
    assert result == expected
    assert result.replace(" ", "") == source.replace(" ", "")
    assert spacer.space(result, prefs) == result
    # The default's explicit-space contract is independent of compound style.
    assert spacer.space(source, SpacingPreferences(compound="model")) == source


def test_layout_and_protected_text_are_opaque_to_compound_join():
    source = "국어  사전\t사과\n나무 https://example.org/국어사전 user@사과나무.test"
    assert default_spacer().space(source, SpacingPreferences(compound="join")) == source


def test_explicit_personal_phrase_can_join_beyond_lexical_compounds():
    source = "자료 처리 시스템을 읽어 보다"
    prefs = SpacingPreferences(compound="join", terms=[dict(
        category="compound", spaced="자료 처리 시스템", joined="자료처리시스템", mode="inherit")])
    assert default_spacer().space(source, prefs) == "자료처리시스템을 읽어 보다"


def test_explicit_term_can_keep_lexical_compound_separated():
    prefs = SpacingPreferences(compound="join", terms=[dict(
        category="compound", spaced="국어 사전", joined="국어사전", mode="separate")])
    assert default_spacer().space("국어 사전을 찾았다", prefs) == "국어 사전을 찾았다"


def test_proper_and_technical_preferences_are_independent():
    spacer = default_spacer()
    assert spacer.space("국립 중앙 박물관", SpacingPreferences(compound="join")) == "국립 중앙 박물관"
    assert spacer.space("국립 중앙 박물관", SpacingPreferences(compound="join", proper="join")) == "국립중앙박물관"
    assert spacer.space("교양 교육", SpacingPreferences(compound="join", technical="join")) == "교양교육"


def _token(form, start=0, *, tag="NNG", id=2):
    return SimpleNamespace(form=form, tag=tag, start=start, end=start + len(form), id=id)


def test_unknown_single_noun_analysis_is_not_dictionary_evidence():
    source = "쟝똘 꾸핑낑"

    def tokenize(text):
        if text == source:
            return [_token("쟝똘"), _token("꾸핑낑", 3)]
        return [_token(text)]  # An unknown-word fallback may emit one NNG.

    assert apply_policy(source, SpacingPreferences(compound="join"), tokenize,
                        lookup_morpheme=lambda _: _token("")) == source


def test_dictionary_lookup_is_required_and_fails_closed_when_absent():
    source = "사과 나무"
    kiwi = default_spacer().kiwi
    assert apply_policy(source, SpacingPreferences(compound="join"), kiwi.tokenize) == source


@pytest.mark.parametrize("separator", ["  ", "\t", "\n"])
def test_lexical_analysis_cannot_remove_layout_inside_one_token(separator):
    source = "사과" + separator + "나무"

    def tokenize(text):
        return [SimpleNamespace(form="사과나무", tag="NNG", start=0, end=len(text), id=10)]

    assert apply_policy(source, SpacingPreferences(compound="join"), tokenize,
                        lookup_morpheme=lambda _: _token("사과나무", id=10)) == source


def test_overlapping_lexical_pairs_do_not_form_an_unverified_chain():
    source = "가 나 다"
    lexicon = {10: "가나", 11: "나다"}

    def tokenize(text):
        if text == source:
            return [_token("가"), _token("나", 2), _token("다", 4)]
        for id, word in lexicon.items():
            if text == word:
                return [_token(word, id=id)]
        return [_token(char, i) for i, char in enumerate(text)]

    result = apply_policy(source, SpacingPreferences(compound="join"), tokenize,
                          lookup_morpheme=lambda id: _token(lexicon[id], id=id))
    assert result == "가나 다"
