#!/bin/bash
# Build and run a standalone AppKit test; never launch/register an IMK bundle.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
OUT="$ROOT/build/segment-editing"
mkdir -p "$OUT"
cargo build --offline --manifest-path "$ROOT/core/Cargo.toml" --lib
xcrun swiftc -swift-version 5 -import-objc-header "$ROOT/core/include/hangul_core.h" \
    "$ROOT/macos/Sources/KeyMapping.swift" "$ROOT/macos/Sources/CandidatePanel.swift" \
    "$ROOT/macos/Sources/SelectionEditing.swift" "$ROOT/macos/Sources/MarkedTextState.swift" \
    "$ROOT/macos/Sources/SegmentEditingSelfTest.swift" \
    "$ROOT/macos/Tests/SegmentEditingHarness.swift" \
    -L "$ROOT/core/target/debug" -lhangul_core \
    -framework Cocoa -framework InputMethodKit \
    -o "$OUT/SegmentEditingHarness"
"$OUT/SegmentEditingHarness" "$OUT"
