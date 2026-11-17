import AppKit
import SwiftUI

/// Settings window opened from the input menu.
enum PreferencesWindow {
    private static var window: NSWindow?

    static func show() {
        if window == nil {
            let w = NSWindow(contentRect: NSRect(x: 0, y: 0, width: 560, height: 720),
                             styleMask: [.titled, .closable], backing: .buffered, defer: false)
            w.title = "\(AppInfo.name) 설정"
            w.isReleasedWhenClosed = false
            w.contentView = NSHostingView(rootView: PreferencesView())
            w.center()
            window = w
        }
        NSApp.activate(ignoringOtherApps: true)
        window?.makeKeyAndOrderFront(nil)
    }
}

private struct Choice: Identifiable, Hashable {
    let value: String
    let label: String
    var id: String { value }
}

private let ruleModes = [
    Choice(value: "separate", label: "띄어 쓰기"),
    Choice(value: "join", label: "허용 범위에서 붙이기"),
    Choice(value: "model", label: "모델 판단"),
]

private final class PreferencesModel: ObservableObject {
    private let s = Settings.shared

    @Published var engine: SpacingEngine { didSet { s.engine = engine } }
    @Published var convertOnSpace: Bool { didSet { s.set(convertOnSpace, for: "convertOnSpace") } }
    @Published var spaceInConversion: String { didSet { s.set(spaceInConversion, for: "spaceInConversion") } }
    @Published var enterPassesThrough: Bool { didSet { s.set(enterPassesThrough, for: "enterPassesThrough") } }
    @Published var spaceImplicitCommits: Bool { didSet { s.set(spaceImplicitCommits, for: "spaceImplicitCommits") } }
    @Published var candidatesEnabled: Bool { didSet { s.set(candidatesEnabled, for: "candidatesEnabled") } }
    @Published var hanjaForms: String { didSet { s.set(hanjaForms, for: "hanjaForms") } }
    @Published var hanjaPresentation: String { didSet { s.set(hanjaPresentation, for: "hanjaPresentation") } }
    @Published var symbolConsonants: Bool { didSet { s.set(symbolConsonants, for: "symbolConsonants") } }
    @Published var hanjaGlossSearch: Bool { didSet { s.set(hanjaGlossSearch, for: "hanjaGlossSearch") } }
    @Published var idleUnloadMinutes: Int { didSet { s.set(idleUnloadMinutes, for: "idleUnloadMinutes") } }
    @Published var auxiliaries: String { didSet { s.set(auxiliaries, for: "rule.auxiliaries") } }
    @Published var compound: String { didSet { s.set(compound, for: "rule.compound") } }
    @Published var numberUnits: String { didSet { s.set(numberUnits, for: "rule.number_units") } }
    @Published var rememberBoundaries: Bool { didSet { s.set(rememberBoundaries, for: "rememberBoundaries") } }
    @Published var words: [String] = []
    @Published var learned: [[String: String]] = []
    var learnedCount: Int { learned.count }
    @Published var syncFolder = ""
    @Published var syncStatus = ""
    @Published var wordbookMessage = ""
    @Published var downloadedFontBytes = 0
    @Published var newWord = ""
    @Published var candidateTextSize: String { didSet { s.set(candidateTextSize, for: "candidateTextSize") } }
    @Published var fontAutoDownload: Bool {
        didSet {
            s.set(fontAutoDownload, for: "fontAutoDownload")
            fontStatus = CandidateFonts.status(for: candidateTheme.fontFamily)
        }
    }
    @Published var fontStatus = ""
    private var fontObserver: NSObjectProtocol?
    @Published var updateAutoCheck: Bool { didSet { s.set(updateAutoCheck, for: "updateAutoCheck") } }
    @Published var updateStatus = ""
    private var updateObserver: NSObjectProtocol?
    @Published var candidatePreset: String
    @Published var candidateTheme: CandidateTheme
    private var observer: NSObjectProtocol?
    private var syncObserver: NSObjectProtocol?

    /// 프리셋을 고르면 그 모양을 그대로 쓴다.
    func choosePreset(_ id: String) {
        guard let preset = CandidateTheme.preset(id) else { return }
        candidatePreset = id
        candidateTheme = preset.theme
        fontStatus = CandidateFonts.status(for: preset.theme.fontFamily)
        s.set(id, for: "candidatePreset")
    }

    /// 세부를 하나라도 바꾸면 「사용자 지정」으로 저장한다.
    func theme<T>(_ keyPath: WritableKeyPath<CandidateTheme, T>) -> Binding<T> {
        Binding(get: { self.candidateTheme[keyPath: keyPath] }, set: { value in
            self.candidateTheme[keyPath: keyPath] = value
            self.candidatePreset = "custom"
            self.fontStatus = CandidateFonts.status(for: self.candidateTheme.fontFamily)
            if let data = try? JSONEncoder().encode(self.candidateTheme) {
                self.s.set(data, for: "candidateTheme")
            }
            self.s.set("custom", for: "candidatePreset")
        })
    }

    func addWord() {
        if s.addWords([newWord]) { newWord = "" }
    }

    func removeWord(_ word: String) { s.removeWord(word) }
    func forgetBoundaries() { s.forgetBoundaries() }
    func forgetBoundary(_ compact: String) { s.forgetBoundary(compact) }

    /// 학습은 입력 중에 뒤에서 일어나므로, 설정이 바뀔 때마다 목록을 다시 읽는다.
    private func reloadLists() {
        words = s.userWords
        learned = s.learnedBoundaries
        syncFolder = s.string("syncFolder")
        downloadedFontBytes = CandidateFonts.downloadedBytes
        let last = UserDefaults.standard.double(forKey: "syncLast")
        let failure = UserDefaults.standard.string(forKey: "syncError") ?? ""
        syncStatus = syncFolder.isEmpty ? "" : !failure.isEmpty ? "맞추지 못했습니다: \(failure)"
            : last == 0 ? "아직 맞추지 않았습니다"
            : "마지막으로 맞춘 때: " + Date(timeIntervalSince1970: last).formatted(date: .abbreviated, time: .shortened)
    }

    // MARK: 단어장

    func exportWordbook() {
        let panel = NSSavePanel()
        panel.nameFieldStringValue = "매무시 단어장.json"
        panel.allowedContentTypes = [.json]
        guard panel.runModal() == .OK, let url = panel.url else { return }
        do {
            try Wordbook.export(to: url)
            wordbookMessage = "단어 \(words.count)개, 띄어쓰기 \(learned.count)개를 내보냈습니다."
        } catch {
            wordbookMessage = "내보내지 못했습니다."
        }
    }

    func importWordbook() {
        let panel = NSOpenPanel()
        panel.allowedContentTypes = [.json]
        panel.allowsMultipleSelection = false
        guard panel.runModal() == .OK, let url = panel.url else { return }
        do {
            let added = try Wordbook.importFile(url)
            wordbookMessage = "단어 \(added.words)개, 띄어쓰기 \(added.boundaries)개를 더했습니다."
        } catch {
            wordbookMessage = "매무시 단어장 파일이 아닙니다."
        }
    }

    func chooseSyncFolder() {
        let panel = NSOpenPanel()
        panel.canChooseDirectories = true
        panel.canChooseFiles = false
        panel.canCreateDirectories = true
        panel.prompt = "이 폴더로 맞추기"
        panel.message = "고른 폴더 안의 ‘Maimusi’ 폴더에 단어장 파일을 둡니다."
        guard panel.runModal() == .OK, let url = panel.url else { return }
        Wordbook.chooseFolder(url)
    }

    func stopSync() { Wordbook.chooseFolder(nil) }

    /// Finder에 보이는 폴더 이름(예: iCloud Drive). 전체 경로는 말풍선 도움말에.
    static func displayName(_ path: String) -> String {
        FileManager.default.displayName(atPath: path)
    }
    func syncNow() { Wordbook.syncNow() }

    // MARK: 개인정보

    func removeDownloadedFonts() {
        CandidateFonts.removeDownloaded()
        reloadLists()
    }

    // MARK: 업데이트

    func checkForUpdates() { UpdateController.shared.check(manual: true) }

    func reloadUpdateStatus() {
        let c = UpdateController.shared
        if let release = c.model.release {
            updateStatus = "새 버전 \(release.displayVersion) (\(release.build))"
        } else if let last = c.lastCheck {
            updateStatus = "마지막 확인 \(last.formatted(date: .abbreviated, time: .shortened)) · 최신 버전"
        } else {
            updateStatus = "아직 확인하지 않았습니다"
        }
    }

    func revealSettingsFile() {
        let url = FileManager.default.homeDirectoryForCurrentUser
            .appendingPathComponent("Library/Preferences/\(Bundle.main.bundleIdentifier ?? "").plist")
        NSWorkspace.shared.activateFileViewerSelecting([url])
    }

    init() {
        engine = s.engine
        convertOnSpace = s.bool("convertOnSpace")
        spaceInConversion = s.string("spaceInConversion")
        enterPassesThrough = s.bool("enterPassesThrough")
        spaceImplicitCommits = s.bool("spaceImplicitCommits")
        candidatesEnabled = s.bool("candidatesEnabled")
        hanjaForms = s.string("hanjaForms")
        hanjaPresentation = s.string("hanjaPresentation")
        symbolConsonants = s.bool("symbolConsonants")
        hanjaGlossSearch = s.bool("hanjaGlossSearch")
        idleUnloadMinutes = s.int("idleUnloadMinutes")
        auxiliaries = s.string("rule.auxiliaries")
        compound = s.string("rule.compound")
        numberUnits = s.string("rule.number_units")
        rememberBoundaries = s.bool("rememberBoundaries")
        candidateTextSize = s.string("candidateTextSize")
        fontAutoDownload = s.bool("fontAutoDownload")
        updateAutoCheck = s.bool("updateAutoCheck")
        candidatePreset = CandidateTheme.presetID(s.string("candidatePreset"))
        candidateTheme = CandidateTheme.load()
        fontStatus = CandidateFonts.status(for: candidateTheme.fontFamily)
        fontObserver = NotificationCenter.default.addObserver(forName: CandidateFonts.didChange, object: nil, queue: .main) { [weak self] _ in
            guard let self else { return }
            self.fontStatus = CandidateFonts.status(for: self.candidateTheme.fontFamily)
        }
        reloadLists()
        syncObserver = NotificationCenter.default.addObserver(forName: Wordbook.didSync, object: nil, queue: .main) { [weak self] _ in
            self?.reloadLists()
        }
        reloadUpdateStatus()
        updateObserver = NotificationCenter.default.addObserver(forName: UpdateController.didChange, object: nil, queue: .main) { [weak self] _ in
            self?.reloadUpdateStatus()
        }
        observer = NotificationCenter.default.addObserver(forName: Settings.didChange, object: nil, queue: .main) { [weak self] _ in
            self?.reloadLists()
        }
    }

    deinit {
        if let observer { NotificationCenter.default.removeObserver(observer) }
    }
}

private struct PreferencesView: View {
    @StateObject private var m = PreferencesModel()
    /// 창 높이. 시안 그림(`--render-settings`)에서는 모든 칸이 보이도록 키운다.
    var height: CGFloat = 720
    private let kiwiInstalled = EngineHub.shared.helper != nil

    var body: some View {
        Form {
            Section("띄어쓰기 엔진") {
                if Settings.lightModelBundled {
                    Picker("엔진", selection: $m.engine) {
                        Text("\(AppInfo.engineName) (고정확도, Kiwi 기반)").tag(SpacingEngine.kiwi)
                        Text("경량 (내장)").tag(SpacingEngine.light)
                    }
                    .pickerStyle(.radioGroup)
                    .disabled(!kiwiInstalled)
                }
                Text(!Settings.lightModelBundled
                     ? "\(AppInfo.engineName) 엔진은 Kiwi 형태소 분석기를 바탕으로 띄어씁니다. 실행 중에는 메모리를 600MB 정도 사용하며, 일정 시간 쓰지 않으면 자동으로 종료됩니다."
                     : kiwiInstalled
                     ? "\(AppInfo.engineName) 엔진은 정확도가 높지만 실행 중 메모리를 600MB 이상 씁니다. 준비되기 전이나 응답이 늦으면 경량 엔진이 대신 처리합니다."
                     : "이 설치본에는 Kiwi 헬퍼가 없어 경량 엔진만 사용합니다.")
                    .font(.caption).foregroundStyle(.secondary)
                Picker("쓰지 않을 때 \(AppInfo.engineName) 엔진 종료", selection: $m.idleUnloadMinutes) {
                    Text("10분 후").tag(10)
                    Text("20분 후").tag(20)
                    Text("60분 후").tag(60)
                    Text("종료하지 않음").tag(0)
                }
                .disabled(!kiwiInstalled || m.engine != .kiwi)
            }
            Section("키 동작") {
                Toggle("스페이스로 자동 띄어쓰기", isOn: $m.convertOnSpace)
                Picker("변환 중 스페이스", selection: $m.spaceInConversion) {
                    Text("선택 어절의 다음 후보 (일본어 입력기 방식)").tag("cycle")
                    Text("확정하고 공백 입력").tag("commit")
                }
                Toggle("조합 중 Enter는 확정 후 줄바꿈·전송까지", isOn: $m.enterPassesThrough)
                Toggle("방향키·Tab·클릭으로 확정할 때도 띄어쓰기", isOn: $m.spaceImplicitCommits)
                Toggle("↑↓ 후보 (한자·기호·이모지·단위·날짜)", isOn: $m.candidatesEnabled)
            }
            CandidateSection(m: m)
            Section("한자 변환") {
                Picker("변환 표기", selection: $m.hanjaPresentation) {
                    Text("한자 — 學校").tag("hanja")
                    Text("한글(한자) — 학교(學校)").tag("hangul_hanja")
                    Text("한자(한글) — 學校(학교)").tag("hanja_hangul")
                    Text("한글한자 — 학교學校").tag("hangulhanja")
                }
                .disabled(!m.candidatesEnabled)
                Picker("한자 자형", selection: $m.hanjaForms) {
                    Text("교육용 한자 규범 자형 (強·豐·祕)").tag("education")
                    Text("KS X 1001 자형 (强·豊·秘)").tag("ks")
                }
                .pickerStyle(.radioGroup)
                .disabled(!m.candidatesEnabled)
                Text("고른 자형만 후보에 나옵니다. 교육용 자형 𮕩(衰)는 맞는 글꼴이 드물어 KS 자형 衰도 함께 나옵니다.")
                    .font(.caption).foregroundStyle(.secondary)
                Toggle("훈음으로 한자 찾기 (살찔비 → 肥)", isOn: $m.hanjaGlossSearch)
                    .disabled(!m.candidatesEnabled)
                Text("뜻과 소리를 붙여 입력하고 Space를 누르면 그 한자가 후보 맨 앞에 나옵니다. 배울학학교교처럼 이어 쓰면 學校. 켜 두면 이런 입력은 띄어 쓰지 않습니다.")
                    .font(.caption).foregroundStyle(.secondary)
            }
            Section("기호 변환") {
                Text("/ → ·, [ ] → 다른 괄호, 알파 → α처럼 변환 후보에서 선택합니다. ‘괄호’로 괄호 쌍도 찾을 수 있습니다.")
                    .font(.caption).foregroundStyle(.secondary)
                Toggle("자음으로도 특수문자 목록 열기 (ㅁ·ㄷ·ㅎ 등)", isOn: $m.symbolConsonants)
                    .disabled(!m.candidatesEnabled)
            }
            Section("띄어쓰기 규칙 (\(AppInfo.engineName) 엔진)") {
                Picker("보조 용언 (먹어 보다)", selection: $m.auxiliaries) {
                    ForEach(ruleModes) { Text($0.label).tag($0.value) }
                }
                Picker("복합명사 (국어 사전)", selection: $m.compound) {
                    ForEach(ruleModes) { Text($0.label).tag($0.value) }
                }
                .help("붙이기를 선택하면 ‘국어 사전’은 ‘국어사전’으로 붙이고, ‘학교 도서관’ 같은 일반 명사구는 유지합니다.")
                Picker("숫자 + 단위 (10 개)", selection: $m.numberUnits) {
                    ForEach(ruleModes) { Text($0.label).tag($0.value) }
                }
                SpacingPreview(rules: "\(m.auxiliaries)|\(m.compound)|\(m.numberUnits)|\(m.words.count)")
                Text("Shift+Space는 일반 두벌식처럼 친 그대로 확정하고 띄웁니다. 자동 띄어쓰기를 잠시 쓰지 않을 때.")
                    .font(.caption).foregroundStyle(.secondary)
            }
            Section("사용자 단어 (\(AppInfo.engineName) 엔진)") {
                HStack {
                    TextField("단어", text: $m.newWord, prompt: Text("예: 찰떡엔진"))
                        .onSubmit { m.addWord() }
                    Button("추가") { m.addWord() }
                        .disabled(m.newWord.trimmingCharacters(in: .whitespaces).count < 2
                                  || m.newWord.contains(" "))
                }
                Text("등록한 단어 안에는 띄어쓰기를 넣지 않습니다. 단어 뒤에 붙는 조사는 그대로 붙여 씁니다.")
                    .font(.caption).foregroundStyle(.secondary)
                if !m.words.isEmpty {
                    ScrollView {
                        VStack(alignment: .leading, spacing: 4) {
                            ForEach(m.words.reversed(), id: \.self) { word in
                                HStack {
                                    Text(word)
                                    Spacer()
                                    Button { m.removeWord(word) } label: { Image(systemName: "minus.circle") }
                                        .buttonStyle(.borderless)
                                        .help("‘\(word)’ 지우기")
                                }
                            }
                        }
                    }
                    .frame(maxHeight: 120)
                }
                Toggle("직접 고친 경계 기억하기", isOn: $m.rememberBoundaries)
                Text("변환 중에 경계를 직접 고쳐 확정하면 한 번에 기억해 다음부터 같은 표현을 그렇게 띄어 씁니다. 합친 어절에서는 조사를 뗀 단어를 사용자 단어에 더합니다. 암호 칸, 주소·메일·경로가 섞인 글, 한글이 없는 말은 기억하지 않습니다. 잘못 기억했으면 입력 메뉴의 ‘방금 기억한 띄어쓰기 잊기’나 아래 목록에서 지웁니다.")
                    .font(.caption).foregroundStyle(.secondary)
                if !m.learned.isEmpty {
                    ScrollView {
                        VStack(alignment: .leading, spacing: 4) {
                            ForEach(m.learned.reversed(), id: \.self) { item in
                                HStack {
                                    Text(item["spaced"] ?? "")
                                    Spacer()
                                    Button { m.forgetBoundary(item["compact"] ?? "") } label: { Image(systemName: "minus.circle") }
                                        .buttonStyle(.borderless)
                                        .help("‘\(item["spaced"] ?? "")’ 잊기")
                                }
                            }
                        }
                    }
                    .frame(maxHeight: 120)
                }
                HStack {
                    Text("기억한 띄어쓰기 \(m.learnedCount)개").foregroundStyle(.secondary)
                    Spacer()
                    Button("모두 지우기") { m.forgetBoundaries() }
                        .disabled(m.learnedCount == 0)
                }
                HStack {
                    Button("단어장 내보내기…") { m.exportWordbook() }
                    Button("가져오기…") { m.importWordbook() }
                    Spacer()
                }
                if !m.wordbookMessage.isEmpty {
                    Text(m.wordbookMessage).font(.caption).foregroundStyle(.secondary)
                }
            }
            Section("기기 사이에 단어장 맞추기") {
                if m.syncFolder.isEmpty {
                    Button("폴더 고르기…") { m.chooseSyncFolder() }
                } else {
                    LabeledContent("폴더") {
                        Text(PreferencesModel.displayName(m.syncFolder))
                            .lineLimit(1).truncationMode(.middle)
                            .help((m.syncFolder as NSString).abbreviatingWithTildeInPath)
                    }
                    HStack {
                        Text(m.syncStatus).font(.caption).foregroundStyle(.secondary)
                        Spacer()
                        Button("지금 맞추기") { m.syncNow() }
                        Button("바꾸기…") { m.chooseSyncFolder() }
                        Button("그만") { m.stopSync() }
                    }
                }
                Text("고른 폴더 안의 ‘Maimusi’ 폴더에 이 기기의 단어장 파일을 두고, 다른 기기의 파일을 읽어 합칩니다. iCloud Drive·Google Drive·Dropbox·OneDrive처럼 폴더를 맞춰 주는 곳이나 외장 디스크 어디든 됩니다. 세반시옷 서버는 거치지 않습니다. 단어장에는 등록한 단어와 기억한 띄어쓰기가 들어 있으니 믿을 수 있는 곳을 고르세요.")
                    .font(.caption).foregroundStyle(.secondary)
            }
            Section("개인정보") {
                Text("입력한 글은 기록하지 않습니다. 모든 처리는 이 Mac 안에서 합니다.")
                LabeledContent("이 Mac에 남는 것") {
                    Text("설정, 단어 \(m.words.count)개, 기억한 띄어쓰기 \(m.learnedCount)개")
                }
                HStack {
                    Spacer()
                    Button("설정 파일 보기") { m.revealSettingsFile() }
                }
                LabeledContent("받아 둔 글꼴") {
                    if m.downloadedFontBytes > 0 {
                        HStack {
                            Text(ByteCountFormatter.string(fromByteCount: Int64(m.downloadedFontBytes), countStyle: .file))
                            Button("지우기") { m.removeDownloadedFonts() }
                        }
                    } else {
                        Text("없음")
                    }
                }
                LabeledContent("기기 밖으로 나가는 것") {
                    VStack(alignment: .trailing, spacing: 2) {
                        Text("확장 한자 글꼴 받기(입력한 내용은 보내지 않음)")
                        Text(m.updateAutoCheck ? "새 버전 확인: 하루 한 번" : "새 버전 확인: 직접 할 때만")
                        Text(m.syncFolder.isEmpty ? "단어장 맞추기: 쓰지 않음" : "단어장 맞추기: 고른 폴더")
                    }
                }
                Text("Time Machine 같은 백업은 설정 파일과 받아 둔 글꼴도 함께 백업합니다.")
                    .font(.caption).foregroundStyle(.secondary)
            }
            Section("정보") {
                LabeledContent("버전", value: "\(AppInfo.version) (\(AppInfo.build))")
                Toggle("새 버전 자동으로 확인", isOn: $m.updateAutoCheck)
                HStack {
                    Text(m.updateStatus).font(.caption).foregroundStyle(.secondary)
                    Spacer()
                    Button("지금 확인") { m.checkForUpdates() }
                }
                Text("하루 한 번 dl.sebansios.com에서 업데이트 정보 파일 하나를 받아 이 Mac에서 비교합니다. 입력한 내용·쓰는 판·기기 정보는 보내지 않습니다. 새 버전은 세반시옷의 서명이 맞을 때만 알리고, 받은 설치 파일도 서명된 크기·해시와 대조한 뒤 엽니다.")
                    .font(.caption).foregroundStyle(.secondary)
                if let site = AppInfo.website {
                    LabeledContent("웹사이트") { Link(site.host ?? site.absoluteString, destination: site) }
                }
                if !AppInfo.supportEmail.isEmpty,
                   let mail = URL(string: "mailto:\(AppInfo.supportEmail)") {
                    LabeledContent("문의") { Link(AppInfo.supportEmail, destination: mail) }
                }
                HStack {
                    Text(AppInfo.copyright).font(.caption).foregroundStyle(.secondary)
                    Spacer()
                    Button("라이선스 보기") { AppInfo.openLicenses() }
                }
            }
        }
        .formStyle(.grouped)
        .frame(width: 560, height: height)
    }
}

/// 색 하나: 「자동」이면 시스템 색(밝게/어둡게를 따른다).
private struct ThemeColorRow: View {
    let title: String
    @Binding var hex: String?
    let automatic: NSColor

    var body: some View {
        HStack {
            Text(title)
            Spacer()
            if hex == nil {
                Text("자동").foregroundStyle(.secondary)
            } else {
                Button("자동으로") { hex = nil }.buttonStyle(.borderless)
            }
            ColorPicker(title, selection: Binding(
                get: { Color(nsColor: NSColor(hex: hex) ?? automatic) },
                set: { hex = NSColor($0).hexString }), supportsOpacity: true)
                .labelsHidden()
        }
    }
}

/// 설정 창의 후보 창 미리보기. 실제 후보 창과 같은 뷰를 쓴다.
/// 띄어쓰기 규칙 예문: 규칙을 바꾸면 같은 문장이 어떻게 띄어지는지 바로 보인다.
private struct SpacingPreview: View {
    /// 규칙이 바뀔 때마다 다시 계산하도록 묶은 값.
    let rules: String
    static let sample = "국어사전을펴놓고사과10개를먹어보았다"
    @State private var text = SpacingPreview.sample
    @State private var result: String?

    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            TextField("예문", text: $text, prompt: Text(SpacingPreview.sample))
                .labelsHidden()
                .textFieldStyle(.roundedBorder)
            Text(result ?? "찰떡 엔진이 준비되면 결과가 보입니다")
                .font(.system(size: 15))
                .foregroundStyle(result == nil ? .secondary : .primary)
                .textSelection(.enabled)
                .frame(maxWidth: .infinity, alignment: .leading)
        }
        .task(id: rules + "\u{1}" + text) {
            let input = text.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty ? SpacingPreview.sample : text
            // 설정값이 저장되고 나서 계산한다(같은 실행 주기에 바뀐 값이 아직 안 들어갔을 수 있다).
            try? await Task.sleep(nanoseconds: 60_000_000)
            let rules = Settings.shared.spacingRules
            let spaced = await Task.detached { EngineHub.shared.preview(input, rules: rules) }.value
            if !Task.isCancelled { result = spaced }
        }
    }
}

private struct CandidatePreviewView: NSViewRepresentable {
    let theme: CandidateTheme

    static let hangulFamilies: [String] = NSFontManager.shared.availableFontFamilies.filter { family in
        guard let font = NSFontManager.shared.font(withFamily: family, traits: [], weight: 5, size: 13) else { return false }
        let set = font.coveredCharacterSet
        return set.contains(UnicodeScalar(0xD55C)!) && set.contains(UnicodeScalar(0xAD6D)!)
    }.sorted()

    func makeNSView(context: Context) -> NSView { NSView() }

    func updateNSView(_ container: NSView, context: Context) {
        container.subviews.forEach { $0.removeFromSuperview() }
        let view = CandidateView(theme: theme, content: .sample)
        view.translatesAutoresizingMaskIntoConstraints = false
        container.addSubview(view)
        NSLayoutConstraint.activate([
            view.centerXAnchor.constraint(equalTo: container.centerXAnchor),
            view.topAnchor.constraint(equalTo: container.topAnchor, constant: 10),
        ])
    }

    func sizeThatFits(_ proposal: ProposedViewSize, nsView: NSView, context: Context) -> CGSize? {
        let size = CandidateView(theme: theme, content: .sample).fittingSize
        return CGSize(width: proposal.width ?? size.width, height: size.height + 20)
    }
}

/// 설정 창의 「후보 창」 항목: 프리셋, 미리보기, 세부 조정.
private struct CandidateSection: View {
    @ObservedObject var m: PreferencesModel
    @State var expanded = false

    var body: some View {
        Section("후보 창") {
            Picker("모양", selection: Binding(get: { m.candidatePreset }, set: { m.choosePreset($0) })) {
                ForEach(CandidateTheme.presets) { Text($0.name).tag($0.id) }
                if m.candidatePreset == "custom" { Text("사용자 지정").tag("custom") }
            }
            Text(CandidateTheme.preset(m.candidatePreset)?.summary ?? "세부 조정에서 바꾼 모양")
                .font(.caption).foregroundStyle(.secondary)
            Picker("글자 크기", selection: $m.candidateTextSize) {
                ForEach(CandidateTheme.textScales, id: \.0) { Text($0.1).tag($0.0) }
            }
            .pickerStyle(.segmented)
            CandidatePreviewView(theme: m.candidateTheme.forThisMac.scaled(
                CandidateTheme.textScales.first { $0.0 == m.candidateTextSize }?.2 ?? 1))
                .frame(maxWidth: .infinity)
            Toggle("확장 한자 글꼴 자동으로 받기", isOn: $m.fontAutoDownload)
            Text(m.fontStatus)
                .font(.caption).foregroundStyle(.secondary)
            DisclosureGroup("세부 조정", isExpanded: $expanded) {
                Picker("모서리", selection: m.theme(\.corner)) {
                    Text("스퀘어클").tag(CandidateTheme.Corner.squircle)
                    Text("둥근 모서리").tag(CandidateTheme.Corner.rounded)
                    Text("각진 모서리").tag(CandidateTheme.Corner.square)
                }
                Slider(value: m.theme(\.radius), in: 2...24, step: 1) { Text("모서리 크기") }
                    .disabled(m.candidateTheme.corner == .square)
                Picker("배경", selection: m.theme(\.backdrop)) {
                    Text("반투명 (메뉴)").tag(CandidateTheme.Backdrop.menu)
                    Text("반투명 (팝오버)").tag(CandidateTheme.Backdrop.popover)
                    Text("어두운 반투명").tag(CandidateTheme.Backdrop.hud)
                    Text("유리 (Liquid Glass)").tag(CandidateTheme.Backdrop.glass)
                    Text("투명 유리").tag(CandidateTheme.Backdrop.clearGlass)
                    Text("단색").tag(CandidateTheme.Backdrop.solid)
                }
                if m.candidateTheme.isGlass {
                    Text(ProcessInfo.processInfo.isOperatingSystemAtLeast(OperatingSystemVersion(majorVersion: 26, minorVersion: 0, patchVersion: 0))
                         ? "Liquid Glass는 뒤 화면을 굴절해 비춥니다. 색조를 주려면 아래 배경색을 고르세요."
                         : "이 macOS에서는 Liquid Glass 대신 반투명 재질로 보입니다(macOS 26 이상).")
                        .font(.caption).foregroundStyle(.secondary)
                    ThemeColorRow(title: "유리 색조", hex: m.theme(\.background), automatic: .clear)
                }
                if m.candidateTheme.backdrop == .solid {
                    ThemeColorRow(title: "배경색", hex: m.theme(\.background), automatic: .windowBackgroundColor)
                    ThemeColorRow(title: "테두리", hex: m.theme(\.border), automatic: .clear)
                }
                ThemeColorRow(title: "글자", hex: m.theme(\.text), automatic: .labelColor)
                ThemeColorRow(title: "번호·출처", hex: m.theme(\.secondary), automatic: .secondaryLabelColor)
                ThemeColorRow(title: "선택", hex: m.theme(\.selectionColor), automatic: .controlAccentColor)
                ThemeColorRow(title: "선택한 글자", hex: m.theme(\.selectionText), automatic: .white)
                Picker("글꼴", selection: m.theme(\.fontFamily)) {
                    Text("시스템").tag(String?.none)
                    ForEach(CandidatePreviewView.hangulFamilies, id: \.self) { Text($0).tag(String?.some($0)) }
                }
                Slider(value: m.theme(\.fontSize), in: 12...24, step: 1) {
                    Text("글자 크기 \(Int(m.candidateTheme.fontSize))")
                }
                Picker("선택 표시", selection: m.theme(\.selection)) {
                    Text("채움").tag(CandidateTheme.Selection.fill)
                    Text("밑줄").tag(CandidateTheme.Selection.underline)
                    Text("왼쪽 막대").tag(CandidateTheme.Selection.bar)
                }
                Picker("배치", selection: m.theme(\.layout)) {
                    Text("세로").tag(CandidateTheme.Layout.vertical)
                    Text("가로").tag(CandidateTheme.Layout.horizontal)
                }
                .pickerStyle(.segmented)
                Slider(value: m.theme(\.padding), in: 2...16, step: 1) { Text("여백") }
                Toggle("번호", isOn: m.theme(\.showNumbers))
                Toggle("출처 (한자 뜻, 로마자 표기법 등)", isOn: m.theme(\.showNotes))
                    .disabled(m.candidateTheme.layout == .horizontal)
                Toggle("경계 조정 키 안내(⇧← 줄이기 · ⇧→ 늘리기)", isOn: m.theme(\.showTools))
                Toggle("키 안내", isOn: m.theme(\.showHint))
            }
        }
    }
}

extension PreferencesWindow {
    /// `--render-candidates`가 함께 뽑는 설정 화면 그림(세부 조정을 펼친 상태).
    /// `--render-settings <png>`: 설정 창 전체를 한 장으로(화면 밖).
    static func renderSettings(to url: URL) {
        let height: CGFloat = 4200
        let host = NSHostingView(rootView: PreferencesView(height: height))
        host.frame = NSRect(x: 0, y: 0, width: 560, height: height)
        host.layoutSubtreeIfNeeded()
        RunLoop.main.run(until: Date().addingTimeInterval(0.3))
        host.layoutSubtreeIfNeeded()
        guard let rep = host.bitmapImageRepForCachingDisplay(in: host.bounds) else { return }
        host.cacheDisplay(in: host.bounds, to: rep)
        try? rep.representation(using: .png, properties: [:])?.write(to: url)
    }

    static func renderCandidateSettings(to url: URL) {
        let host = NSHostingView(rootView: Form { CandidateSection(m: PreferencesModel(), expanded: true) }
            .formStyle(.grouped).frame(width: 560, height: 1180))
        host.frame = NSRect(x: 0, y: 0, width: 560, height: 1180)
        host.layoutSubtreeIfNeeded()
        guard let rep = host.bitmapImageRepForCachingDisplay(in: host.bounds) else { return }
        host.cacheDisplay(in: host.bounds, to: rep)
        try? rep.representation(using: .png, properties: [:])?.write(to: url)
    }
}
