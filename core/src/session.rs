//! Input session: the platform-independent state machine of the IME.
//!
//! Typing accumulates unspaced text as marked (preedit) text. Space asks the
//! backend to space it and enters conversion, where ←/→ pick a word, Space
//! or ↑/↓ step through its candidates (like a Japanese IME), Enter accepts,
//! Esc restores the typed text, and any further typing accepts the
//! conversion with a trailing space.
//!
//! The session never loses input: a backend result is used only if it is a
//! pure respacing of the typed text (see `spacing::checked`).

use crate::composer::Composer;
use crate::layout::Layout;
use crate::romanize::{romanize, System};
use crate::spacing;
use unicode_segmentation::UnicodeSegmentation;

/// Candidates shown per page; number keys 1–9 pick within the current page.
pub const CANDIDATE_PAGE: usize = 9;

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Key {
    /// Printable key; the character the key produces on US QWERTY with Shift applied.
    Char(char),
    Space,
    ShiftSpace,
    Backspace,
    Enter,
    Tab,
    Escape,
    Left,
    Right,
    Up,
    Down,
    /// Move the selected segment's right boundary by one grapheme.
    ShrinkSegment,
    ExpandSegment,
    MergePrevious,
    MergeNext,
    /// Any other key, or any key combined with Command/Control/Option.
    Other,
}

/// What the platform must do after a key.
#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct Output {
    /// False: after inserting `commit`, let the application handle the key.
    pub consumed: bool,
    /// Text to insert into the document before showing the new preedit.
    pub commit: String,
    /// Marked text; empty when nothing is being composed.
    pub preedit: String,
    /// Selected word in `preedit` as (start, len) in chars.
    pub highlight: Option<(usize, usize)>,
    pub candidates: Vec<String>,
    /// Where each candidate comes from (한자, 이모지, 로마자 2000, ...).
    pub candidate_notes: Vec<String>,
    pub candidate_index: Option<usize>,
}

pub trait Backend {
    /// Respace `text`. `None` means "unavailable"; the session keeps the text.
    fn space(&mut self, text: &str) -> Option<String>;
    /// Alternatives for one word as (text, note), best first. May be empty.
    fn candidates(&mut self, word: &str) -> Vec<(String, String)>;
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum SpaceInConversion {
    /// Accept the conversion and insert a space.
    Commit,
    /// Cycle candidates of the selected word; accept when it has none (default).
    Cycle,
}

#[derive(Clone, Debug)]
pub struct Options {
    pub layout: Layout,
    /// Space converts; when false the IME behaves like a plain Korean IME.
    pub convert_on_space: bool,
    pub space_in_conversion: SpaceInConversion,
    /// Enter while composing inserts the spaced text and still sends Enter.
    pub enter_passes_through: bool,
    /// Commits caused by Enter, arrows, clicks and shortcuts are spaced too.
    pub space_implicit_commits: bool,
    pub max_buffer: usize,
}

impl Default for Options {
    fn default() -> Self {
        Options {
            layout: Layout::Dubeolsik,
            convert_on_space: true,
            space_in_conversion: SpaceInConversion::Cycle,
            enter_passes_through: false,
            space_implicit_commits: true,
            max_buffer: 1000,
        }
    }
}

#[derive(Clone, Debug)]
struct Conversion {
    /// Exactly what was typed, including manual spaces.
    original: String,
    /// 변환을 시작할 때 보여 준 띄어쓰기(엔진 제안 또는 가져온 선택 영역).
    proposed: String,
    /// Display split on single spaces; empty entries keep multiple spaces.
    words: Vec<String>,
    /// Backend result for each word before candidate changes.
    sources: Vec<String>,
    selected: usize,
    /// Candidate list for the selected word (index 0 is its source form).
    candidates: Option<(Vec<String>, usize)>,
    notes: Vec<String>,
    /// A selection imported from the document must cancel back verbatim.
    imported: bool,
    /// Preserve manual boundaries when deleting from a normal conversion too.
    boundary_edited: bool,
}

pub const SEGMENT_SHRINK: u32 = 1;
pub const SEGMENT_EXPAND: u32 = 2;
pub const SEGMENT_MERGE_PREVIOUS: u32 = 4;
pub const SEGMENT_MERGE_NEXT: u32 = 8;

impl Conversion {
    fn display(&self) -> String {
        self.words.join(" ")
    }

    fn word_start(&self, idx: usize) -> usize {
        self.words[..idx].iter().map(|w| w.chars().count() + 1).sum()
    }

    fn real_words(&self) -> impl Iterator<Item = usize> + '_ {
        (0..self.words.len()).filter(|&i| !self.words[i].is_empty())
    }

    fn edit_actions(&self) -> u32 {
        let i = self.selected;
        let has_previous = i > 0 && !self.sources[i - 1].is_empty();
        let has_next = i + 1 < self.sources.len() && !self.sources[i + 1].is_empty();
        let shrink = self.sources[i].graphemes(true).nth(1).is_some();
        (if shrink { SEGMENT_SHRINK } else { 0 })
            | (if has_next { SEGMENT_EXPAND | SEGMENT_MERGE_NEXT } else { 0 })
            | (if has_previous { SEGMENT_MERGE_PREVIOUS } else { 0 })
    }

    /// Change source boundaries and reset only the candidates they affect.
    /// Empty entries represent explicit multiple spaces and are never crossed.
    fn edit_boundary(&mut self, key: Key) {
        let bit = match key {
            Key::ShrinkSegment => SEGMENT_SHRINK,
            Key::ExpandSegment => SEGMENT_EXPAND,
            Key::MergePrevious => SEGMENT_MERGE_PREVIOUS,
            Key::MergeNext => SEGMENT_MERGE_NEXT,
            _ => return,
        };
        if self.edit_actions() & bit == 0 { return; }
        let i = self.selected;
        match key {
            Key::ShrinkSegment => {
                let split = self.sources[i].grapheme_indices(true).last().unwrap().0;
                let tail = self.sources[i].split_off(split);
                self.words[i] = self.sources[i].clone();
                if i + 1 < self.sources.len() && !self.sources[i + 1].is_empty() {
                    self.sources[i + 1].insert_str(0, &tail);
                    self.words[i + 1] = self.sources[i + 1].clone();
                } else {
                    self.sources.insert(i + 1, tail.clone());
                    self.words.insert(i + 1, tail);
                }
            }
            Key::ExpandSegment => {
                let end = self.sources[i + 1].graphemes(true).next().unwrap().len();
                let tail = self.sources[i + 1].split_off(end);
                let moved = self.sources[i + 1].clone();
                self.sources[i].push_str(&moved);
                self.words[i] = self.sources[i].clone();
                if tail.is_empty() {
                    self.sources.remove(i + 1);
                    self.words.remove(i + 1);
                } else {
                    self.sources[i + 1] = tail.clone();
                    self.words[i + 1] = tail;
                }
            }
            Key::MergePrevious | Key::MergeNext => {
                let left = if key == Key::MergePrevious { i - 1 } else { i };
                let right = self.sources.remove(left + 1);
                self.sources[left].push_str(&right);
                self.words[left] = self.sources[left].clone();
                self.words.remove(left + 1);
                self.selected = left;
            }
            _ => unreachable!(),
        }
        self.candidates = None;
        self.notes.clear();
        self.boundary_edited = true;
    }

    /// Delete from the displayed selection, retaining the original for Escape.
    /// Only the final affected word loses its old candidate reading.
    fn backspace_display(&mut self) {
        let last = self.words.len() - 1;
        if self.words[last].is_empty() && last > 0 {
            // The final joiner is itself a literal trailing space.
            self.words.pop();
            self.sources.pop();
        } else if let Some((offset, _)) = self.words[last].grapheme_indices(true).last() {
            self.words[last].truncate(offset);
            self.sources[last] = self.words[last].clone();
        }
        if self.selected >= self.words.len() || self.words[self.selected].is_empty() {
            self.selected = self.real_words().last().unwrap_or(0);
        }
        self.candidates = None;
        self.notes.clear();
    }
}

#[derive(Clone, Debug)]
enum State {
    Composing { buf: String, composer: Composer },
    Converting(Conversion),
}

pub struct Session {
    pub options: Options,
    state: State,
    /// 경계를 손으로 고친 변환을 확정했을 때 (엔진이 제안한 글, 확정한 글).
    /// 세션은 이 값을 보관만 했다가 호스트가 가져가면 비운다. 저장은 호스트가 정한다.
    learned: Option<(String, String)>,
}

/// Attaches to the end of the accepted conversion without a space.
fn attaches_left(c: char) -> bool {
    matches!(
        c,
        '.' | ',' | '?' | '!' | ':' | ';' | ')' | ']' | '}' | '>' | '\'' | '"' | '~' | '…' | '%'
            | '」' | '』' | '”' | '’' | '。' | '、'
    )
}

/// Full-width form of ASCII text, or half-width form of full-width text.
fn width_variant(s: &str) -> Option<(String, &'static str)> {
    let full: String = s
        .chars()
        .map(|c| match c {
            '!'..='~' => char::from_u32(c as u32 + 0xFEE0).unwrap_or(c),
            ' ' => '\u{3000}',
            c => c,
        })
        .collect();
    if full != s {
        return Some((full, "전각"));
    }
    let half: String = s
        .chars()
        .map(|c| match c {
            '\u{FF01}'..='\u{FF5E}' => char::from_u32(c as u32 - 0xFEE0).unwrap_or(c),
            '\u{3000}' => ' ',
            c => c,
        })
        .collect();
    (half != s).then_some((half, "반각"))
}

/// Half-width Hangul (U+FFA1..) for a run of compatibility jamo, or the
/// compatibility jamo for a half-width run: ㄱ <-> ﾡ, ㅋㅋ <-> ﾻﾻ.
fn jamo_width_variant(s: &str) -> Option<(String, &'static str)> {
    // Compatibility vowels ㅏ..ㅣ in the half-width block skip FFC8-9, FFD0-1, FFD8-9.
    const VOWELS: [u32; 21] = [
        0xFFC2, 0xFFC3, 0xFFC4, 0xFFC5, 0xFFC6, 0xFFC7, 0xFFCA, 0xFFCB, 0xFFCC, 0xFFCD, 0xFFCE,
        0xFFCF, 0xFFD2, 0xFFD3, 0xFFD4, 0xFFD5, 0xFFD6, 0xFFD7, 0xFFDA, 0xFFDB, 0xFFDC,
    ];
    let half = |c: char| match c as u32 {
        v @ 0x3131..=0x314E => char::from_u32(v - 0x3131 + 0xFFA1),
        v @ 0x314F..=0x3163 => char::from_u32(VOWELS[(v - 0x314F) as usize]),
        _ => None,
    };
    let full = |c: char| match c as u32 {
        v @ 0xFFA1..=0xFFBE => char::from_u32(v - 0xFFA1 + 0x3131),
        v => VOWELS.iter().position(|&h| h == v).and_then(|i| char::from_u32(0x314F + i as u32)),
    };
    if s.is_empty() {
        return None;
    }
    if let Some(text) = s.chars().map(half).collect::<Option<String>>() {
        return Some((text, "반각"));
    }
    s.chars().map(full).collect::<Option<String>>().map(|text| (text, "호환 자모"))
}

/// Candidates for one word: the word itself, the backend's alternatives,
/// then the three romanizations, so every Korean word has alternatives.
fn candidate_list(source: &str, backend: &mut dyn Backend) -> (Vec<String>, Vec<String>) {
    let mut list = vec![source.to_string()];
    let mut notes = vec![String::new()];
    let mut add = |text: String, note: &str, list: &mut Vec<String>, notes: &mut Vec<String>| {
        if !text.is_empty() && !text.contains('\n') && !list.contains(&text) {
            list.push(text);
            notes.push(note.to_string());
        }
    };
    for (text, note) in backend.candidates(source) {
        add(text, &note, &mut list, &mut notes);
    }
    // 낱자는 엔진이 없어도(경량 엔진) 반각 한글을 낸다. 엔진이 낸 것과 겹치면 하나만 남는다.
    if let Some((text, note)) = jamo_width_variant(source) {
        add(text, note, &mut list, &mut notes);
    }
    for system in System::ALL {
        add(romanize(source, system), system.label(), &mut list, &mut notes);
    }
    if list.len() < 2 {
        if let Some((text, note)) = width_variant(source) {
            add(text, note, &mut list, &mut notes);
        }
    }
    (list, notes)
}

impl Default for Session {
    fn default() -> Self {
        Self::new(Options::default())
    }
}

impl Session {
    pub fn new(options: Options) -> Self {
        Session { options, state: State::Composing { buf: String::new(), composer: Composer::new() }, learned: None }
    }

    pub fn is_idle(&self) -> bool {
        matches!(&self.state, State::Composing { buf, composer } if buf.is_empty() && composer.is_empty())
    }

    pub fn is_converting(&self) -> bool {
        matches!(self.state, State::Converting(_))
    }

    pub fn segment_actions(&self) -> u32 {
        match &self.state {
            State::Converting(c) => c.edit_actions(),
            _ => 0,
        }
    }

    /// Import an existing, single-line selection without invoking spacing.
    /// The platform replaces precisely that selection with the returned preedit.
    pub fn edit_selection(&mut self, text: &str) -> Output {
        if !self.is_idle() || text.trim().is_empty()
            || text.chars().count() > self.options.max_buffer
            || text.chars().any(|c| c.is_control() || matches!(c, '\u{2028}' | '\u{2029}'))
        {
            return self.output(false, String::new());
        }
        self.enter_conversion(text.to_owned(), text.to_owned());
        if let State::Converting(c) = &mut self.state { c.imported = true; }
        self.output(true, String::new())
    }

    fn idle_state() -> State {
        State::Composing { buf: String::new(), composer: Composer::new() }
    }

    /// Typed text of the composing state, finishing the current syllable.
    fn take_typed(&mut self) -> String {
        match std::mem::replace(&mut self.state, Self::idle_state()) {
            State::Composing { mut buf, mut composer } => {
                buf.extend(composer.flush());
                buf
            }
            State::Converting(c) => {
                let shown = c.display();
                if c.boundary_edited && shown != c.proposed
                    && shown.replace(' ', "") == c.proposed.replace(' ', "")
                {
                    self.learned = Some((c.proposed, shown.clone()));
                }
                shown
            }
        }
    }

    /// 손으로 고친 경계를 확정했으면 (제안, 확정)을 한 번 내준다.
    pub fn take_learning(&mut self) -> Option<(String, String)> {
        self.learned.take()
    }

    fn space_with(backend: &mut dyn Backend, text: &str) -> String {
        if text.trim().is_empty() {
            return text.to_string();
        }
        let prepared = spacing::prepare(text);
        let spaced = spacing::checked(&prepared, backend.space(&prepared));
        spacing::checked(text, Some(spaced))
    }

    /// Text to insert for an implicit commit (focus change, shortcuts, ...).
    fn implicit_commit(&mut self, backend: &mut dyn Backend) -> String {
        match &self.state {
            State::Converting(_) => self.take_typed(),
            State::Composing { .. } => {
                let typed = self.take_typed();
                if self.options.space_implicit_commits && self.options.convert_on_space {
                    Self::space_with(backend, &typed)
                } else {
                    typed
                }
            }
        }
    }

    /// Commit everything (the application asked, or focus is leaving).
    pub fn commit_all(&mut self, backend: &mut dyn Backend) -> Output {
        let commit = self.implicit_commit(backend);
        self.output(true, commit)
    }

    /// Drop everything without committing.
    pub fn reset(&mut self) -> Output {
        self.state = Self::idle_state();
        self.output(true, String::new())
    }

    pub fn handle(&mut self, key: Key, backend: &mut dyn Backend) -> Output {
        match self.state {
            State::Composing { .. } => self.handle_composing(key, backend),
            State::Converting(_) => self.handle_converting(key, backend),
        }
    }

    /// Candidate chosen with the mouse or a number key.
    pub fn select_candidate(&mut self, index: usize) -> Output {
        if let State::Converting(c) = &mut self.state {
            if let Some((list, _)) = &c.candidates {
                if let Some(word) = list.get(index).cloned() {
                    c.words[c.selected] = word;
                    c.candidates = None;
                }
            }
        }
        self.output(true, String::new())
    }

    fn handle_composing(&mut self, key: Key, backend: &mut dyn Backend) -> Output {
        let idle = self.is_idle();
        let layout = self.options.layout;
        match key {
            Key::Char(ch) => {
                let State::Composing { buf, composer } = &mut self.state else { unreachable!() };
                if let Some(jamo) = layout.map(ch) {
                    buf.extend(composer.feed(jamo));
                } else if idle && !ch.is_ascii_digit() && !"/()[]{}<>.,'\"-~:+*=!?".contains(ch) {
                    // Non-convertible symbols go straight through. Convertible
                    // punctuation stays in preedit for the usual Space/Tab path.
                    return self.output(true, ch.to_string());
                } else {
                    buf.extend(composer.flush());
                    buf.push(ch);
                }
                if buf.chars().count() >= self.options.max_buffer {
                    let commit = self.implicit_commit(backend);
                    return self.output(true, commit);
                }
                self.output(true, String::new())
            }
            Key::Space if idle => self.output(false, String::new()),
            Key::Space if !self.options.convert_on_space => {
                let mut commit = self.take_typed();
                commit.push(' ');
                self.output(true, commit)
            }
            Key::Space => {
                let typed = self.take_typed();
                let spaced = Self::space_with(backend, &typed);
                self.enter_conversion(typed, spaced);
                self.output(true, String::new())
            }
            Key::ShiftSpace if idle => self.output(false, String::new()),
            Key::ShiftSpace => {
                // 일반 두벌식처럼: 친 그대로(자동 띄어쓰기 없이) 확정하고 공백을 넣는다.
                let mut commit = self.take_typed();
                commit.push(' ');
                self.output(true, commit)
            }
            Key::Backspace => {
                let State::Composing { buf, composer } = &mut self.state else { unreachable!() };
                if composer.backspace() || buf.pop().is_some() {
                    self.output(true, String::new())
                } else {
                    self.output(false, String::new())
                }
            }
            _ if idle => self.output(false, String::new()),
            Key::Escape => {
                let commit = self.take_typed();
                self.output(false, commit)
            }
            Key::Enter => {
                // Enter는 확정 키다. 보이는 그대로(스페이스 전이면 띄어쓰기 없이) 확정한다.
                let commit = self.take_typed();
                self.output(!self.options.enter_passes_through, commit)
            }
            _ => {
                let commit = self.implicit_commit(backend);
                self.output(false, commit)
            }
        }
    }

    fn enter_conversion(&mut self, original: String, spaced: String) {
        // An enclosing pair converts as a unit, including spaces in its content.
        let pair = spaced.chars().next().zip(spaced.chars().last());
        let wrapped = spaced.chars().count() >= 2 && matches!(pair,
            Some(('(', ')') | ('[', ']') | ('{', '}') | ('<', '>') |
                 ('「', '」') | ('『', '』') | ('〈', '〉') | ('《', '》') |
                 ('【', '】') | ('〔', '〕') | ('（', '）') | ('［', '］') |
                 ('｛', '｝') | ('≪', '≫') | ('‘', '’') | ('“', '”') |
                 ('\'', '\'') | ('"', '"')));
        let words: Vec<String> = if wrapped { vec![spaced] }
                                else { spaced.split(' ').map(str::to_string).collect() };
        let selected = (0..words.len()).rev().find(|&i| !words[i].is_empty()).unwrap_or(0);
        self.state = State::Converting(Conversion {
            proposed: words.join(" "),
            original,
            sources: words.clone(),
            words,
            selected,
            candidates: None,
            notes: Vec::new(),
            imported: false,
            boundary_edited: false,
        });
    }

    fn handle_converting(&mut self, key: Key, backend: &mut dyn Backend) -> Output {
        let State::Converting(conv) = &mut self.state else { unreachable!() };
        match key {
            Key::Char(ch) if conv.candidates.is_some() && ('1'..='9').contains(&ch) => {
                let current = conv.candidates.as_ref().map(|c| c.1).unwrap_or(0);
                let idx = current / CANDIDATE_PAGE * CANDIDATE_PAGE + (ch as usize - '1' as usize);
                self.select_candidate(idx)
            }
            Key::Char(ch) if attaches_left(ch) => {
                // 문장부호는 마지막 어절에 붙이고 변환을 이어 간다. 여기서 바로
                // 확정하면 다음 Enter가 확정할 것 없이 앱으로 넘어가 메시지가 전송된다.
                conv.candidates = None;
                if let Some(word) = conv.words.last_mut() { word.push(ch); }
                if let Some(source) = conv.sources.last_mut() { source.push(ch); }
                conv.original.push(ch);
                self.output(true, String::new())
            }
            Key::Char(_) => {
                let mut commit = self.take_typed();
                if !commit.is_empty() { commit.push(' '); }
                let mut out = self.handle_composing(key, backend);
                commit.push_str(&out.commit);
                out.commit = commit;
                out
            }
            Key::Space if self.options.space_in_conversion == SpaceInConversion::Cycle => {
                if self.move_candidate(1, backend) {
                    self.output(true, String::new())
                } else {
                    let mut commit = self.take_typed();
                    commit.push(' ');
                    self.output(true, commit)
                }
            }
            Key::Space | Key::ShiftSpace => {
                let mut commit = self.take_typed();
                commit.push(' ');
                self.output(true, commit)
            }
            Key::Left | Key::Right => {
                let forward = key == Key::Right;
                let next = if forward {
                    conv.real_words().find(|&i| i > conv.selected)
                } else {
                    conv.real_words().filter(|&i| i < conv.selected).last()
                };
                if let Some(i) = next {
                    conv.selected = i;
                    conv.candidates = None;
                }
                self.output(true, String::new())
            }
            Key::Down | Key::Up => {
                self.move_candidate(if key == Key::Down { 1 } else { -1 }, backend);
                self.output(true, String::new())
            }
            Key::ShrinkSegment | Key::ExpandSegment | Key::MergePrevious | Key::MergeNext => {
                conv.edit_boundary(key);
                self.output(true, String::new())
            }
            Key::Enter => {
                let commit = self.take_typed();
                self.output(true, commit)
            }
            Key::Escape => {
                if let Some((list, i)) = &conv.candidates {
                    if *i != 0 {
                        conv.words[conv.selected] = list[0].clone();
                    }
                    conv.candidates = None;
                } else if conv.imported {
                    let original = std::mem::take(&mut conv.original);
                    self.state = Self::idle_state();
                    return self.output(true, original);
                } else {
                    let original = std::mem::take(&mut conv.original);
                    self.state = State::Composing { buf: original, composer: Composer::new() };
                }
                self.output(true, String::new())
            }
            Key::Backspace => {
                if conv.imported || conv.boundary_edited {
                    conv.backspace_display();
                    return self.output(true, String::new());
                }
                let mut original = std::mem::take(&mut conv.original);
                if let Some((last, _)) = original.grapheme_indices(true).last() {
                    original.truncate(last);
                }
                self.state = State::Composing { buf: original, composer: Composer::new() };
                self.output(true, String::new())
            }
            Key::Tab | Key::Other => {
                let commit = self.take_typed();
                self.output(false, commit)
            }
        }
    }

    /// Step through candidates of the selected word. False if it has none.
    fn move_candidate(&mut self, delta: isize, backend: &mut dyn Backend) -> bool {
        let State::Converting(conv) = &mut self.state else { return false };
        if conv.candidates.is_none() {
            let source = conv.sources[conv.selected].clone();
            let (list, notes) = candidate_list(&source, backend);
            if list.len() < 2 {
                return false;
            }
            conv.candidates = Some((list, 0));
            conv.notes = notes;
        }
        let (list, idx) = conv.candidates.as_mut().unwrap();
        let n = list.len() as isize;
        *idx = ((*idx as isize + delta).rem_euclid(n)) as usize;
        conv.words[conv.selected] = list[*idx].clone();
        true
    }

    fn output(&self, consumed: bool, commit: String) -> Output {
        let mut out = Output { consumed, commit, ..Default::default() };
        match &self.state {
            State::Composing { buf, composer } => {
                out.preedit = buf.clone();
                out.preedit.extend(composer.preedit());
            }
            State::Converting(c) => {
                out.preedit = c.display();
                let start = c.word_start(c.selected);
                out.highlight = Some((start, c.words[c.selected].chars().count()));
                if let Some((list, i)) = &c.candidates {
                    out.candidates = list.clone();
                    out.candidate_notes = c.notes.clone();
                    out.candidate_index = Some(*i);
                }
            }
        }
        out
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    /// Spaces after 는 and 에 inside Korean runs; candidates for 학교.
    struct Fake {
        calls: usize,
        available: bool,
    }

    impl Backend for Fake {
        fn space(&mut self, text: &str) -> Option<String> {
            self.calls += 1;
            if !self.available {
                return None;
            }
            Some(spacing::space_text(text, |run| {
                let mut out = String::new();
                let chars: Vec<char> = run.chars().collect();
                for (i, c) in chars.iter().enumerate() {
                    out.push(*c);
                    if (*c == '는' || *c == '에') && i + 1 < chars.len() {
                        out.push(' ');
                    }
                }
                out
            }))
        }
        fn candidates(&mut self, word: &str) -> Vec<(String, String)> {
            match word {
                "학교에" => vec![("學校에".into(), "한자".into()), ("🏫에".into(), "이모지".into())],
                _ => vec![],
            }
        }
    }

    fn fake() -> Fake {
        Fake { calls: 0, available: true }
    }

    fn type_keys_with(s: &mut Session, b: &mut dyn Backend, keys: &str) -> String {
        let mut committed = String::new();
        for k in keys.chars() {
            let key = if k == ' ' { Key::Space } else { Key::Char(k) };
            committed.push_str(&s.handle(key, b).commit);
        }
        committed
    }

    fn type_keys(s: &mut Session, b: &mut Fake, keys: &str) -> String {
        let mut committed = String::new();
        for k in keys.chars() {
            let key = if k == ' ' { Key::Space } else { Key::Char(k) };
            committed.push_str(&s.handle(key, b).commit);
        }
        committed
    }

    #[test]
    fn space_converts_then_typing_commits_with_space() {
        let mut s = Session::default();
        let mut b = fake();
        assert_eq!(type_keys(&mut s, &mut b, "sksmsgkrrydpeksek"), "");
        let out = s.handle(Key::Char('d'), &mut b);
        assert_eq!(out.preedit, "나는학교에단당");
        s.handle(Key::Backspace, &mut b);
        let out = s.handle(Key::Space, &mut b);
        assert!(out.consumed);
        assert_eq!(out.commit, "");
        assert_eq!(out.preedit, "나는 학교에 단다");
        assert_eq!(out.highlight, Some((7, 2)));
        let out = s.handle(Key::Char('r'), &mut b);
        assert_eq!(out.commit, "나는 학교에 단다 ");
        assert_eq!(out.preedit, "ㄱ");
    }

    #[test]
    fn punctuation_attaches_after_conversion() {
        let mut s = Session::default();
        let mut b = fake();
        type_keys(&mut s, &mut b, "skdpsms ");
        let out = s.handle(Key::Char('.'), &mut b);
        assert_eq!(out.commit, "");
        assert_eq!(out.preedit, "나에 는.");
        // Enter는 확정만 하고 앱에 넘기지 않는다.
        let out = s.handle(Key::Enter, &mut b);
        assert_eq!(out.commit, "나에 는.");
        assert!(out.consumed);
        assert!(s.is_idle());
        // 이어서 입력하면 문장부호 뒤에 공백을 두고 이어 쓴다.
        type_keys(&mut s, &mut b, "skdpsms ");
        s.handle(Key::Char('?'), &mut b);
        let out = s.handle(Key::Char('g'), &mut b);
        assert_eq!(out.commit, "나에 는? ");
        // Esc는 문장부호까지 친 그대로 돌아간다.
        let mut s = Session::default();
        type_keys(&mut s, &mut b, "skdpsms ");
        s.handle(Key::Char('!'), &mut b);
        let out = s.handle(Key::Escape, &mut b);
        assert_eq!(out.preedit, "나에는!");
    }

    #[test]
    fn enter_commits_spaced_without_sending() {
        let mut s = Session::default();
        let mut b = fake();
        type_keys(&mut s, &mut b, "skdpsms");
        let out = s.handle(Key::Enter, &mut b);
        // Enter는 보이는 그대로 확정한다(스페이스 전이면 띄어쓰기 없이).
        assert_eq!(out.commit, "나에는");
        // 기본값: 조합 중 Enter는 확정만 하고 앱에 넘기지 않는다(메신저 전송 방지).
        assert!(out.consumed);
        // 다음 Enter는 빈 상태라 앱으로 간다.
        let out = s.handle(Key::Enter, &mut b);
        assert!(!out.consumed);
        // 설정을 켜면 확정과 함께 Enter도 넘긴다.
        let mut s = Session::new(Options { enter_passes_through: true, ..Options::default() });
        type_keys(&mut s, &mut b, "skdpsms");
        let out = s.handle(Key::Enter, &mut b);
        assert_eq!(out.commit, "나에는");
        assert!(!out.consumed);
        // Enter in conversion only accepts.
        type_keys(&mut s, &mut b, "skdpsms ");
        let out = s.handle(Key::Enter, &mut b);
        assert_eq!(out.commit, "나에 는");
        assert!(out.consumed);
    }

    #[test]
    fn escape_restores_typed_text() {
        let mut s = Session::default();
        let mut b = fake();
        type_keys(&mut s, &mut b, "skdpsms ");
        let out = s.handle(Key::Escape, &mut b);
        assert_eq!(out.preedit, "나에는");
        assert!(!s.is_converting());
        let out = s.handle(Key::Escape, &mut b);
        assert_eq!(out.commit, "나에는");
        assert!(!out.consumed);
    }

    #[test]
    fn backspace_in_conversion_edits_typed_text() {
        let mut s = Session::default();
        let mut b = fake();
        type_keys(&mut s, &mut b, "skdpsms ");
        let out = s.handle(Key::Backspace, &mut b);
        assert_eq!(out.preedit, "나에");
    }

    #[test]
    fn candidates_and_word_selection() {
        let mut s = Session::default();
        let mut b = fake();
        type_keys(&mut s, &mut b, "skdpgkrrydp ");
        // "나에 학교에" -> select 학교에 (last word) and open candidates.
        let out = s.handle(Key::Down, &mut b);
        assert_eq!(out.preedit, "나에 學校에");
        assert_eq!(out.candidates, vec!["학교에", "學校에", "🏫에", "hakgyoe", "hakkyoe", "hak.kyoey"]);
        assert_eq!(out.candidate_notes, vec!["", "한자", "이모지", "로마자 2000", "매큔라이샤워", "예일"]);
        assert_eq!(out.candidate_index, Some(1));
        let out = s.handle(Key::Down, &mut b);
        assert_eq!(out.preedit, "나에 🏫에");
        let out = s.handle(Key::Escape, &mut b);
        assert_eq!(out.preedit, "나에 학교에");
        assert!(out.candidates.is_empty());
        let out = s.handle(Key::Left, &mut b);
        assert_eq!(out.highlight, Some((0, 2)));
        // A word the backend knows nothing about still gets romanizations.
        let out = s.handle(Key::Down, &mut b);
        assert_eq!(out.preedit, "nae 학교에");
        s.handle(Key::Escape, &mut b);
        s.handle(Key::Right, &mut b);
        s.handle(Key::Down, &mut b);
        let out = s.handle(Key::Char('3'), &mut b);
        assert_eq!(out.preedit, "나에 🏫에");
        let out = s.handle(Key::Enter, &mut b);
        assert_eq!(out.commit, "나에 🏫에");
    }

    #[test]
    fn shift_space_commits_as_typed() {
        let mut s = Session::default();
        let mut b = fake();
        // 자동 띄어쓰기라면 「나에 는」이 될 문장도 친 그대로 확정하고 공백만 더한다.
        type_keys(&mut s, &mut b, "skdpsms");
        let out = s.handle(Key::ShiftSpace, &mut b);
        assert_eq!(out.commit, "나에는 ");
        assert!(out.preedit.is_empty() && out.consumed);
        assert_eq!(b.calls, 0);
        let out = s.handle(Key::Char('d'), &mut b);
        assert_eq!(out.preedit, "ㅇ");
        // 아무것도 치지 않았으면 앱에 그대로 넘긴다.
        let mut idle = Session::default();
        assert!(!idle.handle(Key::ShiftSpace, &mut b).consumed);
    }

    #[test]
    fn unavailable_backend_keeps_text() {
        let mut s = Session::default();
        let mut b = Fake { calls: 0, available: false };
        type_keys(&mut s, &mut b, "skdpsms ");
        let out = s.handle(Key::Enter, &mut b);
        assert_eq!(out.commit, "나에는");
    }

    #[test]
    fn idle_keys_pass_through() {
        let mut s = Session::default();
        let mut b = fake();
        for k in [Key::Space, Key::Backspace, Key::Enter, Key::Left, Key::Escape, Key::Other] {
            let out = s.handle(k, &mut b);
            assert!(!out.consumed, "{k:?}");
            assert_eq!(out.commit, "");
        }
        assert_eq!(b.calls, 0);
        let out = s.handle(Key::Char('\\'), &mut b);
        assert_eq!(out.commit, "\\");
        let out = s.handle(Key::Char('3'), &mut b);
        assert_eq!(out.preedit, "3");
    }

    #[test]
    fn shortcuts_commit_spaced_and_pass_through() {
        let mut s = Session::default();
        let mut b = fake();
        type_keys(&mut s, &mut b, "skdpsms");
        let out = s.handle(Key::Other, &mut b);
        assert_eq!(out.commit, "나에 는");
        assert!(!out.consumed);
        assert!(s.is_idle());
    }

    #[test]
    fn plain_mode_space_commits() {
        let mut s = Session::new(Options { convert_on_space: false, ..Options::default() });
        let mut b = fake();
        let c = type_keys(&mut s, &mut b, "skdpsms ");
        assert_eq!(c, "나에는 ");
        assert_eq!(b.calls, 0);
    }

    #[test]
    fn space_cycles_candidates_by_default() {
        let mut s = Session::default();
        let mut b = fake();
        type_keys(&mut s, &mut b, "skdpgkrrydp ");
        let out = s.handle(Key::Space, &mut b);
        assert_eq!(out.preedit, "나에 學校에");
        assert_eq!(out.candidate_index, Some(1));
        let out = s.handle(Key::Space, &mut b);
        assert_eq!(out.preedit, "나에 🏫에");
        for want in ["hakgyoe", "hakkyoe", "hak.kyoey", "학교에"] {
            let out = s.handle(Key::Space, &mut b);
            assert_eq!(out.preedit, format!("나에 {want}"), "romanizations last, then wrap");
        }
    }

    #[test]
    fn lone_jamo_offer_half_width_hangul() {
        assert_eq!(jamo_width_variant("ㄱ"), Some(("\u{FFA1}".to_string(), "반각")));
        assert_eq!(jamo_width_variant("ㅋㅋ"), Some(("\u{FFBB}\u{FFBB}".to_string(), "반각")));
        assert_eq!(jamo_width_variant("ㅏㅣㅢ"), Some(("\u{FFC2}\u{FFDC}\u{FFDB}".to_string(), "반각")));
        assert_eq!(jamo_width_variant("\u{FFA1}\u{FFC2}"), Some(("ㄱㅏ".to_string(), "호환 자모")));
        assert_eq!(jamo_width_variant("가"), None);
        assert_eq!(jamo_width_variant("ㄱ가"), None);
        let mut none = Fake { calls: 0, available: false };
        let (list, notes) = candidate_list("ㄱ", &mut none);
        assert_eq!(list[1], "\u{FFA1}");
        assert_eq!(notes[1], "반각");
    }

    #[test]
    fn every_word_has_candidates() {
        let mut s = Session::default();
        let mut b = Fake { calls: 0, available: false };
        type_keys(&mut s, &mut b, "dkssudgktpdy ");
        let out = s.handle(Key::Space, &mut b);
        assert_eq!(out.candidates, vec!["안녕하세요", "annyeonghaseyo", "annyŏnghaseyo", "annyenghaseyyo"]);
        // Words without Hangul fall back to a width variant.
        let mut s = Session::default();
        type_keys(&mut s, &mut b, "2026 ");
        let out = s.handle(Key::Space, &mut b);
        assert_eq!(out.candidates, vec!["2026", "２０２６"]);
        assert_eq!(out.candidate_notes[1], "전각");
    }

    #[test]
    fn number_keys_pick_within_the_page() {
        struct Many;
        impl Backend for Many {
            fn space(&mut self, text: &str) -> Option<String> {
                Some(text.to_string())
            }
            fn candidates(&mut self, _word: &str) -> Vec<(String, String)> {
                (0..20).map(|i| (format!("c{i}"), String::new())).collect()
            }
        }
        let mut s = Session::default();
        let mut b = Many;
        type_keys_with(&mut s, &mut b, "rk ");
        for _ in 0..10 {
            s.handle(Key::Down, &mut b);
        }
        // Index 10 is on the second page (9..18); key 2 picks index 10.
        let out = s.handle(Key::Char('2'), &mut b);
        assert_eq!(out.preedit, "c9");
    }

    #[test]
    fn cycle_mode() {
        let mut s = Session::new(Options { space_in_conversion: SpaceInConversion::Cycle, ..Options::default() });
        let mut b = fake();
        type_keys(&mut s, &mut b, "gkrrydp ");
        let out = s.handle(Key::Space, &mut b);
        assert_eq!(out.preedit, "學校에");
        let out = s.handle(Key::Enter, &mut b);
        assert_eq!(out.commit, "學校에");
        type_keys(&mut s, &mut b, "sk ");
        let out = s.handle(Key::Space, &mut b);
        assert_eq!(out.preedit, "na");
    }

    #[test]
    fn commit_mode_space_accepts() {
        let mut s = Session::new(Options { space_in_conversion: SpaceInConversion::Commit, ..Options::default() });
        let mut b = fake();
        type_keys(&mut s, &mut b, "gkrrydp ");
        let out = s.handle(Key::Space, &mut b);
        assert_eq!(out.commit, "학교에 ");
    }
}
