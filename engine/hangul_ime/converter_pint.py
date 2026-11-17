"""Optional SI/compound-unit conversion with a small, bounded input grammar.

Only unit names, products, quotients, parentheses and explicit integer powers
are accepted. User text is never passed to eval or Pint's quantity-expression
parser. Pint resolves individual validated names and performs unit arithmetic.
"""
from __future__ import annotations

from decimal import Decimal, localcontext
from functools import lru_cache
import re

from .converter_helpers import format_quantity


_TOKEN = re.compile(r"[A-Za-zµμΩ°]+(?:_[A-Za-z]+)*|\*\*|[*/^()]|[+-]?[0-9]+")
_NAME = re.compile(r"[A-Za-zµμΩ°]+(?:_[A-Za-z]+)*")


def _unit_terms(expression):
    """Parse to unit-name powers before importing or invoking optional Pint."""
    if not expression or len(expression) > 128:
        return None
    tokens = []
    position = 0
    while position < len(expression):
        if expression[position] == " ":
            position += 1
            continue
        match = _TOKEN.match(expression, position)
        if match is None or len(tokens) >= 32:
            return None
        tokens.append(match.group())
        position = match.end()
    index = 0
    atoms = 0

    def factor(depth):
        nonlocal index, atoms
        if index >= len(tokens) or depth > 3:
            raise ValueError("incomplete or deeply nested unit expression")
        token = tokens[index]
        index += 1
        if token == "(":
            terms = product(depth + 1)
            if index >= len(tokens) or tokens[index] != ")":
                raise ValueError("unclosed unit group")
            index += 1
        elif _NAME.fullmatch(token) and len(token) <= 32:
            atoms += 1
            if atoms > 8:
                raise ValueError("too many units")
            terms = [(token, 1)]
        else:
            raise ValueError("expected a unit name")
        if index < len(tokens) and tokens[index] in ("^", "**"):
            index += 1
            if index >= len(tokens) or not re.fullmatch(r"[+-]?[0-9]{1,2}", tokens[index]):
                raise ValueError("expected a bounded integer exponent")
            exponent = int(tokens[index])
            index += 1
            if not 1 <= abs(exponent) <= 12:
                raise ValueError("unit exponent out of range")
            terms = [(name, power * exponent) for name, power in terms]
        if sum(abs(power) for _, power in terms) > 48:
            raise ValueError("unit powers exceed limit")
        return terms

    def product(depth):
        nonlocal index
        terms = factor(depth)
        while index < len(tokens) and tokens[index] in ("*", "/"):
            operator = tokens[index]
            index += 1
            terms.extend((name, power * (-1 if operator == "/" else 1)) for name, power in factor(depth))
            if sum(abs(power) for _, power in terms) > 48:
                raise ValueError("unit powers exceed limit")
        return terms

    try:
        terms = product(0)
    except ValueError:
        return None
    return terms if index == len(tokens) else None


@lru_cache(maxsize=1)
def _pint_registry():
    try:
        import pint
    except ImportError:
        return None
    return pint.UnitRegistry(non_int_type=Decimal, autoconvert_offset_to_baseunit=False)


def pint_candidates(value: Decimal, expression: str):
    """Return normalized and SI-base candidates, or nothing for invalid input.

    Limits: 128 expression characters, 32 tokens, eight names, three nested
    groups, powers +/-1..12 and total absolute powers <=48. Multiplication must
    be explicit. Bare suffix digits (cm2), arbitrary suffixes and arithmetic on
    magnitudes are rejected even if a general Pint expression would accept them.
    """
    terms = _unit_terms(expression)
    if terms is None or not value.is_finite() or abs(value.adjusted()) > 100:
        return ()
    registry = _pint_registry()
    if registry is None:
        return ()
    from pint.errors import PintError

    try:
        with localcontext() as context:
            context.prec = 40
            unit = registry.Unit("")
            names = []
            for token, exponent in terms:
                # Only one bounded identifier reaches Pint, never an expression.
                name = registry.get_name(token)
                leaf = registry.Unit(name)
                names.append(name)
                zero_base = registry.Quantity(Decimal(0), leaf).to_base_units()
                if zero_base.magnitude and (len(terms) != 1 or exponent != 1):
                    return ()  # Offset temperatures cannot be multiplied/divided.
                unit = unit * leaf ** exponent
            quantity = registry.Quantity(value, unit)
            base = quantity.to_base_units()
            magnitude = Decimal(str(base.magnitude))
            if not magnitude.is_finite() or abs(magnitude.adjusted()) > 100:
                return ()
            temperature = quantity.check("[temperature]")
            difference = temperature and len(names) == 1 and names[0].startswith("delta_")
            if temperature and not difference:
                minimum = {
                    "degree_Celsius": Decimal("-273.15"),
                    "degree_Fahrenheit": Decimal("-459.67"),
                    "kelvin": Decimal(0), "degree_Rankine": Decimal(0),
                }.get(names[0]) if len(names) == 1 and terms[0][1] == 1 else None
                if minimum is not None:
                    if value < minimum:
                        return ()
                    if value == minimum:
                        # Decimal evaluation of Fahrenheit's repeating 5/9
                        # factor may leave a tiny negative residual at exactly
                        # zero kelvin. Compare its exact source-scale limit.
                        magnitude = Decimal(0)
                elif base.to("kelvin").magnitude < 0:
                    return ()
            source_symbol = format(quantity.units, "~P") or "dimensionless"
            base_symbol = format(base.units, "~P") or "dimensionless"
            if difference:
                base_symbol = "Δ" + base_symbol
            variants = (
                f"{format_quantity(value)} {source_symbol}",
                f"{format_quantity(magnitude)} {base_symbol}",
            )
            return tuple(dict.fromkeys(variants))
    except (PintError, ValueError, ArithmeticError, TypeError):
        # Undefined units, incompatible offsets or unsupported numeric converters
        # must not break the editor or produce a partially validated candidate.
        return ()
