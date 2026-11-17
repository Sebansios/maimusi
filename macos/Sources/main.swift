import Cocoa
import InputMethodKit

// A dead helper must not kill the input method through SIGPIPE.
signal(SIGPIPE, SIG_IGN)

let arguments = CommandLine.arguments
// 후보 창 기본 글꼴(앱 안의 Noto CJK KR 부분 글꼴).
CandidateFonts.setUp()
if arguments.contains("--self-test") {
    exit(SelfTest.run())
}
if arguments.contains("--test-font-download") {
    exit(CandidateFonts.runDownloadTest(arguments))
}
if let i = arguments.firstIndex(of: "--render-settings"), i + 1 < arguments.count {
    _ = NSApplication.shared
    if let f = arguments.firstIndex(of: "--fonts"), f + 1 < arguments.count {
        CandidateFonts.setUp(bundleDir: URL(fileURLWithPath: arguments[f + 1]))
    }
    PreferencesWindow.renderSettings(to: URL(fileURLWithPath: arguments[i + 1]))
    exit(0)
}
if arguments.contains("--verify-update") {
    exit(UpdateController.runVerify(arguments))
}
if arguments.contains("--test-update") {
    exit(UpdateController.runFlowTest(arguments))
}
if arguments.contains("--show-update-sample") {
    exit(UpdateController.showSample(arguments))
}
if arguments.contains("--render-update") {
    exit(UpdateController.render(arguments))
}
if arguments.contains("--test-wordbook-sync") {
    exit(Wordbook.runSyncTest(arguments))
}
if arguments.contains("--capture-candidates") {
    exit(CandidatePreview.capture(arguments))
}
if arguments.contains("--render-candidates") {
    exit(CandidatePreview.run(arguments))
}
if arguments.contains(where: { ["--register", "--enable", "--unregister"].contains($0) }) {
    exit(Installer.run(arguments))
}

let info = Bundle.main.infoDictionary ?? [:]
guard let connection = info["InputMethodConnectionName"] as? String,
      let server = IMKServer(name: connection, bundleIdentifier: Bundle.main.bundleIdentifier)
else {
    Log.lifecycle.error("IMKServer could not be created")
    exit(1)
}
Log.lifecycle.notice("input method server started (\(connection, privacy: .public))")

// Load the spacing model before the first keystroke.
_ = EngineHub.shared
// 동기화 폴더를 골랐으면 단어장을 맞춘다(세반시옷 서버는 쓰지 않는다).
Wordbook.start()
// 하루 한 번 새 버전 확인(설정에서 끌 수 있다). 서명이 맞는 업데이트 정보만 쓴다.
UpdateController.shared.start()

let app = NSApplication.shared
app.setActivationPolicy(.accessory)
withExtendedLifetime(server) {
    app.run()
}
