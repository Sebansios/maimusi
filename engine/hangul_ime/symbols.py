"""Explicit symbol candidates; never substitute punctuation while typing.

The legacy repertoire is decoded from KS X 1001 using Python's EUC-KR codec.
Named categories cover the familiar Hanja-key repertoire. Consonant shortcuts
require an explicit opt-in setting. No external dictionary or input log.
"""
import re
import unicodedata

from .conversion_types import WordConverter, _unique


def _row(lead):
    result = []
    for trail in range(0xA1, 0xFF):
        try:
            char = bytes((lead, trail)).decode("euc_kr")
        except UnicodeDecodeError:
            continue
        # Invisible spaces/soft hyphen are poor insertion candidates.
        if not char.isspace() and char != "\u3164" and unicodedata.category(char) != "Cf":
            result.append(char)
    return tuple(result)


PUNCTUATION = tuple("·‥…、。‘’“”〔〕〈〉《》「」『』【】―∼※§¶†‡")
MATH = tuple("＋－±×÷＝≠≤≥∞∴∵√∽∝∫∬∮∑∏∈∋⊆⊇⊂⊃∪∩∧∨￢⇒⇔∀∃∠⊥⌒∂∇≡≒")
SHAPES = tuple("☆★○●◎◇◆□■△▲▽▼◁◀▷▶♤♠♡♥♧♣⊙◈▣◐◑▒▤▥▨▧▦▩♨☏☎☜☞♭♩♪♬")
ARROWS = tuple("→←↑↓↔↕↗↙↖↘⇒⇔")
BRACKETS = (("(", ")"), ("[", "]"), ("{", "}"), ("〈", "〉"),
            ("《", "》"), ("≪", "≫"), ("「", "」"), ("『", "』"),
            ("【", "】"), ("〔", "〕"), ("（", "）"), ("［", "］"), ("｛", "｝"))
QUOTES = (("‘", "’"), ("“", "”"), ("'", "'"), ('"', '"'))
GREEK_NAMES = ("알파 베타 감마 델타 엡실론 제타 에타 세타 이오타 카파 람다 뮤 뉴 크시 "
               "오미크론 파이 로 시그마 타우 입실론 피 카이 프시 오메가").split()
GREEK_SMALL = "αβγδεζηθικλμνξοπρστυφχψω"
GREEK_BIG = "ΑΒΓΔΕΖΗΘΙΚΛΜΝΞΟΠΡΣΤΥΦΧΨΩ"


def _groups():
    a8, a9, a5 = _row(0xA8), _row(0xA9), _row(0xA5)
    groups = {
        "ㄱ": PUNCTUATION, "ㄴ": tuple(c for pair in BRACKETS for c in pair) + tuple("‘’“”"),
        "ㄷ": MATH, "ㄹ": _row(0xA7) + tuple("°′″℃℉Å‰￠￡￥￦€¤№㏇™㏂㏘℡®"),
        "ㅁ": SHAPES + ARROWS + tuple("♂♀㉿㈜"), "ㅂ": _row(0xA6),
        "ㅅ": tuple(c for c in a8 + a9 if 0x3200 <= ord(c) <= 0x327F),
        "ㅇ": tuple(c for c in a8 + a9 if 0x2460 <= ord(c) <= 0x24FF),
        "ㅈ": tuple(c for c in a5 if 0x2160 <= ord(c) <= 0x217F),
        "ㅊ": tuple("½⅓⅔¼¾⅛⅜⅝⅞¹²³⁴ⁿ₁₂₃₄"),
        "ㅋ": tuple(c for c in _row(0xA4) if ord(c) <= 0x3163),
        "ㅌ": tuple(c for c in _row(0xA4) if ord(c) > 0x3163),
        "ㅍ": tuple(c for c in a8 + a9 if ord(c) < 0x250),
        "ㅎ": tuple(GREEK_SMALL + GREEK_BIG),
    }
    for alias, key in {"문장부호":"ㄱ", "괄호":"ㄴ", "수학기호":"ㄷ", "단위기호":"ㄹ",
                       "도형":"ㅁ", "선문자":"ㅂ", "괄호한글":"ㅅ", "원문자":"ㅇ",
                       "로마숫자":"ㅈ", "분수":"ㅊ", "자모":"ㅋ", "옛한글":"ㅌ",
                       "라틴문자":"ㅍ", "그리스문자":"ㅎ"}.items():
        groups[alias] = groups[key]
    # Consonant aliases are gated by SymbolConverter's default-off option.
    groups.update({"화살표": ARROWS, "히라가나": _row(0xAA), "가타카나": _row(0xAB),
                   "키릴문자": _row(0xAC), "전각": _row(0xA3),
                   "특수문자": tuple(_unique(c for lead in range(0xA1, 0xAA) for c in _row(lead)))})
    return groups


GROUPS = _groups()
GROUPS["괄호"] = tuple(left + right for left, right in BRACKETS + QUOTES)
ALIASES = {
    "/": ("·", "ㆍ", "／", "÷"), "가운뎃점": ("·", "ㆍ"), "가운데점": ("·", "ㆍ"),
    "...": ("…", "……", "‥"), "줄임표": ("……", "…", "‥", "......"),
    "-": ("―", "—", "–", "−", "－"), "줄표": ("―", "—"), "붙임표": ("-", "‐"),
    "~": ("∼", "～"), "물결표": ("∼", "~", "～"),
    "'": ("‘", "’", "「", "」"), '"': ("“", "”", "『", "』"),
    "*": ("※", "×", "＊", "★", "☆"), "참고표": ("※",), "당구장": ("※",),
    "+": ("±", "＋"), "=": ("≠", "≡", "≒", "＝"), "곱하기": ("×",), "나누기": ("÷",),
    "더하기빼기": ("±",), "무한대": ("∞",), "루트": ("√",), "적분": ("∫", "∬", "∮"),
    "오른쪽화살표": ("→", "⇒"), "왼쪽화살표": ("←",), "양쪽화살표": ("↔", "⇔"),
    "소괄호": ("()", "（）"), "대괄호": ("[]", "［］", "【】", "〔〕"),
    "중괄호": ("{}", "｛｝"), "홑낫표": ("「」",), "겹낫표": ("『』",),
    "홑화살괄호": ("〈〉", "<>"), "겹화살괄호": ("≪≫", "《》"),
    "작은따옴표": ("‘’",), "큰따옴표": ("“”",), "쌍따옴표": ("“”",),
    "마침표": (".", "。"), "쉼표": (",", "、"), "빗금": ("/", "／"),
    "쌍점": (":", "："), "쌍반점": (";", "；"), "물음표": ("?", "？"), "느낌표": ("!", "！"),
    "하트": ("♥", "♡"), "별표": ("★", "☆"), "체크": ("✓", "✔"),
    "동그라미": ("○", "●", "◎"), "세모": ("△", "▲", "▽", "▼"), "네모": ("□", "■"),
    "별": ("★", "☆"), "음표": ("♪", "♩", "♬", "♫"), "샤프": ("♯",), "플랫": ("♭",),
    "따옴표": ("“”", "‘’", "『』", "「」"), "낫표": ("「」", "『』"),
    "원화": ("₩", "￦"), "유로": ("€",), "엔화": ("¥", "￥"), "저작권": ("©",),
    "등록상표": ("®",), "상표": ("™",), "도씨": ("℃",), "도에프": ("℉",),
}
for left, right in BRACKETS:
    ALIASES[left] = tuple(_unique(l for l, _ in BRACKETS))
    ALIASES[right] = tuple(_unique(r for _, r in BRACKETS))
for name, small, big in zip(GREEK_NAMES, GREEK_SMALL, GREEK_BIG):
    ALIASES[name] = (small, big)
    ALIASES["소문자" + name] = (small,)
    ALIASES["대문자" + name] = (big,)
for variant, name in {"쎄타":"세타", "크사이":"크시", "엡실런":"엡실론", "웁실론":"입실론"}.items():
    ALIASES[variant] = ALIASES[name]


class SymbolConverter(WordConverter):
    name = "기호·문자"

    def __init__(self, consonants=False):
        self.consonants = consonants

    def candidates(self, word, context=None):
        key = unicodedata.normalize("NFC", word)
        if len(key) == 1 and key in GROUPS and not self.consonants:
            return
        # Exact name/category lookup; do not replace substrings of normal prose.
        yield from ALIASES.get(key, GROUPS.get(key, ()))
        if len(key) >= 2 and (key[0], key[-1]) in BRACKETS + QUOTES:
            inner = key[1:-1]
            for left, right in BRACKETS + QUOTES:
                yield left + inner + right
        match = re.fullmatch(r"(동그라미|괄호)([1-9]|1[0-5])", key)
        if match:
            base = 0x2460 if match[1] == "동그라미" else 0x2474
            yield chr(base + int(match[2]) - 1)
