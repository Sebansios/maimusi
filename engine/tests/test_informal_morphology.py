"""Surface-preserving informal analysis and ordinary-language counterexamples."""
import pytest

from hangul_ime.release_spacing import default_spacer
from hangul_ime.spacing_preferences import SpacingPreferences


@pytest.mark.parametrize("source,expected", [
    ("니뭐하노", "니 뭐 하노"),
    ("지금뭐하는교", "지금 뭐 하는교"),
    ("밥먹었심더", "밥 먹었심더"),
    ("이거맛있당께", "이거 맛있당께"),
    ("내가그랬잖여", "내가 그랬잖여"),
    ("혼저옵서예", "혼저 옵서예"),
    ("밥단디챙겨묵으래이", "밥 단디 챙겨 묵으래이"),
    ("오늘장에같이갈텨", "오늘 장에 같이 갈 텨"),
    ("여그가어디랑가", "여그가 어디랑가"),
    ("아따무슨소리를그렇게한당가", "아따 무슨 소리를 그렇게 한당가"),
    ("밥먹었는디", "밥 먹었는디"),
    ("요즘현타가오네", "요즘 현타가 오네"),
    ("그건네뇌피셜이잖아", "그건 네 뇌피셜이잖아"),
    ("너완전겜알못이네", "너 완전 겜알못이네"),
    ("여기가바로편세권이지", "여기가 바로 편세권이지"),
    ("그거완전갑분싸였어", "그거 완전 갑분싸였어"),
    ("그거억까아니냐", "그거 억까 아니냐"),
    ("고마워용잘쓸게용", "고마워용 잘 쓸게용"),
    ("댓글에스포좀하지마", "댓글에 스포 좀 하지 마"),
])
def test_informal_boundaries_and_inflection(source, expected):
    spacer = default_spacer()
    result = spacer.space(source)
    assert result == expected
    assert result.replace(" ", "") == source
    assert spacer.space(result) == result


@pytest.mark.parametrize("source", [
    "이 개 웃기게 생겼다", "이 개 좋아하니", "그 개 슬프게 운다",
    "나랑 가자", "너랑 같이 간다", "친구랑 가끔 만난다",
    "해당 가격은 시장 가격이다", "주당 가격을 계산했다",
    "사람이 사는 디자인", "새로 사는 디자인 책이다",
    "그는 교수가 되었다", "네 가지 경우를 검토했다",
    "용을 그린 그림을 전시했다", "니켈 가격이 올랐다",
])
def test_ordinary_language_is_not_an_informal_suffix(source):
    spacer = default_spacer()
    assert spacer.space(source.replace(" ", "")) == source
    assert spacer.space(source) == source


@pytest.mark.parametrize("source", [
    "고마워 용 잘 쓸게용", "밥 먹었 심더", "현 타가 왔어",
    "단 디 챙겨 묵으래이", "혼 저 옵서예", "내 돈 내 산 후기",
])
def test_explicit_spaces_survive_informal_analysis(source):
    offset, expected = 0, set()
    for char in source:
        if char == " ":
            expected.add(offset)
        else:
            offset += 1
    result = default_spacer().space(source)
    offset, actual = 0, set()
    for char in result:
        if char == " ":
            actual.add(offset)
        else:
            offset += 1
    assert expected <= actual
    assert result.replace(" ", "") == source.replace(" ", "")
    assert default_spacer().space(source, SpacingPreferences(enabled=False)) == source
