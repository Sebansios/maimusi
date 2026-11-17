"""사용자 단어와 손으로 고친 경계를 띄어쓰기 결과에 적용하고, 고친 경계에서 단어를 뽑는다.

- 사용자 단어: 단어 안에는 띄어쓰기를 넣지 않는다.
- 기억한 경계: 사용자가 변환 중에 경계를 직접 고쳐 확정한 어절. 같은 표현이 나오면
  그때의 띄어쓰기를 따른다.
둘 다 어절 첫머리에서 시작하고 뒤에 조사만 붙는 경우에만 적용한다(사용자 용어와 같은 규칙).
여기서는 아무것도 저장하지 않는다. 저장 여부는 호스트(설정)가 정한다.
"""
import re

from .spacing_preferences import MAX_WORD, _WORD

# 단어로 뽑을 수 있는 형태소: 명사류, 외국어·한자·숫자, 어근과 명사 파생 접사.
_NOUNISH = {"NNG", "NNP", "NR", "NP", "SL", "SH", "SN", "XR", "XPN", "XSN"}
MAX_LEARN_TEXT = 400
# 기억하지 않는 글: 주소·메일·경로처럼 보이는 것. 기억하는 말에는 한글이 있어야 한다.
_UNSAFE = re.compile(r"@|://|www\.|[/\\]")
_HANGUL = re.compile(r"[가-힣]")


def _pattern(compact):
    return re.compile(" ?".join(map(re.escape, compact)))


def apply_user(text, preferences):
    cases = [(w, w) for w in preferences.words] + [(c["compact"], c["spaced"]) for c in preferences.learned]
    if not cases:
        return text
    from .converter_helpers import is_particle
    matches = []
    # 긴 것부터: 기억한 경계 「찰떡엔진은」이 단어 「찰떡」보다 먼저 자리를 잡는다.
    for compact, replacement in sorted(cases, key=lambda item: -len(item[0])):
        for match in _pattern(compact).finditer(text):
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


def _boundaries(text):
    """공백이 앞에 오는 글자의 위치(공백을 뺀 글 기준)."""
    found, position = set(), 0
    for char in text:
        if char == " ":
            found.add(position)
        else:
            position += 1
    return found


def _eojeols(text):
    spans, position = [], 0
    for word in text.split(" "):
        if word:
            spans.append((position, position + len(word), word))
            position += len(word)
    return spans


def _trim(word):
    """어절 앞뒤의 문장부호를 떼어 낸다. (떼어 낸 앞쪽 글자 수, 남은 낱말)"""
    match = re.search(r"[가-힣A-Za-z0-9](?:.*[가-힣A-Za-z0-9])?", word)
    return (match.start(), match.group()) if match else (0, "")


def learn(proposed, accepted, tokenize):
    """엔진이 제안한 글과 사용자가 고쳐 확정한 글에서 기억할 경계와 단어를 뽑는다."""
    empty = {"cases": [], "words": []}
    if (type(proposed) is not str or type(accepted) is not str
            or proposed.replace(" ", "") != accepted.replace(" ", "")
            or len(accepted) > MAX_LEARN_TEXT or _UNSAFE.search(accepted)):
        return empty
    proposed_b, accepted_b = _boundaries(proposed), _boundaries(accepted)
    changed = proposed_b ^ accepted_b
    if not changed:
        return empty
    eojeols = _eojeols(accepted)
    # 바뀐 경계에 닿은 어절만 남긴다(문장 전체는 기억하지 않는다).
    touched = [i for i, (start, end, _) in enumerate(eojeols) if any(start <= b <= end for b in changed)]
    groups, current = [], []
    for i in touched:
        if current and i != current[-1] + 1:
            groups.append(current)
            current = []
        current.append(i)
    if current:
        groups.append(current)
    cases = []
    for group in groups:
        lead, _ = _trim(eojeols[group[0]][2])
        spaced = " ".join(eojeols[i][2] for i in group)
        _, spaced = _trim(spaced)
        compact = spaced.replace(" ", "")
        if (2 <= len(compact) <= MAX_WORD and _WORD.fullmatch(compact) and "  " not in spaced
                and _HANGUL.search(compact)):
            cases.append({"compact": compact, "spaced": spaced})
    words = []
    # 붙인 경계(제안에는 있고 확정에는 없는 공백)에서는 조사·어미를 뗀 단어를 뽑는다.
    for b in sorted(proposed_b - accepted_b):
        for start, end, word in eojeols:
            if not start < b < end:
                continue
            lead, core = _trim(word)
            head_end = 0
            for token in tokenize(core):
                if token.tag not in _NOUNISH:
                    break
                head_end = token.start + token.len
            head = core[:head_end]
            if (lead + head_end > b - start and 2 <= len(head) <= MAX_WORD
                    and _WORD.fullmatch(head) and _HANGUL.search(head) and head not in words):
                words.append(head)
    return {"cases": cases, "words": words}
