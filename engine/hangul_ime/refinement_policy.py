"""Preserve literal jamo attachment and confirmed lexical morpheme interiors.

Only newly inserted boundaries inside exact dictionary NNG/NNP entries are
blocked. An analyzer's unknown-word NNG label alone is never dictionary proof.
Input and lookups are local to this call and are never cached or logged.
"""
from bisect import bisect_left, bisect_right
from .title_guard import title_deletion_boundaries


def _is_jamo(char):
    value = ord(char)
    return (0x1100 <= value <= 0x11FF or 0x3130 <= value <= 0x318F
            or 0xA960 <= value <= 0xA97F or 0xD7B0 <= value <= 0xD7FF
            or 0xFFA0 <= value <= 0xFFDC)


def _boundaries(text):
    cuts, offsets, position = set(), [0], 0
    for char in text:
        if char == " ":
            cuts.add(position)
        else:
            position += 1
        offsets.append(position)
    return cuts, offsets


def _structural_relation(left, right):
    return (((left.tag.startswith("N") and (right.tag.startswith(("V", "M")) or right.tag == "NNB"))
            or (left.tag in ("MAG", "MM") and right.tag.startswith(("N", "V", "M"))))
            or left.tag == "ETM" and right.tag == "NNB"
            or left.tag.startswith("J") and right.tag.startswith("V"))


def _single_lexical_alternative(baseline, left, right, tokenize, lookup_morpheme):
    """A whole adjacent surface must independently resolve to one known entry."""
    joined = baseline[left.start:left.end] + baseline[right.start:right.end]
    if not joined or len(joined) > 128:
        return False
    alternatives = list(tokenize(joined))
    if len(alternatives) != 1:
        return False
    token = alternatives[0]
    if token.start != 0 or token.end != len(joined):
        return False
    if token.tag not in ("NNG", "NNP", "NP", "MAG", "VV", "VA", "EC", "EF"):
        return False
    if token.tag not in ("VV", "VA", "EC", "EF") and token.form != joined:
        return False
    entry = lookup_morpheme(token.id)
    return entry is not None and entry.form == token.form and entry.tag == token.tag


def protect_refined_boundaries(baseline, proposed, tokenize, lookup_morpheme):
    if baseline == proposed:
        return proposed
    raw = baseline.replace(" ", "")
    if proposed.replace(" ", "") != raw:
        raise ValueError("boundary policy requires identical non-space characters")
    original, offsets = _boundaries(baseline)
    selected, _ = _boundaries(proposed)
    for offset in range(1, len(raw)):
        if _is_jamo(raw[offset - 1]) or _is_jamo(raw[offset]):
            if offset in original:
                selected.add(offset)
            else:
                selected.discard(offset)

    insertions = sorted(selected - original)
    deletions = original - selected
    tokens = list(tokenize(baseline)) if insertions or deletions else []
    if deletions:
        # Re-analyze the complete model proposal so its word context can
        # confirm or reject the baseline's hypothesized word boundary.
        _, proposed_offsets = _boundaries(proposed)
        proposed_tokens = list(tokenize(proposed))
        selected.update(title_deletion_boundaries(baseline, proposed, tokens, proposed_tokens))
        supported_deletions = set()
        for left, right in zip(proposed_tokens, proposed_tokens[1:]):
            if not 0 <= left.start < left.end <= right.start < right.end <= len(proposed):
                continue
            if proposed_offsets[left.end] != proposed_offsets[right.start]:
                continue
            if _structural_relation(left, right):
                supported_deletions.add(proposed_offsets[right.start])
        for left, right in zip(tokens, tokens[1:]):
            if not (0 <= left.start < left.end < right.start < right.end <= len(baseline)):
                continue
            if baseline[left.end:right.start] != " ":
                continue
            boundary = offsets[right.start]
            if boundary not in deletions or boundary not in supported_deletions:
                continue
            if _structural_relation(left, right):
                if _single_lexical_alternative(baseline, left, right, tokenize, lookup_morpheme):
                    continue
                selected.add(boundary)
    if insertions:
        for token in tokens:
            if token.tag not in ("NNG", "NNP") or not 0 <= token.start < token.end <= len(baseline):
                continue
            surface = baseline[token.start:token.end]
            if not surface or any(char.isspace() for char in surface) or surface != token.form:
                continue
            start, end = offsets[token.start], offsets[token.end]
            first, last = bisect_right(insertions, start), bisect_left(insertions, end)
            if first == last:
                continue
            entry = lookup_morpheme(token.id)
            if entry is None or entry.form != token.form or entry.tag != token.tag:
                continue
            selected.difference_update(insertions[first:last])
    return "".join((" " if offset in selected else "") + char for offset, char in enumerate(raw))
