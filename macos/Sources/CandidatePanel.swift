import AppKit

/// A small non-activating list of candidates shown under the composition,
/// nine per page (number keys pick within the page). Space or ↑/↓ move
/// through it from the keyboard (handled by the core); a click chooses a row.
/// 모양은 설정의 후보 창 테마(`CandidateTheme`)를 따른다.
final class CandidatePanel: NSPanel {
    static let shared = CandidatePanel()

    var onSelect: ((Int) -> Void)?
    var onSegmentAction: ((UInt32) -> Void)?
    private var theme = CandidateTheme.current()
    private var observer: NSObjectProtocol?

    private init() {
        super.init(contentRect: NSRect(x: 0, y: 0, width: 160, height: 40),
                   styleMask: [.nonactivatingPanel, .borderless],
                   backing: .buffered, defer: true)
        level = .popUpMenu
        isFloatingPanel = true
        hidesOnDeactivate = false
        hasShadow = true
        isOpaque = false
        backgroundColor = .clear
        observer = NotificationCenter.default.addObserver(forName: Settings.didChange, object: nil, queue: .main) { [weak self] _ in
            self?.theme = CandidateTheme.current()
        }
    }

    override var canBecomeKey: Bool { false }

    static let pageSize = CandidateContent.pageSize

    func show(_ items: [String], notes: [String], selected: Int, segmentActions: UInt32 = 0, remembered: Bool = false,
              below rect: NSRect) {
        // 부분 글꼴에 없는 확장 한자가 처음 나오면 전체 글꼴을 받아 둔다(다음 표시부터 쓰인다).
        CandidateFonts.ensureCoverage(for: items, family: theme.fontFamily)
        let view = CandidateView(theme: theme,
                                 content: CandidateContent(items: items, notes: notes, selected: selected,
                                                           segmentActions: segmentActions, remembered: remembered))
        view.onSelect = { [weak self] i in self?.onSelect?(i) }
        view.onSegmentAction = { [weak self] key in self?.onSegmentAction?(key) }
        contentView = view
        view.layoutSubtreeIfNeeded()
        let size = view.fittingSize
        var origin = NSPoint(x: rect.minX, y: rect.minY - size.height - 4)
        if let screen = NSScreen.screens.first(where: { $0.frame.contains(rect.origin) }) ?? NSScreen.main {
            let vf = screen.visibleFrame
            if origin.y < vf.minY { origin.y = rect.maxY + 4 }
            origin.x = min(max(origin.x, vf.minX), vf.maxX - size.width)
        }
        setFrame(NSRect(origin: origin, size: size), display: true)
        view.layoutSubtreeIfNeeded()
        invalidateShadow()
        orderFrontRegardless()
    }

    func hide() {
        orderOut(nil)
        onSelect = nil
        onSegmentAction = nil
    }
}
