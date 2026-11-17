#!/bin/bash
# Freeze the Kiwi engine service with PyInstaller: build/engine.noindex/dist/HangulEngine.app
# (an app bundle, so code and data are laid out the way codesign expects).
# Requires ENGINE_PYTHON (see engine/requirements.lock).
# REFINER: optional directory holding boundary-refiner.npz to bundle; only a
# model cleared for redistribution (see docs/LICENSING.md).
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PY="${ENGINE_PYTHON:?set ENGINE_PYTHON to a Python with the engine requirements}"
WORK="$ROOT/build/engine.noindex"
rm -rf "$WORK/dist" "$WORK/work"
ENGINE_APP="$WORK/dist/HangulEngine.app"
# The helper must not look like an input method to the system: no ".inputmethod.".
. "$ROOT/packaging/product.env"
python3 "$ROOT/tools/versions.py" check
. "$ROOT/packaging/version.env"
ENGINE_ID="${BUNDLE_ID/.inputmethod./.}.engine"
mkdir -p "$WORK"

echo "== engine tests"
PYTHONPATH="$ROOT/engine" PYTHONDONTWRITEBYTECODE=1 "$PY" -m pytest -q -p no:cacheprovider "$ROOT/engine/tests" | tail -1

echo "== freeze engine"
PYTHONHASHSEED=0 PYTHONDONTWRITEBYTECODE=1 "$PY" -m PyInstaller --noconfirm --clean --log-level WARN \
    --onedir --windowed --name HangulEngine --target-architecture arm64 \
    --osx-bundle-identifier "$ENGINE_ID" \
    --paths "$ROOT/engine" --distpath "$WORK/dist" --workpath "$WORK/work" --specpath "$WORK" \
    --add-data "$ROOT/engine/hangul_ime/converter_data:hangul_ime/converter_data" \
    --add-data "$ROOT/engine/hangul_ime/spacing_data:hangul_ime/spacing_data" \
    ${REFINER:+--add-data "$REFINER:hangul_ime/models"} \
    --collect-data kiwipiepy_model --collect-data pint \
    --hidden-import kiwipiepy_model --hidden-import korean_lunar_calendar \
    --exclude-module tkinter --exclude-module pytest --exclude-module PySide6 \
    --exclude-module IPython --exclude-module matplotlib --exclude-module pint.testsuite \
    "$ROOT/engine/hangul_engine_main.py"

# Background helper: no Dock icon, never activated.
plutil -replace CFBundleShortVersionString -string "$ENGINE_VERSION" "$ENGINE_APP/Contents/Info.plist"
plutil -replace CFBundleVersion -string "$VERSION_BUILD" "$ENGINE_APP/Contents/Info.plist"
plutil -replace LSUIElement -bool YES "$ENGINE_APP/Contents/Info.plist"
rm -rf "$WORK/dist/HangulEngine"

echo "== engine smoke test"
reply="$(printf '%s\n' '{"id":1,"op":"space","text":"아버지가방에들어가신다"}' | "$WORK/dist/HangulEngine.app/Contents/MacOS/HangulEngine" 2>/dev/null | tail -1)"
echo "   $reply"
case "$reply" in *'아버지가 방에 들어가신다'*) ;; *) echo "engine smoke test failed" >&2; exit 1;; esac

echo "== third-party licences"
rm -rf "$WORK/licenses" && mkdir -p "$WORK/licenses"
"$PY" "$ROOT/tools/collect_licenses.py" "$WORK/licenses"
cp "$ROOT/engine/hangul_ime/spacing_data/LICENSE-open-korean-text.txt" "$WORK/licenses/"
