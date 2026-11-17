"""
engine.py — '변환 키(스페이스)' 오케스트레이터.

UX 모델: 사용자는 공백 없이 자모를 입력한다. 오토마타가 음절을 조합한다.
스페이스(변환 키)를 누르면, 지금까지의 본문을 띄어쓰기 엔진으로 변환해 확정한다.

상태:
  - automaton : 현재 조합 중인 절(아직 변환 안 된 무공백 음절들)
  - _raw      : 이미 변환된 본문의 무공백 원형(문장 단위로 누적)
  - display   : 마지막 변환 결과(공백 포함)

새 조합 절만 띄어쓰기하고 이미 확정한 변환은 유지한다.
데스크톱 편집기는 운영체제 조합을 사용하므로 이 자모 오토마타와 분리된다.
문장 종료(end_sentence) 시 명시적으로 학습하고 버퍼를 리셋한다.
"""
from .automata import Hangul2Automaton
from .correct import NoopCorrector
from .word_transform import (
    WordTransformSession,
    WordTransformer,
    default_word_transformer,
)
from .settings import TypographySettings
from .customization import LearningStore


class ImeEngine:
    def __init__(
        self,
        spacer,
        corrector=None,
        word_transformer=None,
        settings=None,
        learning=None,
        custom_converter=None,
    ):
        self.automaton = Hangul2Automaton()
        self.spacer = spacer
        self.corrector = corrector or NoopCorrector()
        self.settings = settings or TypographySettings()
        self.learning = learning if learning is not None else LearningStore()
        transformer = word_transformer or default_word_transformer(
            custom_converter=custom_converter
        )
        session_learning = None if self.settings.input.private_mode or not getattr(self.settings, "conversion_learning", True) else self.learning
        self.word_session = WordTransformSession(transformer, learning=session_learning)
        self.correction_enabled = False
        self._raw = ""        # 변환 확정된 무공백 본문
        self.display = ""     # 마지막 변환 결과(공백 포함)

    # --- 입력 --------------------------------------------------------------
    def input_jamo(self, ch: str):
        """자모/문자 한 개를 조합기에 투입."""
        self.automaton.feed(ch)
        return self

    def input_text(self, s: str):
        """자모 시퀀스를 한꺼번에 투입(테스트/데모 편의)."""
        self.automaton.feed_text(s)
        return self

    def preedit(self) -> str:
        """현재 조합 중인 절(미변환)."""
        return self.automaton.text()

    def full_text(self) -> str:
        """확정 표시 + 현재 조합 중."""
        pre = self.preedit()
        if self.display and pre:
            return self.display + pre
        return self.display or pre

    # --- 변환 키 -----------------------------------------------------------
    def _commit_spacing(self) -> str:
        """현재 조합을 확정하고 본문 전체를 띄어쓴다."""
        clause = self.automaton.text()
        self.automaton.reset()
        if not clause:
            return self.display
        # A new clause must not destroy a previously accepted conversion.
        self.word_session.commit()
        spaced = self.convert_string(clause)
        self.display += spaced
        self._raw = self.display
        self.word_session.load(self.display)
        return self.display

    def convert(self) -> str:
        """스페이스 처리.

        조합 중인 텍스트가 있으면 기존처럼 띄어쓰기를 확정한다. 조합 중인
        텍스트가 없고 이미 확정된 문장이 있으면 현재 선택 어절의 다음
        변환 후보를 적용한다.
        """
        if self.automaton.text():
            return self._commit_spacing()
        if self.display:
            self.display = self.word_session.cycle()
        return self.display

    def move_word(self, delta: int):
        """어절 선택 커서를 좌(delta=-1)/우(delta=+1)로 이동한다."""
        return self.word_session.move(delta)

    def move_left(self):
        return self.move_word(-1)

    def move_right(self):
        return self.move_word(1)

    def select_word(self, index: int):
        return self.word_session.select(index)

    def selected_word(self):
        return self.word_session.selected_word()

    def word_spans(self):
        return self.word_session.spans()

    def word_candidates(self):
        """현재 선택 어절의 후보와 변환기 이름을 반환한다."""
        return self.word_session.candidates()

    def handle_key(self, key: str):
        """플랫폼 바인딩이 공통 코어로 넘길 최소 키 이벤트."""
        if key in ("LEFT", "ARROWLEFT", "\x1b[D"):
            return self.move_left()
        if key in ("RIGHT", "ARROWRIGHT", "\x1b[C"):
            return self.move_right()
        if key in ("SHIFT+SPACE", "HANKAKU_ZENKAKU"):
            return self.toggle_width()
        if key in ("SPACE", " "):
            return self.convert()
        if len(key) == 1 and key in ",，、､.．。｡?!？！:：;；/／\\＼":
            return self.input_punctuation(key)
        return self.input_jamo(key)

    def end_sentence(self, punct: str = ""):
        """문장 종료: 남은 조합 확정 후 본문 버퍼를 비운다."""
        if self.automaton.text():
            self._commit_spacing()
        self.word_session.commit()
        out = self.display + punct
        self._raw = ""
        self.display = ""
        self.automaton.reset()
        self.word_session.reset()
        return out

    # --- 유틸 --------------------------------------------------------------
    def set_correction(self, enabled: bool):
        self.correction_enabled = enabled
        return self

    def set_settings(self, settings: TypographySettings):
        if not isinstance(settings, TypographySettings):
            raise TypeError("settings는 TypographySettings여야 합니다")
        selected = self.word_session.selected_index
        self.settings = settings
        self.word_session.learning = None if settings.input.private_mode or not getattr(settings, "conversion_learning", True) else self.learning
        return self

    def toggle_width(self):
        mode = self.settings.toggle_width()
        self.set_settings(self.settings)
        return mode

    def input_punctuation(self, symbol: str):
        """구두점 키 입력을 현재 설정으로 확정한다."""
        if self.automaton.text():
            self._commit_spacing()
        self.word_session.commit()
        self.display += self.settings.punctuation(symbol)
        self._raw = self.display
        self.word_session.load(self.display)
        return self.display

    def bracket_pair(self, kind: str = "double_quote"):
        return self.settings.bracket_pair(kind)

    def wrap_with_brackets(self, text: str, kind: str = "double_quote"):
        return self.settings.wrap(text, kind)

    def convert_string(self, text: str, *, preserve_phrase=False) -> str:
        """상태 없이 무공백 문자열 하나를 변환(배치/데모용)."""
        from .release_spacing import KiwiSpacer
        if isinstance(self.spacer, KiwiSpacer):
            spaced = self.spacer.space(text, self.settings.spacing, preserve_phrase=preserve_phrase)
        else:
            spaced = text if preserve_phrase or not self.settings.spacing.enabled else self.spacer.space(text)
        if self.correction_enabled:
            spaced = self.corrector.correct(spaced)
        return self.settings.format_text(spaced)

    def reset(self):
        self.automaton.reset()
        self._raw = ""
        self.display = ""
        self.word_session.reset()
        return self
