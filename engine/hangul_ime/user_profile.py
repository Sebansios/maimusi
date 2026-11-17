"""One atomic user profile; dialog edits live in detached snapshots.

The release includes no user profile. The GUI chooses an OS-local data path.
A cancelled editor discards its snapshot; commit validates every section, checks
for concurrent changes, and replaces one file before publishing live state.
"""
from __future__ import annotations

import csv
from dataclasses import dataclass, field
import hashlib
import io
import json
from pathlib import Path
import threading

from .customization import CustomConversionRegistry, LearningStore, validate_entries, _disabled
from .persistence import (
    MAX_JSON_BYTES, DurabilityError, atomic_json_save, atomic_text_save,
    checked_mapping, checked_version, load_json, profile_lock,
)
from .settings import TypographySettings

PROFILE_FORMAT_VERSION = 1
HANJA_FORMAT_VERSION = 1


class ProfileConflictError(RuntimeError):
    """Reload and reapply the draft instead of overwriting newer user data."""


def validate_hanja_overlay(entries, disabled=()):
    entries = validate_entries(entries)
    disabled = _disabled(disabled, "비활성 한자 원문")
    for source, targets in entries.items():
        if source.startswith("#") or any(char in source for char in "\t\r\n"):
            raise ValueError("한자 원문에는 탭·줄바꿈·행 첫 #을 사용할 수 없습니다")
        if any(any(char in target for char in "\t\r\n") for target in targets):
            raise ValueError("한자 후보에는 탭·줄바꿈을 사용할 수 없습니다")
    for source in disabled:
        if source.startswith("#") or any(char in source for char in "\t\r\n"):
            raise ValueError("비활성 한자 원문 형식이 올바르지 않습니다")
    return entries, disabled


def hanja_overlay_from_dict(payload):
    if not isinstance(payload, dict):
        raise TypeError("한자 사전에는 JSON 객체가 필요합니다")
    # Legacy plain mappings remain supported, including a word named "entries".
    if "schema_version" in payload or isinstance(payload.get("entries"), dict):
        checked_mapping(payload, ("schema_version", "entries", "disabled"), "한자 사전")
        checked_version(payload, HANJA_FORMAT_VERSION, "한자 사전")
        return validate_hanja_overlay(payload.get("entries", {}), payload.get("disabled", []))
    return validate_hanja_overlay(payload)


def hanja_overlay_to_dict(entries, disabled=()):
    entries, disabled = validate_hanja_overlay(entries, disabled)
    return {
        "schema_version": HANJA_FORMAT_VERSION,
        "entries": {key: list(values) for key, values in entries.items()},
        "disabled": sorted(disabled),
    }


def load_hanja_overlay(path):
    """Return (entries, disabled) only after the whole JSON/TSV validates.

    TSV matches HanjaConverter's two columns: source TAB CSV-quoted candidates.
    Disabled built-in entries use a '# disabled TAB source' comment line.
    No HanjaConverter import is required, so reading user data has no data loads.
    """
    path = Path(path)
    if path.suffix.lower() == ".json":
        return hanja_overlay_from_dict(load_json(path))
    with path.open("rb") as handle:
        raw = handle.read(MAX_JSON_BYTES + 1)
    if len(raw) > MAX_JSON_BYTES:
        raise ValueError("한자 사전 파일이 허용 크기를 초과합니다")
    entries, disabled = {}, set()
    for number, line in enumerate(raw.decode("utf-8-sig").splitlines(), 1):
        if line.startswith("# disabled\t"):
            disabled.add(line.split("\t", 1)[1])
            continue
        if not line.strip() or line.startswith("#"):
            continue
        parts = line.split("\t")
        if len(parts) != 2:
            raise ValueError(f"한자 TSV {number}행에는 두 열이 필요합니다")
        try:
            targets = next(csv.reader([parts[1]], strict=True))
        except csv.Error as error:
            raise ValueError(f"한자 TSV {number}행 후보 형식 오류") from error
        validated, _ = validate_hanja_overlay({parts[0]: targets})
        existing = entries.get(parts[0], ())
        entries[parts[0]] = tuple(dict.fromkeys(existing + validated[parts[0]]))
    return validate_hanja_overlay(entries, disabled)


def save_hanja_overlay(path, entries, disabled=()):
    path = Path(path)
    entries, disabled = validate_hanja_overlay(entries, disabled)
    if path.exists():
        load_hanja_overlay(path)  # Never clobber a corrupt/future source.
    if path.suffix.lower() == ".json":
        return atomic_json_save(path, hanja_overlay_to_dict(entries, disabled))
    rows = []
    for source, targets in sorted(entries.items()):
        buffer = io.StringIO(newline="")
        csv.writer(buffer, lineterminator="\n").writerow(targets)
        rows.append(source + "\t" + buffer.getvalue())
    rows.extend(f"# disabled\t{source}\n" for source in sorted(disabled))
    text = "".join(rows)
    if len(text.encode("utf-8")) > MAX_JSON_BYTES:
        raise ValueError("한자 사전 데이터가 허용 크기를 초과합니다")
    return atomic_text_save(path, text)


@dataclass
class UserProfile:
    settings: TypographySettings = field(default_factory=TypographySettings)
    custom: CustomConversionRegistry = field(default_factory=CustomConversionRegistry)
    hanja_entries: dict = field(default_factory=dict)
    hanja_disabled: set = field(default_factory=set)
    learning: LearningStore = field(default_factory=LearningStore)
    _base_revision: int | None = field(default=None, repr=False, compare=False)

    def to_dict(self):
        if not isinstance(self.settings, TypographySettings):
            raise TypeError("프로필 설정 형식이 올바르지 않습니다")
        if not isinstance(self.custom, CustomConversionRegistry):
            raise TypeError("사용자 변환 형식이 올바르지 않습니다")
        if not isinstance(self.learning, LearningStore):
            raise TypeError("학습 데이터 형식이 올바르지 않습니다")
        return {
            "schema_version": PROFILE_FORMAT_VERSION,
            "settings": self.settings.to_dict(),
            "custom": self.custom.to_dict(),
            "hanja": hanja_overlay_to_dict(self.hanja_entries, self.hanja_disabled),
            "learning": self.learning.to_payload(),
        }

    @classmethod
    def from_dict(cls, payload):
        checked_mapping(payload, ("schema_version", "settings", "custom", "hanja", "learning"), "사용자 프로필")
        checked_version(payload, PROFILE_FORMAT_VERSION, "사용자 프로필")
        settings = TypographySettings.from_dict(payload.get("settings", {}))
        custom = CustomConversionRegistry.from_dict(payload.get("custom", {}))
        entries, disabled = hanja_overlay_from_dict(payload.get("hanja", {}))
        learning = LearningStore.from_dict(payload.get("learning", {}))
        return cls(settings, custom, entries, disabled, learning)

    def validate(self):
        self.to_dict()
        return self

    def import_hanja(self, path, *, merge=True):
        if type(merge) is not bool:
            raise TypeError("병합 여부는 참/거짓이어야 합니다")
        entries, disabled = load_hanja_overlay(path)
        if merge:
            entries = {**self.hanja_entries, **entries}
            disabled = self.hanja_disabled | disabled
        entries, disabled = validate_hanja_overlay(entries, disabled)
        self.hanja_entries, self.hanja_disabled = entries, disabled
        return self

    def export_hanja(self, path):
        return save_hanja_overlay(path, self.hanja_entries, self.hanja_disabled)


class UserProfileStore:
    def __init__(self, path, profile=None):
        self.path = Path(path)
        self.profile = UserProfile.from_dict((profile if profile is not None else UserProfile()).to_dict())
        self._fingerprint = None
        self._revision = 0
        self._lock = threading.RLock()
        self.profile._base_revision = self._revision

    @staticmethod
    def _fingerprint_payload(payload):
        return hashlib.sha256(
            json.dumps(payload, ensure_ascii=False, sort_keys=True, allow_nan=False).encode("utf-8")
        ).hexdigest()

    def load(self):
        with self._lock:
            if not self.path.exists():
                if self._fingerprint is not None:
                    raise ProfileConflictError("사용자 프로필 파일이 외부에서 삭제되었습니다")
                return self.profile
            payload = load_json(self.path)
            candidate = UserProfile.from_dict(payload)
            self._fingerprint = self._fingerprint_payload(payload)
            self._revision += 1
            candidate._base_revision = self._revision
            self.profile = candidate
            return candidate

    def snapshot(self):
        with self._lock:
            draft = UserProfile.from_dict(self.profile.to_dict())
            draft._base_revision = self._revision
            return draft

    def commit(self, profile):
        """Commit a detached profile or fail without partially replacing sections.

        DurabilityError(committed=True) is the sole post-replacement exception;
        the complete profile is already visible, but crash durability is unknown.
        """
        if not isinstance(profile, UserProfile):
            raise TypeError("UserProfile이 필요합니다")
        with self._lock:
            if profile._base_revision is not None and profile._base_revision != self._revision:
                raise ProfileConflictError("이 편집을 시작한 뒤 프로필이 변경되었습니다. 다시 열어 적용하십시오.")
            payload = profile.to_dict()
            candidate = UserProfile.from_dict(payload)
            with profile_lock(self.path):
                disk_fingerprint = None
                if self.path.exists():
                    current = load_json(self.path)
                    UserProfile.from_dict(current)  # Unknown versions never get overwritten.
                    disk_fingerprint = self._fingerprint_payload(current)
                if disk_fingerprint != self._fingerprint:
                    raise ProfileConflictError("다른 창이나 프로그램이 프로필을 변경했습니다. 다시 읽어 적용하십시오.")
                durability_error = None
                try:
                    atomic_json_save(self.path, payload)
                except DurabilityError as error:
                    durability_error = error
                self._fingerprint = self._fingerprint_payload(payload)
                self._revision += 1
                candidate._base_revision = self._revision
                self.profile = candidate
                if durability_error is not None:
                    raise durability_error
            return self.profile

    def save(self):
        self.commit(self.profile)
        return self.path

    def record_commit(self, source, target, amount=1):
        """Privacy gate plus one atomic explicit acceptance, never a cycle."""
        with self._lock:
            if not self.profile.settings.learning_enabled:
                return False
            draft = self.snapshot()
            if not draft.learning.record(source, target, amount):
                return False
            self.commit(draft)
            return True

    def clear_learning(self):
        draft = self.snapshot()
        draft.learning.clear()
        return self.commit(draft)


__all__ = [
    "PROFILE_FORMAT_VERSION", "UserProfile", "UserProfileStore", "ProfileConflictError",
    "load_hanja_overlay", "save_hanja_overlay", "validate_hanja_overlay",
    "hanja_overlay_from_dict", "hanja_overlay_to_dict",
]
