"""Engine service for native input-method front ends.

The input method starts this process and talks to it over stdin/stdout with
one JSON object per line (UTF-8):

    -> {"id": 1, "op": "space", "text": "나는학교에간다"}
    <- {"id": 1, "ok": true, "text": "나는 학교에 간다"}
    -> {"id": 2, "op": "candidates", "word": "학교에"}
    <- {"id": 2, "ok": true, "items": ["學校에", "🏫에"], "notes": ["한자", "이모지"]}
    -> {"id": 3, "op": "configure", "spacing": {...SpacingPreferences...},
        "hanja_forms": "education" | "ks"}
    <- {"id": 3, "ok": true}

On start it prints {"op": "ready", ...} once the model is loaded. It exits
when stdin closes. Typed text is never written to disk, logged or sent
anywhere; errors carry only an error type, never the input.
"""
import json
import sys

from . import __version__, __engine_version__

MAX_TEXT = 4096


def _reply(obj):
    sys.stdout.write(json.dumps(obj, ensure_ascii=False) + "\n")
    sys.stdout.flush()


class Service:
    hanja_gloss = False

    def __init__(self):
        from .release_spacing import KiwiSpacer
        from .spacing_preferences import SpacingPreferences
        self.spacer = KiwiSpacer()
        self.preferences = SpacingPreferences()
        self.hanja_forms = "education"
        self.hanja_presentation = "hanja"
        self.symbol_consonants = False
        self.hanja_gloss = False
        self._transformer = None

    @property
    def transformer(self):
        # Emoji/Hanja/unit/date tables load on first use, not at start-up.
        if self._transformer is None:
            from .advanced_transform import default_word_transformer
            kiwi = self.spacer.kiwi

            def analyzer(text):
                # (시작, 길이, 형태, 품사): 한자 어근 분리와 하다 동사 판별에 쓴다.
                return [(t.start, t.len, t.form, t.tag) for t in kiwi.tokenize(text)]

            self._transformer = default_word_transformer(analyzer=analyzer, hanja_forms=self.hanja_forms,
                                                        symbol_consonants=self.symbol_consonants,
                                                        hanja_presentation=self.hanja_presentation,
                                                        hanja_gloss=self.hanja_gloss)
        return self._transformer

    def handle(self, request):
        op = request.get("op")
        if op == "ping":
            return {"version": __version__, "engine_version": __engine_version__, "refiner": self.spacer.refiner_info}
        if op == "learn":
            # 손으로 고친 경계에서 기억할 어절과 단어를 뽑아 돌려준다. 저장은 호스트가 한다.
            from .user_spacing import learn
            return learn(request.get("proposed"), request.get("accepted"),
                         lambda text: self.spacer.kiwi.tokenize(text))
        if op == "configure":
            from .spacing_preferences import SpacingPreferences
            if "spacing" in request:
                self.preferences = SpacingPreferences.from_dict(request["spacing"])
            forms = request.get("hanja_forms", self.hanja_forms)
            if forms not in ("education", "ks"):
                raise ValueError("hanja_forms")
            from .advanced_transform import HANJA_PRESENTATIONS
            presentation = request.get("hanja_presentation", self.hanja_presentation)
            if presentation not in HANJA_PRESENTATIONS:
                raise ValueError("hanja_presentation")
            consonants = request.get("symbol_consonants", self.symbol_consonants)
            if not isinstance(consonants, bool):
                raise ValueError("symbol_consonants")
            gloss = request.get("hanja_gloss", self.hanja_gloss)
            if not isinstance(gloss, bool):
                raise ValueError("hanja_gloss")
            if gloss != self.hanja_gloss:
                self.hanja_gloss = gloss
                self._transformer = None
            if consonants != self.symbol_consonants:
                self.symbol_consonants = consonants
                self._transformer = None
            if forms != self.hanja_forms:
                self.hanja_forms = forms
                self._transformer = None
            if presentation != self.hanja_presentation:
                self.hanja_presentation = presentation
                self._transformer = None
            return {}
        if op == "space":
            text = request.get("text")
            if not isinstance(text, str) or len(text) > MAX_TEXT:
                raise ValueError("text")
            # Keep exact conversion names together (e.g. 특수문자/대문자알파),
            # so spacing cannot split the requested conversion into two words.
            from .symbols import ALIASES, GROUPS
            if text in ALIASES or (text in GROUPS and (len(text) > 1 or self.symbol_consonants)):
                return {"text": text}
            # 훈음 찾기를 켰을 때, 훈음(살찔비, 배울학학교교)만 입력했으면 붙여 두어 한자 후보로 찾게 한다.
            from .advanced_transform import hanja_gloss_split
            if self.hanja_gloss and hanja_gloss_split(text):
                return {"text": text}
            preferences = self.preferences
            if "spacing" in request:
                # 설정 창 예문: 저장하지 않고 이 요청에만 쓴다.
                from .spacing_preferences import SpacingPreferences
                preferences = SpacingPreferences.from_dict(request["spacing"])
            return {"text": self.spacer.space(text, preferences)}
        if op == "candidates":
            word = request.get("word")
            if not isinstance(word, str) or not word or len(word) > 256:
                raise ValueError("word")
            found = [c for c in self.transformer.candidates(word)[1:]
                     if "\n" not in c.text and "\t" not in c.text][:511]
            return {"items": [c.text for c in found], "notes": [c.converter for c in found]}
        raise ValueError("op")


def main(argv=None):
    # The protocol is UTF-8 regardless of the console code page (cp949 on Korean
    # Windows). A byte order mark before the first request is skipped: .NET
    # writers on a UTF-8 console (code page 65001) put one there.
    for stream, encoding in ((sys.stdin, "utf-8-sig"), (sys.stdout, "utf-8")):
        if stream is not None and hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding=encoding)
    try:
        service = Service()
    except Exception as exc:  # model missing or broken
        _reply({"op": "ready", "ok": False, "error": type(exc).__name__})
        return 1
    _reply({"op": "ready", "ok": True, "version": __version__, "engine_version": __engine_version__, "engine": "kiwi",
            "refiner": service.spacer.refiner_info})
    while True:
        line = sys.stdin.readline()
        if not line:
            return 0
        request_id = None
        try:
            request = json.loads(line)
            request_id = request.get("id")
            response = service.handle(request)
            response.update(id=request_id, ok=True)
        except Exception as exc:
            response = {"id": request_id, "ok": False, "error": type(exc).__name__}
        _reply(response)


if __name__ == "__main__":
    raise SystemExit(main())
