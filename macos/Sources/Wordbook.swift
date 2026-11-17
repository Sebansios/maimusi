import AppKit

/// 단어장: 등록한 단어와 기억한 띄어쓰기. 파일로 내보내고 가져오며, 사용자가 고른 폴더로 기기 사이에 맞춘다.
///
/// 세반시옷 서버는 쓰지 않는다. 동기화 폴더(iCloud Drive·Google Drive·Dropbox·OneDrive·외장 디스크 등)
/// 안의 `Maimusi` 폴더에 기기마다 자기 파일 하나만 쓰고(클라우드 충돌 사본이 생기지 않게), 다른 기기의
/// 파일을 읽어 항목마다 더 나중에 바뀐 쪽을 따른다. 형식은 macOS·Windows가 같다(docs/WORDBOOK.md).
enum Wordbook {
    static let format = "maimusi-wordbook"
    static let version = 1
    static let subfolder = "Maimusi"
    static let filePrefix = "maimusi-wordbook-"

    struct WordItem: Codable { var word: String; var at: String; var removed: Bool? }
    struct BoundaryItem: Codable { var compact: String; var spaced: String; var at: String; var removed: Bool? }
    struct File: Codable {
        var format: String
        var version: Int
        var device: String?
        var updated: String
        var words: [WordItem]
        var boundaries: [BoundaryItem]
    }

    /// 항목 하나의 상태. 지운 항목도 시각과 함께 남는다.
    struct Item: Equatable { var spaced: String?; var at: Double; var removed: Bool }
    struct State: Equatable {
        var words: [String: Item] = [:]
        var boundaries: [String: Item] = [:]
    }

    static let didSync = Notification.Name("MaimusiWordbookDidSync")

    // MARK: 지금 상태

    static func localState(_ s: Settings = .shared) -> State {
        let stamps = s.wordbookStamps
        func at(_ key: String) -> Double { stamps[key]?["at"] as? Double ?? 0 }
        var state = State()
        for word in s.userWords { state.words[word] = Item(spaced: nil, at: at("w:" + word), removed: false) }
        for b in s.learnedBoundaries {
            guard let compact = b["compact"], let spaced = b["spaced"] else { continue }
            state.boundaries[compact] = Item(spaced: spaced, at: at("b:" + compact), removed: false)
        }
        for (key, value) in stamps where value["removed"] as? Bool == true {
            let time = value["at"] as? Double ?? 0
            if key.hasPrefix("w:"), state.words[String(key.dropFirst(2))] == nil {
                state.words[String(key.dropFirst(2))] = Item(spaced: nil, at: time, removed: true)
            } else if key.hasPrefix("b:"), state.boundaries[String(key.dropFirst(2))] == nil {
                state.boundaries[String(key.dropFirst(2))] = Item(spaced: nil, at: time, removed: true)
            }
        }
        return state
    }

    /// 항목마다 더 나중에 바뀐 쪽. 시각이 같으면 남아 있는 쪽.
    static func merge(_ a: State, _ b: State) -> State {
        func pick(_ x: Item?, _ y: Item) -> Item {
            guard let x else { return y }
            if y.at != x.at { return y.at > x.at ? y : x }
            return x.removed ? y : x
        }
        var out = a
        for (k, v) in b.words { out.words[k] = pick(out.words[k], v) }
        for (k, v) in b.boundaries { out.boundaries[k] = pick(out.boundaries[k], v) }
        return out
    }

    static func apply(_ state: State, to s: Settings = .shared) {
        let live = { (items: [String: Item]) in items.filter { !$0.value.removed }.sorted { ($0.value.at, $0.key) < ($1.value.at, $1.key) } }
        let words = live(state.words).map(\.key)
        let boundaries = live(state.boundaries).compactMap { k, v in v.spaced.map { ["compact": k, "spaced": $0] } }
        var stamps: [String: [String: Any]] = [:]
        for (k, v) in state.words { stamps["w:" + k] = ["at": v.at, "removed": v.removed] }
        for (k, v) in state.boundaries { stamps["b:" + k] = ["at": v.at, "removed": v.removed] }
        s.replaceWordbook(words: words, boundaries: boundaries, stamps: stamps)
    }

    // MARK: 파일

    private static let iso: ISO8601DateFormatter = {
        let f = ISO8601DateFormatter()
        f.formatOptions = [.withInternetDateTime]
        return f
    }()

    static func encode(_ state: State, device: String?, includeRemoved: Bool) throws -> Data {
        func time(_ t: Double) -> String { iso.string(from: Date(timeIntervalSince1970: t)) }
        let words = state.words.filter { includeRemoved || !$0.value.removed }.sorted { $0.key < $1.key }
            .map { WordItem(word: $0.key, at: time($0.value.at), removed: $0.value.removed ? true : nil) }
        let boundaries = state.boundaries.filter { includeRemoved || !$0.value.removed }.sorted { $0.key < $1.key }
            .map { BoundaryItem(compact: $0.key, spaced: $0.value.spaced ?? $0.key, at: time($0.value.at),
                                removed: $0.value.removed ? true : nil) }
        let file = File(format: format, version: version, device: device, updated: iso.string(from: Date()),
                        words: words, boundaries: boundaries)
        let encoder = JSONEncoder()
        encoder.outputFormatting = [.prettyPrinted, .sortedKeys, .withoutEscapingSlashes]
        return try encoder.encode(file)
    }

    enum ReadError: Error { case notWordbook, newerVersion }

    /// 단어장 파일을 읽는다. 단어와 띄어쓰기는 엔진과 같은 규칙으로 걸러 낸다.
    static func decode(_ data: Data) throws -> (state: State, device: String?) {
        let file = try JSONDecoder().decode(File.self, from: data)
        guard file.format == format else { throw ReadError.notWordbook }
        guard file.version <= version else { throw ReadError.newerVersion }
        func time(_ s: String) -> Double { iso.date(from: s)?.timeIntervalSince1970 ?? 0 }
        var state = State()
        for w in file.words where valid(w.word) {
            state.words[w.word] = Item(spaced: nil, at: time(w.at), removed: w.removed ?? false)
        }
        for b in file.boundaries where valid(b.compact) && b.spaced.replacingOccurrences(of: " ", with: "") == b.compact
            && !b.spaced.contains("  ") {
            state.boundaries[b.compact] = Item(spaced: b.spaced, at: time(b.at), removed: b.removed ?? false)
        }
        return (state, file.device)
    }

    private static func valid(_ word: String) -> Bool {
        (2...40).contains(word.count) && !word.contains(" ")
            && word.unicodeScalars.allSatisfy { CharacterSet.alphanumerics.contains($0) || "-·’'".unicodeScalars.contains($0) }
    }

    // MARK: 내보내기·가져오기

    static func export(to url: URL) throws {
        try encode(localState(), device: nil, includeRemoved: false).write(to: url, options: .atomic)
    }

    /// 덮어쓰지 않고 더한다. 지운 기록은 따르지 않는다(사용자가 고른 파일이므로).
    /// 돌려주는 값: 새로 더한 단어 수, 새로 더하거나 바꾼 띄어쓰기 수.
    static func importFile(_ url: URL) throws -> (words: Int, boundaries: Int) {
        let incoming = try decode(Data(contentsOf: url)).state
        var state = localState()
        let now = Date().timeIntervalSince1970
        var words = 0, boundaries = 0
        for (k, v) in incoming.words where !v.removed {
            if state.words[k].map({ $0.removed }) ?? true {
                state.words[k] = Item(spaced: nil, at: now, removed: false)
                words += 1
            }
        }
        for (k, v) in incoming.boundaries where !v.removed {
            let local = state.boundaries[k]
            if local == nil || local!.removed || (local!.spaced != v.spaced && v.at > local!.at) {
                state.boundaries[k] = Item(spaced: v.spaced, at: now, removed: false)
                boundaries += 1
            }
        }
        apply(state)
        return (words, boundaries)
    }

    // MARK: 동기화

    static var folder: URL? {
        let path = Settings.shared.string("syncFolder")
        return path.isEmpty ? nil : URL(fileURLWithPath: path, isDirectory: true)
    }

    /// 파일 이름에 쓰는 이 기기의 표시. 기기 이름 대신 무작위 값을 쓴다.
    static var deviceID: String {
        if let id = UserDefaults.standard.string(forKey: "deviceID"), id.count == 8 { return id }
        let id = String(UUID().uuidString.replacingOccurrences(of: "-", with: "").prefix(8)).lowercased()
        UserDefaults.standard.set(id, forKey: "deviceID")
        return id
    }

    private static let queue = DispatchQueue(label: "maimusi.wordbook")
    private static var timer: Timer?
    private static var observer: NSObjectProtocol?
    private static var pending: DispatchWorkItem?
    private static var lastWritten: State?

    /// 입력기를 시작할 때 한 번. 폴더를 골랐으면 맞추고, 바뀔 때마다·5분마다 다시 맞춘다.
    static func start() {
        observer = NotificationCenter.default.addObserver(forName: Settings.didChange, object: nil, queue: .main) { _ in
            guard folder != nil, localState() != lastWritten else { return }
            schedule(after: 3)
        }
        timer = Timer.scheduledTimer(withTimeInterval: 300, repeats: true) { _ in
            if folder != nil { syncNow() }
        }
        if folder != nil { schedule(after: 2) }
    }

    static func schedule(after seconds: Double) {
        pending?.cancel()
        let work = DispatchWorkItem { syncNow() }
        pending = work
        DispatchQueue.main.asyncAfter(deadline: .now() + seconds, execute: work)
    }

    /// 다른 기기 파일을 읽어 합치고, 이 기기 파일을 쓴다. 메인 스레드에서 부른다.
    static func syncNow(completion: ((String?) -> Void)? = nil) {
        guard let folder else { completion?(nil); return }
        let local = localState()
        let id = deviceID
        queue.async {
            let dir = folder.appendingPathComponent(subfolder, isDirectory: true)
            var merged = local
            var failure: String?
            do {
                try FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true)
                let own = filePrefix + id + ".json"
                for url in try FileManager.default.contentsOfDirectory(at: dir, includingPropertiesForKeys: nil) {
                    let name = url.lastPathComponent
                    // iCloud Drive가 아직 내려받지 않은 파일(.이름.json.icloud)은 받아 두고 다음에 읽는다.
                    if name.hasPrefix("." + filePrefix), name.hasSuffix(".json.icloud") {
                        try? FileManager.default.startDownloadingUbiquitousItem(at: url)
                        continue
                    }
                    guard name.hasPrefix(filePrefix), name.hasSuffix(".json"), name != own,
                          let data = try? Data(contentsOf: url), let other = try? decode(data) else { continue }
                    merged = merge(merged, other.state)
                }
                try encode(merged, device: id, includeRemoved: true).write(to: dir.appendingPathComponent(own), options: .atomic)
            } catch {
                failure = (error as NSError).localizedDescription
            }
            DispatchQueue.main.async {
                if failure == nil {
                    // 맞추는 동안 이 기기에서 바뀐 것이 있으면 그것도 함께 둔다.
                    let final = merge(merged, localState())
                    apply(final)
                    lastWritten = localState()
                    UserDefaults.standard.set(Date().timeIntervalSince1970, forKey: "syncLast")
                    if final != merged { schedule(after: 1) }
                } else {
                    Log.lifecycle.error("wordbook sync failed")
                }
                UserDefaults.standard.set(failure ?? "", forKey: "syncError")
                NotificationCenter.default.post(name: didSync, object: nil)
                completion?(failure)
            }
        }
    }

    static func chooseFolder(_ url: URL?) {
        Settings.shared.set(url?.path ?? "", for: "syncFolder")
        lastWritten = nil
        if url != nil { syncNow() }
    }

    /// `--test-wordbook-sync <폴더>`: 실제 파일로 맞추기를 시험한다. 앱 밖에서 돌리면 입력기와 다른
    /// 설정 영역을 쓰므로 입력기 설정은 건드리지 않는다.
    static func runSyncTest(_ arguments: [String]) -> Int32 {
        guard Bundle.main.bundleIdentifier == nil,
              let i = arguments.firstIndex(of: "--test-wordbook-sync"), i + 1 < arguments.count else { return 2 }
        let folder = URL(fileURLWithPath: arguments[i + 1], isDirectory: true)
        let dir = folder.appendingPathComponent(subfolder, isDirectory: true)
        try? FileManager.default.removeItem(at: dir)
        try? FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true)
        let d = UserDefaults.standard
        for key in ["userWords", "learnedBoundaries", "wordbookStamps", "lastLearned", "syncFolder", "syncLast", "syncError"] {
            d.removeObject(forKey: key)
        }
        let s = Settings.shared
        s.addWords(["지울단어", "이기기단어"])
        // 다른 기기: 「지울단어」를 나중에 지웠고, 단어 하나와 띄어쓰기 하나를 더했다.
        let later = iso.string(from: Date().addingTimeInterval(60))
        let other = """
        {"format":"maimusi-wordbook","version":1,"device":"0ther0ne","updated":"\(later)",
         "words":[{"word":"다른기기단어","at":"\(later)"},{"word":"지울단어","at":"\(later)","removed":true}],
         "boundaries":[{"compact":"원물로","spaced":"원물로","at":"\(later)"}]}
        """
        try? Data(other.utf8).write(to: dir.appendingPathComponent(filePrefix + "0ther0ne.json"))
        d.set(folder.path, forKey: "syncFolder")
        var done = false, failure: String?
        syncNow { failure = $0; done = true }
        while !done { RunLoop.main.run(until: Date().addingTimeInterval(0.05)) }
        let words = Set(s.userWords)
        let ownURL = dir.appendingPathComponent(filePrefix + deviceID + ".json")
        let own = (try? Data(contentsOf: ownURL)).flatMap { try? decode($0) }
        var ok = failure == nil
        ok = ok && words == ["이기기단어", "다른기기단어"]
        ok = ok && s.learnedBoundaries.contains { $0["compact"] == "원물로" }
        ok = ok && own?.state.words["지울단어"]?.removed == true && own?.device == deviceID
        print("\(ok ? "PASS" : "FAIL")  wordbook sync: words=\(words.sorted()) learned=\(s.learnedBoundaries.count) own file=\(own != nil) error=\(failure ?? "-")")
        for key in ["userWords", "learnedBoundaries", "wordbookStamps", "lastLearned", "syncFolder", "syncLast", "syncError", "deviceID"] {
            d.removeObject(forKey: key)
        }
        return ok ? 0 : 1
    }

    /// `--test-wordbook`: 두 기기를 흉내 내어 합치기·지운 기록·파일 읽기를 확인한다.
    static func runSelfTest(check: (String, Bool, String) -> Void) {
        var a = State(), b = State()
        a.words["찰떡엔진"] = Item(spaced: nil, at: 10, removed: false)
        b.words["찰떡엔진"] = Item(spaced: nil, at: 20, removed: true)
        a.words["매무시"] = Item(spaced: nil, at: 30, removed: false)
        b.boundaries["원물로"] = Item(spaced: "원물로", at: 5, removed: false)
        a.boundaries["원물로"] = Item(spaced: "원 물로", at: 7, removed: false)
        let m = merge(a, b)
        check("wordbook: newer removal wins", m.words["찰떡엔진"]?.removed == true && m.words["매무시"]?.removed == false,
              "removed on the other device later")
        check("wordbook: newer spacing wins", m.boundaries["원물로"]?.spaced == "원 물로", "per-entry last writer")
        check("wordbook: merge is symmetric", merge(a, b) == merge(b, a), "same result on both devices")
        let data = (try? encode(m, device: "abcd1234", includeRemoved: true)) ?? Data()
        let back = try? decode(data)
        check("wordbook: file round trip", back?.state.words.keys.sorted() == m.words.keys.sorted()
              && back?.state.boundaries["원물로"]?.spaced == "원 물로" && back?.device == "abcd1234",
              "\(data.count) bytes")
        let bad = #"{"format":"maimusi-wordbook","version":1,"updated":"","words":[{"word":"띄어 쓴 말","at":""}],"#
            + #""boundaries":[{"compact":"가나다","spaced":"가 다","at":""}]}"#
        let filtered = try? decode(Data(bad.utf8))
        check("wordbook: invalid entries dropped", filtered?.state.words.isEmpty == true && filtered?.state.boundaries.isEmpty == true,
              "spaced words and mismatched spacing")
        check("wordbook: other formats rejected", (try? decode(Data(#"{"format":"x","version":1,"updated":"","words":[],"boundaries":[]}"#.utf8))) == nil,
              "format must be maimusi-wordbook")
    }
}
