"""Shared classification of opaque addresses, numbers, paths and identifiers.

A period between Korean words is sentence punctuation unless another part of
the token supplies identifier syntax. A path separator or an ASCII extension
provides that evidence; bare dot-separated Korean words do not. Classification
uses syntax only and retains neither input nor lookup results.
"""
import re


class ProtectedText:
    # Korean prose may touch a numeric token before spacing is restored.
    # Keep ASCII identifier prefixes excluded without making numeric opacity
    # depend on whether the user has already typed a space after Hangul.
    _candidates = re.compile(
        r"(?P<url>(?:[a-zA-Z][a-zA-Z0-9+.-]*://|www\.)[^\s<>\"「」『』]+)"
        r"|(?P<windows_path>[A-Za-z]:\\[^\s<>\"「」『』]+)"
        r"|(?P<rooted_path>(?<!\w)(?:~?/|\.\.?/|\\\\)[^\s<>\"「」『』]+)"
        r"|(?P<email>[\w.+-]+@[\w.-]+\.[A-Za-z]{2,})"
        r"|(?P<signed_number>(?<![A-Za-z0-9_])[+-](?:\d+(?:[.,:/-]\d+)*|\.\d+)(?:[eE][+-]?\d+)?)"
        r"|(?P<number>(?<![A-Za-z0-9_])[+-]?\d+(?:[.,:/-]\d+)+(?:[eE][+-]?\d+)?)"
        r"|(?P<decimal>(?<![A-Za-z0-9_])\.\d+)"
        r"|(?P<identifier>\w+(?:[-_./:\\]\w+)+)",
        re.UNICODE,
    )
    _ascii_component_start = re.compile(r"[A-Za-z0-9]")

    @classmethod
    def _is_identifier(cls, candidate):
        # Keep existing non-period identifier syntax, including Korean paths
        # and underscore-delimited names. No extension/TLD word list is needed.
        if any(separator in candidate for separator in "-_/:\\"):
            return True
        if candidate.isascii():
            return True
        # Retain the existing opaque span if a dotted component starts with
        # ASCII: extensions, domains, decimals and versions may have Korean
        # particles/prose attached (보고서.pdf를, 수치3.14를, 버전v1.2.3).
        # Filtering only the final component would expose embedded numeric or
        # filename dots to typography conversion. Bare Korean dotted names
        # need explicit path/URL syntax to distinguish them from sentences.
        return any(cls._ascii_component_start.match(part) for part in candidate.split(".")[1:])

    def finditer(self, text, pos=0, endpos=None):
        for match in self._candidates.finditer(text, pos, len(text) if endpos is None else endpos):
            if match.lastgroup == "identifier" and not self._is_identifier(match[0]):
                continue
            yield match


PROTECTED_TEXT = ProtectedText()
