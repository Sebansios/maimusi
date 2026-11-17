import AppKit

/// Shared by the IMK controller and the standalone NSTextView harness. The
/// target closures bridge their different protocol method names, not behavior.
final class MarkedTextState {
    struct Target {
        let markedRange: () -> NSRange
        let insert: (String, NSRange) -> Void
        let mark: (NSAttributedString, NSRange, NSRange) -> Void
    }

    private(set) var showingMarkedText = false
    private var converting = false
    private var importedAnchor: Int?
    private var emptyAnchor: Int?
    var isActive: Bool { showingMarkedText || converting }

    func apply(commit: String, preedit: NSAttributedString, converting: Bool,
               initialReplacement: NSRange? = nil, target: Target) {
        let notFound = NSRange(location: NSNotFound, length: NSNotFound)
        if let initialReplacement { importedAnchor = initialReplacement.location }
        func emptyReplacement() -> NSRange {
            emptyAnchor.map { NSRange(location: $0, length: 0) } ?? notFound
        }
        if !commit.isEmpty {
            target.insert(commit, emptyReplacement())
            showingMarkedText = false
            emptyAnchor = nil
        }
        if preedit.length > 0 {
            target.mark(preedit, NSRange(location: preedit.length, length: 0),
                        initialReplacement ?? emptyReplacement())
            showingMarkedText = true
            emptyAnchor = nil
        } else if showingMarkedText {
            // An empty marked string may end the client's marked range. Save
            // its current document anchor before clearing so Escape can restore
            // a manually edited conversion without replacing surrounding text.
            if converting {
                let range = target.markedRange()
                emptyAnchor = range.location == NSNotFound ? importedAnchor : range.location
            }
            target.mark(NSAttributedString(string: ""), NSRange(location: 0, length: 0), notFound)
            showingMarkedText = false
        }
        self.converting = converting
        if !converting {
            importedAnchor = nil
            emptyAnchor = nil
        }
    }
}
