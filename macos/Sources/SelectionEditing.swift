import Foundation
import InputMethodKit

/// Read one exact document selection. Never expand an app's replacement range.
enum SelectionEditing {
    struct Selection {
        let text: String
        let range: NSRange
    }

    static func read(from client: IMKTextInput) -> Selection? {
        read(range: client.selectedRange()) { range, actual in
            client.string(from: range, actualRange: &actual)
        }
    }

    // The closure also lets the native harness exercise unsupported/partial
    // client responses without registering an input method or accessing a document.
    static func read(range: NSRange, string: (NSRange, inout NSRange) -> String?) -> Selection? {
        guard range.location != NSNotFound, range.length > 0, range.length <= 2000,
              range.location >= 0, range.location <= Int.max - range.length else { return nil }
        var actual = NSRange(location: NSNotFound, length: 0)
        guard let text = string(range, &actual), actual == range,
              (text as NSString).length == range.length,
              !text.unicodeScalars.contains(where: { $0.value == 0 }) else { return nil }
        return Selection(text: text, range: range)
    }
}
