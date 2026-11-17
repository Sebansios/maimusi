"""Public authored regressions; no evaluation-corpus text is retained here."""
import pytest

from hangul_ime.protected_text import PROTECTED_TEXT
from hangul_ime.release_spacing import KiwiSpacer
from hangul_ime.settings import TypographySettings

class IdentityRefiner:
    """Exercise the canonical refinement path without learned weights."""

    def refine(self, baseline_text, **kwargs):
        return baseline_text


@pytest.fixture(scope='module', params=[False, True], ids=['kiwi-only', 'identity-refiner'])
def spacer(request):
    result = KiwiSpacer(False)
    if request.param:
        result.refiner = IdentityRefiner()
        result.refiner_status = 'loaded'
        result.refiner_threshold = 1.0
        result.refiner_removal_threshold = 4.0
    return result


@pytest.mark.parametrize('text,restored_expected', [
    ('먹어 보려다가 멈췄어', '먹어 보려다가 멈췄어'),
    ('도와 주려다가 말았어', '도와주려다가 말았어'),
    ('책을 읽어 보려다가 잠들었어', '책을 읽어 보려다가 잠들었어'),
])
def test_contracted_auxiliary_stays_intact_and_repeatable(text, restored_expected, spacer):
    result = spacer.space(text)
    assert result == text
    assert spacer.space(result) == result
    restored = spacer.space(text.replace(' ', ''))
    assert restored == restored_expected
    assert spacer.space(restored) == restored


@pytest.mark.parametrize('prefix,number,suffix,category', [
    ('가격', '1,234.56', '원', 'number'),
    ('비율', '1,2', '는예시야', 'number'),
    ('수익', '+3.14', '퍼센트', 'signed_number'),
    ('잔액', '+.5', '원', 'signed_number'),
    ('', '.5', '리터', 'decimal'),
    ('', '-.5', '도', 'signed_number'),
])
def test_numeric_protection_does_not_depend_on_space_after_hangul(prefix, number, suffix, category, spacer):
    compact_span = (len(prefix), len(prefix) + len(number))
    for gap in ('', ' '):
        text = prefix + gap + number + suffix
        found = list(PROTECTED_TEXT.finditer(text))
        assert len(found) == 1
        assert found[0][0] == number
        assert found[0].lastgroup == category
        assert (len(text[:found[0].start()].replace(' ', '')),
                len(text[:found[0].end()].replace(' ', ''))) == compact_span
        result = spacer.space(text)
        assert number in result
        assert spacer.space(result) == result
        assert result.replace(' ', '') == text.replace(' ', '')


@pytest.mark.parametrize('text', [
    'v1.2.3', 'SKU123-45', 'foo_bar', 'AB+12.5X', 'ID_A1,234는그대로',
    '버전v1.2.3을설치해', '보고서.pdf', 'https://example.org/a?x=1,234.56',
    'name@example.org', '2026-10-02', '2026/10/02', '12:30:15',
    '3,500원가격', '일정2026-10-02는내일', '비율1:2로계산해',
    '온도-12.5도', '확률.5로가정해', '서울.다시가자',
])
def test_numbers_identifiers_and_prose_preserve_content_and_repeatability(text, spacer):
    result = spacer.space(text)
    assert result.replace(' ', '') == text.replace(' ', '')
    assert spacer.space(result) == result
    for match in PROTECTED_TEXT.finditer(text):
        assert match[0] in result


@pytest.mark.parametrize('text', ['SKU123-45', 'v1.2.3', 'foo_bar', '보고서.pdf',
                                 'name@example.org', 'https://example.org/a?x=1,234.56'])
def test_identifier_typography_remains_opaque(text):
    settings = TypographySettings(punctuation_profile='japanese', punctuation_width='full',
                                  latin_width='full', digit_width='full')
    assert settings.format_text(text) == text


def test_korean_sentence_punctuation_is_still_prose():
    text = '서울.다시가자'
    assert list(PROTECTED_TEXT.finditer(text)) == []
    settings = TypographySettings(punctuation_profile='japanese')
    assert settings.format_text(text) == '서울。다시가자'
