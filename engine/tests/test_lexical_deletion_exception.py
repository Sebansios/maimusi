"""Single verified morphemes can reject a false grammatical split."""
from types import SimpleNamespace
import pytest
from hangul_ime.refinement_policy import _single_lexical_alternative

def t(form, tag="NNG", start=0, end=None, identifier=1):
    return SimpleNamespace(form=form, tag=tag, start=start, end=len(form) if end is None else end, id=identifier)

@pytest.mark.parametrize("tag", ["NNG", "NNP", "NP", "MAG", "VV", "VA", "EC", "EF"])
def test_full_single_known_entry_is_lexical_evidence(tag):
    entry=t("가나", tag)
    assert _single_lexical_alternative("가 나", t("가",end=1), t("나",start=2,end=3), lambda s:[entry], lambda i:entry)

@pytest.mark.parametrize("tokens,entry", [
    ([],None), ([t("가나")],None), ([t("가나")],t("다른말")),
    ([t("가나")],t("가나", "NNP")), ([t("가나", "SW")],t("가나", "SW")),
    ([t("가나",end=1)],t("가나")), ([t("가나",start=1,end=2)],t("가나")),
    ([t("가",end=1),t("나",start=1,end=2)],t("가")),
    ([t("다른말",end=2)],t("다른말")),
])
def test_unknown_partial_or_multiple_tokens_are_not_lexical_evidence(tokens, entry):
    assert not _single_lexical_alternative("가 나", t("가",end=1), t("나",start=2,end=3), lambda s:tokens, lambda i:entry)
