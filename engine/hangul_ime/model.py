"""
model.py — 띄어쓰기 통계 모델 컨테이너 + 피처 추출.

핵심 아이디어: 띄어쓰기를 '음절 사이 경계(gap)마다 띄움/붙임 라벨을 매기는
시퀀스 라벨링' 문제로 본다. 규칙으로 '걸'을 풀 수 없는 이유가 여기 있다 ―
같은 음절도 앞뒤 문맥에 따라 띄움/붙임이 달라지므로, 경계 결정은 반드시
'주변 음절'을 조건으로 해야 한다.

이 프로토타입은 경계 결정을 나이브베이즈 로그-오즈로 점수화한다:
    lo(gap) = log P(띄움) - log P(붙임)
            = log P(띄움)/P(붙임)  +  Σ_feature [log P(f|띄움) - log P(f|붙임)]
피처는 경계를 둘러싼 음절 n-gram이다(아래 gap_features). 이렇게 하면
'을\t걸'(붙임 경향)과 'ㄴ\t걸'(띄움 경향)이 데이터로부터 다른 점수를 받는다.

생산 단계의 고정확도 엔진(신경망 CRF)도 동일한 인터페이스(경계별 점수)를
내보내므로 spacing.py의 디코더를 그대로 재사용한다. 자세한 내용은 docs/DESIGN.md.
"""
import json
import math

from .morphology import morph_gap_features

SEP = "\t"          # 피처 family와 값 구분자 (JSON 안전)
BOS = "^"           # 문자열 시작 센티넬
EOS = "$"           # 문자열 끝 센티넬


def gap_features(text: str, i: int):
    """text의 i번째 경계(text[i-1]과 text[i] 사이)를 설명하는 피처 키 목록.

    표면 음절 피처(P/L/R/TL/TR)와 품사 범주 피처(morphology.morph_gap_features:
    JL=조사 종결, EL=어미 종결, UR=의존명사 선행, ADNU=관형형+의존명사)를 합친다.
    품사 피처 덕분에 '걸'뿐 아니라 같은 품사 패턴의 모든 단어로 규칙이 일반화된다.
    """
    n = len(text)
    L = text[i - 1]
    R = text[i]
    LL = text[i - 2] if i - 2 >= 0 else BOS
    RR = text[i + 1] if i + 1 < n else EOS
    feats = [
        "P" + SEP + L + R,
        "L" + SEP + L,
        "R" + SEP + R,
        "TL" + SEP + LL + L + R,
        "TR" + SEP + L + R + RR,
    ]
    feats.extend(morph_gap_features(text, i))
    return feats


def _softplus(x: float) -> float:
    # log(1+e^x), 오버플로 안전
    if x > 30:
        return x
    if x < -30:
        return 0.0
    return math.log1p(math.exp(x))


class SpacingModel:
    """학습된 경계 통계 + 어절 사전. JSON으로 직렬화된다."""

    def __init__(self):
        self.alpha = 0.7          # 라플라스 스무딩
        self.S = 0                # 띄움 경계 총수
        self.N = 0                # 붙임 경계 총수
        self.feats = {}           # key -> [count_space, count_nospace]
        self.fam_vocab = {}       # family -> 고유 키 수 (스무딩 분모)
        self.word_freq = {}       # 어절 -> 빈도
        self.total_words = 0
        # 디코더 가중치 (train 후 튜닝값으로 덮어씀)
        self.w_word = 0.6         # 어절 사전 보너스 가중
        self.known_bonus = 1.2    # 사전에 있는 어절 가산점
        self.oov_char = -0.55     # 미등록 음절당 비용
        self.max_word = 12        # 디코더가 시도할 최대 어절 길이
        self.space_penalty = 0.0  # 경계마다 띄울 때 빼는 패널티(과분할 억제 정규화)

    # --- 경계 점수 ---------------------------------------------------------
    def gap_logodds(self, feats) -> float:
        a = self.alpha
        lo = math.log((self.S + a) / (self.N + a))     # 사전확률 로그-오즈
        for key in feats:
            cs, cn = self.feats.get(key, (0, 0))
            fam = key.split(SEP, 1)[0]
            V = self.fam_vocab.get(fam, 1)
            ps = (cs + a) / (self.S + a * V)
            pn = (cn + a) / (self.N + a * V)
            lo += math.log(ps) - math.log(pn)
        return lo

    def gap_scores(self, text: str):
        """경계별 (cut_score, nocut_score) 리스트. 인덱스 i는 text[i-1]|text[i]."""
        n = len(text)
        cut = [0.0] * n
        nocut = [0.0] * n
        for i in range(1, n):
            lo = self.gap_logodds(gap_features(text, i))
            cut[i] = -_softplus(-lo)     # log sigmoid(lo)  = log P(띄움)
            nocut[i] = -_softplus(lo)    # log sigmoid(-lo) = log P(붙임)
        return cut, nocut

    def word_bonus(self, tok: str) -> float:
        a = self.alpha
        f = self.word_freq.get(tok)
        if f:
            V = max(1, len(self.word_freq))
            return self.known_bonus + self.w_word * math.log(
                (f + a) / (self.total_words + a * V)
            )
        return len(tok) * self.oov_char

    # --- 직렬화 ------------------------------------------------------------
    def to_dict(self):
        return {
            "alpha": self.alpha, "S": self.S, "N": self.N,
            "feats": {k: v for k, v in self.feats.items()},
            "fam_vocab": self.fam_vocab,
            "word_freq": self.word_freq, "total_words": self.total_words,
            "w_word": self.w_word, "known_bonus": self.known_bonus,
            "oov_char": self.oov_char, "max_word": self.max_word,
            "space_penalty": self.space_penalty,
        }

    @classmethod
    def from_dict(cls, d):
        m = cls()
        m.alpha = d["alpha"]; m.S = d["S"]; m.N = d["N"]
        m.feats = {k: tuple(v) for k, v in d["feats"].items()}
        m.fam_vocab = d["fam_vocab"]
        m.word_freq = d["word_freq"]; m.total_words = d["total_words"]
        for k in ("w_word", "known_bonus", "oov_char", "max_word", "space_penalty"):
            if k in d:
                setattr(m, k, d[k])
        return m

    def save(self, path):
        with open(path, "w", encoding="utf-8") as f:
            json.dump(self.to_dict(), f, ensure_ascii=False)

    @classmethod
    def load(cls, path):
        with open(path, encoding="utf-8") as f:
            return cls.from_dict(json.load(f))
