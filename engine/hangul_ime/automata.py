"""
automata.py — 두벌식 한글 입력 오토마타.

키보드에서 들어오는 '호환 자모'(ㄱ, ㅏ, ㅄ ...) 시퀀스를 받아 완성형 음절로
조합한다. 표준 두벌식 동작을 구현한다:
  - 초성 -> 중성 -> 종성 순서로 음절을 쌓는다.
  - 겹모음(ㅗ+ㅏ=ㅘ), 겹받침(ㄹ+ㄱ=ㄺ)을 결합한다.
  - 받침 뒤에 모음이 오면 받침(또는 겹받침의 뒷자음)이 다음 음절의 초성으로 넘어간다.
    예) '각' + 'ㅏ' -> '가' + '가'  /  '갉' + 'ㅏ' -> '갈' + '가'

스페이스(변환 키)·문장부호 등 자모가 아닌 입력이 오면 현재 조합 중인 음절을
확정(flush)한다. IME 상위 계층(engine.py)이 이 오토마타를 구동한다.

Rust 포팅: 상태 (cho/jung/jong: Option<u8>) + match 기반 전이로 1:1 대응된다.
"""
from .jamo import (
    CHO, JUNG, JONG, CHO_IDX, JUNG_IDX, JONG_IDX,
    VOWEL_COMBINE, JONG_COMBINE, JONG_SPLIT, compose,
)


class Hangul2Automaton:
    """두벌식 조합 상태 기계. cho/jung/jong은 인덱스(None=없음)."""

    def __init__(self):
        self.committed = []   # 확정된 글자들
        self.cho = None
        self.jung = None
        self.jong = None      # JONG 인덱스(>=1) 또는 None

    # --- 출력 ---------------------------------------------------------------
    def _compose_current(self) -> str:
        if self.cho is not None and self.jung is not None:
            return compose(self.cho, self.jung, self.jong or 0)
        if self.cho is not None:
            return CHO[self.cho]          # 초성만 -> 자음 자모
        if self.jung is not None:
            return JUNG[self.jung]        # 중성만 -> 모음 자모
        return ""

    def preedit(self) -> str:
        """현재 조합 중(미확정) 글자."""
        return self._compose_current()

    def text(self) -> str:
        """확정분 + 조합 중을 합친 전체 문자열."""
        return "".join(self.committed) + self._compose_current()

    def _flush(self):
        cur = self._compose_current()
        if cur:
            self.committed.append(cur)
        self.cho = self.jung = self.jong = None

    def flush(self):
        """외부에서 조합 강제 확정 (변환 키/포커스 이동 등)."""
        self._flush()

    def reset(self):
        self.committed = []
        self.cho = self.jung = self.jong = None

    # --- 입력 ---------------------------------------------------------------
    def feed(self, ch: str):
        if ch in JUNG_IDX:
            self._feed_vowel(ch)
        elif ch in CHO_IDX:
            self._feed_consonant(ch)
        else:
            # 자모가 아님(숫자·기호 등): 조합 확정 후 그대로 출력
            self._flush()
            self.committed.append(ch)
        return self

    def feed_text(self, s: str):
        for ch in s:
            self.feed(ch)
        return self

    # --- 전이 ---------------------------------------------------------------
    def _feed_vowel(self, v: str):
        vidx = JUNG_IDX[v]
        if self.jong is not None:
            # 받침을 다음 음절 초성으로 이동
            moved_cho, keep_jong = self._split_jong_for_move()
            self.jong = keep_jong
            self.committed.append(self._compose_current())
            self.cho, self.jung, self.jong = moved_cho, vidx, None
        elif self.cho is not None and self.jung is None:
            self.jung = vidx                       # 초성 + 중성
        elif self.jung is not None:
            cur = JUNG[self.jung]
            comb = VOWEL_COMBINE.get((cur, v))     # 겹모음 결합 시도
            if comb:
                self.jung = JUNG_IDX[comb]
            else:
                self._flush()
                self.jung = vidx                   # 모음만 새로 시작
        else:
            self.jung = vidx

    def _feed_consonant(self, c: str):
        if self.cho is None and self.jung is None:
            self.cho = CHO_IDX[c]
        elif self.jung is None:
            self._flush()                          # 자음 연속 -> 앞 자음 확정
            self.cho = CHO_IDX[c]
        elif self.cho is None:
            self._flush()                          # 모음 뒤 자음 -> 모음 확정
            self.cho = CHO_IDX[c]
        elif self.jong is None:
            if c in JONG_IDX:
                self.jong = JONG_IDX[c]            # 종성 채움
            else:
                self._flush()                      # 종성 불가(ㄸㅃㅉ) -> 새 초성
                self.cho = CHO_IDX[c]
        else:
            curj = JONG[self.jong]
            comb = JONG_COMBINE.get((curj, c))     # 겹받침 결합 시도
            if comb:
                self.jong = JONG_IDX[comb]
            else:
                self._flush()
                self.cho = CHO_IDX[c]

    def _split_jong_for_move(self):
        """현재 종성에서 다음 초성으로 옮길 자음과 남길 종성 인덱스를 반환."""
        jc = JONG[self.jong]
        if jc in JONG_SPLIT:                        # 겹받침: 뒷자음만 이동
            keep, move = JONG_SPLIT[jc]
            return CHO_IDX[move], JONG_IDX[keep]
        return CHO_IDX[jc], None                    # 홑받침: 통째로 이동


def compose_keystrokes(jamo_seq: str) -> str:
    """편의 함수: 자모 시퀀스 -> 완성형 문자열."""
    a = Hangul2Automaton()
    a.feed_text(jamo_seq)
    a.flush()
    return a.text()
