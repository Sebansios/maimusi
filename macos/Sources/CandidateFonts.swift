import AppKit
import CryptoKit

/// 후보 창 글꼴을 고른다: 이미 설치된 전체 글꼴 > 받아 둔 전체 글꼴 > 앱 안의 부분 글꼴.
///
/// 앱에는 Noto Sans/Serif CJK KR의 부분 글꼴(한글·라틴·기호·KS X 1001 한자)만 들어 있다.
/// 그 밖의 확장 한자가 후보에 처음 나오면, 설정에서 켜 두었을 때 같은 글꼴의 전체 파일을
/// 배포 서버에서 한 번 받아 SHA-256을 확인한 뒤 쓴다. 이때 입력한 내용은 보내지 않는다.
enum CandidateFonts {
    struct Entry: Decodable {
        struct Full: Decodable {
            let file: String
            let url: String
            let sha256: String
            let bytes: Int
        }
        let file: String
        let family: String
        let full: Full
    }

    /// 같은 디자인의 다른 이름들. 사용자의 Mac에 설치돼 있으면 그것을 그대로 쓴다.
    static let aliases: [String: [String]] = [
        CandidateTheme.sans: ["Noto Sans CJK KR", "Source Han Sans K", "Source Han Sans KR", "본고딕"],
        CandidateTheme.serif: ["Noto Serif CJK KR", "Source Han Serif K", "Source Han Serif KR", "본명조"],
    ]

    static let didChange = Notification.Name("MaimusiCandidateFontsDidChange")

    private static var entries: [Entry] = []
    private static var bundleDir: URL?
    /// 우리 글꼴 이름 -> 설치돼 있던 전체 글꼴 이름.
    private static var installed: [String: String] = [:]
    /// 받아 둔 전체 글꼴을 쓰고 있는 이름.
    private static var usingDownloaded: Set<String> = []
    private static var downloading: Set<String> = []

    /// 시험용: 설치된 글꼴을 무시하고 다른 폴더에 받는다(`--test-font-download`).
    static var testDownloadDir: URL?

    static var downloadDir: URL {
        testDownloadDir ?? FileManager.default.urls(for: .applicationSupportDirectory, in: .userDomainMask)[0]
            .appendingPathComponent("HangulSpacing/fonts", isDirectory: true)
    }

    /// 프로세스 시작 때 한 번. 설치된 전체 글꼴이 없을 때만 앱의 글꼴을 이 프로세스에 등록한다.
    static func setUp(bundleDir: URL? = Bundle.main.resourceURL?.appendingPathComponent("Fonts")) {
        self.bundleDir = bundleDir
        installed = [:]
        usingDownloaded = []
        if let dir = bundleDir, let data = try? Data(contentsOf: dir.appendingPathComponent("fonts.json")) {
            entries = (try? JSONDecoder().decode([Entry].self, from: data)) ?? []
        }
        let families = testDownloadDir == nil ? Set(NSFontManager.shared.availableFontFamilies) : []
        for (family, names) in aliases {
            if let hit = names.first(where: families.contains) { installed[family] = hit }
        }
        for entry in entries where installed[entry.family] == nil {
            let downloaded = downloadDir.appendingPathComponent(entry.full.file)
            if verified(downloaded, entry.full) {
                register(downloaded)
                usingDownloaded.insert(entry.family)
            } else if let dir = bundleDir {
                register(dir.appendingPathComponent(entry.file))
            }
        }
    }

    /// 테마의 글꼴 이름으로 실제 글꼴을 만든다.
    /// 설치된 글꼴(Source Han 등)은 가족 이름으로, 앱이 넣은 글꼴은 PostScript 이름으로 찾는다.
    /// (이 프로세스에서 등록을 바꾸면 가족 이름 찾기는 낡은 기록을 볼 수 있다.)
    static func font(family name: String, size: CGFloat) -> NSFont? {
        if let installedName = installed[name] {
            return NSFontManager.shared.font(withFamily: installedName, traits: [], weight: 5, size: size)
        }
        if let entry = entries.first(where: { $0.family == name }),
           let font = NSFont(name: (entry.file as NSString).deletingPathExtension, size: size) {
            return font
        }
        return NSFontManager.shared.font(withFamily: name, traits: [], weight: 5, size: size)
    }

    /// 받아 둔 전체 글꼴의 크기(바이트). 없으면 0.
    static var downloadedBytes: Int {
        let files = (try? FileManager.default.contentsOfDirectory(at: downloadDir, includingPropertiesForKeys: [.fileSizeKey])) ?? []
        return files.reduce(0) { $0 + ((try? $1.resourceValues(forKeys: [.fileSizeKey]).fileSize) ?? 0) }
    }

    /// 받아 둔 전체 글꼴을 지우고 앱 안의 부분 글꼴로 돌아간다.
    static func removeDownloaded() {
        for entry in entries where usingDownloaded.contains(entry.family) {
            CTFontManagerUnregisterFontsForURL(downloadDir.appendingPathComponent(entry.full.file) as CFURL, .process, nil)
        }
        try? FileManager.default.removeItem(at: downloadDir)
        setUp(bundleDir: bundleDir)
        NotificationCenter.default.post(name: didChange, object: nil)
    }

    /// 설정 창에 보이는 상태.
    static func status(for family: String?) -> String {
        guard let family, aliases[family] != nil else { return "시스템 글꼴" }
        if let name = installed[family] { return "설치된 \(name) 사용" }
        if usingDownloaded.contains(family) { return "받아 둔 전체 글꼴 사용" }
        if downloading.contains(family) { return "확장 한자 글꼴을 받는 중" }
        return Settings.shared.bool("fontAutoDownload")
            ? "기본 글꼴 사용. 확장 한자가 처음 나오면 전체 글꼴(\(sizeText(family)))을 받습니다."
            : "기본 글꼴 사용. 확장 한자는 다른 글꼴로 보입니다."
    }

    private static func sizeText(_ family: String) -> String {
        guard let bytes = entries.first(where: { $0.family == family })?.full.bytes else { return "" }
        return "\(Int((Double(bytes) / 1_000_000).rounded())) MB"
    }

    /// 부분 글꼴에 없는 한자가 후보에 있으면 전체 글꼴을 받는다(설정에서 켰을 때, 한 번만).
    static func ensureCoverage(for texts: [String], family: String?) {
        guard let family, installed[family] == nil, !usingDownloaded.contains(family), !downloading.contains(family),
              testDownloadDir != nil || Settings.shared.bool("fontAutoDownload"),
              let entry = entries.first(where: { $0.family == family }),
              let font = font(family: family, size: 13)
        else { return }
        let covered = font.coveredCharacterSet
        let missing = texts.contains { text in
            text.unicodeScalars.contains { isHan($0) && !covered.contains($0) }
        }
        if missing { download(entry) }
    }

    private static func isHan(_ s: Unicode.Scalar) -> Bool {
        switch s.value {
        case 0x3400...0x4DBF, 0x4E00...0x9FFF, 0xF900...0xFAFF, 0x20000...0x3134F: return true
        default: return false
        }
    }

    private static func download(_ entry: Entry) {
        guard let url = URL(string: entry.full.url) else { return }
        downloading.insert(entry.family)
        NotificationCenter.default.post(name: didChange, object: nil)
        let destination = downloadDir.appendingPathComponent(entry.full.file)
        // 쿠키·캐시를 쓰지 않는 세션. 주소에 사용자 정보를 싣지 않는다.
        let configuration = URLSessionConfiguration.ephemeral
        configuration.httpAdditionalHeaders = ["User-Agent": "Maimusi", "Accept-Language": "ko"]
        let session = URLSession(configuration: configuration)
        session.downloadTask(with: url) { temporary, response, error in
            var ok = false
            if let temporary, error == nil, (response as? HTTPURLResponse)?.statusCode == 200,
               verified(temporary, entry.full) {
                try? FileManager.default.createDirectory(at: downloadDir, withIntermediateDirectories: true)
                try? FileManager.default.removeItem(at: destination)
                ok = (try? FileManager.default.moveItem(at: temporary, to: destination)) != nil
            }
            DispatchQueue.main.async {
                downloading.remove(entry.family)
                if ok {
                    if let dir = bundleDir {
                        CTFontManagerUnregisterFontsForURL(dir.appendingPathComponent(entry.file) as CFURL, .process, nil)
                    }
                    register(destination)
                    usingDownloaded.insert(entry.family)
                    Log.lifecycle.notice("candidate font downloaded: \(entry.full.file, privacy: .public)")
                } else {
                    Log.lifecycle.error("candidate font download failed: \(entry.full.file, privacy: .public)")
                }
                NotificationCenter.default.post(name: didChange, object: nil)
            }
        }.resume()
    }

    private static func verified(_ url: URL, _ full: Entry.Full) -> Bool {
        guard let data = try? Data(contentsOf: url, options: .mappedIfSafe), data.count == full.bytes else { return false }
        return SHA256.hash(data: data).map { String(format: "%02x", $0) }.joined() == full.sha256
    }

    private static func register(_ url: URL) {
        CTFontManagerRegisterFontsForURL(url as CFURL, .process, nil)
    }

    /// `--test-font-download <글꼴 폴더> <받을 폴더>`: 설치된 글꼴을 무시하고, 부분 글꼴에 없는
    /// 확장 한자로 전체 글꼴 받기·검증·등록을 시험한다.
    static func runDownloadTest(_ arguments: [String]) -> Int32 {
        guard let i = arguments.firstIndex(of: "--test-font-download"), i + 2 < arguments.count else { return 2 }
        _ = NSApplication.shared
        testDownloadDir = URL(fileURLWithPath: arguments[i + 2])
        setUp(bundleDir: URL(fileURLWithPath: arguments[i + 1]))
        let rare = "\u{3400}"   // KS X 1001 밖 한자(확장 A)
        var ok = true
        for family in [CandidateTheme.sans, CandidateTheme.serif] {
            let before = font(family: family, size: 13)?
                .coveredCharacterSet.contains(Unicode.Scalar(0x3400)!) ?? false
            ensureCoverage(for: [rare], family: family)
            let deadline = Date().addingTimeInterval(120)
            while downloading.contains(family) && Date() < deadline {
                RunLoop.main.run(until: Date().addingTimeInterval(0.2))
            }
            let after = font(family: family, size: 13)?
                .coveredCharacterSet.contains(Unicode.Scalar(0x3400)!) ?? false
            let reused = before && usingDownloaded.contains(family)
            let pass = (reused || !before) && after && usingDownloaded.contains(family)
            ok = ok && pass
            print("\(pass ? "PASS" : "FAIL")  \(family): " + (reused
                ? "already using the downloaded full font, covers U+3400 \(after)"
                : "subset covers U+3400 \(before), after download \(after)"))
        }
        return ok ? 0 : 1
    }
}
