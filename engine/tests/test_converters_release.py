"""Release regression checks for converter data, boundaries and persistence."""
from datetime import date
from decimal import Decimal
import hashlib
import json
from pathlib import Path
from unittest.mock import patch

import pytest

from hangul_ime.advanced_transform import (
    DATA_DIR, DEFAULT_ERAS, UNIT_DEFINITIONS, DateConverter, EmojiConverter,
    EmojiRegistry, Era, HanjaConverter, JamoUnicodeConverter, UnitConverter,
    _bundled_hanja, default_word_transformer, hanja_gloss, load_eras,
)
from hangul_ime.conversion_types import WordConverter
from hangul_ime.converter_helpers import format_quantity
from hangul_ime.converter_pint import _unit_terms, _pint_registry, pint_candidates


@pytest.fixture(scope="module")
def emoji():
    return EmojiConverter()


@pytest.fixture(scope="module")
def hanja():
    return HanjaConverter()


@pytest.mark.parametrize("source,expected", [
    ("1톤", ["1 t", "1000 kg"]),
    ("-1톤", ["-1 t", "-1000 kg"]),
    ("−1톤", ["-1 t", "-1000 kg"]),
    ("(−1톤에만).", ["(-1 t에만).", "(-1000 kg에만)."]),
    ("1,234.5킬로그램", ["1234.5 kg", "1234500 g"]),
    ("1,234,567그램", ["1234567 g", "1234.567 kg"]),
    ("-.5 kg", ["-0.5 kg", "-500 g"]),
    ("+2킬로그램", ["2 kg", "2000 g"]),
    ("1e3그램", ["1000 g", "1 kg"]),
    ("1E-3킬로그램", ["0.001 kg", "1 g"]),
    ("2키로", ["2 km", "2000 m", "2 kg", "2000 g"]),
    ("1m²", ["1 m²", "0.3025 평"]),
    ("1세제곱미터", ["1 m³", "1000 L"]),
    ("1m/s", ["1 m/s", "3.6 km/h"]),
    ("1밀리초", ["1 ms", "0.001 s"]),
    ("1kWh", ["1 kWh", "3.6 MJ"]),
    ("1볼트", ["1 V", "1000 mV"]),
    ("1밀리암페어", ["1 mA", "0.001 A"]),
    ("1킬로옴", ["1 kΩ", "1000 Ω"]),
    ("1몰", ["1 mol", "1000 mmol"]),
    ("1g/cm³", ["1 g/cm³", "1000 kg/m³"]),
    ("8Mbps", ["8 Mbps", "1 MB/s"]),
    ("10%", ["10 %", "100 ‰"]),
    ("1B", ["1 B", "8 bit"]),
    ("1b", ["1 bit", "0.125 byte"]),
    ("1KiB", ["1 KiB", "0.000976562 MiB"]),
    ("3kg은", ["3 kg은", "3000 g은"]),
])
def test_units(source, expected):
    assert list(UnitConverter().candidates(source)) == expected


@pytest.mark.parametrize("source", [
    "1,2kg", "12,34kg", "1234,567kg", "1.234,56kg", "1..2kg", "1,234,kg",
    "1e999kg", "1e1000kg", "NaNkg", "infkg", "--1kg", "3kgfoo", "1mystery",
    "3그램사과", "1도서", "1바나나", "1일기", "1시계", "1Kfoo", "1cm2",
    "-300°C", "-1K", "-500°F",
])
def test_units_reject_invalid_or_partial_matches(source):
    assert list(UnitConverter().candidates(source)) == []


@pytest.mark.parametrize("source,expected", [
    ("-40℃", ["-40 °C", "-40 °F", "233.15 K"]),
    ("-40℉", ["-40 °F", "-40 °C", "233.15 K"]),
    ("0 K", ["0 K", "-273.15 °C", "-459.67 °F"]),
    ("100도", ["100 °C", "212 °F", "373.15 K"]),
    ("1°C는", ["1 °C는", "33.8 °F는", "274.15 K는"]),
    ("1도로", ["1 °C로", "33.8 °F로", "274.15 K로"]),
])
def test_temperature_signed_and_particles(source, expected):
    assert list(UnitConverter().candidates(source)) == expected


def test_tiny_quantities_not_rounded_to_zero():
    assert Decimal(format_quantity(Decimal("1e-12"))) == Decimal("1e-12")
    assert list(UnitConverter().candidates("0.000000001나노미터"))[1] != "0 μm"


def test_every_unit_alias_and_factor():
    # Every alias must preserve a matching definition, including ambiguous aliases.
    converter = UnitConverter()
    for definition in UNIT_DEFINITIONS:
        for alias in definition.aliases:
            assert f"2 {definition.symbol}" in converter.candidates("2" + alias), alias
        if definition.alternate_symbol:
            alternate = next((d for d in UNIT_DEFINITIONS if d.symbol == definition.alternate_symbol and d.dimension == definition.dimension), None)
            if alternate:
                assert definition.alternate_factor == pytest.approx(definition.to_base / alternate.to_base, rel=1e-8)


@pytest.mark.parametrize("source,expected", [
    ("1uL", ["1 µl", "0.000000001 m³"]),
    ("1MPa", ["1 MPa", "1000000 kg/m/s²"]),
    ("1millinewton", ["1 mN", "0.001 kg·m/s²"]),
    ("1picofarad", ["1 pF", "1e-12 A²·s⁴/kg/m²"]),
    ("1m/s^2", ["1 m/s²"]),
    ("1kg/m^3", ["1 kg/m³"]),
    ("1N*m", ["1 m·N", "1 kg·m²/s²"]),
    ("2N/(m*s)", ["2 N/m/s", "2 kg/s³"]),
    ("-9.81 m / s ** 2", ["-9.81 m/s²"]),
    ("1cm^2", ["1 cm²", "0.0001 m²"]),
    ("2s^-1", ["2 1/s"]),
    ("1,234.5uL", ["1234.5 µl", "0.000001234 m³"]),
    ("(1uL).", ["(1 µl).", "(0.000000001 m³)."]),
    ("-40degC", ["-40 °C", "233.15 K"]),
    ("-300delta_degC", ["-300 Δ°C", "-300 ΔK"]),
    ("0degR", ["0 °R", "0 K"]),
    ("-459.67degF", ["-459.67 °F", "0 K"]),
    ("-273.15celsius", ["-273.15 °C", "0 K"]),
])
def test_optional_pint_generalized_units(source, expected):
    pytest.importorskip("pint")
    assert list(UnitConverter().candidates(source)) == expected


@pytest.mark.parametrize("source", [
    "1cm2", "1m/s2", "1m/s^2junk", "1uLgarbage", "1MPa에만", "1uL사과",
    "1m + 1s", "1m;print(1)", "1__import__('os')", "1m.__class__", "1m[0]",
    "1m^100", "1m^-100", "1m^0", "1m^2.5", "1m^2^2", "1m//s", "1m/**s",
    "1m / 100s", "1m s", "1N/(m*s", "1m*s)", "1m\ns", "1m\ts",
    "-300degC", "-500fahrenheit", "-1kelvin", "-1millikelvin", "-1degR",
    "-459.670000000000000001degF", "-273.150000000000000001degC",
    "1degC/s", "1degF*kg", "1degC/degC", "1degC^2", "1celsius*kelvin^-1",
    "1" + "m*" * 8 + "m", "1" + "(" * 4 + "m" + ")" * 4,
    "1((m^12)^12)", "1" + "m" * 129, "1m" + ")" * 10000,
])
def test_pint_does_not_relax_invalid_input(source):
    assert list(UnitConverter().candidates(source)) == []


@pytest.mark.parametrize("expression", ["cm2", "m+1s", "m^1000000", "m^2^2", "__import__('os')", "m" * 129, "m\ns"])
def test_pint_syntax_rejected_before_optional_library(expression):
    with patch("hangul_ime.converter_pint._pint_registry", side_effect=AssertionError("invalid input reached Pint")):
        assert pint_candidates(Decimal(1), expression) == ()


def test_pint_unavailable_preserves_explicit_units():
    with patch("hangul_ime.converter_pint._pint_registry", return_value=None):
        converter = UnitConverter()
        assert list(converter.candidates("1uL")) == []
        assert list(converter.candidates("1톤")) == ["1 t", "1000 kg"]
        assert list(converter.candidates("1kPa")) == ["1 kPa", "1000 Pa"]
        assert list(converter.candidates("1nm")) == ["1 nm", "0.001 μm"]


def test_pint_quantity_expression_parser_is_not_used():
    pytest.importorskip("pint")
    registry = _pint_registry()
    with patch.object(registry, "parse_expression", side_effect=AssertionError("quantity parser used")):
        assert pint_candidates(Decimal(1), "kg/m^3") == ("1 kg/m³",)


def test_unit_expression_precedence_and_limits():
    assert _unit_terms("kg/m/s^2") == [("kg", 1), ("m", -1), ("s", -2)]
    assert _unit_terms("kg/(m*s^2)") == [("kg", 1), ("m", -1), ("s", -2)]
    assert _unit_terms("(m/s)^2") == [("m", 2), ("s", -2)]


def test_bundled_data_hashes_and_coverage():
    manifest = json.loads((DATA_DIR / "sources.json").read_text(encoding="utf-8"))
    for record in manifest["files"]:
        # A Windows checkout made before .gitattributes marked this data -text keeps
        # CRLF copies that git does not rewrite: delete both folders, then
        # `git checkout -- engine/hangul_ime/converter_data engine/hangul_ime/spacing_data`.
        assert hashlib.sha256((DATA_DIR / record["file"]).read_bytes()).hexdigest() == record["sha256"], \
            f"{record['file']} differs from sources.json (line endings?)"
    assert EmojiRegistry.bundled().sequence_count == 3953
    dictionary = _bundled_hanja()
    assert len(dictionary) == 222709
    assert sum(map(len, dictionary.values())) == 303494
    notice = (DATA_DIR / "LICENSE-libhangul-hanja.txt").read_text(encoding="utf-8")
    assert "Neither the name" in notice and "THIS SOFTWARE IS PROVIDED" in notice
    assert (DATA_DIR / "LICENSE-Unicode.txt").is_file()


@pytest.mark.parametrize("source,sequence", [
    ("grinning face", "😀"), ("man-technologist", "👨‍💻"),
    ("woman_technologist", "👩‍💻"), ("red heart", "❤️"),
    ("flag: South Korea", "🇰🇷"), ("keycap: 1", "1️⃣"),
    ("(man technologist)도", "(👨‍💻)도"),
    ("(A button (blood type))도", "(🅰️)도"),
    ("flag: Myanmar (Burma)도", "🇲🇲도"),
    ("사과", "🍎"), ("학교에만", "🏫에만"), ("(커피)!", "(☕)!"),
])
def test_emoji_direct_registry_lookup(emoji, source, sequence):
    assert sequence in emoji.candidates(source)


def test_all_official_emoji_sequences_reachable(emoji):
    official = EmojiRegistry.from_emoji_test(DATA_DIR / "emoji-test-17.0.txt")
    for record in official.records:
        assert record.sequence in emoji.lookup(record.name), record.name
        assert record.sequence in emoji.candidates(record.name), record.name
    assert any("\U0001f3fd" in r.sequence and "\u200d" in r.sequence for r in official.records)
    assert any("\U000e0067" in r.sequence for r in official.records)  # subdivision flags


@pytest.mark.parametrize("wrapper", ["annotations", "annotationsDerived", None])
def test_cldr_real_nested_structure_and_string_or_array(tmp_path, wrapper):
    entries = {"😀": {"tts": ["미소"], "default": ["웃음", "행복"]}, "👍": {"tts": "좋아", "default": "찬성"}}
    payload = {wrapper: {"identity": {"language": "ko"}, "annotations": entries}} if wrapper else entries
    path = tmp_path / "cldr.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    registry = EmojiRegistry.from_cldr_annotations(path)
    assert registry.lookup("미소") == ("😀",)
    assert registry.lookup("찬성") == ("👍",)
    assert registry.lookup("미") == ()


def test_explicit_emoji_override_and_missing_source(tmp_path):
    converter = EmojiConverter(mapping={"원하는단어": ["😀", "😀", "👍"]})
    assert list(converter.candidates("원하는단어")) == ["😀", "👍"]
    with pytest.raises(FileNotFoundError):
        EmojiConverter(emoji_test_path=tmp_path / "missing.txt")


@pytest.mark.parametrize("word,target", [
    ("국가", "國家"), ("국가의", "國家의"), ("자동차", "自動車"),
    ("자동차로", "自動車로"), ("학교에만", "學校에만"),
    ("학교에서부터는", "學校에서부터는"), ("(학교에만).", "(學校에만)."),
    ("사과", "謝過"),
])
def test_hanja_dictionary_known_longest_stem(hanja, word, target):
    assert target in hanja.candidates(word)


def test_user_longest_match_over_particle_analysis():
    converter = HanjaConverter(mapping={"학교에": "FULL", "학교": "STEM", "국가": "COUNTRY"})
    assert list(converter.candidates("학교에만")) == ["FULL만"]
    assert list(converter.candidates("국가")) == ["COUNTRY"]
    assert list(converter.candidates("학교banana")) == []


@pytest.mark.parametrize("extension", ["tsv", "json"])
def test_lexicon_save_load_save_preserves_edits(tmp_path, extension):
    first, second = tmp_path / f"first.{extension}", tmp_path / f"second.{extension}"
    converter = HanjaConverter(mapping={"검증단어": ["一", "二"], "구두점": ["a,b", 'x"y'], "entries": "記錄"})
    converter.remove_entry("학교")
    converter.remove_entry("국가")
    converter.save_lexicon(first)
    restored = HanjaConverter(lexicon_path=first)
    restored.save_lexicon(second)
    again = HanjaConverter(lexicon_path=second)
    assert again.user_mapping == converter.user_mapping
    assert again.disabled == converter.disabled
    assert list(again.candidates("학교에만")) == []
    assert list(again.candidates("국가")) == []
    assert list(again.candidates("검증단어")) == ["一", "二"]
    again.add_entry("학교", "NEW")
    assert list(again.candidates("학교에만")) == ["NEW에만"]
    again.remove_entry("검증단어")
    assert "검증단어" not in again.mapping


def test_legacy_tsv_import_survives_json_export(tmp_path):
    tsv = tmp_path / "import.tsv"
    tsv.write_text("# heading\n검증단어\t一,二\n검증단어\t三\n# disabled\t국가\n", encoding="utf-8")
    converter = HanjaConverter(lexicon_path=tsv)
    path = tmp_path / "export.json"
    converter.save_lexicon(path)
    loaded = HanjaConverter(lexicon_path=path)
    assert loaded.user_mapping["검증단어"] == ("一", "二", "三")
    assert "국가" in loaded.disabled


@pytest.mark.parametrize("payload", [[], {"x": 123}, {"x": []}, {"x": [None]}, {"entries": {"good": "一"}, "disabled": "학교"}, {"schema_version": 999, "entries": {}}])
def test_invalid_json_is_atomic(tmp_path, payload):
    converter = HanjaConverter(mapping={"검증단어": "一"})
    path = tmp_path / "bad.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    before = dict(converter.user_mapping)
    with pytest.raises(ValueError):
        converter.load_lexicon(path)
    assert converter.user_mapping == before


def test_invalid_tsv_does_not_partially_mutate(tmp_path):
    path = tmp_path / "bad.tsv"
    path.write_text("검증단어\t一\nmissing-tab\n", encoding="utf-8")
    converter = HanjaConverter()
    with pytest.raises(ValueError):
        converter.load_lexicon(path)
    assert "검증단어" not in converter.user_mapping


@pytest.mark.parametrize("source,year", [
    ("성종5년", 1474), ("성종 원년", 1470), ("성종즉위년", 1469),
    ("태조1년", 1392), ("태종1년", 1401), ("세종1년", 1419),
    ("세조1년", 1455), ("중종1년", 1506), ("인조1년", 1623),
    ("광해군1년", 1609), ("고종1년", 1864), ("순종1년", 1907),
    ("令和6年", 2024), ("令和元年", 2019), ("康熙20年", 1681),
    ("民國115年", 2026), ("昭和64年", 1989),
])
def test_era_years(source, year):
    assert list(DateConverter(lunar_backend=False).candidates(source)) == [f"{year}년"]


@pytest.mark.parametrize("source", [
    "성종0년", "성종26년", "태종19년", "광해군16년", "순종5년",
    "令和0年", "平成32年", "昭和65年", "康熙62年", "洪武32年",
    "성종5년1월1일", "康熙20年1月1日", "明治5年1月1日",
    "令和1年4月30日", "平成31年5月1日", "昭和64年1月8日",
    "大正1年7月29日", "明治45年7月30日", "令和6年13月1日", "令和6年2月30日",
    "2026년13월99일", "0000-01-01", "2026-02/03", "-2026-01-01", "2026-02-29",
])
def test_invalid_historical_and_gregorian_dates_produce_nothing(source):
    assert list(DateConverter(lunar_backend=False).candidates(source)) == []


@pytest.mark.parametrize("source,target", [
    ("令和元年5月1日", "2019-05-01"), ("平成31年4月30日", "2019-04-30"),
    ("昭和64年1月7日", "1989-01-07"), ("大正元年7月30日", "1912-07-30"),
    ("明治6年1月1日", "1873-01-01"), ("2024년2월29일", "2024-02-29"),
])
def test_valid_calendar_boundaries(source, target):
    assert target in DateConverter(lunar_backend=False).candidates(source)


def test_gregorian_output_never_fabricates_historical_lunar_dates():
    values = list(DateConverter(lunar_backend=False).candidates("1474-06-03"))
    assert not any(value.startswith(("성종", "홍무", "영락")) for value in values)


def test_today_live_between_calls_and_fixed_reference():
    converter = DateConverter(lunar_backend=False)
    with patch.object(DateConverter, "_today", return_value=date(2026, 12, 31)):
        assert next(converter.candidates("오늘")) == "2026-12-31"
    with patch.object(DateConverter, "_today", return_value=date(2027, 1, 1)):
        assert next(converter.candidates("오늘")) == "2027-01-01"
        assert next(DateConverter(date(2020, 1, 2), lunar_backend=False).candidates("오늘")) == "2020-01-02"


@pytest.mark.parametrize("source,target", [
    ("그저께", "2026-09-18"), ("오늘도", "2026-09-20도"),
    ("다음 주 월요일", "2026-09-21"), ("월요일", "2026-09-14"),
    ("지난주일요일", "2026-09-13"), ("다다음주수요일", "2026-09-30"),
    ("10일 전", "2026-09-10"), ("10일 뒤", "2026-09-30"),
    ("(내일).", "(2026-09-21)."),
])
def test_relative_weekday_and_particles(source, target):
    assert next(DateConverter(date(2026, 9, 20), lunar_backend=False).candidates(source)) == target


@pytest.mark.parametrize("reference,source", [(date.min, "어제"), (date.min, "지난주월요일"), (date.max, "내일"), (date.max, "다음주일요일"), (date.today(), "9999999일뒤"), (date.today(), "9" * 5000 + "일뒤")])
def test_date_overflow_is_safe(reference, source):
    assert list(DateConverter(reference, lunar_backend=False).candidates(source)) == []


def test_year_one_has_zero_padded_slash_variant():
    assert "0001/01/01" in DateConverter(lunar_backend=False).candidates("0001-01-01")


def test_lunar_real_backend_and_invalid_leap_month():
    converter = DateConverter(date(2024, 2, 10))
    assert converter.lunar_available
    assert "음력 2024년 1월 1일" in converter.candidates("오늘")
    assert "2024-02-10" in converter.candidates("음력 2024년 1월 1일")
    assert list(converter.candidates("음력 2024년 윤1월 1일")) == []
    assert "2023-03-22" in converter.candidates("음력 2023년 윤2월 1일")
    for invalid in ("음력 2024년 13월 1일", "음력 2024년 1월 31일", "음력 0999년 1월 1일", "음력 9999년 1월 1일"):
        assert list(converter.candidates(invalid)) == []


def test_optional_lunar_missing_backend_is_supported():
    with patch("hangul_ime.advanced_transform._optional_lunar_backend", return_value=None):
        converter = DateConverter(date(2024, 2, 10))
        assert not converter.lunar_available
        assert next(converter.candidates("오늘")) == "2024-02-10"
        assert list(converter.candidates("음력 2024년 1월 1일")) == []


def test_era_injection_roundtrip_and_bounds(tmp_path):
    path = tmp_path / "eras.json"
    path.write_text(json.dumps({"eras": [{"name": "테스트", "start_year": 2000, "first_year": 2001, "end_year": 2010, "calendar": "year-only"}]}), encoding="utf-8")
    converter = DateConverter(eras=load_eras(path), lunar_backend=False)
    assert list(converter.candidates("테스트1년")) == ["2001년"]
    assert list(converter.candidates("테스트11년")) == []
    with pytest.raises(ValueError):
        Era("invalid", 2000, end_year=1999)


def test_jamo_final_consonant_and_combining_mark():
    converter = JamoUnicodeConverter()
    assert "ㅎㅏㄴ" in converter.candidates("한")
    assert "ㄴ" in converter.candidates("ᆫ")
    assert list(converter.candidates("ㄱ"))[-1] == "U+3131"
    assert list(converter.candidates("\u0301"))[-1] == "U+0301"


def test_default_transformer_public_contract(tmp_path):
    class Custom(WordConverter):
        name = "사용자 변환"

        def candidates(self, word, context=None):
            if word == "검증단어":
                yield "custom"

    hanja_path = tmp_path / "user.tsv"
    hanja_path.write_text("검증단어\t一\n", encoding="utf-8")
    transformer = default_word_transformer(reference_date=date(2026, 9, 20), hanja_lexicon_path=hanja_path, lunar_backend=False, custom_converter=Custom())
    assert [c.name for c in transformer.converters] == ["기호·문자", "한자", "이모지", "단위", "날짜", "자모·유니코드", "사용자 변환"]
    assert [c.text for c in transformer.candidates("검증단어")] == ["검증단어", "一", "custom"]
    assert "1000 kg" in [c.text for c in transformer.candidates("1톤")]


def test_hanja_keeps_derivational_endings_in_hangul():
    from hangul_ime.advanced_transform import HanjaConverter
    h = HanjaConverter(mapping={"안녕": "安寧", "발전": "發展", "자연": "自然", "과학": "科學"})
    assert "安寧하다" in list(h.candidates("안녕하다"))
    assert "安寧하세요" in list(h.candidates("안녕하세요"))
    assert "安寧히" in list(h.candidates("안녕히"))
    assert "發展된" in list(h.candidates("발전된"))
    assert "自然스럽다" in list(h.candidates("자연스럽다"))
    assert "科學적인" in list(h.candidates("과학적인"))
    # Endings alone and native verbs with no noun stem stay unconverted.
    assert list(h.candidates("하다")) == []
    assert list(h.candidates("간다")) == []


def test_hanja_before_emoji():
    from hangul_ime.advanced_transform import default_word_transformer
    texts = [c.text for c in default_word_transformer(lunar_backend=False).candidates("학교에")[1:]]
    first_emoji = next(i for i, t in enumerate(texts) if not any("\u4e00" <= ch <= "\u9fff" for ch in t))
    assert texts[0] == "學校에" and first_emoji > 0


def _ranked(forms, word):
    return [(t, tier) for t, tier, _ in HanjaConverter(forms=forms).ranked_candidates(word)]


def test_hanja_tiers_follow_education_forms():
    strong = _ranked("education", "강하다")
    assert strong[0] == ("強하다", "top")
    # 고른 자형만 낸다(KS 자형 强은 내지 않는다).
    assert not any("强" in text for text, _ in strong)
    assert _ranked("education", "풍부하다")[0] == ("豐富하다", "top")
    assert _ranked("education", "비밀")[0] == ("祕密", "top")
    # Extension F 𮕩 is the education form of 衰; 頹 is not an education hanja.
    # 𮕩는 흔한 글꼴에 없어 KS 자형 衰도 대신 낸다.
    assert _ranked("education", "쇠퇴") == [
        ("𮕩退", "top"), ("衰退", "variant"), ("𮕩頹", "rare"), ("衰頹", "rare")]


def test_hanja_tiers_follow_ks_forms():
    assert _ranked("ks", "강하다")[0] == ("强하다", "top")
    assert not any("強" in text for text, _ in _ranked("ks", "강하다"))
    assert _ranked("ks", "풍부하다")[0] == ("豊富하다", "top")
    assert _ranked("ks", "비밀")[0] == ("秘密", "top")
    assert _ranked("ks", "쇠퇴") == [("衰退", "top"), ("衰頹", "rare")]


def test_candidate_tier_order():
    from hangul_ime.advanced_transform import default_word_transformer
    items = default_word_transformer(lunar_backend=False).candidates("강하다")[1:]
    notes = [c.converter for c in items]
    texts = [c.text for c in items]
    assert texts[0] == "強하다"
    first_emoji = notes.index("이모지") if "이모지" in notes else None
    # 출처에는 「한자」 대신 훈음과 자형·벽자 구분만 적는다.
    assert notes[0] == "강할 강"
    assert not any("KS 자형" in n for n in notes)
    rare = next(i for i, n in enumerate(notes) if "벽자" in n)
    assert rare > 0
    assert not any(n == "한자" or n.startswith("한자 ·") for n in notes)
    if first_emoji is not None:
        assert 0 < first_emoji < texts.index("江하다")


def test_invalid_hanja_forms_rejected():
    with pytest.raises(ValueError):
        HanjaConverter(forms="simplified")


def test_hanja_gloss():
    from hangul_ime.advanced_transform import hanja_gloss
    assert hanja_gloss("학교", "學校") == "배울 학, 학교 교"
    # 뜻이 여럿이면 첫 뜻, 소리가 빠진 항목은 소리를 붙인다.
    assert hanja_gloss("학교", "學敎") == "배울 학, 가르침 교"
    assert hanja_gloss("강", "強") == "강할 강"
    # 글자 수가 다르거나 훈음이 없는 글자가 있으면 비운다.
    assert hanja_gloss("학", "學校") == ""
    assert hanja_gloss("가나다라마", "加那多羅馬") == ""


def test_ha_verb_contractions_prefer_verb_hanja():
    # 위한·위해는 낱말 전체가 胃寒·危害와 같아 보여도 하다 동사(爲하다)로 읽는다.
    spans = {
        "위한": [(0, 2, "위하", "VV"), (1, 1, "ᆫ", "ETM")],
        "위해": [(0, 2, "위하", "VV"), (1, 1, "어", "EC")],
        "대한": [(0, 2, "대하", "VV"), (1, 1, "ᆫ", "ETM")],
        "인해": [(0, 2, "인하", "VV"), (1, 1, "어", "EC")],
        "피해": [(0, 2, "피해", "NNG")],
    }
    converter = HanjaConverter(analyzer=lambda text: spans.get(text, [(0, len(text), text, "NNG")]))
    first = lambda word: converter.ranked_candidates(word)[0]
    assert first("위한")[:2] == ("爲한", "top")
    assert first("위해")[:2] == ("爲해", "top")
    assert first("대한")[0] == "對한"
    assert first("인해")[0] == "因해"
    assert "胃寒" in [text for text, _, _ in converter.ranked_candidates("위한")]
    assert first("피해")[0] == "被害"
    # 분석기가 품사를 주지 않으면(예전 계약) 낱말 전체 한자어만 낸다.
    plain = HanjaConverter(analyzer=lambda text: [(0, len(text))])
    assert plain.ranked_candidates("위한")[0][0] == "胃寒"
    # 부사 꼬리에는 표를 쓰지 않는다(속히는 速히).
    assert HanjaConverter().ranked_candidates("속히")[0][0] == "速히"


def test_jamo_runs_offer_halfwidth_hangul():
    converter = JamoUnicodeConverter()
    assert converter.ranked_candidates("ㄱ")[0] == ("ﾡ", None, "반각")
    assert converter.ranked_candidates("ㅋㅋ") == [("ﾻﾻ", None, "반각")]
    assert ("ㄱㄴㅏ", None, "호환 자모") in converter.ranked_candidates("ﾡﾤￂ")
    assert converter.ranked_candidates("가ㄱ") == []


def test_hanja_gloss_initial_sound_law():
    assert hanja_gloss("이해", "理解") == "다스릴 리, 쪼갤 해"
    assert hanja_gloss("여자", "女子") == "계집 녀, 아들 자"
