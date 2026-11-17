//! Two-set (dubeolsik) Hangul composition automaton with jamo-level undo.
//!
//! Completed syllables are handed to the caller through `feed`'s return value;
//! only the syllable under construction stays here. Backspace walks back one
//! jamo at a time inside that syllable, like the system Korean input methods.

use crate::jamo::{
    cho_index, combine_jong, combine_vowel, compose, jong_index, jung_index, split_jong, CHO, JONG,
    JUNG,
};

#[derive(Clone, Copy, Debug, Default, PartialEq, Eq)]
struct Syllable {
    cho: Option<u8>,
    jung: Option<u8>,
    jong: Option<u8>,
}

impl Syllable {
    fn is_empty(&self) -> bool {
        self.cho.is_none() && self.jung.is_none() && self.jong.is_none()
    }

    fn render(&self) -> Option<char> {
        match (self.cho, self.jung, self.jong) {
            (Some(l), Some(v), t) => Some(compose(l, v, t.unwrap_or(0))),
            (Some(l), None, _) => Some(CHO[l as usize]),
            (None, Some(v), _) => Some(JUNG[v as usize]),
            _ => None,
        }
    }
}

#[derive(Clone, Debug, Default)]
pub struct Composer {
    current: Syllable,
    /// States before each jamo of the current syllable, for Backspace.
    history: Vec<Syllable>,
}

impl Composer {
    pub fn new() -> Self {
        Self::default()
    }

    pub fn is_empty(&self) -> bool {
        self.current.is_empty()
    }

    /// The syllable (or lone jamo) under construction.
    pub fn preedit(&self) -> Option<char> {
        self.current.render()
    }

    /// Finish the current syllable and return it.
    pub fn flush(&mut self) -> Option<char> {
        let out = self.current.render();
        self.current = Syllable::default();
        self.history.clear();
        out
    }

    pub fn reset(&mut self) {
        self.current = Syllable::default();
        self.history.clear();
    }

    /// Undo the last jamo. Returns false when nothing was composing.
    pub fn backspace(&mut self) -> bool {
        if self.current.is_empty() {
            return false;
        }
        self.current = self.history.pop().unwrap_or_default();
        true
    }

    /// Feed one compatibility jamo. Returns syllables completed by this input.
    /// Non-jamo characters must not be fed; flush and handle them upstream.
    pub fn feed(&mut self, jamo: char) -> Vec<char> {
        let mut done = Vec::new();
        if jung_index(jamo).is_some() {
            self.feed_vowel(jamo, &mut done);
        } else if cho_index(jamo).is_some() || jong_index(jamo).is_some() {
            self.feed_consonant(jamo, &mut done);
        }
        done
    }

    fn push(&mut self, next: Syllable) {
        self.history.push(self.current);
        self.current = next;
    }

    fn start_new(&mut self, next: Syllable, done: &mut Vec<char>) {
        if let Some(c) = self.flush() {
            done.push(c);
        }
        self.history.push(Syllable::default());
        self.current = next;
    }

    fn feed_vowel(&mut self, v: char, done: &mut Vec<char>) {
        let vi = jung_index(v).unwrap();
        let cur = self.current;
        if let (Some(_), Some(_), Some(t)) = (cur.cho, cur.jung, cur.jong) {
            // The final consonant (or the second half of a double final)
            // becomes the initial of a new syllable: 닭 + ㅏ = 달 + 가.
            let jc = JONG[t as usize];
            let (keep, moved) = match split_jong(jc) {
                Some((a, b)) => (jong_index(a), b),
                None => (None, jc),
            };
            done.push(compose(cur.cho.unwrap(), cur.jung.unwrap(), keep.unwrap_or(0)));
            let moved_cho = cho_index(moved).unwrap();
            self.history.clear();
            self.history.push(Syllable::default());
            self.history.push(Syllable { cho: Some(moved_cho), ..Default::default() });
            self.current = Syllable { cho: Some(moved_cho), jung: Some(vi), jong: None };
            return;
        }
        match (cur.cho, cur.jung) {
            (Some(_), None) if cur.jong.is_none() => {
                self.push(Syllable { jung: Some(vi), ..cur });
            }
            (_, Some(j)) => {
                if let Some(c) = combine_vowel(JUNG[j as usize], v) {
                    self.push(Syllable { jung: jung_index(c), ..cur });
                } else {
                    self.start_new(Syllable { jung: Some(vi), ..Default::default() }, done);
                }
            }
            _ => {
                if cur.is_empty() {
                    self.push(Syllable { jung: Some(vi), ..Default::default() });
                } else {
                    self.start_new(Syllable { jung: Some(vi), ..Default::default() }, done);
                }
            }
        }
    }

    fn feed_consonant(&mut self, c: char, done: &mut Vec<char>) {
        let cur = self.current;
        let as_cho = cho_index(c);
        let fresh = |done: &mut Vec<char>, me: &mut Self| match as_cho {
            Some(l) => me.start_new(Syllable { cho: Some(l), ..Default::default() }, done),
            // A double final typed on its own (not producible on dubeolsik).
            None => {
                if let Some(ch) = me.flush() {
                    done.push(ch);
                }
                done.push(c);
            }
        };
        if cur.is_empty() {
            match as_cho {
                Some(l) => self.push(Syllable { cho: Some(l), ..Default::default() }),
                None => done.push(c),
            }
            return;
        }
        match (cur.cho, cur.jung, cur.jong) {
            (Some(_), Some(_), None) => match jong_index(c) {
                Some(t) => self.push(Syllable { jong: Some(t), ..cur }),
                // ㄸ ㅃ ㅉ cannot be finals.
                None => fresh(done, self),
            },
            (Some(_), Some(_), Some(t)) => match combine_jong(JONG[t as usize], c) {
                Some(d) => self.push(Syllable { jong: jong_index(d), ..cur }),
                None => fresh(done, self),
            },
            // Consonant after a lone consonant or a lone vowel starts anew.
            _ => fresh(done, self),
        }
    }
}

/// Compose a whole jamo string (test and tooling helper).
pub fn compose_str(jamo: &str) -> String {
    let mut c = Composer::new();
    let mut out = String::new();
    for ch in jamo.chars() {
        if jung_index(ch).is_some() || cho_index(ch).is_some() || jong_index(ch).is_some() {
            out.extend(c.feed(ch));
        } else {
            out.extend(c.flush());
            out.push(ch);
        }
    }
    out.extend(c.flush());
    out
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::layout::Layout;

    fn keys(s: &str) -> String {
        let l = Layout::Dubeolsik;
        let jamo: String = s.chars().map(|k| l.map(k).unwrap_or(k)).collect();
        compose_str(&jamo)
    }

    #[test]
    fn basic_words() {
        assert_eq!(keys("dkssudgktpdy"), "안녕하세요");
        assert_eq!(keys("gksrmf"), "한글");
        assert_eq!(keys("rnfmadnlfmf"), "구름위를");
        assert_eq!(keys("dkqjwlrkqkddpemfdjrktlsek"), "아버지가방에들어가신다");
    }

    #[test]
    fn final_moves_to_next_syllable() {
        assert_eq!(compose_str("ㄷㅏㄺㅏ"), "달가");
        assert_eq!(compose_str("ㄱㅏㄱㅏ"), "가가");
        assert_eq!(compose_str("ㄱㅏㅂㅅㅣ"), "갑시");
        assert_eq!(compose_str("ㄷㅏㄹㄱ"), "닭");
    }

    #[test]
    fn double_vowels_and_finals() {
        assert_eq!(keys("ghkrdls"), "확인");
        assert_eq!(keys("ghkrls"), "화긴");
        assert_eq!(keys("dnjsgo"), "원해");
        assert_eq!(keys("dmlwk"), "의자");
        assert_eq!(keys("dlfr"), "읽");
        assert_eq!(keys("tkfa"), "삶");
        assert_eq!(keys("djqtek"), "없다");
    }

    #[test]
    fn tense_consonants_and_lone_jamo() {
        assert_eq!(keys("Tkd"), "쌍");
        assert_eq!(keys("dkEo"), "아때");
        assert_eq!(keys("zzz"), "ㅋㅋㅋ");
        assert_eq!(keys("hk"), "ㅘ");
        assert_eq!(keys("rt"), "ㄱㅅ");
        // ㄸ cannot be a final, so it starts a new syllable.
        assert_eq!(keys("rkE"), "가ㄸ");
    }

    #[test]
    fn backspace_walks_jamo() {
        let mut c = Composer::new();
        for j in ['ㄷ', 'ㅏ', 'ㄹ', 'ㄱ'] {
            assert!(c.feed(j).is_empty());
        }
        assert_eq!(c.preedit(), Some('닭'));
        assert!(c.backspace());
        assert_eq!(c.preedit(), Some('달'));
        assert!(c.backspace());
        assert_eq!(c.preedit(), Some('다'));
        assert!(c.backspace());
        assert_eq!(c.preedit(), Some('ㄷ'));
        assert!(c.backspace());
        assert_eq!(c.preedit(), None);
        assert!(!c.backspace());
    }

    #[test]
    fn backspace_after_moved_final() {
        let mut c = Composer::new();
        let mut done = String::new();
        for j in ['ㄷ', 'ㅏ', 'ㄹ', 'ㄱ', 'ㅏ'] {
            done.extend(c.feed(j));
        }
        assert_eq!(done, "달");
        assert_eq!(c.preedit(), Some('가'));
        c.backspace();
        assert_eq!(c.preedit(), Some('ㄱ'));
        c.backspace();
        assert_eq!(c.preedit(), None);
    }

    #[test]
    fn backspace_compound_vowel() {
        let mut c = Composer::new();
        for j in ['ㄱ', 'ㅗ', 'ㅏ'] {
            c.feed(j);
        }
        assert_eq!(c.preedit(), Some('과'));
        c.backspace();
        assert_eq!(c.preedit(), Some('고'));
    }
}
