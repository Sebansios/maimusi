# Bundled converter data

This directory contains version-pinned public upstream data and its redistribution
notices. The desktop distribution must include this entire directory. No runtime
download is required. See `sources.json` for versions, URLs and SHA-256 checksums.

Unicode Emoji 17.0 supplies every fully-qualified RGI emoji sequence and standalone
emoji component. CLDR 48.2 supplies Korean and English names and keywords, including
derived annotations for skin tones, flags and ZWJ sequences. Non-emoji CLDR symbols
are excluded from the emoji index; CLDR sequences without presentation selectors
are resolved to the Unicode fully-qualified spelling.

The libhangul 0.2.0 `hanja.txt` dictionary has its own BSD 3-Clause license in its
header. This application bundles that data file, not the LGPL-2.1 libhangul library.
Retain both the data header and `LICENSE-libhangul-hanja.txt` in source and binary
distributions. Public upstream copyright attributions are required license notices,
not user profile information.

Converter source, tests and the notices in this directory contain no local user
paths or account identifiers.
