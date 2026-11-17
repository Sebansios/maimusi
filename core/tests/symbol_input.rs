use hangul_core::{Backend, Key, Session};

struct Symbols;
impl Backend for Symbols {
    fn space(&mut self, s: &str) -> Option<String> { Some(s.into()) }
    fn candidates(&mut self, s: &str) -> Vec<(String,String)> {
        match s {
            "/" => vec![("·".into(), "기호·문자".into())],
            "(" => vec![("「".into(), "기호·문자".into())],
            "[책 이름]" => vec![("『책 이름』".into(), "기호·문자".into())],
            _ => vec![],
        }
    }
}

#[test]
fn bracketed_selection_converts_as_a_whole_and_preserves_inner_spaces() {
    let mut s = Session::default(); let mut b = Symbols;
    s.edit_selection("[책 이름]");
    assert_eq!(s.handle(Key::Space, &mut b).preedit, "『책 이름』");
    assert_eq!(s.handle(Key::Enter, &mut b).commit, "『책 이름』");
}

#[test]
fn slash_and_bracket_can_be_converted_without_early_commit() {
    for (input, expected) in [('/', "·"), ('(', "「")] {
        let mut s = Session::default(); let mut b = Symbols;
        let out = s.handle(Key::Char(input), &mut b);
        assert!(out.commit.is_empty());
        assert!(!out.preedit.is_empty());
        s.handle(Key::Space, &mut b);
        let out = s.handle(Key::Space, &mut b);
        assert_eq!(out.preedit, expected);
        assert_eq!(s.handle(Key::Enter, &mut b).commit, expected);
    }
}

#[test]
fn punctuation_can_be_kept_or_cancelled_and_backspaced() {
    let mut s = Session::default(); let mut b = Symbols;
    s.handle(Key::Char('/'), &mut b);
    s.handle(Key::Space, &mut b);
    s.handle(Key::Space, &mut b);
    assert_eq!(s.handle(Key::Escape, &mut b).preedit, "/");
    assert_eq!(s.handle(Key::Enter, &mut b).commit, "/");
    s.handle(Key::Char('('), &mut b);
    s.handle(Key::Backspace, &mut b);
    assert!(s.is_idle());
    s.handle(Key::Char('/'), &mut b);
    assert_eq!(s.handle(Key::Enter, &mut b).commit, "/");
}
