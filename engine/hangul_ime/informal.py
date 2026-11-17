"""Small offline POS lexicon and surface variants for informal Korean.

These are analysis candidates, not replacements or mandatory segmentation.
The original spelling is still protected by KiwiSpacer's character invariant.
No input is collected, cached or sent to a service. Sources and filtering are
documented in spacing_data/README.md; all registrations precede model warmup.
"""
from pathlib import Path


# Preserve the previous authored vocabulary and its scores.
_EXISTING_WORDS = (
    ("주린이", "NNG"), ("골린이", "NNG"), ("숲세권", "NNG"),
    ("개꿀", "NNG"), ("프로불편러", "NNG"), ("존맛", "NNG"),
    ("찐친", "NNG"), ("축알못", "NNG"), ("PC방", "NNG"),
    ("킹받", "VV"), ("혼술하", "VV"), ("공활하", "VA"),
)

# A known original morpheme supplies the POS and language-model context while
# the surface form stays literal. Avoid general 개- or -알못/-린이 regex joins:
# those would merge unrelated words and ordinary noun phrases.
_VARIANTS = (
    ("존버하", "VV", "버티"),
    ("여그", "NP", "여기"), ("저그", "NP", "저기"),
    ("요것", "NP", "이것"), ("ᆸ니꺼", "EF", "ᆸ니까"),
    ("좀따", "MAG", "이따"), ("니", "NP", "너"),
    ("혼저", "MAG", "어서"),
    ("는교", "EF", "나요"), ("능교", "EF", "나요"),
    ("심더", "EF", "습니다"), ("당께", "EF", "다니까"),
    ("잖여", "EF", "잖아"), ("니꺼", "EF", "니까"),
    ("단디", "MAG", "똑바로"), ("으래이", "EF", "으라"),
    ("래이", "EF", "라"), ("당가", "EF", "는가"),
    ("ᆫ당가", "EF", "ᆫ가"), ("텨", "NNB", "터"),
    ("는디", "EC", "는데"), ("은디", "EC", "은데"),
)
_STEMS = ("광탈하", "혼밥하", "덕질하", "입덕하", "탈덕하")


def register_informal_vocabulary(kiwi):
    for word, tag in _EXISTING_WORDS:
        kiwi.add_user_word(word, tag, 0)
    data = Path(__file__).with_name("spacing_data")
    for name in ("open-korean-text-slangs.tsv", "authored-nouns.tsv"):
        for line in (data / name).read_text(encoding="utf-8").splitlines():
            if not line or line.startswith("#"):
                continue
            word, tag, score = line.split("\t")
            kiwi.add_user_word(word, tag, float(score))
    for word, tag, original in _VARIANTS:
        kiwi.add_user_word(word, tag, -3, orig_word=original)
    for stem in _STEMS:
        kiwi.add_user_word(stem, "VV", -3)
    # A fixed lexical form, not a blanket 제주 ending rule. Explicit offsets
    # prevent reconstruction from substituting the standard-language spelling.
    kiwi.add_pre_analyzed_word(
        "옵서예", [("오", "VV", 0, 1), ("세요", "EF", 1, 3)], -3,
    )
    kiwi.add_pre_analyzed_word(
        "랑가", [("이", "VCP", 0, 1), ("ᆫ가", "EF", 0, 2)], -3,
    )
    # Restrict productive spelling variants to sentence-final endings. A broad
    # 요→유 family was tested and rejected because it creates false boundaries.
    kiwi.add_re_rule("EF", "요$", "용", -2)
    kiwi.add_re_rule("EF", "요$", "욤", -2)
