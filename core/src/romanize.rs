//! Romanization of Hangul: Revised Romanization (2000), McCune–Reischauer
//! (South Korean usage) and Yale (Martin's linguistic system).
//!
//! RR and MR transcribe pronunciation, so words first go through a model of
//! the standard pronunciation rules (표준 발음법): liaison including clusters,
//! ㅎ deletion and aspiration, palatalization, coda neutralization and cluster
//! simplification, nasalization, nasalization of ㄹ and lateralization.
//! Rules that depend on word structure (ㄴ insertion, tensification after
//! adnominal endings, noun/verb aspiration exceptions) are not modelled.
//! Yale is morphophonemic and follows the spelling.

use crate::jamo::{decompose, CHO, JONG, JUNG};

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum System {
    Revised,
    McCuneReischauer,
    Yale,
}

impl System {
    pub const ALL: [System; 3] = [System::Revised, System::McCuneReischauer, System::Yale];

    pub fn label(self) -> &'static str {
        match self {
            System::Revised => "로마자 2000",
            System::McCuneReischauer => "매큔라이샤워",
            System::Yale => "예일",
        }
    }
}

/// A syllable as compatibility jamo; `ini == None` is the silent ㅇ.
#[derive(Clone, Debug, PartialEq, Eq)]
struct Syl {
    ini: Option<char>,
    vow: char,
    fin: Vec<char>,
}

fn split_final(t: char) -> Vec<char> {
    match t {
        'ㄳ' => vec!['ㄱ', 'ㅅ'],
        'ㄵ' => vec!['ㄴ', 'ㅈ'],
        'ㄶ' => vec!['ㄴ', 'ㅎ'],
        'ㄺ' => vec!['ㄹ', 'ㄱ'],
        'ㄻ' => vec!['ㄹ', 'ㅁ'],
        'ㄼ' => vec!['ㄹ', 'ㅂ'],
        'ㄽ' => vec!['ㄹ', 'ㅅ'],
        'ㄾ' => vec!['ㄹ', 'ㅌ'],
        'ㄿ' => vec!['ㄹ', 'ㅍ'],
        'ㅀ' => vec!['ㄹ', 'ㅎ'],
        'ㅄ' => vec!['ㅂ', 'ㅅ'],
        c => vec![c],
    }
}

fn to_syl(c: char) -> Option<Syl> {
    let (l, v, t) = decompose(c)?;
    let ini = CHO[l as usize];
    Some(Syl {
        ini: if ini == 'ㅇ' { None } else { Some(ini) },
        vow: JUNG[v as usize],
        fin: if t == 0 { Vec::new() } else { split_final(JONG[t as usize]) },
    })
}

fn aspirate(c: char) -> char {
    match c {
        'ㄱ' | 'ㄲ' | 'ㅋ' => 'ㅋ',
        'ㄷ' | 'ㅅ' | 'ㅆ' | 'ㅌ' => 'ㅌ',
        'ㅂ' | 'ㅍ' => 'ㅍ',
        'ㅈ' | 'ㅊ' => 'ㅊ',
        c => c,
    }
}

fn is_obstruent(c: char) -> bool {
    matches!(c, 'ㄱ' | 'ㄲ' | 'ㅋ' | 'ㄷ' | 'ㅅ' | 'ㅆ' | 'ㅈ' | 'ㅊ' | 'ㅌ' | 'ㅂ' | 'ㅍ')
}

/// Reduce a coda before a consonant or at the end of a word.
fn close_coda(fin: &mut Vec<char>, next: Option<char>) {
    if fin.len() == 2 {
        let keep = match (fin[0], fin[1]) {
            ('ㄹ', 'ㄱ') if next == Some('ㄱ') => 'ㄹ',
            ('ㄹ', 'ㄱ') => 'ㄱ',
            ('ㄹ', 'ㅁ') => 'ㅁ',
            ('ㄹ', 'ㅍ') => 'ㅂ',
            ('ㄹ', _) => 'ㄹ',
            (a, _) => a, // ㄳ ㄵ ㄶ ㅄ keep the first consonant
        };
        *fin = vec![keep];
    }
    if let Some(c) = fin.first_mut() {
        *c = match *c {
            'ㄲ' | 'ㅋ' => 'ㄱ',
            'ㅅ' | 'ㅆ' | 'ㅈ' | 'ㅊ' | 'ㅌ' | 'ㅎ' => 'ㄷ',
            'ㅍ' => 'ㅂ',
            c => c,
        };
    }
}

/// Standard pronunciation of one run of Hangul syllables.
fn pronounce(word: &[Syl]) -> Vec<Syl> {
    let mut s = word.to_vec();
    for i in 0..s.len() {
        let last = i + 1 == s.len();
        if last {
            let mut fin = std::mem::take(&mut s[i].fin);
            close_coda(&mut fin, None);
            s[i].fin = fin;
            break;
        }
        let (left, right) = s.split_at_mut(i + 1);
        let a = &mut left[i].fin;
        let b = &mut right[0];

        // ㅎ in the coda.
        if a.last() == Some(&'ㅎ') {
            match b.ini {
                None => {
                    a.pop();
                }
                Some(c @ ('ㄱ' | 'ㄷ' | 'ㅈ')) => {
                    a.pop();
                    b.ini = Some(aspirate(c));
                }
                Some('ㅅ') => {
                    a.pop();
                    b.ini = Some('ㅆ');
                }
                Some('ㄴ') => {
                    a.pop();
                    if a.is_empty() {
                        a.push('ㄴ');
                    }
                }
                _ => {
                    a.pop();
                    if a.is_empty() {
                        a.push('ㄷ');
                    }
                }
            }
        }
        // Obstruent + ㅎ -> aspirate (축하 추카, 밝히다 발키다).
        let mut from_d = false;
        if b.ini == Some('ㅎ') {
            if let Some(&c) = a.last() {
                if is_obstruent(c) {
                    a.pop();
                    let asp = aspirate(match c {
                        'ㅅ' | 'ㅆ' | 'ㅈ' | 'ㅊ' | 'ㅌ' => 'ㄷ',
                        c => c,
                    });
                    from_d = asp == 'ㅌ';
                    b.ini = Some(asp);
                }
            }
        }
        // Palatalization (굳이 구지, 같이 가치, 닫히다 다치다).
        if b.vow == 'ㅣ' {
            if b.ini.is_none() {
                match a.last() {
                    Some('ㄷ') => {
                        a.pop();
                        b.ini = Some('ㅈ');
                    }
                    Some('ㅌ') => {
                        a.pop();
                        b.ini = Some('ㅊ');
                    }
                    _ => {}
                }
            } else if from_d && b.ini == Some('ㅌ') {
                b.ini = Some('ㅊ');
            }
        }
        // Liaison: the (last) coda consonant moves to an empty onset.
        if b.ini.is_none() && !a.is_empty() && a.last() != Some(&'ㅇ') {
            let mut c = a.pop().unwrap();
            if c == 'ㅅ' && !a.is_empty() {
                c = 'ㅆ'; // 값이 갑씨, 넋이 넉씨
            }
            b.ini = Some(c);
        }
        let next = b.ini;
        close_coda(a, next);
        let Some(n) = b.ini else { continue };
        let Some(&f) = a.first() else { continue };
        let mut f = f;
        let mut n = n;
        // ㄹ after a coda other than ㄹ becomes ㄴ (종로 종노, 독립 동닙).
        if n == 'ㄹ' && matches!(f, 'ㅁ' | 'ㅇ' | 'ㄱ' | 'ㄷ' | 'ㅂ') {
            n = 'ㄴ';
        }
        // Nasalization of obstruent codas (국물 궁물, 밥만 밤만).
        if matches!(n, 'ㄴ' | 'ㅁ') {
            f = match f {
                'ㄱ' => 'ㅇ',
                'ㄷ' => 'ㄴ',
                'ㅂ' => 'ㅁ',
                f => f,
            };
        }
        // Lateralization (신라 실라, 설날 설랄).
        if f == 'ㄴ' && n == 'ㄹ' {
            f = 'ㄹ';
        } else if f == 'ㄹ' && n == 'ㄴ' {
            n = 'ㄹ';
        }
        a[0] = f;
        b.ini = Some(n);
    }
    s
}

fn vowel_rr(v: char) -> &'static str {
    match v {
        'ㅏ' => "a",
        'ㅐ' => "ae",
        'ㅑ' => "ya",
        'ㅒ' => "yae",
        'ㅓ' => "eo",
        'ㅔ' => "e",
        'ㅕ' => "yeo",
        'ㅖ' => "ye",
        'ㅗ' => "o",
        'ㅘ' => "wa",
        'ㅙ' => "wae",
        'ㅚ' => "oe",
        'ㅛ' => "yo",
        'ㅜ' => "u",
        'ㅝ' => "wo",
        'ㅞ' => "we",
        'ㅟ' => "wi",
        'ㅠ' => "yu",
        'ㅡ' => "eu",
        'ㅢ' => "ui",
        _ => "i",
    }
}

fn vowel_mr(v: char) -> &'static str {
    match v {
        'ㅓ' => "ŏ",
        'ㅕ' => "yŏ",
        'ㅝ' => "wŏ",
        'ㅡ' => "ŭ",
        'ㅢ' => "ŭi",
        v => vowel_rr(v),
    }
}

fn coda_roman(c: char) -> &'static str {
    match c {
        'ㄱ' => "k",
        'ㄴ' => "n",
        'ㄷ' => "t",
        'ㄹ' => "l",
        'ㅁ' => "m",
        'ㅂ' => "p",
        _ => "ng",
    }
}

fn rr_word(p: &[Syl], out: &mut String) {
    for (i, s) in p.iter().enumerate() {
        let prev_l = i > 0 && p[i - 1].fin.first() == Some(&'ㄹ');
        if let Some(c) = s.ini {
            out.push_str(match c {
                'ㄱ' => "g",
                'ㄲ' => "kk",
                'ㄴ' => "n",
                'ㄷ' => "d",
                'ㄸ' => "tt",
                'ㄹ' if prev_l => "l",
                'ㄹ' => "r",
                'ㅁ' => "m",
                'ㅂ' => "b",
                'ㅃ' => "pp",
                'ㅅ' => "s",
                'ㅆ' => "ss",
                'ㅈ' => "j",
                'ㅉ' => "jj",
                'ㅊ' => "ch",
                'ㅋ' => "k",
                'ㅌ' => "t",
                'ㅍ' => "p",
                _ => "h",
            });
        }
        out.push_str(vowel_rr(s.vow));
        if let Some(&f) = s.fin.first() {
            out.push_str(coda_roman(f));
        }
    }
}

fn mr_word(p: &[Syl], out: &mut String) {
    for (i, s) in p.iter().enumerate() {
        let prev = if i > 0 { Some(&p[i - 1]) } else { None };
        let prev_fin = prev.and_then(|x| x.fin.first().copied());
        // Plain stops are voiced after a vowel or a sonorant coda.
        let voiced = prev.is_some() && matches!(prev_fin, None | Some('ㄴ' | 'ㄹ' | 'ㅁ' | 'ㅇ'));
        if let Some(c) = s.ini {
            if c == 'ㄱ' && prev_fin == Some('ㄴ') {
                out.push('\''); // han'guk, not hanguk (ㅇ+ㄱ)
            }
            out.push_str(match c {
                'ㄱ' if voiced => "g",
                'ㄱ' => "k",
                'ㄷ' if voiced => "d",
                'ㄷ' => "t",
                'ㅂ' if voiced => "b",
                'ㅂ' => "p",
                'ㅈ' if voiced => "j",
                'ㅈ' => "ch",
                'ㄲ' => "kk",
                'ㄸ' => "tt",
                'ㅃ' => "pp",
                'ㅆ' => "ss",
                'ㅉ' => "tch",
                'ㅊ' => "ch'",
                'ㅋ' => "k'",
                'ㅌ' => "t'",
                'ㅍ' => "p'",
                'ㅅ' if s.vow == 'ㅟ' => "sh",
                'ㅅ' => "s",
                'ㄴ' => "n",
                'ㅁ' => "m",
                'ㄹ' if prev_fin == Some('ㄹ') => "l",
                'ㄹ' => "r",
                _ => "h",
            });
        }
        let after_a_o = s.ini.is_none()
            && prev.is_some_and(|x| x.fin.is_empty() && matches!(x.vow, 'ㅏ' | 'ㅗ'));
        if s.vow == 'ㅔ' && after_a_o {
            out.push('ë');
        } else {
            out.push_str(vowel_mr(s.vow));
        }
        if let Some(&f) = s.fin.first() {
            out.push_str(coda_roman(f));
        }
    }
}

fn yale_initial(c: char) -> &'static str {
    match c {
        'ㄱ' => "k",
        'ㄲ' => "kk",
        'ㄴ' => "n",
        'ㄷ' => "t",
        'ㄸ' => "tt",
        'ㄹ' => "l",
        'ㅁ' => "m",
        'ㅂ' => "p",
        'ㅃ' => "pp",
        'ㅅ' => "s",
        'ㅆ' => "ss",
        'ㅈ' => "c",
        'ㅉ' => "cc",
        'ㅊ' => "ch",
        'ㅋ' => "kh",
        'ㅌ' => "th",
        'ㅍ' => "ph",
        'ㅎ' => "h",
        _ => "ng",
    }
}

fn yale_vowel(v: char, ini: Option<char>) -> &'static str {
    match v {
        'ㅏ' => "a",
        'ㅐ' => "ay",
        'ㅑ' => "ya",
        'ㅒ' => "yay",
        'ㅓ' => "e",
        'ㅔ' => "ey",
        'ㅕ' => "ye",
        'ㅖ' => "yey",
        'ㅗ' => "o",
        'ㅘ' => "wa",
        'ㅙ' => "way",
        'ㅚ' => "oy",
        'ㅛ' => "yo",
        // ㅡ does not follow labials, so ㅜ is written u after them.
        'ㅜ' if matches!(ini, Some('ㅁ' | 'ㅂ' | 'ㅃ' | 'ㅍ')) => "u",
        'ㅜ' => "wu",
        'ㅝ' => "we",
        'ㅞ' => "wey",
        'ㅟ' => "wi",
        'ㅠ' => "yu",
        'ㅡ' => "u",
        'ㅢ' => "uy",
        _ => "i",
    }
}

fn yale_word(w: &[Syl], out: &mut String) {
    let mut prev_coda = String::new();
    for s in w {
        let onset = s.ini.map(yale_initial).unwrap_or("");
        // Mark the syllable boundary where the letters could be regrouped:
        // a coda before a vowel (늙은 nulk.un) or a coda + onset that reads
        // as one consonant (박하 pak.ha, 학교 hak.kyo).
        if !prev_coda.is_empty() {
            let last = prev_coda.chars().last().unwrap();
            let first = onset.chars().next();
            let ambiguous = match first {
                None => true,
                Some('h') => matches!(last, 'k' | 't' | 'p' | 'c'),
                Some(f) => f == last && matches!(f, 'k' | 't' | 'p' | 'c' | 's'),
            };
            if ambiguous {
                out.push('.');
            }
        }
        out.push_str(onset);
        out.push_str(yale_vowel(s.vow, s.ini));
        prev_coda.clear();
        for c in &s.fin {
            prev_coda.push_str(yale_initial(*c));
        }
        out.push_str(&prev_coda);
    }
}

/// Romanize `text`: Hangul syllables are transcribed, everything else is kept.
pub fn romanize(text: &str, system: System) -> String {
    let mut out = String::with_capacity(text.len() * 2);
    let mut run: Vec<Syl> = Vec::new();
    let flush = |run: &mut Vec<Syl>, out: &mut String| {
        if run.is_empty() {
            return;
        }
        match system {
            System::Revised => rr_word(&pronounce(run), out),
            System::McCuneReischauer => mr_word(&pronounce(run), out),
            System::Yale => yale_word(run, out),
        }
        run.clear();
    };
    for c in text.chars() {
        match to_syl(c) {
            Some(s) => run.push(s),
            None => {
                flush(&mut run, &mut out);
                out.push(c);
            }
        }
    }
    flush(&mut run, &mut out);
    out
}

#[cfg(test)]
mod tests {
    use super::*;

    fn check(system: System, cases: &[(&str, &str)]) {
        for (hangul, want) in cases {
            assert_eq!(romanize(hangul, system), *want, "{system:?} {hangul}");
        }
    }

    #[test]
    fn revised_romanization() {
        check(
            System::Revised,
            &[
                ("안녕하세요", "annyeonghaseyo"),
                ("한국", "hanguk"),
                ("부산", "busan"),
                ("서울", "seoul"),
                ("김치", "gimchi"),
                ("학교", "hakgyo"),
                ("한글", "hangeul"),
                ("신라", "silla"),
                ("종로", "jongno"),
                ("독립문", "dongnimmun"),
                ("왕십리", "wangsimni"),
                ("설날", "seollal"),
                ("백마", "baengma"),
                ("국물", "gungmul"),
                ("같이", "gachi"),
                ("굳이", "guji"),
                ("좋다", "jota"),
                ("좋아", "joa"),
                ("않아", "ana"),
                ("닫히다", "dachida"),
                ("밝히다", "balkida"),
                ("값이", "gapssi"),
                ("읽다", "ikda"),
                ("맑게", "malge"),
                ("의사", "uisa"),
                ("학교에 간다", "hakgyoe ganda"),
            ],
        );
    }

    #[test]
    fn mccune_reischauer() {
        check(
            System::McCuneReischauer,
            &[
                ("안녕하세요", "annyŏnghaseyo"),
                ("한국", "han'guk"),
                ("대한민국", "taehanmin'guk"),
                ("한글", "han'gŭl"),
                ("부산", "pusan"),
                ("대구", "taegu"),
                ("서울", "sŏul"),
                ("김치", "kimch'i"),
                ("학교", "hakkyo"),
                ("독립문", "tongnimmun"),
                ("신라", "silla"),
                ("종로", "chongno"),
                ("같이", "kach'i"),
                ("좋다", "chot'a"),
                ("설날", "sŏllal"),
                ("경상북도", "kyŏngsangbukto"),
                ("쉬다", "shwida"),
                ("가에", "kaë"),
            ],
        );
    }

    #[test]
    fn yale() {
        check(
            System::Yale,
            &[
                ("한글", "hankul"),
                ("서울", "sewul"),
                ("부산", "pusan"),
                ("김치", "kimchi"),
                ("늙은", "nulk.un"),
                ("같이", "kath.i"),
                ("안녕하세요", "annyenghaseyyo"),
                ("학교", "hak.kyo"),
                ("박하", "pak.ha"),
                ("꽃", "kkoch"),
                ("의사", "uysa"),
                ("값", "kaps"),
            ],
        );
    }

    #[test]
    fn non_hangul_is_kept() {
        assert_eq!(romanize("3개", System::Revised), "3gae");
        assert_eq!(romanize("abc", System::Yale), "abc");
    }
}
