"""Sentence punctuation is prose; identifiable numbers/files/paths are opaque."""
import pytest

from hangul_ime.protected_text import PROTECTED_TEXT
from hangul_ime.release_spacing import KiwiSpacer
from hangul_ime.settings import TypographySettings


@pytest.fixture(scope="module")
def baseline_spacer():
    return KiwiSpacer(False)


@pytest.mark.parametrize("text", [
    "오늘학교에갔다.친구를만났다", "나는밥을먹었다.동생은책을읽었다",
    "끝났다.다음이야기가시작됐다.모두집중했다", "잘됐어.다시만나자",
    "제1장은끝났다.제2장을읽었다", "API를썼다.결과가나왔다",
])
def test_korean_sentences_are_not_classified_as_identifiers(text, baseline_spacer):
    assert list(PROTECTED_TEXT.finditer(text)) == []
    assert baseline_spacer.space(text) == ".".join(baseline_spacer.space(part) for part in text.split("."))
    assert baseline_spacer.space(text) != text
    settings = TypographySettings(punctuation_profile="japanese")
    assert settings.format_text(text) == text.replace(".", "。")


@pytest.mark.parametrize("text", [
    "example.com", "api.example.co.kr", "localhost:8080", "192.168.0.1", "v1.2.3",
    "AB-123", "foo_bar", "namespace:value", "package.module.symbol", "오늘foo_bar값을봤어",
    "보고서.pdf", "서울.일정.md", "발표자료.pptx", "원고.hwp", "원고.hwpx", "통계.xlsx",
    "보고서.PDF", "자료.customext42", "보고서.pdf를", "서울.일정.md에는",
    "보고서.pdf를읽었다", "수치3.14를확인했다", "버전v1.2.3을썼다", "example.com주소를썼다",
    "배포v1.2.3", "자료_백업", "문서/최종.백업",
    "문서\\보고서.pdf", "/tmp/서울.일정.md", "./서울.일정.md", "../문서/보고서.hwp", "~/문서/초안.백업",
    r"C:\Users\public\보고서.pdf", r"\\server\share\서울.일정.md",
    "name@example.org", "이름@예시.com", "a+b@example.com",
    "https://example.org/한국어/자료?x=3.14&y=2026-09-21#part", "https://예시.한국/자료", "www.example.org/자료",
    "ftp://example.org/f.txt", "-12.50", "+3.14", ".5", "-.5", "1,234.56",
    "2026-09-21", "2026/09/21", "12:34:56",
])
def test_identifiers_numbers_files_and_paths_remain_opaque(text, baseline_spacer):
    matches = list(PROTECTED_TEXT.finditer(text))
    assert len(matches) == 1 and matches[0].span() == (0, len(text))
    assert baseline_spacer.space(text) == text
    settings = TypographySettings(punctuation_profile="japanese", punctuation_width="full",
                                  latin_width="full", digit_width="full")
    assert settings.format_text(text) == text


def test_shared_classifier_preserves_offsets_in_mixed_prose():
    text = "왔다.다시봤다 보고서.pdf와는 별도로 서울.일정.md https://example.org/자료 3.14 끝났다.집에갔다"
    found = list(PROTECTED_TEXT.finditer(text))
    assert [m[0] for m in found] == ["보고서.pdf와는", "서울.일정.md", "https://example.org/자료", "3.14"]
    assert all(text[m.start():m.end()] == m[0] for m in found)
