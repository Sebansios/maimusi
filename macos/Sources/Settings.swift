import Foundation

/// Which engine spaces text. Kiwi runs in a helper process; the light
/// engine is built into the input method when its model is bundled.
enum SpacingEngine: String, CaseIterable, Identifiable {
    case kiwi
    case light
    var id: String { rawValue }
}

/// User preferences, stored in the input method's own defaults domain.
/// Typed text is not stored, except words the user registers and the few words
/// around a boundary the user corrected by hand (only while 「경계 기억」 is on).
final class Settings {
    static let shared = Settings()
    static let didChange = Notification.Name("HangulSpacingSettingsDidChange")

    private let defaults = UserDefaults.standard

    /// Release builds may ship without the light model (its training data is
    /// not cleared for redistribution); Kiwi is then the only engine.
    static let lightModelBundled = Bundle.main.url(forResource: "spacing", withExtension: "hspm") != nil

    /// Defaults domain used by builds before 0.5.0, copied over once.
    private static let legacyDomain = "org.hangulspacing.inputmethod.HangulSpacing"

    private init() {
        migrateLegacyDefaults()
        defaults.register(defaults: [
            "engine": SpacingEngine.kiwi.rawValue,
            "convertOnSpace": true,
            "spaceInConversion": "cycle",
            "enterPassesThrough": false,
            "spaceImplicitCommits": true,
            "candidatesEnabled": true,
            "hanjaForms": "education",
            "hanjaPresentation": "hanja",
            "symbolConsonants": false,
            "hanjaGlossSearch": false,
            "idleUnloadMinutes": 20,
            "rule.auxiliaries": "separate",
            "rule.compound": "model",
            "rule.number_units": "model",
            "rule.existing_spaces": "preserve",
            "rememberBoundaries": true,
            "candidatePreset": CandidateTheme.defaultPresetID,
            "candidateTextSize": "normal",
            "fontAutoDownload": true,
            "userWords": [String](),
            "learnedBoundaries": [[String: String]](),
            "syncFolder": "",
            // 하루 한 번 새 버전 확인(Updater.swift). 입력 내용은 보내지 않는다.
            "updateAutoCheck": true,
        ])
    }

    private func migrateLegacyDefaults() {
        guard Bundle.main.bundleIdentifier != Settings.legacyDomain,
              defaults.object(forKey: "migratedLegacyDefaults") == nil else { return }
        defaults.set(true, forKey: "migratedLegacyDefaults")
        guard let old = UserDefaults.standard.persistentDomain(forName: Settings.legacyDomain) else { return }
        for (key, value) in old where defaults.object(forKey: key) == nil {
            defaults.set(value, forKey: key)
        }
    }

    private func changed() {
        NotificationCenter.default.post(name: Settings.didChange, object: nil)
    }

    /// Engine forced by the self-test; never persisted.
    var engineOverride: SpacingEngine?

    var engine: SpacingEngine {
        get {
            if let engineOverride { return engineOverride }
            guard Settings.lightModelBundled else { return .kiwi }
            return SpacingEngine(rawValue: defaults.string(forKey: "engine") ?? "") ?? .kiwi
        }
        set { defaults.set(newValue.rawValue, forKey: "engine"); changed() }
    }

    func bool(_ key: String) -> Bool { defaults.bool(forKey: key) }
    func string(_ key: String) -> String { defaults.string(forKey: key) ?? "" }
    func int(_ key: String) -> Int { defaults.integer(forKey: key) }

    func set(_ value: Any, for key: String) {
        defaults.set(value, forKey: key)
        changed()
    }

    // MARK: 사용자 단어와 기억한 경계

    static let maxWords = 5000
    static let maxLearned = 2000

    var userWords: [String] { defaults.stringArray(forKey: "userWords") ?? [] }
    var learnedBoundaries: [[String: String]] {
        (defaults.array(forKey: "learnedBoundaries") as? [[String: String]]) ?? []
    }

    /// 단어 안에는 띄어쓰기를 넣지 않는다. 띄어 쓴 말이나 한 글자는 받지 않는다.
    @discardableResult func addWords(_ words: [String]) -> Bool { !insertWords(words).isEmpty }

    /// 새로 더한 단어만 돌려준다.
    private func insertWords(_ words: [String]) -> [String] {
        var list = userWords
        var added: [String] = []
        for word in words.map({ $0.trimmingCharacters(in: .whitespaces) })
        where word.count >= 2 && word.count <= 40 && !word.contains(" ") && !list.contains(word) {
            list.append(word)
            added.append(word)
        }
        guard !added.isEmpty else { return [] }
        defaults.set(Array(list.suffix(Settings.maxWords)), forKey: "userWords")
        stamp(added.map { "w:" + $0 }, removed: false)
        changed()
        return added
    }

    func removeWord(_ word: String) {
        defaults.set(userWords.filter { $0 != word }, forKey: "userWords")
        stamp(["w:" + word], removed: true)
        changed()
    }

    /// 같은 표현은 새로 고친 띄어쓰기로 바꾸고, 오래된 것부터 덜어 낸다.
    @discardableResult func remember(_ cases: [[String: String]]) -> [String] {
        guard bool("rememberBoundaries"), !cases.isEmpty else { return [] }
        var list = learnedBoundaries
        var keys: [String] = []
        for c in cases {
            guard let compact = c["compact"], let spaced = c["spaced"] else { continue }
            list.removeAll { $0["compact"] == compact }
            list.append(["compact": compact, "spaced": spaced])
            keys.append(compact)
        }
        defaults.set(Array(list.suffix(Settings.maxLearned)), forKey: "learnedBoundaries")
        stamp(keys.map { "b:" + $0 }, removed: false)
        changed()
        return keys
    }

    /// 손으로 고친 경계를 확정했을 때 엔진이 뽑아 준 것을 기억한다. 「방금 기억한 것 잊기」를 위해 따로 적어 둔다.
    func learned(cases: [[String: String]], words: [String]) {
        guard bool("rememberBoundaries") else { return }
        let compacts = remember(cases)
        let added = insertWords(words)
        guard !compacts.isEmpty || !added.isEmpty else { return }
        defaults.set(["cases": compacts, "words": added], forKey: "lastLearned")
    }

    /// 마지막으로 기억한 것: (기억한 띄어쓰기, 함께 더한 단어). 메뉴에 보인다.
    var lastLearned: (cases: [String], words: [String]) {
        let d = defaults.dictionary(forKey: "lastLearned") ?? [:]
        let cases = (d["cases"] as? [String] ?? []).filter { c in learnedBoundaries.contains { $0["compact"] == c } }
        let words = (d["words"] as? [String] ?? []).filter(userWords.contains)
        return (cases, words)
    }

    func forgetLastLearned() {
        let last = lastLearned
        defaults.removeObject(forKey: "lastLearned")
        guard !last.cases.isEmpty || !last.words.isEmpty else { return }
        defaults.set(learnedBoundaries.filter { !last.cases.contains($0["compact"] ?? "") }, forKey: "learnedBoundaries")
        defaults.set(userWords.filter { !last.words.contains($0) }, forKey: "userWords")
        stamp(last.cases.map { "b:" + $0 } + last.words.map { "w:" + $0 }, removed: true)
        changed()
    }

    func forgetBoundary(_ compact: String) {
        defaults.set(learnedBoundaries.filter { $0["compact"] != compact }, forKey: "learnedBoundaries")
        stamp(["b:" + compact], removed: true)
        changed()
    }

    func forgetBoundaries() {
        stamp(learnedBoundaries.compactMap { $0["compact"] }.map { "b:" + $0 }, removed: true)
        defaults.set([[String: String]](), forKey: "learnedBoundaries")
        defaults.removeObject(forKey: "lastLearned")
        changed()
    }

    // MARK: 단어장 기록(동기화용)

    /// 항목마다 바꾼 시각. 지운 항목은 지운 시각만 남겨, 동기화할 때 다른 기기에서 되살아나지 않게 한다.
    /// 키 "w:단어" / "b:붙여 쓴 꼴", 값 ["at": 1970년 이후 초, "removed": Bool].
    var wordbookStamps: [String: [String: Any]] {
        (defaults.dictionary(forKey: "wordbookStamps") as? [String: [String: Any]]) ?? [:]
    }

    private func stamp(_ keys: [String], removed: Bool, at time: Double = Date().timeIntervalSince1970) {
        guard !keys.isEmpty else { return }
        var stamps = wordbookStamps
        for key in keys { stamps[key] = ["at": time, "removed": removed] }
        // 지운 기록은 1년이 지나면 버린다(그동안 모든 기기가 한 번은 맞췄다고 본다).
        let old = Date().timeIntervalSince1970 - 365 * 86400
        stamps = stamps.filter { !(($0.value["removed"] as? Bool ?? false) && ($0.value["at"] as? Double ?? 0) < old) }
        defaults.set(stamps, forKey: "wordbookStamps")
    }

    /// 동기화·가져오기로 합친 결과를 그대로 쓴다. 바뀐 것이 있을 때만 알린다.
    func replaceWordbook(words: [String], boundaries: [[String: String]], stamps: [String: [String: Any]]) {
        let words = Array(words.suffix(Settings.maxWords))
        let boundaries = Array(boundaries.suffix(Settings.maxLearned))
        let same = words == userWords && boundaries == learnedBoundaries
        defaults.set(stamps, forKey: "wordbookStamps")
        guard !same else { return }
        defaults.set(words, forKey: "userWords")
        defaults.set(boundaries, forKey: "learnedBoundaries")
        changed()
    }

    /// Options understood by `hc_session_set_option`.
    var sessionOptions: [(String, String)] {
        [
            ("layout", "dubeolsik"),
            ("convert_on_space", bool("convertOnSpace") ? "1" : "0"),
            ("space_in_conversion", string("spaceInConversion") == "commit" ? "commit" : "cycle"),
            ("enter_passes_through", bool("enterPassesThrough") ? "1" : "0"),
            ("space_implicit_commits", bool("spaceImplicitCommits") ? "1" : "0"),
        ]
    }

    /// Options for the helper's `configure` request.
    var engineOptions: [String: Any] {
        ["spacing": spacingRules, "hanja_forms": string("hanjaForms") == "ks" ? "ks" : "education",
         "hanja_presentation": ["hanja", "hangul_hanja", "hanja_hangul", "hangulhanja"].contains(string("hanjaPresentation")) ? string("hanjaPresentation") : "hanja",
         "symbol_consonants": bool("symbolConsonants"),
         "hanja_gloss": bool("hanjaGlossSearch")]
    }

    /// Spacing rules for the Kiwi engine (`SpacingPreferences` fields).
    var spacingRules: [String: Any] {
        [
            "auxiliaries": string("rule.auxiliaries"),
            "compound": string("rule.compound"),
            "number_units": string("rule.number_units"),
            "existing_spaces": string("rule.existing_spaces"),
            "words": userWords,
            "learned": learnedBoundaries,
        ]
    }
}
