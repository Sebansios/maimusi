import unicodedata

import pytest

from hangul_ime.symbols import ALIASES, GROUPS, GREEK_NAMES, GREEK_SMALL, GREEK_BIG, SymbolConverter
from hangul_ime.word_transform import WordTransformer


@pytest.mark.parametrize('source,expected', [
    ('/', '·'), ('가운뎃점', '·'), ('...', '…'), ('줄임표', '……'),
    ('겹낫표', '『』'), ('홑낫표', '「」'), ('겹화살괄호', '≪≫'),
    ('곱하기', '×'), ('당구장', '※'), ('동그라미15', '⑮'), ('괄호15', '⒂'),
    ('(', '「'), (')', '」'), ('(학교)', '『학교』'), ('[책 이름]', '≪책 이름≫'),
    ('괄호', '『』'), ('괄호', '（）'), ('[', '【'), (']', '】'),
    ("'", '‘'), ('"', '“'), ("'내용'", '「내용」'),
])
def test_direct_conversions(source, expected):
    result = WordTransformer([SymbolConverter()]).candidates(source)
    assert result[0].text == source
    assert expected in [c.text for c in result[1:]]


@pytest.mark.parametrize('name,small,big', zip(GREEK_NAMES, GREEK_SMALL, GREEK_BIG))
def test_greek_names_and_explicit_case(name, small, big):
    c = SymbolConverter()
    assert list(c.candidates(name)) == [small, big]
    assert list(c.candidates('대문자' + name)) == [big]
    assert list(c.candidates('소문자' + name)) == [small]


def test_categories_cover_legacy_repertoire_and_safe_characters():
    # Independent CP949 readback checks every encodable non-Hangul symbol
    # from the legacy rows is reachable through some named category.
    reachable = {c for group in GROUPS.values() for c in group}
    for lead in range(0xA1, 0xAD):
        for trail in range(0xA1, 0xFF):
            try:
                char = bytes([lead, trail]).decode('cp949')
            except UnicodeDecodeError:
                continue
            if not char.isspace() and char != '\u3164' and unicodedata.category(char) != 'Cf':
                assert char in reachable
    for key, group in GROUPS.items():
        if len(key) == 1:
            assert len(group) < 511
        assert all('\n' not in c and '\t' not in c for c in group)


@pytest.mark.parametrize('text', ['알파벳', '오메가3', '알파와', '학교', 'https://example.com', 'a/b'])
def test_no_substring_conversion(text):
    assert list(SymbolConverter().candidates(text)) == []


def test_service_keeps_long_symbol_lists_and_first_hanja():
    from hangul_ime.ime_service import Service
    service = Service()
    assert service.handle({'op':'candidates', 'word':'/'})['items'][0] == '·'
    assert service.handle({'op':'candidates', 'word':'오메가'})['items'][:2] == ['ω', 'Ω']
    assert service.handle({'op':'candidates', 'word':'학교에'})['items'][0] == '學校에'
    items = service.handle({'op':'candidates', 'word':'전각'})['items']
    assert 'ｚ' in items and len(items) > 64
    assert service.handle({'op':'candidates', 'word':'선문자'})['items'][:2] == ['─', '│']
    for name in ['특수문자', '대문자알파', '겹화살괄호', '원문자']:
        assert service.handle({'op':'space', 'text':name})['text'] == name


@pytest.mark.parametrize('consonant', list('ㄱㄴㄷㄹㅁㅂㅅㅇㅈㅊㅋㅌㅍㅎ'))
def test_consonants_do_not_open_symbols(consonant):
    assert list(SymbolConverter().candidates(consonant)) == []


def test_consonants_can_only_be_enabled_explicitly_and_disabled_again():
    from hangul_ime.ime_service import Service
    service = Service()
    def items():
        return service.handle({'op':'candidates', 'word':'ㅁ'})['items']
    assert '★' not in items()
    service.handle({'op':'configure', 'symbol_consonants':True})
    assert '★' in items()
    service.handle({'op':'configure', 'symbol_consonants':False})
    assert '★' not in items()
    with pytest.raises(ValueError):
        service.handle({'op':'configure', 'symbol_consonants':'true'})
