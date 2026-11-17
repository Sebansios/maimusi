//! Hangul syllable arithmetic and compatibility-jamo tables.
//!
//! Syllables U+AC00..U+D7A3 are `0xAC00 + (L * 21 + V) * 28 + T`.
//! Keyboards produce compatibility jamo (U+3131..U+3163); this module maps
//! them to L/V/T indices and knows the standard double-jamo combinations.

pub const S_BASE: u32 = 0xAC00;
pub const L_COUNT: u32 = 19;
pub const V_COUNT: u32 = 21;
pub const T_COUNT: u32 = 28;
pub const N_COUNT: u32 = V_COUNT * T_COUNT;
pub const S_COUNT: u32 = L_COUNT * N_COUNT;

/// Initial consonants in index order (compatibility jamo).
pub const CHO: [char; 19] = [
    'ㄱ', 'ㄲ', 'ㄴ', 'ㄷ', 'ㄸ', 'ㄹ', 'ㅁ', 'ㅂ', 'ㅃ', 'ㅅ', 'ㅆ', 'ㅇ', 'ㅈ', 'ㅉ', 'ㅊ', 'ㅋ',
    'ㅌ', 'ㅍ', 'ㅎ',
];

/// Medial vowels in index order.
pub const JUNG: [char; 21] = [
    'ㅏ', 'ㅐ', 'ㅑ', 'ㅒ', 'ㅓ', 'ㅔ', 'ㅕ', 'ㅖ', 'ㅗ', 'ㅘ', 'ㅙ', 'ㅚ', 'ㅛ', 'ㅜ', 'ㅝ', 'ㅞ',
    'ㅟ', 'ㅠ', 'ㅡ', 'ㅢ', 'ㅣ',
];

/// Final consonants; index 0 means "no final".
pub const JONG: [char; 28] = [
    '\0', 'ㄱ', 'ㄲ', 'ㄳ', 'ㄴ', 'ㄵ', 'ㄶ', 'ㄷ', 'ㄹ', 'ㄺ', 'ㄻ', 'ㄼ', 'ㄽ', 'ㄾ', 'ㄿ', 'ㅀ',
    'ㅁ', 'ㅂ', 'ㅄ', 'ㅅ', 'ㅆ', 'ㅇ', 'ㅈ', 'ㅊ', 'ㅋ', 'ㅌ', 'ㅍ', 'ㅎ',
];

const VOWEL_COMBINE: [(char, char, char); 7] = [
    ('ㅗ', 'ㅏ', 'ㅘ'),
    ('ㅗ', 'ㅐ', 'ㅙ'),
    ('ㅗ', 'ㅣ', 'ㅚ'),
    ('ㅜ', 'ㅓ', 'ㅝ'),
    ('ㅜ', 'ㅔ', 'ㅞ'),
    ('ㅜ', 'ㅣ', 'ㅟ'),
    ('ㅡ', 'ㅣ', 'ㅢ'),
];

const JONG_COMBINE: [(char, char, char); 11] = [
    ('ㄱ', 'ㅅ', 'ㄳ'),
    ('ㄴ', 'ㅈ', 'ㄵ'),
    ('ㄴ', 'ㅎ', 'ㄶ'),
    ('ㄹ', 'ㄱ', 'ㄺ'),
    ('ㄹ', 'ㅁ', 'ㄻ'),
    ('ㄹ', 'ㅂ', 'ㄼ'),
    ('ㄹ', 'ㅅ', 'ㄽ'),
    ('ㄹ', 'ㅌ', 'ㄾ'),
    ('ㄹ', 'ㅍ', 'ㄿ'),
    ('ㄹ', 'ㅎ', 'ㅀ'),
    ('ㅂ', 'ㅅ', 'ㅄ'),
];

pub fn cho_index(c: char) -> Option<u8> {
    CHO.iter().position(|&x| x == c).map(|i| i as u8)
}

pub fn jung_index(c: char) -> Option<u8> {
    JUNG.iter().position(|&x| x == c).map(|i| i as u8)
}

pub fn jong_index(c: char) -> Option<u8> {
    if c == '\0' {
        return None;
    }
    JONG.iter().position(|&x| x == c).map(|i| i as u8)
}

pub fn is_vowel(c: char) -> bool {
    jung_index(c).is_some()
}

pub fn is_consonant(c: char) -> bool {
    cho_index(c).is_some() || jong_index(c).is_some()
}

pub fn combine_vowel(a: char, b: char) -> Option<char> {
    VOWEL_COMBINE.iter().find(|&&(x, y, _)| x == a && y == b).map(|&(_, _, z)| z)
}

pub fn combine_jong(a: char, b: char) -> Option<char> {
    JONG_COMBINE.iter().find(|&&(x, y, _)| x == a && y == b).map(|&(_, _, z)| z)
}

/// Split a double final into (kept final, consonant moving to the next syllable).
pub fn split_jong(c: char) -> Option<(char, char)> {
    JONG_COMBINE.iter().find(|&&(_, _, z)| z == c).map(|&(x, y, _)| (x, y))
}

pub fn is_syllable(c: char) -> bool {
    let u = c as u32;
    (S_BASE..S_BASE + S_COUNT).contains(&u)
}

pub fn compose(cho: u8, jung: u8, jong: u8) -> char {
    let u = S_BASE + (cho as u32 * V_COUNT + jung as u32) * T_COUNT + jong as u32;
    char::from_u32(u).unwrap_or('\u{FFFD}')
}

/// (L, V, T) indices of a precomposed syllable.
pub fn decompose(c: char) -> Option<(u8, u8, u8)> {
    if !is_syllable(c) {
        return None;
    }
    let s = c as u32 - S_BASE;
    Some(((s / N_COUNT) as u8, ((s % N_COUNT) / T_COUNT) as u8, (s % T_COUNT) as u8))
}

/// Final consonant (compatibility jamo) of a syllable, if any.
pub fn final_of(c: char) -> Option<char> {
    decompose(c).and_then(|(_, _, t)| if t == 0 { None } else { Some(JONG[t as usize]) })
}

pub fn without_final(c: char) -> Option<char> {
    decompose(c).map(|(l, v, _)| compose(l, v, 0))
}

pub fn is_hangul_letter(c: char) -> bool {
    is_syllable(c) || ('\u{3131}'..='\u{318E}').contains(&c) || ('\u{1100}'..='\u{11FF}').contains(&c)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn roundtrip() {
        let g = compose(0, 0, 0);
        assert_eq!(g, '가');
        assert_eq!(decompose('값'), Some((0, 0, 18)));
        assert_eq!(compose(18, 20, 27), '힣');
        assert_eq!(final_of('닭'), Some('ㄺ'));
        assert_eq!(without_final('닭'), Some('다'));
    }

    #[test]
    fn combinations() {
        assert_eq!(combine_vowel('ㅗ', 'ㅏ'), Some('ㅘ'));
        assert_eq!(combine_vowel('ㅏ', 'ㅗ'), None);
        assert_eq!(combine_jong('ㄹ', 'ㄱ'), Some('ㄺ'));
        assert_eq!(split_jong('ㅄ'), Some(('ㅂ', 'ㅅ')));
        assert_eq!(jong_index('ㄸ'), None);
        assert_eq!(cho_index('ㄳ'), None);
    }
}
