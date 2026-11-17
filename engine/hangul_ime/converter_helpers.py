"""Conservative token boundaries shared by the release converters."""
from __future__ import annotations

from decimal import Decimal, localcontext
import re


# A case particle can be followed by an auxiliary particle and a topic marker.
# Restrict suffixes instead of accepting arbitrary text after a number/unit or
# repeatedly cutting endings off a dictionary word (국가, 자동차, 사과, ...).
_CASE = r"(?:으로부터|에서부터|에게서|한테서|이라고|이라서|으로|라고|이라|에게|한테|에서|처럼|만큼|밖에|커녕|보다|은|는|이|가|을|를|의|와|과|로|에)"
_PARTICLE_RE = re.compile(
    rf"(?:{_CASE}(?:부터|까지)?(?:만|조차|마저)?(?:은|는|도)?"
    r"|(?:부터|까지)(?:만)?(?:은|는|도)?|(?:만|조차|마저)(?:은|는|도)?|도)"
)


def is_particle(value: str) -> bool:
    return not value or _PARTICLE_RE.fullmatch(value) is not None


def stem_candidates(value: str):
    """Yield the full token, then longest possible stems with valid particles."""
    yield value, ""
    for split in range(len(value) - 1, 0, -1):
        suffix = value[split:]
        if is_particle(suffix):
            yield value[:split], suffix


# Endings that turn a Sino-Korean noun into a verb, adjective or adverb
# (안녕하다, 발전된, 자연스럽다, 조용히, 과학적인). The Hangul tail is kept
# as typed and only the noun stem is converted.
_DERIVATION_RE = re.compile(
    r"(?:하|해|했|한|할|함|합|하시|하셨|되|돼|됐|된|될|됨|됩|시키|시켜|시켰|시킨|시킬|당하|당해|당했|당한"
    r"|스럽|스러|스런|스러운|적|히)[가-힣]*"
)


def is_derivation(tail: str) -> bool:
    return bool(tail) and _DERIVATION_RE.fullmatch(tail) is not None


def hanja_stem_candidates(value: str):
    """Yield (stem, tail) splits for Hanja lookup, longest stem first.

    The full token comes first, then stems followed by a particle, then
    stems followed by a derivational ending such as 하다/되다/스럽다/히.
    """
    yield value, ""
    for split in range(len(value) - 1, 0, -1):
        suffix = value[split:]
        if is_particle(suffix) or _DERIVATION_RE.fullmatch(suffix):
            yield value[:split], suffix


def token_edges(value: str):
    """Preserve syntax characters: signs, decimal dots, degrees and emoji marks.

    Only known surrounding prose punctuation is detached. In particular an
    invalid date such as -2026-01-01 must not silently become a positive date.
    """
    left = 0
    right = len(value)
    pairs = {close: opening for opening, close in zip("([{<「『【", ")]} >」』】".replace(" ", ""))}

    def closes_internal_group(end):
        closing = value[end - 1]
        opening = pairs.get(closing)
        content = value[left:end]
        return opening is not None and content.count(closing) <= content.count(opening)

    while left < right and (value[left].isspace() or value[left] in '([{<「『【“‘"\''):
        left += 1
    while right > left and (value[right - 1].isspace() or value[right - 1] in ')]}>」』】”’"\'!?。！？.,，;；'):
        if closes_internal_group(right):
            break
        right -= 1
    wrapped_particle = re.search(r"[)\]}>」』】”’\"']+[가-힣]+$", value[left:right])
    if wrapped_particle:
        wrapped = wrapped_particle.group()
        suffix = wrapped.lstrip(')]}>」』】”’"\'')
        if is_particle(suffix):
            end = right - len(suffix)
            while end > left + wrapped_particle.start() and not closes_internal_group(end):
                end -= 1
            if end < right - len(suffix):
                right = end
    return value[:left], value[left:right], value[right:]


def format_quantity(value: Decimal) -> str:
    """Keep nine fractional places without erasing tiny nonzero quantities."""
    if not value.is_finite():
        raise ValueError("quantity must be finite")
    if not value:
        return "0"
    with localcontext() as context:
        context.prec = max(40, len(value.as_tuple().digits) + abs(value.adjusted()) + 12)
        if abs(value) < Decimal("1e-9") or abs(value) >= Decimal("1e30"):
            return format(value.normalize(), ".9g")
        result = format(value, ".9f").rstrip("0").rstrip(".")
        return "0" if result == "-0" else result
