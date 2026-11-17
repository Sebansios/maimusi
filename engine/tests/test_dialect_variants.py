"""Independent authored contexts for four sourced morphology registrations."""
import pytest
from hangul_ime.release_spacing import KiwiSpacer


@pytest.fixture(scope="module")
def spacer():
    return KiwiSpacer(False)


@pytest.mark.parametrize("source,expected", [
    ("내일학교에가십니꺼", "내일 학교에 가십니꺼"),
    ("언제오십니꺼", "언제 오십니꺼"),
    ("여그에서기다려라", "여그에서 기다려라"),
    ("저그가보인다", "저그가 보인다"),
    ("저그로갑시다", "저그로 갑시다"),
    ("여그말고저그에놓아라", "여그 말고 저그에 놓아라"),
    ("요것을받아라", "요것을 받아라"),
    ("요것이무엇입니까", "요것이 무엇입니까"),
    ("요것좀보세요", "요것 좀 보세요"),
    ("저것을가져오세요", "저것을 가져오세요"),
    ("어디가십니까", "어디 가십니까"),
    ("학교에가십니다", "학교에 가십니다"),
    ("보고서를검토하셨습니까", "보고서를 검토하셨습니까"),
    ("식사는하셨습니까", "식사는 하셨습니까"),
    ("이것은연구결과입니다", "이것은 연구 결과입니다"),
    ("저기는공원입니다", "저기는 공원입니다"),
    ("여기가도서관입니다", "여기가 도서관입니다"),
    ("그것은사실입니다", "그것은 사실입니다"),
    ("저그선수가경기에서승리했다", "저그 선수가 경기에서 승리했다"),
])
def test_forms_generalize_and_standard_prose_keeps_boundaries(spacer, source, expected):
    output = spacer.space(source)
    assert output == expected
    assert output.replace(" ", "") == source
    assert spacer.space(output) == output


def test_ending_uses_verb_honorific_and_final_ending_without_surface_rewrite(spacer):
    tokens = spacer.kiwi.tokenize("내일학교에가십니꺼")
    assert [(token.form, token.tag) for token in tokens[-3:]] == [
        ("가", "VV"), ("시", "EP"), ("ᆸ니꺼", "EF")]


@pytest.mark.parametrize("source,form", [
    ("여그에서기다려라", "여그"),
    ("저그로갑시다", "저그"),
    ("요것을받아라", "요것"),
])
def test_literal_pronoun_variants_have_pronoun_analysis(spacer, source, form):
    assert any(token.form == form and token.tag == "NP"
               for token in spacer.kiwi.tokenize(source))
