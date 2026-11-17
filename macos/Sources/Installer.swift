import Carbon
import Foundation

/// Input-source registration used by the installer scripts.
///   --register   make macOS aware of this bundle (no logout needed)
///   --enable     also add it to the user's input menu
///   --unregister disable and remove it from the input menu
enum Installer {
    private static var sourceID: String { (Bundle.main.bundleIdentifier ?? "") + ".dubeolsik" }

    private static func sources() -> [TISInputSource] {
        let filter = [kTISPropertyBundleID as String: Bundle.main.bundleIdentifier ?? ""] as CFDictionary
        guard let list = TISCreateInputSourceList(filter, true)?.takeRetainedValue() as? [TISInputSource] else { return [] }
        return list
    }

    static func run(_ args: [String]) -> Int32 {
        if args.contains("--register") || args.contains("--enable") {
            let status = TISRegisterInputSource(Bundle.main.bundleURL as CFURL)
            if status != noErr {
                print("register failed: \(status)")
                return 1
            }
        }
        if args.contains("--enable") {
            for s in sources() {
                let id = TISGetInputSourceProperty(s, kTISPropertyInputSourceID)
                    .map { Unmanaged<CFString>.fromOpaque($0).takeUnretainedValue() as String }
                if id == sourceID {
                    TISEnableInputSource(s)
                }
            }
        }
        if args.contains("--unregister") {
            for s in sources() {
                TISDisableInputSource(s)
            }
        }
        return 0
    }
}
