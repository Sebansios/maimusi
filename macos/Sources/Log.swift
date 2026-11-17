import Foundation
import os

/// Lifecycle diagnostics in the unified log (`log stream --predicate
/// 'subsystem BEGINSWITH "com.sebansios"'`). Never log typed text.
enum Log {
    static let lifecycle = Logger(subsystem: Bundle.main.bundleIdentifier ?? "HangulSpacing", category: "lifecycle")
}
