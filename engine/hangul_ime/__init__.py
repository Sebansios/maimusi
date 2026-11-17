"""
hangul_ime — 변환 키(스페이스) 기반 한글 IME 공통 로직 레퍼런스 구현.

모듈
  jamo      : 음절 조합/분해, 자모 테이블
  automata  : 두벌식 입력 오토마타(자모 -> 음절)
  model     : 띄어쓰기 통계 모델(경계 n-gram) 컨테이너/피처
  spacing   : 자동 띄어쓰기 엔진(Spacer 인터페이스 + Viterbi 디코더)
  correct   : 선택적 맞춤법/오타 교정
  engine    : 변환 키 오케스트레이터

오토마타·통계 코어는 표준 라이브러리를 사용한다. 입력기 엔진 서비스
(ime_service)는 Kiwi, Pint, 한국 음력 라이브러리와 공개 Unicode/한자 데이터를 쓴다.
"""
from .automata import Hangul2Automaton, compose_keystrokes
from .model import SpacingModel
from .spacing import (
    Spacer, NgramViterbiSpacer, MorphViterbiSpacer, NeuralSpacer, viterbi_decode,
)
from .correct import Corrector, NoopCorrector, DictionaryCorrector
from .engine import ImeEngine
from .word_transform import (
    ConversionCandidate, WordSpan, WordConverter,
    EmojiRecord, EmojiRegistry, EmojiConverter, HanjaConverter,
    UnitDefinition, UnitConverter, Era, DEFAULT_ERAS, DateConverter,
    JamoUnicodeConverter, load_eras,
    WordTransformer, default_word_transformer, WordTransformSession,
)
from . import morphology
from .settings import (
    SETTINGS_FORMAT_VERSION, WIDTH_MODES, PUNCTUATION_PROFILES, BRACKET_PROFILES,
    InputBehaviorSettings, TypographySettings, SettingsStore, settings_schema,
)
from .customization import (
    ConversionRule, CustomConversionConverter, CustomConversionRegistry, LearningStore,
)

__all__ = [
    "Hangul2Automaton", "compose_keystrokes",
    "SpacingModel",
    "Spacer", "NgramViterbiSpacer", "MorphViterbiSpacer", "NeuralSpacer",
    "viterbi_decode", "morphology",
    "Corrector", "NoopCorrector", "DictionaryCorrector",
    "ImeEngine",
    "ConversionCandidate", "WordSpan", "WordConverter",
    "EmojiRecord", "EmojiRegistry", "EmojiConverter", "HanjaConverter",
    "UnitDefinition", "UnitConverter", "Era", "DEFAULT_ERAS", "DateConverter",
    "JamoUnicodeConverter", "load_eras",
    "WordTransformer", "default_word_transformer", "WordTransformSession",
    "SETTINGS_FORMAT_VERSION", "WIDTH_MODES", "PUNCTUATION_PROFILES", "BRACKET_PROFILES",
    "InputBehaviorSettings", "TypographySettings", "SettingsStore", "settings_schema",
    "ConversionRule", "CustomConversionConverter", "CustomConversionRegistry", "LearningStore",
]
from ._version import PRODUCT_VERSION as __version__, ENGINE_VERSION as __engine_version__

