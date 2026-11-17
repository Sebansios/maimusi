"""Validated custom rules and bounded, explicit-commit candidate learning."""
from __future__ import annotations

from dataclasses import asdict, dataclass, fields, replace
from pathlib import Path
import re
import time
from typing import Mapping, Optional, Sequence

import regex

from .persistence import atomic_json_save, checked_mapping, checked_text, checked_version, load_json
from .conversion_types import ConversionCandidate, WordConverter, KOREAN_PARTICLES, _edges

CUSTOM_FORMAT_VERSION = 1
LEARNING_FORMAT_VERSION = 1
MAX_ENTRIES = 10000
MAX_TARGETS = 64
MAX_RULES = 256
MAX_PATTERN = 512
MAX_TEXT = 4096
REGEX_TIMEOUT = 0.02
REGEX_BATCH_TIMEOUT = 0.05
MAX_LEARNING_SOURCES = 5000
MAX_LEARNING_RECORDS = 20000
MAX_COUNT = 2**31 - 1
_ALLOWED_FLAGS = int(re.I | re.M | re.S | re.X | re.A | re.U)


def validate_entries(entries):
    if not isinstance(entries, dict):
        raise TypeError("사용자 사전에는 객체가 필요합니다")
    if len(entries) > MAX_ENTRIES:
        raise ValueError("사용자 사전 항목 수가 상한을 초과합니다")
    validated = {}
    for source, targets in entries.items():
        checked_text(source, "원문", maximum=MAX_TEXT)
        if isinstance(targets, str):
            targets = (targets,)
        if not isinstance(targets, (list, tuple)) or not 1 <= len(targets) <= MAX_TARGETS:
            raise ValueError(f"변환 후보는 1~{MAX_TARGETS}개의 문자열 목록이어야 합니다")
        for target in targets:
            checked_text(target, "후보", maximum=MAX_TEXT)
        if len(set(targets)) != len(targets):
            raise ValueError("중복된 변환 후보가 있습니다")
        validated[source] = tuple(targets)
    return validated


def _disabled(values, label):
    if not isinstance(values, (set, list, tuple, frozenset)):
        raise TypeError(f"{label}: 목록이 필요합니다")
    if len(values) > MAX_ENTRIES:
        raise ValueError(f"{label}: 항목 수가 상한을 초과합니다")
    for value in values:
        checked_text(value, label, maximum=MAX_TEXT)
    if len(set(values)) != len(values):
        raise ValueError(f"{label}: 중복된 항목이 있습니다")
    return set(values)


def _compile_rule(rule):
    checked_text(rule.pattern, "정규식", maximum=MAX_PATTERN)
    checked_text(rule.replacement, "치환문", maximum=MAX_TEXT, empty=True)
    checked_text(rule.name, "규칙 이름", maximum=128)
    if type(rule.priority) is not int or not -10000 <= rule.priority <= 10000:
        raise ValueError("우선순위는 -10000~10000의 정수여야 합니다")
    if type(rule.flags) is not int or rule.flags < 0 or rule.flags & ~_ALLOWED_FLAGS:
        raise ValueError("지원하지 않는 정규식 플래그입니다")
    if type(rule.enabled) is not bool:
        raise TypeError("규칙 활성화 여부는 참/거짓이어야 합니다")
    # Very large counted repeats may allocate excessive memory at compile time,
    # before an execution timeout could protect the UI.
    for repeat in re.finditer(r"\{(\d+)(?:,(\d*))?\}", rule.pattern):
        if any(int(value) > 10000 for value in repeat.groups() if value):
            raise ValueError("정규식 반복 횟수는 10000 이하여야 합니다")
    flags = regex.VERSION0
    for source, destination in (
        (re.I, regex.I), (re.M, regex.M), (re.S, regex.S),
        (re.X, regex.X), (re.A, regex.A), (re.U, regex.U),
    ):
        if rule.flags & source:
            flags |= destination
    try:
        compiled = regex.compile(rule.pattern, flags)
        if compiled.groups > 64:
            raise ValueError("정규식 캡처 그룹은 64개 이하여야 합니다")
        # Validate replacement escapes and group references even if the real
        # pattern cannot match an empty string. This mirror contains no input.
        names = {number: name for name, number in compiled.groupindex.items()}
        probe = "".join(
            f"(?P<{names[number]}>)" if number in names else "()"
            for number in range(1, compiled.groups + 1)
        )
        regex.compile(probe).fullmatch("").expand(rule.replacement)
    except (regex.error, IndexError, KeyError, OverflowError) as error:
        raise ValueError("올바르지 않은 정규식 또는 치환문입니다") from error
    return compiled


@dataclass
class ConversionRule:
    pattern: str
    replacement: str
    name: str = "사용자 변환"
    priority: int = 0
    flags: int = 0
    enabled: bool = True

    def __post_init__(self):
        _compile_rule(self)

    def validate(self):
        _compile_rule(self)
        return self


def _particle_suffix(suffix):
    if not suffix:
        return True
    # The bounded dynamic program accepts compound particles, but only after
    # finding a dictionary-known stem; it never strips arbitrary word endings.
    possible = {0}
    for index in range(len(suffix)):
        if index in possible:
            for particle in KOREAN_PARTICLES:
                if suffix.startswith(particle, index):
                    possible.add(index + len(particle))
    return len(suffix) in possible


class CustomConversionConverter(WordConverter):
    """Snapshot of exact rules plus timeout-protected regex rules."""

    name = "사용자 변환"

    def __init__(self, entries=None, rules: Sequence[ConversionRule] = ()):
        self.entries = validate_entries({} if entries is None else entries)
        if not isinstance(rules, (list, tuple)) or len(rules) > MAX_RULES:
            raise ValueError("정규식 규칙 목록이 올바르지 않습니다")
        if any(not isinstance(rule, ConversionRule) for rule in rules):
            raise TypeError("정규식 규칙에는 ConversionRule이 필요합니다")
        self.rules = [replace(rule) for rule in rules]
        self._compiled = [
            (rule, _compile_rule(rule)) for rule in
            sorted(self.rules, key=lambda item: item.priority, reverse=True) if rule.enabled
        ]
        self.last_timeouts = ()

    def add(self, source, targets):
        candidate = validate_entries({**self.entries, source: targets})
        self.entries = candidate

    def remove(self, source):
        self.entries.pop(source, None)

    def candidates(self, word, context=None):
        if type(word) is not str or len(word) > MAX_TEXT:
            return
        leading, core, trailing = _edges(word)
        results = list(self.entries.get(word, ()))
        if core != word:
            results.extend(leading + target + trailing for target in self.entries.get(core, ()))
        # Prefer the longest known stem when there is no exact entry.
        if core not in self.entries:
            for split in range(len(core) - 1, 0, -1):
                stem, suffix = core[:split], core[split:]
                if stem in self.entries and _particle_suffix(suffix):
                    results.extend(leading + target + suffix + trailing for target in self.entries[stem])
                    break
        timeouts = []
        deadline = time.monotonic() + REGEX_BATCH_TIMEOUT
        for rule, compiled in self._compiled:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                timeouts.append(rule.name)
                break
            try:
                # A callable replacement lets us bound output before regex.sub
                # constructs a potentially huge expanded result.
                result_length = len(core)

                def substitute(match):
                    nonlocal result_length
                    expanded = match.expand(rule.replacement)
                    result_length += len(expanded) - len(match[0])
                    if result_length > MAX_TEXT:
                        raise ValueError("정규식 변환 결과가 허용 길이를 초과합니다")
                    return expanded

                converted = compiled.sub(substitute, core, timeout=min(REGEX_TIMEOUT, remaining))
            except TimeoutError:
                timeouts.append(rule.name)
                continue
            except (ValueError, regex.error):
                continue
            if converted and converted != core:
                results.append(leading + converted + trailing)
        self.last_timeouts = tuple(timeouts)
        seen = {word}
        for result in results:
            if result and result not in seen:
                seen.add(result)
                yield result


class CustomConversionRegistry:
    """All imports validate a detached registry before publishing anything."""

    def __init__(self):
        self.entries = {}
        self.rules = []
        self.disabled_names = set()
        self.disabled_entries = set()

    def add(self, source, targets):
        self.entries = validate_entries({**self.entries, source: targets})
        return self

    def remove(self, source):
        self.entries.pop(source, None)
        self.disabled_entries.discard(source)
        return self

    def set_enabled(self, source, enabled):
        if source not in self.entries:
            raise KeyError(source)
        if type(enabled) is not bool:
            raise TypeError("활성화 여부는 참/거짓이어야 합니다")
        if enabled:
            self.disabled_entries.discard(source)
        else:
            self.disabled_entries.add(source)
        return self

    def add_rule(self, pattern, replacement, name="사용자 변환", priority=0, flags=0, enabled=True):
        if len(self.rules) >= MAX_RULES:
            raise ValueError("정규식 규칙 수가 상한을 초과합니다")
        rule = ConversionRule(pattern, replacement, name, priority, flags, enabled)
        self.rules.append(rule)
        return self

    def remove_rule(self, pattern):
        self.rules = [rule for rule in self.rules if rule.pattern != pattern]
        self.disabled_names.intersection_update(rule.name for rule in self.rules)
        return self

    def set_rule_enabled(self, index, enabled):
        if type(index) is not int or not 0 <= index < len(self.rules):
            raise IndexError("규칙 번호가 올바르지 않습니다")
        if type(enabled) is not bool:
            raise TypeError("활성화 여부는 참/거짓이어야 합니다")
        candidate = replace(self.rules[index], enabled=enabled)
        self.rules[index] = candidate
        if enabled:
            self.disabled_names.discard(candidate.name)
        return self

    def converter(self):
        validated = self.from_dict(self.to_dict())
        rules = [rule for rule in validated.rules if rule.enabled and rule.name not in validated.disabled_names]
        entries = {key: value for key, value in validated.entries.items() if key not in validated.disabled_entries}
        return CustomConversionConverter(entries, rules)

    def to_dict(self):
        entries = validate_entries(self.entries)
        if not isinstance(self.rules, list) or len(self.rules) > MAX_RULES:
            raise ValueError("정규식 규칙 목록이 올바르지 않습니다")
        rules = []
        for rule in self.rules:
            if not isinstance(rule, ConversionRule):
                raise TypeError("ConversionRule이 필요합니다")
            rules.append(asdict(rule.validate()))
        disabled_entries = _disabled(self.disabled_entries, "비활성 원문")
        disabled_names = _disabled(self.disabled_names, "비활성 규칙")
        if not disabled_entries <= entries.keys():
            raise ValueError("비활성 목록에 없는 원문 항목이 있습니다")
        return {
            "schema_version": CUSTOM_FORMAT_VERSION,
            "entries": {key: list(value) for key, value in entries.items()},
            "rules": rules,
            "disabled_names": sorted(disabled_names),
            "disabled_entries": sorted(disabled_entries),
        }

    @classmethod
    def from_dict(cls, payload):
        checked_mapping(payload, ("schema_version", "entries", "rules", "disabled_names", "disabled_entries"), "사용자 변환")
        checked_version(payload, CUSTOM_FORMAT_VERSION, "사용자 변환")
        registry = cls()
        registry.entries = validate_entries(payload.get("entries", {}))
        rules = payload.get("rules", [])
        if not isinstance(rules, list) or len(rules) > MAX_RULES:
            raise ValueError("정규식 규칙 목록이 올바르지 않습니다")
        for item in rules:
            checked_mapping(item, {item.name for item in fields(ConversionRule)}, "정규식 규칙")
            registry.rules.append(ConversionRule(**item))
        registry.disabled_names = _disabled(payload.get("disabled_names", []), "비활성 규칙")
        registry.disabled_entries = _disabled(payload.get("disabled_entries", []), "비활성 원문")
        registry.to_dict()
        return registry

    def import_dict(self, payload, *, merge=False):
        if type(merge) is not bool:
            raise TypeError("병합 여부는 참/거짓이어야 합니다")
        imported = self.from_dict(payload)
        if merge:
            combined = self.to_dict()
            combined["entries"].update(imported.to_dict()["entries"])
            combined["rules"].extend(imported.to_dict()["rules"])
            combined["disabled_entries"] = sorted(self.disabled_entries | imported.disabled_entries)
            combined["disabled_names"] = sorted(self.disabled_names | imported.disabled_names)
            imported = self.from_dict(combined)
        self.entries, self.rules = imported.entries, imported.rules
        self.disabled_names, self.disabled_entries = imported.disabled_names, imported.disabled_entries
        return self

    @classmethod
    def load(cls, path):
        return cls.from_dict(load_json(path))

    def save(self, path):
        payload = self.to_dict()
        if Path(path).exists():
            self.from_dict(load_json(path))
        return atomic_json_save(path, payload)


_CODEPOINTS = re.compile(r"U\+[0-9A-Fa-f]{4,6}(?:\s+U\+[0-9A-Fa-f]{4,6})*")


class LearningStore:
    """Bounded counts. record() is ONLY for explicit acceptance/commit events.

    Ranking and browsing are read-only. The caller must gate both ranking and
    recording with settings.learning_enabled (including private mode).
    """

    def __init__(self, counts: Optional[Mapping] = None):
        self.counts = self._validate_counts({} if counts is None else counts)

    @staticmethod
    def _validate_counts(counts):
        if not isinstance(counts, dict) or len(counts) > MAX_LEARNING_SOURCES:
            raise ValueError("학습 원문 목록이 올바르지 않거나 너무 큽니다")
        result, total = {}, 0
        for source, targets in counts.items():
            checked_text(source, "학습 원문", maximum=MAX_TEXT)
            if not isinstance(targets, dict) or not 1 <= len(targets) <= MAX_TARGETS:
                raise ValueError("학습 후보 목록이 올바르지 않습니다")
            result[source] = {}
            for target, count in targets.items():
                checked_text(target, "학습 후보", maximum=MAX_TEXT)
                if type(count) is not int or not 1 <= count <= MAX_COUNT or source == target:
                    raise ValueError("학습 횟수 또는 후보가 올바르지 않습니다")
                result[source][target] = count
                total += 1
            if total > MAX_LEARNING_RECORDS:
                raise ValueError("학습 항목 수가 상한을 초과합니다")
        return result

    def record(self, source, target, amount=1):
        checked_text(source, "학습 원문", maximum=MAX_TEXT)
        checked_text(target, "학습 후보", maximum=MAX_TEXT)
        if type(amount) is not int or not 1 <= amount <= MAX_COUNT:
            raise ValueError("학습 증가량은 허용 범위의 양의 정수여야 합니다")
        if source == target:
            return False
        targets = self.counts.get(source, {})
        if target not in targets:
            if source not in self.counts and len(self.counts) >= MAX_LEARNING_SOURCES:
                return False
            if len(targets) >= MAX_TARGETS or sum(map(len, self.counts.values())) >= MAX_LEARNING_RECORDS:
                return False
        # Saturate rather than overflow; never silently evict existing records.
        self.counts.setdefault(source, {})[target] = min(MAX_COUNT, targets.get(target, 0) + amount)
        return True

    def forget(self, source, target=None):
        checked_text(source, "학습 원문", maximum=MAX_TEXT)
        if target is None:
            self.counts.pop(source, None)
        else:
            checked_text(target, "학습 후보", maximum=MAX_TEXT)
            if source in self.counts:
                self.counts[source].pop(target, None)
                if not self.counts[source]:
                    self.counts.pop(source)
        return self

    def clear(self):
        self.counts.clear()
        return self

    def rank(self, source, candidates: Sequence[ConversionCandidate]):
        scores = self.counts.get(source, {})
        originals, rest, codepoints = [], [], []
        for index, candidate in enumerate(candidates):
            if candidate.text == source or candidate.converter == "원문":
                originals.append(candidate)
            elif _CODEPOINTS.fullmatch(candidate.text):
                codepoints.append(candidate)
            else:
                rest.append((index, candidate))
        rest.sort(key=lambda item: (-scores.get(item[1].text, 0), item[0]))
        return tuple(originals) + tuple(candidate for _, candidate in rest) + tuple(codepoints)

    def to_dict(self):
        """Legacy raw counts API retained; files carry a versioned envelope."""
        validated = self._validate_counts(self.counts)
        return {source: dict(sorted(targets.items())) for source, targets in sorted(validated.items())}

    def to_payload(self):
        return {"schema_version": LEARNING_FORMAT_VERSION, "counts": self.to_dict()}

    @classmethod
    def from_dict(cls, payload):
        if not isinstance(payload, dict):
            raise TypeError("학습 데이터에는 객체가 필요합니다")
        if "schema_version" in payload and type(payload["schema_version"]) is not dict:
            checked_mapping(payload, ("schema_version", "counts"), "학습")
            checked_version(payload, LEARNING_FORMAT_VERSION, "학습")
            if "counts" not in payload:
                raise ValueError("학습 counts가 필요합니다")
            payload = payload["counts"]
        return cls(payload)

    @classmethod
    def load(cls, path):
        return cls.from_dict(load_json(path))

    def save(self, path):
        payload = self.to_payload()
        if Path(path).exists():
            self.from_dict(load_json(path))
        return atomic_json_save(path, payload)


__all__ = [
    "ConversionRule", "CustomConversionConverter", "CustomConversionRegistry",
    "LearningStore", "validate_entries",
]
