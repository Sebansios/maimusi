"""한국어 IME 설정·문장부호·괄호 정책.

일본어/중국어 IME에서 자주 제공하는 전각/반각, 구두점, 기호, 숫자,
후보 단축키, 라이브 변환 설정을 한국어 UI 용어로 표현한다. 플랫폼별
설정 창은 이 모듈의 dataclass와 settings_schema를 바인딩하면 된다.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field, fields
import re
from pathlib import Path
import unicodedata
from typing import Dict, Mapping, Optional

from .persistence import (
    atomic_json_save as _atomic_json_save, atomic_text_save as _atomic_text_save,
    checked_mapping, checked_text, checked_version, load_json,
)
from .spacing_preferences import SpacingPreferences
# Spacing and typography share the same syntax classifier and source offsets.
from .protected_text import PROTECTED_TEXT as _PROTECTED_TEXT


SETTINGS_FORMAT_VERSION = 3


WIDTH_MODES = ("preserve", "half", "full")


PUNCTUATION_PROFILES = {
    "korean": {
        "label": "한국어 기본(반각 ASCII)",
        "comma": ",", "period": ".", "question": "?", "exclamation": "!",
        "colon": ":", "semicolon": ";", "ellipsis": "…", "middle_dot": "·",
        "slash": "/", "backslash": "\\", "wave_dash": "~", "dash": "-",
        "reference": "※", "iteration": "々",
    },
    "korean_fullwidth": {
        "label": "한국어 전각",
        "comma": "，", "period": "．", "question": "？", "exclamation": "！",
        "colon": "：", "semicolon": "；", "ellipsis": "……", "middle_dot": "・",
        "slash": "／", "backslash": "＼", "wave_dash": "～", "dash": "－",
        "reference": "※", "iteration": "々",
    },
    "japanese": {
        "label": "일본어식",
        "comma": "、", "period": "。", "question": "？", "exclamation": "！",
        "colon": "：", "semicolon": "；", "ellipsis": "……", "middle_dot": "・",
        "slash": "／", "backslash": "＼", "wave_dash": "〜", "dash": "―",
        "reference": "※", "iteration": "々",
    },
    "chinese": {
        "label": "중국어식",
        "comma": "，", "period": "。", "question": "？", "exclamation": "！",
        "colon": "：", "semicolon": "；", "ellipsis": "……", "middle_dot": "・",
        "slash": "／", "backslash": "＼", "wave_dash": "～", "dash": "—",
        "reference": "※", "iteration": "々",
    },
    "east_asian_halfwidth": {
        "label": "동아시아식 반각",
        "comma": "､", "period": "｡", "question": "?", "exclamation": "!",
        "colon": ":", "semicolon": ";", "ellipsis": "...", "middle_dot": "･",
        "slash": "/", "backslash": "\\", "wave_dash": "~", "dash": "-",
        "reference": "※", "iteration": "々",
    },
    "korean_mixed": {
        "label": "한국어 혼합(구두점만 전각)",
        "comma": ",", "period": ".", "question": "？", "exclamation": "！",
        "colon": ":", "semicolon": ";", "ellipsis": "…", "middle_dot": "·",
        "slash": "/", "backslash": "\\", "wave_dash": "~", "dash": "-",
        "reference": "※", "iteration": "々",
    },
    "japanese_mixed": {
        "label": "일본어 혼합(구두점 일부 반각)",
        "comma": "、", "period": "。", "question": "?", "exclamation": "!",
        "colon": ":", "semicolon": ";", "ellipsis": "…", "middle_dot": "・",
        "slash": "/", "backslash": "\\", "wave_dash": "~", "dash": "-",
        "reference": "※", "iteration": "々",
    },
}


BRACKET_PROFILES = {
    "ascii": {
        "label": "ASCII",
        "parenthesis": ("(", ")"), "square": ("[", "]"), "curly": ("{", "}"),
        "angle": ("<", ">"), "single_quote": ("'", "'"), "double_quote": ('"', '"'),
    },
    "korean": {
        "label": "한국어 권장",
        "parenthesis": ("(", ")"), "square": ("[", "]"), "curly": ("{", "}"),
        "angle": ("〈", "〉"), "single_quote": ("‘", "’"), "double_quote": ("“", "”"),
        "corner": ("「", "」"), "double_corner": ("『", "』"),
        "double_angle": ("《", "》"), "lenticular": ("【", "】"),
        "tortoise": ("〔", "〕"), "white_corner": ("〖", "〗"),
        "double_lenticular": ("〘", "〙"), "triple_lenticular": ("〚", "〛"),
        "corner_vertical": ("﹁", "﹂"), "double_corner_vertical": ("﹃", "﹄"),
    },
    "east_asian": {
        "label": "동아시아 표준 괄호 전체",
        "parenthesis": ("（", "）"), "square": ("［", "］"), "curly": ("｛", "｝"),
        "angle": ("〈", "〉"), "double_angle": ("《", "》"),
        "corner": ("「", "」"), "double_corner": ("『", "』"),
        "lenticular": ("【", "】"), "tortoise": ("〔", "〕"),
        "white_corner": ("〖", "〗"), "double_lenticular": ("〘", "〙"),
        "triple_lenticular": ("〚", "〛"), "corner_vertical": ("﹁", "﹂"),
        "double_corner_vertical": ("﹃", "﹄"),
        "small_parenthesis": ("﹙", "﹚"), "small_square": ("﹝", "﹞"),
        "small_curly": ("﹛", "﹜"), "small_angle": ("﹤", "﹥"),
        "white_square": ("⟦", "⟧"), "mathematical_angle": ("⟨", "⟩"),
    },
    "japanese": {
        "label": "일본어식",
        "parenthesis": ("（", "）"), "square": ("［", "］"), "curly": ("｛", "｝"),
        "angle": ("〈", "〉"), "double_angle": ("《", "》"),
        "single_quote": ("「", "」"), "double_quote": ("『", "』"),
        "lenticular": ("【", "】"), "tortoise": ("〔", "〕"),
        "white_corner": ("〖", "〗"), "double_lenticular": ("〘", "〙"),
        "triple_lenticular": ("〚", "〛"), "corner_vertical": ("﹁", "﹂"),
        "double_corner_vertical": ("﹃", "﹄"),
    },
    "chinese": {
        "label": "중국어식",
        "parenthesis": ("（", "）"), "square": ("［", "］"), "curly": ("｛", "｝"),
        "angle": ("〈", "〉"), "double_angle": ("《", "》"),
        "single_quote": ("「", "」"), "double_quote": ("『", "』"),
        "lenticular": ("【", "】"), "white_corner": ("〖", "〗"),
        "tortoise": ("〔", "〕"), "double_lenticular": ("〘", "〙"),
        "triple_lenticular": ("〚", "〛"), "corner_vertical": ("﹁", "﹂"),
        "double_corner_vertical": ("﹃", "﹄"),
    },
    "fullwidth": {
        "label": "전각 괄호",
        "parenthesis": ("（", "）"), "square": ("［", "］"), "curly": ("｛", "｝"),
        "angle": ("＜", "＞"), "single_quote": ("‘", "’"), "double_quote": ("“", "”"),
    },
}


PUNCTUATION_ALIASES = {
    ",": "comma", "，": "comma", "、": "comma", "､": "comma",
    ".": "period", "．": "period", "。": "period", "｡": "period",
    "?": "question", "？": "question", "!": "exclamation", "！": "exclamation",
    ":": "colon", "：": "colon", ";": "semicolon", "；": "semicolon",
    "…": "ellipsis", "⋯": "ellipsis", "·": "middle_dot", "・": "middle_dot",
    "･": "middle_dot", "/": "slash", "／": "slash", "\\": "backslash", "＼": "backslash",
    "~": "wave_dash", "～": "wave_dash", "〜": "wave_dash",
    "-": "dash", "－": "dash", "—": "dash", "―": "dash", "–": "dash",
    "※": "reference", "々": "iteration",
}


def _fullwidth_ascii(value: str) -> str:
    return "".join(
        chr(ord(char) + 0xFEE0) if 0x21 <= ord(char) <= 0x7E
        else "\u3000" if char == " "
        else char
        for char in value
    )


def _halfwidth_ascii(value: str) -> str:
    return "".join(
        chr(ord(char) - 0xFEE0) if 0xFF01 <= ord(char) <= 0xFF5E
        else " " if char == "\u3000"
        else char
        for char in value
    )


# Only Unicode narrow decompositions are width mappings; compatibility
# normalization of the entire document would change unrelated characters.
_KATA_FULL = {
    chr(cp): chr(int(unicodedata.decomposition(chr(cp)).split()[1], 16))
    for cp in range(0xFF61, 0xFFA0)
    if unicodedata.decomposition(chr(cp)).startswith("<narrow>")
}
_KATA_HALF = {full: half for half, full in _KATA_FULL.items()}
_KATA_HALF.update({"゛": "ﾞ", "゜": "ﾟ"})
_KATA_RUN = re.compile(r"[\uFF61-\uFF9F\u30A0-\u30FF\u3099-\u309C]+")

# Halfwidth Hangul decomposes to compatibility jamo, NOT to a composed syllable.
_JAMO_FULL = {
    chr(cp): chr(int(unicodedata.decomposition(chr(cp)).split()[1], 16))
    for cp in range(0xFFA0, 0xFFDD)
    if unicodedata.decomposition(chr(cp)).startswith("<narrow>")
}
_JAMO_HALF = {full: half for half, full in _JAMO_FULL.items()}


def _halfwidth_katakana(value: str) -> str:
    def convert(match):
        return "".join(_KATA_HALF.get(char, char) for char in unicodedata.normalize("NFD", match[0]))
    return _KATA_RUN.sub(convert, value)


def _fullwidth_katakana(value: str) -> str:
    def convert(match):
        return unicodedata.normalize("NFC", "".join(_KATA_FULL.get(char, char) for char in match[0]))
    return _KATA_RUN.sub(convert, value)


BRACKET_CATALOG = {
    key: pair for profile in BRACKET_PROFILES.values()
    for key, pair in profile.items() if key != "label"
}
BRACKET_CATALOG.update({
    "parenthesis": ("(", ")"), "square": ("[", "]"), "curly": ("{", "}"),
    "angle": ("〈", "〉"), "single_quote": ("‘", "’"), "double_quote": ("“", "”"),
    "ascii_angle": ("<", ">"), "ascii_single_quote": ("'", "'"),
    "ascii_double_quote": ('"', '"'), "fullwidth_parenthesis": ("（", "）"),
    "fullwidth_square": ("［", "］"), "fullwidth_curly": ("｛", "｝"),
    "fullwidth_angle": ("＜", "＞"), "halfwidth_corner": ("｢", "｣"),
    "guillemets": ("«", "»"), "single_guillemets": ("‹", "›"),
    "low_double_quote": ("„", "“"), "low_single_quote": ("‚", "‘"),
    "double_mathematical_angle": ("⟪", "⟫"), "white_parenthesis": ("⦅", "⦆"),
    "vertical_parenthesis": ("︵", "︶"), "vertical_square": ("﹇", "﹈"),
    "vertical_curly": ("︷", "︸"), "vertical_lenticular": ("︻", "︼"),
})
BRACKET_LABELS = dict(zip(BRACKET_CATALOG, (
    # All labels also include the actual pair in the generated schema.
    "소괄호", "대괄호", "중괄호", "홑화살괄호", "작은따옴표", "큰따옴표",
)))
BRACKET_LABELS.update({
    "corner": "홑낫표", "double_corner": "겹낫표", "double_angle": "겹화살괄호",
    "lenticular": "검은렌즈괄호", "tortoise": "거북등괄호", "white_corner": "흰렌즈괄호",
    "double_lenticular": "흰거북등괄호", "triple_lenticular": "흰사각괄호",
    "corner_vertical": "세로 홑낫표", "double_corner_vertical": "세로 겹낫표",
    "small_parenthesis": "작은 소괄호", "small_square": "작은 거북등괄호",
    "small_curly": "작은 중괄호", "small_angle": "작은 화살괄호",
    "white_square": "수학 흰사각괄호", "mathematical_angle": "수학 홑화살괄호",
    "ascii_angle": "ASCII 화살괄호", "ascii_single_quote": "직선 작은따옴표",
    "ascii_double_quote": "직선 큰따옴표", "fullwidth_parenthesis": "전각 소괄호",
    "fullwidth_square": "전각 대괄호", "fullwidth_curly": "전각 중괄호",
    "fullwidth_angle": "전각 화살괄호", "halfwidth_corner": "반각 홑낫표",
    "guillemets": "겹빗금따옴표", "single_guillemets": "홑빗금따옴표",
    "low_double_quote": "아래 큰따옴표", "low_single_quote": "아래 작은따옴표",
    "double_mathematical_angle": "수학 겹화살괄호", "white_parenthesis": "흰소괄호",
    "vertical_parenthesis": "세로 소괄호", "vertical_square": "세로 대괄호",
    "vertical_curly": "세로 중괄호", "vertical_lenticular": "세로 렌즈괄호",
})
CONVERTER_NAMES = ("사용자 변환", "이모지", "한자", "단위", "날짜", "자모·유니코드")
WIDTH_LABELS = {"preserve": "원문 유지", "half": "반각", "full": "전각"}
UNSUPPORTED_INPUT_FIELDS = (
    "input_layout", "live_conversion", "convert_with_punctuation",
    "candidate_shortcuts", "auto_ascii_conversion", "reconversion",
    "shift_mode", "space_action", "half_fullwidth_hotkey",
)
def _choice(value, choices, label):
    if type(value) is not str or value not in choices:
        raise ValueError(f"{label}: {tuple(choices)} 중 하나가 필요합니다")


def _bool(value, label):
    if type(value) is not bool:
        raise TypeError(f"{label}: 참/거짓 값이 필요합니다")


def _names(value, label):
    if not isinstance(value, (list, tuple)):
        raise TypeError(f"{label}: 목록이 필요합니다")
    for name in value:
        _choice(name, CONVERTER_NAMES, label)
    if len(set(value)) != len(value):
        raise ValueError(f"{label}: 중복된 변환기가 있습니다")


@dataclass
class InputBehaviorSettings:
    # Retained to read v1 data without dropping fields; unsupported fields are
    # explicitly excluded from the release UI and listed in schema metadata.
    input_layout: str = "두벌식"
    live_conversion: bool = False
    convert_with_punctuation: bool = True
    candidate_shortcuts: str = "digits"
    fullwidth_numerals: bool = False
    fullwidth_latin: bool = False
    auto_ascii_conversion: bool = False
    punctuation_conversion: bool = True
    reconversion: bool = True
    private_mode: bool = False
    shift_mode: str = "없음"
    space_action: str = "띄어쓰기 확정 후 후보 순환"
    half_fullwidth_hotkey: str = "SHIFT+SPACE"

    def __post_init__(self):
        self.validate()

    def validate(self):
        for name in (
            "live_conversion", "convert_with_punctuation", "fullwidth_numerals",
            "fullwidth_latin", "auto_ascii_conversion", "punctuation_conversion",
            "reconversion", "private_mode",
        ):
            _bool(getattr(self, name), name)
        _choice(self.input_layout, ("두벌식", "세벌식390", "세벌식최종", "사용자"), "input_layout")
        _choice(self.candidate_shortcuts, ("digits", "letters", "none"), "candidate_shortcuts")
        for name in ("shift_mode", "space_action", "half_fullwidth_hotkey"):
            checked_text(getattr(self, name), name, maximum=128)
        return self


@dataclass
class TypographySettings:
    ascii_width: str = "half"
    digit_width: str = "half"
    latin_width: str = "half"
    punctuation_width: str = "preserve"
    symbol_width: str = "preserve"
    katakana_width: str = "preserve"
    hangul_jamo_width: str = "preserve"
    space_width: str = "half"
    punctuation_profile: str = "korean"
    punctuation_overrides: Dict[str, str] = field(default_factory=dict)
    bracket_profile: str = "korean"
    bracket_overrides: dict = field(default_factory=dict)
    auto_pair_brackets: bool = True
    smart_quotes: bool = True
    normalize_unicode: str = "NFC"
    conversion_learning: bool = True
    enabled_converters: list = field(default_factory=lambda: list(CONVERTER_NAMES))
    converter_order: list = field(default_factory=lambda: list(CONVERTER_NAMES))
    input: InputBehaviorSettings = field(default_factory=InputBehaviorSettings)
    spacing: SpacingPreferences = field(default_factory=SpacingPreferences)

    def __post_init__(self):
        self.validate()

    @property
    def learning_enabled(self):
        return self.conversion_learning and not self.input.private_mode

    def validate(self):
        for name in (
            "ascii_width", "digit_width", "latin_width", "punctuation_width",
            "symbol_width", "katakana_width", "hangul_jamo_width", "space_width",
        ):
            _choice(getattr(self, name), WIDTH_MODES, name)
        _choice(self.punctuation_profile, PUNCTUATION_PROFILES, "punctuation_profile")
        _choice(self.bracket_profile, BRACKET_PROFILES, "bracket_profile")
        # NFKC is deliberately not accepted: it changes Hanja, circled numbers,
        # jamo and other intentional compatibility characters, beyond width.
        _choice(self.normalize_unicode, ("NFC", "none"), "normalize_unicode")
        for name in ("auto_pair_brackets", "smart_quotes", "conversion_learning"):
            _bool(getattr(self, name), name)
        checked_mapping(self.punctuation_overrides, PUNCTUATION_PROFILES["korean"], "구두점 재정의")
        for key, value in self.punctuation_overrides.items():
            if key == "label":
                raise ValueError("구두점 재정의에 label은 사용할 수 없습니다")
            checked_text(value, "구두점", maximum=16)
            if any(char.isspace() or char.isalnum() for char in value):
                raise ValueError("구두점 재정의에는 공백·문자·숫자를 사용할 수 없습니다")
        checked_mapping(self.bracket_overrides, BRACKET_CATALOG, "괄호 재정의")
        for pair in self.bracket_overrides.values():
            if not isinstance(pair, (list, tuple)) or len(pair) != 2:
                raise ValueError("괄호는 여는 부호와 닫는 부호 한 쌍이어야 합니다")
            for part in pair:
                checked_text(part, "괄호", maximum=4)
                if any(char.isspace() or char.isalnum() for char in part):
                    raise ValueError("괄호에는 공백·문자·숫자를 사용할 수 없습니다")
        _names(self.enabled_converters, "enabled_converters")
        _names(self.converter_order, "converter_order")
        if not isinstance(self.input, InputBehaviorSettings):
            raise TypeError("input은 InputBehaviorSettings여야 합니다")
        self.input.validate()
        if not isinstance(self.spacing, SpacingPreferences):
            raise TypeError("spacing은 SpacingPreferences여야 합니다")
        self.spacing.validate()
        return self

    @classmethod
    def from_dict(cls, payload: Mapping):
        if not isinstance(payload, dict):
            raise TypeError("설정에는 JSON 객체가 필요합니다")
        checked_version(payload, SETTINGS_FORMAT_VERSION)
        if "settings" in payload:
            checked_mapping(payload, ("settings", "schema_version"))
            return cls.from_dict(payload["settings"])
        allowed = {item.name for item in fields(cls)}
        checked_mapping(payload, allowed | {"schema_version"})
        data = {key: value for key, value in payload.items() if key != "schema_version"}
        input_payload = data.pop("input", {})
        checked_mapping(input_payload, {item.name for item in fields(InputBehaviorSettings)}, "입력 설정")
        data["input"] = InputBehaviorSettings(**input_payload)
        data["spacing"] = SpacingPreferences.from_dict(data.pop("spacing", {}))
        # Copies avoid aliases to callers' dictionaries and lists.
        for name in ("punctuation_overrides", "bracket_overrides"):
            if name in data and isinstance(data[name], dict):
                data[name] = dict(data[name])
        if isinstance(data.get("bracket_overrides"), dict):
            data["bracket_overrides"] = {
                key: tuple(value) if isinstance(value, (list, tuple)) else value
                for key, value in data["bracket_overrides"].items()
            }
        for name in ("enabled_converters", "converter_order"):
            if isinstance(data.get(name), (list, tuple)):
                data[name] = list(data[name])
        return cls(**data)

    def to_dict(self):
        self.validate()
        payload = asdict(self)
        payload["schema_version"] = SETTINGS_FORMAT_VERSION
        return payload

    def punctuation(self, symbol: str) -> str:
        key = PUNCTUATION_ALIASES.get(symbol, symbol)
        value = self.punctuation_overrides.get(key, PUNCTUATION_PROFILES[self.punctuation_profile].get(key, symbol))
        if self.punctuation_width == "half":
            return _halfwidth_ascii(value).translate(str.maketrans({"、": "､", "。": "｡", "・": "･"}))
        if self.punctuation_width == "full":
            return _fullwidth_ascii(value).translate(str.maketrans({"､": "、", "｡": "。", "･": "・"}))
        return value

    def format_text(self, text: str) -> str:
        """Format prose while keeping URL/identifier/numeric separators intact."""
        if type(text) is not str:
            raise TypeError("본문은 문자열이어야 합니다")
        self.validate()
        output, last = [], 0
        # The ASCII view keeps indices identical even for fullwidth digits.
        for match in _PROTECTED_TEXT.finditer(_halfwidth_ascii(text)):
            end = match.end()
            # Sentence punctuation immediately following a URL is still prose.
            if "://" in match[0] or match[0].startswith("www."):
                while end > match.start() and text[end - 1] in ".,!?。，！？":
                    end -= 1
            output.append(self._format_prose(text[last:match.start()]))
            output.append(text[match.start():end])
            last = end
        output.append(self._format_prose(text[last:]))
        return "".join(output)

    def _format_prose(self, text):
        if self.normalize_unicode == "NFC":
            # Do not normalize Korean compatibility or halfwidth jamo.
            text = unicodedata.normalize("NFC", text)
        digit_width = "full" if self.input.fullwidth_numerals else self.digit_width
        latin_width = "full" if self.input.fullwidth_latin else self.latin_width
        # Treat emitted multi-character punctuation atomically on subsequent
        # calls; otherwise a two-character ellipsis doubles on every format.
        emitted = {self.punctuation(key) for key in self.punctuation_overrides}
        if self.input.punctuation_conversion:
            emitted.add(self.punctuation("ellipsis"))
        emitted = sorted(emitted, key=len, reverse=True)
        output, index = [], 0
        while index < len(text):
            if self.input.punctuation_conversion:
                token = next((value for value in emitted if text.startswith(value, index)), None)
                if token:
                    output.append(token)
                    index += len(token)
                    continue
                ellipsis = re.match(r"(?:\.{3,}|[…⋯]+)", text[index:]) if text[index] in ".…⋯" else None
                if ellipsis:
                    output.append(self.punctuation("ellipsis"))
                    index += len(ellipsis[0])
                    continue
            char = text[index]
            index += 1
            if char in PUNCTUATION_ALIASES and self.input.punctuation_conversion:
                output.append(self.punctuation(char))
            elif ("0" <= char <= "9") or ("０" <= char <= "９"):
                output.append(self._apply_width(char, digit_width))
            elif ("A" <= char <= "Z") or ("a" <= char <= "z") or ("Ａ" <= char <= "Ｚ") or ("ａ" <= char <= "ｚ"):
                output.append(self._apply_width(char, latin_width))
            elif char in (" ", "\u3000"):
                output.append(self._apply_width(char, self.space_width))
            elif char in _JAMO_FULL or char in _JAMO_HALF:
                mapping = _JAMO_HALF if self.hangul_jamo_width == "half" else _JAMO_FULL
                output.append(char if self.hangul_jamo_width == "preserve" else mapping.get(char, char))
            elif _KATA_RUN.fullmatch(char):
                # Process voiced sequences together, not one character at a time.
                start = index - 1
                while index < len(text) and _KATA_RUN.fullmatch(text[index]):
                    index += 1
                output.append(self._apply_katakana_width(text[start:index]))
            elif 0x21 <= ord(char) <= 0x7E:
                mode = self.symbol_width if self.symbol_width != "preserve" else self.ascii_width
                output.append(self._apply_width(char, mode))
            elif 0xFF01 <= ord(char) <= 0xFF5E:
                # Both directions use the same effective mode, so full is stable.
                mode = self.symbol_width if self.symbol_width != "preserve" else self.ascii_width
                output.append(self._apply_width(char, mode))
            else:
                output.append(char)
        return "".join(output)

    @staticmethod
    def _apply_width(char: str, mode: str) -> str:
        return char if mode == "preserve" else (_fullwidth_ascii(char) if mode == "full" else _halfwidth_ascii(char))

    def _apply_katakana_width(self, text: str) -> str:
        if self.katakana_width == "preserve":
            return text
        return _fullwidth_katakana(text) if self.katakana_width == "full" else _halfwidth_katakana(text)

    def bracket_pair(self, kind: str = "double_quote"):
        if kind not in BRACKET_CATALOG:
            raise ValueError("지원하지 않는 괄호 종류입니다")
        return tuple(self.bracket_overrides.get(
            kind, BRACKET_PROFILES[self.bracket_profile].get(kind, BRACKET_CATALOG[kind])
        ))

    def wrap(self, text: str, kind: str = "double_quote") -> str:
        opening, closing = self.bracket_pair(kind)
        return opening + text + closing

    def quote_for_insertion(self, quote: str, before: str = "", after: str = "") -> str:
        """Pure insertion policy; the GUI owns event dispatch and cursor state."""
        if quote not in ("'", '"'):
            raise ValueError("직선 작은따옴표 또는 큰따옴표가 필요합니다")
        if not self.smart_quotes:
            return quote
        opening, closing = self.bracket_pair("single_quote" if quote == "'" else "double_quote")
        if quote == "'" and before[-1:].isalnum() and after[:1].isalnum():
            return closing  # Apostrophe inside a word.
        paragraph = before.rsplit("\n", 1)[-1]
        if opening != closing and paragraph.count(opening) > paragraph.count(closing):
            return closing
        if not before or before[-1].isspace() or before[-1] in "([{<〈《「『":
            return opening
        return closing

    def insertion_for_key(self, key: str, before: str = "", after: str = ""):
        """Return (inserted text, Python-character cursor offset)."""
        if key in ("'", '"'):
            quote = self.quote_for_insertion(key, before, after)
            if not self.smart_quotes:
                return key, len(key)
            opening, closing = self.bracket_pair("single_quote" if key == "'" else "double_quote")
            if quote == opening and self.auto_pair_brackets and opening != closing:
                return opening + closing, len(opening)
            return quote, len(quote)
        for kind, source in (("parenthesis", "("), ("square", "["), ("curly", "{"), ("angle", "<")):
            if key == source:
                opening, closing = self.bracket_pair(kind)
                return opening + closing if self.auto_pair_brackets else opening, len(opening)
        return key, len(key)

    def toggle_width(self):
        next_mode = "half" if self.latin_width == "full" else "full"
        self.latin_width = self.digit_width = self.punctuation_width = self.space_width = next_mode
        return next_mode


class SettingsStore:
    """Detached validation first; a failed update/load leaves live state intact."""

    def __init__(self, path: Optional[str | Path] = None, settings: Optional[TypographySettings] = None):
        self.path = Path(path) if path is not None else None
        self.settings = settings if settings is not None else TypographySettings()
        self.settings.validate()

    def load(self):
        if self.path is None or not self.path.exists():
            return self.settings
        candidate = TypographySettings.from_dict(load_json(self.path))
        self.settings = candidate
        return candidate

    def save(self):
        if self.path is None:
            raise ValueError("설정 저장 경로가 필요합니다")
        payload = self.settings.to_dict()
        if self.path.exists():
            # Even save-before-load cannot overwrite a future or corrupt file.
            TypographySettings.from_dict(load_json(self.path))
        _atomic_json_save(self.path, payload)
        return self.path

    def update(self, **values):
        allowed = {item.name for item in fields(TypographySettings)}
        unknown = set(values) - allowed
        if unknown:
            raise KeyError(next(iter(sorted(unknown))))
        candidate = self.settings.to_dict()
        for key, value in values.items():
            if key == "input":
                if isinstance(value, InputBehaviorSettings):
                    candidate[key] = asdict(value)
                elif isinstance(value, dict):
                    candidate[key] = {**candidate[key], **value}
                else:
                    raise TypeError("input에는 입력 설정 또는 객체가 필요합니다")
            else:
                candidate[key] = value
        validated = TypographySettings.from_dict(candidate)
        self.settings = validated
        return validated


def settings_schema():
    """Legacy tuple fields + explicit capabilities; no advertised no-op controls."""
    groups = [
        {"id": "spacing", "label": "띄어쓰기", "fields": [
            ("spacing", "범주별 설정·선택적 예외 사전", "spacing_preferences"),
        ]},
        {"id": "width", "label": "반각·전각", "fields": [
            ("ascii_width", "ASCII 기호 폭", WIDTH_MODES),
            ("digit_width", "숫자 폭", WIDTH_MODES), ("latin_width", "영문 폭", WIDTH_MODES),
            ("punctuation_width", "구두점 폭", WIDTH_MODES), ("space_width", "공백 폭", WIDTH_MODES),
            ("hangul_jamo_width", "한글 자모 폭", WIDTH_MODES),
        ]},
        {"id": "punctuation", "label": "문장부호", "fields": [
            ("punctuation_profile", "문장부호 형식", tuple(PUNCTUATION_PROFILES)),
            ("punctuation_overrides", "부호별 재정의", "mapping"),
        ]},
        {"id": "brackets", "label": "괄호·따옴표", "fields": [
            ("bracket_profile", "기본 괄호 세트", tuple(BRACKET_PROFILES)),
            ("bracket_overrides", "종류별 괄호 선택", "pairs"),
            ("auto_pair_brackets", "닫는 괄호 자동 삽입", "bool"),
            ("smart_quotes", "여닫는 따옴표 구분", "bool"),
        ]},
        {"id": "input", "label": "입력", "fields": [
            ("punctuation_conversion", "문장부호 변환", "bool"),
            ("private_mode", "비공개 모드 (학습과 학습 순서 사용 안 함)", "bool"),
        ]},
        {"id": "candidates", "label": "변환 후보·학습", "fields": [
            ("enabled_converters", "사용할 변환기", "names"),
            ("converter_order", "변환기 순서", "names"),
            ("conversion_learning", "확정한 후보만 이 기기에 학습", "bool"),
        ]},
        {"id": "advanced", "label": "고급 문자 폭", "advanced": True, "fields": [
            ("katakana_width", "가타카나 폭", WIDTH_MODES),
            ("symbol_width", "전각 기호 폭", WIDTH_MODES),
        ]},
    ]
    for group in groups:
        group["supported"] = True
        group["behavior"] = "editor" if group["id"] in ("brackets", "candidates") else "core"
        group["field_support"] = {item[0]: True for item in group["fields"]}
        group["choice_labels"] = dict(WIDTH_LABELS)
    groups.append({
        "id": "legacy", "label": "이전 형식 보존용 (미지원)", "supported": False,
        "fields": [], "unsupported_fields": list(UNSUPPORTED_INPUT_FIELDS),
    })
    return groups


__all__ = [
    "SETTINGS_FORMAT_VERSION", "WIDTH_MODES", "WIDTH_LABELS", "CONVERTER_NAMES",
    "PUNCTUATION_PROFILES", "BRACKET_PROFILES", "BRACKET_CATALOG", "BRACKET_LABELS",
    "InputBehaviorSettings", "TypographySettings", "SettingsStore", "settings_schema",
]
