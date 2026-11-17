"""Partial-space regression classes derived only from authored development data.

This module is ready to copy into engine/tests after candidate selection. It
uses the existing accepted alternatives as the authority and exercises the
actual configured spacer, including a learned model when its path is set.
"""
from pathlib import Path
import json

import pytest
from hangul_ime.release_spacing import KiwiSpacer
from hangul_ime.spacing_preferences import SpacingPreferences


@pytest.fixture(scope="module")
def partial_spacer():
    return KiwiSpacer()


# Keep one or two examples per grammatical relation, plus ordinary controls.
# Strings are partial boundary subsets of the cited public authored references.
CASES = [
    ("spacing_cases.json", 15, "너 뭐하냐ㅋㅋ나집가는중", "pronoun-verb-with-jamo"),
    ("spacing_cases.json", 17, "넘 슬퍼ㅠㅠ오늘못감", "adverb-verb"),
    ("spacing_cases.json", 30, "그란에 이름을적었다", "determiner-noun"),
    ("informal_development.json", 26, "그건 좀에바인듯", "adnominal-bound-noun"),
    ("informal_development.json", 37, "그건 누가봐도답정너야", "subject-particle-verb"),
    ("compound_cases.json", 2, "사과 배포도바나나", "separate-noun-list"),
    ("compound_cases.json", 6, "서울 대학병원", "proper-noun-context"),
    ("compound_cases.json", 16, "국립 중앙박물관전시안내", "proper-noun-context-following-prose"),
    ("spacing_cases.json", 3, "오늘밥 먹었어", "ordinary-noun-verb-control"),
    ("spacing_cases.json", 2, "할수 있잖아", "bound-noun-control"),
    ("spacing_cases.json", 5, "나 지금집가는중이야", "ongoing-predicate-control"),
    ("spacing_cases.json", 4, "이거진짜 괜찮네", "adverb-control"),
    ("spacing_cases.json", 14, "축알못이라 잘몰라", "literal-lexicon-control"),
    ("compound_cases.json", 7, "자료처리 시스템을읽어보다", "noun-phrase-and-auxiliary-policy"),
]


@pytest.mark.parametrize("filename,index,source,relation", CASES,
                         ids=[case[3] for case in CASES])
def test_partial_spaces_do_not_disable_missing_word_boundaries(
        partial_spacer, filename, index, source, relation):
    references = json.loads((Path(__file__).parent / filename).read_text(encoding="utf-8"))[index - 1]["accepted"]
    preferences = SpacingPreferences(compound="join" if filename == "compound_cases.json" else "model")
    assert all(source.replace(" ", "") == reference.replace(" ", "") for reference in references)
    result = partial_spacer.space(source, preferences)
    assert result in references
    assert result.replace(" ", "") == source.replace(" ", "")
    assert partial_spacer.space(result, preferences) == result
