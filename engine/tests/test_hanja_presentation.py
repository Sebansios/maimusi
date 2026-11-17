import pytest

from hangul_ime.advanced_transform import HanjaConverter, default_word_transformer


MODES = [
    ('hanja', '學校'), ('hangul_hanja', '학교(學校)'),
    ('hanja_hangul', '學校(학교)'), ('hangulhanja', '학교學校'),
]


@pytest.mark.parametrize('mode,expected', MODES)
def test_hanja_presentation_keeps_stem_suffix_and_punctuation(mode, expected):
    converter = HanjaConverter(mapping={'학교':['學校']}, presentation=mode)
    assert list(converter.candidates('학교'))[0] == expected
    assert list(converter.candidates('“학교에,”'))[0] == '“' + expected + '에,”'
    transformer = default_word_transformer(hanja_presentation=mode, lunar_backend=False)
    result = transformer.candidates('학교에')
    assert result[0].text == '학교에'
    assert result[1].text == expected + '에'
    assert result[1].converter == '배울 학, 학교 교'


@pytest.mark.parametrize('mode,expected', [
    ('hanja','安寧하다'), ('hangul_hanja','안녕(安寧)하다'),
    ('hanja_hangul','安寧(안녕)하다'), ('hangulhanja','안녕安寧하다'),
])
def test_derivational_endings_stay_outside_annotation(mode, expected):
    assert list(HanjaConverter(presentation=mode).candidates('안녕하다'))[0] == expected


def test_glyph_standards_variants_and_rank_stay_intact():
    education = HanjaConverter(presentation='hangul_hanja', forms='education')
    ks = HanjaConverter(presentation='hangul_hanja', forms='ks')
    edu = education.ranked_candidates('강하다')
    ks_rows = ks.ranked_candidates('강하다')
    assert edu[0][:2] == ('강(強)하다', 'top')
    assert ks_rows[0][:2] == ('강(强)하다', 'top')
    assert not any('强' in text for text, _, _ in edu)
    assert not any('強' in text for text, _, _ in ks_rows)


def test_configure_switches_modes_and_retains_other_candidate_types():
    from hangul_ime.ime_service import Service
    service = Service()
    def items(word):
        return service.handle({'op':'candidates','word':word})['items']
    for mode, expected in MODES:
        service.handle({'op':'configure', 'hanja_presentation':mode})
        assert items('학교에')[0] == expected + '에'
        assert '🏫에' in items('학교에')
        assert items('/')[0] == '·'
    service.handle({'op':'configure', 'hanja_presentation':'hangul_hanja'})
    service.handle({'op':'configure', 'symbol_consonants':True, 'hanja_forms':'ks'})
    assert service.hanja_presentation == 'hangul_hanja'
    assert items('강하다')[0] == '강(强)하다'
    with pytest.raises(ValueError):
        service.handle({'op':'configure', 'hanja_presentation':'bad'})
    assert items('강하다')[0] == '강(强)하다'


@pytest.mark.parametrize('value', ['bad', None, 1, [], {}])
def test_invalid_presentation_is_rejected(value):
    with pytest.raises(ValueError):
        HanjaConverter(presentation=value)


def test_gloss_search_is_opt_in():
    # 훈음으로 한자 찾기(살찔비 -> 肥)는 켰을 때만. 끈 상태의 후보·띄어쓰기는 그대로다.
    off = HanjaConverter()
    assert [t for t, _, _ in off.ranked_candidates("살찔비")] == []
    on = HanjaConverter(gloss_search=True)
    assert on.ranked_candidates("살찔비")[0] == ("肥", "top", "살찔 비")
    assert on.ranked_candidates("배울학학교교")[0][:2] == ("學校", "top")
    assert on.ranked_candidates("다스릴이")[0][0] == "理"
    # 사전에 있는 낱말이면 그 한자어가 먼저(입구 -> 入口, 그다음 口).
    assert [t for t, _, _ in on.ranked_candidates("입구")][:2] == ["入口", "口"]
    assert HanjaConverter(gloss_search=True, presentation="hangul_hanja").ranked_candidates("살찔비")[0][0] == "비(肥)"


def test_service_gloss_option_and_preview_spacing():
    from hangul_ime.ime_service import Service
    service = Service()
    assert service.handle({"op": "space", "text": "살찔비"})["text"] == "살찔 비"
    assert "肥" not in service.handle({"op": "candidates", "word": "살찔비"})["items"]
    service.handle({"op": "configure", "hanja_gloss": True})
    assert service.handle({"op": "space", "text": "살찔비"})["text"] == "살찔비"
    assert service.handle({"op": "candidates", "word": "살찔비"})["items"][0] == "肥"
    with pytest.raises(ValueError):
        service.handle({"op": "configure", "hanja_gloss": "yes"})
    # 설정 창 예문: 요청에 실은 규칙으로만 띄우고 저장된 규칙은 바꾸지 않는다.
    text = "국어사전을펴놓고사과10개를먹어보았다"
    joined = {"auxiliaries": "join", "compound": "join", "number_units": "join"}
    separate = {"auxiliaries": "separate", "compound": "separate", "number_units": "separate"}
    assert service.handle({"op": "space", "text": text, "spacing": joined})["text"] == "국어사전을 펴놓고 사과 10개를 먹어보았다"
    assert service.handle({"op": "space", "text": text, "spacing": separate})["text"] == "국어 사전을 펴 놓고 사과 10 개를 먹어 보았다"
    assert service.handle({"op": "space", "text": text})["text"] == service.spacer.space(text, service.preferences)
