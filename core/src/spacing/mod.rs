//! Spacing: the light in-process model plus text-level handling shared by
//! every backend (manual spaces, punctuation, protected non-Korean text).

pub mod model;
pub mod morph;

use crate::jamo::is_hangul_letter;
pub use model::NgramModel;

/// Characters the model sees. Everything else is copied through verbatim.
fn is_prose(c: char) -> bool {
    is_hangul_letter(c) || c.is_ascii_digit()
}

/// Punctuation after which a following Korean word starts a new eojeol.
fn ends_clause(c: char) -> bool {
    matches!(c, '.' | ',' | '?' | '!' | '…' | '。' | '、' | '？' | '！' | '，')
}

/// Space `text` with `space_run` applied to each run of Korean letters and
/// digits. Existing spaces are kept, other characters are never altered and
/// a space is added after clause punctuation that is followed by Korean.
pub fn space_text(text: &str, mut space_run: impl FnMut(&str) -> String) -> String {
    let chars: Vec<char> = text.chars().collect();
    let mut out = String::with_capacity(text.len() + 16);
    let mut i = 0;
    while i < chars.len() {
        let c = chars[i];
        if is_prose(c) {
            let start = i;
            while i < chars.len() && is_prose(chars[i]) {
                i += 1;
            }
            let run: String = chars[start..i].iter().collect();
            let spaced = space_run(&run);
            out.push_str(if same_letters(&run, &spaced) { &spaced } else { &run });
            continue;
        }
        out.push(c);
        if ends_clause(c) {
            if let Some(&next) = chars.get(i + 1) {
                let prev_digit = i > 0 && chars[i - 1].is_ascii_digit();
                if is_hangul_letter(next) && !(prev_digit && c == ',') {
                    out.push(' ');
                }
            }
        }
        i += 1;
    }
    out
}

/// Insert the boundary after clause punctuation followed by Korean
/// (`간다.그리고` -> `간다. 그리고`) before a backend sees the text, so no
/// backend mistakes an unspaced sentence for a file name or identifier.
pub fn prepare(text: &str) -> String {
    let chars: Vec<char> = text.chars().collect();
    let mut out = String::with_capacity(text.len() + 8);
    for (i, &c) in chars.iter().enumerate() {
        out.push(c);
        if ends_clause(c) {
            if let Some(&next) = chars.get(i + 1) {
                let prev_digit = i > 0 && chars[i - 1].is_ascii_digit();
                if is_hangul_letter(next) && !(prev_digit && c == ',') {
                    out.push(' ');
                }
            }
        }
    }
    out
}

/// True when `b` differs from `a` only by ASCII spaces.
pub fn same_letters(a: &str, b: &str) -> bool {
    a.chars().filter(|&c| c != ' ').eq(b.chars().filter(|&c| c != ' '))
}

/// True when every space of `original` survives in `spaced`, so a backend
/// never removes a boundary the user typed on purpose.
pub fn keeps_spaces(original: &str, spaced: &str) -> bool {
    let cuts = |s: &str| {
        let mut pos = 0usize;
        let mut v = Vec::new();
        for c in s.chars() {
            if c == ' ' {
                v.push(pos);
            } else {
                pos += 1;
            }
        }
        v.dedup();
        v
    };
    let want = cuts(original);
    let got = cuts(spaced);
    want.iter().all(|p| got.binary_search(p).is_ok())
}

/// Accept a backend result only if it is a pure respacing of the input.
pub fn checked(original: &str, spaced: Option<String>) -> String {
    match spaced {
        Some(s) if same_letters(original, &s) && keeps_spaces(original, &s) => merge_spaces(original, &s),
        _ => original.to_string(),
    }
}

/// Spaces before each letter (and after the last): the user's own count, or
/// one space where only the backend put a boundary. Edges stay as typed.
fn merge_spaces(original: &str, spaced: &str) -> String {
    fn runs(s: &str) -> Vec<usize> {
        let mut v = vec![0usize];
        for c in s.chars() {
            if c == ' ' {
                *v.last_mut().unwrap() += 1;
            } else {
                v.push(0);
            }
        }
        v
    }
    let typed = runs(original);
    let got = runs(spaced);
    let letters: Vec<char> = original.chars().filter(|&c| c != ' ').collect();
    let mut out = String::with_capacity(spaced.len());
    for (i, c) in letters.iter().enumerate() {
        let n = if i == 0 { typed[0] } else { typed[i].max(got[i].min(1)) };
        out.extend(std::iter::repeat(' ').take(n));
        out.push(*c);
    }
    out.extend(std::iter::repeat(' ').take(*typed.last().unwrap()));
    out
}

/// Light engine: the n-gram model applied through `space_text`.
pub struct LightSpacer {
    pub model: NgramModel,
}

impl LightSpacer {
    pub fn new(model: NgramModel) -> Self {
        LightSpacer { model }
    }

    pub fn space(&self, text: &str) -> String {
        let spaced = space_text(text, |run| self.model.space_run(run));
        checked(text, Some(spaced))
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn fake(run: &str) -> String {
        // Space after every 는 / 에 for predictable tests.
        let mut out = String::new();
        let chars: Vec<char> = run.chars().collect();
        for (i, c) in chars.iter().enumerate() {
            out.push(*c);
            if (*c == '는' || *c == '에') && i + 1 < chars.len() {
                out.push(' ');
            }
        }
        out
    }

    #[test]
    fn runs_and_punctuation() {
        assert_eq!(space_text("나는학교에간다", fake), "나는 학교에 간다");
        assert_eq!(space_text("나는학교에간다.그는집에", fake), "나는 학교에 간다. 그는 집에");
        assert_eq!(space_text("3.14는", fake), "3.14는");
        assert_eq!(space_text("1,000원에", fake), "1,000원에");
        assert_eq!(space_text("\"안녕\"이라고", fake), "\"안녕\"이라고");
        assert_eq!(space_text("나는 학교에", fake), "나는 학교에");
    }

    #[test]
    fn prepare_splits_clauses() {
        assert_eq!(prepare("간다.그리고3개"), "간다. 그리고3개");
        assert_eq!(prepare("3.14배, 1,000원"), "3.14배, 1,000원");
        assert_eq!(prepare("왜?정말"), "왜? 정말");
        assert_eq!(prepare("a.b"), "a.b");
    }

    #[test]
    fn checks() {
        assert!(same_letters("나는학교", "나는 학교"));
        assert!(!same_letters("나는학교", "나는 학 고"));
        assert!(keeps_spaces("하늘 공활한데", "하늘 공 활한데"));
        assert!(!keeps_spaces("하늘 공활한데", "하늘공활한데"));
        assert_eq!(checked("가나", Some("가 다".into())), "가나");
        assert_eq!(checked("가나", Some("가  나 ".into())), "가 나");
        assert_eq!(checked("가  나다", Some("가  나 다".into())), "가  나 다");
        assert_eq!(checked("가나", None), "가나");
    }
}
