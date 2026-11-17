import AppKit

/// Product identity read from the bundle (set at build time from
/// packaging/product.env), for windows and the About section.
enum AppInfo {
    private static let info = Bundle.main.localizedInfoDictionary ?? [:]
    private static let base = Bundle.main.infoDictionary ?? [:]

    static var name: String {
        info["CFBundleDisplayName"] as? String ?? base["CFBundleDisplayName"] as? String ?? "매무시"
    }
    static var version: String {
        let short = base["CFBundleShortVersionString"] as? String ?? "?"
        let label = base["HSReleaseLabel"] as? String ?? ""
        return label.isEmpty ? short : "\(short) \(label)"
    }
    /// Product name of the spacing engine (Kiwi-based).
    static var engineName: String { base["HSEngineName"] as? String ?? "Kiwi" }
    static var build: String { base["CFBundleVersion"] as? String ?? "?" }
    static var copyright: String { base["NSHumanReadableCopyright"] as? String ?? "" }
    static var website: URL? { (base["HSWebsite"] as? String).flatMap(URL.init(string:)) }
    static var supportEmail: String { base["HSSupportEmail"] as? String ?? "" }

    static func openLicenses() {
        guard let url = Bundle.main.resourceURL?.appendingPathComponent("Licenses") else { return }
        NSWorkspace.shared.open(url)
    }
}
