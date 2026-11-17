"""사용자 단어와 손으로 고친 경계."""
import pytest

from hangul_ime.release_spacing import default_spacer
from hangul_ime.spacing_preferences import SpacingPreferences
from hangul_ime.user_spacing import apply_user, learn


@pytest.fixture(scope="module")
def spacer():
    return default_spacer()


def test_registered_word_is_never_split(spacer):
    source = "찰떡엔진은형태소분석에보정모델을더한것이다"
    plain = spacer.space(source)
    assert "찰떡 엔진" in plain or "찰떡엔진" in plain
    words = SpacingPreferences(words=["찰떡엔진"])
    assert spacer.space(source, words).startswith("찰떡엔진은 ")


def test_word_applies_only_at_word_start_with_particles():
    prefs = SpacingPreferences(words=["사과"])
    assert apply_user("회사 과장이 왔다", prefs) == "회사 과장이 왔다"
    assert apply_user("사 과를 먹었다", prefs) == "사과를 먹었다"
    assert apply_user("나 무엇을", SpacingPreferences(words=["나무"])) == "나 무엇을"


def test_learned_case_is_followed(spacer):
    prefs = SpacingPreferences(learned=[{"compact": "먹어버렸다", "spaced": "먹어 버렸다"}],
                               auxiliaries="join")
    assert spacer.space("다먹어버렸다", prefs).endswith("먹어 버렸다")


def test_learn_extracts_case_and_word(spacer):
    tokenize = spacer.kiwi.tokenize
    got = learn("찰떡 엔진은 형태소 분석에", "찰떡엔진은 형태소 분석에", tokenize)
    assert got["cases"] == [{"compact": "찰떡엔진은", "spaced": "찰떡엔진은"}]
    assert got["words"] == ["찰떡엔진"]
    split = learn("다 먹어버렸다", "다 먹어 버렸다", tokenize)
    assert split["cases"] == [{"compact": "먹어버렸다", "spaced": "먹어 버렸다"}]
    assert split["words"] == []
    assert learn("같은 글", "같은 글", tokenize) == {"cases": [], "words": []}
    assert learn("다른 글", "다른 말", tokenize) == {"cases": [], "words": []}


def test_learn_skips_addresses_paths_and_text_without_hangul(spacer):
    tokenize = spacer.kiwi.tokenize
    none = {"cases": [], "words": []}
    # 주소·메일·경로가 섞인 확정은 통째로 기억하지 않는다.
    assert learn("메일 은 a@b.kr 로", "메일은 a@b.kr 로", tokenize) == none
    assert learn("주소 는 https://sebansios.com", "주소는 https://sebansios.com", tokenize) == none
    assert learn("폴더 는 ~/문서 에", "폴더는 ~/문서 에", tokenize) == none
    # 한글이 없는 말(영문·숫자)은 기억하지 않는다.
    assert learn("Mac OS 13", "MacOS 13", tokenize) == none
    assert learn("12 34", "1234", tokenize) == none


def test_preferences_reject_bad_entries():
    with pytest.raises(ValueError):
        SpacingPreferences(words=["띄어 쓴 말"]).validate()
    with pytest.raises(ValueError):
        SpacingPreferences(learned=[{"compact": "가나", "spaced": "가 다"}]).validate()
