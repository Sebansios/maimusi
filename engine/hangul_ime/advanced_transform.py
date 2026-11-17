"""확장 어절 변환기.

word_transform의 작은 호환 변환기를 대체한다. Unicode 이모지 레지스트리,
주입식 한자 사전, 광범위한 단위, 음력/연호/요일, 자모 반각과 code point를
각각 독립적인 변환기로 제공한다.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation, localcontext
from functools import lru_cache
import csv
import io
import json
import os
from pathlib import Path
import re
import unicodedata
from typing import Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

from .settings import _atomic_json_save, _atomic_text_save
from .conversion_types import WordConverter, _edges, _unique
from .converter_helpers import is_particle, is_derivation, stem_candidates, hanja_stem_candidates, token_edges, format_quantity
from .converter_pint import pint_candidates
from .symbols import SymbolConverter


DATA_DIR = Path(__file__).with_name("converter_data")


def _emoji_key(value: str) -> str:
    value = unicodedata.normalize("NFC", value).casefold().replace("_", " ").replace("-", " ")
    return re.sub(r"\s+", " ", value).strip()


@dataclass(frozen=True)
class EmojiRecord:
    sequence: str
    name: str
    status: str = "fully-qualified"


class EmojiRegistry:
    """Unicode emoji-test.txt 또는 CLDR annotations의 이름 인덱스."""

    def __init__(self, records: Iterable[EmojiRecord] = ()):
        self.records = tuple(records)
        self._by_name: Dict[str, List[str]] = {}
        for record in self.records:
            bucket = self._by_name.setdefault(_emoji_key(record.name), [])
            if record.sequence not in bucket:
                bucket.append(record.sequence)

    @classmethod
    def from_emoji_test(
        cls, path: os.PathLike | str, include_components: bool = True
    ) -> "EmojiRegistry":
        records = []
        with open(path, encoding="utf-8") as handle:
            for line in handle:
                if not line.strip() or line.lstrip().startswith("#") or ";" not in line or "#" not in line:
                    continue
                left, comment = line.split("#", 1)
                fields = [field.strip() for field in left.split(";")]
                if len(fields) < 2:
                    continue
                status = fields[1]
                if status != "fully-qualified" and not (
                    include_components and status == "component"
                ):
                    continue
                try:
                    sequence = "".join(chr(int(value, 16)) for value in fields[0].split())
                except ValueError as error:
                    raise ValueError("invalid Unicode emoji code point") from error
                metadata = comment.strip().split()
                if len(metadata) >= 3:
                    records.append(EmojiRecord(sequence, " ".join(metadata[2:]), status))
        return cls(records)

    @classmethod
    def from_cldr_annotations(cls, path: os.PathLike | str) -> "EmojiRegistry":
        with open(path, encoding="utf-8") as handle:
            payload = json.load(handle)
        if not isinstance(payload, Mapping):
            raise ValueError("CLDR annotations must be an object")
        annotations = payload.get("annotationsDerived", payload.get("annotations", payload))
        if isinstance(annotations, Mapping):
            annotations = annotations.get("annotations", annotations)
        if not isinstance(annotations, Mapping):
            raise ValueError("CLDR annotations must be an object")
        records = []
        for sequence, data in annotations.items():
            if not isinstance(data, Mapping):
                continue
            names = []
            for field in ("tts", "default"):
                value = data.get(field, []) or []
                names.extend([value] if isinstance(value, str) else value)
            for name in _unique(names):
                if isinstance(name, str):
                    records.append(EmojiRecord(sequence, name))
        return cls(records)

    def lookup(self, name: str) -> Tuple[str, ...]:
        return tuple(self._by_name.get(_emoji_key(name), ()))

    def __len__(self):
        return len(self.records)

    @property
    def sequence_count(self):
        return len({record.sequence for record in self.records})

    @classmethod
    @lru_cache(maxsize=1)
    def bundled(cls):
        official = cls.from_emoji_test(DATA_DIR / "emoji-test-17.0.txt")
        canonical = {record.sequence.replace("\ufe0f", ""): record.sequence for record in official.records}
        records = list(official.records)
        for language in ("ko", "en"):
            for kind in ("annotations", "derived"):
                localized = cls.from_cldr_annotations(DATA_DIR / f"cldr-48.2-{language}-{kind}.json")
                for record in localized.records:
                    sequence = canonical.get(record.sequence.replace("\ufe0f", ""))
                    if sequence:
                        records.append(EmojiRecord(sequence, record.name))
        return cls(records)


class EmojiConverter(WordConverter):
    name = "이모지"
    DEFAULTS = {
        "사랑": "❤️", "사랑해": "❤️", "사랑해요": "❤️", "좋아": "👍",
        "좋아요": "👍", "축하": "🎉", "축하해": "🎉", "웃음": "😂",
        "웃겨": "😂", "울음": "😭", "슬픔": "😢", "화남": "😡",
        "감사": "🙏", "고마워": "🙏", "안녕": "👋", "주의": "⚠️",
        "경고": "⚠️", "불": "🔥", "별": "⭐", "커피": "☕",
        "맥주": "🍺", "음식": "🍽️", "강아지": "🐶", "고양이": "🐱",
        "여행": "✈️", "집": "🏠", "학교": "🏫", "생일": "🎂",
        "완료": "✅", "실패": "❌",
    }
    KOREAN_ALIASES = {
        "사랑": ("red heart",), "좋아": ("thumbs up",),
        "축하": ("party popper",), "웃음": ("face with tears of joy",),
        "울음": ("loudly crying face",), "슬픔": ("crying face",),
        "화남": ("enraged face",), "감사": ("folded hands",),
        "안녕": ("waving hand",), "경고": ("warning",), "불": ("fire",),
        "별": ("star",), "커피": ("hot beverage",), "강아지": ("dog face",),
        "고양이": ("cat face",), "여행": ("airplane",), "집": ("house",),
        "학교": ("school",), "생일": ("birthday cake",),
        "완료": ("check mark button",), "실패": ("cross mark",),
    }

    def __init__(
        self,
        mapping: Optional[Mapping[str, str | Sequence[str]]] = None,
        registry: Optional[EmojiRegistry] = None,
        emoji_test_path: Optional[os.PathLike | str] = None,
    ):
        self.mapping = dict(self.DEFAULTS)
        if mapping:
            self.mapping.update(mapping)
        path = emoji_test_path or os.environ.get("HANGUL_IME_EMOJI_TEST")
        if registry is not None:
            self.registry = registry
        elif path:
            self.registry = EmojiRegistry.from_emoji_test(path)
        else:
            self.registry = EmojiRegistry.bundled()

    @property
    def registry_size(self):
        return len(self.registry)

    def lookup(self, name):
        mapped = self.mapping.get(name, ())
        values = list((mapped,) if isinstance(mapped, str) else mapped)
        values.extend(self.registry.lookup(name))
        for alias in self.KOREAN_ALIASES.get(name, ()):
            values.extend(self.registry.lookup(alias))
        return tuple(_unique(values))

    def candidates(self, word, context=None):
        leading, core, trailing = token_edges(word)
        for base, particle in stem_candidates(core):
            values = self.lookup(base)
            if values:
                for emoji in values:
                    yield leading + emoji + particle + trailing
                return


@lru_cache(maxsize=1)
def _bundled_hanja():
    entries = {}
    with (DATA_DIR / "hanja-libhangul-0.2.0.txt").open(encoding="utf-8") as handle:
        for line in handle:
            if line.startswith("#") or not line.strip():
                continue
            word, target, _comment = line.rstrip("\r\n").split(":", 2)
            entries.setdefault(word, []).append(target)
    return {word: tuple(_unique(values)) for word, values in entries.items()}


@lru_cache(maxsize=1)
def _hanja_meanings():
    """(소리, 한자 한 글자) -> 훈음, 예: ("학", "學") -> "배울 학" (libhangul 한 글자 항목)."""
    meanings = {}
    with (DATA_DIR / "hanja-libhangul-0.2.0.txt").open(encoding="utf-8") as handle:
        for line in handle:
            if line.startswith("#") or not line.strip():
                continue
            word, target, comment = line.rstrip("\r\n").split(":", 2)
            # 뜻이 여러 개면 첫 뜻만("가르침 교, 가르칠 교" -> "가르침 교"), 소리가 빠졌으면 붙인다("강할" -> "강할 강").
            gloss = comment.split(",")[0].strip()
            if len(word) == 1 and len(target) == 1 and gloss and (word, target) not in meanings:
                # 두음 법칙 소리로 찾은 글자는 본음 훈음 그대로 둔다(이:理 -> "다스릴 리").
                said = gloss.endswith(word) or _initial_sound(gloss[-1]) == word
                meanings[(word, target)] = gloss if said else f"{gloss} {word}"
    return meanings


@lru_cache(maxsize=1)
def _hanja_by_gloss():
    """훈음 -> [(한자, 소리, 훈음)], 예: "살찔비" -> [("肥", "비", "살찔 비")].

    libhangul 한 글자 항목의 모든 뜻을 쓴다(물 수, 고를 수 -> 물수·고를수). 두음 법칙 소리로도
    찾는다(다스릴리·다스릴이 -> 理). 자주 쓰는 한자가 앞에 온다."""
    index = {}
    with (DATA_DIR / "hanja-libhangul-0.2.0.txt").open(encoding="utf-8") as handle:
        for line in handle:
            if line.startswith("#") or not line.strip():
                continue
            word, target, comment = line.rstrip("\r\n").split(":", 2)
            if len(word) != 1 or len(target) != 1:
                continue
            for gloss in comment.split(","):
                gloss = gloss.strip()
                if not gloss:
                    continue
                said = gloss.endswith(word) or _initial_sound(gloss[-1]) == word
                full = gloss if said else f"{gloss} {word}"
                key = full.replace(" ", "")
                for k in {key, key[:-1] + word}:
                    if len(k) >= 2 and all("가" <= c <= "힣" for c in k):
                        entries = index.setdefault(k, [])
                        if all(e[0] != target for e in entries):
                            entries.append((target, word, full))
    usage = _hanja_usage()
    for entries in index.values():
        entries.sort(key=lambda e: -usage.get(e[0], (False, False, 0))[2])
    return index


def hanja_gloss_split(text, max_parts=4):
    """훈음을 이어 쓴 말을 훈음 단위로 나눈다: "배울학학교교" -> ["배울학", "학교교"]. 안 되면 None.

    조각이 적은 쪽을 고른다. 한 조각이면 그 자체가 훈음이다."""
    index = _hanja_by_gloss()
    if not text or len(text) > 8 * max_parts:
        return None
    best = {len(text): []}
    for i in range(len(text) - 1, -1, -1):
        options = [[text[i:j]] + best[j] for j in range(i + 2, min(len(text), i + 8) + 1)
                   if j in best and text[i:j] in index and len(best[j]) < max_parts]
        if options:
            best[i] = min(options, key=len)
    return best.get(0)


def _initial_sound(syllable):
    """두음 법칙을 적용한 소리: 리 -> 이, 녀 -> 여, 라 -> 나. 해당 없으면 그대로."""
    code = ord(syllable) - 0xAC00
    if not 0 <= code < 11172:
        return syllable
    initial, vowel, final = code // 588, code % 588 // 28, code % 28
    front = vowel in (2, 6, 7, 12, 17, 20)   # ㅑ ㅕ ㅖ ㅛ ㅠ ㅣ
    if initial == 5:                           # ㄹ
        initial = 11 if front else 2           # ㅇ or ㄴ
    elif initial == 2 and front:               # ㄴ
        initial = 11
    return chr(0xAC00 + initial * 588 + vowel * 28 + final)


def _needs_font_fallback(text):
    """CJK 확장 E 이후 글자(𮕩 등)는 Noto CJK를 비롯한 흔한 글꼴에 없다."""
    return any(ord(c) >= 0x2B820 for c in text)


def hanja_gloss(reading, hanja, max_chars=4):
    """한자 단어의 글자별 훈음, 예: ("학교", "學校") -> "배울 학, 학교 교".

    글자마다 훈음이 있을 때만 돌려주고, 하나라도 없거나 너무 길면 빈 문자열."""
    if len(reading) != len(hanja) or not 0 < len(hanja) <= max_chars:
        return ""
    meanings = _hanja_meanings()
    to_ks, to_edu = _hanja_forms()
    parts = []
    for r, c in zip(reading, hanja):
        gloss = meanings.get((r, c)) or meanings.get((r, to_ks.get(c, c))) or meanings.get((r, to_edu.get(c, c)))
        if not gloss:
            return ""
        parts.append(gloss)
    return ", ".join(parts)


@lru_cache(maxsize=1)
def _hanja_usage():
    """char -> (education hanja, KS X 1001, frequency)."""
    table = {}
    path = DATA_DIR / "hanja-usage-unihan-17.0.tsv"
    if path.exists():
        with path.open(encoding="utf-8") as handle:
            for line in handle:
                if line.startswith("#") or not line.strip():
                    continue
                char, edu, ks, freq, _grade = line.rstrip("\n").split("\t")
                table[char] = (edu == "1", ks == "1", int(freq))
    return table


@lru_cache(maxsize=1)
def _hanja_forms():
    """(education form -> KS form, KS form -> education form)."""
    to_ks, to_edu = {}, {}
    path = DATA_DIR / "hanja-forms.tsv"
    if path.exists():
        with path.open(encoding="utf-8") as handle:
            for line in handle:
                if line.startswith("#") or not line.strip():
                    continue
                edu, ks = line.rstrip("\n").split("\t")
                to_ks[edu] = ks
                to_edu[ks] = edu
    return to_ks, to_edu


HANJA_FORMS = ("education", "ks")
HANJA_PRESENTATIONS = ("hanja", "hangul_hanja", "hanja_hangul", "hangulhanja")


def _is_hanja(c):
    o = ord(c)
    return 0x3400 <= o <= 0x4DBF or 0x4E00 <= o <= 0x9FFF or 0xF900 <= o <= 0xFAFF or 0x20000 <= o <= 0x3FFFF


class HanjaConverter(WordConverter):
    """BSD-licensed libhangul dictionary with a persistent user overlay.

    Candidates are ranked for an input method (see ``ranked_candidates``):
    forms follow the Korean education hanja standard (強, 豐, 敎); allowed
    variant forms (强, 豊) and words with characters outside the 1,800
    education hanja come last."""

    name = "한자"
    DEFAULTS = {
        "한국": "韓國", "한국어": "韓國語", "한자": "漢字", "학교": "學校",
        "학생": "學生", "선생": "先生", "사람": "人", "시간": "時間",
        "날짜": "日期", "단위": "單位", "변환": "變換", "기능": "機能",
        "문장": "文章", "어절": "語節", "자동": "自動", "자동차": "自動車",
        "입력": "入力", "출력": "出力", "공부": "工夫", "연구": "硏究",
        "자료": "資料", "문서": "文書", "내용": "內容", "작업": "作業",
        "사용": "使用", "선택": "選擇", "오늘": "今日", "내일": "明日",
        "어제": "昨日", "현재": "現在", "미래": "未來", "방법": "方法",
        "결과": "結果", "문제": "問題", "정보": "情報", "개발": "開發",
        "구현": "具現", "모델": "模型", "언어": "言語", "영어": "英語",
        "일본어": "日本語", "중국어": "中國語", "날": "日", "달": "月",
        "년": "年", "주": "週", "요일": "曜日", "변환기": "變換器",
    }

    def __init__(self, mapping=None, lexicon_path=None, analyzer=None, forms="education", presentation="hanja",
                 gloss_search=False):
        # 훈음으로 한자 찾기(살찔비 -> 肥). 선택 기능이라 켰을 때만 쓴다.
        self.gloss_search = gloss_search
        # analyzer(text) -> [(start, length[, form, tag]), ...] morpheme spans,
        # used to reject stem splits that cut a single word (고양이 is not
        # 고양+이) and, with form/tag, to read 위한 as 위하/VV + ㄴ (爲한).
        self.analyzer = analyzer
        # "education": normative forms of the education hanja (強, 豐) first;
        # "ks": the KS X 1001 forms (强, 豊) first.
        if forms not in HANJA_FORMS:
            raise ValueError("한자 자형 기준은 education 또는 ks입니다")
        self.forms = forms
        if presentation not in HANJA_PRESENTATIONS:
            raise ValueError("한자 변환 표기 방식이 올바르지 않습니다")
        self.presentation = presentation
        self.mapping = dict(_bundled_hanja())
        for key, value in self.DEFAULTS.items():
            self.mapping.setdefault(key, (value,))
        self._builtin_keys = frozenset(self.mapping)
        self.user_mapping = {}
        self.disabled = set()
        self.source = "libhangul 0.2.0 (BSD-3-Clause) + compatibility seed"
        if lexicon_path:
            self.load_lexicon(lexicon_path)
        if mapping:
            self.update(mapping)

    @property
    def dictionary_source(self):
        return self.source

    def update(self, mapping):
        validated = self._validate_entries(mapping)
        for key, values in validated.items():
            self.mapping[key] = values
            self.user_mapping[key] = values
            self.disabled.discard(key)

    @staticmethod
    def _validate_entries(mapping):
        if not isinstance(mapping, Mapping):
            raise ValueError("한자 항목은 객체여야 합니다")
        validated = {}
        for key, value in mapping.items():
            if not isinstance(key, str) or not key.strip() or key.startswith("#") or any(c in key for c in "\r\n\t"):
                raise ValueError("한자 단어가 올바르지 않습니다")
            if isinstance(value, str):
                values = (value,)
            elif isinstance(value, (list, tuple)):
                values = tuple(value)
            else:
                raise ValueError("한자 후보는 문자열 또는 문자열 목록이어야 합니다")
            if not values or any(not isinstance(v, str) or not v.strip() or any(c in v for c in "\r\n\t") for v in values):
                raise ValueError("빈 한자 후보 또는 잘못된 후보입니다")
            validated[key] = tuple(_unique(values))
        return validated

    def add_entry(self, word, hanja):
        self.update({word: hanja})
        return self

    def remove_entry(self, word):
        self.user_mapping.pop(word, None)
        if word in self._builtin_keys:
            self.disabled.add(word)
        else:
            self.mapping.pop(word, None)
            self.disabled.discard(word)
        return self

    def load_lexicon(self, path):
        path = Path(path)
        entries = {}
        disabled = set()
        if path.suffix.lower() == ".json":
            with path.open(encoding="utf-8-sig") as handle:
                payload = json.load(handle)
            if not isinstance(payload, Mapping):
                raise ValueError("한자 JSON 사전은 객체여야 합니다")
            if isinstance(payload.get("schema_version"), int) or isinstance(payload.get("entries"), Mapping):
                if payload.get("schema_version", 1) != 1:
                    raise ValueError("지원하지 않는 한자 사전 버전입니다")
                entries = self._validate_entries(payload.get("entries", {}))
                raw_disabled = payload.get("disabled", [])
                if not isinstance(raw_disabled, list) or any(not isinstance(key, str) or not key.strip() or any(c in key for c in "\r\n\t") for key in raw_disabled):
                    raise ValueError("disabled는 단어 목록이어야 합니다")
                disabled.update(raw_disabled)
            else:
                entries = self._validate_entries(payload)
        else:
            with path.open(encoding="utf-8-sig") as handle:
                for line_number, line in enumerate(handle, 1):
                    line = line.rstrip("\r\n")
                    if not line or line.startswith("#"):
                        if line.startswith("# disabled\t"):
                            key = line.split("\t", 1)[1]
                            self._validate_entries({key: "disabled"})
                            disabled.add(key)
                        continue
                    fields = line.split("\t")
                    if len(fields) != 2:
                        raise ValueError(f"한자 TSV {line_number}행에 탭이 없습니다")
                    try:
                        values = next(csv.reader([fields[1]], strict=True))
                    except csv.Error as error:
                        raise ValueError(f"한자 TSV {line_number}행 후보 형식 오류") from error
                    validated = self._validate_entries({fields[0]: values})
                    entries[fields[0]] = tuple(_unique(entries.get(fields[0], ()) + validated[fields[0]]))
        # Validate the complete file before changing the active dictionary.
        self.update(entries)
        self.disabled.update(disabled)
        self.source = "libhangul 0.2.0 (BSD-3-Clause) + compatibility seed + 사용자 사전"

    def save_lexicon(self, path):
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.suffix.lower() == ".json":
            payload = {"schema_version": 1, "entries": {key: list(value) for key, value in self.user_mapping.items()}, "disabled": sorted(self.disabled)}
            _atomic_json_save(path, payload)
        else:
            rows = []
            for key, values in sorted(self.user_mapping.items()):
                handle = io.StringIO(newline="")
                csv.writer(handle, lineterminator="\n").writerow(values)
                rows.append(f"{key}\t{handle.getvalue()}")
            text = "".join(rows)
            if self.disabled:
                text += "".join(f"# disabled\t{key}\n" for key in sorted(self.disabled))
            _atomic_text_save(path, text)
        return path

    def candidates(self, word, context=None):
        for text, _tier, _note in self.ranked_candidates(word, context):
            yield text

    def _split_ok(self, core, base, tail):
        if not tail or self.analyzer is None or is_derivation(tail):
            return True
        try:
            spans = self.analyzer(core)
        except Exception:
            return True
        return any(span[0] + span[1] == len(base) for span in spans)

    def _verb_split(self, core):
        """(어근, 꼬리) when the analyzer reads the word as an X하다/X되다 verb.

        위한·위해·대한·통해처럼 하다 동사의 줄어든 활용형은 낱말 전체가 사전의 다른
        말(胃寒, 危害, 大韓)과 같아 보여도 爲한·爲해·對한·通해가 먼저다. 분석기가
        첫 형태소를 VV/VA(위하, 대하)로 읽을 때만 쓴다(피해·방해 같은 명사는 제외).
        """
        if self.analyzer is None:
            return None
        try:
            spans = self.analyzer(core)
        except Exception:
            return None
        if not spans or len(spans[0]) < 4:
            return None
        start, _length, form, tag = spans[0][:4]
        if start != 0 or tag not in ("VV", "VA") or len(form) < 2 or form[-1] not in "하되":
            return None
        base = form[:-1]
        tail = core[len(base):]
        if not core.startswith(base) or not is_derivation(tail):
            return None
        return base, tail

    @staticmethod
    def _all_education(text):
        usage = _hanja_usage()
        if not usage:
            return True
        to_ks, to_edu = _hanja_forms()
        def edu(c):
            # Both glyph forms of an education hanja count (強 and 强, 𮕩 and 衰).
            return c in to_ks or c in to_edu or usage.get(c, (False, False, 0))[0]
        return all(edu(c) for c in text if _is_hanja(c))

    @staticmethod
    def _frequency(text):
        usage = _hanja_usage()
        return min((usage.get(c, (False, False, 0))[2] for c in text if _is_hanja(c)), default=0)

    def ranked_candidates(self, word, context=None):
        """[(text, tier, note)] with tier in top, common, variant, rare.

        top: the single most likely hanja word (only education hanja; the
        first dictionary entry, or the most frequent character for
        one-syllable stems with 하다/되다/... endings); common: other words
        written only with education hanja; variant: the same word in the
        other glyph standard, only when the chosen form needs a rare font
        (𮕩 -> 衰, see ``_needs_font_fallback``);
        rare: words with characters outside the education hanja (벽자).
        """
        leading, core, trailing = token_edges(word)
        gloss = self._gloss_candidates(leading, core, trailing) if self.gloss_search else []
        ranked = self._word_candidates(leading, core, trailing)
        if not gloss:
            return ranked
        # 사전에 낱말로 있으면(입구 -> 入口) 그것이 먼저, 훈음(입 구 -> 口)은 그 뒤.
        if core in self.mapping:
            head = [item for item in ranked if item[1] in ("top", "common")]
            tail = [item for item in ranked if item[1] not in ("top", "common")]
            return head + [(text, "common", note) for text, _tier, note in gloss] + tail
        return gloss + [(text, "common" if tier == "top" else tier, note) for text, tier, note in ranked]

    def _gloss_candidates(self, leading, core, trailing):
        """훈음으로 찾기: 살찔비 -> 肥, 배울학학교교 -> 學校."""
        parts = hanja_gloss_split(core)
        if not parts:
            return []
        index = _hanja_by_gloss()
        to_ks, to_edu = _hanja_forms()
        preferred = to_edu if self.forms == "education" else to_ks
        norm = lambda h: "".join(preferred.get(c, c) for c in h)
        if len(parts) == 1:
            choices = [(norm(h), reading, full) for h, reading, full in index[parts[0]]]
        else:
            firsts = [index[part][0] for part in parts]
            choices = [("".join(norm(h) for h, _, _ in firsts), "".join(r for _, r, _ in firsts),
                        ", ".join(f for _, _, f in firsts))]
        out, seen = [], set()
        for i, (hanja, reading, full) in enumerate(choices):
            if hanja in seen:
                continue
            seen.add(hanja)
            text = leading + self._present(reading, hanja) + trailing
            out.append((text, "top" if i == 0 else "common", full))
        return out

    def _present(self, reading, hanja):
        if self.presentation == "hangul_hanja":
            return reading + "(" + hanja + ")"
        if self.presentation == "hanja_hangul":
            return hanja + "(" + reading + ")"
        if self.presentation == "hangulhanja":
            return reading + hanja
        return hanja

    def _word_candidates(self, leading, core, trailing):
        found = None
        for base, tail in hanja_stem_candidates(core):
            if base in self.disabled:
                return []
            if not self.mapping.get(base) or not self._split_ok(core, base, tail):
                continue
            found = (base, tail)
            break
        if found is None:
            return []
        ranked = self._rank(leading, trailing, *found)
        verb = self._verb_split(core) if not is_derivation(found[1]) else None
        if verb and verb != found and verb[0] not in self.disabled and self.mapping.get(verb[0]):
            # 하다 동사로 읽은 쪽이 먼저. 낱말 전체의 한자어는 그 뒤로 내린다.
            demoted = [(text, "common" if tier == "top" else tier, note) for text, tier, note in ranked]
            ranked = self._rank(leading, trailing, *verb) + demoted
        return ranked

    # 한 글자 어근 + 하다 동사·형용사에서 흔히 쓰는 한자(對하다, 因하다). 글자 빈도로
    # 고르면 大한·人해가 먼저 나오므로 이 표가 앞선다. 하·해·했·한·할·함·합 꼬리에만 쓴다
    # (속히는 速히, 속한은 屬한).
    HA_VERBS = dict(zip(
        "위대인의관향통가편변정당속응청칭처접면망명반범비상순약강요원전제존종준진취쾌탐택패피필해행허험화흥"
        "독득급귀극금기능답동논겸고과구권궁실심악엄역임장적점족중즉찬창천첨체촉친탁퇴투폐표한합후흉연유성보경",
        "爲對因依關向通加便變定當屬應請稱處接免亡命反犯比傷順弱強要願傳除存從準盡取快貪擇敗避畢害行許險化興"
        "毒得急貴極禁期能答動論兼告過求勸窮實甚惡嚴逆臨壯適占足重卽讚唱賤添滯促親濁退投廢表限合厚凶連留盛補輕"))

    def _rank(self, leading, trailing, base, tail):
        to_ks, to_edu = _hanja_forms()
        preferred, other = (to_edu, to_ks) if self.forms == "education" else (to_ks, to_edu)
        variant_note = "KS 자형" if self.forms == "education" else "교육용 자형"
        values = self.mapping.get(base)
        # 한자인 것은 후보 글자로 알 수 있으므로 출처에는 훈음과 자형·벽자 구분만 적는다.
        normative, alternate = [], {}
        for hanja in values:
            norm = "".join(preferred.get(c, c) for c in hanja)
            alt = "".join(other.get(c, c) for c in norm)
            if norm not in normative:
                normative.append(norm)
                if alt != norm:
                    alternate[norm] = alt
        common = [h for h in normative if self._all_education(h)]
        rare = [h for h in normative if not self._all_education(h)]
        top = []
        if base in self.user_mapping:
            first = normative[0]
            top = [first]
            common = [h for h in common if h != first]
            rare = [h for h in rare if h != first]
        elif common:
            if len(base) == 1 and is_derivation(tail):
                usual = self.HA_VERBS.get(base, "") if tail[0] in "하해했한할함합" else ""
                usual = "".join(preferred.get(c, c) for c in usual)
                best = usual if usual in common else max(common, key=self._frequency)
            else:
                best = common[0]
            top = [best]
            common.remove(best)
        def wrap(h):
            # Annotate just the converted stem, leaving particles, verb
            # endings and surrounding punctuation outside the annotation.
            if self.presentation == "hangul_hanja":
                text = base + "(" + h + ")"
            elif self.presentation == "hanja_hangul":
                text = h + "(" + base + ")"
            elif self.presentation == "hangulhanja":
                text = base + h
            else:
                text = h
            return leading + text + tail + trailing
        # 고른 자형만 낸다. 다만 고른 자형에 흔한 글꼴이 없는 글자(확장 E 이후, 예: 𮕩)가 있으면
        # 다른 자형(衰)도 대신 낸다. 벽자 낱말의 대신 자형은 그 옆 맨 아래에 둔다.
        alternate = {h: a for h, a in alternate.items() if _needs_font_fallback(h)}
        variant = [alternate[h] for h in top + common if h in alternate]
        def note(h, *tags):
            return " · ".join(part for part in (hanja_gloss(base, h), *tags) if part)
        bottom = []
        for h in rare:
            bottom.append((wrap(h), "rare", note(h, "벽자")))
            if h in alternate:
                bottom.append((wrap(alternate[h]), "rare", note(alternate[h], "벽자", variant_note)))
        return ([(wrap(h), "top", note(h)) for h in top] + [(wrap(h), "common", note(h)) for h in common]
                + [(wrap(h), "variant", note(h, variant_note)) for h in variant] + bottom)


@dataclass(frozen=True)
class UnitDefinition:
    key: str
    symbol: str
    dimension: str
    to_base: float
    aliases: Tuple[str, ...]
    alternate_symbol: Optional[str] = None
    alternate_factor: Optional[float] = None


def _unit(key, symbol, dimension, to_base, aliases, alternate_symbol=None, alternate_factor=None):
    return UnitDefinition(
        key, symbol, dimension, to_base, tuple(aliases), alternate_symbol, alternate_factor
    )


UNIT_DEFINITIONS = (
    _unit("km", "km", "length", 1000, ("킬로미터", "키로미터", "km", "키로"), "m", 1000),
    _unit("m", "m", "length", 1, ("미터", "m"), "cm", 100),
    _unit("cm", "cm", "length", .01, ("센티미터", "센치미터", "센티", "센치", "cm"), "m", .01),
    _unit("mm", "mm", "length", .001, ("밀리미터", "미리미터", "밀리", "미리", "mm"), "cm", .1),
    _unit("um", "μm", "length", .000001, ("마이크로미터", "마이크로", "μm", "um"), "nm", 1000),
    _unit("nm", "nm", "length", .000000001, ("나노미터", "나노", "nm"), "μm", .001),
    _unit("in", "in", "length", .0254, ("인치", "inch", "in"), "cm", 2.54),
    _unit("ft", "ft", "length", .3048, ("피트", "ft", "feet"), "m", .3048),
    _unit("yd", "yd", "length", .9144, ("야드", "yd"), "m", .9144),
    _unit("mi", "mi", "length", 1609.344, ("마일", "mi"), "km", 1.609344),
    _unit("nmi", "nmi", "length", 1852, ("해리", "nmi"), "km", 1.852),
    _unit("kg", "kg", "mass", 1, ("킬로그램", "키로그램", "kg", "키로"), "g", 1000),
    _unit("g", "g", "mass", .001, ("그램", "g"), "kg", .001),
    _unit("mg", "mg", "mass", .000001, ("밀리그램", "미리그램", "mg", "미리"), "g", .001),
    _unit("t", "t", "mass", 1000, ("톤", "t"), "kg", 1000),
    _unit("lb", "lb", "mass", .45359237, ("파운드", "lb"), "kg", .45359237),
    _unit("oz", "oz", "mass", .028349523125, ("온스", "oz"), "g", 28.349523125),
    _unit("don", "돈", "mass", .00375, ("돈",), "g", 3.75),
    _unit("L", "L", "volume", 1, ("리터", "L", "l"), "mL", 1000),
    _unit("mL", "mL", "volume", .001, ("밀리리터", "미리리터", "미리", "mL", "ml"), "L", .001),
    _unit("cc", "cc", "volume", .001, ("시시", "cc"), "mL", 1),
    _unit("cup", "cup", "volume", .2365882365, ("컵", "cup"), "mL", 236.5882365),
    _unit("gal", "gal", "volume", 3.785411784, ("갤런", "gal", "gallon"), "L", 3.785411784),
    _unit("m2", "m²", "area", 1, ("제곱미터", "평방미터", "m²", "m2"), "평", .3025),
    _unit("pyeong", "평", "area", 3.305785124, ("평",), "m²", 3.305785124),
    _unit("ha", "ha", "area", 10000, ("헥타르", "ha"), "m²", 10000),
    _unit("acre", "acre", "area", 4046.8564224, ("에이커", "acre"), "m²", 4046.8564224),
    _unit("s", "s", "time", 1, ("초", "s", "sec"), "min", 1/60),
    _unit("min", "min", "time", 60, ("분", "min"), "s", 60),
    _unit("h", "h", "time", 3600, ("시간", "시", "h", "hr"), "min", 60),
    _unit("day", "d", "time", 86400, ("일", "day"), "h", 24),
    _unit("week", "주", "time", 604800, ("주", "week"), "일", 7),
    _unit("Hz", "Hz", "frequency", 1, ("헤르츠", "Hz"), "kHz", .001),
    _unit("kHz", "kHz", "frequency", 1000, ("킬로헤르츠", "kHz"), "Hz", 1000),
    _unit("MHz", "MHz", "frequency", 1000000, ("메가헤르츠", "MHz"), "kHz", 1000),
    _unit("Pa", "Pa", "pressure", 1, ("파스칼", "Pa"), "kPa", .001),
    _unit("kPa", "kPa", "pressure", 1000, ("킬로파스칼", "kPa"), "Pa", 1000),
    _unit("bar", "bar", "pressure", 100000, ("바", "bar"), "kPa", 100),
    _unit("atm", "atm", "pressure", 101325, ("기압", "atm"), "kPa", 101.325),
    _unit("J", "J", "energy", 1, ("줄", "J"), "kJ", .001),
    _unit("kJ", "kJ", "energy", 1000, ("킬로줄", "kJ"), "J", 1000),
    _unit("cal", "cal", "energy", 4.184, ("칼로리", "cal"), "J", 4.184),
    _unit("kcal", "kcal", "energy", 4184, ("킬로칼로리", "키로칼로리", "kcal"), "kJ", 4.184),
    _unit("W", "W", "power", 1, ("와트", "W"), "kW", .001),
    _unit("kW", "kW", "power", 1000, ("킬로와트", "키로와트", "kW"), "W", 1000),
    _unit("MW", "MW", "power", 1000000, ("메가와트", "MW"), "kW", 1000),
    _unit("bit", "bit", "data", 1, ("비트", "bit", "b"), "byte", .125),
    _unit("byte", "B", "data", 8, ("바이트", "byte", "B"), "bit", 8),
    _unit("KB", "KB", "data", 8*1000, ("킬로바이트", "키로바이트", "KB"), "MB", .001),
    _unit("MB", "MB", "data", 8*1000**2, ("메가바이트", "MB"), "GB", .001),
    _unit("GB", "GB", "data", 8*1000**3, ("기가바이트", "기가", "GB"), "MB", 1000),
    _unit("TB", "TB", "data", 8*1000**4, ("테라바이트", "테라", "TB"), "GB", 1000),
    _unit("KiB", "KiB", "data", 8*1024, ("키비바이트", "KiB"), "MiB", 1/1024),
    _unit("MiB", "MiB", "data", 8*1024**2, ("메비바이트", "MiB"), "GiB", 1/1024),
    _unit("GiB", "GiB", "data", 8*1024**3, ("기비바이트", "GiB"), "MiB", 1024),
    _unit("kmh", "km/h", "speed", 1000/3600, ("킬로미터/시", "km/h", "시속"), "m/s", 1000/3600),
    _unit("ms", "m/s", "speed", 1, ("미터/초", "m/s"), "km/h", 3.6),
    _unit("mph", "mph", "speed", 1609.344/3600, ("마일/시", "mph", "마일퍼아워"), "km/h", 1.609344),
    _unit("rad", "rad", "angle", 1, ("라디안", "rad"), "°", 180/3.141592653589793),
    _unit("degree", "°", "angle", 3.141592653589793/180, ("각도", "도각", "deg"), "rad", 3.141592653589793/180),
    _unit("m3", "m³", "volume", 1000, ("세제곱미터", "입방미터", "m³", "m3"), "L", 1000),
    _unit("cm3", "cm³", "volume", .001, ("세제곱센티미터", "cm³", "cm3"), "mL", 1),
    _unit("km2", "km²", "area", 1000000, ("제곱킬로미터", "km²", "km2"), "m²", 1000000),
    _unit("ms_time", "ms", "time", .001, ("밀리초", "ms"), "s", .001),
    _unit("us_time", "μs", "time", .000001, ("마이크로초", "μs", "us"), "ms", .001),
    _unit("knot", "kn", "speed", 1852/3600, ("노트", "kn", "knot"), "km/h", 1.852),
    _unit("Wh", "Wh", "energy", 3600, ("와트시", "Wh"), "J", 3600),
    _unit("kWh", "kWh", "energy", 3600000, ("킬로와트시", "kWh"), "MJ", 3.6),
    _unit("N", "N", "force", 1, ("뉴턴", "N"), "kN", .001),
    _unit("kN", "kN", "force", 1000, ("킬로뉴턴", "kN"), "N", 1000),
    _unit("V", "V", "voltage", 1, ("볼트", "V"), "mV", 1000),
    _unit("mV", "mV", "voltage", .001, ("밀리볼트", "mV"), "V", .001),
    _unit("A", "A", "current", 1, ("암페어", "A"), "mA", 1000),
    _unit("mA", "mA", "current", .001, ("밀리암페어", "mA"), "A", .001),
    _unit("ohm", "Ω", "resistance", 1, ("옴", "Ω", "ohm"), "kΩ", .001),
    _unit("kohm", "kΩ", "resistance", 1000, ("킬로옴", "kΩ", "kohm"), "Ω", 1000),
    _unit("mol", "mol", "amount", 1, ("몰", "mol"), "mmol", 1000),
    _unit("mmol", "mmol", "amount", .001, ("밀리몰", "mmol"), "mol", .001),
    _unit("kgm3", "kg/m³", "density", 1, ("kg/m³", "kg/m3"), "g/cm³", .001),
    _unit("gcm3", "g/cm³", "density", 1000, ("g/cm³", "g/cm3"), "kg/m³", 1000),
    _unit("Mbps", "Mbps", "data_rate", 1000000, ("메가비피에스", "Mbps"), "MB/s", .125),
    _unit("MBps", "MB/s", "data_rate", 8000000, ("MB/s",), "Mbps", 8),
    _unit("percent", "%", "ratio", .01, ("퍼센트", "%"), "‰", 10),
)


class UnitConverter(WordConverter):
    name = "단위"
    # Commas are thousands separators; decimal commas are deliberately rejected.
    NUMBER_RE = re.compile(r"^(?P<value>[+−-]?(?:(?:[0-9]{1,3}(?:,[0-9]{3})+|[0-9]+)(?:\.[0-9]+)?|\.[0-9]+)(?:[eE][+-]?[0-9]{1,3})?)")
    TEMPERATURE_ALIASES = (
        ("섭씨", "C"), ("셀시우스", "C"), ("℃", "C"), ("°C", "C"), ("C", "C"),
        ("화씨", "F"), ("파렌하이트", "F"), ("℉", "F"), ("°F", "F"), ("F", "F"),
        ("켈빈", "K"), ("K", "K"), ("도", "C"),
    )

    def __init__(self, definitions=UNIT_DEFINITIONS):
        self.definitions = tuple(definitions)
        self._aliases = sorted(
            ((alias, definition) for definition in self.definitions for alias in definition.aliases),
            key=lambda item: len(item[0]), reverse=True,
        )

    def _quantity(self, core):
        if len(core) > 512:
            return None
        number_match = self.NUMBER_RE.match(core)
        if not number_match:
            return None
        try:
            value = Decimal(number_match.group("value").replace(",", "").replace("−", "-"))
        except InvalidOperation:
            return None
        if not value.is_finite() or abs(value.adjusted()) > 100:
            return None
        return value, core[number_match.end():].lstrip()

    def _matches(self, core):
        quantity = self._quantity(core)
        if quantity is None:
            return
        value, rest = quantity
        matches = [
            (alias, definition) for alias, definition in self._aliases
            if rest.startswith(alias) and is_particle(rest[len(alias):])
        ]
        if not matches:
            return
        longest = max(len(alias) for alias, _ in matches)
        for alias, definition in matches:
            if len(alias) == longest:
                yield value, definition, rest[len(alias):]

    def candidates(self, word, context=None):
        if len(word) > 512:
            return
        leading, core, trailing = token_edges(word)
        quantity = self._quantity(core)
        if quantity is not None:
            value, rest = quantity
            for alias, scale in sorted(self.TEMPERATURE_ALIASES, key=lambda item: len(item[0]), reverse=True):
                if not rest.startswith(alias):
                    continue
                suffix = rest[len(alias):]
                if not is_particle(suffix):
                    continue
                with localcontext() as decimal_context:
                    decimal_context.prec = 40
                    freezing = Decimal("273.15")
                    if scale == "C":
                        celsius = value
                        variants = ((value, "°C"), (value * 9 / 5 + 32, "°F"), (value + freezing, "K"))
                    elif scale == "F":
                        celsius = (value - 32) * 5 / 9
                        variants = ((value, "°F"), (celsius, "°C"), (celsius + freezing, "K"))
                    else:
                        celsius = value - freezing
                        variants = ((value, "K"), (celsius, "°C"), (celsius * 9 / 5 + 32, "°F"))
                    if celsius < -freezing:
                        return
                for converted, symbol in variants:
                    yield leading + f"{format_quantity(converted)} {symbol}" + suffix + trailing
                return
        matched = False
        for value, definition, suffix in self._matches(core):
            matched = True
            yield leading + f"{format_quantity(value)} {definition.symbol}" + suffix + trailing
            if definition.alternate_symbol and definition.alternate_factor is not None:
                with localcontext() as decimal_context:
                    decimal_context.prec = 40
                    converted = value * Decimal(str(definition.alternate_factor))
                    if converted.is_finite():
                        yield leading + f"{format_quantity(converted)} {definition.alternate_symbol}" + suffix + trailing
        if not matched and quantity is not None:
            value, expression = quantity
            if any(leading.count(opening) != trailing.count(closing)
                   for opening, closing in zip("([{<「『【", ")]} >」』】".replace(" ", ""))):
                return
            # The fallback requires the entire remaining unit expression. It
            # deliberately does not peel arbitrary suffixes or change priority
            # or candidate order for the established Korean/colloquial units.
            for converted in pint_candidates(value, expression):
                yield leading + converted + trailing


@dataclass(frozen=True)
class Era:
    name: str
    start_year: int
    start_month: int = 1
    start_day: int = 1
    aliases: Tuple[str, ...] = ()
    # start_year denotes accession; first_year denotes the year labelled 1.
    first_year: Optional[int] = None
    end_year: Optional[int] = None
    end_month: int = 12
    end_day: int = 31
    calendar: str = "gregorian"
    gregorian_from: Optional[date] = None

    def __post_init__(self):
        if not isinstance(self.name, str) or not self.name:
            raise ValueError("era name must not be empty")
        if self.calendar not in ("gregorian", "year-only"):
            raise ValueError("unsupported era calendar")
        if not 1 <= self.year_one <= 9999 or self.year_one < self.start_year:
            raise ValueError("invalid first regnal year")
        if self.end < self.start or self.year_one > self.end.year:
            raise ValueError("invalid era bounds")

    @property
    def year_one(self):
        return self.start_year if self.first_year is None else self.first_year

    @property
    def start(self):
        return date(self.start_year, self.start_month, self.start_day)

    @property
    def end(self):
        return date(self.end_year, self.end_month, self.end_day) if self.end_year is not None else date.max


def _era(name, year, month=1, day=1, aliases=(), **kwargs):
    return Era(name, year, month, day, tuple(aliases), **kwargs)


def _korean_era(name, accession, end, immediate=False, aliases=()):
    return _era(name, accession, aliases=aliases, first_year=accession if immediate else accession + 1,
                end_year=end, calendar="year-only")


def _historical_era(name, first, end, aliases):
    return _era(name, first, aliases=aliases, end_year=end, calendar="year-only")


DEFAULT_ERAS = (
    _korean_era("태조", 1392, 1398, True), _korean_era("정종", 1398, 1400),
    _korean_era("태종", 1400, 1418), _korean_era("세종", 1418, 1450),
    _korean_era("문종", 1450, 1452), _korean_era("단종", 1452, 1455),
    _korean_era("세조", 1455, 1468, True), _korean_era("예종", 1468, 1469),
    _korean_era("성종", 1469, 1494), _korean_era("연산군", 1494, 1506, aliases=("연산",)),
    _korean_era("중종", 1506, 1544, True), _korean_era("인종", 1544, 1545),
    _korean_era("명종", 1545, 1567), _korean_era("선조", 1567, 1608),
    _korean_era("광해군", 1608, 1623, aliases=("광해",)), _korean_era("인조", 1623, 1649, True),
    _korean_era("효종", 1649, 1659), _korean_era("현종", 1659, 1674),
    _korean_era("숙종", 1674, 1720), _korean_era("경종", 1720, 1724),
    _korean_era("영조", 1724, 1776), _korean_era("정조", 1776, 1800),
    _korean_era("순조", 1800, 1834), _korean_era("헌종", 1834, 1849),
    _korean_era("철종", 1849, 1863), _korean_era("고종", 1863, 1907),
    _korean_era("순종", 1907, 1910, True),
    _era("메이지", 1868, aliases=("明治",), end_year=1912, end_month=7, end_day=29, gregorian_from=date(1873, 1, 1)),
    _era("다이쇼", 1912, 7, 30, aliases=("大正",), end_year=1926, end_month=12, end_day=24),
    _era("쇼와", 1926, 12, 25, aliases=("昭和",), end_year=1989, end_month=1, end_day=7),
    _era("헤이세이", 1989, 1, 8, aliases=("平成",), end_year=2019, end_month=4, end_day=30),
    _era("레이와", 2019, 5, 1, aliases=("令和",)),
    _historical_era("홍무", 1368, 1398, ("洪武",)),
    _historical_era("영락", 1403, 1424, ("永樂", "永乐")),
    _historical_era("강희", 1662, 1722, ("康熙",)),
    _historical_era("옹정", 1723, 1735, ("雍正",)),
    _historical_era("건륭", 1736, 1795, ("乾隆",)),
    _historical_era("가경", 1796, 1820, ("嘉慶", "嘉庆")),
    _historical_era("도광", 1821, 1850, ("道光",)),
    _historical_era("함풍", 1851, 1861, ("咸豐", "咸丰")),
    _historical_era("동치", 1862, 1874, ("同治",)),
    _historical_era("광서", 1875, 1908, ("光緒", "光绪")),
    _historical_era("선통", 1909, 1912, ("宣統", "宣统")),
    _era("민국", 1912, aliases=("民國", "民国")),
)


def load_eras(path):
    """JSON 연호 목록을 읽어 DateConverter에 주입한다."""
    with Path(path).open(encoding="utf-8") as handle:
        payload = json.load(handle)
    if isinstance(payload, Mapping):
        payload = payload.get("eras", payload)
    if isinstance(payload, Mapping):
        payload = [dict(value, name=key) for key, value in payload.items()]
    return tuple(
        _era(
            item["name"], int(item["start_year"]), int(item.get("start_month", 1)),
            int(item.get("start_day", 1)), tuple(item.get("aliases", ())),
            first_year=int(item["first_year"]) if item.get("first_year") is not None else None,
            end_year=int(item["end_year"]) if item.get("end_year") is not None else None,
            end_month=int(item.get("end_month", 12)), end_day=int(item.get("end_day", 31)),
            calendar=item.get("calendar", "gregorian"),
            gregorian_from=date.fromisoformat(item["gregorian_from"]) if item.get("gregorian_from") else None,
        )
        for item in payload
    )

_KOREAN_ERA_NAMES = {
    "태조", "정종", "태종", "세종", "문종", "단종", "세조", "예종", "성종",
    "연산군", "중종", "인종", "명종", "선조", "광해군", "인조", "효종", "현종",
    "숙종", "경종", "영조", "정조", "순조", "헌종", "철종", "고종", "순종",
}
_JAPANESE_ERA_NAMES = {"메이지", "다이쇼", "쇼와", "헤이세이", "레이와"}
_CHINESE_ERA_NAMES = {
    "홍무", "영락", "강희", "옹정", "건륭", "가경", "도광", "함풍", "동치",
    "광서", "선통", "민국",
}
_TERMINATED_ERA_FAMILIES = {"korean"}


def _era_family(era):
    if era.name in _KOREAN_ERA_NAMES:
        return "korean"
    if era.name in _JAPANESE_ERA_NAMES:
        return "japanese"
    if era.name in _CHINESE_ERA_NAMES:
        return "chinese"
    return era.name


class _KoreanLunarBackend:
    def __init__(self):
        from korean_lunar_calendar import KoreanLunarCalendar
        self._calendar_type = KoreanLunarCalendar

    def solar_to_lunar(self, value):
        instance = self._calendar_type()
        if not instance.setSolarDate(value.year, value.month, value.day):
            return None
        leap = "윤" if getattr(instance, "isIntercalation", False) else ""
        return f"음력 {instance.lunarYear}년 {leap}{instance.lunarMonth}월 {instance.lunarDay}일"

    def lunar_to_solar(self, year, month, day, leap=False):
        instance = self._calendar_type()
        if not instance.setLunarDate(year, month, day, leap):
            return None
        # Some backend versions silently treat a nonexistent leap month as an
        # ordinary month. Reject this lossy normalization.
        if bool(instance.isIntercalation) != bool(leap):
            return None
        return date(instance.solarYear, instance.solarMonth, instance.solarDay)


def _optional_lunar_backend():
    try:
        return _KoreanLunarBackend()
    except (ImportError, ModuleNotFoundError):
        return None


class DateConverter(WordConverter):
    name = "날짜"
    FULL_RE = re.compile(r"^(?P<year>\d{4})년\s*(?P<month>\d{1,2})월\s*(?P<day>\d{1,2})일?$")
    SHORT_RE = re.compile(r"^(?P<month>\d{1,2})월\s*(?P<day>\d{1,2})일?$")
    ISO_RE = re.compile(r"^(?P<year>[0-9]{4})(?P<separator>[-/.])(?P<month>[0-9]{1,2})(?P=separator)(?P<day>[0-9]{1,2})$")
    LUNAR_RE = re.compile(
        r"^(?:음력|lunar)\s*(?P<year>\d{4})[-/.년]\s*"
        r"(?P<leap>윤달|윤|leap)?\s*(?P<month>\d{1,2})"
        r"(?:월|[-/.])\s*(?P<day>\d{1,2})일?$"
    )
    ERA_RE = re.compile(
        r"^(?P<era>[가-힣一-龥A-Za-z]+?)\s*(?P<year>즉위|원|元|[0-9]{1,4})(?:년|年)?"
        r"(?:\s*(?P<month>\d{1,2})(?:월|月)\s*(?P<day>\d{1,2})(?:일|日)?)?$"
    )
    WEEKDAY_RE = re.compile(
        r"^(?:(?P<prefix>다다음주|다음주|이번주|지난주)\s*)?"
        r"(?P<weekday>[월화수목금토일])요일$"
    )
    RELATIVE = {
        "그끄저께": -3, "그제": -2, "그저께": -2, "어제": -1, "오늘": 0,
        "내일": 1, "모레": 2, "글피": 3,
    }

    def __init__(self, reference_date=None, lunar_backend=None, eras=DEFAULT_ERAS):
        self.reference_date = reference_date
        self.lunar_backend = (
            _optional_lunar_backend() if lunar_backend is None or lunar_backend == "auto"
            else (None if lunar_backend is False else lunar_backend)
        )
        self.eras = tuple(eras)
        self._era_by_name = {}
        for era in self.eras:
            self._era_by_name[era.name] = era
            for alias in era.aliases:
                self._era_by_name[alias] = era

    @staticmethod
    def _today():
        from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
        try:
            return datetime.now(ZoneInfo("Asia/Seoul")).date()
        except ZoneInfoNotFoundError:
            return date.today()

    @property
    def reference_date(self):
        return self._reference_date if self._reference_date is not None else self._today()

    @reference_date.setter
    def reference_date(self, value):
        if isinstance(value, datetime):
            value = value.date()
        if value is not None and not isinstance(value, date):
            raise ValueError("reference_date must be a date or None")
        self._reference_date = value

    @property
    def lunar_available(self):
        return self.lunar_backend is not None

    @staticmethod
    def _safe_date(year, month, day):
        try:
            return date(year, month, day)
        except (ValueError, OverflowError):
            return None

    @staticmethod
    def _weekday(value):
        return "월화수목금토일"[value.weekday()] + "요일"

    def _gregorian_variants(self, value):
        yield value.isoformat()
        yield f"{value.year:04d}/{value.month:02d}/{value.day:02d}"
        yield f"{value.year}년 {value.month}월 {value.day}일"
        yield f"{value.isoformat()} ({self._weekday(value)})"
        if self.lunar_backend is not None:
            try:
                lunar = self.lunar_backend.solar_to_lunar(value)
            except (ValueError, OverflowError):
                lunar = None
            if lunar:
                yield lunar
        for era in self.eras:
            if era.calendar != "gregorian" or not era.start <= value <= era.end:
                continue
            if era.gregorian_from is not None and value < era.gregorian_from:
                continue
            regnal = value.year - era.year_one + 1
            if regnal > 0:
                yield f"{era.name} {regnal}년 {value.month}월 {value.day}일"

    def _parse_gregorian(self, core, reference=None):
        for pattern in (self.FULL_RE, self.ISO_RE):
            match = pattern.match(core)
            if match:
                return self._safe_date(
                    int(match.group("year")), int(match.group("month")), int(match.group("day"))
                )
        match = self.SHORT_RE.match(core)
        if match:
            return self._safe_date(
                (reference or self.reference_date).year, int(match.group("month")), int(match.group("day"))
            )
        return None

    def _parse_relative(self, core, reference=None):
        reference = reference or self.reference_date
        try:
            if core in self.RELATIVE:
                return reference + timedelta(days=self.RELATIVE[core])
            match = re.fullmatch(r"([0-9]{1,7})\s*일\s*(뒤|후|전)", core)
            if match:
                days = int(match.group(1)) * (-1 if match.group(2) == "전" else 1)
                return reference + timedelta(days=days)
        except (ValueError, OverflowError):
            return None
        return None

    def _parse_weekday(self, core, reference=None):
        match = self.WEEKDAY_RE.match(core.replace(" ", ""))
        if not match:
            return None
        weekday = "월화수목금토일".index(match.group("weekday"))
        reference = reference or self.reference_date
        prefix = match.group("prefix") or "이번주"
        offset = {"지난주": -7, "이번주": 0, "다음주": 7, "다다음주": 14}[prefix]
        try:
            return reference + timedelta(days=offset + weekday - reference.weekday())
        except (ValueError, OverflowError):
            return None

    def _parse_era(self, core):
        match = self.ERA_RE.match(core)
        if not match:
            return None
        era = self._era_by_name.get(match.group("era"))
        if era is None:
            return None
        label = match.group("year")
        if label == "즉위":
            if era.calendar != "year-only" or era.name not in _KOREAN_ERA_NAMES:
                return None
            year = era.start_year
        else:
            regnal_year = 1 if label in ("원", "元") else int(label)
            if regnal_year < 1:
                return None
            year = era.year_one + regnal_year - 1
        if not era.start_year <= year <= era.end.year:
            return None
        if not match.group("month") or not match.group("day"):
            return era, year, None
        if era.calendar != "gregorian":
            return None
        target = self._safe_date(
            year,
            int(match.group("month")), int(match.group("day"))
        )
        if target is None or not era.start <= target <= era.end:
            return None
        if era.gregorian_from is not None and target < era.gregorian_from:
            return None
        return era, year, target

    def _parse_lunar(self, core):
        match = self.LUNAR_RE.match(core)
        if not match or self.lunar_backend is None:
            return None
        year, month, day = (int(match.group(key)) for key in ("year", "month", "day"))
        if not (1 <= year <= 9999 and 1 <= month <= 12 and 1 <= day <= 30):
            return None
        try:
            value = self.lunar_backend.lunar_to_solar(year, month, day, bool(match.group("leap")))
        except (ValueError, OverflowError):
            return None
        return value if isinstance(value, date) else None

    def candidates(self, word, context=None):
        if len(word) > 512:
            return
        leading, core, trailing = token_edges(word)
        reference = self.reference_date
        for base, particle in stem_candidates(core):
            suffix = particle + trailing
            target = self._parse_relative(base, reference) or self._parse_weekday(base, reference)
            if target is None:
                target = self._parse_gregorian(base, reference)
            if target is None:
                target = self._parse_lunar(base)
            era_value = self._parse_era(base)
            if era_value:
                era, year, era_date = era_value
                if era_date is None:
                    yield leading + f"{year}년" + suffix
                    return
                target = era_date
            if target is not None:
                for variant in _unique(self._gregorian_variants(target)):
                    yield leading + variant + suffix
                return


def _is_hangul_character(character):
    if len(character) != 1:
        return False
    codepoint = ord(character)
    return (
        0x1100 <= codepoint <= 0x11FF or 0x3130 <= codepoint <= 0x318F
        or 0xA960 <= codepoint <= 0xA97F or 0xAC00 <= codepoint <= 0xD7A3
        or 0xD7B0 <= codepoint <= 0xD7FF or 0xFFA0 <= codepoint <= 0xFFDC
    )


def _codepoint_label(value):
    return " ".join(f"U+{ord(character):04X}" for character in value)


def _jamo_maps():
    canonical_to_halfwidth = {}
    canonical_to_compatibility = {}
    for codepoint in range(0xFFA0, 0xFFDD):
        halfwidth = chr(codepoint)
        canonical = unicodedata.normalize("NFKC", halfwidth)
        if canonical != halfwidth:
            canonical_to_halfwidth.setdefault(canonical, halfwidth)
    for codepoint in range(0x3130, 0x3190):
        compatibility = chr(codepoint)
        canonical = unicodedata.normalize("NFKC", compatibility)
        if canonical != compatibility and _is_hangul_character(canonical):
            canonical_to_compatibility.setdefault(canonical, compatibility)
    # NFKC maps compatibility consonants to choseong, so jongseong needs an
    # explicit counterpart when decomposing syllables such as 한 -> ㅎㅏㄴ.
    for index, compatibility in enumerate("ㄱㄲㄳㄴㄵㄶㄷㄹㄺㄻㄼㄽㄾㄿㅀㅁㅂㅄㅅㅆㅇㅈㅊㅋㅌㅍㅎ", 0x11A8):
        final = chr(index)
        canonical_to_compatibility[final] = compatibility
        halfwidth = canonical_to_halfwidth.get(unicodedata.normalize("NFKC", compatibility))
        if halfwidth:
            canonical_to_halfwidth[final] = halfwidth
    return canonical_to_halfwidth, canonical_to_compatibility


class JamoUnicodeConverter(WordConverter):
    name = "자모·유니코드"
    _canonical_to_halfwidth, _canonical_to_compatibility = _jamo_maps()

    def candidates(self, word, context=None):
        for text, _tier, _note in self.ranked_candidates(word, context):
            yield text

    def ranked_candidates(self, word, context=None):
        """[(text, None, note)]: 반각·호환 자모, 조합형 자모, code point.

        낱자만으로 된 말(ㄱ, ㅋㅋ, ﾡ)은 반각 한글(U+FFA1..)과 호환 자모를 서로 바꿔 준다.
        """
        from .settings import _JAMO_FULL, _JAMO_HALF
        leading, core, trailing = _edges(word)
        result = []

        def add(text, note):
            if text and text != core and all(text != item[0] for item in result):
                result.append((text, None, note))

        filler = ("\u3164", "\uFFA0")
        if core and all((c in _JAMO_HALF or c in _JAMO_FULL) and c not in filler for c in core):
            add("".join(_JAMO_HALF.get(c, c) for c in core), "반각")
            add("".join(_JAMO_FULL.get(c, c) for c in core), "호환 자모")
        if len(core) == 1 and (_is_hangul_character(core) or unicodedata.category(core).startswith("M")):
            if 0xAC00 <= ord(core) <= 0xD7A3:
                decomposed = unicodedata.normalize("NFD", core)
                add(decomposed, "조합형 자모")
                add("".join(self._canonical_to_compatibility.get(part, part) for part in decomposed), "낱자")
            else:
                canonical = unicodedata.normalize("NFKC", core)
                add(self._canonical_to_halfwidth.get(canonical, ""), "반각")
                add(self._canonical_to_compatibility.get(canonical, ""), "호환 자모")
                add(canonical, "조합형 자모")
            add(_codepoint_label(core), "유니코드")
        return [(leading + text + trailing, tier, note) for text, tier, note in result]


def default_word_transformer(
    reference_date=None, emoji_test_path=None, hanja_lexicon_path=None,
    lunar_backend=None, custom_converter=None, analyzer=None, hanja_forms="education", symbol_consonants=False,
    hanja_presentation="hanja", hanja_gloss=False,
):
    from .word_transform import WordTransformer
    # Hanja first: it is the conversion people reach for most in Korean.
    converters = [
        SymbolConverter(consonants=symbol_consonants),
        HanjaConverter(lexicon_path=hanja_lexicon_path, analyzer=analyzer, forms=hanja_forms,
                       presentation=hanja_presentation, gloss_search=hanja_gloss),
        EmojiConverter(emoji_test_path=emoji_test_path),
        UnitConverter(),
        DateConverter(reference_date, lunar_backend=lunar_backend),
        JamoUnicodeConverter(),
    ]
    if custom_converter is not None:
        converters.append(custom_converter)
    return WordTransformer(tuple(converters))


__all__ = [
    "EmojiRecord", "EmojiRegistry", "EmojiConverter", "HanjaConverter",
    "UnitDefinition", "UnitConverter", "Era", "DEFAULT_ERAS", "DateConverter",
    "JamoUnicodeConverter", "load_eras", "default_word_transformer",
]
