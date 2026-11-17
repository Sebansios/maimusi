"""
jamo.py — 한글 음절 조합/분해 유틸리티 (의존성 없음).

유니코드 한글 음절 영역(U+AC00 ~ U+D7A3)은 다음 규칙으로 구성된다:
    code = 0xAC00 + (초성 * 21 + 중성) * 28 + 종성
- 초성(L): 19개, 중성(V): 21개, 종성(T): 28개(0=받침 없음).

이 모듈은 (1) L/V/T 인덱스 <-> 음절 변환, (2) 키보드 입력에서 들어오는
'호환 자모'(ㄱ, ㄴ, ㅏ ...)를 L/V/T 인덱스로 매핑, (3) 두벌식 입력에 필요한
겹자모 결합 규칙(ㅗ+ㅏ=ㅘ, ㄱ+ㅅ=ㄳ 등)을 제공한다.

Rust 코어로 포팅할 때 이 파일은 `jamo.rs`의 const 테이블 + 순수 함수에 대응한다.
"""

SBASE = 0xAC00          # '가'
TCOUNT = 28
VCOUNT = 21
LCOUNT = 19
NCOUNT = VCOUNT * TCOUNT    # 588
SCOUNT = LCOUNT * NCOUNT    # 11172

# 초성 19 (호환 자모 표기)
CHO = [
    "ㄱ", "ㄲ", "ㄴ", "ㄷ", "ㄸ", "ㄹ", "ㅁ", "ㅂ", "ㅃ", "ㅅ",
    "ㅆ", "ㅇ", "ㅈ", "ㅉ", "ㅊ", "ㅋ", "ㅌ", "ㅍ", "ㅎ",
]
# 중성 21
JUNG = [
    "ㅏ", "ㅐ", "ㅑ", "ㅒ", "ㅓ", "ㅔ", "ㅕ", "ㅖ", "ㅗ", "ㅘ",
    "ㅙ", "ㅚ", "ㅛ", "ㅜ", "ㅝ", "ㅞ", "ㅟ", "ㅠ", "ㅡ", "ㅢ", "ㅣ",
]
# 종성 28 (0번은 받침 없음)
JONG = [
    "", "ㄱ", "ㄲ", "ㄳ", "ㄴ", "ㄵ", "ㄶ", "ㄷ", "ㄹ", "ㄺ",
    "ㄻ", "ㄼ", "ㄽ", "ㄾ", "ㄿ", "ㅀ", "ㅁ", "ㅂ", "ㅄ", "ㅅ",
    "ㅆ", "ㅇ", "ㅈ", "ㅊ", "ㅋ", "ㅌ", "ㅍ", "ㅎ",
]

CHO_IDX = {c: i for i, c in enumerate(CHO)}
JUNG_IDX = {c: i for i, c in enumerate(JUNG)}
JONG_IDX = {c: i for i, c in enumerate(JONG) if c}

# 두벌식: 두 모음이 합쳐져 겹모음(이중모음)이 되는 규칙
VOWEL_COMBINE = {
    ("ㅗ", "ㅏ"): "ㅘ", ("ㅗ", "ㅐ"): "ㅙ", ("ㅗ", "ㅣ"): "ㅚ",
    ("ㅜ", "ㅓ"): "ㅝ", ("ㅜ", "ㅔ"): "ㅞ", ("ㅜ", "ㅣ"): "ㅟ",
    ("ㅡ", "ㅣ"): "ㅢ",
}
# 두벌식: 두 자음이 합쳐져 겹받침이 되는 규칙
JONG_COMBINE = {
    ("ㄱ", "ㅅ"): "ㄳ", ("ㄴ", "ㅈ"): "ㄵ", ("ㄴ", "ㅎ"): "ㄶ",
    ("ㄹ", "ㄱ"): "ㄺ", ("ㄹ", "ㅁ"): "ㄻ", ("ㄹ", "ㅂ"): "ㄼ",
    ("ㄹ", "ㅅ"): "ㄽ", ("ㄹ", "ㅌ"): "ㄾ", ("ㄹ", "ㅍ"): "ㄿ",
    ("ㄹ", "ㅎ"): "ㅀ", ("ㅂ", "ㅅ"): "ㅄ",
}
# 겹받침 -> (앞 받침, 뒤 자음) 분해. 받침 뒤에 모음이 오면 뒤 자음이 다음 초성으로 넘어간다.
JONG_SPLIT = {v: k for k, v in JONG_COMBINE.items()}


def is_syllable(ch: str) -> bool:
    """완성형 한글 음절인지."""
    return len(ch) == 1 and SBASE <= ord(ch) <= SBASE + SCOUNT - 1


def compose(cho: int, jung: int, jong: int = 0) -> str:
    """L/V/T 인덱스 -> 완성형 음절 한 글자."""
    return chr(SBASE + (cho * VCOUNT + jung) * TCOUNT + jong)


def decompose(ch: str):
    """완성형 음절 -> (cho, jung, jong) 인덱스. 음절이 아니면 None."""
    if not is_syllable(ch):
        return None
    s = ord(ch) - SBASE
    jong = s % TCOUNT
    jung = (s // TCOUNT) % VCOUNT
    cho = s // NCOUNT
    return cho, jung, jong


def decompose_to_jamo(ch: str):
    """완성형 음절 -> 호환 자모 리스트 (예: '값' -> ['ㄱ','ㅏ','ㅂ','ㅅ'])."""
    d = decompose(ch)
    if d is None:
        return [ch]
    cho, jung, jong = d
    out = [CHO[cho], JUNG[jung]]
    if jong:
        j = JONG[jong]
        if j in JONG_SPLIT:           # 겹받침은 두 자모로 분해
            out.extend(JONG_SPLIT[j])
        else:
            out.append(j)
    return out


def text_to_jamo(text: str) -> str:
    """문자열 전체를 자모 시퀀스 문자열로 (편집거리/교정용)."""
    buf = []
    for ch in text:
        buf.extend(decompose_to_jamo(ch))
    return "".join(buf)
