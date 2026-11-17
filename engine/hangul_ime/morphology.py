"""
morphology.py — 품사(POS) 기반 띄어쓰기 일반화 자원·피처.

한글 띄어쓰기의 핵심 원리는 표면 음절이 아니라 형태소/품사다(한글 맞춤법 제2항:
단어는 띄어 쓰되 조사는 앞말에 붙임):
  - 조사(JOSA)·어미(EOMI)는 앞 형태소에 붙는다  -> 그 뒤에서 '단어 경계'가 생김.
  - 의존명사(UIJON: 것·수·줄·데·바·걸·만큼·대로…)는 앞말과 띄운다.
  - 의존명사 vs 동음 조사("먹을 만큼"↔"너만큼")는 '관형형(어간+ㄴ/ㄹ/는/던) 뒤'인지로
    갈린다 -> 이것이 '걸'을 포함한 의존명사 전반의 일반 규칙이다.

이 모듈은 '걸' 하나를 특례로 박지 않는다. 위 규칙들을 **폐쇄집합 사전 + 코퍼스 유도
어간**으로 일반화하고, 각 경계에 품사 범주 피처를 부여한다. 모델은 이 피처들의 가중치를
코퍼스에서 학습하므로, 같은 품사 패턴을 가진 '모든' 단어로 규칙이 일반화된다.

Rust 포팅: 아래 집합은 const 테이블, 피처 함수는 순수 함수로 1:1 대응된다.
"""
import math
from .jamo import decompose, compose, JONG

# 받침으로 실현되는 어미(관형형 -ㄴ/-ㄹ, 명사형 -ㅁ) 추정용 종성
CODA_EOMI = ("ㄴ", "ㄹ", "ㅁ")

# 의존명사이면서 동시에 종결/연결 어미로도 쓰이는 동음 형태(걸/게/데/지/대/래…).
# 표면만으로는 띄움/붙임이 갈리지 않으므로(올걸=어미 vs 예쁜 걸=의존명사) 형태론으로
# 강제하지 않고 '통계에 위임'한다. '걸' 특례 박기가 아니라, 동음 어미 집합 전반의 규칙.
_AMBIG_END = set("걸게데지대래")

# ── 조사(체언 뒤 부속, 붙임) ─ 격/보조/접속조사 표면형 ────────────────────────
JOSA = {
    "이", "가", "을", "를", "은", "는", "의", "에", "도", "만", "와", "과", "로",
    "랑", "나", "께", "야", "에서", "에게", "한테", "께서", "에게서", "한테서",
    "으로", "으로서", "으로써", "로서", "로써", "이랑", "이나", "처럼", "보다",
    "까지", "부터", "조차", "마저", "마다", "밖에", "이며", "이라고", "라고",
    "이라는", "라는", "이든지", "든지", "이라도", "라도", "커녕", "은커녕",
    "는커녕", "마는", "이야", "이야말로", "야말로", "더러", "보고", "한테로",
}

# ── 어미(용언 어간 뒤, 붙임) ─ 종결/연결/전성 표면형 ─────────────────────────
EOMI = {
    "다", "까", "요", "죠", "지", "네", "군", "구나", "는구나", "더라", "더군",
    "니", "니까", "으니까", "으니", "면", "으면", "면서", "으면서", "고", "거나",
    "지만", "는데", "은데", "ㄴ데", "아서", "어서", "여서", "아도", "어도",
    "으며", "며", "도록", "든", "자", "자마자", "았다", "었다", "였다", "겠다",
    "았어", "었어", "았지", "었지", "ㄴ다", "는다", "한다", "ㅂ니다", "습니다",
    "ㅂ니까", "습니까", "았습니다", "었습니다", "으세요", "세요", "으십시오",
    "십시오", "아요", "어요", "여요", "에요", "예요", "이에요", "았어요", "었어요",
    "나요", "지요", "네요", "군요", "으려고", "려고", "으러", "러", "기", "음",
    "ㅁ", "래", "대", "든가", "잖아", "거든", "더라고", "더라구",
}

# ── 의존명사(앞말과 띄움) + 자주 쓰는 단위명사 ──────────────────────────────
UIJON = {
    "것", "거", "걸", "게", "수", "줄", "바", "데", "때", "적", "만큼", "대로",
    "뿐", "채", "척", "체", "양", "등", "들", "따위", "나름", "김", "통", "차",
    "판", "셈", "리", "겸", "나위", "무렵", "즈음", "따름", "녘", "법", "만",
    "뻔", "축", "둥", "품", "길", "측", "분", "명", "개", "마리", "권", "장",
    "대", "번", "살", "그루", "송이", "켤레", "벌", "잔", "그릇", "병", "캔",
    "회", "차례", "가지", "종류", "쪽", "군데", "평", "곳", "달", "년", "월", "일",
}

_JOSA_MAX = max(len(x) for x in JOSA)
_EOMI_MAX = max(len(x) for x in EOMI)
_UIJON_MAX = max(len(x) for x in UIJON)

SEP = "\t"


def _suffix_in(text, i, vocab, maxlen):
    """text[..i) 의 끝에서 vocab에 속하는 가장 긴 접미(길이>=1)를 반환, 없으면 None."""
    for L in range(min(maxlen, i), 0, -1):
        if text[i - L:i] in vocab:
            return text[i - L:i]
    return None


def _prefix_in(text, i, vocab, maxlen, n):
    """text[i..) 의 앞에서 vocab에 속하는 가장 긴 접두를 반환, 없으면 None."""
    for L in range(min(maxlen, n - i), 0, -1):
        if text[i:i + L] in vocab:
            return text[i:i + L]
    return None


def is_adnominal_end(ch):
    """관형형 종결 추정: 받침이 ㄴ/ㄹ(은·ㄴ·을·ㄹ) 이거나 음절이 는/던."""
    if ch in ("는", "던"):
        return True
    d = decompose(ch)
    return bool(d) and JONG[d[2]] in ("ㄴ", "ㄹ")


def morph_gap_features(text, i):
    """경계 i(text[i-1]|text[i])에 대한 품사 범주 피처.

    family: JL=좌측 조사 종결, EL=좌측 어미 종결, UR=우측 의존명사 시작,
            ADNU=관형형+의존명사(걸·것·수… 일반 규칙).
    값은 일반화를 위해 '범주 신호'로 묶는다(개별 표면형이 아니라 패턴).
    """
    n = len(text)
    feats = []
    josa = _suffix_in(text, i, JOSA, _JOSA_MAX)
    if josa:
        feats.append("JL" + SEP + "1")          # 조사 뒤 = 단어 경계 신호
    eomi = _suffix_in(text, i, EOMI, _EOMI_MAX)
    if eomi:
        feats.append("EL" + SEP + "1")          # 어미 뒤 = 단어 경계 신호
    uijon = _prefix_in(text, i, UIJON, _UIJON_MAX, n)
    if uijon:
        feats.append("UR" + SEP + uijon)        # 의존명사 앞 = 띄움 신호(표면형별 학습)
        if is_adnominal_end(text[i - 1]):
            feats.append("ADNU" + SEP + "1")     # 관형형+의존명사 = 강한 띄움 신호
    return feats


# ──────────────────────────────────────────────────────────────────────────
# 형태소 분석 기반 어절 검증 (코퍼스 유도 어간 + 폐쇄집합 규칙)
#
# '단어(어절) 단위로 띄운다'는 원리를 직접 구현한다. 후보 토큰이 형태론적으로
# 타당한 어절인지 점수화한다:  체언+조사 | 어간+어미 | 의존명사(+조사).
# 타당하면 +점수, 아니면(예: '갈수'=관형형+의존명사가 한 덩어리) 음수 -> 디코더가
# 잘못된 결합을 거부하고 경계를 넣는다. 이로써 '걸'을 포함한 의존명사 분리가
# 특례가 아니라 규칙으로 일반화된다.
# ──────────────────────────────────────────────────────────────────────────

def strip_coda(syl):
    """음절의 받침을 떼어 (받침없는음절, 받침자모) 반환. 받침 없으면 None."""
    d = decompose(syl)
    if not d or d[2] == 0:
        return None
    return compose(d[0], d[1], 0), JONG[d[2]]


def analyze_eojeol(w, noun, stem):
    """어절 w의 최적 형태 분석을 (점수, 라벨)로. noun/stem: 표면형->빈도 dict.

    라벨: NOUN(체언) / N+J(체언+조사) / V+E(어간+어미) / V+ETM(관형형·명사형) /
          UIJON(의존명사+조사) / OOV.
    """
    best, label = None, "OOV"

    def upd(score, lab):
        nonlocal best, label
        if best is None or score > best:
            best, label = score, lab

    if w in noun:
        upd(0.5 + 0.25 * math.log1p(noun[w]), "NOUN")          # 체언/부사/관형사
    j = _suffix_in(w, len(w), JOSA, _JOSA_MAX)                  # 체언 + 조사
    if j and len(w) > len(j) and w[:-len(j)] in noun:
        upd(1.0 + 0.25 * math.log1p(noun[w[:-len(j)]]), "N+J")
    e = _suffix_in(w, len(w), EOMI, _EOMI_MAX)                  # 어간 + 어미(음절형)
    if e and len(w) > len(e) and w[:-len(e)] in stem:
        upd(1.0 + 0.25 * math.log1p(stem[w[:-len(e)]]), "V+E")
    sc = strip_coda(w[-1])                                      # 어간 + 어미(받침형: 관형형/명사형)
    if sc and sc[1] in CODA_EOMI:
        cand = w[:-1] + sc[0]
        if cand in stem:
            upd(0.8 + 0.25 * math.log1p(stem[cand]), "V+ETM")
    u = _prefix_in(w, 0, UIJON, _UIJON_MAX, len(w))             # 의존명사 (+조사)
    if u:
        rest = w[len(u):]
        if rest == "" or rest in JOSA or _suffix_in(rest, len(rest), JOSA, _JOSA_MAX) == rest:
            upd(0.7, "UIJON")
    if best is None:
        if len(w) >= 2 and w[-1] in _AMBIG_END:                # 동음 어미 -> 통계에 위임
            return 0.0, "AMBIG"
        best = -0.45 * len(w)                                   # 미분석(OOV) 음절당 벌점
    return best, label


def token_score(w, noun, stem):
    """어절 타당성 '제약'. 타당하면 0, 형태론적으로 미분석(OOV)이면 음절당 벌점.

    보상이 아니라 벌점만 준다 -> 과분할을 유도하지 않으면서, '갈수'(관형형+의존명사가
    한 덩어리)처럼 부적격한 결합만 디코더가 깨도록 만든다. 한 글자는 약하게 벌점.
    """
    _, label = analyze_eojeol(w, noun, stem)
    if label != "OOV":
        return 0.0
    return -1.0 * (len(w) if len(w) >= 2 else 0.5)

