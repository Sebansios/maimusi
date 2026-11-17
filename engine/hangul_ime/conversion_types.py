"""Shared conversion contracts without concrete converter dependencies."""
from abc import ABC, abstractmethod
from dataclasses import dataclass
import math
import re

@dataclass(frozen=True)
class ConversionCandidate:
    text: str
    converter: str

@dataclass(frozen=True)
class WordSpan:
    index: int
    text: str
    start: int
    end: int

class WordConverter(ABC):
    name = "변환"
    @abstractmethod
    def candidates(self, word, context=None):
        """Yield alternatives without mutating source."""

KOREAN_PARTICLES = (
    "으로부터", "에서부터", "에게서", "한테서", "이라고", "이라서",
    "으로는", "으로도", "으로", "라고", "이라", "부터", "까지",
    "에게", "한테", "에서", "에는", "에도", "만큼", "처럼",
    "조차", "마저", "밖에", "커녕", "보다", "만", "도", "은",
    "는", "이", "가", "을", "를", "의", "와", "과", "로", "에",
)

def _edges(word):
    # Strip wrappers, not signs, decimal points, degrees or percent symbols.
    start = 0
    while start < len(word) and word[start] in " (\"'“‘「『《〈【[":
        start += 1
    end = len(word)
    while end > start and word[end-1] in " )\"'”’」』》〉】]!?。":
        end -= 1
    return word[:start], word[start:end], word[end:]

def _split_particle(word):
    remaining, suffixes = word, []
    while True:
        for particle in sorted(KOREAN_PARTICLES, key=len, reverse=True):
            if remaining.endswith(particle) and len(remaining) > len(particle):
                remaining = remaining[:-len(particle)]
                suffixes.insert(0, particle)
                break
        else:
            return remaining, "".join(suffixes)

def _unique(values):
    seen = set()
    for value in values:
        if value and value not in seen:
            seen.add(value)
            yield value

def _format_number(value):
    if not math.isfinite(value):
        raise ValueError("유한한 숫자만 변환할 수 있습니다")
    if abs(value - round(value)) < 1e-9:
        return str(int(round(value)))
    return f"{value:.9f}".rstrip("0").rstrip(".")
