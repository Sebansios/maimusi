//! Compact syllable n-gram spacing model ("HSPM" binary) and Viterbi decoder.
//!
//! Every syllable gap gets a log-odds score from surrounding n-gram and
//! morphology features; a segment-level DP then picks the best split using
//! word bonuses and an optional morphological plausibility penalty.
//!
//! File layout (little endian):
//! ```text
//! "HSPM" u32:version
//! f32: prior, space_penalty, oov_char, w_morph   u32: max_word
//! u32: family_count, then f32 default weight per family
//! table: features (key = family byte + UTF-8 value, weight = log-odds contribution)
//! table: words    (key = UTF-8 word, weight = word bonus)
//! table: nouns    (weights empty)
//! table: stems    (weights empty)
//! table = u32 count, u32 blob_len, u32 offsets[count + 1], blob, f32 weights[count or 0]
//! ```
//! Keys in each table are sorted bytewise for binary search, so the whole file
//! can be used in place without building hash maps.

use super::morph;
use std::fmt;

pub mod family {
    pub const P: u8 = 0;
    pub const L: u8 = 1;
    pub const R: u8 = 2;
    pub const TL: u8 = 3;
    pub const TR: u8 = 4;
    pub const JL: u8 = 5;
    pub const EL: u8 = 6;
    pub const UR: u8 = 7;
    pub const ADNU: u8 = 8;
    pub const COUNT: usize = 9;
}

const MAGIC: &[u8; 4] = b"HSPM";
const VERSION: u32 = 1;

#[derive(Debug)]
pub struct ModelError(pub String);

impl fmt::Display for ModelError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(f, "spacing model: {}", self.0)
    }
}

impl std::error::Error for ModelError {}

struct Reader<'a> {
    buf: &'a [u8],
    pos: usize,
}

impl<'a> Reader<'a> {
    fn take(&mut self, n: usize) -> Result<&'a [u8], ModelError> {
        let end = self.pos.checked_add(n).filter(|&e| e <= self.buf.len());
        let end = end.ok_or_else(|| ModelError("truncated file".into()))?;
        let s = &self.buf[self.pos..end];
        self.pos = end;
        Ok(s)
    }
    fn u32(&mut self) -> Result<u32, ModelError> {
        Ok(u32::from_le_bytes(self.take(4)?.try_into().unwrap()))
    }
    fn f32(&mut self) -> Result<f32, ModelError> {
        Ok(f32::from_le_bytes(self.take(4)?.try_into().unwrap()))
    }
}

/// Sorted key table stored as byte ranges into the model buffer.
struct Table {
    count: usize,
    offsets: usize,
    blob: usize,
    weights: Option<usize>,
}

impl Table {
    fn read(r: &mut Reader, weighted: bool) -> Result<Table, ModelError> {
        let count = r.u32()? as usize;
        let blob_len = r.u32()? as usize;
        let offsets = r.pos;
        r.take((count + 1) * 4)?;
        let blob = r.pos;
        r.take(blob_len)?;
        let weights = if weighted {
            let at = r.pos;
            r.take(count * 4)?;
            Some(at)
        } else {
            None
        };
        let t = Table { count, offsets, blob, weights };
        // Validate offsets once so lookups can index without checks failing.
        let mut prev = 0;
        for i in 0..=count {
            let o = t.offset(r.buf, i);
            if o < prev || o > blob_len {
                return Err(ModelError("corrupt key offsets".into()));
            }
            prev = o;
        }
        Ok(t)
    }

    fn offset(&self, buf: &[u8], i: usize) -> usize {
        let at = self.offsets + i * 4;
        u32::from_le_bytes(buf[at..at + 4].try_into().unwrap()) as usize
    }

    fn key<'b>(&self, buf: &'b [u8], i: usize) -> &'b [u8] {
        &buf[self.blob + self.offset(buf, i)..self.blob + self.offset(buf, i + 1)]
    }

    fn find(&self, buf: &[u8], key: &[u8]) -> Option<usize> {
        let (mut lo, mut hi) = (0, self.count);
        while lo < hi {
            let mid = (lo + hi) / 2;
            match self.key(buf, mid).cmp(key) {
                std::cmp::Ordering::Less => lo = mid + 1,
                std::cmp::Ordering::Greater => hi = mid,
                std::cmp::Ordering::Equal => return Some(mid),
            }
        }
        None
    }

    fn weight(&self, buf: &[u8], i: usize) -> f32 {
        let at = self.weights.expect("weighted table") + i * 4;
        f32::from_le_bytes(buf[at..at + 4].try_into().unwrap())
    }
}

pub struct NgramModel {
    buf: Vec<u8>,
    prior: f32,
    space_penalty: f32,
    oov_char: f32,
    w_morph: f32,
    max_word: usize,
    defaults: [f32; family::COUNT],
    feats: Table,
    words: Table,
    nouns: Table,
    stems: Table,
    use_lexicon: bool,
}

impl NgramModel {
    pub fn from_bytes(buf: Vec<u8>) -> Result<NgramModel, ModelError> {
        let mut r = Reader { buf: &buf, pos: 0 };
        if r.take(4)? != MAGIC {
            return Err(ModelError("not an HSPM file".into()));
        }
        let version = r.u32()?;
        if version != VERSION {
            return Err(ModelError(format!("unsupported version {version}")));
        }
        let prior = r.f32()?;
        let space_penalty = r.f32()?;
        let oov_char = r.f32()?;
        let w_morph = r.f32()?;
        let max_word = r.u32()? as usize;
        let fams = r.u32()? as usize;
        if fams != family::COUNT || max_word == 0 || max_word > 64 {
            return Err(ModelError("unexpected header values".into()));
        }
        let mut defaults = [0f32; family::COUNT];
        for d in defaults.iter_mut() {
            *d = r.f32()?;
        }
        let feats = Table::read(&mut r, true)?;
        let words = Table::read(&mut r, true)?;
        let nouns = Table::read(&mut r, false)?;
        let stems = Table::read(&mut r, false)?;
        let use_lexicon = nouns.count > 0 && w_morph != 0.0;
        drop(r);
        Ok(NgramModel {
            buf,
            prior,
            space_penalty,
            oov_char,
            w_morph,
            max_word,
            defaults,
            feats,
            words,
            nouns,
            stems,
            use_lexicon,
        })
    }

    pub fn load(path: &std::path::Path) -> Result<NgramModel, ModelError> {
        let buf = std::fs::read(path).map_err(|e| ModelError(format!("{}: {e}", path.display())))?;
        Self::from_bytes(buf)
    }

    /// Enable or disable the morphological word-plausibility term.
    pub fn set_lexicon(&mut self, on: bool) {
        self.use_lexicon = on && self.nouns.count > 0 && self.w_morph != 0.0;
    }

    pub fn feature_count(&self) -> usize {
        self.feats.count
    }

    fn feature_weight(&self, fam: u8, value: &str, key: &mut Vec<u8>) -> f32 {
        key.clear();
        key.push(fam);
        key.extend_from_slice(value.as_bytes());
        match self.feats.find(&self.buf, key) {
            Some(i) => self.feats.weight(&self.buf, i),
            None => self.defaults[fam as usize],
        }
    }

    /// Log-odds that a space belongs at gap `i` of `text` (`text[i-1] | text[i]`).
    pub fn gap_logodds(&self, text: &[char], i: usize) -> f32 {
        let n = text.len();
        let l = text[i - 1];
        let r = text[i];
        let ll = if i >= 2 { text[i - 2] } else { '^' };
        let rr = if i + 1 < n { text[i + 1] } else { '$' };
        let mut key = Vec::with_capacity(16);
        let mut s = String::with_capacity(12);
        let mut lo = self.prior;
        let mut add = |fam: u8, chars: &[char], s: &mut String, key: &mut Vec<u8>| {
            s.clear();
            s.extend(chars);
            lo += self.feature_weight(fam, s, key);
        };
        add(family::P, &[l, r], &mut s, &mut key);
        add(family::L, &[l], &mut s, &mut key);
        add(family::R, &[r], &mut s, &mut key);
        add(family::TL, &[ll, l, r], &mut s, &mut key);
        add(family::TR, &[l, r, rr], &mut s, &mut key);
        let mut morph_feats = Vec::new();
        morph::gap_features(text, i, &mut morph_feats);
        for (fam, value) in morph_feats {
            lo += self.feature_weight(fam, &value, &mut key);
        }
        lo
    }

    fn word_bonus(&self, tok: &[char], key: &mut String) -> f32 {
        key.clear();
        key.extend(tok);
        match self.words.find(&self.buf, key.as_bytes()) {
            Some(i) => self.words.weight(&self.buf, i),
            None => tok.len() as f32 * self.oov_char,
        }
    }

    fn in_table(&self, t: &Table, w: &[char]) -> bool {
        let s: String = w.iter().collect();
        t.find(&self.buf, s.as_bytes()).is_some()
    }

    /// Space a run that contains no spaces. Returns the chosen cut positions.
    pub fn cuts(&self, text: &[char]) -> Vec<usize> {
        let n = text.len();
        if n <= 1 {
            return Vec::new();
        }
        let mut cut = vec![0f32; n];
        let mut nocut = vec![0f32; n];
        for i in 1..n {
            let lo = self.gap_logodds(text, i);
            cut[i] = -softplus(-lo);
            nocut[i] = -softplus(lo);
        }
        let mut pn = vec![0f32; n];
        for k in 1..n {
            pn[k] = pn[k - 1] + nocut[k];
        }
        let mut dp = vec![f32::NEG_INFINITY; n + 1];
        let mut back = vec![0usize; n + 1];
        dp[0] = 0.0;
        let mut key = String::new();
        for i in 1..=n {
            let j0 = i.saturating_sub(self.max_word);
            for j in j0..i {
                if dp[j] == f32::NEG_INFINITY {
                    continue;
                }
                let internal = if i - 1 >= j { pn[i - 1] - pn[j] } else { 0.0 };
                let tok = &text[j..i];
                let mut score = dp[j] + internal + self.word_bonus(tok, &mut key);
                if self.use_lexicon {
                    score += self.w_morph
                        * morph::token_score(
                            tok,
                            |w| self.in_table(&self.nouns, w),
                            |w| self.in_table(&self.stems, w),
                        );
                }
                if j > 0 {
                    score += cut[j] - self.space_penalty;
                }
                if score > dp[i] {
                    dp[i] = score;
                    back[i] = j;
                }
            }
        }
        let mut cuts = Vec::new();
        let mut i = n;
        while i > 0 {
            let j = back[i];
            if j > 0 {
                cuts.push(j);
            }
            i = j;
        }
        cuts.reverse();
        cuts
    }

    /// Space a run without spaces.
    pub fn space_run(&self, run: &str) -> String {
        let text: Vec<char> = run.chars().collect();
        let cuts = self.cuts(&text);
        let mut out = String::with_capacity(run.len() + cuts.len());
        let mut next = cuts.iter().peekable();
        for (i, c) in text.iter().enumerate() {
            if next.peek() == Some(&&i) {
                out.push(' ');
                next.next();
            }
            out.push(*c);
        }
        out
    }
}

fn softplus(x: f32) -> f32 {
    if x > 30.0 {
        x
    } else if x < -30.0 {
        0.0
    } else {
        x.exp().ln_1p()
    }
}

/// Serialise a model; used by tools and tests.
pub struct ModelWriter {
    pub prior: f32,
    pub space_penalty: f32,
    pub oov_char: f32,
    pub w_morph: f32,
    pub max_word: u32,
    pub defaults: [f32; family::COUNT],
    pub feats: Vec<(Vec<u8>, f32)>,
    pub words: Vec<(String, f32)>,
    pub nouns: Vec<String>,
    pub stems: Vec<String>,
}

impl ModelWriter {
    pub fn to_bytes(mut self) -> Vec<u8> {
        let mut out = Vec::new();
        out.extend_from_slice(MAGIC);
        out.extend_from_slice(&VERSION.to_le_bytes());
        for v in [self.prior, self.space_penalty, self.oov_char, self.w_morph] {
            out.extend_from_slice(&v.to_le_bytes());
        }
        out.extend_from_slice(&self.max_word.to_le_bytes());
        out.extend_from_slice(&(family::COUNT as u32).to_le_bytes());
        for d in self.defaults {
            out.extend_from_slice(&d.to_le_bytes());
        }
        self.feats.sort_by(|a, b| a.0.cmp(&b.0));
        write_table(&mut out, self.feats.iter().map(|(k, w)| (k.as_slice(), Some(*w))), true);
        self.words.sort_by(|a, b| a.0.as_bytes().cmp(b.0.as_bytes()));
        write_table(&mut out, self.words.iter().map(|(k, w)| (k.as_bytes(), Some(*w))), true);
        self.nouns.sort();
        write_table(&mut out, self.nouns.iter().map(|k| (k.as_bytes(), None)), false);
        self.stems.sort();
        write_table(&mut out, self.stems.iter().map(|k| (k.as_bytes(), None)), false);
        out
    }
}

fn write_table<'a>(out: &mut Vec<u8>, rows: impl Iterator<Item = (&'a [u8], Option<f32>)>, weighted: bool) {
    let rows: Vec<_> = rows.collect();
    let blob_len: usize = rows.iter().map(|r| r.0.len()).sum();
    out.extend_from_slice(&(rows.len() as u32).to_le_bytes());
    out.extend_from_slice(&(blob_len as u32).to_le_bytes());
    let mut off = 0u32;
    out.extend_from_slice(&off.to_le_bytes());
    for r in &rows {
        off += r.0.len() as u32;
        out.extend_from_slice(&off.to_le_bytes());
    }
    for r in &rows {
        out.extend_from_slice(r.0);
    }
    if weighted {
        for r in &rows {
            out.extend_from_slice(&r.1.unwrap_or(0.0).to_le_bytes());
        }
    }
}

#[cfg(test)]
pub(crate) fn tiny_model() -> NgramModel {
    // A hand-made model: strong space after 는/에, a few known words.
    let mut feats = Vec::new();
    for (l, r, w) in [('는', '학', 4.0f32), ('에', '간', 4.0), ('학', '교', -4.0), ('간', '다', -4.0), ('나', '는', -4.0), ('교', '에', -4.0)] {
        let mut k = vec![family::P];
        k.extend_from_slice(format!("{l}{r}").as_bytes());
        feats.push((k, w));
    }
    let words = vec![("나는".to_string(), 2.0f32), ("학교에".into(), 2.0), ("간다".into(), 2.0)];
    ModelWriter {
        prior: -0.7,
        space_penalty: 0.0,
        oov_char: -0.55,
        w_morph: 0.0,
        max_word: 12,
        defaults: [0.0; family::COUNT],
        feats,
        words,
        nouns: vec![],
        stems: vec![],
    }
    .to_bytes()
    .pipe(|b| NgramModel::from_bytes(b).unwrap())
}

#[cfg(test)]
trait Pipe: Sized {
    fn pipe<T>(self, f: impl FnOnce(Self) -> T) -> T {
        f(self)
    }
}
#[cfg(test)]
impl<T> Pipe for T {}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn roundtrip_and_decode() {
        let m = tiny_model();
        assert_eq!(m.space_run("나는학교에간다"), "나는 학교에 간다");
        assert_eq!(m.space_run("가"), "가");
        assert_eq!(m.space_run(""), "");
    }

    #[test]
    fn rejects_garbage() {
        assert!(NgramModel::from_bytes(b"nope".to_vec()).is_err());
        let mut b = tiny_model().buf.clone();
        b.truncate(b.len() - 3);
        assert!(NgramModel::from_bytes(b).is_err());
    }
}
