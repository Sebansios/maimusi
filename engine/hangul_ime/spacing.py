"""
spacing.py — 자동 띄어쓰기 엔진.

설계 핵심: '경계 점수 생성기'와 '디코더'를 분리한다.
  - 점수 생성기: 각 음절 경계의 (띄움 점수, 붙임 점수)를 만든다.
      * 프로토타입(오프라인·무학습데이터): SpacingModel의 음절 n-gram 나이브베이즈.
      * 생산(고정확도): 신경망 CRF가 같은 형태의 경계 점수를 출력 -> 디코더 재사용.
  - 디코더: 경계 점수 + 어절 사전 보너스를 결합해 Viterbi(분절 DP)로 전역 최적
    띄어쓰기를 찾는다. 음절 단위가 아니라 '문장 전체'를 보고 결정하므로
    한 글자 어절 남발 같은 국소 오류를 줄인다.

모든 Spacer는 동일한 인터페이스(space(text)->str)를 가지므로, 플랫폼/정확도
요구에 따라 백엔드만 교체하면 된다.
"""
from abc import ABC, abstractmethod
from .model import SpacingModel


class Spacer(ABC):
    """무공백 문자열 -> 띄어쓰기 적용 문자열."""

    @abstractmethod
    def space(self, text: str) -> str:
        ...


def viterbi_decode(text: str, cut, nocut, model, extra_token=None) -> str:
    """경계 점수(cut/nocut)와 어절 사전으로 최적 분절을 찾는다.

    dp[i] = text[:i]를 어절 경계 i에서 끊었을 때의 최대 누적 점수.
    토큰 text[j:i]의 점수 = (앞 경계 j에서 띄움) + (내부 경계 모두 붙임) + 어절보너스
                          + (선택) extra_token(토큰) [형태론 타당성 점수].
    """
    n = len(text)
    if n <= 1:
        return text
    # 내부 '붙임' 점수의 누적합: pn[k] = nocut[1]+...+nocut[k]
    pn = [0.0] * n
    for k in range(1, n):
        pn[k] = pn[k - 1] + nocut[k]

    NEG = float("-inf")
    dp = [NEG] * (n + 1)
    back = [0] * (n + 1)
    dp[0] = 0.0
    maxw = model.max_word
    penalty = getattr(model, "space_penalty", 0.0)   # 과분할 억제 정규화
    for i in range(1, n + 1):
        j0 = max(0, i - maxw)
        for j in range(j0, i):
            if dp[j] == NEG:
                continue
            # 내부 경계 j+1..i-1 은 붙임
            internal = pn[i - 1] - pn[j] if i - 1 >= j else 0.0
            tok = text[j:i]
            score = dp[j] + internal + model.word_bonus(tok)
            if extra_token is not None:
                score += extra_token(tok)
            if j > 0:                      # 토큰 앞 경계 = 띄움
                score += cut[j] - penalty
            if score > dp[i]:
                dp[i] = score
                back[i] = j
    # 역추적 -> 끊는 위치 집합
    cuts = set()
    i = n
    while i > 0:
        j = back[i]
        if j > 0:
            cuts.add(j)
        i = j
    out = []
    for idx, ch in enumerate(text):
        if idx in cuts:
            out.append(" ")
        out.append(ch)
    return "".join(out)


class NgramViterbiSpacer(Spacer):
    """음절 n-gram 나이브베이즈 + Viterbi 디코더 (프로토타입 기본 엔진)."""

    def __init__(self, model: SpacingModel):
        self.model = model

    @classmethod
    def from_file(cls, path: str):
        return cls(SpacingModel.load(path))

    def space(self, text: str) -> str:
        # 이미 들어있는 공백은 제거하고 다시 계산(변환 키 UX 전제: 무공백 입력)
        raw = text.replace(" ", "")
        if len(raw) <= 1:
            return raw
        cut, nocut = self.model.gap_scores(raw)
        return viterbi_decode(raw, cut, nocut, self.model)

    def gap_probs(self, text: str):
        """진단용: 각 경계의 띄움 확률(0~1)."""
        import math
        raw = text.replace(" ", "")
        cut, nocut = self.model.gap_scores(raw)
        out = []
        for i in range(1, len(raw)):
            p = math.exp(cut[i])            # cut[i] = log P(띄움)
            out.append((raw[i - 1], raw[i], round(p, 3)))
        return out


class MorphViterbiSpacer(Spacer):
    """통계 경계모델 + 형태소 분석 어절 검증을 결합한 띄어쓰기기.

    n-gram 경계 점수에, 형태론적으로 타당한 어절(체언+조사/어간+어미/의존명사)에
    가산점·부적격 결합에 벌점을 주는 token_score를 더한다. '단어 단위 띄어쓰기'
    원리를 디코더가 직접 강제하므로, 학습에서 못 본 의존명사 구성도 규칙으로 분리된다.
    """

    def __init__(self, model: SpacingModel, noun: dict, stem: dict, w_morph: float = 1.0):
        from . import morphology
        self.model = model
        self.noun = noun
        self.stem = stem
        self.w_morph = w_morph
        self._ts = morphology.token_score

    @classmethod
    def from_files(cls, model_path: str, lex_path: str, w_morph: float = 1.0):
        import json
        m = SpacingModel.load(model_path)
        with open(lex_path, encoding="utf-8") as f:
            lex = json.load(f)
        return cls(m, lex.get("noun", {}), lex.get("stem", {}), w_morph)

    def space(self, text: str) -> str:
        raw = text.replace(" ", "")
        if len(raw) <= 1:
            return raw
        cut, nocut = self.model.gap_scores(raw)
        wt, ts, noun, stem = self.w_morph, self._ts, self.noun, self.stem
        return viterbi_decode(
            raw, cut, nocut, self.model,
            extra_token=lambda tok: wt * ts(tok, noun, stem),
        )


class NeuralSpacer(Spacer):
    """생산용 고정확도 백엔드 (설계 자리표시자).

    DESIGN.md의 학습 파이프라인으로 만든 양자화 모델(ONNX)을 로드해 경계 점수를
    내고, 위 viterbi_decode를 그대로 재사용한다. 본 프로토타입 세션에서는
    런타임/모델 파일이 없으므로 미구현이다. Rust 코어에서는 `tract` 추론으로
    대체된다(의존성 없는 순수 Rust ONNX 실행기).
    """

    def __init__(self, model_path: str):
        self.model_path = model_path
        raise NotImplementedError(
            "NeuralSpacer는 학습된 모델이 필요합니다. "
            "core/scripts/train_neural.py 및 docs/DESIGN.md 참고."
        )

    def space(self, text: str) -> str:  # pragma: no cover
        raise NotImplementedError
