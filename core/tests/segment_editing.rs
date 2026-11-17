use hangul_core::{Backend, Key, Session};
use hangul_core::session::{SEGMENT_EXPAND, SEGMENT_MERGE_NEXT, SEGMENT_MERGE_PREVIOUS, SEGMENT_SHRINK};

#[derive(Default)]
struct Probe { spacing_calls: usize, candidate_calls: Vec<String> }
impl Backend for Probe {
    fn space(&mut self, text: &str) -> Option<String> {
        self.spacing_calls += 1;
        Some(text.replace("학교에간다", "학교에 간다"))
    }
    fn candidates(&mut self, text: &str) -> Vec<(String, String)> {
        self.candidate_calls.push(text.into());
        vec![(format!("【{text}】"), "test".into())]
    }
}

fn selected(text: &str) -> (Session, Probe) {
    let mut session = Session::default();
    let out = session.edit_selection(text);
    assert!(out.consumed);
    assert_eq!(out.preedit, text);
    (session, Probe::default())
}

#[test]
fn split_move_boundary_and_merge_both_directions() {
    let (mut s, mut b) = selected("학교에간다");
    assert_eq!(s.segment_actions(), SEGMENT_SHRINK);
    assert_eq!(s.handle(Key::ShrinkSegment, &mut b).preedit, "학교에간 다");
    assert_eq!(s.handle(Key::ShrinkSegment, &mut b).preedit, "학교에 간다");
    assert_eq!(s.segment_actions(), SEGMENT_SHRINK | SEGMENT_EXPAND | SEGMENT_MERGE_NEXT);
    assert_eq!(s.handle(Key::ExpandSegment, &mut b).preedit, "학교에간 다");
    assert_eq!(s.handle(Key::ExpandSegment, &mut b).preedit, "학교에간다");
    s.handle(Key::ShrinkSegment, &mut b);
    s.handle(Key::Right, &mut b);
    assert_eq!(s.segment_actions(), SEGMENT_MERGE_PREVIOUS);
    assert_eq!(s.handle(Key::MergePrevious, &mut b).preedit, "학교에간다");
    s.handle(Key::ShrinkSegment, &mut b);
    assert_eq!(s.handle(Key::MergeNext, &mut b).preedit, "학교에간다");
    assert_eq!(s.handle(Key::Enter, &mut b).commit, "학교에간다");
    assert_eq!(b.spacing_calls, 0);
}

#[test]
fn edited_spacing_survives_every_commit_path_without_respace() {
    for key in [Key::Enter, Key::Other, Key::Tab, Key::ShiftSpace, Key::Char('r')] {
        let (mut s, mut b) = selected("학교에 간다");
        s.handle(Key::MergePrevious, &mut b);
        let out = s.handle(key, &mut b);
        assert!(out.commit.starts_with("학교에간다"), "{key:?}: {out:?}");
        assert_eq!(b.spacing_calls, 0);
    }
    // 문장부호는 고친 경계를 그대로 둔 채 붙고, 확정은 Enter가 한다.
    let (mut s, mut b) = selected("학교에 간다");
    s.handle(Key::MergePrevious, &mut b);
    assert_eq!(s.handle(Key::Char('!'), &mut b).preedit, "학교에간다!");
    assert_eq!(s.handle(Key::Enter, &mut b).commit, "학교에간다!");
    assert_eq!(b.spacing_calls, 0);
    let (mut s, mut b) = selected("학교에 간다");
    s.handle(Key::MergePrevious, &mut b);
    assert_eq!(s.commit_all(&mut b).commit, "학교에간다");
    assert_eq!(b.spacing_calls, 0);
}

#[test]
fn composing_conversion_can_be_manually_overridden_and_cancelled() {
    let mut s = Session::default();
    let mut b = Probe::default();
    for ch in "gkrrydprksek".chars() { s.handle(Key::Char(ch), &mut b); }
    assert_eq!(s.handle(Key::Space, &mut b).preedit, "학교에 간다");
    assert_eq!(b.spacing_calls, 1);
    assert_eq!(s.handle(Key::MergePrevious, &mut b).preedit, "학교에간다");
    assert_eq!(s.handle(Key::Escape, &mut b).preedit, "학교에간다");
    assert!(!s.is_converting());
    assert_eq!(b.spacing_calls, 1);
}

#[test]
fn imported_escape_restores_exact_original_without_auto_spacing() {
    let original = "  학교에간다  ";
    let (mut s, mut b) = selected(original);
    s.handle(Key::ShrinkSegment, &mut b);
    let out = s.handle(Key::Escape, &mut b);
    assert_eq!(out.commit, original);
    assert!(out.preedit.is_empty());
    assert!(s.is_idle());
    assert_eq!(b.spacing_calls, 0);
}

#[test]
fn candidates_for_affected_segments_reset_other_choices_survive() {
    let (mut s, mut b) = selected("나는 학교에 간다");
    s.handle(Key::Left, &mut b);
    s.handle(Key::Left, &mut b);
    s.handle(Key::Down, &mut b); // unrelated segment's explicit candidate
    s.handle(Key::Right, &mut b);
    s.handle(Key::Down, &mut b);
    let out = s.handle(Key::ShrinkSegment, &mut b);
    assert_eq!(out.preedit, "【나는】 학교 에간다");
    assert!(out.candidates.is_empty());
    assert_eq!(out.candidate_index, None);
    let out = s.handle(Key::Down, &mut b);
    assert_eq!(out.preedit, "【나는】 【학교】 에간다");
    assert_eq!(b.candidate_calls, ["나는", "학교에", "학교"]);
}

#[test]
fn explicit_multiple_spaces_are_preserved_and_not_crossed() {
    let (mut s, mut b) = selected(" 가나  다라 ");
    assert_eq!(s.segment_actions(), SEGMENT_SHRINK);
    assert_eq!(s.handle(Key::MergePrevious, &mut b).preedit, " 가나  다라 ");
    s.handle(Key::Left, &mut b);
    assert_eq!(s.handle(Key::ExpandSegment, &mut b).preedit, " 가나  다라 ");
    assert_eq!(s.handle(Key::MergeNext, &mut b).preedit, " 가나  다라 ");
    assert_eq!(s.handle(Key::ShrinkSegment, &mut b).preedit, " 가 나  다라 ");
    assert_eq!(s.handle(Key::MergeNext, &mut b).preedit, " 가나  다라 ");
}

#[test]
fn single_graphemes_never_split_internally() {
    for unit in ["한", "e\u{301}", "👨‍👩‍👧‍👦", "🇰🇷", "👍🏽", "1️⃣", "क्ष"] {
        let (mut s, mut b) = selected(unit);
        assert_eq!(s.segment_actions(), 0, "{unit}");
        for key in [Key::ShrinkSegment, Key::ExpandSegment, Key::MergePrevious, Key::MergeNext] {
            assert_eq!(s.handle(key, &mut b).preedit, unit);
        }
        let (mut s, mut b) = selected(&format!("가{unit}"));
        assert_eq!(s.handle(Key::ShrinkSegment, &mut b).preedit, format!("가 {unit}"));
        assert_eq!(s.handle(Key::ExpandSegment, &mut b).preedit, format!("가{unit}"));
    }
}

#[test]
fn deterministic_unicode_edit_sequences_preserve_all_content_and_cluster_boundaries() {
    let atoms = ["가", "한", "e\u{301}", "👨‍👩‍👧‍👦", "🇰🇷", "👍🏽", "1️⃣", "क्ष", "Z"];
    let actions = [Key::ShrinkSegment, Key::ExpandSegment, Key::MergePrevious, Key::MergeNext, Key::Left, Key::Right];
    let mut seed = 0x20261002u64;
    let mut next = || { seed = seed.wrapping_mul(6364136223846793005).wrapping_add(1); (seed >> 32) as usize };
    for _ in 0..400 {
        let units: Vec<_> = (0..(4 + next() % 15)).map(|_| atoms[next() % atoms.len()]).collect();
        let compact = units.concat();
        let mut bounds = vec![0];
        for unit in &units { bounds.push(bounds.last().unwrap() + unit.len()); }
        let (mut s, mut b) = selected(&compact);
        for _ in 0..40 {
            let out = s.handle(actions[next() % actions.len()], &mut b);
            assert_eq!(out.preedit.replace(' ', ""), compact);
            let mut offset = 0;
            for word in out.preedit.split(' ') {
                assert!(bounds.contains(&offset));
                offset += word.len();
                assert!(bounds.contains(&offset));
            }
            let (start, len) = out.highlight.unwrap();
            assert!(len > 0 && start + len <= out.preedit.chars().count());
            assert!(out.commit.is_empty());
        }
        assert_eq!(s.commit_all(&mut b).commit.replace(' ', ""), compact);
        assert_eq!(b.spacing_calls, 0);
    }
}

#[test]
fn reject_invalid_or_nonidle_selection_without_losing_existing_input() {
    for text in ["", "  ", "가\n나", "가\t나", "가\0나", "가\u{2028}나", "가\u{2029}나"] {
        let mut s = Session::default();
        assert!(!s.edit_selection(text).consumed);
        assert!(s.is_idle());
    }
    let mut s = Session::default();
    assert!(!s.edit_selection(&"가".repeat(1001)).consumed);
    let mut b = Probe::default();
    s.handle(Key::Char('r'), &mut b);
    assert_eq!(s.edit_selection("교체하지마").preedit, "ㄱ");
    assert!(!s.edit_selection("교체하지마").consumed);
}

#[test]
fn shift_arrows_outside_conversion_retain_legacy_pass_through() {
    for key in [Key::ShrinkSegment, Key::ExpandSegment] {
        let mut s = Session::default();
        let mut b = Probe::default();
        assert!(!s.handle(key, &mut b).consumed);
        s.handle(Key::Char('r'), &mut b);
        let out = s.handle(key, &mut b);
        assert!(!out.consumed);
        assert_eq!(out.commit, "ㄱ");
        assert!(out.preedit.is_empty());
    }
}

#[test]
fn imported_backspace_keeps_manual_boundaries_and_escape_original() {
    for merge in [false, true] {
        let original = if merge { "학교에 간다" } else { "학교에간다" };
        let (mut s, mut b) = selected(original);
        if merge { s.handle(Key::MergePrevious, &mut b); }
        else {
            s.handle(Key::ShrinkSegment, &mut b);
            s.handle(Key::ShrinkSegment, &mut b);
        }
        let expected = if merge { "학교에간" } else { "학교에 간" };
        assert_eq!(s.handle(Key::Backspace, &mut b).preedit, expected);
        assert!(s.is_converting());
        assert_eq!(s.handle(Key::Escape, &mut b).commit, original);
        assert!(s.is_idle());
        assert_eq!(b.spacing_calls, 0);
    }
}

#[test]
fn imported_backspace_commit_and_focus_never_respace() {
    for focus in [false, true] {
        let (mut s, mut b) = selected("학교에간다");
        s.handle(Key::ShrinkSegment, &mut b);
        s.handle(Key::ShrinkSegment, &mut b);
        s.handle(Key::Backspace, &mut b);
        let out = if focus { s.commit_all(&mut b) } else { s.handle(Key::Enter, &mut b) };
        assert_eq!(out.commit, "학교에 간");
        assert!(s.is_idle());
        assert_eq!(b.spacing_calls, 0);
    }
}

#[test]
fn imported_backspace_deletes_whole_graphemes_and_keeps_empty_cancel() {
    let original = "e\u{301}가";
    let (mut s, mut b) = selected(original);
    assert_eq!(s.handle(Key::Backspace, &mut b).preedit, "e\u{301}");
    let empty = s.handle(Key::Backspace, &mut b);
    assert!(empty.preedit.is_empty());
    assert_eq!(empty.highlight, Some((0, 0)));
    assert!(s.is_converting());
    assert_eq!(s.segment_actions(), 0);
    assert!(s.handle(Key::Backspace, &mut b).preedit.is_empty());
    assert_eq!(s.handle(Key::Escape, &mut b).commit, original);
    assert_eq!(b.spacing_calls, 0);
    for unit in ["한", "👨‍👩‍👧‍👦", "🇰🇷", "👍🏽", "1️⃣", "क्ष"] {
        let (mut s, mut b) = selected(unit);
        assert!(s.handle(Key::Backspace, &mut b).preedit.is_empty());
        assert_eq!(s.handle(Key::Escape, &mut b).commit, unit);
    }
}

#[test]
fn imported_delete_all_then_type_has_no_added_separator() {
    let (mut s, mut b) = selected("가");
    s.handle(Key::Backspace, &mut b);
    let out = s.handle(Key::Char('r'), &mut b);
    assert!(out.commit.is_empty());
    assert_eq!(out.preedit, "ㄱ");
    assert!(!s.is_converting());
    assert_eq!(b.spacing_calls, 0);
}

#[test]
fn imported_delete_all_can_commit_or_reset_without_restoring() {
    for action in [0, 1, 2] {
        let (mut s, mut b) = selected("가");
        s.handle(Key::Backspace, &mut b);
        let out = match action {
            0 => s.handle(Key::Enter, &mut b),
            1 => s.commit_all(&mut b),
            _ => s.reset(),
        };
        assert!(out.commit.is_empty() && out.preedit.is_empty());
        assert_eq!(out.highlight, None);
        assert!(s.is_idle());
        assert_eq!(b.spacing_calls, 0);
    }
}

#[test]
fn imported_backspace_preserves_other_candidate_readings_and_literal_spaces() {
    let (mut s, mut b) = selected("학교에 가");
    s.handle(Key::Left, &mut b);
    s.handle(Key::Down, &mut b);
    assert_eq!(s.handle(Key::Backspace, &mut b).preedit, "【학교에】 ");
    assert_eq!(s.handle(Key::Backspace, &mut b).preedit, "【학교에】");
    // The untouched word still offers candidates from its Korean reading.
    s.handle(Key::Down, &mut b);
    assert_eq!(b.candidate_calls, ["학교에", "학교에"]);
    assert_eq!(s.handle(Key::Escape, &mut b).preedit, "학교에");
    assert_eq!(s.handle(Key::Escape, &mut b).commit, "학교에 가");
}

#[test]
fn manually_edited_typed_conversion_backspace_preserves_boundaries() {
    for edit in [Key::MergePrevious, Key::ShrinkSegment] {
        let mut s = Session::default();
        let mut b = Probe::default();
        for ch in "gkrrydprksek".chars() { s.handle(Key::Char(ch), &mut b); }
        assert_eq!(s.handle(Key::Space, &mut b).preedit, "학교에 간다");
        s.handle(edit, &mut b);
        let expected = if edit == Key::MergePrevious { "학교에간" } else { "학교에 간 " };
        assert_eq!(s.handle(Key::Backspace, &mut b).preedit, expected);
        assert!(s.is_converting());
        assert_eq!(b.spacing_calls, 1);
        assert_eq!(s.handle(Key::Enter, &mut b).commit, expected);
        assert_eq!(b.spacing_calls, 1); // no additional automatic analysis
    }
}

#[test]
fn manually_edited_typed_conversion_escape_restores_raw_composition() {
    let mut s = Session::default();
    let mut b = Probe::default();
    for ch in "gkrrydprksek".chars() { s.handle(Key::Char(ch), &mut b); }
    s.handle(Key::Space, &mut b);
    s.handle(Key::MergePrevious, &mut b);
    s.handle(Key::Backspace, &mut b);
    let out = s.handle(Key::Escape, &mut b);
    assert_eq!(out.preedit, "학교에간다");
    assert!(out.commit.is_empty());
    assert!(!s.is_converting());
    assert_eq!(b.spacing_calls, 1);
}

#[test]
fn unavailable_boundary_action_keeps_unedited_backspace_behavior() {
    let mut s = Session::default();
    let mut b = Probe::default();
    for ch in "gkrrydprksek".chars() { s.handle(Key::Char(ch), &mut b); }
    s.handle(Key::Space, &mut b);
    s.handle(Key::ExpandSegment, &mut b); // selected last segment cannot expand
    let out = s.handle(Key::Backspace, &mut b);
    assert_eq!(out.preedit, "학교에간");
    assert!(!s.is_converting());
}

#[test]
fn manually_edited_typed_conversion_can_delete_all_then_cancel() {
    let mut s = Session::default();
    let mut b = Probe::default();
    for ch in "rksk".chars() { s.handle(Key::Char(ch), &mut b); }
    s.handle(Key::Space, &mut b);
    assert_eq!(s.handle(Key::ShrinkSegment, &mut b).preedit, "가 나");
    for _ in 0..3 { s.handle(Key::Backspace, &mut b); }
    assert!(s.is_converting());
    let out = s.handle(Key::Escape, &mut b);
    assert_eq!(out.preedit, "가나");
    assert!(out.commit.is_empty());
    assert!(!s.is_converting());
    assert_eq!(b.spacing_calls, 1);
}

#[test]
fn hand_edited_boundaries_are_offered_once_for_learning() {
    let (mut s, mut b) = selected("학교에 간다");
    s.handle(Key::MergePrevious, &mut b);
    s.handle(Key::Enter, &mut b);
    assert_eq!(s.take_learning(), Some(("학교에 간다".into(), "학교에간다".into())));
    assert_eq!(s.take_learning(), None);
    // 고치지 않고 확정하면 배울 것이 없다.
    let (mut s, mut b) = selected("학교에 간다");
    s.handle(Key::Enter, &mut b);
    assert_eq!(s.take_learning(), None);
    // 고쳤다가 원래대로 돌려놓아도 없다.
    let (mut s, mut b) = selected("학교에 간다");
    s.handle(Key::MergePrevious, &mut b);
    s.handle(Key::ShrinkSegment, &mut b);
    s.handle(Key::ShrinkSegment, &mut b);
    let out = s.handle(Key::Enter, &mut b);
    if out.commit == "학교에 간다" {
        assert_eq!(s.take_learning(), None);
    }
}
