//! Keyboard layouts: physical key (as the US-QWERTY character at that
//! position, Shift applied) to compatibility jamo.
//!
//! Only layouts whose behaviour is covered by tests are listed. Sebeolsik
//! variants need per-edition specifications and are not claimed yet.

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Layout {
    /// KS X 5002 standard two-set layout.
    Dubeolsik,
}

impl Layout {
    pub fn from_id(id: &str) -> Option<Layout> {
        match id {
            "2" | "dubeolsik" => Some(Layout::Dubeolsik),
            _ => None,
        }
    }

    pub fn id(self) -> &'static str {
        match self {
            Layout::Dubeolsik => "dubeolsik",
        }
    }

    /// Jamo for a key, or `None` when the key is not a letter key of this layout.
    pub fn map(self, key: char) -> Option<char> {
        match self {
            Layout::Dubeolsik => dubeolsik(key),
        }
    }
}

fn dubeolsik(key: char) -> Option<char> {
    let jamo = match key {
        'Q' => 'ㅃ',
        'W' => 'ㅉ',
        'E' => 'ㄸ',
        'R' => 'ㄲ',
        'T' => 'ㅆ',
        'O' => 'ㅒ',
        'P' => 'ㅖ',
        _ => match key.to_ascii_lowercase() {
            'q' => 'ㅂ',
            'w' => 'ㅈ',
            'e' => 'ㄷ',
            'r' => 'ㄱ',
            't' => 'ㅅ',
            'y' => 'ㅛ',
            'u' => 'ㅕ',
            'i' => 'ㅑ',
            'o' => 'ㅐ',
            'p' => 'ㅔ',
            'a' => 'ㅁ',
            's' => 'ㄴ',
            'd' => 'ㅇ',
            'f' => 'ㄹ',
            'g' => 'ㅎ',
            'h' => 'ㅗ',
            'j' => 'ㅓ',
            'k' => 'ㅏ',
            'l' => 'ㅣ',
            'z' => 'ㅋ',
            'x' => 'ㅌ',
            'c' => 'ㅊ',
            'v' => 'ㅍ',
            'b' => 'ㅠ',
            'n' => 'ㅜ',
            'm' => 'ㅡ',
            _ => return None,
        },
    };
    Some(jamo)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn dubeolsik_letters() {
        let l = Layout::Dubeolsik;
        assert_eq!(l.map('r'), Some('ㄱ'));
        assert_eq!(l.map('R'), Some('ㄲ'));
        assert_eq!(l.map('K'), Some('ㅏ'));
        assert_eq!(l.map('P'), Some('ㅖ'));
        assert_eq!(l.map('1'), None);
        assert_eq!(l.map('.'), None);
        let all: String = ('a'..='z').filter_map(|c| l.map(c)).collect();
        assert_eq!(all.chars().count(), 26);
    }
}
