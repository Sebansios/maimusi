"""Whitespace-preserving conversion sessions with explicit learning commits."""
from dataclasses import dataclass
import re
from .conversion_types import (
    ConversionCandidate, WordSpan, WordConverter, KOREAN_PARTICLES,
    _edges, _split_particle, _unique, _format_number,
)

class WordTransformer:
    def __init__(self, converters=None):
        self.converters = tuple(converters or ())
        self.errors = []

    def has_phrase_conversion(self, phrase):
        """Existence check only: do not enumerate Hanja, Unicode or all outputs."""
        if len(phrase) > 512:
            return False
        lookup = "".join(chr(ord(c) - 0xFEE0) if 0xFF01 <= ord(c) <= 0xFF5E
                         else " " if c == "\u3000" else c for c in phrase)
        for converter in self.converters:
            if converter.name not in {"날짜", "단위", "단위환산", "사용자 변환", "이모지"}:
                continue
            try:
                if any(isinstance(item, str) and item and item != phrase and len(item) <= 8192
                       for item in converter.candidates(lookup)):
                    return True
            except (ValueError, ArithmeticError, TimeoutError):
                pass
        return False

    def candidates(self, word, context=None):
        result = [ConversionCandidate(word, "원문")]
        seen = {word}
        self.errors = []
        if len(word) > 1024:
            return tuple(result)
        # Width preferences must not make typed dates/units unrecognizable.
        # Normalize only fullwidth ASCII for lookup, never Hangul/kana via NFKC,
        # and keep the exact user's source as candidate zero.
        lookup_word = "".join(chr(ord(c)-0xFEE0) if 0xFF01 <= ord(c) <= 0xFF5E
                              else " " if c == "\u3000" else c for c in word)
        groups = {}
        for converter in self.converters:
            items = []
            try:
                if hasattr(converter, "ranked_candidates"):
                    items = list(converter.ranked_candidates(lookup_word, context))
                else:
                    for candidate in converter.candidates(lookup_word, context):
                        items.append((candidate, None, converter.name))
                        if len(items) >= 512:
                            break
            except (ValueError, ArithmeticError, TimeoutError) as exc:
                self.errors.append((converter.name, type(exc).__name__))
            groups.setdefault(converter.name, []).extend(items)

        def add(items, _name=None):
            for candidate, _tier, note in items:
                if isinstance(candidate, str) and candidate and len(candidate) <= 8192 and candidate not in seen and len(result) < 512:
                    result.append(ConversionCandidate(candidate, note))
                    seen.add(candidate)

        hanja = groups.get("한자", [])
        emoji = groups.get("이모지", [])
        tier = lambda t: [item for item in hanja if item[1] == t]
        # Most likely hanja > representative emoji > other common hanja >
        # emoji variants > allowed variant forms > rare hanja (벽자).
        add(groups.get("기호·문자", []), "기호·문자")
        add(tier("top"), "한자")
        add(groups.get("사용자 변환", []), "사용자 변환")
        add(emoji[:1], "이모지")
        for name in ("단위", "날짜"):
            add(groups.get(name, []), name)
        add(tier("common"), "한자")
        add(emoji[1:], "이모지")
        add(tier("variant"), "한자")
        add(tier("rare"), "한자")
        for name, items in groups.items():
            if name not in ("한자", "이모지", "사용자 변환", "기호·문자", "단위", "날짜"):
                add(items, name)
        ordinary, codepoints = [], []
        for item in result[1:]:
            (codepoints if re.fullmatch(r"U\+[0-9A-F]+(?: U\+[0-9A-F]+)*", item.text) else ordinary).append(item)
        return tuple(result[:1] + ordinary + codepoints)

@dataclass
class _WordState:
    original: str
    current: str
    options: tuple = ()
    option_index: int = 0

class WordTransformSession:
    def __init__(self, transformer=None, learning=None):
        self.transformer = transformer or default_word_transformer()
        self.learning = learning
        self.reset()

    def reset(self):
        self._words = []
        self._gaps = [""]
        self.selected_index = None
        self._committed = False

    def load(self, text, selected_index=None):
        self.reset()
        matches = list(re.finditer(r"\S+", text))
        end, index = 0, 0
        while index < len(matches):
            match = matches[index]
            stop = index + 1
            for size in range(min(5, len(matches) - index), 1, -1):
                last = matches[index + size - 1]
                phrase = text[match.start():last.end()]
                if "\n" in phrase or "\t" in phrase or "  " in phrase:
                    continue
                if self.transformer.has_phrase_conversion(phrase):
                    stop = index + size
                    break
            finish = matches[stop - 1].end()
            self._gaps[-1] = text[end:match.start()]
            token = text[match.start():finish]
            self._words.append(_WordState(token, token))
            self._gaps.append("")
            end, index = finish, stop
        self._gaps[-1] = text[end:]
        if self._words:
            self.selected_index = len(self._words)-1 if selected_index is None else max(0, min(selected_index, len(self._words)-1))
        return self.text

    @property
    def text(self):
        return self._gaps[0] + "".join(w.current + self._gaps[i+1] for i, w in enumerate(self._words))

    @property
    def has_changes(self):
        return any(w.current != w.original for w in self._words)

    @property
    def option_index(self):
        word = self._require_selection()
        return word.option_index if word else 0

    def _require_selection(self):
        return self._words[self.selected_index] if self.selected_index is not None else None

    def move(self, delta):
        return self.select((self.selected_index or 0) + delta)

    def select(self, index):
        if self._words:
            self.selected_index = max(0, min(index, len(self._words)-1))
        return self.selected_word()

    def spans(self):
        result, pos = [], len(self._gaps[0])
        for i, word in enumerate(self._words):
            result.append(WordSpan(i, word.current, pos, pos + len(word.current)))
            pos += len(word.current) + len(self._gaps[i+1])
        return tuple(result)

    def selected_word(self):
        return self.spans()[self.selected_index] if self.selected_index is not None else None

    def candidates(self):
        word = self._require_selection()
        if word is None:
            return ()
        if not word.options:
            options = self.transformer.candidates(word.original)
            word.options = self.learning.rank(word.original, options) if self.learning is not None else options
        return word.options

    def choose(self, index):
        options = self.candidates()
        if not 0 <= index < len(options):
            raise IndexError("후보 범위를 벗어났습니다")
        word = self._require_selection()
        word.option_index, word.current = index, options[index].text
        self._committed = False
        return self.text

    def cycle(self, delta=1):
        options = self.candidates()
        return self.choose((self.option_index + delta) % len(options)) if options else self.text

    def commit(self):
        if not self._committed and self.learning is not None:
            for word in self._words:
                if word.current != word.original:
                    self.learning.record(word.original, word.current)
        self._committed = True
        return self.text

    def cancel(self):
        for word in self._words:
            word.current, word.option_index = word.original, 0
        return self.text

from .advanced_transform import (
    EmojiRecord, EmojiRegistry, EmojiConverter, HanjaConverter,
    UnitDefinition, UnitConverter, Era, DEFAULT_ERAS, DateConverter,
    JamoUnicodeConverter, load_eras, default_word_transformer,
)
