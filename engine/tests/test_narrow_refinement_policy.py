"""Public synthetic tokens: narrow grammar requires both contextual analyses."""
from types import SimpleNamespace

import pytest

from hangul_ime.refinement_policy import protect_refined_boundaries


def tok(tag, start, end, *, form="가", identifier=1):
    return SimpleNamespace(tag=tag, start=start, end=end, form=form, id=identifier)


def run(baseline, proposed, baseline_tokens, proposed_tokens):
    analyses = {baseline: baseline_tokens, proposed: proposed_tokens}
    return protect_refined_boundaries(baseline, proposed, lambda text: analyses.get(text, []), lambda ident: None)


@pytest.mark.parametrize("left,right", [
    ("NNG", "VV"), ("NNP", "VA"), ("NP", "VV"), ("NNB", "VX"),
    ("NR", "MAG"), ("NNG", "MM"), ("NNP", "NNB"), ("MM", "NNG"),
    ("MAG", "VV"), ("MAG", "NNG"), ("MM", "MAG"), ("ETM", "NNB"),
    ("JKS", "VV"), ("JKO", "VV"), ("JX", "VA"),
])
def test_required_grammatical_cut_survives_when_both_analyses_agree(left, right):
    assert run("가 나", "가나", [tok(left, 0, 1), tok(right, 2, 3)],
               [tok(left, 0, 1), tok(right, 1, 2)]) == "가 나"


@pytest.mark.parametrize("left,right", [
    ("NNG", "NNG"), ("NNG", "NNP"), ("NNP", "NNG"), ("NNP", "NNP"),
    ("NP", "NNG"), ("NR", "NNG"), ("NNB", "NNG"), ("VV", "EF"),
    ("ETM", "NNG"), ("JKS", "NNG"), ("SW", "NNG"), ("SL", "XSN"),
])
def test_plain_noun_runs_and_other_morphology_are_not_blanket_protected(left, right):
    assert run("가 나", "가나", [tok(left, 0, 1), tok(right, 2, 3)],
               [tok(left, 0, 1), tok(right, 1, 2)]) == "가나"


def test_baseline_hypothesis_without_proposal_corroboration_is_not_enough():
    assert run("가 나", "가나", [tok("NP", 0, 1), tok("VV", 2, 3)],
               [tok("NNG", 0, 2)]) == "가나"


def test_proposal_hypothesis_cannot_invent_a_baseline_grammatical_cut():
    assert run("가 나", "가나", [tok("NNG", 0, 1), tok("NNG", 2, 3)],
               [tok("NP", 0, 1), tok("VV", 1, 2)]) == "가나"


def test_corroboration_must_share_the_same_compact_character_offset():
    assert run("가 나라", "가나라", [tok("NP", 0, 1), tok("VV", 2, 4)],
               [tok("NP", 0, 2), tok("VV", 2, 3)]) == "가나라"


@pytest.mark.parametrize("baseline_tokens,proposed_tokens", [
    ([tok("NP", 0, 0), tok("VV", 2, 3)], [tok("NP", 0, 1), tok("VV", 1, 2)]),
    ([tok("NP", 0, 1), tok("VV", 2, 2)], [tok("NP", 0, 1), tok("VV", 1, 2)]),
    ([tok("NP", 0, 1), tok("VV", 2, 3)], [tok("NP", 0, 0), tok("VV", 1, 2)]),
    ([tok("NP", 0, 1), tok("VV", 2, 3)], [tok("NP", 0, 1), tok("VV", 1, 1)]),
    ([tok("NP", 0, 3), tok("VV", 2, 3)], [tok("NP", 0, 1), tok("VV", 1, 2)]),
    ([tok("NP", 0, 1), tok("VV", 2, 3)], [tok("NP", 0, 2), tok("VV", 1, 2)]),
    ([tok("NP", 0, 1), tok("VV", 2, 3)], [tok("NP", -1, 1), tok("VV", 1, 2)]),
    ([tok("NP", 0, 1), tok("VV", 2, 3)], [tok("NP", 0, 1), tok("VV", 1, 3)]),
])
def test_zero_width_overlap_and_out_of_range_tokens_are_not_evidence(baseline_tokens, proposed_tokens):
    assert run("가 나", "가나", baseline_tokens, proposed_tokens) == "가나"


def test_only_the_corroborated_cut_is_restored_in_a_multi_cut_proposal():
    assert run("가 나 다", "가나다", [tok("NP", 0, 1), tok("VV", 2, 3), tok("NNG", 4, 5)],
               [tok("NP", 0, 1), tok("VV", 1, 2), tok("NNG", 2, 3)]) == "가 나다"


def test_literal_jamo_attachment_still_uses_the_canonical_baseline():
    assert run("가ㅠㅠ 나", "가 ㅠ ㅠ나", [], []) == "가ㅠㅠ 나"


def test_exact_dictionary_noun_insertion_guard_is_unchanged():
    entry = tok("NNG", 0, 3, form="가나다")
    assert protect_refined_boundaries("가나다", "가 나다", lambda text: [entry],
                                      lambda ident: entry) == "가나다"


def test_unknown_noun_token_does_not_gain_dictionary_protection():
    entry = tok("NNG", 0, 3, form="가나다")
    assert protect_refined_boundaries("가나다", "가 나다", lambda text: [entry],
                                      lambda ident: None) == "가 나다"


def test_unchanged_surface_never_requires_analysis():
    def unexpected(value):
        raise AssertionError("no boundary edit should perform another lookup")
    assert protect_refined_boundaries("가 나", "가 나", unexpected, unexpected) == "가 나"


def test_non_space_character_changes_are_rejected():
    with pytest.raises(ValueError):
        run("가 나", "가다", [], [])
