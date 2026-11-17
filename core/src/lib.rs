//! Core of the Hangul auto-spacing input method.
//!
//! * `composer` / `layout` — Hangul composition from key presses.
//! * `spacing` — the light spacing model and text-level safety checks.
//! * `session` — the IME state machine every platform front end drives.
//! * `ffi` — C ABI for Swift (macOS/iOS) and other native front ends.
//!
//! Nothing here logs, stores or transmits typed text.

pub mod composer;
pub mod ffi;
pub mod jamo;
pub mod layout;
pub mod romanize;
pub mod session;
pub mod spacing;

pub use session::{Backend, Key, Options, Output, Session, SpaceInConversion};
pub use spacing::{LightSpacer, NgramModel};

/// Backend that uses only the light in-process model.
pub struct LightBackend<'a> {
    pub spacer: Option<&'a LightSpacer>,
}

impl Backend for LightBackend<'_> {
    fn space(&mut self, text: &str) -> Option<String> {
        self.spacer.map(|s| s.space(text))
    }

    fn candidates(&mut self, _word: &str) -> Vec<(String, String)> {
        Vec::new()
    }
}
