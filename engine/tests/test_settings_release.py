"""Release regressions for settings, private persistence, dictionaries and learning."""
import copy
import json
import os
from pathlib import Path
import stat
import time
from unittest.mock import patch

import pytest

from hangul_ime.conversion_types import ConversionCandidate
from hangul_ime.customization import (
    ConversionRule, CustomConversionRegistry, LearningStore, MAX_COUNT,
    MAX_LEARNING_RECORDS, MAX_LEARNING_SOURCES, MAX_TARGETS,
)
from hangul_ime.persistence import (
    DurabilityError, MAX_JSON_BYTES, atomic_json_save, load_json,
)
from hangul_ime.settings import (
    BRACKET_CATALOG, BRACKET_LABELS, PUNCTUATION_PROFILES, SETTINGS_FORMAT_VERSION,
    InputBehaviorSettings, SettingsStore, TypographySettings, settings_schema,
    _fullwidth_katakana, _halfwidth_katakana,
)
from hangul_ime.user_profile import (
    ProfileConflictError, UserProfile, UserProfileStore,
    load_hanja_overlay, save_hanja_overlay,
)


@pytest.mark.parametrize("payload", [
    [], None, {"typo": 1}, {"input": {"unknown": True}},
    {"input": None}, {"input": []}, {"input": {"private_mode": 1}},
    {"conversion_learning": "true"}, {"auto_pair_brackets": 0},
    {"schema_version": True}, {"schema_version": -1}, {"schema_version": "1"},
    {"schema_version": SETTINGS_FORMAT_VERSION + 1},
    {"settings": {"schema_version": SETTINGS_FORMAT_VERSION + 1}},
    {"settings": {}, "unknown": {}},
    {"digit_width": "learned"}, {"normalize_unicode": "NFKC"},
    {"punctuation_overrides": {"typo": "!"}},
    {"punctuation_overrides": {"period": "hello"}},
    {"punctuation_overrides": {"period": "\ud800"}},
    {"bracket_overrides": {"corner": ["「"]}},
    {"bracket_overrides": {"typo": ["(", ")"]}},
    {"enabled_converters": ["한자", "한자"]},
    {"converter_order": ["bogus"]}, {"enabled_converters": "한자"},
])
def test_settings_reject_unknown_versions_keys_and_types(payload):
    with pytest.raises((ValueError, TypeError)):
        TypographySettings.from_dict(payload)


def test_settings_update_is_detached_and_atomic():
    store = SettingsStore()
    store.update(input={"private_mode": True})
    original = store.settings
    before = original.to_dict()
    with pytest.raises(ValueError):
        store.update(latin_width="full", digit_width="invalid")
    assert store.settings is original
    assert store.settings.to_dict() == before
    with pytest.raises(KeyError):
        store.update(latin_width="full", validate=True)
    assert store.settings.to_dict() == before
    changed = store.update(input={"punctuation_conversion": False})
    assert changed.input.private_mode is True
    assert changed.input.punctuation_conversion is False
    assert original.to_dict() == before


def test_settings_nested_values_cannot_alias_caller():
    payload = {
        "bracket_overrides": {"corner": ["(", ")"]},
        "enabled_converters": ["한자"],
    }
    settings = TypographySettings.from_dict(payload)
    payload["bracket_overrides"]["corner"][0] = "["
    payload["enabled_converters"].clear()
    assert settings.bracket_pair("corner") == ("(", ")")
    assert settings.enabled_converters == ["한자"]


@pytest.mark.parametrize("bad", [
    '{"schema_version":999,"future":{"important":true}}',
    '{"input":{"private_mode":"yes"}}',
    '{"digit_width":"full","digit_width":"half"}',
    '{"conversion_learning":NaN}',
    '{"truncated":',
])
def test_bad_load_cannot_be_followed_by_overwriting_save(tmp_path, bad):
    path = tmp_path / "settings.json"
    path.write_text(bad, encoding="utf-8")
    store = SettingsStore(path)
    original = store.settings
    with pytest.raises((ValueError, TypeError)):
        store.load()
    assert store.settings is original
    with pytest.raises((ValueError, TypeError)):
        store.save()
    assert path.read_text(encoding="utf-8") == bad


def test_settings_legacy_roundtrip(tmp_path):
    path = tmp_path / "settings.json"
    path.write_text('{"schema_version":1,"punctuation_profile":"japanese"}', encoding="utf-8")
    store = SettingsStore(path)
    assert store.load().punctuation_profile == "japanese"
    store.save()
    assert load_json(path)["schema_version"] == SETTINGS_FORMAT_VERSION


@pytest.mark.parametrize("profile", PUNCTUATION_PROFILES)
@pytest.mark.parametrize("width", ["preserve", "half", "full"])
def test_punctuation_profiles_are_idempotent(profile, width):
    settings = TypographySettings(punctuation_profile=profile, punctuation_width=width)
    text = "안녕, 세상. ? ! : ; … …… ... · / ~ - ※ 々 Ａ１２"
    once = settings.format_text(text)
    assert settings.format_text(once) == once


@pytest.mark.parametrize("text", [
    "3.14", "-12.50", "+3.14", ".5", "-.5", "+.5", "-12", "-1e-3", "1,234.56", "2026-09-21", "2026/09/21",
    "12:34:56", "v1.2.3", "AB-123", "abc_def", "namespace:value",
    "example.com", "report.csv", "name@example.org",
    "https://example.org/a/b?x=3.14&y=2026-09-21#part",
    "ftp://example.org/f.txt", r"C:\data\file.txt",
])
def test_typography_preserves_identifier_numeric_and_url_separators(text):
    settings = TypographySettings(
        punctuation_profile="japanese", punctuation_width="full",
        latin_width="full", digit_width="full",
    )
    assert settings.format_text(text) == text


def test_sentence_punctuation_after_url_converts():
    settings = TypographySettings(punctuation_profile="japanese")
    assert settings.format_text("https://example.org/a. 다음!") == "https://example.org/a。 다음！"


def test_override_outputs_do_not_expand_or_change_on_second_pass():
    settings = TypographySettings(punctuation_profile="japanese", punctuation_overrides={"period": "!!"})
    once = settings.format_text("안녕. 다음…")
    assert once == "안녕!! 다음……"
    assert settings.format_text(once) == once


@pytest.mark.parametrize("ascii_width", ["preserve", "half", "full"])
@pytest.mark.parametrize("symbol_width", ["preserve", "half", "full"])
def test_symbol_width_is_idempotent(ascii_width, symbol_width):
    settings = TypographySettings(ascii_width=ascii_width, symbol_width=symbol_width)
    once = settings.format_text("$＄=＝")
    assert settings.format_text(once) == once


def test_korean_jamo_preserved_by_default_and_explicit_width():
    original = "ㄱㄴㅏ ﾡﾤￂ 한글"
    assert TypographySettings().format_text(original) == original
    assert TypographySettings(hangul_jamo_width="half").format_text("ㄱㄴㅏ") == "ﾡﾤￂ"
    assert TypographySettings(hangul_jamo_width="full").format_text("ﾡﾤￂ") == "ㄱㄴㅏ"
    assert TypographySettings(hangul_jamo_width="half").format_text("한글") == "한글"


def test_voiced_katakana_and_non_width_symbols_are_preserved():
    assert _fullwidth_katakana("ｶﾞﾊﾟｳﾞﾜﾞ") == "ガパヴヷ"
    assert _halfwidth_katakana("ガパヴヷ") == "ｶﾞﾊﾟｳﾞﾜﾞ"
    assert _fullwidth_katakana("①㍿Ａㄱ") == "①㍿Ａㄱ"
    assert _halfwidth_katakana("①㍿Ａㄱ") == "①㍿Ａㄱ"
    assert TypographySettings().format_text("ｶﾞ①㍿") == "ｶﾞ①㍿"
    assert TypographySettings(katakana_width="full").format_text("ｶﾞ①㍿") == "ガ①㍿"
    assert TypographySettings(katakana_width="half").format_text("ガパ") == "ｶﾞﾊﾟ"


def test_bracket_override_is_independent_of_profile():
    settings = TypographySettings(bracket_profile="ascii", bracket_overrides={"parenthesis": ["【", "】"]})
    assert settings.wrap("내용", "parenthesis") == "【내용】"
    assert settings.bracket_pair("corner_vertical") == ("﹁", "﹂")
    assert set(BRACKET_CATALOG) == set(BRACKET_LABELS)
    with pytest.raises(ValueError):
        settings.bracket_pair("typo")


def test_smart_quote_insertion_is_pure_and_contextual():
    settings = TypographySettings()
    assert settings.insertion_for_key('"') == ("“”", 1)
    assert settings.quote_for_insertion('"', "“내용") == "”"
    assert settings.quote_for_insertion("'", "can", "t") == "’"
    assert settings.insertion_for_key("(") == ("()", 1)
    settings.auto_pair_brackets = False
    assert settings.insertion_for_key("(") == ("(", 1)
    settings.smart_quotes = False
    assert settings.insertion_for_key('"') == ('"', 1)


def test_schema_hides_unsupported_settings_and_marks_advanced():
    schema = settings_schema()
    controls = {name for group in schema for name, _, _ in group["fields"]}
    assert "live_conversion" not in controls
    assert "input_layout" not in controls
    assert "conversion_learning" in controls
    advanced = next(group for group in schema if group["id"] == "advanced")
    assert advanced["advanced"] and "katakana_width" in {item[0] for item in advanced["fields"]}
    assert any(group["supported"] is False for group in schema)


def test_atomic_write_failure_preserves_file_and_removes_temporary(tmp_path):
    path = tmp_path / "data.json"
    atomic_json_save(path, {"old": True})
    before = path.read_bytes()
    with patch("hangul_ime.persistence.os.replace", side_effect=OSError("replace failed")):
        with pytest.raises(OSError):
            atomic_json_save(path, {"new": True})
    assert path.read_bytes() == before
    assert list(tmp_path.glob("*.tmp")) == []
    assert list(tmp_path.glob(".*.tmp")) == []


def test_file_fsync_failure_preserves_file(tmp_path):
    path = tmp_path / "data.json"
    atomic_json_save(path, {"old": True})
    with patch("hangul_ime.persistence.os.fsync", side_effect=OSError("disk full")):
        with pytest.raises(OSError):
            atomic_json_save(path, {"new": True})
    assert load_json(path) == {"old": True}


@pytest.mark.skipif(os.name != "posix", reason="POSIX permission bits")
def test_private_permissions_and_directory_fsync(tmp_path):
    path = tmp_path / "private" / "profile.json"
    real_fsync = os.fsync
    calls = []
    def tracked(fd):
        calls.append(stat.S_ISDIR(os.fstat(fd).st_mode))
        return real_fsync(fd)
    with patch("hangul_ime.persistence.os.fsync", side_effect=tracked):
        atomic_json_save(path, {})
    assert calls == [False, True]
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert stat.S_IMODE(path.parent.stat().st_mode) == 0o700


def test_symlink_save_refuses_to_overwrite_other_file(tmp_path):
    target = tmp_path / "target.json"
    target.write_text('{"original":true}', encoding="utf-8")
    link = tmp_path / "link.json"
    link.symlink_to(target)
    with pytest.raises(ValueError):
        atomic_json_save(link, {})
    assert load_json(target) == {"original": True}


def test_oversized_json_load_is_bounded(tmp_path):
    path = tmp_path / "large.json"
    with path.open("wb") as handle:
        handle.truncate(MAX_JSON_BYTES + 1)
    with pytest.raises(ValueError):
        load_json(path)


@pytest.mark.parametrize("payload", [
    None, [], {"unknown": {}}, {"schema_version": True}, {"schema_version": 99},
    {"entries": {"": ["空"]}}, {"entries": {"원문": []}},
    {"entries": {"원문": ["候補", "候補"]}}, {"entries": {"원문": [1]}},
    {"entries": {"원문": "\ud800"}}, {"rules": [{"pattern": "(", "replacement": ""}]},
    {"rules": [{"pattern": "(x)", "replacement": r"\2"}]},
    {"rules": [{"pattern": "(x)", "replacement": r"\g<missing>"}]},
    {"rules": [{"pattern": "x", "replacement": r"\q"}]},
    {"rules": [{"pattern": "x", "replacement": "", "priority": True}]},
    {"rules": [{"pattern": "x", "replacement": "", "flags": -1}]},
    {"rules": [{"pattern": "x{1000000000}", "replacement": ""}]},
    {"rules": [{"pattern": "x", "replacement": "", "enabled": 0}]},
    {"rules": [{"pattern": "x", "replacement": "", "typo": True}]},
    {"disabled_entries": ["없음"]},
])
def test_custom_import_rejects_invalid_without_partial_changes(payload):
    registry = CustomConversionRegistry().add("유지", "保持")
    before = registry.to_dict()
    with pytest.raises((ValueError, TypeError)):
        registry.import_dict(payload)
    assert registry.to_dict() == before


def test_custom_exact_longest_known_stem_and_rules_roundtrip(tmp_path):
    registry = CustomConversionRegistry().add("국가", "國家").add("학교", "學校")
    registry.add_rule(r"^버전(?P<n>\d+)$", r"v\g<n>", name="버전", priority=5)
    converter = registry.converter()
    assert list(converter.candidates("국가")) == ["國家"]
    assert list(converter.candidates("학교에만")) == ["學校에만"]
    assert list(converter.candidates("버전23")) == ["v23"]
    registry.set_enabled("학교", False).set_rule_enabled(0, False)
    path = tmp_path / "custom.json"
    registry.save(path)
    loaded = CustomConversionRegistry.load(path)
    assert loaded.to_dict() == registry.to_dict()
    assert list(loaded.converter().candidates("학교")) == []
    assert list(loaded.converter().candidates("버전23")) == []
    loaded.set_enabled("학교", True).set_rule_enabled(0, True)
    assert list(loaded.converter().candidates("버전23")) == ["v23"]


def test_rule_snapshot_does_not_alias_live_registry():
    registry = CustomConversionRegistry().add("원문", "候補")
    registry.add_rule("^test$", "passed")
    converter = registry.converter()
    registry.entries["원문"] = ("변경",)
    registry.rules[0].replacement = "changed"
    assert list(converter.candidates("원문")) == ["候補"]
    assert list(converter.candidates("test")) == ["passed"]


def test_regex_timeout_and_batch_budget_bound_harmful_rule():
    registry = CustomConversionRegistry()
    for index in range(8):
        registry.add_rule(r"(a+)+$", "x", name=f"slow-{index}")
    converter = registry.converter()
    started = time.monotonic()
    assert list(converter.candidates("a" * 3000 + "X")) == []
    assert time.monotonic() - started < 1.0
    assert converter.last_timeouts


def test_regex_expansion_is_bounded():
    registry = CustomConversionRegistry().add_rule("a", "b" * 4096)
    assert list(registry.converter().candidates("a" * 1000)) == []


@pytest.mark.parametrize("counts", [
    [], {"원문": []}, {"원문": {}}, {"원문": {"候補": 0}},
    {"원문": {"候補": -1}}, {"원문": {"候補": True}},
    {"원문": {"候補": "1"}}, {"원문": {"候補": 1.5}},
    {"원문": {"候補": MAX_COUNT + 1}}, {"원문": {"원문": 1}},
    {"": {"候補": 1}}, {"원문": {"": 1}},
])
def test_learning_rejects_invalid_counts(counts):
    with pytest.raises((ValueError, TypeError)):
        LearningStore(counts)


def test_learning_rank_pins_actual_original_and_codepoints_last():
    learning = LearningStore({"학교": {"學校": 4, "U+D559 U+AD50": 100}})
    options = [
        ConversionCandidate("🏫", "이모지"),
        ConversionCandidate("U+D559 U+AD50", "자모·유니코드"),
        ConversionCandidate("학교", "원문"),
        ConversionCandidate("學校", "한자"),
    ]
    before = learning.to_dict()
    assert [item.text for item in learning.rank("학교", options)] == ["학교", "學校", "🏫", "U+D559 U+AD50"]
    assert learning.to_dict() == before


def test_learning_record_and_deletion_are_bounded():
    learning = LearningStore({"원문": {"候補": MAX_COUNT}})
    learning.record("원문", "候補")
    assert learning.counts["원문"]["候補"] == MAX_COUNT
    before = learning.to_dict()
    for invalid in (True, -1, 0, 1.2, "1", MAX_COUNT + 1):
        with pytest.raises(ValueError):
            learning.record("원문", "다른후보", invalid)
    assert learning.to_dict() == before
    learning.forget("원문", "候補")
    assert learning.to_dict() == {}
    learning.record("원문", "후보")
    learning.clear()
    assert learning.to_dict() == {}


def test_learning_target_cap_preserves_existing_data():
    learning = LearningStore({"원문": {str(index): 1 for index in range(MAX_TARGETS)}})
    assert learning.record("원문", "추가") is False
    assert learning.record("원문", "0") is True
    assert len(learning.counts["원문"]) == MAX_TARGETS


def test_learning_version_roundtrip_and_future_protection(tmp_path):
    path = tmp_path / "learning.json"
    learning = LearningStore()
    learning.record("테스트", "試驗", 3)
    learning.save(path)
    assert LearningStore.load(path).counts == learning.counts
    path.write_text('{"schema_version":99,"counts":{}}', encoding="utf-8")
    with pytest.raises(ValueError):
        learning.save(path)
    assert load_json(path)["schema_version"] == 99


def test_learning_legacy_word_schema_version_is_not_mistaken_for_envelope():
    assert LearningStore.from_dict({"schema_version": {"후보": 1}}).counts == {"schema_version": {"후보": 1}}


def test_profile_snapshot_cancel_and_atomic_commit(tmp_path):
    path = tmp_path / "profile.json"
    store = UserProfileStore(path)
    draft = store.snapshot()
    draft.settings.latin_width = "full"
    draft.custom.add("학교", "學校")
    draft.hanja_entries["나라"] = ("國",)
    draft.hanja_disabled.add("국가")
    draft.learning.record("학교", "學校")
    assert not path.exists()
    assert store.profile.settings.latin_width == "half"
    published = store.commit(draft)
    assert published is not draft
    draft.custom.remove("학교")
    reopened = UserProfileStore(path).load()
    assert reopened.custom.entries["학교"] == ("學校",)
    assert reopened.hanja_disabled == {"국가"}
    assert reopened.learning.counts["학교"]["學校"] == 1


def test_invalid_profile_section_keeps_all_other_sections(tmp_path):
    store = UserProfileStore(tmp_path / "profile.json")
    store.save()
    original, before = store.profile, store.path.read_bytes()
    draft = store.snapshot()
    draft.settings.latin_width = "full"
    draft.hanja_entries = {"원문": []}
    with pytest.raises(ValueError):
        store.commit(draft)
    assert store.profile is original
    assert store.path.read_bytes() == before


def test_failed_profile_write_does_not_publish_draft(tmp_path):
    store = UserProfileStore(tmp_path / "profile.json")
    store.save()
    draft = store.snapshot()
    draft.settings.input.private_mode = True
    original, before = store.profile, store.path.read_bytes()
    with patch("hangul_ime.persistence.os.replace", side_effect=OSError("full disk")):
        with pytest.raises(OSError):
            store.commit(draft)
    assert store.profile is original
    assert store.path.read_bytes() == before


@pytest.mark.skipif(os.name != "posix", reason="Windows has no directory fsync")
def test_directory_fsync_failure_reports_complete_commit(tmp_path):
    store = UserProfileStore(tmp_path / "profile.json")
    draft = store.snapshot()
    draft.settings.latin_width = "full"
    fsync = os.fsync
    def directory_error(fd):
        if stat.S_ISDIR(os.fstat(fd).st_mode):
            raise OSError("directory flush failed")
        fsync(fd)
    with patch("hangul_ime.persistence.os.fsync", side_effect=directory_error):
        with pytest.raises(DurabilityError) as caught:
            store.commit(draft)
    assert caught.value.committed
    assert store.profile.settings.latin_width == "full"
    assert UserProfileStore(store.path).load().settings.latin_width == "full"


def test_profile_conflicts_preserve_newer_disk_and_memory(tmp_path):
    path = tmp_path / "profile.json"
    first = UserProfileStore(path)
    first.save()
    second = UserProfileStore(path)
    second.load()
    stale = second.snapshot()
    current = first.snapshot()
    current.settings.latin_width = "full"
    first.commit(current)
    before = path.read_bytes()
    with pytest.raises(ProfileConflictError):
        second.commit(stale)
    assert path.read_bytes() == before
    assert second.profile.settings.latin_width == "half"


def test_stale_dialog_rejected_after_same_store_changes(tmp_path):
    store = UserProfileStore(tmp_path / "profile.json")
    stale, current = store.snapshot(), store.snapshot()
    current.settings.punctuation_profile = "japanese"
    store.commit(current)
    with pytest.raises(ProfileConflictError):
        store.commit(stale)


@pytest.mark.parametrize("payload", [
    {"schema_version": 999}, {"unknown": {}},
    {"settings": {"future": True}}, {"custom": {"schema_version": 999}},
    {"learning": {"schema_version": 999, "counts": {}}},
    {"hanja": {"schema_version": 999, "entries": {}}},
])
def test_profile_invalid_future_data_never_overwritten(tmp_path, payload):
    path = tmp_path / "profile.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    before = path.read_bytes()
    store = UserProfileStore(path)
    with pytest.raises((ValueError, TypeError)):
        store.load()
    with pytest.raises((ValueError, TypeError)):
        store.commit(store.snapshot())
    assert path.read_bytes() == before


def test_profile_learning_privacy_gate(tmp_path):
    store = UserProfileStore(tmp_path / "profile.json")
    draft = store.snapshot()
    draft.settings.input.private_mode = True
    store.commit(draft)
    before = store.path.read_bytes()
    assert store.record_commit("학교", "學校") is False
    assert store.path.read_bytes() == before
    draft = store.snapshot()
    draft.settings.input.private_mode = False
    draft.settings.conversion_learning = False
    store.commit(draft)
    assert store.record_commit("학교", "學校") is False
    draft = store.snapshot()
    draft.settings.conversion_learning = True
    store.commit(draft)
    assert store.record_commit("학교", "學校") is True
    assert UserProfileStore(store.path).load().learning.counts == {"학교": {"學校": 1}}
    store.clear_learning()
    assert UserProfileStore(store.path).load().learning.counts == {}


@pytest.mark.parametrize("suffix", [".json", ".tsv"])
def test_hanja_roundtrip_including_commas_quotes_and_disable(tmp_path, suffix):
    path = tmp_path / ("hanja" + suffix)
    entries = {"원문": ("漢字", "句,讀", '"引用"')}
    disabled = {"학교"}
    save_hanja_overlay(path, entries, disabled)
    assert load_hanja_overlay(path) == (entries, disabled)


def test_hanja_tsv_import_is_all_or_nothing(tmp_path):
    path = tmp_path / "hanja.tsv"
    path.write_text("학교\t學校\nbroken row\n", encoding="utf-8")
    profile = UserProfile(hanja_entries={"원문": ("原文",)})
    before = profile.to_dict()
    with pytest.raises(ValueError):
        profile.import_hanja(path)
    assert profile.to_dict() == before


def test_hanja_import_never_normalizes_or_drops_invalid_data(tmp_path):
    path = tmp_path / "hanja.json"
    for payload in (
        {"schema_version": True}, {"schema_version": 2, "entries": {}},
        {"schema_version": 1, "entries": {}, "unknown": True},
        {"entries": {"단어": ["候補", 5]}},
        {"entries": {"단어": ["候補"]}, "disabled": [False]},
    ):
        path.write_text(json.dumps(payload), encoding="utf-8")
        with pytest.raises((ValueError, TypeError)):
            load_hanja_overlay(path)


def test_hanja_converter_interoperability(tmp_path):
    from hangul_ime.advanced_transform import HanjaConverter
    for suffix in (".json", ".tsv"):
        path = tmp_path / ("hanja" + suffix)
        save_hanja_overlay(path, {"새단어": ("新語", "新,語")}, {"학교"})
        converter = HanjaConverter(lexicon_path=path)
        assert list(converter.candidates("학교")) == []
        assert list(converter.candidates("새단어")) == ["新語", "新,語"]
        converter.save_lexicon(path)
        assert load_hanja_overlay(path) == ({"새단어": ("新語", "新,語")}, {"학교"})
