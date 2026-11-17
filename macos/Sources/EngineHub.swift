import Foundation

/// Spacing and candidate services shared by all input sessions.
///
/// The core calls back into `space` / `candidates` through `hc_backend`.
/// Kiwi (helper process) is preferred when selected and ready; the built-in
/// light model answers otherwise, so a slow or missing helper never blocks
/// typing for more than `timeout`.
final class EngineHub {
    static let shared = EngineHub()

    private let spacer: OpaquePointer?
    let helper: EngineHelper?
    private var lastSpace: UnsafeMutablePointer<CChar>?
    private var lastCandidates: UnsafeMutablePointer<CChar>?
    private var idleTimer: Timer?
    private let timeout: TimeInterval = 0.6
    /// How long Space may wait for Kiwi to load when there is no light model.
    private let startupWait: TimeInterval = 5

    var lightAvailable: Bool { spacer != nil }

    private init() {
        let model = Bundle.main.url(forResource: "spacing", withExtension: "hspm")
        spacer = model.flatMap { url in url.path.withCString { hc_spacer_load($0) } }
        helper = EngineHelper(bundle: Bundle.main)
        helper?.configure(Settings.shared.engineOptions)
        NotificationCenter.default.addObserver(forName: Settings.didChange, object: nil, queue: .main) { [weak self] _ in
            self?.settingsChanged()
        }
        idleTimer = Timer.scheduledTimer(withTimeInterval: 60, repeats: true) { [weak self] _ in self?.unloadIfIdle() }
    }

    private func settingsChanged() {
        helper?.configure(Settings.shared.engineOptions)
        if Settings.shared.engine == .kiwi {
            helper?.start()
        } else {
            helper?.stop()
        }
    }

    /// Called when an input session becomes active.
    func warmUp() {
        if Settings.shared.engine == .kiwi {
            helper?.start()
        }
    }

    private func unloadIfIdle() {
        let minutes = Settings.shared.int("idleUnloadMinutes")
        guard minutes > 0, let helper, helper.state == .ready else { return }
        if Date().timeIntervalSince(helper.lastUse) > Double(minutes) * 60 {
            helper.stop()
        }
    }

    var engineStatus: String {
        let e = AppInfo.engineName
        switch (Settings.shared.engine, helper?.state) {
        case (.light, _): return "경량 엔진 사용 중"
        case (.kiwi, nil): return lightAvailable ? "\(e) 엔진 없음 · 경량 엔진 사용 중" : "띄어쓰기 엔진 없음"
        case (.kiwi, .ready?): return "\(e) 엔진 준비됨"
        case (.kiwi, .starting?): return lightAvailable ? "\(e) 엔진 준비 중 · 그동안 경량 엔진 사용" : "\(e) 엔진 준비 중"
        case (.kiwi, .failed?): return lightAvailable ? "\(e) 엔진 시작 실패 · 경량 엔진 사용 중" : "\(e) 엔진을 시작하지 못했습니다"
        case (.kiwi, .stopped?): return "\(e) 엔진 대기 중 (입력하면 시작)"
        }
    }

    func space(_ text: String) -> String? {
        if Settings.shared.engine == .kiwi, let helper {
            if !lightAvailable && helper.state != .ready && helper.state != .failed {
                helper.start()
                let deadline = Date().addingTimeInterval(startupWait)
                while helper.state == .starting && Date() < deadline {
                    Thread.sleep(forTimeInterval: 0.05)
                }
            }
            if helper.state == .ready,
               let reply = helper.request(["op": "space", "text": text], timeout: timeout),
               let spaced = reply["text"] as? String {
                return spaced
            }
            helper.start()
        }
        return lightSpace(text)
    }

    /// 설정 창의 띄어쓰기 예문. 찰떡 엔진이 준비됐을 때만 지금 규칙으로 띄운다(엔진을 기다리지 않는다).
    func preview(_ text: String, rules: [String: Any]) -> String? {
        guard Settings.shared.engine == .kiwi, let helper else { return nil }
        guard helper.state == .ready else { helper.start(); return nil }
        let reply = helper.request(["op": "space", "text": text, "spacing": rules], timeout: timeout)
        return reply?["text"] as? String
    }

    func lightSpace(_ text: String) -> String? {
        guard let spacer else { return nil }
        guard let raw = text.withCString({ hc_spacer_space(spacer, $0) }) else { return nil }
        defer { hc_string_free(raw) }
        return String(cString: raw)
    }

    /// 손으로 고친 경계를 확정했을 때: 엔진에 기억할 어절과 단어를 물어 설정에 더한다.
    /// 찰떡 엔진이 준비되지 않았으면 아무것도 하지 않는다(타자를 막지 않도록 뒤에서 처리).
    func learn(proposed: String, accepted: String) {
        guard Settings.shared.bool("rememberBoundaries"), let helper, helper.state == .ready else { return }
        DispatchQueue.global(qos: .utility).async {
            guard let reply = helper.request(["op": "learn", "proposed": proposed, "accepted": accepted],
                                             timeout: 2) else { return }
            let cases = reply["cases"] as? [[String: String]] ?? []
            let words = reply["words"] as? [String] ?? []
            DispatchQueue.main.async {
                Settings.shared.learned(cases: cases, words: words)
            }
        }
    }

    /// Engine candidates as (text, source). Romanizations are added by the core.
    func candidates(_ word: String) -> [(String, String)] {
        guard Settings.shared.bool("candidatesEnabled"), let helper, helper.state == .ready else { return [] }
        let reply = helper.request(["op": "candidates", "word": word], timeout: timeout)
        let items = reply?["items"] as? [String] ?? []
        let notes = reply?["notes"] as? [String] ?? []
        return items.enumerated().map { i, text in (text, i < notes.count ? notes[i] : "") }
    }

    // MARK: C callbacks

    fileprivate func spaceForCore(_ text: String) -> UnsafePointer<CChar>? {
        free(lastSpace)
        lastSpace = space(text).flatMap { strdup($0) }
        return UnsafePointer(lastSpace)
    }

    fileprivate func candidatesForCore(_ word: String) -> UnsafePointer<CChar>? {
        free(lastCandidates)
        lastCandidates = strdup(candidates(word).map { "\($0.0)\t\($0.1)" }.joined(separator: "\n"))
        return UnsafePointer(lastCandidates)
    }

    /// Run `body` with a backend whose callbacks reach this hub.
    func withBackend<T>(_ body: (UnsafePointer<hc_backend>) -> T) -> T {
        var backend = hc_backend(
            ctx: Unmanaged.passUnretained(self).toOpaque(),
            space: { ctx, text in
                guard let ctx, let text else { return nil }
                return Unmanaged<EngineHub>.fromOpaque(ctx).takeUnretainedValue().spaceForCore(String(cString: text))
            },
            candidates: { ctx, word in
                guard let ctx, let word else { return nil }
                return Unmanaged<EngineHub>.fromOpaque(ctx).takeUnretainedValue().candidatesForCore(String(cString: word))
            }
        )
        return withUnsafePointer(to: &backend) { body($0) }
    }
}
