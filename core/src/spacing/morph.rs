//! Closed-class morphology used by the light spacing model: particle and
//! ending suffixes, dependent-noun prefixes and word plausibility.
//! Mirrors the reference Python implementation so trained models stay valid.

use crate::jamo::{final_of, without_final};

pub const JOSA: &[&str] = &[
    "이", "가", "을", "를", "은", "는", "의", "에", "도", "만", "와", "과", "로", "랑", "나", "께",
    "야", "에서", "에게", "한테", "께서", "에게서", "한테서", "으로", "으로서", "으로써", "로서",
    "로써", "이랑", "이나", "처럼", "보다", "까지", "부터", "조차", "마저", "마다", "밖에", "이며",
    "이라고", "라고", "이라는", "라는", "이든지", "든지", "이라도", "라도", "커녕", "은커녕",
    "는커녕", "마는", "이야", "이야말로", "야말로", "더러", "보고", "한테로",
];

pub const EOMI: &[&str] = &[
    "다", "까", "요", "죠", "지", "네", "군", "구나", "는구나", "더라", "더군", "니", "니까",
    "으니까", "으니", "면", "으면", "면서", "으면서", "고", "거나", "지만", "는데", "은데", "ㄴ데",
    "아서", "어서", "여서", "아도", "어도", "으며", "며", "도록", "든", "자", "자마자", "았다",
    "었다", "였다", "겠다", "았어", "었어", "았지", "었지", "ㄴ다", "는다", "한다", "ㅂ니다",
    "습니다", "ㅂ니까", "습니까", "았습니다", "었습니다", "으세요", "세요", "으십시오", "십시오",
    "아요", "어요", "여요", "에요", "예요", "이에요", "았어요", "었어요", "나요", "지요", "네요",
    "군요", "으려고", "려고", "으러", "러", "기", "음", "ㅁ", "래", "대", "든가", "잖아", "거든",
    "더라고", "더라구",
];

pub const UIJON: &[&str] = &[
    "것", "거", "걸", "게", "수", "줄", "바", "데", "때", "적", "만큼", "대로", "뿐", "채", "척",
    "체", "양", "등", "들", "따위", "나름", "김", "통", "차", "판", "셈", "리", "겸", "나위",
    "무렵", "즈음", "따름", "녘", "법", "만", "뻔", "축", "둥", "품", "길", "측", "분", "명",
    "개", "마리", "권", "장", "대", "번", "살", "그루", "송이", "켤레", "벌", "잔", "그릇", "병",
    "캔", "회", "차례", "가지", "종류", "쪽", "군데", "평", "곳", "달", "년", "월", "일",
];

/// Homographs of dependent nouns and endings; left to statistics.
const AMBIG_END: &[char] = &['걸', '게', '데', '지', '대', '래'];

fn max_len(v: &[&str]) -> usize {
    v.iter().map(|s| s.chars().count()).max().unwrap_or(0)
}

fn contains(v: &[&str], s: &[char]) -> bool {
    v.iter().any(|w| w.chars().eq(s.iter().copied()))
}

/// Longest suffix of `text[..i]` found in `vocab`.
pub fn suffix_in<'a>(text: &'a [char], i: usize, vocab: &[&str]) -> Option<&'a [char]> {
    let top = max_len(vocab).min(i);
    (1..=top).rev().map(|l| &text[i - l..i]).find(|s| contains(vocab, s))
}

/// Longest prefix of `text[i..]` found in `vocab`.
pub fn prefix_in<'a>(text: &'a [char], i: usize, vocab: &[&str]) -> Option<&'a [char]> {
    let top = max_len(vocab).min(text.len() - i);
    (1..=top).rev().map(|l| &text[i..i + l]).find(|s| contains(vocab, s))
}

pub fn is_adnominal_end(c: char) -> bool {
    c == '는' || c == '던' || matches!(final_of(c), Some('ㄴ') | Some('ㄹ'))
}

/// Morphological gap features of boundary `i` (between `text[i-1]` and `text[i]`).
/// Each feature is (family, value).
pub fn gap_features(text: &[char], i: usize, out: &mut Vec<(u8, String)>) {
    use super::model::family;
    if suffix_in(text, i, JOSA).is_some() {
        out.push((family::JL, "1".into()));
    }
    if suffix_in(text, i, EOMI).is_some() {
        out.push((family::EL, "1".into()));
    }
    if let Some(u) = prefix_in(text, i, UIJON) {
        out.push((family::UR, u.iter().collect()));
        if is_adnominal_end(text[i - 1]) {
            out.push((family::ADNU, "1".into()));
        }
    }
}

/// Word plausibility: 0 for analysable words, a per-syllable penalty otherwise.
pub fn token_score(w: &[char], is_noun: impl Fn(&[char]) -> bool, is_stem: impl Fn(&[char]) -> bool) -> f32 {
    let n = w.len();
    if n == 0 {
        return 0.0;
    }
    if is_noun(w) {
        return 0.0;
    }
    if let Some(j) = suffix_in(w, n, JOSA) {
        if n > j.len() && is_noun(&w[..n - j.len()]) {
            return 0.0;
        }
    }
    if let Some(e) = suffix_in(w, n, EOMI) {
        if n > e.len() && is_stem(&w[..n - e.len()]) {
            return 0.0;
        }
    }
    if let (Some(coda), Some(bare)) = (final_of(w[n - 1]), without_final(w[n - 1])) {
        if matches!(coda, 'ㄴ' | 'ㄹ' | 'ㅁ') {
            let mut cand = w[..n - 1].to_vec();
            cand.push(bare);
            if is_stem(&cand) {
                return 0.0;
            }
        }
    }
    if let Some(u) = prefix_in(w, 0, UIJON) {
        let rest = &w[u.len()..];
        if rest.is_empty() || contains(JOSA, rest) {
            return 0.0;
        }
    }
    if n >= 2 && AMBIG_END.contains(&w[n - 1]) {
        return 0.0;
    }
    -(if n >= 2 { n as f32 } else { 0.5 })
}

#[cfg(test)]
mod tests {
    use super::*;

    fn chars(s: &str) -> Vec<char> {
        s.chars().collect()
    }

    #[test]
    fn affixes() {
        let t = chars("학교에서");
        assert_eq!(suffix_in(&t, 4, JOSA).map(|s| s.iter().collect::<String>()), Some("에서".into()));
        let t = chars("갈수있다");
        assert_eq!(prefix_in(&t, 1, UIJON).map(|s| s.iter().collect::<String>()), Some("수".into()));
        assert!(is_adnominal_end('갈'));
        assert!(is_adnominal_end('는'));
        assert!(!is_adnominal_end('가'));
    }

    #[test]
    fn plausibility() {
        let nouns = [chars("학교")];
        let stems = [chars("가")];
        let is_noun = |w: &[char]| nouns.iter().any(|n| n == w);
        let is_stem = |w: &[char]| stems.iter().any(|n| n == w);
        assert_eq!(token_score(&chars("학교에"), is_noun, is_stem), 0.0);
        assert_eq!(token_score(&chars("갈"), is_noun, is_stem), 0.0);
        assert!(token_score(&chars("학교가수"), is_noun, is_stem) < 0.0);
        assert_eq!(token_score(&chars("올걸"), is_noun, is_stem), 0.0);
    }
}
