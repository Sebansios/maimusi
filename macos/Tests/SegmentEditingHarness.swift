import AppKit

/// Standalone executable, never an IMK server or registered input source.
@main enum SegmentEditingHarness {
    static func main() {
        let app = NSApplication.shared
        app.setActivationPolicy(.accessory)
        var failures = 0
        func check(_ label: String, _ ok: Bool, _ detail: String) {
            print("\(ok ? "PASS" : "FAIL") \(label): \(detail)")
            if !ok { failures += 1 }
        }
        SegmentEditingSelfTest.run(check: check)

        let session = hc_session_new()!
        defer { hc_session_free(session) }
        var out = hc_output()
        let prefix = "앞부분 "
        let original = "학교에간다"
        let suffix = " 뒷부분"
        let document = prefix + original + suffix
        let selected = NSRange(location: prefix.utf16.count, length: original.utf16.count)
        let markedState = MarkedTextState()
        let textView = NSTextView(frame: NSRect(x: 0, y: 0, width: 550, height: 90))
        textView.font = .systemFont(ofSize: 22)
        textView.string = document
        textView.setSelectedRange(selected)
        let window = NSWindow(contentRect: NSRect(x: 300, y: 450, width: 550, height: 90),
                              styleMask: [.titled], backing: .buffered, defer: false)
        window.title = "분절 편집 검증 — 독립 AppKit 테스트"
        window.contentView = textView
        window.orderFrontRegardless()
        original.withCString { hc_session_edit_selection(session, $0, &out) }
        func apply(_ replacement: NSRange = NSRange(location: NSNotFound, length: 0)) {
            let commit = String(cString: out.commit)
            let preedit = String(cString: out.preedit)
            let marked = NSMutableAttributedString(string: preedit, attributes: [.underlineStyle: NSUnderlineStyle.single.rawValue])
            let highlight = NSRange(location: Int(out.highlight_start), length: Int(out.highlight_len))
            if highlight.location >= 0 && NSMaxRange(highlight) <= marked.length {
                marked.addAttribute(.backgroundColor, value: NSColor.selectedTextBackgroundColor.withAlphaComponent(0.25), range: highlight)
            }
            markedState.apply(commit: commit, preedit: marked, converting: out.highlight_start >= 0,
                              initialReplacement: replacement.location == NSNotFound ? nil : replacement,
                              target: .init(markedRange: { textView.markedRange() },
                                            insert: { textView.insertText($0, replacementRange: $1) },
                                            mark: { textView.setMarkedText($0, selectedRange: $1, replacementRange: $2) }))
        }
        apply(selected)
        let panel = CandidatePanel.shared
        func showPanel() {
            panel.show([], notes: [], selected: -1, segmentActions: hc_session_segment_actions(session),
                       below: NSRect(x: 310, y: 455, width: 1, height: 25))
        }
        var clicked = 0
        panel.onSegmentAction = { key in
            clicked += 1
            hc_session_key(session, key, 0, nil, &out)
            apply()
            showPanel()
        }
        func buttons(_ view: NSView) -> [NSButton] {
            view.subviews.flatMap { subview in
                (subview as? NSButton).map { [$0] } ?? buttons(subview)
            }
        }
        showPanel()
        for _ in 0..<2 {
            buttons(panel.contentView!).first { $0.tag == HC_KEY_SHRINK_SEGMENT }!.performClick(nil)
        }
        check("native panel click changes marked document", clicked == 2 && textView.string == prefix + "학교에 간다" + suffix,
              "two split clicks, surrounding text unchanged")
        let firstButtons = buttons(panel.contentView!)
        check("native panel action availability", firstButtons.count == 4
              && firstButtons.first { $0.tag == HC_KEY_MERGE_PREVIOUS }?.isEnabled == false
              && firstButtons.first { $0.tag == HC_KEY_MERGE_NEXT }?.isEnabled == true,
              "four visible actions with valid/invalid boundary states")

        RunLoop.current.run(until: Date().addingTimeInterval(0.05))
        if CommandLine.arguments.count > 1 {
            let directory = URL(fileURLWithPath: CommandLine.arguments[1], isDirectory: true)
            try! FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
            for (name, view) in [("segment-panel.png", panel.contentView!), ("segment-marked-text.png", textView)] {
                view.layoutSubtreeIfNeeded()
                let bitmap = view.bitmapImageRepForCachingDisplay(in: view.bounds)!
                view.cacheDisplay(in: view.bounds, to: bitmap)
                try! bitmap.representation(using: .png, properties: [:])!.write(to: directory.appendingPathComponent(name))
            }
        }
        hc_session_key(session, UInt32(HC_KEY_ENTER), 0, nil, &out)
        apply()
        check("native marked range commit", textView.string == prefix + "학교에 간다" + suffix && !textView.hasMarkedText(),
              "changed-length selection committed without surrounding replacement")
        // Repeat with Escape after replacement length changes.
        textView.string = document
        original.withCString { hc_session_edit_selection(session, $0, &out) }
        apply(selected)
        hc_session_key(session, UInt32(HC_KEY_SHRINK_SEGMENT), 0, nil, &out)
        apply()
        hc_session_key(session, UInt32(HC_KEY_ESCAPE), 0, nil, &out)
        apply()
        check("native marked range cancel", textView.string == document && !textView.hasMarkedText(), "original document restored")
        // Production and harness share MarkedTextState, including empty output.
        let single = "e\u{301}가"
        let singleDocument = prefix + single + suffix
        let singleRange = NSRange(location: prefix.utf16.count, length: single.utf16.count)
        for finish in ["escape", "enter", "focus", "reset", "type"] {
            textView.string = singleDocument
            single.withCString { hc_session_edit_selection(session, $0, &out) }
            apply(singleRange)
            hc_session_key(session, UInt32(HC_KEY_BACKSPACE), 0, nil, &out)
            apply()
            hc_session_key(session, UInt32(HC_KEY_BACKSPACE), 0, nil, &out)
            apply()
            check("native delete to empty (\(finish))", textView.string == prefix + suffix && markedState.isActive,
                  "selection erased, surrounding text and cancel state retained")
            if finish == "escape" {
                // A zero-length replacement must use the saved document anchor,
                // even when the client's current selection no longer identifies it.
                textView.setSelectedRange(NSRange(location: textView.string.utf16.count, length: 0))
            }
            switch finish {
            case "escape": hc_session_key(session, UInt32(HC_KEY_ESCAPE), 0, nil, &out)
            case "enter": hc_session_key(session, UInt32(HC_KEY_ENTER), 0, nil, &out)
            case "focus": hc_session_commit(session, nil, &out)
            case "reset": hc_session_reset(session, &out)
            default: hc_session_key(session, UInt32(HC_KEY_CHAR), 114, nil, &out)
            }
            apply()
            let expected = finish == "escape" ? singleDocument : (finish == "type" ? prefix + "ㄱ" + suffix : prefix + suffix)
            check("native empty selection finish (\(finish))", textView.string == expected,
                  "precise original anchor; no extra separator or surrounding replacement")
            if finish == "type" {
                hc_session_commit(session, nil, &out)
                apply()
            }
            check("native anchor released (\(finish))", !markedState.isActive, "commit/reset ends selection lifetime")
            textView.setSelectedRange(NSRange(location: 0, length: 0))
            hc_session_key(session, UInt32(HC_KEY_CHAR), 114, nil, &out)
            apply()
            check("native next composition uses current selection (\(finish))", textView.string == "ㄱ" + expected,
                  "old imported anchor cannot move later input")
            hc_session_commit(session, nil, &out)
            apply()
        }
        // Ordinary keyboard input also retains manually edited boundaries.
        // It has no imported selection fallback: the shared state must use the
        // client's actual marked-range anchor when the result becomes empty.
        textView.string = prefix + suffix
        textView.setSelectedRange(NSRange(location: prefix.utf16.count, length: 0))
        for scalar in "rksk".unicodeScalars {
            hc_session_key(session, UInt32(HC_KEY_CHAR), scalar.value, nil, &out)
            apply()
        }
        hc_session_key(session, UInt32(HC_KEY_SPACE), 0, nil, &out)
        apply()
        hc_session_key(session, UInt32(HC_KEY_SHRINK_SEGMENT), 0, nil, &out)
        apply()
        for _ in 0..<3 {
            hc_session_key(session, UInt32(HC_KEY_BACKSPACE), 0, nil, &out)
            apply()
        }
        check("native typed manual edit delete to empty", textView.string == prefix + suffix && markedState.isActive,
              "manual conversion retained without an imported selection")
        textView.setSelectedRange(NSRange(location: textView.string.utf16.count, length: 0))
        hc_session_key(session, UInt32(HC_KEY_ESCAPE), 0, nil, &out)
        apply()
        check("native typed manual edit empty cancel", textView.string == prefix + "가나" + suffix
              && textView.hasMarkedText() && out.highlight_start < 0,
              "typed original restored as composition at the original anchor")
        hc_session_commit(session, nil, &out)
        apply()
        check("native typed manual edit anchor released", !markedState.isActive,
              "ordinary composition commit ends the saved anchor lifetime")
        panel.hide()
        window.orderOut(nil)
        print(failures == 0 ? "segment editing native harness passed" : "segment editing native harness FAILED")
        exit(failures == 0 ? 0 : 1)
    }
}
