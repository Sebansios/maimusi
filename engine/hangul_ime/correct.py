"""
correct.py — 선택적 맞춤법/오타 교정 계층 (기본 OFF).

교정은 띄어쓰기와 독립된 '플러그인'이다. engine에서 on/off 토글한다.
프로토타입 구현은 '자모 단위 편집거리 + 어절 사전' 기반의 보수적 교정이다:
오타가 난 어절을, 자모 1글자 차이 안에 있는 '충분히 빈도 높은' 사전 어절로만
바꾼다(과교정 방지). 자판 인접 오타 규칙도 소수 포함한다.

생산 단계에서는 같은 Corrector 인터페이스 뒤에 '자모 노이즈 채널 + 통계
언어모델 재랭킹' 또는 소형 seq2seq 교정 모델을 끼울 수 있다(DESIGN.md).
"""
from abc import ABC, abstractmethod
from .jamo import text_to_jamo


class Corrector(ABC):
    @abstractmethod
    def correct(self, text: str) -> str:
        ...


class NoopCorrector(Corrector):
    """아무것도 하지 않음 (교정 OFF 기본값)."""

    def correct(self, text: str) -> str:
        return text


def _edit_distance(a: str, b: str, cap: int = 2) -> int:
    """자모 문자열 간 레벤슈타인 거리(상한 cap에서 조기 종료)."""
    la, lb = len(a), len(b)
    if abs(la - lb) > cap:
        return cap + 1
    prev = list(range(lb + 1))
    for i in range(1, la + 1):
        cur = [i] + [0] * lb
        best = cur[0]
        for j in range(1, lb + 1):
            cost = 0 if a[i - 1] == b[j - 1] else 1
            cur[j] = min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + cost)
            best = min(best, cur[j])
        if best > cap:
            return cap + 1
        prev = cur
    return prev[lb]


class DictionaryCorrector(Corrector):
    """어절 사전 + 자모 편집거리 기반 보수적 오타 교정.

    word_freq: 어절->빈도. 미등록 어절을 자모거리 <=max_jamo_dist 이며 빈도
    >=min_freq 인 후보 중 최빈 어절로 교체. 후보가 없으면 원형 유지.
    """

    def __init__(self, word_freq: dict, min_freq: int = 3, max_jamo_dist: int = 1):
        self.word_freq = word_freq
        self.min_freq = min_freq
        self.max_jamo_dist = max_jamo_dist
        # 자모 길이별로 후보를 묶어 탐색량을 줄임
        self._by_len = {}
        self._jamo = {}
        for w, f in word_freq.items():
            if f < min_freq:
                continue
            j = text_to_jamo(w)
            self._jamo[w] = j
            self._by_len.setdefault(len(j), []).append(w)

    def _best_candidate(self, tok: str):
        if tok in self.word_freq:
            return tok
        jt = text_to_jamo(tok)
        best, best_f = None, -1
        for dl in range(-self.max_jamo_dist, self.max_jamo_dist + 1):
            for w in self._by_len.get(len(jt) + dl, ()):
                d = _edit_distance(jt, self._jamo[w], self.max_jamo_dist)
                if d <= self.max_jamo_dist and self.word_freq[w] > best_f:
                    best, best_f = w, self.word_freq[w]
        return best or tok

    def correct(self, text: str) -> str:
        return " ".join(self._best_candidate(t) for t in text.split(" "))
