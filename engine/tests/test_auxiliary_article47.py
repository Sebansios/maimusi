"""한글 맞춤법 제47항(보조 용언): 띄어 씀이 원칙, 정해진 경우에만 붙여 씀 허용.

근거: 제47항 본문과 해설, 국립국어원 온라인가나다 답변.
- '-아/-어' 뒤 보조 용언과 '관형사형 + 듯·만·법·성·척 + 하다/싶다'는 붙여 쓸 수 있다.
- 앞말에 조사가 붙거나 중간에 조사가 들어가면 띄운다.
- 본용언이 합성어·파생어이고 활용형이 3음절 이상이면 띄운다(2음절이면 허용).
- 보조 용언이 거듭되면 앞의 것만 붙일 수 있다.
"""
import pytest

from hangul_ime.release_spacing import default_spacer
from hangul_ime.spacing_preferences import SpacingPreferences

# (원칙 표기, 허용 붙임 표기 — None이면 붙여 쓸 수 없음)
CASES = [
    ("불이 꺼져 간다", "불이 꺼져간다"),
    ("내 힘으로 막아 낸다", "내 힘으로 막아낸다"),
    ("어머니를 도와 드린다", "어머니를 도와드린다"),
    ("비가 올 듯하다", "비가 올듯하다"),
    ("그 일은 할 만하다", "그 일은 할만하다"),
    ("일이 될 법하다", "일이 될법하다"),
    ("비가 올 성싶다", "비가 올성싶다"),
    ("잘 아는 척한다", "잘 아는척한다"),
    ("구름 위에 서 있는데", "구름 위에 서있는데"),
    ("저기 앉아 있는 사람", "저기 앉아있는 사람"),
    ("문이 잡혀 있었다", "문이 잡혀있었다"),
    ("나가 버렸다", "나가버렸다"),
    ("빛나 보인다", "빛나보인다"),
    ("착해 보인다", "착해보인다"),
    ("슬퍼 보이는 얼굴", "슬퍼보이는 얼굴"),
    ("웃어 보였다", "웃어보였다"),
    ("반가워 보였다", "반가워보였다"),
    ("기다려 주었다", "기다려주었다"),
    ("가르쳐 주었다", "가르쳐주었다"),
    ("적어 둘 만하다", "적어둘 만하다"),
    ("읽어 볼 만하다", "읽어볼 만하다"),
    ("책을 읽어도 보고", None),
    ("네가 덤벼들어 보아라", None),
    ("강물에 떠내려가 버렸다", None),
    ("그가 올 듯도 하다", None),
    ("잘난 체를 한다", None),
    ("그릇을 깨뜨려 버렸다", None),
    ("공부해 보았다", None),
    ("열심히 노력해 왔다", None),
    ("정리해 두었다", None),
    ("아름다워 보인다", None),
    ("사랑스러워 보인다", None),
    ("새로워 보인다", None),
    ("반짝거려 보인다", None),
    ("먹고 있다", None),
    ("가지 않는다", None),
]


@pytest.fixture(scope="module")
def spacer():
    return default_spacer()


@pytest.mark.parametrize("rule,allowed", CASES)
def test_article47(spacer, rule, allowed):
    source = rule.replace(" ", "")
    assert spacer.space(source, SpacingPreferences(auxiliaries="separate")) == rule
    assert spacer.space(source, SpacingPreferences(auxiliaries="join")) == (allowed or rule)
