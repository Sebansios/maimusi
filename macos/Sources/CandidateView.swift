import AppKit

/// 후보 창에 보이는 것: 후보, 출처, 선택 위치, 쓸 수 있는 경계 편집.
struct CandidateContent {
    var items: [String]
    var notes: [String]
    var selected: Int
    var segmentActions: UInt32 = 0
    /// 이 문장에 기억한 띄어쓰기가 쓰였다.
    var remembered = false

    static let pageSize = 9


    /// 설정 미리보기와 시안 그림에 쓰는 예.
    static let sample = CandidateContent(
        items: ["學校", "학교", "🏫", "學敎", "hakgyo", "hakkyo"],
        notes: ["배울 학, 학교 교", "", "이모지", "배울 학, 가르침 교", "로마자 2000", "매큔-라이샤워"],
        selected: 0,
        segmentActions: UInt32(HC_SEGMENT_SHRINK | HC_SEGMENT_EXPAND))
}

/// 모서리 경로. squircle은 연속 곡률 모서리(Apple 앱 아이콘·컨트롤과 같은 곡선)의 3차 베지어 근사.
enum CandidateShape {
    static func path(_ rect: CGRect, radius: CGFloat, corner: CandidateTheme.Corner) -> CGPath {
        switch corner {
        case .square:
            return CGPath(rect: rect, transform: nil)
        case .rounded:
            let r = min(radius, rect.width / 2, rect.height / 2)
            return CGPath(roundedRect: rect, cornerWidth: r, cornerHeight: r, transform: nil)
        case .squircle:
            return continuous(rect, radius: radius)
        }
    }

    private static let k: [(CGFloat, CGFloat)] = [
        (1.08849323, 0), (0.86840689, 0), (0.63149399, 0.07491100),
        (0.37282392, 0.16905899), (0.16905899, 0.37282392), (0.07491100, 0.63149399),
        (0, 0.86840689), (0, 1.08849323), (0, 1.52866483),
    ]

    static func continuous(_ rect: CGRect, radius: CGFloat) -> CGPath {
        let r = max(0, min(radius, min(rect.width, rect.height) / (2 * 1.52866483)))
        let p = CGMutablePath()
        // 꼭짓점과, 그 꼭짓점으로 들어오는 변(u)·나가는 변(v)의 방향.
        let corners: [(CGPoint, CGVector, CGVector)] = [
            (CGPoint(x: rect.maxX, y: rect.minY), CGVector(dx: 1, dy: 0), CGVector(dx: 0, dy: 1)),
            (CGPoint(x: rect.maxX, y: rect.maxY), CGVector(dx: 0, dy: 1), CGVector(dx: -1, dy: 0)),
            (CGPoint(x: rect.minX, y: rect.maxY), CGVector(dx: -1, dy: 0), CGVector(dx: 0, dy: -1)),
            (CGPoint(x: rect.minX, y: rect.minY), CGVector(dx: 0, dy: -1), CGVector(dx: 1, dy: 0)),
        ]
        func pt(_ c: CGPoint, _ u: CGVector, _ v: CGVector, _ a: CGFloat, _ b: CGFloat) -> CGPoint {
            CGPoint(x: c.x - a * r * u.dx + b * r * v.dx, y: c.y - a * r * u.dy + b * r * v.dy)
        }
        for (i, (c, u, v)) in corners.enumerated() {
            let start = pt(c, u, v, 1.52866483, 0)
            i == 0 ? p.move(to: start) : p.addLine(to: start)
            for j in stride(from: 0, to: k.count, by: 3) {
                p.addCurve(to: pt(c, u, v, k[j + 2].0, k[j + 2].1),
                           control1: pt(c, u, v, k[j].0, k[j].1),
                           control2: pt(c, u, v, k[j + 1].0, k[j + 1].1))
            }
        }
        p.closeSubpath()
        return p
    }

    static func maskImage(_ size: NSSize, radius: CGFloat, corner: CandidateTheme.Corner) -> NSImage {
        NSImage(size: size, flipped: false) { rect in
            let ctx = NSGraphicsContext.current!.cgContext
            ctx.addPath(path(rect, radius: radius, corner: corner))
            ctx.setFillColor(NSColor.black.cgColor)
            ctx.fillPath()
            return true
        }
    }
}

/// 단색 배경을 테마 모양대로 그린다.
final class CandidateBackdropView: NSView {
    var theme = CandidateTheme()
    override var isFlipped: Bool { true }
    override func draw(_ dirtyRect: NSRect) {
        guard let ctx = NSGraphicsContext.current?.cgContext else { return }
        let rect = bounds.insetBy(dx: 0.5, dy: 0.5)
        let shape = CandidateShape.path(rect, radius: theme.cornerRadius, corner: theme.corner)
        ctx.addPath(shape)
        ctx.setFillColor(theme.solidBackground.cgColor)
        ctx.fillPath()
        if let border = theme.borderColor {
            ctx.addPath(shape)
            ctx.setStrokeColor(border.cgColor)
            ctx.setLineWidth(1)
            ctx.strokePath()
        }
    }
}

/// 후보 한 칸. 선택 표시(채움·밑줄·막대)를 직접 그린다.
final class CandidateRowView: NSView {
    var theme = CandidateTheme()
    var isSelected = false
    var onClick: (() -> Void)?
    override var isFlipped: Bool { true }

    override func draw(_ dirtyRect: NSRect) {
        guard isSelected, let ctx = NSGraphicsContext.current?.cgContext else { return }
        let color = theme.selectionFill.cgColor
        switch theme.selection {
        case .fill:
            ctx.addPath(CandidateShape.path(bounds, radius: theme.innerRadius, corner: theme.corner))
            ctx.setFillColor(color)
            ctx.fillPath()
        case .underline:
            ctx.setFillColor(color)
            ctx.fill(CGRect(x: 8, y: bounds.maxY - 3, width: bounds.width - 16, height: 1.5))
        case .bar:
            let h = bounds.height - 12
            ctx.addPath(CGPath(roundedRect: CGRect(x: 1, y: 6, width: 3, height: max(4, h)),
                               cornerWidth: 1.5, cornerHeight: 1.5, transform: nil))
            ctx.setFillColor(color)
            ctx.fillPath()
        }
    }

    override func mouseDown(with event: NSEvent) { onClick?() }
}

/// 후보 창의 내용 전체. 실제 창·설정 미리보기·시안 그림이 같은 뷰를 쓴다.
final class CandidateView: NSView {
    let theme: CandidateTheme
    private let content: CandidateContent
    var onSelect: ((Int) -> Void)?
    var onSegmentAction: ((UInt32) -> Void)?
    /// 시안 그림처럼 화면 밖에서 그릴 때의 모드(어둡게면 true). 반투명 재질 대신 비슷한 단색을 쓴다.
    private let offscreenDark: Bool?

    override var isFlipped: Bool { true }

    init(theme: CandidateTheme, content: CandidateContent, offscreenDark: Bool? = nil) {
        self.theme = theme
        self.content = content
        self.offscreenDark = offscreenDark
        super.init(frame: .zero)
        if let dark = offscreenDark {
            appearance = NSAppearance(named: dark ? .darkAqua : .aqua)
        }
        build()
    }

    required init?(coder: NSCoder) { fatalError() }

    private func label(_ s: String, font: NSFont, color: NSColor) -> NSTextField {
        let f = NSTextField(labelWithString: s)
        f.font = font
        f.textColor = color
        f.lineBreakMode = .byClipping
        f.setContentHuggingPriority(.required, for: .horizontal)
        return f
    }

    private func build() {
        let t = theme
        let page = max(0, content.selected) / CandidateContent.pageSize
        let start = page * CandidateContent.pageSize
        let end = min(content.items.count, start + CandidateContent.pageSize)
        let pages = (content.items.count + CandidateContent.pageSize - 1) / CandidateContent.pageSize
        let font = t.font()
        let small = t.font(secondary: true)
        let rowPad = CGFloat(max(3, t.fontSize * 0.3))

        let list = NSStackView()
        list.orientation = t.layout == .vertical ? .vertical : .horizontal
        list.alignment = t.layout == .vertical ? .leading : .centerY
        list.spacing = t.layout == .vertical ? 1 : 2
        for absolute in start..<end {
            let i = absolute - start
            let selected = absolute == content.selected
            let row = CandidateRowView()
            row.theme = t
            row.isSelected = selected
            row.onClick = { [weak self] in self?.onSelect?(absolute) }
            let fg = selected ? t.selectionTextColor : t.textColor
            let dim = selected ? t.selectionTextColor.withAlphaComponent(0.72) : t.secondaryColor
            let line = NSStackView()
            line.orientation = .horizontal
            line.alignment = .firstBaseline
            line.spacing = CGFloat(t.fontSize * 0.5)
            if t.showNumbers {
                let n = label("\(i + 1)", font: .monospacedDigitSystemFont(ofSize: small.pointSize, weight: .regular), color: dim)
                line.addArrangedSubview(n)
            }
            line.addArrangedSubview(label(content.items[absolute], font: font, color: fg))
            let note = absolute < content.notes.count ? content.notes[absolute] : ""
            if t.showNotes && t.layout == .vertical && !note.isEmpty {
                let spacer = NSView()
                spacer.setContentHuggingPriority(.defaultLow, for: .horizontal)
                line.addArrangedSubview(spacer)
                line.addArrangedSubview(label(note, font: small, color: dim))
            }
            line.translatesAutoresizingMaskIntoConstraints = false
            row.addSubview(line)
            let side = CGFloat(t.selection == .bar ? 12 : 9)
            NSLayoutConstraint.activate([
                line.leadingAnchor.constraint(equalTo: row.leadingAnchor, constant: side),
                line.trailingAnchor.constraint(equalTo: row.trailingAnchor, constant: -9),
                line.topAnchor.constraint(equalTo: row.topAnchor, constant: rowPad),
                line.bottomAnchor.constraint(equalTo: row.bottomAnchor, constant: -rowPad),
            ])
            row.setAccessibilityRole(.button)
            row.setAccessibilityLabel(note.isEmpty ? content.items[absolute] : "\(content.items[absolute]), \(note)")
            list.addArrangedSubview(row)
            if t.layout == .vertical {
                row.widthAnchor.constraint(equalTo: list.widthAnchor, constant: 0).isActive = true
            }
        }

        let outer = NSStackView()
        outer.orientation = .vertical
        outer.alignment = .leading
        outer.spacing = 4
        outer.edgeInsets = NSEdgeInsets(top: CGFloat(t.padding), left: CGFloat(t.padding),
                                        bottom: CGFloat(t.padding), right: CGFloat(t.padding))
        outer.addArrangedSubview(list)
        if t.layout == .vertical {
            list.widthAnchor.constraint(equalTo: outer.widthAnchor, constant: -2 * CGFloat(t.padding)).isActive = true
            list.widthAnchor.constraint(greaterThanOrEqualToConstant: CGFloat(t.fontSize) * 11).isActive = true
        }

        // 아래 줄: 쪽 번호, 경계 편집, 안내.
        let footer = NSStackView()
        footer.orientation = .horizontal
        footer.spacing = 10
        footer.edgeInsets = NSEdgeInsets(top: 2, left: 9, bottom: 0, right: 9)
        if t.showTools {
            // 경계 조정은 키 두 개로 한다. 합치기는 늘리기를 거듭하면 된다(다음 어절을 다 가져오면 합쳐진다).
            let keyFont = NSFont.systemFont(ofSize: max(9, small.pointSize - 1))
            let actions: [(String, String, Int, Int)] = [
                ("⇧←", "줄이기", HC_KEY_SHRINK_SEGMENT, HC_SEGMENT_SHRINK),
                ("⇧→", "늘리기", HC_KEY_EXPAND_SEGMENT, HC_SEGMENT_EXPAND),
            ]
            for (key, title, code, bit) in actions {
                let enabled = content.segmentActions & UInt32(bit) != 0
                let color = enabled ? t.secondaryColor : t.secondaryColor.withAlphaComponent(0.35)
                let item = SegmentActionView(spacing: 4)
                item.addArrangedSubview(KeycapView(key, font: keyFont, color: color))
                item.addArrangedSubview(label(title, font: small, color: color))
                item.setAccessibilityElement(true)
                item.setAccessibilityRole(.button)
                item.setAccessibilityLabel("\(title), Shift \(key.hasSuffix("←") ? "왼쪽" : "오른쪽") 화살표")
                item.setAccessibilityEnabled(enabled)
                if enabled { item.onClick = { [weak self] in self?.onSegmentAction?(UInt32(code)) } }
                footer.addArrangedSubview(item)
            }
        }
        if t.showHint {
            footer.addArrangedSubview(label("← → 어절 · Enter 확정 · Esc 취소", font: small, color: t.secondaryColor))
        }
        // 남는 폭은 끝으로 보내 항목끼리 붙어 있게 한다.
        let spacer = NSView()
        spacer.setContentHuggingPriority(.defaultLow, for: .horizontal)
        if !footer.arrangedSubviews.isEmpty || pages > 1 { footer.addArrangedSubview(spacer) }
        if content.remembered {
            footer.addArrangedSubview(label("기억한 띄어쓰기", font: small, color: t.secondaryColor))
        }
        if pages > 1 {
            footer.addArrangedSubview(label("\(page + 1)/\(pages)", font: .monospacedDigitSystemFont(ofSize: small.pointSize, weight: .regular), color: t.secondaryColor))
        }
        if !footer.arrangedSubviews.isEmpty {
            outer.addArrangedSubview(footer)
            if t.layout == .vertical {
                footer.widthAnchor.constraint(equalTo: list.widthAnchor).isActive = true
            }
        }

        // 배경.
        let back: NSView
        if t.isGlass, offscreenDark == nil, #available(macOS 26.0, *) {
            // Liquid Glass: 내용은 contentView로만 넣는다(유리 효과 안에 놓이도록).
            let glass = NSGlassEffectView()
            glass.style = t.backdrop == .clearGlass ? .clear : .regular
            glass.cornerRadius = t.cornerRadius
            if let tint = NSColor(hex: t.background) { glass.tintColor = tint }
            let holder = NSView()
            glass.contentView = holder
            holder.translatesAutoresizingMaskIntoConstraints = false
            outer.translatesAutoresizingMaskIntoConstraints = false
            holder.addSubview(outer)
            glass.translatesAutoresizingMaskIntoConstraints = false
            addSubview(glass)
            NSLayoutConstraint.activate([
                glass.leadingAnchor.constraint(equalTo: leadingAnchor),
                glass.trailingAnchor.constraint(equalTo: trailingAnchor),
                glass.topAnchor.constraint(equalTo: topAnchor),
                glass.bottomAnchor.constraint(equalTo: bottomAnchor),
                holder.leadingAnchor.constraint(equalTo: glass.leadingAnchor),
                holder.trailingAnchor.constraint(equalTo: glass.trailingAnchor),
                holder.topAnchor.constraint(equalTo: glass.topAnchor),
                holder.bottomAnchor.constraint(equalTo: glass.bottomAnchor),
                outer.leadingAnchor.constraint(equalTo: holder.leadingAnchor),
                outer.trailingAnchor.constraint(equalTo: holder.trailingAnchor),
                outer.topAnchor.constraint(equalTo: holder.topAnchor),
                outer.bottomAnchor.constraint(equalTo: holder.bottomAnchor),
            ])
            backdrop = glass
            return
        }
        if let material = t.material, offscreenDark == nil {
            let effect = NSVisualEffectView()
            effect.material = material
            effect.state = .active
            effect.blendingMode = .behindWindow
            if t.backdrop == .hud { effect.appearance = NSAppearance(named: .vibrantDark) }
            back = effect
        } else {
            let solid = CandidateBackdropView()
            var shown = t
            if t.material != nil {
                // 화면 밖 그림: 반투명 재질을 비슷한 단색으로.
                if t.isGlass {
                    // 화면 밖 그림의 유리 흉내: 밝은 반투명 바탕과 가는 빛 테두리.
                    shown.background = offscreenDark == true ? "#3A3A3CC7" : "#FFFFFFC2"
                    shown.border = offscreenDark == true ? "#FFFFFF33" : "#FFFFFFE6"
                } else {
                    shown.background = t.backdrop == .hud ? "#1E1E1EE6" : (offscreenDark == true ? "#2B2B2BF2" : "#F4F4F4F2")
                    shown.border = nil
                }
            }
            solid.theme = shown
            back = solid
        }
        back.translatesAutoresizingMaskIntoConstraints = false
        outer.translatesAutoresizingMaskIntoConstraints = false
        addSubview(back)
        back.addSubview(outer)
        NSLayoutConstraint.activate([
            back.leadingAnchor.constraint(equalTo: leadingAnchor),
            back.trailingAnchor.constraint(equalTo: trailingAnchor),
            back.topAnchor.constraint(equalTo: topAnchor),
            back.bottomAnchor.constraint(equalTo: bottomAnchor),
            outer.leadingAnchor.constraint(equalTo: back.leadingAnchor),
            outer.trailingAnchor.constraint(equalTo: back.trailingAnchor),
            outer.topAnchor.constraint(equalTo: back.topAnchor),
            outer.bottomAnchor.constraint(equalTo: back.bottomAnchor),
        ])
        backdrop = back
    }

    private var backdrop: NSView?

    /// 크기가 정해진 뒤 반투명 재질의 모양을 맞춘다.
    override func layout() {
        super.layout()
        if let effect = backdrop as? NSVisualEffectView {
            effect.maskImage = CandidateShape.maskImage(bounds.size, radius: theme.cornerRadius, corner: theme.corner)
        }
    }

}


/// 아래 줄의 경계 조정 항목(키캡과 이름). 눌러도 된다.
final class SegmentActionView: NSStackView {
    var onClick: (() -> Void)?

    convenience init(spacing: CGFloat) {
        self.init(frame: .zero)
        orientation = .horizontal
        alignment = .centerY
        self.spacing = spacing
    }

    override func mouseDown(with event: NSEvent) { onClick?() }
}

/// 작은 키캡: 둥근 테두리 안의 키 기호.
final class KeycapView: NSView {
    private let text: NSAttributedString
    private let color: NSColor

    init(_ key: String, font: NSFont, color: NSColor) {
        self.color = color
        text = NSAttributedString(string: key, attributes: [.font: font, .foregroundColor: color])
        super.init(frame: .zero)
        setContentHuggingPriority(.required, for: .horizontal)
        setContentCompressionResistancePriority(.required, for: .horizontal)
    }

    required init?(coder: NSCoder) { fatalError() }

    override var intrinsicContentSize: NSSize {
        let s = text.size()
        return NSSize(width: ceil(s.width) + 8, height: ceil(s.height) + 2)
    }

    override func draw(_ dirtyRect: NSRect) {
        let path = NSBezierPath(roundedRect: bounds.insetBy(dx: 0.5, dy: 0.5), xRadius: 4, yRadius: 4)
        color.withAlphaComponent(0.45).setStroke()
        path.lineWidth = 0.75
        path.stroke()
        let s = text.size()
        text.draw(at: NSPoint(x: (bounds.width - s.width) / 2, y: (bounds.height - s.height) / 2))
    }
}
