"""Bounded JSON loading and private, durable, atomic user-data writes."""
from __future__ import annotations

from contextlib import contextmanager
import errno
import json
import os
from pathlib import Path
import tempfile

MAX_JSON_BYTES = 8 * 1024 * 1024


class DurabilityError(OSError):
    """Replacement succeeded, but directory fsync failed; callers must reload.

    The committed flag distinguishes failures that leave the old file intact.
    Never retry a non-idempotent operation blindly after this error.
    """

    committed = True


def checked_mapping(payload, allowed, label="설정"):
    if not isinstance(payload, dict):
        raise TypeError(f"{label}: JSON 객체가 필요합니다")
    if any(type(key) is not str for key in payload):
        raise TypeError(f"{label}: 키는 문자열이어야 합니다")
    unknown = set(payload) - set(allowed)
    if unknown:
        raise ValueError(f"{label}: 지원하지 않는 필드: {', '.join(sorted(unknown))}")
    return payload


def checked_version(payload, current, label="설정"):
    version = payload.get("schema_version", 0)
    if type(version) is not int or version < 0:
        raise ValueError(f"{label}: 형식 버전은 0 이상의 정수여야 합니다")
    if version > current:
        raise ValueError(f"{label}: 더 새로운 형식({version})은 지원하지 않습니다")
    return version


def checked_text(value, label, *, maximum=4096, empty=False):
    if type(value) is not str:
        raise TypeError(f"{label}: 문자열이 필요합니다")
    if len(value) > maximum or (not empty and not value.strip()):
        raise ValueError(f"{label}: 비어 있지 않은 {maximum}자 이하 문자열이 필요합니다")
    if "\x00" in value or any(0xD800 <= ord(char) <= 0xDFFF for char in value):
        raise ValueError(f"{label}: NUL 또는 단독 서로게이트는 사용할 수 없습니다")
    return value


def _pairs_without_duplicates(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("JSON에 중복된 키가 있습니다")
        result[key] = value
    return result


def _invalid_constant(value):
    raise ValueError("JSON에 유한하지 않은 숫자가 있습니다")


def load_json(path):
    """Reject oversized, ambiguous, malformed data without touching the source."""
    with Path(path).open("rb") as handle:
        raw = handle.read(MAX_JSON_BYTES + 1)
    if len(raw) > MAX_JSON_BYTES:
        raise ValueError("사용자 데이터 파일이 허용 크기를 초과합니다")
    return json.loads(
        raw.decode("utf-8"), object_pairs_hook=_pairs_without_duplicates,
        parse_constant=_invalid_constant,
    )


def _make_parent(path):
    # Do not chmod an existing shared parent, such as Application Support.
    missing = []
    parent = path.parent
    while not parent.exists():
        missing.append(parent)
        parent = parent.parent
    for directory in reversed(missing):
        try:
            directory.mkdir(mode=0o700)
        except FileExistsError:
            if not directory.is_dir():
                raise


def atomic_text_save(path, text):
    """0600 temporary file + file fsync + replace + parent directory fsync."""
    path = Path(path)
    if type(text) is not str:
        raise TypeError("저장할 내용은 문자열이어야 합니다")
    encoded = text.encode("utf-8")
    if path.is_symlink():
        raise ValueError("사용자 데이터 심볼릭 링크를 덮어쓰지 않습니다")
    _make_parent(path)
    directory_fd = None
    if os.name == "posix":
        directory_fd = os.open(path.parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    temporary = None
    try:
        fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
        with os.fdopen(fd, "wb") as handle:
            if os.name == "posix":
                os.fchmod(handle.fileno(), 0o600)
            handle.write(encoded)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        temporary = None
        if directory_fd is not None:
            try:
                os.fsync(directory_fd)
            except OSError as error:
                raise DurabilityError(
                    error.errno or errno.EIO,
                    "파일은 교체되었지만 디렉터리 동기화를 확인하지 못했습니다. 다시 읽어 확인하십시오.",
                ) from error
    finally:
        if temporary is not None:
            try:
                os.unlink(temporary)
            except FileNotFoundError:
                pass
        if directory_fd is not None:
            os.close(directory_fd)
    return path


def atomic_json_save(path, payload):
    serialized = json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
    if len(serialized.encode("utf-8")) > MAX_JSON_BYTES:
        raise ValueError("사용자 데이터가 허용 크기를 초과합니다")
    return atomic_text_save(path, serialized)


@contextmanager
def profile_lock(path):
    """Advisory process lock for cooperating profile writers (macOS/POSIX)."""
    path = Path(path)
    _make_parent(path)
    lock_path = path.with_name(f".{path.name}.lock")
    flags = os.O_CREAT | os.O_RDWR | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(lock_path, flags, 0o600)
    try:
        if os.name == "posix":
            import fcntl
            os.fchmod(descriptor, 0o600)
            fcntl.flock(descriptor, fcntl.LOCK_EX)
        yield
    finally:
        if os.name == "posix":
            import fcntl
            fcntl.flock(descriptor, fcntl.LOCK_UN)
        os.close(descriptor)
