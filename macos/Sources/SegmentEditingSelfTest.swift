import AppKit

/// Public fixed strings only. The same checks run in the app's --self-test and
/// the standalone native harness; neither accesses an actual client document.
enum SegmentEditingSelfTest {
    static func run(check: (String, Bool, String) -> Void) {
        let s = hc_session_new()!
        defer { hc_session_free(s) }
        var out = hc_output()
        func key(_ code: Int) { hc_session_key(s, UInt32(code), 0, nil, &out) }
        func text() -> String { String(cString: out.preedit) }
        func load(_ value: String) {
            hc_session_reset(s, &out)
            value.withCString { hc_session_edit_selection(s, $0, &out) }
        }
        load("학교에간다")
        key(HC_KEY_SHRINK_SEGMENT)
        key(HC_KEY_SHRINK_SEGMENT)
        check("segment: split", text() == "학교에 간다", text())
        key(HC_KEY_MERGE_NEXT)
        key(HC_KEY_ENTER)
        check("segment: manual commit", String(cString: out.commit) == "학교에간다", String(cString: out.commit))
        load("앞 👨‍👩‍👧‍👦한e\u{301}")
        key(HC_KEY_SHRINK_SEGMENT)
        let expected = "앞 👨‍👩‍👧‍👦한 e\u{301}"
        check("segment: UTF-16 highlight", text() == expected && out.highlight_start == 2
              && out.highlight_len == ("👨‍👩‍👧‍👦한" as NSString).length,
              "start=\(out.highlight_start), length=\(out.highlight_len)")
        key(HC_KEY_ESCAPE)
        check("segment: selection cancel", String(cString: out.commit) == "앞 👨‍👩‍👧‍👦한e\u{301}", "verbatim original restored")
        load("학교에간다")
        key(HC_KEY_SHRINK_SEGMENT)
        key(HC_KEY_SHRINK_SEGMENT)
        key(HC_KEY_BACKSPACE)
        check("segment: edited backspace", text() == "학교에 간" && out.highlight_start >= 0,
              "manual boundaries retained")
        key(HC_KEY_ESCAPE)
        check("segment: backspace cancel", String(cString: out.commit) == "학교에간다", "original selection retained")
        load("e\u{301}가")
        key(HC_KEY_BACKSPACE)
        key(HC_KEY_BACKSPACE)
        check("segment: empty selection still cancellable", text().isEmpty && out.highlight_start == 0 && out.highlight_len == 0,
              "combining mark deleted together with its base")
        key(HC_KEY_ESCAPE)
        check("segment: empty selection cancel", String(cString: out.commit) == "e\u{301}가", "complete original restored")
        hc_session_reset(s, &out)
        for scalar in "rksk".unicodeScalars {
            hc_session_key(s, UInt32(HC_KEY_CHAR), scalar.value, nil, &out)
        }
        key(HC_KEY_SPACE)
        key(HC_KEY_SHRINK_SEGMENT)
        key(HC_KEY_BACKSPACE)
        check("segment: typed manual boundary backspace", text() == "가 " && out.highlight_start >= 0,
              "manual boundary retained for ordinary keyboard input")
        key(HC_KEY_ESCAPE)
        check("segment: typed manual boundary cancel", text() == "가나" && String(cString: out.commit).isEmpty
              && out.highlight_start < 0, "typed original restored as unconverted composition")

        // 합치기 단추 없이 ⇧←/⇧→ 두 키만으로: 늘리기를 거듭하면 다음 어절과 합쳐진다.
        load("학교 에간다")
        key(HC_KEY_LEFT)
        key(HC_KEY_EXPAND_SEGMENT)
        check("segment: expand fixes split", text() == "학교에 간다", text())
        key(HC_KEY_EXPAND_SEGMENT)
        key(HC_KEY_EXPAND_SEGMENT)
        check("segment: expand merges next", text() == "학교에간다"
              && hc_session_segment_actions(s) & UInt32(HC_SEGMENT_EXPAND) == 0, text())
        load("내일 학교에")
        key(HC_KEY_LEFT)
        for _ in 0..<3 { key(HC_KEY_EXPAND_SEGMENT) }
        check("segment: previous word merge by keys", text() == "내일학교에", text())

        // Independent Swift Character boundaries validate the Rust FFI offsets.
        let atoms = ["가", "한", "e\u{301}", "👨‍👩‍👧‍👦", "🇰🇷", "👍🏽", "1️⃣", "क्ष"]
        var unicodeOK = true
        var combinations = 0
        for left in atoms { for right in atoms {
            let original = "\(left)\(right)가"
            load(original)
            key(HC_KEY_SHRINK_SEGMENT)
            key(HC_KEY_SHRINK_SEGMENT)
            let expected = "\(left) \(right)가"
            unicodeOK = unicodeOK && text() == expected
                && out.preedit_utf16_len == expected.utf16.count
                && out.highlight_start == 0 && out.highlight_len == left.utf16.count
            key(HC_KEY_MERGE_NEXT)
            unicodeOK = unicodeOK && text() == original
            combinations += 1
        }}
        check("segment: native Unicode oracle", unicodeOK, "\(combinations) combinations, Swift Character / UTF-16")

        func event(_ code: UInt16, _ flags: NSEvent.ModifierFlags) -> NSEvent {
            NSEvent.keyEvent(with: .keyDown, location: .zero, modifierFlags: flags,
                             timestamp: 0, windowNumber: 0, context: nil,
                             characters: "", charactersIgnoringModifiers: "", isARepeat: false, keyCode: code)!
        }
        check("segment: Shift arrows", KeyMapping.coreKey(for: event(123, .shift)).0 == UInt32(HC_KEY_SHRINK_SEGMENT)
              && KeyMapping.coreKey(for: event(124, .shift)).0 == UInt32(HC_KEY_EXPAND_SEGMENT)
              && KeyMapping.coreKey(for: event(123, [.shift, .command])).0 == UInt32(HC_KEY_OTHER),
              "Shift only resizes; Command/Option/Control retain shortcut behavior")
        check("segment: selection shortcut", KeyMapping.isEditSelection(event(15, [.control, .shift]))
              && !KeyMapping.isEditSelection(event(15, [.control, .shift, .command]))
              && !KeyMapping.isEditSelection(event(15, [.control])), "Control+Shift+R only")

        let requested = NSRange(location: 7, length: 3)
        let valid = SelectionEditing.read(range: requested) { range, actual in actual = range; return "😀가" }
        let partial = SelectionEditing.read(range: requested) { _, actual in actual = NSRange(location: 8, length: 2); return "가나" }
        let wrongLength = SelectionEditing.read(range: requested) { range, actual in actual = range; return "가" }
        let null = SelectionEditing.read(range: requested) { range, actual in actual = range; return "가\0나" }
        var invalidRead = false
        let missing = SelectionEditing.read(range: NSRange(location: NSNotFound, length: NSNotFound)) { _, _ in invalidRead = true; return nil }
        check("segment: exact selected range", valid?.range == requested && valid?.text == "😀가"
              && partial == nil && wrongLength == nil && null == nil && missing == nil && !invalidRead,
              "mismatched, missing and NUL selections rejected before replacement")
    }
}
