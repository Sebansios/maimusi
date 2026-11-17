"""Offline spacing with optional local refinement and bounded work."""
import hashlib
import math
import os
from pathlib import Path
import re
import sys
from functools import lru_cache
from .spacing import Spacer
from .spacing_preferences import SpacingPreferences
from .spacing_policy import apply_policy
from .informal import register_informal_vocabulary
from .refinement_policy import protect_refined_boundaries
from .user_spacing import apply_user

_PROSE = re.compile(r"[가-힣A-Za-z0-9]+(?: [가-힣A-Za-z0-9]+)*")
_LAYOUT = re.compile(r" {2,}|[^\S ]+")


def _default_refiner_path():
    if sys.platform == "darwin":
        root = Path.home() / "Library" / "Application Support"
    elif sys.platform == "win32":
        root = Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local")
    else:
        root = Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share")
    return root / "HangulSpacing" / "models" / "boundary-refiner.npz"


def _bundled_refiner_path():
    """Refiner shipped inside a release build (approved for distribution);
    absent in source checkouts."""
    return Path(__file__).resolve().parent / "models" / "boundary-refiner.npz"


def _restore_manual_spaces(source, result):
    boundaries, position = set(), 0
    for char in source:
        if char == " ":
            boundaries.add(position)
        else:
            position += 1
    position, chunks = 0, []
    for char in result:
        if char != " ":
            if position in boundaries and chunks and chunks[-1] != " ":
                chunks.append(" ")
            position += 1
        chunks.append(char)
    return "".join(chunks)


def _checked_threshold(value):
    if (isinstance(value, bool) or not isinstance(value, (int, float))
            or not math.isfinite(value) or value < 0):
        raise ValueError("invalid boundary-refiner confidence threshold")
    return float(value)


class KiwiSpacer(Spacer):
    def __init__(self, refiner_path=None, *, refiner_threshold=None, refiner_removal_threshold=None):
        from kiwipiepy import Kiwi
        self.kiwi = Kiwi(num_workers=1, model_type="cong")
        register_informal_vocabulary(self.kiwi)
        # Kiwi builds its analyzer lazily. Pay this cost before accepting input,
        # not on the first user's Space. This is fixed public text, never a log.
        self.kiwi.tokenize("한글 입력 준비")
        self.refiner = None
        self.refiner_status = "disabled"
        self.refiner_error = None
        self.refiner_sha256 = None
        self.refiner_threshold = None
        self.refiner_removal_threshold = None
        if refiner_threshold is not None:
            refiner_threshold = _checked_threshold(refiner_threshold)
        if refiner_removal_threshold is not None:
            refiner_removal_threshold = _checked_threshold(refiner_removal_threshold)
        if refiner_path is False:
            return
        explicit = refiner_path is not None
        path = Path(refiner_path if explicit else (
            os.environ.get("HANGUL_SPACING_REFINER") or _default_refiner_path())).expanduser()
        try:
            if not explicit and not path.exists():
                # A user-installed file takes precedence; otherwise use the
                # model bundled with a release build, if any.
                path = _bundled_refiner_path()
            if not explicit and not path.exists():
                self.refiner_status = "missing"
                return
            # Weights are never fetched over the network.
            # Bound both loading and hashing of an accidentally oversized file.
            if path.stat().st_size > 8 * 1024 * 1024:
                raise ValueError("boundary-refiner archive is too large")
            from .boundary_refiner import BoundaryRefiner
            refiner = BoundaryRefiner.load(path)
            threshold = _checked_threshold(refiner_threshold if refiner_threshold is not None
                                           else refiner.metadata.get("confidence_threshold", 1.3))
            removal_threshold = _checked_threshold(refiner_removal_threshold if refiner_removal_threshold is not None
                                                   else refiner.metadata.get("removal_threshold", threshold))
            self.refiner_sha256 = hashlib.sha256(path.read_bytes()).hexdigest()
            self.refiner_threshold = threshold
            self.refiner_removal_threshold = removal_threshold
            self.refiner = refiner
            self.refiner_status = "loaded"
        except Exception as exc:
            self.refiner_status = "error"
            self.refiner_error = type(exc).__name__
            if explicit:
                raise

    @property
    def refiner_info(self):
        """Non-sensitive identity and health metadata, never paths or input."""
        return dict(loaded=self.refiner is not None, status=self.refiner_status,
                    model_sha256=self.refiner_sha256, confidence_threshold=self.refiner_threshold,
                    removal_threshold=self.refiner_removal_threshold,
                    error=self.refiner_error)

    def _refine(self, source, baseline, preferences):
        if self.refiner is None or not re.search("[가-힣]", source):
            return baseline
        try:
            result = self.refiner.refine(baseline, confidence_threshold=self.refiner_threshold,
                                        removal_threshold=self.refiner_removal_threshold)
            if not isinstance(result, str) or result.replace(" ", "") != source.replace(" ", ""):
                raise ValueError("invalid boundary-refiner output")
            # The refiner deliberately returns unusual baseline layout intact.
            # A no-op is valid even when Kiwi itself emitted repeated spaces.
            if result != baseline and (result.startswith(" ") or result.endswith(" ") or _LAYOUT.search(result)):
                raise ValueError("invalid boundary-refiner layout")
            result = protect_refined_boundaries(baseline, result, self.kiwi.tokenize, self.kiwi.morpheme)
            if preferences.existing_spaces == "preserve":
                # Only explicit style rules below may override a manual space;
                # the learned model itself never owns that user decision.
                result = _restore_manual_spaces(source, result)
            result = _PROSE.sub(lambda match: apply_policy(
                match.group(), preferences, self.kiwi.tokenize,
                lookup_morpheme=self.kiwi.morpheme), result)
            if result.replace(" ", "") != source.replace(" ", ""):
                raise ValueError("invalid spacing-policy output")
            return result
        except Exception as exc:
            # Fail closed for this process, retaining only the error's type.
            self.refiner = None
            self.refiner_status = "error"
            self.refiner_error = type(exc).__name__
            return baseline

    def space(self, text, preferences=None, *, preserve_phrase=False):
        if len(text) > 4096:
            raise ValueError("한 번에 최대 4,096자까지 변환할 수 있습니다. 부분을 선택해 주세요.")
        preferences = (preferences or SpacingPreferences()).validate()
        if not preferences.enabled:
            return text
        use_refiner = self.refiner is not None and not preserve_phrase and preferences.compound == "model"
        started_with_refiner = use_refiner
        # One contextual analysis per prose span, rather than per existing word.
        # Tabs, newlines, indentation and protected identifiers are opaque.
        # Latin must share context with Hangul: 오늘RTX5090 and ASMR영상
        # have real word boundaries that separate Hangul-only spans cannot see.
        def convert(match, *, canonical=False):
            source = match.group()
            compact = source.replace(" ", "")
            raw = compact if canonical or preferences.existing_spaces == "normalize" else source
            result = source if preserve_phrase else self.kiwi.space(raw)
            if result.replace(" ", "") != compact:
                return source
            if not canonical and preferences.existing_spaces == "preserve":
                # Keep manually entered boundaries unless an explicit style
                # rule below owns them. No global result cache retains input.
                result = _restore_manual_spaces(source, result)
            result = apply_policy(result, preferences, self.kiwi.tokenize,
                                  lookup_morpheme=self.kiwi.morpheme)
            return result if result.replace(" ", "") == compact else source

        def refine_line(source):
            # Preserve edge spaces around protected text and layout verbatim.
            # Punctuation stays in the model's context across prose spans.
            core = source.strip(" ")
            if not core:
                return source
            start = len(source) - len(source.lstrip(" "))
            end = len(source.rstrip(" "))
            if not re.search("[가-힣]", core):
                return source[:start] + _PROSE.sub(convert, core) + source[end:]
            # Existing wording the contextual engine accepts unchanged is an
            # explicit manual decision. Keep it before running the learned
            # second pass; this identity branch never changes model context.
            if (preferences.existing_spaces == "preserve" and " " in core
                    and _PROSE.sub(convert, core) == core):
                return source
            baseline = _PROSE.sub(lambda match: convert(match, canonical=True), core.replace(" ", ""))
            baseline = re.sub(" +", " ", baseline).strip(" ")
            return source[:start] + self._refine(core, baseline, preferences) + source[end:]

        def unprotected(source):
            return apply_user(spaced_part(source), preferences)

        def spaced_part(source):
            if not use_refiner:
                return _PROSE.sub(convert, source)
            chunks, last = [], 0
            for layout in _LAYOUT.finditer(source):
                chunks.extend((refine_line(source[last:layout.start()]), layout.group()))
                last = layout.end()
            chunks.append(refine_line(source[last:]))
            return "".join(chunks)

        from .settings import _PROTECTED_TEXT
        chunks, last = [], 0
        for protected in _PROTECTED_TEXT.finditer(text):
            chunks.append(unprotected(text[last:protected.start()]))
            chunks.append(protected[0])
            last = protected.end()
        chunks.append(unprotected(text[last:]))
        if started_with_refiner and self.refiner is None:
            # A later segment may fail after earlier ones were refined. Return
            # one consistent legacy result for the entire request in that case.
            return self.space(text, preferences, preserve_phrase=preserve_phrase)
        return "".join(chunks)


@lru_cache(maxsize=1)
def default_spacer():
    return KiwiSpacer()
