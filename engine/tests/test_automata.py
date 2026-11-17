import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from hangul_ime import compose_keystrokes, Hangul2Automaton  # noqa: E402
from hangul_ime.jamo import compose, decompose, is_syllable  # noqa: E402


class TestJamo(unittest.TestCase):
    def test_compose_decompose_roundtrip(self):
        for code in range(0xAC00, 0xD7A4, 137):   # 표본
            ch = chr(code)
            cho, jung, jong = decompose(ch)
            self.assertEqual(compose(cho, jung, jong), ch)

    def test_is_syllable(self):
        self.assertTrue(is_syllable("가"))
        self.assertTrue(is_syllable("힣"))
        self.assertFalse(is_syllable("ㄱ"))
        self.assertFalse(is_syllable("A"))


class TestAutomaton(unittest.TestCase):
    def test_basic(self):
        self.assertEqual(compose_keystrokes("ㄴㅏㄴㅡㄴ"), "나는")
        self.assertEqual(compose_keystrokes("ㅎㅏㄱㄱㅛ"), "학교")
        self.assertEqual(compose_keystrokes("ㅇㅏㄴㄴㅕㅇ"), "안녕")

    def test_vowel_combine(self):
        self.assertEqual(compose_keystrokes("ㄱㅗㅏ"), "과")     # ㅗ+ㅏ=ㅘ
        self.assertEqual(compose_keystrokes("ㅇㅢ"), "의")       # ㅡ+ㅣ=ㅢ

    def test_jong_combine(self):
        self.assertEqual(compose_keystrokes("ㄷㅏㄹㄱ"), "닭")   # ㄹ+ㄱ=ㄺ
        self.assertEqual(compose_keystrokes("ㄱㅏㅂㅅ"), "값")   # ㅂ+ㅅ=ㅄ

    def test_jong_move_to_next(self):
        # 받침 뒤 모음 -> 받침이 다음 초성으로
        self.assertEqual(compose_keystrokes("ㄱㅏㄴㅏ"), "가나")
        # 겹받침 뒤 모음 -> 뒷자음만 이동
        self.assertEqual(compose_keystrokes("ㄷㅏㄹㄱㅏ"), "달가")
        self.assertEqual(compose_keystrokes("ㄱㅏㅂㅅㅏ"), "갑사")

    def test_preedit_state(self):
        a = Hangul2Automaton()
        a.feed_text("ㅎㅏㄴ")
        self.assertEqual(a.text(), "한")          # 조합 중
        a.feed("ㄱ")                               # 한+ㄱ -> 받침 추가? '핝'
        a.feed("ㅡ"); a.feed("ㄹ")                 # ㄱ 이동 -> 한+그ㄹ
        a.flush()
        self.assertEqual(a.text(), "한글")


if __name__ == "__main__":
    unittest.main()
