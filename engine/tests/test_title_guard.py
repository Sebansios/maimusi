"""Public synthetic linguistic contracts; no learned model or corpus is read."""
from dataclasses import dataclass

import pytest

from hangul_ime.title_guard import TITLE_NOUNS, title_deletion_boundaries


@dataclass(frozen=True)
class Token:
    form: str
    tag: str
    start: int
    end: int


def tokens(text, parts):
    result, cursor = [], 0
    for form, tag in parts:
        start = text.index(form, cursor)
        cursor = start + len(form)
        result.append(Token(form, tag, start, cursor))
    return result


def check(baseline, proposed, parts, expected, proposed_parts=None):
    original = tokens(baseline, parts)
    candidate = tokens(proposed, parts if proposed_parts is None else proposed_parts)
    assert title_deletion_boundaries(baseline, proposed, original, candidate) == expected


@pytest.mark.parametrize("name", ["유", "김", "남궁", "김민수", "홍길동"])
@pytest.mark.parametrize("title", sorted(TITLE_NOUNS))
def test_name_or_surname_followed_by_title(name, title):
    check(f"{name} {title}은", f"{name}{title}은",
          [(name, "NNP"), (title, "NNG"), ("은", "JX")], {len(name)})


@pytest.mark.parametrize("suffix,parts", [
    ("", []), ("님", [("님", "XSN")]), ("께", [("께", "JKB")]),
    ("님께서는", [("님", "XSN"), ("께서", "JKS"), ("는", "JX")]),
    ("님은", [("님", "XSN"), ("은", "JX")]),
    ("이다", [("이", "VCP"), ("다", "EF")]),
])
def test_only_honorific_and_particle_suffixes_are_in_scope(suffix, parts):
    expected = set() if suffix == "이다" else {3}
    check("김민수 교수" + suffix, "김민수교수" + suffix,
          [("김민수", "NNP"), ("교수", "NNG")] + parts, expected)


@pytest.mark.parametrize("ending", [".", ",", "!", "?", "…", " ", "\n", "\t"])
def test_word_end_including_punctuation(ending):
    name = "유"
    check(f"{name} 의원{ending}", f"{name}의원{ending}",
          [(name, "NNP"), ("의원", "NNG")], {len(name)})


@pytest.mark.parametrize("left,left_tag,right,right_tag", [
    ("시내", "NNG", "버스", "NNG"), ("서울", "NNP", "버스", "NNG"),
    ("물리학", "NNG", "박사", "NNG"), ("김밥", "NNG", "박사", "NNG"),
    ("국회", "NNG", "의원", "NNG"), ("전", "MM", "의원", "NNG"),
    ("김", "NNP", "씨", "NNB"), ("김", "NNP", "군", "NNB"),
    ("박", "NNP", "양", "NNB"), ("김", "NNP", "님", "XSN"),
    ("유", "NNP", "의원", "NNP"),
])
def test_non_title_or_non_proper_name_relations_remain_unprotected(left, left_tag, right, right_tag):
    check(f"{left} {right}", left + right, [(left, left_tag), (right, right_tag)], set())


@pytest.mark.parametrize("title,tail,tail_tag", [
    ("교수", "법", "NNG"), ("박사", "학위", "NNG"),
    ("의원", "실", "NNG"), ("의원", "들", "XSN"),
])
def test_title_substring_of_a_larger_nominal_word_is_not_a_title_use(title, tail, tail_tag):
    check(f"신 {title}{tail}", f"신{title}{tail}",
          [("신", "NNP"), (title, "NNG"), (tail, tail_tag)], set())


def test_same_exact_spans_must_be_supported_by_the_proposal_analysis():
    check("유 의원은", "유의원은", [("유", "NNP"), ("의원", "NNG"), ("은", "JX")], set(),
          [("유의원", "NNP"), ("은", "JX")])
    check("유 의원은", "유의원은", [("유", "NNP"), ("의원", "NNG"), ("은", "JX")], set(),
          [("유", "NNG"), ("의원", "NNG"), ("은", "JX")])


def test_does_not_add_new_boundaries_or_change_an_already_preserved_cut():
    parts = [("유", "NNP"), ("의원", "NNG"), ("은", "JX")]
    check("유의원은", "유의원은", parts, set())
    check("유의원은", "유 의원은", parts, set())
    check("유 의원은", "유 의원은", parts, set())


def test_multiple_spaces_are_not_treated_as_an_editable_single_boundary():
    check("유  의원은", "유의원은", [("유", "NNP"), ("의원", "NNG"), ("은", "JX")], set())


def test_only_title_cut_is_returned_when_other_model_boundaries_change():
    check("오늘 유 의원은 왔다", "오 늘 유의원은왔다",
          [("오늘", "NNG"), ("유", "NNP"), ("의원", "NNG"), ("은", "JX"), ("왔", "VV"), ("다", "EF")],
          set(),
          [("오", "NNG"), ("늘", "NNG"), ("유", "NNP"), ("의원", "NNG"), ("은", "JX"), ("왔", "VV"), ("다", "EF")])
    # Above, the proposal merges a predicate into the title's word: no tail corroboration.
    baseline = "오늘 유 의원은 왔다"
    proposed = "오늘유의원은 왔다"
    parts = [("오늘", "NNG"), ("유", "NNP"), ("의원", "NNG"), ("은", "JX"), ("왔", "VV"), ("다", "EF")]
    check(baseline, proposed, parts, {3})


@pytest.mark.parametrize("bad", [
    Token("유", "NNP", -1, 0), Token("유", "NNP", 0, 0),
    Token("유", "NNP", 0, 2), Token("김", "NNP", 0, 1),
])
def test_invalid_or_nonliteral_name_tokens_do_not_guard(bad):
    baseline = [bad, Token("의원", "NNG", 2, 4)]
    proposed = [Token("유", "NNP", 0, 1), Token("의원", "NNG", 1, 3)]
    assert title_deletion_boundaries("유 의원", "유의원", baseline, proposed) == set()


def test_surface_changes_are_rejected_instead_of_projecting_wrong_offsets():
    with pytest.raises(ValueError, match="identical non-space"):
        title_deletion_boundaries("유 의원", "김의원", [], [])


def test_zero_length_and_overlapping_proposal_tokens_do_not_guard():
    baseline = [Token("유", "NNP", 0, 1), Token("의원", "NNG", 2, 4)]
    for proposal in [
        [Token("유", "NNP", 0, 1), Token("의원", "NNG", 1, 1)],
        [Token("유의", "NNP", 0, 2), Token("의원", "NNG", 1, 3)],
    ]:
        assert title_deletion_boundaries("유 의원", "유의원", baseline, proposal) == set()


def test_repeated_names_match_by_raw_span_and_only_deleted_cuts_are_returned():
    check("유 의원, 유 의원", "유의원, 유 의원",
          [("유", "NNP"), ("의원", "NNG"), (",", "SP"), ("유", "NNP"), ("의원", "NNG")], {1})


def test_clinic_homonym_is_an_explicit_limit_of_pos_only_evidence():
    # 의원/醫院 has exactly the same public Kiwi POS/form as 의원/議員.
    # This test records what the guard does; it does NOT certify that this
    # clinic-name boundary is normatively mandatory or that NNP means person.
    check("유 의원에서", "유의원에서", [("유", "NNP"), ("의원", "NNG"), ("에서", "JKB")], {1})
