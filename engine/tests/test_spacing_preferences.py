"""Normative examples, deliberately disallowed joins, and user-style isolation."""
from dataclasses import asdict
import json
import pytest
from hangul_ime.release_spacing import default_spacer
from hangul_ime.spacing_preferences import SpacingPreferences, load_spacing_preferences, save_spacing_preferences
from hangul_ime.settings import TypographySettings


@pytest.mark.parametrize("source,joined,separated", [
    ("읽어 보다", "읽어보다", "읽어 보다"),
    ("먹어 주었다", "먹어주었다", "먹어 주었다"),
    ("막아 냈다", "막아냈다", "막아 냈다"),
    ("먹어 버렸다", "먹어버렸다", "먹어 버렸다"),
    ("먹어 두었다", "먹어두었다", "먹어 두었다"),
    ("먹어 놓았다", "먹어놓았다", "먹어 놓았다"),
    ("바꾸어 주다", "바꾸어주다", "바꾸어 주다"),
    ("가르쳐 주다", "가르쳐주다", "가르쳐 주다"),
    ("먹여 주다", "먹여주다", "먹여 주다"),
    ("돌아가 버렸다", "돌아가 버렸다", "돌아가 버렸다"),
    ("먹고 있다", "먹고 있다", "먹고 있다"),
    ("먹고 싶다", "먹고 싶다", "먹고 싶다"),
    ("먹지 않았다", "먹지 않았다", "먹지 않았다"),
    ("읽어도 보았다", "읽어도 보았다", "읽어도 보았다"),
    ("공부해 보았다", "공부해 보았다", "공부해 보았다"),
    ("덤벼들어 보아라", "덤벼들어 보아라", "덤벼들어 보아라"),
    ("읽어 보고 싶다", "읽어보고 싶다", "읽어 보고 싶다"),
    ("먹어 보아 버렸다", "먹어보아 버렸다", "먹어 보아 버렸다"),
    ("할 만하다", "할만하다", "할 만하다"),
    ("올 듯하다", "올듯하다", "올 듯하다"),
    ("될 법하다", "될법하다", "될 법하다"),
    ("올 성싶다", "올성싶다", "올 성싶다"),
    ("잘 아는 척한다", "잘 아는척한다", "잘 아는 척한다"),
    ("올 듯도 하다", "올 듯도 하다", "올 듯도 하다"),
    ("도와드렸다", "도와드렸다", "도와드렸다"),
    ("지워진다", "지워진다", "지워진다"),
    ("먹고 싶어 하다", "먹고 싶어 하다", "먹고 싶어 하다"),
    ("10 개", "10개", "10 개"),
    ("2026년 9월 21일", "2026년 9월 21일", "2026 년 9 월 21 일"),
    ("두시 삼십분", "두시 삼십분", "두 시 삼십 분"),
    ("삼학년", "삼학년", "삼 학년"),
    ("열 살", "열 살", "열 살"),
    ("두 분", "두 분", "두 분"),
    ("좀 더 큰 이 새 차", "좀더 큰 이 새차", "좀 더 큰 이 새 차"),
    ("이 말 저 말", "이말 저말", "이 말 저 말"),
    ("물 한 병을", "물 한 병을", "물 한 병을"),
    ("할 수 있다", "할 수 있다", "할 수 있다"),
    ("만성골수성백혈병", "만성골수성백혈병", "만성 골수성 백혈병"),
    ("교양교육을", "교양교육을", "교양 교육을"),
    ("한국대학교사범대학", "한국대학교 사범대학", "한국 대학교 사범 대학"),
    ("국제기구", "국제기구", "국제기구"),
])
@pytest.mark.parametrize("preset", ["standard", "permitted"])
def test_rules(source, joined, separated, preset):
    spacer = default_spacer()
    prefs = SpacingPreferences().preset(preset)
    result = spacer.space(source, prefs)
    assert result == (joined if preset == "permitted" else separated)
    assert result.replace(" ", "") == source.replace(" ", "")
    assert spacer.space(result, prefs) == result


def test_auxiliary_category_applies_to_all_and_other_categories_are_independent():
    prefs = SpacingPreferences(auxiliaries="join", number_units="separate", date_units="join")
    assert default_spacer().space("읽어 보다 먹어 주다 10개 2026년", prefs) == "읽어보다 먹어주다 10 개 2026년"


@pytest.mark.parametrize("aux,nouns,expected", [
    ("join", "join", "자료 처리 시스템을 읽어보다"),
    ("join", "separate", "자료 처리 시스템을 읽어보다"),
    ("separate", "join", "자료 처리 시스템을 읽어 보다"),
    ("separate", "separate", "자료 처리 시스템을 읽어 보다"),
])
def test_auxiliary_style_is_independent_from_conservative_compound_style(aux, nouns, expected):
    prefs = SpacingPreferences(auxiliaries=aux, compound=nouns)
    assert prefs.terms == []
    assert default_spacer().space("자료 처리 시스템을 읽어 보다", prefs) == expected


def test_noun_style_does_not_join_particles_or_predicates():
    prefs = SpacingPreferences(compound="join")
    assert default_spacer().space("새로운 자료 처리 방법을 읽어 보다", prefs) == "새로운 자료 처리 방법을 읽어 보다"
    assert default_spacer().space("국제기구", SpacingPreferences(compound="separate")) == "국제기구"


def test_big_numerals():
    assert default_spacer().space("십이억삼천사백오십육만칠천팔백구십팔") == "십이억 삼천사백오십육만 칠천팔백구십팔"
    assert default_spacer().space("12억3456만7898") == "12억 3456만 7898"


@pytest.mark.parametrize("text", ["123 456", "10 20 30", "일 이 삼", "12억 3456만 7898 1000"])
def test_number_enumerations_are_not_merged(text):
    assert default_spacer().space(text) == text


def test_layout_urls_identifiers_and_characters_survive():
    text = "😀\n읽어  보다\t교양 교육 https://example.org/교양교육 foo@bar.test 2026-09-21 3.5kg ㄱ\r\n"
    result = default_spacer().space(text, SpacingPreferences().preset("permitted"))
    assert result == "😀\n읽어  보다\t교양교육 https://example.org/교양교육 foo@bar.test 2026-09-21 3.5kg ㄱ\r\n"


def test_disabled_and_existing_space_policy():
    spacer = default_spacer()
    text = "구 름 위 를"
    assert spacer.space(text, SpacingPreferences(enabled=False)) == text
    assert spacer.space(text, SpacingPreferences(existing_spaces="preserve")) == text
    assert spacer.space(text, SpacingPreferences(existing_spaces="normalize")) == "구름 위를"


def term(spaced="테스트 표현", joined="테스트표현", category="custom", mode="join"):
    return dict(spaced=spaced, joined=joined, category=category, mode=mode)


def test_registered_terms_particles_longest_and_no_substrings():
    prefs = SpacingPreferences(terms=[term(), term("테스트 표현 모음", "테스트표현 모음")])
    spacer = default_spacer()
    assert spacer.space("테스트 표현을", prefs) == "테스트표현을"
    assert spacer.space("테스트 표현 모음", prefs) == "테스트표현 모음"
    assert spacer.space("교육 기관차", SpacingPreferences(technical="join")) == "교육 기관차"


def test_person_category_requires_explicit_registration():
    prefs = SpacingPreferences(ambiguous_names="separate", terms=[term("남궁 억", "남궁억", "ambiguous_names", "inherit")])
    assert default_spacer().space("남궁억", prefs) == "남궁 억"


def test_custom_overrides_builtin_and_profile_isolation():
    prefs = SpacingPreferences(technical="join", terms=[term("교양 교육", "교양교육", "custom", "separate")])
    assert default_spacer().space("교양교육", prefs) == "교양 교육"
    assert default_spacer().space("교양교육", SpacingPreferences(technical="join")) == "교양교육"


@pytest.mark.parametrize("data", [
    {"enabled": 1}, {"auxiliaries": "bad"}, {"unknown": "join"},
    {"auxiliary_overrides": {"보": "join"}}, {"terms": "bad"},
    {"terms": [term(joined="다른말")]}, {"terms": [term(spaced="테스트  표현")]},
    {"terms": [term(mode="inherit")]}, {"terms": [term(), term()]},
    {"terms": [term(spaced="테스트\n표현")]}, {"terms": [term()] * 1001},
])
def test_bad_preferences_rejected(data):
    with pytest.raises((TypeError, ValueError)):
        SpacingPreferences.from_dict(data)


def test_export_import_and_future_file_is_preserved(tmp_path):
    prefs = SpacingPreferences(terms=[term()], auxiliaries="join")
    path = tmp_path / "spacing.json"
    save_spacing_preferences(path, prefs)
    assert load_spacing_preferences(path) == prefs
    data = json.loads(path.read_text(encoding="utf-8"))
    data["schema_version"] = 999
    path.write_text(json.dumps(data), encoding="utf-8")
    before = path.read_bytes()
    with pytest.raises(ValueError):
        save_spacing_preferences(path, prefs)
    assert path.read_bytes() == before


def test_old_settings_and_roundtrip():
    settings = TypographySettings.from_dict({"schema_version": 2, "latin_width": "full"})
    assert settings.spacing == SpacingPreferences()
    settings.spacing.terms = [term()]
    copy = TypographySettings.from_dict(settings.to_dict())
    assert copy == settings
    copy.spacing.terms[0]["mode"] = "separate"
    assert settings.spacing.terms[0]["mode"] == "join"
