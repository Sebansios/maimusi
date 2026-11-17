import os
import sys
import tempfile
import unittest
from datetime import date

HERE = os.path.dirname(__file__)
sys.path.insert(0, os.path.join(HERE, ".."))
from hangul_ime import (  # noqa: E402
    DateConverter,
    EmojiConverter,
    EmojiRegistry,
    HanjaConverter,
    ImeEngine,
    JamoUnicodeConverter,
    LearningStore,
    SETTINGS_FORMAT_VERSION,
    NgramViterbiSpacer,
    SpacingModel,
    CustomConversionRegistry,
    SettingsStore,
    TypographySettings,
    UnitConverter,
    WordTransformSession,
    WordTransformer,
)


MODEL = os.path.join(HERE, "..", "data", "spacing_model.json")


class TestConverters(unittest.TestCase):
    def test_hanja_keeps_particle_in_hangul(self):
        values = list(HanjaConverter().candidates("학교에"))
        self.assertIn("學校에", values)
        self.assertNotIn("學校", values)
        self.assertIn("學校에만", list(HanjaConverter().candidates("학교에만")))

    def test_unit_conversion_has_primary_and_adjacent_unit(self):
        values = list(UnitConverter().candidates("3킬로그램"))
        self.assertEqual(values, ["3 kg", "3000 g"])

    def test_date_conversion_is_deterministic_with_reference_date(self):
        converter = DateConverter(date(2026, 9, 20))
        values = list(converter.candidates("오늘"))
        self.assertEqual(values[:2], ["2026-09-20", "2026/09/20"])
        self.assertTrue(any("일요일" in value for value in values))
        self.assertEqual(list(converter.candidates("2026년13월99일")), [])

    def test_colloquial_units_cover_ambiguous_spoken_forms(self):
        converter = UnitConverter()
        self.assertEqual(
            list(converter.candidates("2키로")),
            ["2 km", "2000 m", "2 kg", "2000 g"],
        )
        self.assertIn("3 GB", list(converter.candidates("3기가")))
        self.assertIn("10 mm", list(converter.candidates("10미리")))
        self.assertIn("10 mL", list(converter.candidates("10미리")))
        self.assertIn("5 cm", list(converter.candidates("5센치")))
        self.assertIn("212 °F", list(converter.candidates("100도")))
        self.assertIn("27.777777778 m/s", list(converter.candidates("100시속")))

    def test_hanja_lexicon_can_be_injected(self):
        converter = HanjaConverter(mapping={"사전": "辭典"})
        self.assertEqual(list(converter.candidates("사전에")), ["辭典에"])
        self.assertIn("seed", converter.dictionary_source)

    def test_emoji_registry_reads_sequences_and_names(self):
        # Windows cannot reopen an open NamedTemporaryFile; a plain file can be.
        with tempfile.TemporaryDirectory() as directory, \
                open(os.path.join(directory, "emoji-test.txt"), "w", encoding="utf-8") as handle:
            handle.write("1F600 ; fully-qualified # 😀 E1.0 grinning face\n")
            handle.write("1F468 200D 1F4BB ; fully-qualified # 👨‍💻 E4.0 man technologist\n")
            handle.flush()
            registry = EmojiRegistry.from_emoji_test(handle.name)
        self.assertEqual(registry.lookup("grinning face"), ("😀",))
        self.assertEqual(registry.lookup("man-technologist"), ("👨‍💻",))
        converter = EmojiConverter(registry=registry, mapping={"웃음": "😀"})
        self.assertIn("😀", list(converter.candidates("웃음")))

    def test_weekday_era_and_lunar_backend(self):
        converter = DateConverter(date(2026, 9, 20))
        self.assertIn("2026-09-21", list(converter.candidates("다음주월요일")))
        self.assertEqual(list(converter.candidates("성종 5년")), ["1474년"])
        self.assertEqual(list(converter.candidates("令和6年")), ["2024년"])
        self.assertEqual(list(converter.candidates("康熙20年")), ["1681년"])

        class FakeLunar:
            def solar_to_lunar(self, value):
                return "음력 2026년 8월 9일"

            def lunar_to_solar(self, year, month, day, leap=False):
                return date(2026, 9, 20)

        converter = DateConverter(date(2026, 9, 20), lunar_backend=FakeLunar())
        self.assertIn("음력 2026년 8월 9일", list(converter.candidates("오늘")))
        self.assertIn("2026-09-20", list(converter.candidates("음력 2026년 8월 9일")))

    def test_jamo_halfwidth_and_codepoint_are_last(self):
        values = list(JamoUnicodeConverter().candidates("ㄱ"))
        self.assertEqual(values[-1], "U+3131")
        self.assertIn("ﾡ", values)
        syllable_values = list(JamoUnicodeConverter().candidates("한"))
        self.assertTrue(syllable_values[-1].startswith("U+D55C"))


class TestWordTransformEngine(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not os.path.exists(MODEL):
            raise unittest.SkipTest("먼저 scripts/train_ngram.py 실행 필요")
        cls.sp = NgramViterbiSpacer(SpacingModel.load(MODEL))

    def test_arrow_selection_and_repeated_space_cycle_one_word(self):
        eng = ImeEngine(self.sp)
        eng.input_text("ㅎㅏㄱㄱㅛㅇㅔㄱㅏㄴㄷㅏ")
        self.assertEqual(eng.convert(), "학교에 간다")

        # 첫 확정 뒤 선택 커서는 마지막 어절에 있다. 왼쪽으로 학교에를 선택한다.
        selected = eng.move_left()
        self.assertEqual(selected.text, "학교에")
        self.assertEqual(eng.convert(), "🏫에 간다")
        self.assertIn("學校에", [candidate.text for candidate in eng.word_candidates()])
        # Bundled dictionaries may add valid alternatives; a complete cycle restores source.
        for _ in range(len(eng.word_candidates()) - 1):
            eng.convert()
        self.assertEqual(eng.display, "학교에 간다")

    def test_right_arrow_and_candidate_metadata(self):
        eng = ImeEngine(self.sp)
        eng.input_text("ㅎㅏㄱㄱㅛㅇㅔㄱㅏㄴㄷㅏ")
        eng.convert()
        eng.move_left()
        eng.handle_key("RIGHT")
        self.assertEqual(eng.selected_word().text, "간다")
        self.assertEqual([c.text for c in eng.word_candidates()], ["간다"])

    def test_unit_and_date_word_candidates(self):
        eng = ImeEngine(
            self.sp,
            word_transformer=None,
        )
        eng.word_session.load("3킬로그램 오늘")
        eng.select_word(0)
        self.assertEqual(eng.word_session.cycle(), "3 kg 오늘")
        eng.select_word(1)
        # 기본 DateConverter는 실행 날짜를 사용하므로 후보 존재만 확인한다.
        self.assertGreater(len(eng.word_candidates()), 1)

    def test_sentence_end_does_not_cycle_a_word(self):
        eng = ImeEngine(self.sp)
        eng.input_text("ㅎㅏㄱㄱㅛ")
        self.assertEqual(eng.convert(), "학교")
        self.assertEqual(eng.end_sentence("."), "학교.")

    def test_settings_localize_width_punctuation_and_brackets(self):
        settings = TypographySettings(punctuation_profile="japanese")
        self.assertEqual(settings.format_text("Ａ１２，。?!"), "A12、。？！")
        self.assertEqual(settings.wrap("내용", "corner"), "「내용」")
        settings.punctuation_width = "half"
        self.assertEqual(settings.format_text("，。"), "､｡")
        settings.bracket_profile = "east_asian"
        self.assertEqual(settings.wrap("내용", "small_square"), "﹝내용﹞")
        self.assertEqual(settings.format_text("~ - ※ 々"), "〜 ― ※ 々")

    def test_settings_store_round_trip(self):
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "settings.json")
            store = SettingsStore(path, TypographySettings(punctuation_profile="chinese"))
            store.save()
            loaded = SettingsStore(path).load()
            self.assertEqual(loaded.punctuation_profile, "chinese")
            with open(path, encoding="utf-8") as handle:
                self.assertEqual(__import__("json").load(handle)["schema_version"], SETTINGS_FORMAT_VERSION)

    def test_settings_explicit_fullwidth_flags(self):
        settings = TypographySettings()
        settings.input.fullwidth_numerals = True
        settings.input.fullwidth_latin = True
        self.assertEqual(settings.format_text("A12"), "Ａ１２")

    def test_user_data_round_trip(self):
        with tempfile.TemporaryDirectory() as directory:
            custom_path = os.path.join(directory, "custom.json")
            registry = CustomConversionRegistry().add("내표현", ("내변환", "別候補"))
            registry.save(custom_path)
            self.assertEqual(CustomConversionRegistry.load(custom_path).entries["내표현"], ("내변환", "別候補"))

            hanja_path = os.path.join(directory, "hanja.tsv")
            hanja = HanjaConverter(mapping={"내표현": "內表現"})
            hanja.save_lexicon(hanja_path)
            self.assertIn("內表現", HanjaConverter(lexicon_path=hanja_path).mapping["내표현"])

            learning_path = os.path.join(directory, "learning.json")
            learning = LearningStore()
            learning.record("내표현", "내변환", 2)
            learning.save(learning_path)
            self.assertEqual(LearningStore.load(learning_path).counts["내표현"]["내변환"], 2)

    def test_custom_conversion_and_learning(self):
        registry = CustomConversionRegistry().add("테스트", "試驗")
        registry.add_rule(r"^버전(\d+)$", r"v\1", name="버전 규칙")
        transformer = WordTransformer((registry.converter(),))
        self.assertEqual([c.text for c in transformer.candidates("테스트")], ["테스트", "試驗"])
        self.assertEqual([c.text for c in transformer.candidates("버전2")], ["버전2", "v2"])

        learning = LearningStore()
        session = WordTransformSession(transformer, learning=learning)
        session.load("테스트")
        self.assertEqual(session.cycle(), "試驗")
        session.load("테스트")
        self.assertEqual(session.candidates()[1].text, "試驗")

    def test_engine_applies_settings_and_custom_converter(self):
        settings = TypographySettings(punctuation_profile="japanese")
        custom = CustomConversionRegistry().add("테스트", "試驗").converter()
        eng = ImeEngine(self.sp, settings=settings, custom_converter=custom)
        eng.word_session.load("테스트")
        eng.display = "테스트"
        eng._raw = "테스트"
        self.assertEqual(eng.convert(), "試驗")
        self.assertEqual(eng.input_punctuation("."), "試驗。")

    def test_spacing_regression_for_cloud_above_particle_phrase(self):
        eng = ImeEngine(self.sp)
        self.assertEqual(eng.convert_string("구름위를"), "구름 위를")


if __name__ == "__main__":
    unittest.main()
