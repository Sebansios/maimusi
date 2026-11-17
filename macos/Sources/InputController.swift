import Carbon
import Cocoa
import InputMethodKit

/// One controller per client text input. It forwards keys to a core session
/// and mirrors the session output into the client: committed text via
/// `insertText`, the composition via `setMarkedText`.
@objc(HangulSpacingInputController)
final class InputController: IMKInputController {
    private let session: OpaquePointer = hc_session_new()
    private let markedState = MarkedTextState()
    private var observer: NSObjectProtocol?

    // IMKTextInput highlight styles (HIToolbox kTSMHilite*).
    private let rawTextStyle = 2
    private let convertedTextStyle = 4
    private let selectedConvertedTextStyle = 5

    override init!(server: IMKServer!, delegate: Any!, client inputClient: Any!) {
        super.init(server: server, delegate: delegate, client: inputClient)
        Log.lifecycle.notice("input controller created")
        applySettings()
        observer = NotificationCenter.default.addObserver(forName: Settings.didChange, object: nil, queue: .main) { [weak self] _ in
            self?.applySettings()
        }
    }

    deinit {
        if let observer { NotificationCenter.default.removeObserver(observer) }
        hc_session_free(session)
    }

    private func applySettings() {
        for (key, value) in Settings.shared.sessionOptions {
            _ = key.withCString { k in value.withCString { v in hc_session_set_option(session, k, v) } }
        }
    }

    override func recognizedEvents(_ sender: Any!) -> Int {
        Int(NSEvent.EventTypeMask.keyDown.rawValue)
    }

    override func activateServer(_ sender: Any!) {
        super.activateServer(sender)
        Log.lifecycle.info("activate")
        EngineHub.shared.warmUp()
    }

    override func deactivateServer(_ sender: Any!) {
        commitAll(sender)
        CandidatePanel.shared.hide()
        super.deactivateServer(sender)
    }

    override func commitComposition(_ sender: Any!) {
        commitAll(sender)
    }

    private func commitAll(_ sender: Any?) {
        guard let client = (sender as? IMKTextInput) ?? (self.client() as IMKTextInput?) else { return }
        var out = hc_output()
        EngineHub.shared.withBackend { hc_session_commit(session, $0, &out) }
        apply(out, to: client)
        takeLearning()
    }

    /// 손으로 고친 경계를 확정했으면 엔진에 넘겨 기억하게 한다. 암호 칸(보안 입력)에서는 기억하지 않는다.
    private func takeLearning() {
        guard let raw = hc_session_take_learning(session) else { return }
        guard !IsSecureEventInputEnabled() else { return }
        let parts = String(cString: raw).split(separator: "\u{1f}", omittingEmptySubsequences: false)
        guard parts.count == 2 else { return }
        EngineHub.shared.learn(proposed: String(parts[0]), accepted: String(parts[1]))
    }

    override func handle(_ event: NSEvent!, client sender: Any!) -> Bool {
        guard let event, event.type == .keyDown else { return false }
        // 업데이트 알림은 타자가 멈춘 뒤에 띄운다(시각만 적는다).
        UpdateController.shared.noteKey()
        guard let client = sender as? IMKTextInput else {
            Log.lifecycle.error("key event without an IMKTextInput client")
            return false
        }
        if KeyMapping.isEditSelection(event), !markedState.isActive {
            return editSelection(in: client)
        }
        let (key, ch) = KeyMapping.coreKey(for: event)
        var out = hc_output()
        EngineHub.shared.withBackend { hc_session_key(session, key, ch, $0, &out) }
        apply(out, to: client)
        takeLearning()
        return out.consumed
    }

    private func apply(_ out: hc_output, to client: IMKTextInput, replacementRange: NSRange? = nil) {
        let commit = out.commit.map { String(cString: $0) } ?? ""
        let preedit = out.preedit.map { String(cString: $0) } ?? ""
        markedState.apply(commit: commit, preedit: marked(preedit, out), converting: out.highlight_start >= 0,
                          initialReplacement: replacementRange,
                          target: .init(markedRange: { client.markedRange() },
                                        insert: { client.insertText($0, replacementRange: $1) },
                                        mark: { client.setMarkedText($0, selectionRange: $1, replacementRange: $2) }))
        updateCandidates(out, client: client)
    }

    private func attributes(_ style: Int, _ range: NSRange) -> [NSAttributedString.Key: Any] {
        var result: [NSAttributedString.Key: Any] = [:]
        for (k, v) in mark(forStyle: style, at: range) ?? [:] {
            if let name = k as? String { result[NSAttributedString.Key(name)] = v }
            else if let key = k as? NSAttributedString.Key { result[key] = v }
        }
        return result
    }

    private func marked(_ text: String, _ out: hc_output) -> NSAttributedString {
        let whole = NSRange(location: 0, length: (text as NSString).length)
        let converting = out.highlight_start >= 0
        let s = NSMutableAttributedString(string: text, attributes: attributes(converting ? convertedTextStyle : rawTextStyle, whole))
        if converting {
            let r = NSRange(location: Int(out.highlight_start), length: Int(out.highlight_len))
            if NSMaxRange(r) <= whole.length {
                s.setAttributes(attributes(selectedConvertedTextStyle, r), range: r)
            }
        }
        return s
    }

    private func updateCandidates(_ out: hc_output, client: IMKTextInput) {
        guard out.highlight_start >= 0 else {
            CandidatePanel.shared.hide()
            return
        }
        let items = (0..<out.candidate_count).compactMap { i in
            hc_session_candidate(session, i).map { String(cString: $0) }
        }
        let notes = (0..<out.candidate_count).map { i in
            hc_session_candidate_note(session, i).map { String(cString: $0) } ?? ""
        }
        var rect = NSRect.zero
        _ = client.attributes(forCharacterIndex: 0, lineHeightRectangle: &rect)
        CandidatePanel.shared.onSelect = { [weak self] index in self?.choose(index) }
        CandidatePanel.shared.onSegmentAction = { [weak self] key in self?.editSegment(key) }
        let preedit = " " + (out.preedit.map { String(cString: $0) } ?? "") + " "
        // 기억한 띄어쓰기가 이 문장에 쓰였으면 후보 창에 알린다(입력 메뉴에서 잊을 수 있다).
        let remembered = Settings.shared.learnedBoundaries.contains { b in
            guard let spaced = b["spaced"] else { return false }
            return preedit.contains(" " + spaced + " ") || preedit.contains(" " + spaced)
        }
        CandidatePanel.shared.show(items, notes: notes, selected: Int(out.candidate_index),
                                   segmentActions: hc_session_segment_actions(session), remembered: remembered, below: rect)
    }

    private func choose(_ index: Int) {
        guard let client = self.client() as IMKTextInput? else { return }
        var out = hc_output()
        hc_session_select_candidate(session, UInt32(index), &out)
        apply(out, to: client)
    }

    private func editSegment(_ key: UInt32) {
        guard markedState.isActive, let client = self.client() as IMKTextInput? else { return }
        var out = hc_output()
        // Boundary operations never ask the automatic spacing backend to run.
        hc_session_key(session, key, 0, nil, &out)
        apply(out, to: client)
    }

    /// IMK ranges are UTF-16 document offsets, not offsets into the selection.
    /// Unsupported clients and empty/multiline/oversized selections pass through.
    @discardableResult private func editSelection(in client: IMKTextInput) -> Bool {
        guard !markedState.isActive else { return false }
        guard let selection = SelectionEditing.read(from: client) else { return false }
        var out = hc_output()
        selection.text.withCString { hc_session_edit_selection(session, $0, &out) }
        guard out.consumed else { return false }
        apply(out, to: client, replacementRange: selection.range)
        return true
    }

    // MARK: Input menu

    override func menu() -> NSMenu! {
        let menu = NSMenu()
        let status = NSMenuItem(title: EngineHub.shared.engineStatus, action: nil, keyEquivalent: "")
        status.isEnabled = false
        menu.addItem(status)
        menu.addItem(.separator())
        for engine in SpacingEngine.allCases where Settings.lightModelBundled {
            let title = engine == .kiwi ? "\(AppInfo.engineName) 엔진 (고정확도)" : "경량 엔진 (내장)"
            let item = NSMenuItem(title: title, action: #selector(selectEngine(_:)), keyEquivalent: "")
            item.target = self
            item.representedObject = engine.rawValue
            item.state = Settings.shared.engine == engine ? .on : .off
            menu.addItem(item)
        }
        let toggle = NSMenuItem(title: "스페이스로 자동 띄어쓰기", action: #selector(toggleSpacing(_:)), keyEquivalent: "")
        toggle.target = self
        toggle.state = Settings.shared.bool("convertOnSpace") ? .on : .off
        menu.addItem(toggle)
        let last = Settings.shared.lastLearned
        if !last.cases.isEmpty || !last.words.isEmpty {
            let shown = (Settings.shared.learnedBoundaries.first { $0["compact"] == last.cases.first }?["spaced"]) ?? last.words.first ?? ""
            let forget = NSMenuItem(title: "방금 기억한 띄어쓰기 잊기 (\(shown))", action: #selector(forgetLastLearned(_:)), keyEquivalent: "")
            forget.target = self
            menu.addItem(forget)
        }
        menu.addItem(.separator())
        let edit = NSMenuItem(title: "선택한 텍스트의 띄어쓰기 편집", action: #selector(editSelectedText(_:)), keyEquivalent: "r")
        edit.keyEquivalentModifierMask = [.control, .shift]
        edit.target = self
        menu.addItem(edit)
        let prefs = NSMenuItem(title: "설정…", action: #selector(openPreferences(_:)), keyEquivalent: "")
        prefs.target = self
        menu.addItem(prefs)
        let update = NSMenuItem(title: UpdateController.shared.menuTitle, action: #selector(checkForUpdates(_:)), keyEquivalent: "")
        update.target = self
        menu.addItem(update)
        return menu
    }

    /// IMK passes menu actions a dictionary; the item is under kIMKCommandMenuItemName.
    private func menuItem(_ sender: Any?) -> NSMenuItem? {
        if let item = sender as? NSMenuItem { return item }
        return (sender as? [String: Any])?[kIMKCommandMenuItemName] as? NSMenuItem
    }

    @objc private func selectEngine(_ sender: Any?) {
        guard let raw = menuItem(sender)?.representedObject as? String, let engine = SpacingEngine(rawValue: raw) else { return }
        Settings.shared.engine = engine
    }

    @objc private func toggleSpacing(_ sender: Any?) {
        Settings.shared.set(!Settings.shared.bool("convertOnSpace"), for: "convertOnSpace")
    }

    @objc private func forgetLastLearned(_ sender: Any?) {
        Settings.shared.forgetLastLearned()
    }

    @objc private func openPreferences(_ sender: Any?) {
        PreferencesWindow.show()
    }

    @objc private func checkForUpdates(_ sender: Any?) {
        UpdateController.shared.menuAction()
    }

    @objc private func editSelectedText(_ sender: Any?) {
        guard let client = self.client() as IMKTextInput? else { return }
        _ = editSelection(in: client)
    }

    override func showPreferences(_ sender: Any!) {
        PreferencesWindow.show()
    }
}
