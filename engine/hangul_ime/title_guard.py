"""Conservative deletion protection for a proper name followed by a title.

The caller supplies both token sequences; this module never invokes an analyzer.
Returned offsets count Python characters after removing ASCII spaces, matching
refinement_policy's boundary representation. It returns existing deleted cuts
only and does not insert boundaries into an originally unspaced expression.

NNP is not a person-name label. In particular, Kiwi's 의원/NNG token does not
distinguish 議員 (legislator) from 醫院 (clinic). See README.md for this limit.
"""

from unicodedata import category


# A lexical category, independent of any evaluation sentence or surname.
# Seven appear in NIKL's Article 48 explanation; 의원 is a public-office title.
TITLE_NOUNS = frozenset({"의원", "선생", "교수", "박사", "장군", "사장", "여사", "정승"})


def _offsets_and_cuts(text):
    offsets, cuts, position = [0], set(), 0
    for char in text:
        if char == " ":
            cuts.add(position)
        else:
            position += 1
        offsets.append(position)
    return offsets, cuts


def _exact_token(text, token):
    return (0 <= token.start < token.end <= len(text)
            and text[token.start:token.end] == token.form
            and not any(char.isspace() for char in token.form))


def _title_ends_word(text, tokens, index):
    """The title may take 님/XSN and particles, but no noun/derivation tail."""
    cursor = tokens[index].end
    index += 1
    honorific_seen = particle_seen = False
    while cursor < len(text):
        # Punctuation terminates a lexical word just as whitespace does. Its
        # tokenization is irrelevant; URL/identifier protection belongs upstream.
        if text[cursor].isspace() or category(text[cursor]).startswith("P"):
            return True
        if index >= len(tokens):
            return False
        token = tokens[index]
        if token.start != cursor or not _exact_token(text, token):
            return False
        if token.tag == "XSN" and token.form == "님":
            if honorific_seen or particle_seen:
                return False
            honorific_seen = True
        elif token.tag.startswith("J"):
            particle_seen = True
        else:
            return False
        cursor = token.end
        index += 1
    return True


def _title_pairs(text, tokens, offsets, gap):
    """Return the complete raw-span signatures corroborated by one analysis."""
    pairs = set()
    for index in range(1, len(tokens)):
        left, title = tokens[index - 1], tokens[index]
        if left.tag != "NNP" or title.tag != "NNG" or title.form not in TITLE_NOUNS:
            continue
        if not _exact_token(text, left) or not _exact_token(text, title):
            continue
        if left.end > title.start or text[left.end:title.start] != gap:
            continue
        if not _title_ends_word(text, tokens, index):
            continue
        pairs.add((offsets[title.start], offsets[left.start], offsets[left.end],
                   left.form, offsets[title.end], title.form))
    return pairs


def title_deletion_boundaries(baseline, proposed, baseline_tokens, proposed_tokens):
    """Return existing title boundaries a spacing-only proposal should retain.

    Protect a single-space NNP + NNG-title boundary only when the proposed
    sentence independently analyzes the same exact source spans as those two
    tokens. A proposed single lexical token, changed POS, or altered name span
    does not corroborate the baseline. Supplied tokens need form/tag/start/end.
    """
    if baseline.replace(" ", "") != proposed.replace(" ", ""):
        raise ValueError("title guard requires identical non-space characters")
    baseline_offsets, original = _offsets_and_cuts(baseline)
    proposed_offsets, selected = _offsets_and_cuts(proposed)
    deleted = original - selected
    if not deleted:
        return set()
    baseline_pairs = _title_pairs(baseline, list(baseline_tokens), baseline_offsets, " ")
    if not baseline_pairs:
        return set()
    proposed_pairs = _title_pairs(proposed, list(proposed_tokens), proposed_offsets, "")
    return {pair[0] for pair in baseline_pairs & proposed_pairs if pair[0] in deleted}
