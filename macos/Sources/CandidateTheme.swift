import AppKit

/// 후보 창의 모양. 프리셋으로 고르거나 설정에서 하나하나 바꿀 수 있다.
/// 색은 "#RRGGBB" 또는 "#RRGGBBAA"이고, nil이면 시스템 색(밝게/어둡게 모드를 따른다)을 쓴다.
struct CandidateTheme: Codable, Equatable {
    enum Corner: String, Codable, CaseIterable { case squircle, rounded, square }
    /// 배경: 시스템 반투명 재질, Liquid Glass(macOS 26 이상, 그 전에는 반투명 재질), 단색.
    enum Backdrop: String, Codable, CaseIterable { case menu, popover, hud, glass, clearGlass, solid }
    enum Selection: String, Codable, CaseIterable { case fill, underline, bar }
    enum Layout: String, Codable, CaseIterable { case vertical, horizontal }

    var corner: Corner = .squircle
    var radius: Double = 14
    var backdrop: Backdrop = .popover
    var background: String? = nil
    var border: String? = nil
    var fontFamily: String? = CandidateTheme.sans
    var fontSize: Double = 15
    var text: String? = nil
    var secondary: String? = nil
    var selection: Selection = .fill
    var selectionColor: String? = nil
    var selectionText: String? = nil
    var layout: Layout = .vertical
    var showNumbers = true
    var showNotes = true
    var showTools = true
    var showHint = false
    var padding: Double = 8
}

extension CandidateTheme {
    struct Preset: Identifiable {
        let id: String
        let name: String
        let summary: String
        let theme: CandidateTheme
    }

    static let defaultPresetID = "glass"

    /// Liquid Glass가 없는 macOS(26 이전)에서 유리 대신 그리는 모양:
    /// 연속 곡률(스퀘어클) 모서리와 시스템 반투명 재질.
    static let squircle = CandidateTheme()

    /// 시험용(`--capture-candidates --no-glass`): macOS 26 이전처럼 그린다.
    static var simulatePreLiquidGlass = false

    static var hasLiquidGlass: Bool {
        if simulatePreLiquidGlass { return false }
        if #available(macOS 26.0, *) { return true }
        return false
    }

    /// 저장된 프리셋 이름. 0.5.3 시험판의 「스퀘어클」은 「유리」로 합쳤다.
    static func presetID(_ stored: String?) -> String {
        guard let stored, !stored.isEmpty else { return defaultPresetID }
        return stored == "squircle" ? "glass" : stored
    }

    /// 이 Mac에서 실제로 그릴 모양. 유리를 그릴 수 없으면 스퀘어클로 대신한다.
    var forThisMac: CandidateTheme {
        guard isGlass, !CandidateTheme.hasLiquidGlass else { return self }
        if self == CandidateTheme.preset("glass")?.theme { return CandidateTheme.squircle }
        var fallback = self
        fallback.backdrop = CandidateTheme.squircle.backdrop
        return fallback
    }
    /// 앱에 넣은 기본 글꼴(Noto CJK KR 부분 글꼴, SIL OFL 1.1). 없으면 시스템 글꼴로 그린다.
    static let sans = "Noto Sans CJK KR"
    static let serif = "Noto Serif CJK KR"

    /// 시안. 글꼴은 앱에 넣은 Noto CJK KR만 쓰고, 0.5.2 모양만 시스템 글꼴.
    static let presets: [Preset] = [
        Preset(id: "glass", name: "유리",
               summary: "macOS Liquid Glass. 뒤 화면이 비치고 가장자리에 빛이 맺힌다. macOS 26 이전에는 연속 곡률 모서리의 반투명 창(스퀘어클)",
               theme: CandidateTheme(corner: .squircle, radius: 18, backdrop: .glass,
                                     fontSize: 16, selection: .fill, padding: 10)),
        Preset(id: "lacquer", name: "옻칠",
               summary: "흑칠 바탕에 주칠 선택, 한지색 글자",
               theme: CandidateTheme(corner: .squircle, radius: 12, backdrop: .solid,
                                     background: "#120C0AF7", border: "#2E201A",
                                     fontFamily: CandidateTheme.sans, fontSize: 15,
                                     text: "#E8DAC2", secondary: "#8E7A68",
                                     selection: .fill, selectionColor: "#B5462F", selectionText: "#FFF4E6",
                                     padding: 8)),
        Preset(id: "hanji", name: "한지",
               summary: "한지색 바탕, 명조, 각진 모서리, 먹색 밑줄 선택",
               theme: CandidateTheme(corner: .square, radius: 0, backdrop: .solid,
                                     background: "#F4EFE3", border: "#D6CDB8",
                                     fontFamily: CandidateTheme.serif, fontSize: 16,
                                     text: "#2B2A26", secondary: "#8C8475",
                                     selection: .underline, selectionColor: "#2F4F4A", selectionText: "#2F4F4A",
                                     padding: 10)),
        Preset(id: "ink", name: "먹",
               summary: "흰 바탕에 먹색 선택, 흑백만",
               theme: CandidateTheme(corner: .squircle, radius: 8, backdrop: .solid,
                                     background: "#FFFFFF", border: "#00000024",
                                     fontFamily: CandidateTheme.sans, fontSize: 15,
                                     text: "#1A1A1A", secondary: "#8A8A8A",
                                     selection: .fill, selectionColor: "#1A1A1A", selectionText: "#FFFFFF",
                                     padding: 6)),
        Preset(id: "celadon", name: "청자",
               summary: "청자 유약색 바탕, 쪽빛 먹청 선택",
               theme: CandidateTheme(corner: .squircle, radius: 16, backdrop: .solid,
                                     background: "#DCE8E2F7", border: "#B9CEC4",
                                     fontFamily: CandidateTheme.sans, fontSize: 15,
                                     text: "#1F3532", secondary: "#5E7A72",
                                     selection: .fill, selectionColor: "#2F4F4A", selectionText: "#F4F1E8",
                                     padding: 9)),
        Preset(id: "strip", name: "가로",
               summary: "후보를 한 줄로 늘어놓는 작은 띠",
               theme: CandidateTheme(corner: .squircle, radius: 10, backdrop: .menu,
                                     fontSize: 15, selection: .fill,
                                     layout: .horizontal, showNotes: false, showTools: false, padding: 6)),
        Preset(id: "quiet", name: "담백",
               summary: "배경을 거의 비우고 선택은 왼쪽 막대로만",
               theme: CandidateTheme(corner: .squircle, radius: 10, backdrop: .menu,
                                     fontSize: 15, selection: .bar,
                                     showNumbers: false, showTools: false, padding: 6)),
        Preset(id: "classic", name: "기본(0.5.2)",
               summary: "0.5.2까지의 모양",
               theme: CandidateTheme(corner: .rounded, radius: 6, backdrop: .menu,
                                     fontFamily: nil, fontSize: 15, selection: .fill,
                                     showHint: true, padding: 4)),
    ]

    static func preset(_ id: String) -> Preset? { presets.first { $0.id == id } }

    // MARK: 해석

    func font(_ size: Double? = nil, secondary: Bool = false) -> NSFont {
        let s = CGFloat(secondary ? max(10, (size ?? fontSize) * 0.72) : (size ?? fontSize))
        if let family = fontFamily, let f = CandidateFonts.font(family: family, size: s) {
            return f
        }
        return .systemFont(ofSize: s)
    }

    var textColor: NSColor { NSColor(hex: text) ?? .labelColor }
    var secondaryColor: NSColor { NSColor(hex: secondary) ?? .secondaryLabelColor }
    var selectionFill: NSColor { NSColor(hex: selectionColor) ?? .controlAccentColor }
    var selectionTextColor: NSColor {
        if let c = NSColor(hex: selectionText) { return c }
        return selection == .fill ? .white : selectionFill
    }
    /// 단색 배경. nil이면 창 배경색(밝게/어둡게를 따른다).
    var solidBackground: NSColor { NSColor(hex: background) ?? .windowBackgroundColor }
    var borderColor: NSColor? { NSColor(hex: border) }
    var cornerRadius: CGFloat { corner == .square ? 0 : CGFloat(radius) }
    /// 선택 칸의 모서리: 창 모서리보다 작게, 같은 곡률로.
    var innerRadius: CGFloat { corner == .square ? 0 : max(3, cornerRadius - CGFloat(padding) / 2 - 2) }

    var isGlass: Bool { backdrop == .glass || backdrop == .clearGlass }

    var material: NSVisualEffectView.Material? {
        switch backdrop {
        case .menu: return .menu
        case .popover: return .popover
        case .hud: return .hudWindow
        case .glass, .clearGlass: return .popover   // Liquid Glass가 없는 macOS에서 대신 쓰는 재질
        case .solid: return nil
        }
    }

    /// 글자 크기 옵션: 어느 테마에나 곱해서 쓴다(글자·여백·모서리를 함께 키운다).
    static let textScales: [(String, String, Double)] = [("normal", "보통", 1), ("large", "크게", 1.25), ("xlarge", "아주 크게", 1.5)]

    func scaled(_ factor: Double) -> CandidateTheme {
        guard factor != 1 else { return self }
        var t = self
        t.fontSize = (fontSize * factor).rounded()
        t.padding = (padding * factor).rounded()
        t.radius = (radius * factor).rounded()
        return t
    }

    /// 지금 설정의 테마에 글자 크기 옵션까지 적용한 것.
    static func current(from defaults: UserDefaults = .standard) -> CandidateTheme {
        let key = defaults.string(forKey: "candidateTextSize") ?? "normal"
        let factor = textScales.first { $0.0 == key }?.2 ?? 1
        return load(from: defaults).forThisMac.scaled(factor)
    }

    // MARK: 저장

    static func load(from defaults: UserDefaults = .standard) -> CandidateTheme {
        let id = presetID(defaults.string(forKey: "candidatePreset"))
        if id == "custom", let data = defaults.data(forKey: "candidateTheme"),
           let theme = try? JSONDecoder().decode(CandidateTheme.self, from: data) {
            return theme
        }
        return (preset(id) ?? preset(defaultPresetID)!).theme
    }
}

extension NSColor {
    /// "#RRGGBB" 또는 "#RRGGBBAA" (sRGB).
    convenience init?(hex: String?) {
        guard var s = hex?.trimmingCharacters(in: .whitespaces), s.hasPrefix("#") else { return nil }
        s.removeFirst()
        guard s.count == 6 || s.count == 8, let v = UInt64(s, radix: 16) else { return nil }
        let r, g, b, a: CGFloat
        if s.count == 6 {
            r = CGFloat((v >> 16) & 0xFF) / 255; g = CGFloat((v >> 8) & 0xFF) / 255; b = CGFloat(v & 0xFF) / 255; a = 1
        } else {
            r = CGFloat((v >> 24) & 0xFF) / 255; g = CGFloat((v >> 16) & 0xFF) / 255
            b = CGFloat((v >> 8) & 0xFF) / 255; a = CGFloat(v & 0xFF) / 255
        }
        self.init(srgbRed: r, green: g, blue: b, alpha: a)
    }

    var hexString: String {
        let c = usingColorSpace(.sRGB) ?? self
        let r = Int(round(c.redComponent * 255)), g = Int(round(c.greenComponent * 255))
        let b = Int(round(c.blueComponent * 255)), a = Int(round(c.alphaComponent * 255))
        return a == 255 ? String(format: "#%02X%02X%02X", r, g, b) : String(format: "#%02X%02X%02X%02X", r, g, b, a)
    }
}
