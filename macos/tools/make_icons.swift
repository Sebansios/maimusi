// Draws the input-menu template icon and the app icon.
// Usage: swift make_icons.swift <output-dir>
//
// 매무시 표지: 한복 옷깃(V, 오른깃이 왼깃 위로 여며짐)과 그 아래 띄어쓰기 부호(⎵).
// 도형은 macos/tools/mark_geometry.py와 같은 좌표(120 단위 viewBox, y 아래로)를 쓴다.
import AppKit

let out = URL(fileURLWithPath: CommandLine.arguments.count > 1 ? CommandLine.arguments[1] : ".")
try? FileManager.default.createDirectory(at: out, withIntermediateDirectories: true)

func image(size: CGFloat, height: CGFloat? = nil, draw: (CGContext) -> Void) -> NSBitmapImageRep {
    let rep = NSBitmapImageRep(bitmapDataPlanes: nil, pixelsWide: Int(size), pixelsHigh: Int(height ?? size),
                               bitsPerSample: 8, samplesPerPixel: 4, hasAlpha: true, isPlanar: false,
                               colorSpaceName: .deviceRGB, bytesPerRow: 0, bitsPerPixel: 0)!
    NSGraphicsContext.saveGraphicsState()
    let g = NSGraphicsContext(bitmapImageRep: rep)!
    NSGraphicsContext.current = g
    draw(g.cgContext)
    NSGraphicsContext.restoreGraphicsState()
    return rep
}

// MARK: geometry

typealias P = CGPoint
func quad(_ a: P, _ c: P, _ b: P, _ t: CGFloat) -> P {
    P(x: (1 - t) * (1 - t) * a.x + 2 * (1 - t) * t * c.x + t * t * b.x,
      y: (1 - t) * (1 - t) * a.y + 2 * (1 - t) * t * c.y + t * t * b.y)
}
func quadD(_ a: P, _ c: P, _ b: P, _ t: CGFloat) -> P {
    P(x: 2 * (1 - t) * (c.x - a.x) + 2 * t * (b.x - c.x),
      y: 2 * (1 - t) * (c.y - a.y) + 2 * t * (b.y - c.y))
}
/// 옷깃 곡선을 옆으로 d만큼 옮긴 선(동정은 깃을 따라 나란히 달린다).
func offsetPath(_ q: (P, P, P), _ d: CGFloat, _ t0: CGFloat = 0, _ t1: CGFloat = 1, side: CGFloat = 1) -> CGPath {
    let path = CGMutablePath()
    for k in 0...32 {
        let t = t0 + (t1 - t0) * CGFloat(k) / 32
        let p = quad(q.0, q.1, q.2, t), v = quadD(q.0, q.1, q.2, t)
        let l = hypot(v.x, v.y)
        let pt = P(x: p.x - v.y / l * side * d, y: p.y + v.x / l * side * d)
        k == 0 ? path.move(to: pt) : path.addLine(to: pt)
    }
    return path
}
let leftArm = (P(x: 36, y: 10), P(x: 44, y: 42), P(x: 60, y: 58))   // 왼깃(아래)
let rightArm = (P(x: 84, y: 10), P(x: 77, y: 44), P(x: 48, y: 67))  // 오른깃(위)
let band: CGFloat = 7, trim: CGFloat = 2.2, trimGap: CGFloat = 7.4
func spaceMark() -> CGPath {
    let p = CGMutablePath()
    p.move(to: P(x: 32, y: 81))
    p.addQuadCurve(to: P(x: 41, y: 94), control: P(x: 32, y: 94))
    p.addLine(to: P(x: 79, y: 94))
    p.addQuadCurve(to: P(x: 88, y: 81), control: P(x: 88, y: 94))
    return p
}

// MARK: menu icon — 입력 메뉴의 기본 배지(한·ABC·拼音)와 같은 22×16 pt, 모서리 3.5 pt.
// 꽉 찬 둥근 사각형에 표지를 투명하게 뚫은 템플릿 이미지라 메뉴 막대 밝기에 따라 색이 바뀐다.

let badgeW: CGFloat = 22, badgeH: CGFloat = 16, badgeR: CGFloat = 3.5

func menuIcon(scale: CGFloat) -> NSBitmapImageRep {
    image(size: badgeW * scale, height: badgeH * scale) { c in
        c.translateBy(x: 0, y: badgeH * scale)
        c.scaleBy(x: scale, y: -scale)       // pt 단위, y 아래로
        c.addPath(CGPath(roundedRect: CGRect(x: 0, y: 0, width: badgeW, height: badgeH),
                         cornerWidth: badgeR, cornerHeight: badgeR, transform: nil))
        c.setFillColor(NSColor.black.cgColor)
        c.fillPath()
        c.setLineCap(.round)
        c.setLineJoin(.round)
        // 표지(120 단위, 세로 16–94)를 배지 가운데에 둔다.
        c.translateBy(x: badgeW / 2, y: badgeH / 2)
        c.scaleBy(x: 0.135, y: 0.135)
        c.translateBy(x: -60, y: -55)
        let w: CGFloat = 8.6                // 약 1.2 pt, 기본 배지 글자의 획 굵기
        func knock(_ path: CGPath) {
            c.setBlendMode(.clear)
            c.addPath(path); c.setLineWidth(w); c.strokePath()
            c.setBlendMode(.normal)
        }
        c.saveGState()
        c.clip(to: CGRect(x: -40, y: 16, width: 200, height: 200))  // 목둘레 위는 자른다
        knock(offsetPath(leftArm, 0))
        // 오른깃이 왼깃 위로 여며진 것이 보이도록 겹치는 곳에 바탕을 한 겹 되살린다.
        c.addPath(offsetPath(rightArm, 0)); c.setLineWidth(w + 7)
        c.setStrokeColor(NSColor.black.cgColor); c.strokePath()
        knock(offsetPath(rightArm, 0))
        c.restoreGState()
        knock(spaceMark())
    }
}

// 이름 끝의 Template은 macOS가 템플릿 이미지로 다루는 규칙이다.
let menu = NSImage(size: NSSize(width: badgeW, height: badgeH))
for scale: CGFloat in [1, 2] {
    let rep = menuIcon(scale: scale)
    rep.size = NSSize(width: badgeW, height: badgeH)
    menu.addRepresentation(rep)
}
menu.isTemplate = true
try menu.tiffRepresentation(using: .lzw, factor: 1)!.write(to: out.appendingPathComponent("MenuIconTemplate.tiff"))

/// 초타원 |x/a|^n + |y/b|^n = 1 (n = 5). macOS 앱 아이콘의 연속 곡률 모서리에 가깝다.
func squircle(_ r: CGRect, n: CGFloat = 5) -> CGPath {
    let path = CGMutablePath()
    let a = r.width / 2, b = r.height / 2
    for k in 0..<720 {
        let t = CGFloat(k) / 720 * 2 * .pi
        let ct = cos(t), st = sin(t)
        let x = r.midX + a * (ct < 0 ? -1 : 1) * pow(abs(ct), 2 / n)
        let y = r.midY + b * (st < 0 ? -1 : 1) * pow(abs(st), 2 / n)
        k == 0 ? path.move(to: CGPoint(x: x, y: y)) : path.addLine(to: CGPoint(x: x, y: y))
    }
    path.closeSubpath()
    return path
}

// MARK: app icon — 옻칠 바탕에 청자색 옷깃, 흰 동정, 띄어쓰기 부호

let lacquer = NSColor(srgbRed: 0x11 / 255.0, green: 0x13 / 255.0, blue: 0x12 / 255.0, alpha: 1)
let celadon = NSColor(srgbRed: 0x9D / 255.0, green: 0xBF / 255.0, blue: 0xB2 / 255.0, alpha: 1)
let hanji = NSColor(srgbRed: 0xE9 / 255.0, green: 0xE4 / 255.0, blue: 0xD8 / 255.0, alpha: 1)

let app = image(size: 1024) { c in
    // macOS 앱 아이콘 격자: 824 pt squircle(초타원, 모서리 곡률이 이어지는 꼴), 바깥 100 pt 여백.
    c.addPath(squircle(CGRect(x: 100, y: 100, width: 824, height: 824)))
    c.setFillColor(lacquer.cgColor)
    c.fillPath()
    c.translateBy(x: 0, y: 1024)
    c.scaleBy(x: 1, y: -1)
    c.translateBy(x: 512, y: 512)
    c.scaleBy(x: 6.4, y: 6.4)
    c.translateBy(x: -60, y: -55)
    c.setLineCap(.round)
    c.setLineJoin(.round)
    func stroke(_ path: CGPath, _ width: CGFloat, _ color: NSColor) {
        c.addPath(path); c.setLineWidth(width); c.setStrokeColor(color.cgColor); c.strokePath()
    }
    c.saveGState()
    c.clip(to: CGRect(x: -40, y: 20, width: 200, height: 200))
    stroke(offsetPath(leftArm, 0), band, celadon)
    stroke(offsetPath(leftArm, trimGap, 0, 0.62, side: -1), trim, hanji)
    stroke(offsetPath(rightArm, 0), band + 6, lacquer)             // 여밈 틈
    stroke(offsetPath(rightArm, 0), band, celadon)
    stroke(offsetPath(rightArm, trimGap, 0, 0.78, side: 1), trim, hanji)
    c.restoreGState()
    stroke(spaceMark(), band, celadon)
}
try app.representation(using: .png, properties: [:])!.write(to: out.appendingPathComponent("AppIcon-1024.png"))
print("icons written to \(out.path)")
