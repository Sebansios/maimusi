//! C ABI. See `include/hangul_core.h` for the contract.
//!
//! Strings are UTF-8 and NUL-terminated. Strings returned inside
//! `hc_output` stay valid until the next call on the same session.
//! Offsets are in UTF-16 code units, which is what AppKit, UIKit, Windows
//! and Java use for text ranges.

use crate::layout::Layout;
use crate::session::{Backend, Key, Output, Session, SpaceInConversion};
use crate::spacing::{LightSpacer, NgramModel};
use std::ffi::{c_char, c_void, CStr, CString};
use std::ptr;

pub type HcSpaceFn = Option<unsafe extern "C" fn(ctx: *mut c_void, text: *const c_char) -> *const c_char>;
pub type HcCandidatesFn = Option<unsafe extern "C" fn(ctx: *mut c_void, word: *const c_char) -> *const c_char>;

#[repr(C)]
pub struct HcBackend {
    pub ctx: *mut c_void,
    /// Returns the spaced text, or NULL when unavailable. The returned
    /// pointer must stay valid until the callback is invoked again.
    pub space: HcSpaceFn,
    /// Returns newline-separated alternatives, each optionally followed by
    /// a tab and a short note (its source), or NULL/"" for none.
    pub candidates: HcCandidatesFn,
}

#[repr(C)]
pub struct HcOutput {
    pub consumed: bool,
    pub commit: *const c_char,
    pub preedit: *const c_char,
    pub preedit_utf16_len: u32,
    pub highlight_start: i32,
    pub highlight_len: i32,
    pub candidate_count: u32,
    pub candidate_index: i32,
}

pub struct HcSession {
    session: Session,
    commit: CString,
    preedit: CString,
    candidates: Vec<CString>,
    notes: Vec<CString>,
    learning: CString,
}

pub struct HcSpacer {
    spacer: LightSpacer,
}

pub const HC_KEY_CHAR: u32 = 0;
pub const HC_KEY_SPACE: u32 = 1;
pub const HC_KEY_SHIFT_SPACE: u32 = 2;
pub const HC_KEY_BACKSPACE: u32 = 3;
pub const HC_KEY_ENTER: u32 = 4;
pub const HC_KEY_TAB: u32 = 5;
pub const HC_KEY_ESCAPE: u32 = 6;
pub const HC_KEY_LEFT: u32 = 7;
pub const HC_KEY_RIGHT: u32 = 8;
pub const HC_KEY_UP: u32 = 9;
pub const HC_KEY_DOWN: u32 = 10;
pub const HC_KEY_OTHER: u32 = 11;
pub const HC_KEY_SHRINK_SEGMENT: u32 = 12;
pub const HC_KEY_EXPAND_SEGMENT: u32 = 13;
pub const HC_KEY_MERGE_PREVIOUS: u32 = 14;
pub const HC_KEY_MERGE_NEXT: u32 = 15;

struct CBackend<'a>(Option<&'a HcBackend>);

unsafe fn borrowed_str<'a>(p: *const c_char) -> Option<&'a str> {
    if p.is_null() {
        None
    } else {
        CStr::from_ptr(p).to_str().ok()
    }
}

fn c_string(s: &str) -> CString {
    // Interior NULs cannot come from key input; drop them defensively.
    CString::new(s.replace('\0', "")).unwrap_or_default()
}

impl Backend for CBackend<'_> {
    fn space(&mut self, text: &str) -> Option<String> {
        let b = self.0?;
        let f = b.space?;
        let arg = c_string(text);
        unsafe { borrowed_str(f(b.ctx, arg.as_ptr())).map(str::to_string) }
    }

    fn candidates(&mut self, word: &str) -> Vec<(String, String)> {
        let Some(b) = self.0 else { return Vec::new() };
        let Some(f) = b.candidates else { return Vec::new() };
        let arg = c_string(word);
        let raw = unsafe { borrowed_str(f(b.ctx, arg.as_ptr())) };
        raw.map(|s| {
            s.lines()
                .filter(|l| !l.is_empty())
                .map(|l| match l.split_once('\t') {
                    Some((text, note)) => (text.to_string(), note.to_string()),
                    None => (l.to_string(), String::new()),
                })
                .collect()
        })
        .unwrap_or_default()
    }
}

fn utf16_len(s: &str) -> usize {
    s.chars().map(char::len_utf16).sum()
}

fn utf16_offset(s: &str, chars: usize) -> usize {
    s.chars().take(chars).map(char::len_utf16).sum()
}

impl HcSession {
    fn publish(&mut self, out: Output, dst: *mut HcOutput) {
        self.commit = c_string(&out.commit);
        self.preedit = c_string(&out.preedit);
        self.candidates = out.candidates.iter().map(|c| c_string(c)).collect();
        self.notes = out.candidate_notes.iter().map(|c| c_string(c)).collect();
        if dst.is_null() {
            return;
        }
        let (hs, hl) = match out.highlight {
            Some((start, len)) => {
                let s = utf16_offset(&out.preedit, start);
                let e = utf16_offset(&out.preedit, start + len);
                (s as i32, (e - s) as i32)
            }
            None => (-1, 0),
        };
        unsafe {
            *dst = HcOutput {
                consumed: out.consumed,
                commit: self.commit.as_ptr(),
                preedit: self.preedit.as_ptr(),
                preedit_utf16_len: utf16_len(&out.preedit) as u32,
                highlight_start: hs,
                highlight_len: hl,
                candidate_count: self.candidates.len() as u32,
                candidate_index: out.candidate_index.map(|i| i as i32).unwrap_or(-1),
            };
        }
    }
}

#[no_mangle]
pub extern "C" fn hc_session_new() -> *mut HcSession {
    Box::into_raw(Box::new(HcSession {
        session: Session::default(),
        commit: CString::default(),
        preedit: CString::default(),
        candidates: Vec::new(),
        notes: Vec::new(),
        learning: CString::default(),
    }))
}

/// # Safety
/// `s` must come from `hc_session_new` and not be used afterwards.
#[no_mangle]
pub unsafe extern "C" fn hc_session_free(s: *mut HcSession) {
    if !s.is_null() {
        drop(Box::from_raw(s));
    }
}

/// Set an option. Returns false for unknown keys or values.
/// Keys: layout, convert_on_space, space_in_conversion (commit|cycle),
/// enter_passes_through, space_implicit_commits (values "1"/"0").
///
/// # Safety
/// Pointers must be valid NUL-terminated strings.
#[no_mangle]
pub unsafe extern "C" fn hc_session_set_option(s: *mut HcSession, key: *const c_char, value: *const c_char) -> bool {
    let (Some(s), Some(key), Some(value)) = (s.as_mut(), borrowed_str(key), borrowed_str(value)) else {
        return false;
    };
    let flag = match value {
        "1" | "true" => Some(true),
        "0" | "false" => Some(false),
        _ => None,
    };
    let o = &mut s.session.options;
    match (key, flag) {
        ("layout", _) => match Layout::from_id(value) {
            Some(l) => o.layout = l,
            None => return false,
        },
        ("convert_on_space", Some(f)) => o.convert_on_space = f,
        ("enter_passes_through", Some(f)) => o.enter_passes_through = f,
        ("space_implicit_commits", Some(f)) => o.space_implicit_commits = f,
        ("space_in_conversion", _) => {
            o.space_in_conversion = match value {
                "commit" => SpaceInConversion::Commit,
                "cycle" => SpaceInConversion::Cycle,
                _ => return false,
            }
        }
        _ => return false,
    }
    true
}

fn to_key(key: u32, ch: u32) -> Key {
    match key {
        HC_KEY_CHAR => char::from_u32(ch).filter(|c| !c.is_control()).map(Key::Char).unwrap_or(Key::Other),
        HC_KEY_SPACE => Key::Space,
        HC_KEY_SHIFT_SPACE => Key::ShiftSpace,
        HC_KEY_BACKSPACE => Key::Backspace,
        HC_KEY_ENTER => Key::Enter,
        HC_KEY_TAB => Key::Tab,
        HC_KEY_ESCAPE => Key::Escape,
        HC_KEY_LEFT => Key::Left,
        HC_KEY_RIGHT => Key::Right,
        HC_KEY_UP => Key::Up,
        HC_KEY_DOWN => Key::Down,
        HC_KEY_SHRINK_SEGMENT => Key::ShrinkSegment,
        HC_KEY_EXPAND_SEGMENT => Key::ExpandSegment,
        HC_KEY_MERGE_PREVIOUS => Key::MergePrevious,
        HC_KEY_MERGE_NEXT => Key::MergeNext,
        _ => Key::Other,
    }
}

/// Process one key.
///
/// # Safety
/// `s` must be a live session; `backend` may be NULL; `out` must be writable.
#[no_mangle]
pub unsafe extern "C" fn hc_session_key(s: *mut HcSession, key: u32, ch: u32, backend: *const HcBackend, out: *mut HcOutput) {
    let Some(s) = s.as_mut() else { return };
    let mut b = CBackend(backend.as_ref());
    let o = s.session.handle(to_key(key, ch), &mut b);
    s.publish(o, out);
}

/// Commit everything that is being composed or converted.
///
/// # Safety
/// As for `hc_session_key`.
#[no_mangle]
pub unsafe extern "C" fn hc_session_commit(s: *mut HcSession, backend: *const HcBackend, out: *mut HcOutput) {
    let Some(s) = s.as_mut() else { return };
    let mut b = CBackend(backend.as_ref());
    let o = s.session.commit_all(&mut b);
    s.publish(o, out);
}

/// Discard composition without committing.
///
/// # Safety
/// As for `hc_session_key`.
#[no_mangle]
pub unsafe extern "C" fn hc_session_reset(s: *mut HcSession, out: *mut HcOutput) {
    let Some(s) = s.as_mut() else { return };
    let o = s.session.reset();
    s.publish(o, out);
}

/// Choose a candidate of the open list.
///
/// # Safety
/// As for `hc_session_key`.
#[no_mangle]
pub unsafe extern "C" fn hc_session_select_candidate(s: *mut HcSession, index: u32, out: *mut HcOutput) {
    let Some(s) = s.as_mut() else { return };
    let o = s.session.select_candidate(index as usize);
    s.publish(o, out);
}

/// Available boundary actions in the current conversion.
///
/// # Safety
/// `s` must be a live session or NULL.
#[no_mangle]
pub unsafe extern "C" fn hc_session_segment_actions(s: *const HcSession) -> u32 {
    s.as_ref().map(|s| s.session.segment_actions()).unwrap_or(0)
}

/// Import selected document text verbatim when the session is idle.
///
/// # Safety
/// `s` must be live, `text` a valid NUL-terminated string, and `out` writable.
#[no_mangle]
pub unsafe extern "C" fn hc_session_edit_selection(s: *mut HcSession, text: *const c_char, out: *mut HcOutput) {
    let Some(s) = s.as_mut() else { return };
    let o = s.session.edit_selection(borrowed_str(text).unwrap_or(""));
    s.publish(o, out);
}

/// Candidate `index` of the last output, or NULL.
///
/// # Safety
/// `s` must be a live session.
#[no_mangle]
pub unsafe extern "C" fn hc_session_candidate(s: *const HcSession, index: u32) -> *const c_char {
    match s.as_ref().and_then(|s| s.candidates.get(index as usize)) {
        Some(c) => c.as_ptr(),
        None => ptr::null(),
    }
}

/// Note (source) of candidate `index` of the last output, or NULL.
///
/// # Safety
/// `s` must be a live session.
#[no_mangle]
pub unsafe extern "C" fn hc_session_candidate_note(s: *const HcSession, index: u32) -> *const c_char {
    match s.as_ref().and_then(|s| s.notes.get(index as usize)) {
        Some(c) => c.as_ptr(),
        None => ptr::null(),
    }
}

/// 경계를 손으로 고친 변환이 방금 확정되었으면 "제안\u{1f}확정"을 돌려준다. 없으면 NULL.
/// 한 번 돌려준 값은 다시 나오지 않는다. 포인터는 다음 호출까지 유효하다.
///
/// # Safety
/// `s` must come from `hc_session_new`.
#[no_mangle]
pub unsafe extern "C" fn hc_session_take_learning(s: *mut HcSession) -> *const c_char {
    let Some(s) = s.as_mut() else { return ptr::null() };
    match s.session.take_learning() {
        Some((proposed, accepted)) => {
            s.learning = CString::new(format!("{proposed}\u{1f}{accepted}")).unwrap_or_default();
            s.learning.as_ptr()
        }
        None => ptr::null(),
    }
}

/// Romanize `text` (0 = Revised 2000, 1 = McCune–Reischauer, 2 = Yale).
/// Free the result with `hc_string_free`.
///
/// # Safety
/// `text` must be a valid NUL-terminated string.
#[no_mangle]
pub unsafe extern "C" fn hc_romanize(text: *const c_char, system: u32) -> *mut c_char {
    use crate::romanize::{romanize, System};
    let Some(text) = borrowed_str(text) else { return ptr::null_mut() };
    let Some(&sys) = System::ALL.get(system as usize) else { return ptr::null_mut() };
    c_string(&romanize(text, sys)).into_raw()
}

/// Load the light spacing model. Returns NULL on failure.
///
/// # Safety
/// `path` must be a valid NUL-terminated string.
#[no_mangle]
pub unsafe extern "C" fn hc_spacer_load(path: *const c_char) -> *mut HcSpacer {
    let Some(path) = borrowed_str(path) else { return ptr::null_mut() };
    match NgramModel::load(std::path::Path::new(path)) {
        Ok(m) => Box::into_raw(Box::new(HcSpacer { spacer: LightSpacer::new(m) })),
        Err(_) => ptr::null_mut(),
    }
}

/// # Safety
/// `sp` must come from `hc_spacer_load`.
#[no_mangle]
pub unsafe extern "C" fn hc_spacer_free(sp: *mut HcSpacer) {
    if !sp.is_null() {
        drop(Box::from_raw(sp));
    }
}

/// Space `text` with the light model. Free the result with `hc_string_free`.
///
/// # Safety
/// `sp` must be live; `text` a valid NUL-terminated string.
#[no_mangle]
pub unsafe extern "C" fn hc_spacer_space(sp: *const HcSpacer, text: *const c_char) -> *mut c_char {
    let (Some(sp), Some(text)) = (sp.as_ref(), borrowed_str(text)) else { return ptr::null_mut() };
    c_string(&sp.spacer.space(text)).into_raw()
}

/// # Safety
/// `p` must come from this library.
#[no_mangle]
pub unsafe extern "C" fn hc_string_free(p: *mut c_char) {
    if !p.is_null() {
        drop(CString::from_raw(p));
    }
}

/// Library version, static string.
#[no_mangle]
pub extern "C" fn hc_version() -> *const c_char {
    concat!(env!("CARGO_PKG_VERSION"), "\0").as_ptr() as *const c_char
}

#[cfg(test)]
mod tests {
    use super::*;

    unsafe fn s(p: *const c_char) -> String {
        CStr::from_ptr(p).to_str().unwrap().to_string()
    }

    unsafe extern "C" fn space_cb(_ctx: *mut c_void, text: *const c_char) -> *const c_char {
        let t = CStr::from_ptr(text).to_str().unwrap();
        assert_eq!(t, "나에는");
        c"나에 는".as_ptr()
    }

    #[test]
    fn roundtrip_through_c_abi() {
        unsafe {
            let sess = hc_session_new();
            let backend = HcBackend { ctx: ptr::null_mut(), space: Some(space_cb), candidates: None };
            let mut out = std::mem::zeroed::<HcOutput>();
            for k in "skdpsms".chars() {
                hc_session_key(sess, HC_KEY_CHAR, k as u32, &backend, &mut out);
            }
            assert_eq!(s(out.preedit), "나에는");
            assert_eq!(out.preedit_utf16_len, 3);
            hc_session_key(sess, HC_KEY_SPACE, 0, &backend, &mut out);
            assert_eq!(s(out.preedit), "나에 는");
            assert_eq!((out.highlight_start, out.highlight_len), (3, 1));
            hc_session_key(sess, HC_KEY_ENTER, 0, &backend, &mut out);
            assert_eq!(s(out.commit), "나에 는");
            assert!(out.consumed);
            assert!(hc_session_set_option(sess, c"space_in_conversion".as_ptr(), c"cycle".as_ptr()));
            assert!(!hc_session_set_option(sess, c"nope".as_ptr(), c"1".as_ptr()));
            hc_session_free(sess);
        }
    }

    #[test]
    fn utf16_offsets_count_astral_chars() {
        assert_eq!(utf16_len("🏫에"), 3);
        assert_eq!(utf16_offset("🏫에 가", 2), 3);
    }
}
