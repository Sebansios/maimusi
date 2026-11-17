"""Build isolated surface-preserving/contextual spacing experiments.

No corpus text is embedded; comparisons use tools/compare_spacing.py.
"""
from pathlib import Path
import shutil

ROOT = Path(__file__).resolve().parents[1]
BASELINE = ROOT / "build/spacing-v046-baseline/engine"
HELPER = r'''"""Render morphological word boundaries without reconstructing spelling."""
import re
from kiwipiepy import Match

_INSERT = re.compile('|'.join([
    r'(([^SUWX]|X[RS]|S[EH]).* ([NMI]|V[VAX]|VCN|XR|XPN|S[WLHN]))',
    r'(SN ([MI]|N[PR]|NN[GP]|V[VAX]|VCN|XR|XPN|S[WH]))',
    r'((S[FPL]).* ([NMI]|V[VAX]|VCN|XR|XPN|S[WH]))',
]))

def offset_space(kiwi, raw):
    tokens = kiwi.analyze(raw, top_n=1, match_options=Match.ALL | Match.Z_CODA)[0][0]
    cuts = set()
    previous = None
    for token in tokens:
        if (previous and token.start >= previous.end and token.start > 0
                and _INSERT.match(previous.tag + ' ' + token.tag)
                and not (token.tag == 'VX' and token.form in ('하', '지'))):
            cuts.add(token.start)
        previous = token
    return ''.join((' ' if i in cuts and not raw[i - 1].isspace()
                    and not c.isspace() else '') + c for i, c in enumerate(raw))
'''

def main():
    for name, wide in (("offset", False), ("context", True)):
        destination = ROOT / "build/spacing-v046-context" / name / "engine"
        if destination.exists():
            raise SystemExit(f"refusing to replace {destination}")
        shutil.copytree(BASELINE, destination)
        package = destination / "hangul_ime"
        (package / "context_spacing.py").write_text(HELPER, encoding="utf-8")
        release = package / "release_spacing.py"
        source = release.read_text(encoding="utf-8")
        source = source.replace('from .spacing import Spacer',
                                'from .spacing import Spacer\nfrom .context_spacing import offset_space')
        source = source.replace('self.kiwi.space(raw)', 'offset_space(self.kiwi, raw)')
        if wide:
            source = source.replace('r"[가-힣A-Za-z0-9]+(?: [가-힣A-Za-z0-9]+)*"',
                                    'r"[^\\s]+(?: [^\\s]+)*"')
        release.write_text(source, encoding="utf-8")
        print(destination)

if __name__ == '__main__':
    main()
