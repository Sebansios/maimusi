#!/bin/bash
# Build the macOS input method bundle: build/macos.noindex/HangulSpacing.app
# Output folders end in ".noindex" so Spotlight does not register build copies
# with LaunchServices; a second registered copy with the same bundle ID makes
# the system input-method launcher fail (imklaunchagent status -50).
#
# Environment (all optional):
#   BUNDLE_ID      bundle identifier; must contain ".inputmethod."
#   SIGN_IDENTITY  codesign identity; "-" (default) signs ad hoc
#   ENGINE_PYTHON  Python with kiwipiepy, pint, regex, korean-lunar-calendar
#                  and PyInstaller; builds the Kiwi helper. Unset: light only.
#   MODEL          light spacing model (.hspm); default build/models/nikl-morph.hspm.
#                  "none" builds without it (Kiwi only; Apple Silicon only).
#   ARCHS          "arm64 x86_64" (default) or a subset
#   REUSE_ENGINE   1: reuse build/engine.noindex/dist/HangulEngine.app if present
#   FONTS          candidate-window fonts (Noto Sans/Serif CJK KR subsets, SIL OFL 1.1);
#                  default build/fonts from macos/tools/prepare_fonts.py. "none": system font.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
# shellcheck source=../packaging/product.env
. "$ROOT/packaging/product.env"
python3 "$ROOT/tools/versions.py" check
. "$ROOT/packaging/version.env"
OUT="$ROOT/build/macos.noindex"
APP="$OUT/HangulSpacing.app"
SIGN_IDENTITY="${SIGN_IDENTITY:--}"
MODEL="${MODEL:-$ROOT/build/models/nikl-morph.hspm}"
ARCHS="${ARCHS:-arm64 x86_64}"
MIN_MACOS=13.0
BUILD="$VERSION_BUILD"
COPYRIGHT="${COPYRIGHT:-Copyright © $COPYRIGHT_YEAR $PUBLISHER. All rights reserved.}"

case "$BUNDLE_ID" in *.inputmethod.*) ;; *) echo "BUNDLE_ID must contain .inputmethod." >&2; exit 1;; esac
if [ "$MODEL" != none ]; then
    [ -f "$MODEL" ] || { echo "missing light model: $MODEL (see models/README.md)" >&2; exit 1; }
fi

mkdir -p "$OUT/obj"
rm -rf "$APP"

# Paths in panic/assert messages must not reveal the build machine.
export RUSTFLAGS="--remap-path-prefix=$ROOT=/src --remap-path-prefix=$HOME=/build"
export MACOSX_DEPLOYMENT_TARGET=$MIN_MACOS

binaries=()
for arch in $ARCHS; do
    case $arch in
        arm64) rtarget=aarch64-apple-darwin ;;
        x86_64) rtarget=x86_64-apple-darwin ;;
        *) echo "unknown arch $arch" >&2; exit 1 ;;
    esac
    echo "== core ($arch)"
    cargo build --quiet --release --offline --lib --manifest-path "$ROOT/core/Cargo.toml" --target $rtarget
    echo "== input method ($arch)"
    xcrun swiftc -O -wmo -swift-version 5 -target $arch-apple-macos$MIN_MACOS \
        -import-objc-header "$ROOT/core/include/hangul_core.h" \
        -file-prefix-map "$ROOT=." -file-prefix-map "$HOME=~" \
        "$ROOT"/macos/Sources/*.swift \
        -L "$ROOT/core/target/$rtarget/release" -lhangul_core \
        -framework Cocoa -framework InputMethodKit -framework SwiftUI \
        -Xlinker -dead_strip \
        -o "$OUT/obj/HangulSpacing-$arch"
    binaries+=("$OUT/obj/HangulSpacing-$arch")
done

echo "== bundle"
mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources"
lipo -create "${binaries[@]}" -output "$APP/Contents/MacOS/HangulSpacing"
strip -x "$APP/Contents/MacOS/HangulSpacing"

subst() {
    sed -e "s|@BUNDLE_ID@|$BUNDLE_ID|g" -e "s|@VERSION@|$VERSION|g" \
        -e "s|@BUILD@|$BUILD|g" -e "s|@COPYRIGHT@|$COPYRIGHT|g" \
        -e "s|@NAME_KO@|$PRODUCT_NAME_KO|g" -e "s|@NAME_EN@|$PRODUCT_NAME_EN|g" \
        -e "s|@ENGINE_KO@|$ENGINE_NAME_KO|g" -e "s|@ENGINE_EN@|$ENGINE_NAME_EN|g" \
        -e "s|@WEBSITE@|$WEBSITE|g" -e "s|@RELEASE_LABEL@|$RELEASE_LABEL|g" -e "s|@SUPPORT_EMAIL@|$SUPPORT_EMAIL|g" \
        -e "s|@UPDATE_URL@|$UPDATE_URL_MACOS|g" "$1"
}
subst "$ROOT/macos/Resources/Info.plist.in" > "$APP/Contents/Info.plist"
plutil -insert CharTecVersion -string "$ENGINE_VERSION" "$APP/Contents/Info.plist"
# 업데이트 정보 서명을 확인할 공개키(docs/UPDATES.md). 없으면 업데이트를 받을 수 없으니 멈춘다.
UPDATE_KEYS="$(python3 -c 'import json,sys; k=json.load(open(sys.argv[1]))["keys"]; assert k; print(json.dumps(k))' "$ROOT/packaging/update-keys.json")"
plutil -insert HSUpdateKeys -json "$UPDATE_KEYS" "$APP/Contents/Info.plist"
plutil -lint -s "$APP/Contents/Info.plist"
for lang in ko en; do
    mkdir -p "$APP/Contents/Resources/$lang.lproj"
    subst "$ROOT/macos/Resources/$lang.lproj/InfoPlist.strings.in" > "$APP/Contents/Resources/$lang.lproj/InfoPlist.strings"
done

ICONS="$OUT/icons"
xcrun swift "$ROOT/macos/tools/make_icons.swift" "$ICONS" >/dev/null
cp "$ICONS/MenuIconTemplate.tiff" "$APP/Contents/Resources/"
ICONSET="$OUT/obj/AppIcon.iconset"
rm -rf "$ICONSET" && mkdir -p "$ICONSET"
for s in 16 32 128 256 512; do
    sips -z $s $s "$ICONS/AppIcon-1024.png" --out "$ICONSET/icon_${s}x${s}.png" >/dev/null
    sips -z $((s * 2)) $((s * 2)) "$ICONS/AppIcon-1024.png" --out "$ICONSET/icon_${s}x${s}@2x.png" >/dev/null
done
iconutil -c icns "$ICONSET" -o "$APP/Contents/Resources/AppIcon.icns"

[ "$MODEL" = none ] || cp "$MODEL" "$APP/Contents/Resources/spacing.hspm"
python3 "$ROOT/packaging/render.py" "$ROOT/packaging/macos/uninstall.command.in" "$APP/Contents/Resources/uninstall.command" \
    "NAME_EN=$PRODUCT_NAME_EN" "APP_BUNDLE=$APP_BUNDLE" "LEGACY_APP_BUNDLE=$LEGACY_APP_BUNDLE" \
    "BUNDLE_ID=$BUNDLE_ID" "LEGACY_BUNDLE_ID=$LEGACY_BUNDLE_ID"
chmod 755 "$APP/Contents/Resources/uninstall.command"
mkdir -p "$APP/Contents/Resources/Licenses"
cp "$ROOT/THIRD_PARTY_NOTICES.md" "$APP/Contents/Resources/Licenses/"
mkdir -p "$APP/Contents/Resources/Licenses/unicode-segmentation"
cp "$ROOT/core/vendor/unicode-segmentation-1.12.0"/LICENSE-* "$APP/Contents/Resources/Licenses/unicode-segmentation/"
python3 "$ROOT/packaging/render.py" "$ROOT/packaging/LICENSE.txt.in" "$APP/Contents/Resources/Licenses/LICENSE.txt" \
    "NAME_KO=$PRODUCT_NAME_KO" "NAME_EN=$PRODUCT_NAME_EN" "PUBLISHER=$PUBLISHER" "COPYRIGHT=$COPYRIGHT" \
    "WEBSITE=$WEBSITE" "SUPPORT_EMAIL=$SUPPORT_EMAIL"

FONTS="${FONTS:-$ROOT/build/fonts}"
if [ "$FONTS" != none ]; then
    for f in NotoSansCJKkr-Regular.otf NotoSerifCJKkr-Regular.otf fonts.json; do
        [ -f "$FONTS/$f" ] || { echo "font input missing: $FONTS/$f (run macos/tools/prepare_fonts.py, or FONTS=none)" >&2; exit 1; }
    done
    mkdir -p "$APP/Contents/Resources/Fonts" "$APP/Contents/Resources/Licenses/fonts"
    cp "$FONTS/NotoSansCJKkr-Regular.otf" "$FONTS/NotoSerifCJKkr-Regular.otf" "$FONTS/fonts.json" "$APP/Contents/Resources/Fonts/"
    python3 - "$FONTS/fonts.json" "$ROOT/tools/license-texts/OFL-1.1.txt" "$APP/Contents/Resources/Licenses/fonts/NotoCJK-OFL.txt" <<'PY'
import json, sys
fonts = json.load(open(sys.argv[1], encoding="utf-8"))
lines = [f"{f['family']} ({f['file']}, {f['version'].split(';')[0]}; subset: {f['subset']})\n{f['copyright']}" for f in fonts]
open(sys.argv[3], "w", encoding="utf-8").write("\n\n".join(lines) + "\n\n" + open(sys.argv[2], encoding="utf-8").read())
PY
    echo "   fonts $(shasum -a 256 "$FONTS"/*.otf | cut -c1-16 | tr '\n' ' ')"
fi

if [ -n "${ENGINE_PYTHON:-}" ]; then
    if [ "${REUSE_ENGINE:-0}" = 1 ] && [ -d "$ROOT/build/engine.noindex/dist/HangulEngine.app" ]; then
        [ "$(plutil -extract CFBundleShortVersionString raw "$ROOT/build/engine.noindex/dist/HangulEngine.app/Contents/Info.plist")" = "$ENGINE_VERSION" ] || { echo "stale engine; rebuild without REUSE_ENGINE" >&2; exit 1; }
        [ "$(plutil -extract CFBundleVersion raw "$ROOT/build/engine.noindex/dist/HangulEngine.app/Contents/Info.plist")" = "$VERSION_BUILD" ] || { echo "stale engine build; rebuild without REUSE_ENGINE" >&2; exit 1; }
        echo "== engine (reused)"
    else
        BUNDLE_ID="$BUNDLE_ID" "$ROOT/macos/build_engine.sh"
    fi
    mkdir -p "$APP/Contents/Helpers"
    ditto "$ROOT/build/engine.noindex/dist/HangulEngine.app" "$APP/Contents/Helpers/HangulEngine.app"
    cp -R "$ROOT/build/engine.noindex/licenses" "$APP/Contents/Resources/Licenses/engine"
else
    echo "   (ENGINE_PYTHON unset: bundle has the light engine only)"
fi

echo "== sign ($([ "$SIGN_IDENTITY" = "-" ] && echo ad-hoc || echo identity))"
sign_args=(--force --sign "$SIGN_IDENTITY" --timestamp=none)
if [ "$SIGN_IDENTITY" != "-" ]; then
    sign_args=(--force --sign "$SIGN_IDENTITY" --timestamp --options runtime)
fi
ENGINE="$APP/Contents/Helpers/HangulEngine.app"
if [ -d "$ENGINE" ]; then
    # Inside-out: every Mach-O in the helper, then the helper bundle itself.
    find "$ENGINE/Contents" -type f ! -path "*/Contents/MacOS/HangulEngine" -print0 |
        while IFS= read -r -d '' f; do
            if file -b "$f" | grep -q Mach-O; then codesign "${sign_args[@]}" "$f"; fi
        done
    codesign "${sign_args[@]}" --entitlements "$ROOT/macos/Resources/engine.entitlements" "$ENGINE"
fi
codesign "${sign_args[@]}" "$APP"
codesign --verify --deep --strict "$APP"
# Only the installed copy may be known to LaunchServices under this bundle ID.
LSREGISTER=/System/Library/Frameworks/CoreServices.framework/Versions/A/Frameworks/LaunchServices.framework/Versions/A/Support/lsregister
"$LSREGISTER" -u "$APP" 2>/dev/null || true
"$LSREGISTER" -u "$ROOT/build/engine.noindex/dist/HangulEngine.app" 2>/dev/null || true

echo "== built $APP ($VERSION, $BUILD)"
du -sh "$APP" | awk '{print "   size " $1}'
