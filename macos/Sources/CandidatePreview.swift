import AppKit

/// `HangulSpacing --render-candidates <폴더>`: 프리셋마다 밝게·어둡게 후보 창 그림을 만들고
/// 한 장짜리 비교표(`candidates-sheet.png`)로 모은다. 실제 후보 창과 같은 `CandidateView`로 그린다.
/// 반투명 재질은 화면 밖에서 그릴 수 없어 비슷한 단색으로 대신한다.
enum CandidatePreview {
    /// 문서 한 줄과 그 아래에 뜬 후보 창.
    private final class Scene: NSView {
        let panel: CandidateView
        let dark: Bool
        static let margin: CGFloat = 28
        static let lineHeight: CGFloat = 34

        init(theme: CandidateTheme, dark: Bool) {
            self.dark = dark
            panel = CandidateView(theme: theme, content: .sample, offscreenDark: dark)
            super.init(frame: .zero)
            appearance = NSAppearance(named: dark ? .darkAqua : .aqua)
            panel.layoutSubtreeIfNeeded()
            let size = panel.fittingSize
            frame = NSRect(x: 0, y: 0, width: max(size.width, 220) + Self.margin * 2,
                           height: Self.lineHeight + size.height + Self.margin * 2 + 6)
            panel.frame = NSRect(x: Self.margin, y: Self.margin + Self.lineHeight + 6, width: size.width, height: size.height)
            addSubview(panel)
            panel.layoutSubtreeIfNeeded()
        }

        required init?(coder: NSCoder) { fatalError() }
        override var isFlipped: Bool { true }

        override func draw(_ dirtyRect: NSRect) {
            (dark ? NSColor(srgbRed: 0.12, green: 0.12, blue: 0.13, alpha: 1) : NSColor(srgbRed: 0.98, green: 0.98, blue: 0.97, alpha: 1)).setFill()
            bounds.fill()
            // 조합 중인 문장: 앞부분과, 밑줄 친 선택 어절.
            let ink = dark ? NSColor(white: 0.92, alpha: 1) : NSColor(white: 0.12, alpha: 1)
            let font = NSFont.systemFont(ofSize: 17)
            let before = NSAttributedString(string: "내일 ", attributes: [.font: font, .foregroundColor: ink])
            let word = NSAttributedString(string: "학교", attributes: [
                .font: font, .foregroundColor: ink,
                .underlineStyle: NSUnderlineStyle.thick.rawValue,
            ])
            let after = NSAttributedString(string: "에 간다", attributes: [.font: font, .foregroundColor: ink])
            var x = Self.margin + 9
            let y = Self.margin + 4
            for s in [before, word, after] {
                s.draw(at: NSPoint(x: x, y: y))
                x += s.size().width
            }
            // 창 그림자.
            NSGraphicsContext.saveGraphicsState()
            let shadow = NSShadow()
            shadow.shadowBlurRadius = 14
            shadow.shadowOffset = NSSize(width: 0, height: -5)
            shadow.shadowColor = NSColor.black.withAlphaComponent(dark ? 0.55 : 0.18)
            shadow.set()
            // 그림자만 보이도록 창보다 조금 안쪽 도형으로 깐다.
            let path = CandidateShape.path(panel.frame.insetBy(dx: 2, dy: 2), radius: panel.theme.cornerRadius, corner: panel.theme.corner)
            let ctx = NSGraphicsContext.current!.cgContext
            ctx.addPath(path)
            ctx.setFillColor(NSColor.black.cgColor)
            ctx.fillPath()
            NSGraphicsContext.restoreGraphicsState()
        }
    }

    private static func image(of view: NSView, scale: CGFloat = 2) -> NSBitmapImageRep {
        let rep = NSBitmapImageRep(bitmapDataPlanes: nil, pixelsWide: Int(view.bounds.width * scale),
                                   pixelsHigh: Int(view.bounds.height * scale), bitsPerSample: 8,
                                   samplesPerPixel: 4, hasAlpha: true, isPlanar: false,
                                   colorSpaceName: .deviceRGB, bytesPerRow: 0, bitsPerPixel: 0)!
        rep.size = view.bounds.size
        view.cacheDisplay(in: view.bounds, to: rep)
        return rep
    }

    static func run(_ arguments: [String]) -> Int32 {
        guard let i = arguments.firstIndex(of: "--render-candidates"), i + 1 < arguments.count else {
            print("usage: --render-candidates <dir>")
            return 2
        }
        let dir = URL(fileURLWithPath: arguments[i + 1])
        // 앱 밖에서 돌릴 때는 --fonts <폴더>로 글꼴을 준다(예: build/fonts).
        if let f = arguments.firstIndex(of: "--fonts"), f + 1 < arguments.count {
            CandidateFonts.setUp(bundleDir: URL(fileURLWithPath: arguments[f + 1]))
        }
        try? FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true)
        _ = NSApplication.shared
        var rows: [(CandidateTheme.Preset, NSBitmapImageRep, NSBitmapImageRep)] = []
        for preset in CandidateTheme.presets {
            let light = image(of: Scene(theme: preset.theme, dark: false))
            let dark = image(of: Scene(theme: preset.theme, dark: true))
            for (rep, mode) in [(light, "light"), (dark, "dark")] {
                try? rep.representation(using: .png, properties: [:])?
                    .write(to: dir.appendingPathComponent("candidate-\(preset.id)-\(mode).png"))
            }
            rows.append((preset, light, dark))
        }
        // 비교표.
        let labelW: CGFloat = 220, gap: CGFloat = 16
        let colW = rows.map { max($0.1.size.width, $0.2.size.width) }.max() ?? 300
        let height = rows.reduce(gap) { $0 + max($1.1.size.height, $1.2.size.height) + gap }
        let width = labelW + colW * 2 + gap * 4
        let sheet = NSImage(size: NSSize(width: width, height: height), flipped: true) { _ in
            NSColor(white: 0.9, alpha: 1).setFill()
            NSRect(x: 0, y: 0, width: width, height: height).fill()
            var y = gap
            for (preset, light, dark) in rows {
                let h = max(light.size.height, dark.size.height)
                NSAttributedString(string: preset.name, attributes: [.font: NSFont.boldSystemFont(ofSize: 18)])
                    .draw(at: NSPoint(x: gap, y: y + 8))
                NSAttributedString(string: preset.summary, attributes: [
                    .font: NSFont.systemFont(ofSize: 12), .foregroundColor: NSColor.darkGray,
                ]).draw(in: NSRect(x: gap, y: y + 36, width: labelW - gap, height: h - 36))
                light.draw(in: NSRect(x: labelW + gap, y: y, width: light.size.width, height: light.size.height),
                           from: .zero, operation: .sourceOver, fraction: 1, respectFlipped: true, hints: nil)
                dark.draw(in: NSRect(x: labelW + colW + gap * 2, y: y, width: dark.size.width, height: dark.size.height),
                          from: .zero, operation: .sourceOver, fraction: 1, respectFlipped: true, hints: nil)
                y += h + gap
            }
            return true
        }
        let rep = NSBitmapImageRep(bitmapDataPlanes: nil, pixelsWide: Int(width * 2), pixelsHigh: Int(height * 2),
                                   bitsPerSample: 8, samplesPerPixel: 4, hasAlpha: true, isPlanar: false,
                                   colorSpaceName: .deviceRGB, bytesPerRow: 0, bitsPerPixel: 0)!
        rep.size = sheet.size
        NSGraphicsContext.saveGraphicsState()
        NSGraphicsContext.current = NSGraphicsContext(bitmapImageRep: rep)
        sheet.draw(in: NSRect(origin: .zero, size: sheet.size))
        NSGraphicsContext.restoreGraphicsState()
        try? rep.representation(using: .png, properties: [:])?.write(to: dir.appendingPathComponent("candidates-sheet.png"))
        PreferencesWindow.renderCandidateSettings(to: dir.appendingPathComponent("settings-candidate.png"))
        print("rendered \(rows.count) presets to \(dir.path)")
        return 0
    }

    /// `--capture-candidates <폴더> [프리셋…]`: 실제 화면에 문서 창과 후보 창을 띄우고 찍는다.
    /// Liquid Glass·반투명 재질은 화면에서만 그려지므로 이것으로 확인한다(화면 기록 권한 필요).
    static func capture(_ arguments: [String]) -> Int32 {
        guard let i = arguments.firstIndex(of: "--capture-candidates"), i + 1 < arguments.count else { return 2 }
        let dir = URL(fileURLWithPath: arguments[i + 1])
        try? FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true)
        let ids = Array(arguments[(i + 2)...].prefix { !$0.hasPrefix("--") })
        let app = NSApplication.shared
        app.setActivationPolicy(.accessory)
        if let f = arguments.firstIndex(of: "--fonts"), f + 1 < arguments.count {
            CandidateFonts.setUp(bundleDir: URL(fileURLWithPath: arguments[f + 1]))
        }
        CandidateTheme.simulatePreLiquidGlass = arguments.contains("--no-glass")

        let screen = NSScreen.main!.visibleFrame
        let docRect = NSRect(x: screen.midX - 260, y: screen.midY - 200, width: 520, height: 400)
        let doc = NSWindow(contentRect: docRect, styleMask: [.borderless], backing: .buffered, defer: false)
        doc.level = .floating
        doc.contentView = DocumentBackdrop()
        doc.orderFrontRegardless()
        var presets = CandidateTheme.presets
        // 투명 유리는 프리셋이 아니라 세부 조정의 배경 선택이다. 확인용으로만 덧붙인다.
        if let glass = presets.first(where: { $0.id == "glass" }) {
            var theme = glass.theme
            theme.backdrop = .clearGlass
            presets.append(.init(id: "clearGlass", name: "투명 유리", summary: "", theme: theme))
        }
        for preset in presets where ids.isEmpty || ids.contains(preset.id) {
            for dark in [false, true] {
                app.appearance = NSAppearance(named: dark ? .darkAqua : .aqua)
                doc.contentView?.needsDisplay = true
                let view = CandidateView(theme: preset.theme.forThisMac, content: .sample)
                view.layoutSubtreeIfNeeded()
                let size = view.fittingSize
                print("\(preset.id) \(dark ? "dark" : "light"): \(Int(size.width))x\(Int(size.height)) backdrop \(type(of: view.subviews.first ?? view))")
                let panel = NSPanel(contentRect: NSRect(x: docRect.minX + 40, y: docRect.maxY - 70 - size.height,
                                                        width: size.width, height: size.height),
                                    styleMask: [.nonactivatingPanel, .borderless], backing: .buffered, defer: false)
                panel.level = .popUpMenu
                panel.isOpaque = false
                panel.backgroundColor = .clear
                panel.hasShadow = true
                panel.contentView = view
                panel.orderFrontRegardless()
                RunLoop.main.run(until: Date().addingTimeInterval(0.8))
                panel.invalidateShadow()
                RunLoop.main.run(until: Date().addingTimeInterval(0.4))
                // screencapture의 -R은 왼쪽 위 기준 좌표.
                let top = NSScreen.screens[0].frame.maxY - docRect.maxY
                let tag = CandidateTheme.simulatePreLiquidGlass ? "-pre26" : ""
                let out = dir.appendingPathComponent("live-\(preset.id)\(tag)-\(dark ? "dark" : "light").png")
                let p = Process()
                p.executableURL = URL(fileURLWithPath: "/usr/sbin/screencapture")
                p.arguments = ["-x", "-R", "\(Int(docRect.minX)),\(Int(top)),\(Int(docRect.width)),\(Int(docRect.height))", out.path]
                try? p.run()
                p.waitUntilExit()
                // 권한이 없으면 screencapture가 실패한다. 이 프로세스의 창은 권한 없이 찍힐 수 있다.
                if !FileManager.default.fileExists(atPath: out.path),
                   let image = ownWindowsImage(CGRect(x: docRect.minX, y: top, width: docRect.width, height: docRect.height)) {
                    try? NSBitmapImageRep(cgImage: image).representation(using: .png, properties: [:])?.write(to: out)
                }
                print(FileManager.default.fileExists(atPath: out.path) ? "captured \(out.lastPathComponent)" : "capture failed")
                // --hold <초>: 화면 기록 권한이 없을 때 눈으로 보도록 띄워 둔다.
                if let h = arguments.firstIndex(of: "--hold"), h + 1 < arguments.count, let s = Double(arguments[h + 1]) {
                    RunLoop.main.run(until: Date().addingTimeInterval(s))
                }
                panel.orderOut(nil)
            }
        }
        doc.orderOut(nil)
        return 0
    }

    /// CGWindowListCreateImage(SDK에서는 막혔지만 런타임에는 남아 있다)로 화면 영역을 찍는다.
    private static func ownWindowsImage(_ rect: CGRect) -> CGImage? {
        typealias Fn = @convention(c) (CGRect, UInt32, UInt32, UInt32) -> Unmanaged<CGImage>?
        guard let sym = dlsym(UnsafeMutableRawPointer(bitPattern: -2), "CGWindowListCreateImage") else { return nil }
        return unsafeBitCast(sym, to: Fn.self)(rect, 1, 0, 8)?.takeRetainedValue()
    }

    /// 후보 창 뒤에 깔 문서: 글자와 색 도형(유리 굴절이 보이도록).
    private final class DocumentBackdrop: NSView {
        override var isFlipped: Bool { true }
        override func draw(_ dirtyRect: NSRect) {
            let dark = effectiveAppearance.bestMatch(from: [.darkAqua, .aqua]) == .darkAqua
            (dark ? NSColor(srgbRed: 0.11, green: 0.11, blue: 0.12, alpha: 1) : NSColor(srgbRed: 0.98, green: 0.98, blue: 0.97, alpha: 1)).setFill()
            bounds.fill()
            let shapes: [(NSRect, NSColor)] = [
                (NSRect(x: 60, y: 120, width: 140, height: 140), NSColor(srgbRed: 0.18, green: 0.31, blue: 0.29, alpha: 1)),
                (NSRect(x: 230, y: 170, width: 200, height: 90), NSColor(srgbRed: 0.62, green: 0.75, blue: 0.70, alpha: 1)),
                (NSRect(x: 120, y: 280, width: 260, height: 60), NSColor(srgbRed: 0.85, green: 0.55, blue: 0.30, alpha: 1)),
            ]
            for (r, c) in shapes { c.setFill(); NSBezierPath(ovalIn: r).fill() }
            let ink = dark ? NSColor(white: 0.92, alpha: 1) : NSColor(white: 0.12, alpha: 1)
            let body = "띄어쓰기 없이 입력한 문장을 스페이스 한 번으로 띄어 씁니다. 후보 창 뒤로 지나가는 글자와 도형이 유리에 굴절되어 비칩니다."
            NSAttributedString(string: body, attributes: [.font: NSFont.systemFont(ofSize: 15), .foregroundColor: ink])
                .draw(in: NSRect(x: 28, y: 60, width: bounds.width - 56, height: 200))
            let font = NSFont.systemFont(ofSize: 17)
            NSAttributedString(string: "내일 학교에 간다", attributes: [.font: font, .foregroundColor: ink])
                .draw(at: NSPoint(x: 40, y: 22))
        }
    }
}
