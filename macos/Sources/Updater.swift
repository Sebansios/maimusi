import AppKit
import Combine
import CryptoKit
import SwiftUI

/// 새 버전 확인·내려받기·설치. 형식과 출시 순서는 docs/UPDATES.md.
///
/// - 설정 「새 버전 자동으로 확인」이 켜져 있으면(기본값) 하루 한 번 배포 서버의 업데이트 정보 파일
///   하나(Info.plist `HSUpdateURL`)를 받는다. 주소·헤더에 입력 내용·버전·기기 정보를 싣지 않는다.
///   지금 판과 비교하는 일은 이 Mac에서 한다.
/// - 그 파일은 앱에 넣은 공개키(`HSUpdateKeys`, packaging/update-keys.json)의 Ed25519 서명이 맞아야
///   쓴다. 배포 서버가 침해돼도 서명 없이는 설치 파일을 바꿔치기할 수 없다. 지금보다 높은 빌드만
///   알린다(옛 판으로 되돌리기 방지).
/// - 알림은 키보드 초점을 가져가지 않는 작은 창으로, 타자가 몇 초 멈췄을 때 화면 오른쪽 위에 띄운다.
///   치던 키가 알림의 단추로 가는 일이 없다.
/// - 설치 파일은 서명된 정보의 크기·SHA-256과 맞을 때만 macOS 설치 프로그램으로 연다. 관리자 암호와
///   설치는 설치 프로그램이 맡고, 설치하는 동안 입력기가 다시 시작된다.
enum Updater {
    struct Release: Decodable, Equatable {
        struct File: Decodable, Equatable {
            let name: String
            let url: String
            let bytes: Int
            let sha256: String
        }
        let format: String
        let version: Int
        let platform: String
        let channel: String
        let product: String
        let label: String?
        let build: Int
        let published: String?
        let notes: [String]?
        let page: String?
        let minimumOS: String?
        let architectures: [String]?
        let file: File

        enum CodingKeys: String, CodingKey {
            case format, version, platform, channel, product, label, build, published, notes, page, architectures, file
            case minimumOS = "minimum_os"
        }

        /// 사용자에게 보이는 판 이름(예: 「0.5.4」, 「0.6.0 Beta 1」).
        var displayVersion: String {
            let l = label ?? ""
            return l.isEmpty ? product : "\(product) \(l)"
        }
    }

    private struct Envelope: Decodable {
        let format: String
        let key: String
        let payload: String
        let signature: String
    }

    enum Rejection: Error, Equatable {
        case tooLarge, notUpdateFile, unknownKey, badSignature, unsupported, wrongPlatform, badFile
    }

    static let format = "maimusi-update"
    /// 서명 대상 앞에 붙이는 구분자. 같은 키로 서명한 다른 종류의 글과 섞이지 않게 한다.
    static let domain = Data("maimusi-update/1\n".utf8)
    static let maxManifest = 64 * 1024
    static let maxPackage = 1 << 30

    /// 서명된 업데이트 정보를 확인하고 내용을 돌려준다(tools/update_manifest.py `verify`와 같은 규칙).
    /// allowLoopback: 시험(`--test-update`)에서만 127.0.0.1의 http 주소를 받아들인다.
    static func verify(_ data: Data, keys: [String: Data], platform: String = "macos",
                       allowLoopback: Bool = false) throws -> Release {
        guard data.count <= maxManifest else { throw Rejection.tooLarge }
        guard let envelope = try? JSONDecoder().decode(Envelope.self, from: data), envelope.format == format
        else { throw Rejection.notUpdateFile }
        guard let raw = keys[envelope.key], let key = try? Curve25519.Signing.PublicKey(rawRepresentation: raw)
        else { throw Rejection.unknownKey }
        guard let payload = Data(base64Encoded: envelope.payload),
              let signature = Data(base64Encoded: envelope.signature),
              key.isValidSignature(signature, for: domain + payload)
        else { throw Rejection.badSignature }
        guard let release = try? JSONDecoder().decode(Release.self, from: payload),
              release.format == format, release.version == 1, release.channel == "stable"
        else { throw Rejection.unsupported }
        guard release.platform == platform else { throw Rejection.wrongPlatform }
        let f = release.file
        let safeName = !f.name.hasPrefix(".") && f.name.allSatisfy { $0.isASCII && ($0.isLetter || $0.isNumber || "._-".contains($0)) }
        guard release.build > 0, URL(string: f.url).map({ secure($0, allowLoopback: allowLoopback) }) == true,
              f.bytes > 0, f.bytes <= maxPackage,
              f.sha256.count == 64, f.sha256.allSatisfy({ "0123456789abcdef".contains($0) }),
              safeName, platform != "macos" || f.name.hasSuffix(".pkg")
        else { throw Rejection.badFile }
        return release
    }

    static func secure(_ url: URL, allowLoopback: Bool = false) -> Bool {
        guard let host = url.host, !host.isEmpty else { return false }
        if url.scheme == "https" { return true }
        return allowLoopback && url.scheme == "http" && host == "127.0.0.1"
    }

    enum Offer: Equatable {
        case none
        case newer
        case needsNewerOS(String)
        case otherArchitecture
    }

    /// 이 Mac에 알릴 새 버전인가. 빌드 번호는 플랫폼과 관계없이 계속 올라가므로 빌드로만 비교한다.
    static func offer(_ r: Release, currentBuild: Int, os: OperatingSystemVersion, arch: String) -> Offer {
        guard r.build > currentBuild else { return .none }
        if let list = r.architectures, !list.contains(arch) { return .otherArchitecture }
        if let minimum = r.minimumOS, !satisfies(os, minimum) { return .needsNewerOS(minimum) }
        return .newer
    }

    static func satisfies(_ os: OperatingSystemVersion, _ minimum: String) -> Bool {
        let need = minimum.split(separator: ".").map { Int($0) ?? 0 } + [0, 0, 0]
        let have = [os.majorVersion, os.minorVersion, os.patchVersion]
        for i in 0..<3 where have[i] != need[i] { return have[i] > need[i] }
        return true
    }

    static var machineArch: String {
        #if arch(arm64)
        return "arm64"
        #else
        return "x86_64"
        #endif
    }

    /// 파일 크기·SHA-256이 서명된 정보와 같은가(1 MB씩 읽는다).
    static func fileMatches(_ url: URL, _ f: Release.File) -> Bool {
        guard let handle = try? FileHandle(forReadingFrom: url) else { return false }
        defer { try? handle.close() }
        var hasher = SHA256()
        var total = 0
        while let chunk = try? handle.read(upToCount: 1 << 20), !chunk.isEmpty {
            total += chunk.count
            if total > f.bytes { return false }
            hasher.update(data: chunk)
        }
        return total == f.bytes && hex(hasher.finalize()) == f.sha256
    }

    static func hex<D: Sequence>(_ digest: D) -> String where D.Element == UInt8 {
        digest.map { String(format: "%02x", $0) }.joined()
    }

    /// 쿠키·캐시를 쓰지 않는 요청. User-Agent는 앱 이름만, 언어는 고정값(시스템 언어 설정을 알리지 않는다).
    static func configuration() -> URLSessionConfiguration {
        let c = URLSessionConfiguration.ephemeral
        c.httpAdditionalHeaders = ["User-Agent": "Maimusi", "Accept-Language": "ko"]
        c.httpCookieStorage = nil
        c.httpShouldSetCookies = false
        c.urlCache = nil
        c.requestCachePolicy = .reloadIgnoringLocalCacheData
        c.timeoutIntervalForRequest = 30
        return c
    }
}

/// 알림 창과 설정 창이 함께 보는 상태.
final class UpdateModel: ObservableObject {
    enum Phase: Equatable {
        case idle
        case checking
        case upToDate
        case available
        /// 새 버전이 있지만 이 Mac에는 설치할 수 없다(설명).
        case unavailable(String)
        case downloading(Int64, Int64)
        case verifying
        case opened
        /// 실패(제목, 설명, 다시 시도할 일이 내려받기인가).
        case failed(String, String, download: Bool)
    }
    @Published var phase: Phase = .idle
    @Published var release: Updater.Release?
}

final class UpdateController: NSObject, URLSessionDataDelegate, URLSessionDownloadDelegate {
    static let shared = UpdateController()
    static let didChange = Notification.Name("MaimusiUpdateDidChange")

    let model = UpdateModel()

    // 시험에서만 바꾼다(`--test-update`).
    var keys: [String: Data]
    var manifestURL: URL?
    var currentBuild: Int
    var downloadDir: URL
    var openInstaller: (URL, @escaping (Bool) -> Void) -> Void = UpdateController.openWithInstaller
    var presentsPanel = true
    var allowLoopback = false

    private let defaults = UserDefaults.standard
    private var timer: Timer?
    private var idleTimer: Timer?
    private var hideTimer: Timer?
    private var lastKey = Date.distantPast
    private var checkSession: URLSession?
    private var checkData = Data()
    private var checkManual = false
    private var downloadSession: URLSession?
    private var downloadTask: URLSessionDownloadTask?
    private var downloadedFile: URL?
    private var cancelledByUser = false
    private var oversized = false
    private var lastProgress = Date.distantPast
    private lazy var panel = UpdatePanel(model: model, controller: self)

    private override init() {
        let info = Bundle.main.infoDictionary ?? [:]
        keys = ((info["HSUpdateKeys"] as? [String: String]) ?? [:]).compactMapValues { Data(base64Encoded: $0) }
        manifestURL = (info["HSUpdateURL"] as? String).flatMap(URL.init(string:))
        currentBuild = Int(AppInfo.build) ?? 0
        downloadDir = FileManager.default.urls(for: .cachesDirectory, in: .userDomainMask)[0]
            .appendingPathComponent("HangulSpacing/Updates", isDirectory: true)
        super.init()
    }

    private var busy: Bool {
        switch model.phase {
        case .downloading, .verifying: return true
        default: return checkSession != nil
        }
    }

    // MARK: 일정

    /// 입력기 시작 때 한 번. 로그인 직후에는 서두르지 않고, 그 뒤 한 시간마다 하루가 지났는지만 본다.
    func start() {
        removeStaleDownloads()
        DispatchQueue.main.asyncAfter(deadline: .now() + 90) { [weak self] in self?.tick() }
        let t = Timer(timeInterval: 3600, repeats: true) { [weak self] _ in self?.tick() }
        t.tolerance = 600
        RunLoop.main.add(t, forMode: .common)
        timer = t
    }

    private func tick() {
        guard Settings.shared.bool("updateAutoCheck"), !busy else { return }
        let now = Date()
        if let last = defaults.object(forKey: "updateLastCheck") as? Date {
            let age = now.timeIntervalSince(last)
            if age >= 0 && age < 23 * 3600 { return }
        }
        // 연결이 안 될 때는 세 시간 뒤에 다시.
        if let attempt = defaults.object(forKey: "updateLastAttempt") as? Date {
            let age = now.timeIntervalSince(attempt)
            if age >= 0 && age < 3 * 3600 { return }
        }
        check(manual: false)
    }

    /// 키를 처리할 때마다(InputController). 알림은 타자가 멈춘 뒤에 띄운다.
    func noteKey() { lastKey = Date() }

    var lastCheck: Date? { defaults.object(forKey: "updateLastCheck") as? Date }

    // MARK: 확인

    /// manual: 입력 메뉴·설정에서 직접 확인. 결과를 바로 보여 주고 「건너뛴 판」도 다시 알린다.
    func check(manual: Bool) {
        if busy {
            if manual { showPanel() }
            return
        }
        guard let url = manifestURL, !keys.isEmpty else {
            if manual {
                model.phase = .failed("새 버전을 확인할 수 없습니다", "이 빌드에는 업데이트 정보가 들어 있지 않습니다.", download: false)
                showPanel()
            }
            return
        }
        if manual {
            model.phase = .checking
            showPanel()
        }
        checkManual = manual
        checkData = Data()
        defaults.set(Date(), forKey: "updateLastAttempt")
        let session = URLSession(configuration: Updater.configuration(), delegate: self, delegateQueue: .main)
        checkSession = session
        session.dataTask(with: url).resume()
    }

    private enum CheckFailure: Error {
        case network, server(Int), rejected(Updater.Rejection)

        var message: String {
            switch self {
            case .network: return "인터넷 연결을 확인한 뒤 다시 시도해 주세요."
            case .server(let status): return "배포 서버가 응답하지 않았습니다(\(status))."
            case .rejected: return "받은 업데이트 정보의 서명이 맞지 않아 쓰지 않았습니다."
            }
        }
    }

    private func finishCheck(_ result: Result<Updater.Release?, CheckFailure>) {
        let manual = checkManual
        checkSession?.finishTasksAndInvalidate()
        checkSession = nil
        checkData = Data()
        defer { NotificationCenter.default.post(name: Self.didChange, object: nil) }
        switch result {
        case .failure(let failure):
            if case .rejected(let why) = failure {
                Log.lifecycle.error("update manifest rejected: \(String(describing: why), privacy: .public)")
            }
            if manual {
                model.phase = .failed("새 버전을 확인하지 못했습니다", failure.message, download: false)
                showPanel()
            }
        case .success(let release):
            defaults.set(Date(), forKey: "updateLastCheck")
            let offer = release.map {
                Updater.offer($0, currentBuild: currentBuild, os: ProcessInfo.processInfo.operatingSystemVersion,
                              arch: Updater.machineArch)
            } ?? .none
            switch offer {
            case .newer:
                guard let release else { return }
                model.release = release
                model.phase = .available
                if manual {
                    showPanel()
                } else if release.build != defaults.integer(forKey: "updateSkippedBuild"), !snoozed {
                    showWhenIdle()
                }
            case .needsNewerOS(let minimum):
                model.release = nil
                if manual, let release {
                    model.phase = .unavailable("\(AppInfo.name) \(release.displayVersion) 판은 macOS \(minimum) 이상에서 설치할 수 있습니다.")
                    showPanel()
                }
            case .otherArchitecture:
                model.release = nil
                if manual {
                    model.phase = .unavailable("이 Mac에서 쓸 수 있는 새 버전은 아직 없습니다.")
                    showPanel()
                }
            case .none:
                model.release = nil
                model.phase = .upToDate
                if manual {
                    showPanel()
                    hide(after: 6)
                }
            }
        }
    }

    private var snoozed: Bool {
        guard let until = defaults.object(forKey: "updateRemindAfter") as? Date else { return false }
        return Date() < until
    }

    // MARK: URLSession

    func urlSession(_ session: URLSession, dataTask: URLSessionDataTask, didReceive response: URLResponse,
                    completionHandler: @escaping (URLSession.ResponseDisposition) -> Void) {
        // 큰 응답은 받지 않는다.
        completionHandler(response.expectedContentLength > Int64(Updater.maxManifest) ? .cancel : .allow)
    }

    func urlSession(_ session: URLSession, dataTask: URLSessionDataTask, didReceive data: Data) {
        checkData.append(data)
        if checkData.count > Updater.maxManifest { dataTask.cancel() }
    }

    /// https가 아닌 곳으로 넘기는 응답은 따르지 않는다.
    func urlSession(_ session: URLSession, task: URLSessionTask, willPerformHTTPRedirection response: HTTPURLResponse,
                    newRequest request: URLRequest, completionHandler: @escaping (URLRequest?) -> Void) {
        completionHandler(request.url.map { Updater.secure($0, allowLoopback: allowLoopback) } == true ? request : nil)
    }

    func urlSession(_ session: URLSession, downloadTask: URLSessionDownloadTask, didWriteData bytesWritten: Int64,
                    totalBytesWritten: Int64, totalBytesExpectedToWrite: Int64) {
        guard let release = model.release else { return }
        let expected = Int64(release.file.bytes)
        if totalBytesWritten > expected {
            oversized = true
            downloadTask.cancel()
            return
        }
        let now = Date()
        if now.timeIntervalSince(lastProgress) >= 0.1 || totalBytesWritten == expected {
            lastProgress = now
            model.phase = .downloading(totalBytesWritten, expected)
        }
    }

    func urlSession(_ session: URLSession, downloadTask: URLSessionDownloadTask, didFinishDownloadingTo location: URL) {
        // 이 함수가 끝나면 임시 파일이 지워지므로 여기서 옮긴다.
        guard let release = model.release, (downloadTask.response as? HTTPURLResponse)?.statusCode == 200 else { return }
        let destination = downloadDir.appendingPathComponent(release.file.name)
        let fm = FileManager.default
        try? fm.createDirectory(at: downloadDir, withIntermediateDirectories: true)
        try? fm.removeItem(at: destination)
        if (try? fm.moveItem(at: location, to: destination)) != nil { downloadedFile = destination }
    }

    func urlSession(_ session: URLSession, task: URLSessionTask, didCompleteWithError error: Error?) {
        if session === checkSession {
            let status = (task.response as? HTTPURLResponse)?.statusCode ?? 0
            if error != nil || status == 0 {
                finishCheck(.failure(checkData.count > Updater.maxManifest ? .rejected(.tooLarge) : .network))
            } else if status == 404 {
                // 아직 올린 업데이트 정보가 없다.
                finishCheck(.success(nil))
            } else if status != 200 {
                finishCheck(.failure(.server(status)))
            } else {
                do { finishCheck(.success(try Updater.verify(checkData, keys: keys, allowLoopback: allowLoopback))) } catch {
                    finishCheck(.failure(.rejected(error as? Updater.Rejection ?? .notUpdateFile)))
                }
            }
            return
        }
        guard session === downloadSession else { return }
        session.finishTasksAndInvalidate()
        downloadSession = nil
        downloadTask = nil
        let file = downloadedFile
        downloadedFile = nil
        if cancelledByUser {
            cancelledByUser = false
            if let file { try? FileManager.default.removeItem(at: file) }
            model.phase = .available
            return
        }
        guard error == nil, let file, let release = model.release else {
            if let file { try? FileManager.default.removeItem(at: file) }
            if oversized {
                oversized = false
                Log.lifecycle.error("update package larger than the signed manifest")
                fail("받은 파일이 올바르지 않습니다", "서명된 업데이트 정보보다 커서 받기를 멈췄습니다. 다시 시도해 주세요.")
            } else {
                fail("내려받지 못했습니다", "인터넷 연결을 확인한 뒤 다시 시도해 주세요.")
            }
            return
        }
        verifyAndOpen(file, release)
    }

    // MARK: 내려받기와 설치

    /// 「업데이트」: 받아 둔 파일이 맞으면 그것을, 아니면 새로 받아 확인한 뒤 설치 프로그램을 연다.
    func install() {
        guard let release = model.release, !busy else { return }
        hideTimer?.invalidate()
        let existing = downloadDir.appendingPathComponent(release.file.name)
        if FileManager.default.fileExists(atPath: existing.path) {
            verifyAndOpen(existing, release, downloadIfBad: true)
            return
        }
        startDownload(release)
    }

    private func startDownload(_ release: Updater.Release) {
        guard let url = URL(string: release.file.url) else { return }
        let c = Updater.configuration()
        c.timeoutIntervalForResource = 3 * 3600
        let session = URLSession(configuration: c, delegate: self, delegateQueue: .main)
        downloadSession = session
        cancelledByUser = false
        oversized = false
        model.phase = .downloading(0, Int64(release.file.bytes))
        let task = session.downloadTask(with: url)
        downloadTask = task
        task.resume()
        Log.lifecycle.notice("update download started: build \(release.build, privacy: .public)")
    }

    func cancelDownload() {
        guard let downloadTask else { return }
        cancelledByUser = true
        downloadTask.cancel()
    }

    private func verifyAndOpen(_ file: URL, _ release: Updater.Release, downloadIfBad: Bool = false) {
        model.phase = .verifying
        DispatchQueue.global(qos: .userInitiated).async {
            let ok = Updater.fileMatches(file, release.file)
            DispatchQueue.main.async { [self] in
                guard ok else {
                    try? FileManager.default.removeItem(at: file)
                    if downloadIfBad {
                        startDownload(release)
                    } else {
                        Log.lifecycle.error("update package did not match the signed manifest")
                        fail("받은 파일이 올바르지 않습니다", "서명된 업데이트 정보와 달라 지웠습니다. 다시 시도해 주세요.")
                    }
                    return
                }
                defaults.set(release.build, forKey: "updateDownloadedBuild")
                openInstaller(file) { [self] opened in
                    if opened {
                        model.phase = .opened
                        hide(after: 20)
                    } else {
                        fail("설치 프로그램을 열지 못했습니다", "받은 파일을 Finder에서 직접 열어 설치할 수 있습니다.")
                    }
                }
            }
        }
    }

    private static func openWithInstaller(_ file: URL, _ done: @escaping (Bool) -> Void) {
        let installer = URL(fileURLWithPath: "/System/Library/CoreServices/Installer.app")
        let configuration = NSWorkspace.OpenConfiguration()
        configuration.activates = true
        NSWorkspace.shared.open([file], withApplicationAt: installer, configuration: configuration) { _, error in
            DispatchQueue.main.async { done(error == nil) }
        }
    }

    private func fail(_ title: String, _ message: String) {
        model.phase = .failed(title, message, download: true)
        showPanel()
    }

    /// 설치를 마친 판보다 오래된 받은 파일은 지운다.
    private func removeStaleDownloads() {
        let downloaded = defaults.integer(forKey: "updateDownloadedBuild")
        if downloaded <= currentBuild {
            try? FileManager.default.removeItem(at: downloadDir)
            defaults.removeObject(forKey: "updateDownloadedBuild")
        }
    }

    // MARK: 알림 창

    func later() {
        defaults.set(Date().addingTimeInterval(24 * 3600), forKey: "updateRemindAfter")
        hidePanel()
    }

    func skip() {
        if let build = model.release?.build { defaults.set(build, forKey: "updateSkippedBuild") }
        hidePanel()
    }

    func close() {
        switch model.phase {
        case .downloading, .verifying, .checking: break
        case .available: later(); return
        default: model.phase = model.release == nil ? .idle : .available
        }
        hidePanel()
    }

    func retry() {
        if case .failed(_, _, let download) = model.phase, download, model.release != nil {
            install()
        } else {
            check(manual: true)
        }
    }

    func openPage() {
        let page = model.release?.page.flatMap(URL.init(string:)) ?? AppInfo.website
        if let page, page.scheme == "https" { NSWorkspace.shared.open(page) }
    }

    /// 입력 메뉴 항목.
    var menuTitle: String {
        if let release = model.release { return "새 버전으로 업데이트 (\(release.displayVersion))…" }
        return "업데이트 확인…"
    }

    func menuAction() {
        if model.release != nil {
            if !busy, model.phase != .opened { model.phase = .available }
            showPanel()
        } else {
            check(manual: true)
        }
    }

    private func showWhenIdle() {
        idleTimer?.invalidate()
        let t = Timer(timeInterval: 2, repeats: true) { [weak self] t in
            guard let self else { t.invalidate(); return }
            if Date().timeIntervalSince(self.lastKey) >= 4 {
                t.invalidate()
                self.idleTimer = nil
                self.showPanel()
            }
        }
        RunLoop.main.add(t, forMode: .common)
        idleTimer = t
    }

    private func showPanel() {
        hideTimer?.invalidate()
        guard presentsPanel else { return }
        panel.present()
    }

    private func hidePanel() {
        idleTimer?.invalidate()
        idleTimer = nil
        hideTimer?.invalidate()
        panel.orderOut(nil)
    }

    private func hide(after seconds: TimeInterval) {
        hideTimer?.invalidate()
        let t = Timer(timeInterval: seconds, repeats: false) { [weak self] _ in
            guard let self else { return }
            if self.model.phase == .upToDate || self.model.phase == .opened { self.close() }
        }
        RunLoop.main.add(t, forMode: .common)
        hideTimer = t
    }
}

// MARK: - 알림 창

/// 화면 오른쪽 위의 작은 알림. 키보드 초점을 가져가지 않으므로(canBecomeKey false) 치던 글은
/// 그대로 원래 앱으로 가고, 단추는 마우스로만 누른다.
final class UpdatePanel: NSPanel {
    static let width: CGFloat = 360
    private let host: NSView
    private var observation: AnyCancellable?

    init(model: UpdateModel, controller: UpdateController) {
        let hosting = FirstMouseHostingView(rootView: UpdateCard(model: model, controller: controller))
        host = hosting
        super.init(contentRect: NSRect(x: 0, y: 0, width: Self.width, height: 120),
                   styleMask: [.nonactivatingPanel, .borderless], backing: .buffered, defer: true)
        level = .floating
        isFloatingPanel = true
        hidesOnDeactivate = false
        hasShadow = true
        isOpaque = false
        backgroundColor = .clear
        collectionBehavior = [.canJoinAllSpaces, .fullScreenAuxiliary]
        contentView = Self.backdrop(around: hosting, radius: 18)
        observation = model.objectWillChange.sink { [weak self] _ in
            DispatchQueue.main.async { if self?.isVisible == true { self?.fit() } }
        }
    }

    override var canBecomeKey: Bool { false }
    override var canBecomeMain: Bool { false }

    func present() {
        fit()
        orderFrontRegardless()
    }

    /// 내용 높이에 맞추고 오른쪽 위에 붙인다.
    private func fit() {
        host.layoutSubtreeIfNeeded()
        let size = NSSize(width: Self.width, height: ceil(host.fittingSize.height))
        let screen = NSScreen.main ?? NSScreen.screens.first
        let area = screen?.visibleFrame ?? NSRect(x: 0, y: 0, width: 1440, height: 900)
        let origin = NSPoint(x: area.maxX - size.width - 14, y: area.maxY - size.height - 10)
        setFrame(NSRect(origin: origin, size: size), display: true)
        invalidateShadow()
    }

    /// macOS 26 이상은 Liquid Glass, 그 전은 시스템 반투명 재질(연속 곡률 모서리).
    static func backdrop(around content: NSView, radius: CGFloat) -> NSView {
        content.autoresizingMask = [.width, .height]
        if CandidateTheme.hasLiquidGlass, #available(macOS 26.0, *) {
            let glass = NSGlassEffectView()
            glass.cornerRadius = radius
            glass.contentView = content
            return glass
        }
        let effect = NSVisualEffectView()
        effect.material = .popover
        effect.state = .active
        effect.blendingMode = .behindWindow
        effect.wantsLayer = true
        effect.layer?.cornerRadius = radius
        effect.layer?.cornerCurve = .continuous
        effect.layer?.masksToBounds = true
        content.frame = effect.bounds
        effect.addSubview(content)
        return effect
    }
}

/// 키 창이 아니어도 첫 클릭을 단추가 받는다.
private final class FirstMouseHostingView<Content: View>: NSHostingView<Content> {
    override func acceptsFirstMouse(for event: NSEvent?) -> Bool { true }
}

struct UpdateCard: View {
    @ObservedObject var model: UpdateModel
    let controller: UpdateController?

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            HStack(alignment: .top, spacing: 10) {
                Image(nsImage: NSApp.applicationIconImage ?? NSImage())
                    .resizable().frame(width: 36, height: 36)
                VStack(alignment: .leading, spacing: 2) {
                    Text(title).font(.system(size: 13, weight: .semibold))
                    if !subtitle.isEmpty {
                        Text(subtitle).font(.system(size: 12)).foregroundStyle(.secondary)
                    }
                }
                Spacer(minLength: 0)
                if closable {
                    Button { controller?.close() } label: {
                        Image(systemName: "xmark").font(.system(size: 9, weight: .bold))
                    }
                    .buttonStyle(CloseButtonStyle())
                    .help("닫기")
                }
            }
            details
            actions
        }
        .padding(14)
        .frame(width: UpdatePanel.width, alignment: .leading)
        .fixedSize(horizontal: false, vertical: true)
    }

    private var version: String { model.release?.displayVersion ?? "" }

    private var title: String {
        switch model.phase {
        case .idle, .available: return model.release == nil ? "최신 버전입니다" : "새 버전이 나왔습니다"
        case .checking: return "새 버전을 확인하는 중"
        case .upToDate: return "최신 버전입니다"
        case .unavailable: return "이 Mac에는 설치할 수 없습니다"
        case .downloading: return "새 버전을 받는 중"
        case .verifying: return "받은 파일을 확인하는 중"
        case .opened: return "설치 프로그램을 열었습니다"
        case .failed(let title, _, _): return title
        }
    }

    private var subtitle: String {
        let current = "\(AppInfo.version) (\(AppInfo.build))"
        switch model.phase {
        case .available, .idle:
            return model.release == nil ? "\(AppInfo.name) \(current)" : "\(AppInfo.name) \(version) · 지금 \(AppInfo.version)"
        case .downloading, .opened: return "\(AppInfo.name) \(version)"
        case .verifying: return "세반시옷의 서명과 대조합니다"
        case .upToDate, .checking: return "\(AppInfo.name) \(current)"
        case .unavailable, .failed: return ""
        }
    }

    private var closable: Bool {
        switch model.phase {
        case .verifying, .checking: return false
        default: return true
        }
    }

    @ViewBuilder private var details: some View {
        switch model.phase {
        case .available:
            if let notes = model.release?.notes, !notes.isEmpty {
                VStack(alignment: .leading, spacing: 3) {
                    ForEach(Array(notes.prefix(4).enumerated()), id: \.offset) { _, note in
                        HStack(alignment: .firstTextBaseline, spacing: 6) {
                            Text("·").foregroundStyle(.secondary)
                            Text(note).fixedSize(horizontal: false, vertical: true)
                        }
                    }
                }
                .font(.system(size: 12))
            }
        case .downloading(let received, let total):
            VStack(alignment: .leading, spacing: 4) {
                ProgressView(value: Double(received), total: Double(max(total, 1)))
                Text("\(Self.megabytes(received)) / \(Self.megabytes(total))")
                    .font(.system(size: 11)).foregroundStyle(.secondary).monospacedDigit()
            }
        case .verifying, .checking:
            ProgressView().progressViewStyle(.linear)
        case .opened:
            Text("안내에 따라 설치하면 \(AppInfo.name)가 잠시 다시 시작됩니다. 쓰던 글은 먼저 확정해 두세요.")
                .font(.system(size: 12)).fixedSize(horizontal: false, vertical: true)
        case .unavailable(let message), .failed(_, let message, _):
            Text(message).font(.system(size: 12)).fixedSize(horizontal: false, vertical: true)
        case .idle, .upToDate:
            EmptyView()
        }
    }

    @ViewBuilder private var actions: some View {
        switch model.phase {
        case .available:
            HStack(spacing: 8) {
                Button("이 버전 건너뛰기") { controller?.skip() }
                    .buttonStyle(.plain).font(.system(size: 11)).foregroundStyle(.secondary)
                if model.release?.page != nil {
                    Button("자세히") { controller?.openPage() }
                        .buttonStyle(.plain).font(.system(size: 11)).foregroundStyle(.secondary)
                }
                Spacer()
                Button("나중에") { controller?.later() }.buttonStyle(CardButtonStyle())
                Button("업데이트") { controller?.install() }.buttonStyle(CardButtonStyle(prominent: true))
            }
        case .downloading:
            HStack { Spacer(); Button("취소") { controller?.cancelDownload() }.buttonStyle(CardButtonStyle()) }
        case .failed(_, _, _):
            HStack(spacing: 8) {
                Spacer()
                Button("닫기") { controller?.close() }.buttonStyle(CardButtonStyle())
                Button("다시 시도") { controller?.retry() }.buttonStyle(CardButtonStyle(prominent: true))
            }
        case .opened, .unavailable, .upToDate, .idle:
            HStack { Spacer(); Button("확인") { controller?.close() }.buttonStyle(CardButtonStyle()) }
        case .verifying, .checking:
            EmptyView()
        }
    }

    static func megabytes(_ bytes: Int64) -> String {
        String(format: "%.1f MB", Double(bytes) / 1_000_000)
    }
}

/// 키 창이 아닌 창에서도 흐려지지 않는 단추.
private struct CardButtonStyle: ButtonStyle {
    var prominent = false

    func makeBody(configuration: Configuration) -> some View {
        configuration.label
            .font(.system(size: 12, weight: prominent ? .semibold : .regular))
            .padding(.horizontal, 12)
            .padding(.vertical, 5)
            .foregroundStyle(prominent ? Color.white : Color.primary)
            .background(Capsule().fill(prominent ? Color.accentColor : Color.primary.opacity(0.1)))
            .contentShape(Capsule())
            .opacity(configuration.isPressed ? 0.7 : 1)
    }
}

private struct CloseButtonStyle: ButtonStyle {
    func makeBody(configuration: Configuration) -> some View {
        configuration.label
            .foregroundStyle(.secondary)
            .frame(width: 18, height: 18)
            .background(Circle().fill(Color.primary.opacity(configuration.isPressed ? 0.16 : 0.08)))
            .contentShape(Circle())
    }
}

// MARK: - 시험과 시안

extension Updater {
    /// 시험용 서명(앱은 서명하지 않는다. 출시 서명은 tools/update_manifest.py).
    static func testEnvelope(_ payload: [String: Any], key: Curve25519.Signing.PrivateKey, id: String) -> Data {
        let body = (try? JSONSerialization.data(withJSONObject: payload)) ?? Data()
        let signature = (try? key.signature(for: domain + body)) ?? Data()
        let envelope: [String: Any] = ["format": format, "key": id, "payload": body.base64EncodedString(),
                                       "signature": signature.base64EncodedString()]
        return (try? JSONSerialization.data(withJSONObject: envelope)) ?? Data()
    }

    static func samplePayload(build: Int = 40, platform: String = "macos", channel: String = "stable",
                              url: String = "https://dl.sebansios.com/maimusi/Maimusi-0.5.4.pkg",
                              bytes: Int = 4, sha256: String = String(repeating: "a", count: 64)) -> [String: Any] {
        ["format": format, "version": 1, "platform": platform, "channel": channel, "product": "0.5.4", "label": "",
         "build": build, "published": "2026-11-20", "notes": ["후보 창 테마", "단어장 맞추기"],
         "page": "https://sebansios.com/maimusi",
         "file": ["name": "Maimusi-0.5.4.pkg", "url": url, "bytes": bytes, "sha256": sha256]]
    }

    static func runSelfTest(check: (String, Bool, String) -> Void) {
        let key = Curve25519.Signing.PrivateKey()
        let other = Curve25519.Signing.PrivateKey()
        let keys = ["k1": key.publicKey.rawRepresentation]
        let good = testEnvelope(samplePayload(), key: key, id: "k1")
        let release = try? verify(good, keys: keys)
        check("update: signed manifest accepted", release?.build == 40 && release?.file.name == "Maimusi-0.5.4.pkg",
              release.map { "\($0.displayVersion) build \($0.build)" } ?? "rejected")

        func rejection(_ data: Data, _ k: [String: Data] = keys) -> Rejection? {
            do { _ = try verify(data, keys: k); return nil } catch { return error as? Rejection }
        }
        // 서명한 뒤 payload를 바꾼 경우.
        var tampered = (try? JSONSerialization.jsonObject(with: good)) as? [String: Any] ?? [:]
        let otherBody = (try? JSONSerialization.data(withJSONObject: samplePayload(build: 99))) ?? Data()
        tampered["payload"] = otherBody.base64EncodedString()
        let tamperedData = (try? JSONSerialization.data(withJSONObject: tampered)) ?? Data()
        check("update: tampered payload rejected", rejection(tamperedData) == .badSignature, "\(String(describing: rejection(tamperedData)))")
        check("update: other key rejected", rejection(testEnvelope(samplePayload(), key: other, id: "k1")) == .badSignature, "same id, wrong key")
        check("update: unknown key id rejected", rejection(testEnvelope(samplePayload(), key: key, id: "k9")) == .unknownKey, "k9")
        check("update: no keys means no updates", rejection(good, [:]) == .unknownKey, "empty key ring")
        check("update: other platform rejected", rejection(testEnvelope(samplePayload(platform: "windows"), key: key, id: "k1")) == .wrongPlatform, "windows manifest")
        check("update: pre-release channel rejected", rejection(testEnvelope(samplePayload(channel: "beta"), key: key, id: "k1")) == .unsupported, "beta")
        check("update: plain http file rejected",
              rejection(testEnvelope(samplePayload(url: "http://dl.sebansios.com/x.pkg"), key: key, id: "k1")) == .badFile, "http")
        check("update: bad hash rejected", rejection(testEnvelope(samplePayload(sha256: "zz"), key: key, id: "k1")) == .badFile, "sha256")
        check("update: oversized manifest rejected", rejection(Data(count: maxManifest + 1)) == .tooLarge, "> 64 KiB")

        let os = OperatingSystemVersion(majorVersion: 14, minorVersion: 2, patchVersion: 0)
        if let release {
            check("update: newer build offered", offer(release, currentBuild: 31, os: os, arch: "arm64") == .newer, "40 > 31")
            check("update: same or older build ignored", offer(release, currentBuild: 40, os: os, arch: "arm64") == .none
                  && offer(release, currentBuild: 45, os: os, arch: "arm64") == .none, "no downgrade")
        }
        var p = samplePayload()
        p["minimum_os"] = "14.3"
        p["architectures"] = ["arm64"]
        if let gated = try? verify(testEnvelope(p, key: key, id: "k1"), keys: keys) {
            check("update: minimum macOS respected", offer(gated, currentBuild: 31, os: os, arch: "arm64") == .needsNewerOS("14.3"), "14.2 < 14.3")
            check("update: architecture respected", offer(gated, currentBuild: 31, os: OperatingSystemVersion(majorVersion: 15, minorVersion: 0, patchVersion: 0), arch: "x86_64") == .otherArchitecture, "arm64 only")
        }

        let tmp = FileManager.default.temporaryDirectory.appendingPathComponent("maimusi-update-\(UUID().uuidString)")
        try? Data("abcd".utf8).write(to: tmp)
        defer { try? FileManager.default.removeItem(at: tmp) }
        let digest = hex(SHA256.hash(data: Data("abcd".utf8)))
        check("update: package hash matches", fileMatches(tmp, .init(name: "x.pkg", url: "", bytes: 4, sha256: digest)), "4 bytes")
        check("update: package size mismatch caught", !fileMatches(tmp, .init(name: "x.pkg", url: "", bytes: 3, sha256: digest)), "3 bytes")
    }
}

extension UpdateController {
    /// `--verify-update <정보 파일> <공개키 JSON>`: tools/update_manifest.py가 만든 파일을 앱 규칙으로 확인한다.
    static func runVerify(_ arguments: [String]) -> Int32 {
        guard let i = arguments.firstIndex(of: "--verify-update"), i + 2 < arguments.count,
              let data = FileManager.default.contents(atPath: arguments[i + 1]),
              let ring = FileManager.default.contents(atPath: arguments[i + 2]),
              let json = (try? JSONSerialization.jsonObject(with: ring)) as? [String: Any],
              let list = json["keys"] as? [String: String]
        else { return 2 }
        do {
            let r = try Updater.verify(data, keys: list.compactMapValues { Data(base64Encoded: $0) })
            print("OK \(r.platform) \(r.displayVersion) build \(r.build) \(r.file.name) \(r.file.bytes)")
            return 0
        } catch {
            print("REJECTED \(error)")
            return 1
        }
    }

    /// `--test-update <정보 주소> <공개키 JSON> <지금 빌드> <받을 폴더>`: 실제 요청으로 확인 → 받기 →
    /// 확인 → (설치 프로그램 대신) 결과 출력까지 돈다. 창은 띄우지 않는다.
    static func runFlowTest(_ arguments: [String]) -> Int32 {
        guard let i = arguments.firstIndex(of: "--test-update"), i + 4 < arguments.count,
              let url = URL(string: arguments[i + 1]),
              let ring = FileManager.default.contents(atPath: arguments[i + 2]),
              let json = (try? JSONSerialization.jsonObject(with: ring)) as? [String: Any],
              let list = json["keys"] as? [String: String], let build = Int(arguments[i + 3])
        else { return 2 }
        _ = NSApplication.shared
        let c = UpdateController.shared
        c.keys = list.compactMapValues { Data(base64Encoded: $0) }
        c.manifestURL = url
        c.currentBuild = build
        c.downloadDir = URL(fileURLWithPath: arguments[i + 4])
        c.presentsPanel = false
        c.allowLoopback = true
        var opened: URL?
        c.openInstaller = { file, done in opened = file; done(true) }
        func wait(_ until: () -> Bool) {
            let deadline = Date().addingTimeInterval(60)
            while !until() && Date() < deadline { RunLoop.main.run(until: Date().addingTimeInterval(0.05)) }
        }
        c.check(manual: true)
        wait { c.model.phase != .checking }
        print("check: \(c.model.phase) \(c.model.release.map { "\($0.displayVersion) build \($0.build)" } ?? "-")")
        guard c.model.phase == .available else { return c.model.phase == .upToDate ? 3 : 1 }
        c.install()
        wait {
            switch c.model.phase {
            case .opened, .failed: return true
            default: return false
            }
        }
        print("install: \(c.model.phase) \(opened?.lastPathComponent ?? "-")")
        return c.model.phase == .opened ? 0 : 1
    }

    /// `--show-update-sample [초]`: 실제 알림 창(유리 바탕)을 화면 오른쪽 위에 띄워 상태를 차례로
    /// 바꿔 보이고 창 크기를 출력한다. 단추는 눌러도 아무 일도 하지 않는다.
    static func showSample(_ arguments: [String]) -> Int32 {
        let app = NSApplication.shared
        app.setActivationPolicy(.accessory)
        CandidateTheme.simulatePreLiquidGlass = arguments.contains("--no-glass")
        let seconds = arguments.firstIndex(of: "--show-update-sample").flatMap {
            $0 + 1 < arguments.count ? Double(arguments[$0 + 1]) : nil } ?? 2
        let key = Curve25519.Signing.PrivateKey()
        var payload = Updater.samplePayload()
        payload["notes"] = ["자동 업데이트: 새 버전을 알리고 받아서 설치합니다", "한자 자형: 고른 자형만 후보에 냅니다"]
        let c = UpdateController.shared
        c.model.release = try? Updater.verify(Updater.testEnvelope(payload, key: key, id: "k"),
                                              keys: ["k": key.publicKey.rawRepresentation])
        let phases: [UpdateModel.Phase] = [.available, .downloading(41_300_000, 115_400_000), .verifying, .opened,
                                           .failed("내려받지 못했습니다", "인터넷 연결을 확인한 뒤 다시 시도해 주세요.", download: true)]
        for phase in phases {
            c.model.phase = phase
            c.showPanel()
            RunLoop.main.run(until: Date().addingTimeInterval(seconds))
            let p = c.panel
            print("\(phase): window \(p.frame) key=\(p.isKeyWindow) backdrop=\(type(of: p.contentView!)) content=\(p.contentView!.subviews.first.map { "\($0.frame)" } ?? "glass")")
        }
        c.hidePanel()
        return 0
    }

    /// `--render-update <폴더>`: 알림 창의 모든 상태를 그림으로(화면 밖, 단색 바탕).
    static func render(_ arguments: [String]) -> Int32 {
        guard let i = arguments.firstIndex(of: "--render-update"), i + 1 < arguments.count else { return 2 }
        let dir = URL(fileURLWithPath: arguments[i + 1])
        try? FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true)
        let app = NSApplication.shared
        let key = Curve25519.Signing.PrivateKey()
        var payload = Updater.samplePayload()
        payload["notes"] = ["자동 업데이트: 새 버전을 알리고 받아서 설치합니다", "한자 자형: 고른 자형만 후보에 냅니다",
                            "단어장을 고른 폴더로 기기 사이에 맞춥니다"]
        let sample = try? Updater.verify(Updater.testEnvelope(payload, key: key, id: "k"),
                                         keys: ["k": key.publicKey.rawRepresentation])
        let phases: [(String, UpdateModel.Phase, Bool)] = [
            ("available", .available, true),
            ("downloading", .downloading(41_300_000, 115_400_000), true),
            ("verifying", .verifying, true),
            ("opened", .opened, true),
            ("uptodate", .upToDate, false),
            ("failed", .failed("내려받지 못했습니다", "인터넷 연결을 확인한 뒤 다시 시도해 주세요.", download: true), true),
        ]
        for dark in [false, true] {
            app.appearance = NSAppearance(named: dark ? .darkAqua : .aqua)
            for (name, phase, hasRelease) in phases {
                let model = UpdateModel()
                model.release = hasRelease ? sample : nil
                model.phase = phase
                let card = UpdateCard(model: model, controller: nil)
                    .background(RoundedRectangle(cornerRadius: 18, style: .continuous)
                        .fill(dark ? Color(white: 0.2) : Color(white: 0.97)))
                    .padding(16)
                let host = NSHostingView(rootView: card)
                host.appearance = app.appearance
                host.frame = NSRect(origin: .zero, size: host.fittingSize)
                host.layoutSubtreeIfNeeded()
                guard let rep = host.bitmapImageRepForCachingDisplay(in: host.bounds) else { continue }
                host.cacheDisplay(in: host.bounds, to: rep)
                let out = dir.appendingPathComponent("update-\(name)-\(dark ? "dark" : "light").png")
                try? rep.representation(using: .png, properties: [:])?.write(to: out)
                print("rendered \(out.lastPathComponent) \(Int(host.bounds.width))x\(Int(host.bounds.height))")
            }
        }
        return 0
    }
}
