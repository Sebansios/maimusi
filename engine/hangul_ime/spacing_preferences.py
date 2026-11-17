"""Serializable spacing choices. No personal text or model dependency lives here."""
from dataclasses import asdict, dataclass, field, fields
from copy import deepcopy
import re

MODES = {"model": "모델 판단", "separate": "띄어 쓰기", "join": "허용 범위에서 붙이기"}
CATEGORIES = {"proper": "고유명사", "technical": "전문용어", "ambiguous_names": "구분이 필요한 성명", "compound": "개인 복합명사", "custom": "개인 예외"}
RULES = {
    "auxiliaries": ("보조 용언 전체", "보다·주다·두다·만하다·듯하다 등 전체에 공통 적용 · 제47항"),
    "compound": ("복합명사", "사전에 한 단어로 확인된 일반 명사만 붙임 · 명사구는 유지, 개인 사전은 우선 적용"),
    "number_units": ("아라비아 숫자 + 수량·단위", "10 개 ↔ 10개 · 제43항"),
    "date_units": ("숫자로 쓴 연·월·일", "2026 년 ↔ 2026년 · 제43항"),
    "time_units": ("시각의 시·분·초", "두 시 ↔ 두시 · 제43항"),
    "ordinals": ("순서를 나타내는 말", "삼 학년 ↔ 삼학년 · 제43항"),
    "short_words": ("연속된 한 음절 단어", "좀 더 큰 이 새 차 ↔ 좀더 큰 이 새차 · 제46항"),
    "proper": ("등록된 고유명사", "단어별 ↔ 의미 단위별 · 제49항"),
    "technical": ("등록된 전문용어", "단어별 ↔ 한 개념으로 붙이기 · 제50항"),
    "ambiguous_names": ("구분이 필요한 등록 성명", "성+이름 붙임이 원칙, 혼동 방지용 분리 허용 · 제48항"),
}


MAX_WORDS = 5000
MAX_LEARNED = 2000
MAX_WORD = 40
# 한글·영문·숫자로 된 낱말. 가운데에 붙은 문장부호(-·’)까지는 허용한다.
_WORD = re.compile(r"[가-힣A-Za-z0-9](?:[가-힣A-Za-z0-9\-·’']*[가-힣A-Za-z0-9])?")


@dataclass
class SpacingPreferences:
    enabled: bool = True
    existing_spaces: str = "preserve"
    auxiliaries: str = "separate"
    number_units: str = "model"
    date_units: str = "model"
    time_units: str = "model"
    ordinals: str = "model"
    short_words: str = "separate"
    proper: str = "model"
    technical: str = "model"
    ambiguous_names: str = "model"
    compound: str = "model"
    large_numbers: str = "standard"
    terms: list = field(default_factory=list)
    # 사용자 단어: 단어 안에는 띄어쓰기를 넣지 않는다.
    words: list = field(default_factory=list)
    # 손으로 고친 경계: 같은 표현이 나오면 그때의 띄어쓰기를 따른다.
    learned: list = field(default_factory=list)

    def validate(self):
        if type(self.enabled) is not bool:
            raise TypeError("자동 띄어쓰기: 참/거짓이 필요합니다")
        for key in RULES:
            if getattr(self, key) not in MODES:
                raise ValueError(f"띄어쓰기 {key}: 알 수 없는 방식입니다")
        if self.existing_spaces not in ("preserve", "normalize"):
            raise ValueError("기존 공백 처리 방식이 올바르지 않습니다")
        if self.large_numbers not in ("standard", "model"):
            raise ValueError("큰 수 표기 방식이 올바르지 않습니다")
        if type(self.terms) is not list or len(self.terms) > 1000:
            raise ValueError("띄어쓰기 사전은 최대 1,000행입니다")
        if type(self.words) is not list or len(self.words) > MAX_WORDS:
            raise ValueError(f"사용자 단어는 최대 {MAX_WORDS:,}개입니다")
        for word in self.words:
            if type(word) is not str or not 2 <= len(word) <= MAX_WORD or not _WORD.fullmatch(word):
                raise ValueError("사용자 단어는 띄어쓰기 없는 2–40자 낱말이어야 합니다")
        if type(self.learned) is not list or len(self.learned) > MAX_LEARNED:
            raise ValueError(f"기억한 경계는 최대 {MAX_LEARNED:,}개입니다")
        for case in self.learned:
            if type(case) is not dict or set(case) != {"compact", "spaced"}:
                raise ValueError("기억한 경계에는 compact와 spaced가 필요합니다")
            compact, spaced = case["compact"], case["spaced"]
            if (type(compact) is not str or type(spaced) is not str or not 2 <= len(compact) <= MAX_WORD
                    or not _WORD.fullmatch(compact) or spaced.replace(" ", "") != compact
                    or "  " in spaced or spaced != spaced.strip()):
                raise ValueError("기억한 경계의 형식이 올바르지 않습니다")
        seen = set()
        for term in self.terms:
            if type(term) is not dict or set(term) != {"category", "spaced", "joined", "mode"}:
                raise ValueError("띄어쓰기 사전에는 종류·분리형·붙임형·방식이 필요합니다")
            if term["category"] not in CATEGORIES or term["mode"] not in (*MODES, "inherit"):
                raise ValueError("띄어쓰기 사전의 종류/방식이 올바르지 않습니다")
            if term["category"] == "custom" and term["mode"] == "inherit":
                raise ValueError("개인 예외의 방식은 직접 지정하세요")
            for key in ("spaced", "joined"):
                value = term[key]
                if type(value) is not str or len(value) > 80 or not re.fullmatch(r"[가-힣0-9]+(?: [가-힣0-9]+)*", value):
                    raise ValueError("분리형·붙임형에는 80자 이내 한글·숫자와 한 칸 공백만 사용하세요")
            source = term["spaced"].replace(" ", "")
            if source != term["joined"].replace(" ", "") or term["spaced"] == term["joined"]:
                raise ValueError("분리형과 붙임형은 글자가 같고 띄어쓰기만 달라야 합니다")
            if source in seen:
                raise ValueError("띄어쓰기 사전에 같은 표현이 두 번 있습니다")
            seen.add(source)
        return self

    @classmethod
    def from_dict(cls, payload):
        if type(payload) is not dict or set(payload) - {f.name for f in fields(cls)}:
            raise ValueError("알 수 없는 띄어쓰기 설정 항목입니다")
        return cls(**deepcopy(payload)).validate()

    def preset(self, name):
        if name not in ("standard", "permitted", "model"):
            raise ValueError("알 수 없는 띄어쓰기 프리셋입니다")
        mode = {"standard": "separate", "permitted": "join", "model": "model"}[name]
        for key in RULES:
            setattr(self, key, "model" if key == "compound" else mode)
        self.ambiguous_names = {"standard": "join", "permitted": "separate", "model": "model"}[name]
        return self


def load_spacing_preferences(path):
    from .persistence import load_json, checked_mapping, checked_version
    payload = load_json(path)
    checked_mapping(payload, ("schema_version", "spacing"), "띄어쓰기 설정")
    checked_version(payload, 1, "띄어쓰기 설정")
    return SpacingPreferences.from_dict(payload["spacing"])


def save_spacing_preferences(path, preferences):
    from pathlib import Path
    from .persistence import atomic_json_save
    path = Path(path)
    if path.exists():
        load_spacing_preferences(path)
    atomic_json_save(path, {"schema_version": 1, "spacing": asdict(preferences.validate())})
