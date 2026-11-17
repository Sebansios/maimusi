import AppKit

/// Maps AppKit key events to core keys. Letter keys are read by physical
/// position (ANSI virtual key codes) so the Korean layout does not depend on
/// the Latin layout; digits and symbols use the characters the system
/// keyboard layout produced.
enum KeyMapping {
    static let space: UInt16 = 49
    static let backspace: UInt16 = 51
    static let returnKey: UInt16 = 36
    static let keypadEnter: UInt16 = 76
    static let tab: UInt16 = 48
    static let escape: UInt16 = 53
    static let left: UInt16 = 123
    static let right: UInt16 = 124
    static let down: UInt16 = 125
    static let up: UInt16 = 126

    static func isEditSelection(_ event: NSEvent) -> Bool {
        let modifiers = event.modifierFlags.intersection([.shift, .control, .command, .option])
        return event.keyCode == 15 && modifiers == [.control, .shift]
    }

    private static let letters: [UInt16: Character] = [
        0: "a", 1: "s", 2: "d", 3: "f", 4: "h", 5: "g", 6: "z", 7: "x", 8: "c", 9: "v",
        11: "b", 12: "q", 13: "w", 14: "e", 15: "r", 16: "y", 17: "t", 31: "o", 32: "u",
        34: "i", 35: "p", 37: "l", 38: "j", 40: "k", 45: "n", 46: "m",
    ]

    /// (HC_KEY_*, character) for an event.
    static func coreKey(for event: NSEvent) -> (UInt32, UInt32) {
        let other = (UInt32(HC_KEY_OTHER), UInt32(0))
        let flags = event.modifierFlags.intersection(.deviceIndependentFlagsMask)
        if !flags.intersection([.command, .control, .option]).isEmpty {
            return other
        }
        let shift = flags.contains(.shift)
        switch event.keyCode {
        case space: return (UInt32(shift ? HC_KEY_SHIFT_SPACE : HC_KEY_SPACE), 0)
        case backspace: return (UInt32(HC_KEY_BACKSPACE), 0)
        case returnKey, keypadEnter: return (UInt32(HC_KEY_ENTER), 0)
        case tab: return (UInt32(HC_KEY_TAB), 0)
        case escape: return (UInt32(HC_KEY_ESCAPE), 0)
        case left: return (UInt32(shift ? HC_KEY_SHRINK_SEGMENT : HC_KEY_LEFT), 0)
        case right: return (UInt32(shift ? HC_KEY_EXPAND_SEGMENT : HC_KEY_RIGHT), 0)
        case up: return shift ? other : (UInt32(HC_KEY_UP), 0)
        case down: return shift ? other : (UInt32(HC_KEY_DOWN), 0)
        default: break
        }
        if let letter = letters[event.keyCode] {
            let c = shift ? Character(letter.uppercased()) : letter
            return (UInt32(HC_KEY_CHAR), c.unicodeScalars.first!.value)
        }
        guard let chars = event.characters, chars.unicodeScalars.count == 1,
              let scalar = chars.unicodeScalars.first,
              scalar.value >= 0x20, scalar.value != 0x7F, !(0xF700...0xF8FF).contains(scalar.value)
        else { return other }
        return (UInt32(HC_KEY_CHAR), scalar.value)
    }
}
