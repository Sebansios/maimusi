"""Conservative, offset-based Korean spacing preferences.

Only ASCII spaces change. Morphological ambiguity is left to the base model;
unknown noun sequences are never assumed to be optional compounds.
"""
import re

# Small, explicitly reviewed seeds, not a purported full normative dictionary.
# Sources and conservative coverage boundaries: docs/SPACING_RULES.md.
BUILTIN_TERMS = (
    ("proper", "대한 중학교", "대한중학교"),
    ("proper", "한국 대학교 사범 대학", "한국대학교 사범대학"),
    ("proper", "국립 중앙 박물관", "국립중앙박물관"),
    ("technical", "만성 골수성 백혈병", "만성골수성백혈병"),
    ("technical", "중거리 탄도 유도탄", "중거리탄도유도탄"),
    ("technical", "교양 교육", "교양교육"),
    ("technical", "교육 기관", "교육기관"),
    ("technical", "국제 학회", "국제학회"),
)
_COUNTERS = frozenset("개 명 분 마리 대 자루 벌 켤레 권 장 통 병 잔 그루 채 척 살 세 배 회 번 원 달러 엔 위안 유로 미터 센티미터 밀리미터 킬로미터 그램 킬로그램 톤 리터 밀리리터 평 제곱미터 퍼센트 바이트 킬로바이트 메가바이트 기가바이트 테라바이트 비트 볼트 와트 암페어 헤르츠 파스칼 줄 칼로리 도 시간 일 주 개월 달 년".split())
_ORDINALS = frozenset("학년 층 과 장 절 항 조 호 동 번 실 대대".split())
_ADNOMINAL = frozenset("만 듯 법 척 체 성 뻔".split())
_NATIVE_NUMBERS = frozenset("한 두 세 네 다섯 여섯 일곱 여덟 아홉 열 스물 서너 두어".split())


# 활용형이 3음절 이상인 본용언에서 파생어로 보는 어간 끝(접미사).
_DERIVATIONAL_ENDINGS = ("답", "스럽", "롭", "하", "거리", "대", "뜨리", "트리")


def _compound_joins(text, tokens, tokenize, lookup_morpheme):
    """Return only spans confirmed as one common noun in the model lexicon.

    Adjacency is not compound evidence: e.g. 학교 도서관 이용 시간 is a noun
    phrase, and 친구엄마 can be a film title (NNP), not a common-noun compound.
    An analyzer may also emit an entire unknown string as NNG. Resolve its
    morpheme ID and require an exact dictionary form, not just the POS tag.
    Registered personal/technical/proper terms are handled by apply_terms.

    Windows are bounded, longest first and nonoverlapping: confirming A+B and
    B+C independently must never create an unconfirmed A+B+C compound. No user
    text or lookup result survives this call.
    """
    if lookup_morpheme is None:
        return []
    joins, i = [], 0
    checked = {}

    def is_lexical_noun(compact):
        if compact not in checked:
            parts = tokenize(compact)
            entry = (lookup_morpheme(parts[0].id)
                     if len(parts) == 1 and parts[0].tag == "NNG" and parts[0].form == compact
                     else None)
            checked[compact] = entry is not None and entry.tag == "NNG" and entry.form == compact
        return checked[compact]

    while i < len(tokens):
        if tokens[i].tag != "NNG":
            i += 1
            continue
        candidates = []
        for j in range(i, min(i + 4, len(tokens))):
            if tokens[j].tag != "NNG":
                break
            if j > i and text[tokens[j - 1].end:tokens[j].start] not in ("", " "):
                break
            start, end = tokens[i].start, tokens[j].end
            source = text[start:end]
            if not re.fullmatch(r"\S+(?: \S+)*", source):
                break
            compact = source.replace(" ", "")
            if len(compact) > 16:
                break
            if " " in source and compact == "".join(t.form for t in tokens[i:j + 1]):
                candidates.append((j, start, end, compact))
        for j, start, end, compact in reversed(candidates):
            if not is_lexical_noun(compact):
                continue
            joins.extend((start + match.start(), start + match.end())
                         for match in re.finditer(" ", text[start:end]))
            i = j + 1
            break
        else:
            i += 1
    return joins


def apply_policy(text, preferences, tokenize, *, lookup_morpheme=None):
    """Apply to one prose segment (no layout whitespace or protected tokens)."""
    tokens = tokenize(text)
    edits = {}
    numeric_place_indices = set()
    run = []
    for i in range(len(tokens) + 1):
        if i < len(tokens) and tokens[i].tag in ("NR", "SN"):
            run.append(i)
        else:
            if any(re.search("[십백천만억조경]", tokens[j].form) for j in run):
                numeric_place_indices.update(run)
            run = []

    def boundary(left, right, mode):
        if mode == "model" or left > right or text[left:right] not in ("", " "):
            return
        edits[left, right] = "" if mode == "join" else " "

    if preferences.compound == "join":
        for start, end in _compound_joins(text, tokens, tokenize, lookup_morpheme):
            boundary(start, end, "join")

    def joinable_main(i, previous):
        start = text.rfind(" ", 0, previous.start) + 1
        main = [t for t in tokens[:i] if t.start >= start and t.tag.startswith(("V", "XS"))]
        if not main or any(t.tag == "VX" for t in main):
            return False
        if previous.end - start <= 2:
            return True
        # Inspect the main verb only. Splitting every lexical token would turn
        # dictionary words such as 도와드리다 into falsely optional boundaries.
        parts = tokenize(text[start:previous.end], split_complex=True)
        verbs = [t for t in parts if t.tag.startswith(("V", "XS"))]
        if len(verbs) != 1 or verbs[0].tag.startswith("XS"):
            return False
        # Kiwi가 한 형태소로 묶는 파생어(아름답다, 사랑스럽다, 깨뜨리다 …)도
        # 활용형이 3음절 이상이면 붙이지 않는다(제47항 해설, 국립국어원 답변).
        return not verbs[0].form.endswith(_DERIVATIONAL_ENDINGS)

    for i, current in enumerate(tokens[1:], 1):
        previous = tokens[i - 1]
        mode = "model"
        if previous.tag in ("NNG", "NNP") and current.tag in ("NNG", "NNP"):
            # Only the separate preference applies to arbitrary noun runs.
            # Joining requires lexical evidence above or an explicit term.
            if preferences.compound == "separate":
                mode = "separate"
        # Kiwi는 '-어 보이다'의 '보이다'를 본동사(VV)로 분석하지만, 제47항 해설은
        # '빛나 보인다/빛나보인다', '착해 보인다/착해보인다'를 보조 용언 구성으로 든다.
        seeming = (current.tag == "VV" and current.form == "보이"
                   and previous.tag == "EC" and previous.form in ("어", "아"))
        if (current.tag == "VX" or seeming) and current.form not in ("하", "지"):
            if previous.tag == "EC" and previous.form in ("어", "아"):
                mode = preferences.auxiliaries
                if mode == "join" and not joinable_main(i, previous):
                    mode = "separate"
            elif previous.tag == "EC" or previous.tag.startswith("J"):
                # -고 있다/-고 싶다/-지 않다 and an intervening particle
                # are not optional joins. Never conflate these with -아/-어.
                mode = "separate"
        if (current.tag == "VX" and current.form == "하" and current.end > current.start
                and (previous.tag == "EC" and previous.form not in ("어", "아")
                     or previous.tag.startswith("J"))):
            # -어야 하다 / -게 하다 / -기는 하다 require a word boundary.
            # In contracted forms (e.g. -려다가), a zero-width analyzed 하
            # has no surface word to separate.
            mode = "separate"
        if (current.tag == "VX" and current.form == "하" and current.end > current.start
                and previous.tag == "EC"):
            # Phrasal -어 하다 (먹고 싶어 하다) differs from lexical 예뻐하다.
            # A zero-width restored 하 supplies no surface word to separate.
            if any(t.tag == "VX" for t in tokens[max(0, i - 3):i - 1]):
                mode = "separate"
        if current.form in _ADNOMINAL and current.tag == "NNB" and i + 1 < len(tokens):
            following = tokens[i + 1]
            if following.form in ("하", "싶") and following.tag.startswith(("XS", "V")):
                if text[current.end:following.start] in ("", " "):
                    boundary(current.end, following.start, "join")
                if previous.tag == "ETM":
                    mode = preferences.auxiliaries
                    if mode == "join" and not joinable_main(i, previous):
                        mode = "separate"
        numeric = previous.tag in ("SN", "NR") or previous.tag == "MM" and previous.form in _NATIVE_NUMBERS
        if numeric and current.tag.startswith("N"):
            if current.form in "년 월 일".split() and previous.tag == "SN":
                mode = preferences.date_units
            elif current.form in ("시", "분", "초"):
                if not (current.form == "분" and previous.tag == "MM"):
                    mode = preferences.time_units
            elif current.form in _ORDINALS:
                mode = preferences.ordinals
            elif current.form in _COUNTERS and previous.tag == "SN":
                mode = preferences.number_units
        if (preferences.large_numbers == "standard" and i in numeric_place_indices
                and previous.tag in ("NR", "SN") and current.tag in ("NR", "SN")
                and not previous.tag == current.tag == "SN"):
            # Only Sino-Korean numeral runs, not e.g. 하나 둘 (enumeration).
            if re.fullmatch(r"[0-9영공일이삼사오육칠팔구십백천만억조경]+", previous.form + current.form):
                mode = "separate" if previous.form[-1:] in "만억조경" else "join"
        boundary(previous.end, current.start, mode)

    if preferences.short_words != "model":
        words = list(re.finditer(r"\S+", text))
        # Greedy *pairs*, never chains of 3+ glued syllables. Require a run of
        # three one-syllable words, no particle-bearing right word.
        used = set()
        for i in range(len(words) - 1):
            left, right = words[i:i + 2]
            if len(left[0]) != 1 or len(right[0]) != 1 or i in used:
                continue
            neighbors = (i > 0 and len(words[i - 1][0]) == 1) or (i + 2 < len(words) and len(words[i + 2][0]) == 1)
            lt = [t for t in tokens if t.start == left.start() and t.end == left.end()]
            rt = [t for t in tokens if t.start == right.start() and t.end == right.end()]
            allowed = (left[0] == "좀" and right[0] == "더") or (
                any(t.tag in ("MM", "NP") for t in lt) and any(t.tag.startswith("NN") for t in rt))
            if neighbors and allowed and not any(t.tag.startswith("J") for t in rt):
                boundary(left.end(), right.start(), preferences.short_words)
                used.add(i + 1)

    for (start, end), replacement in sorted(edits.items(), reverse=True):
        text = text[:start] + replacement + text[end:]
    return apply_terms(text, preferences)


def apply_terms(text, preferences):
    terms = {spaced.replace(" ", ""): dict(category=category, spaced=spaced, joined=joined, mode="inherit")
             for category, spaced, joined in BUILTIN_TERMS}
    terms.update({term["spaced"].replace(" ", ""): term for term in preferences.terms})
    active = []
    for compact, term in terms.items():
        mode = term["mode"]
        if mode == "inherit":
            mode = getattr(preferences, term["category"], "model")
        if mode != "model":
            active.append((compact, term["joined" if mode == "join" else "spaced"]))
    if not active:
        return text
    # Match whole registered phrases, allowing ordinary Korean particles after
    # them, never substrings such as 교육기관차 or crossing double spaces/tabs.
    from .converter_helpers import is_particle
    patterns = [(re.compile(" ?".join(map(re.escape, compact))), replacement)
                for compact, replacement in sorted(active, key=lambda item: -len(item[0]))]
    matches = []
    for pattern, replacement in patterns:
        for match in pattern.finditer(text):
            if match.start() and text[match.start() - 1].isalnum():
                continue
            suffix = re.match(r"[가-힣]+", text[match.end():])
            if suffix and not is_particle(suffix[0]):
                continue
            if any(start < match.end() and match.start() < end for start, end, _ in matches):
                continue
            matches.append((match.start(), match.end(), replacement))
    for start, end, replacement in sorted(matches, reverse=True):
        text = text[:start] + replacement + text[end:]
    return text
