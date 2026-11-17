#!/bin/bash
# Package build/macos.noindex/HangulSpacing.app (installed as $APP_BUNDLE) as an installer and a zip:
#   build/dist/<PRODUCT_FILE>-<version><suffix>.pkg
#   build/dist/<PRODUCT_FILE>-<version><suffix>-macOS.zip  (pkg + README + LICENSE + notices + uninstall)
# Names, publisher and installer texts come from packaging/product.env.
#   build/dist/SHA256SUMS
# INSTALLER_IDENTITY: "Developer ID Installer: ..." to sign the pkg (optional).
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
. "$ROOT/packaging/product.env"
python3 "$ROOT/tools/versions.py" check
. "$ROOT/packaging/version.env"
APP="$ROOT/build/macos.noindex/HangulSpacing.app"
[ -d "$APP" ] || { echo "build the app first: macos/build.sh" >&2; exit 1; }
[ "$(plutil -extract CharTecVersion raw "$APP/Contents/Info.plist")" = "$ENGINE_VERSION" ] || { echo "stale engine version; rebuild first" >&2; exit 1; }
EXPECTED_VERSION="$VERSION"
VERSION="$(plutil -extract CFBundleShortVersionString raw "$APP/Contents/Info.plist")"
[ "$VERSION" = "$EXPECTED_VERSION" ] || { echo "stale app version; rebuild first" >&2; exit 1; }
[ "$(plutil -extract CFBundleVersion raw "$APP/Contents/Info.plist")" = "$VERSION_BUILD" ] || { echo "stale app build; rebuild first" >&2; exit 1; }
BUNDLE_ID="$(plutil -extract CFBundleIdentifier raw "$APP/Contents/Info.plist")"
COPYRIGHT="$(plutil -extract NSHumanReadableCopyright raw "$APP/Contents/Info.plist")"
STAGE="$ROOT/build/pkg.noindex"
DIST="$ROOT/build/dist"
NAME="$PRODUCT_FILE-$VERSION$RELEASE_FILE_SUFFIX"
VERSION_DISPLAY="$VERSION${RELEASE_LABEL:+ $RELEASE_LABEL}"

# Without the light model the Kiwi helper (arm64 only) is the sole engine.
if [ -f "$APP/Contents/Resources/spacing.hspm" ] && lipo -archs "$APP/Contents/MacOS/HangulSpacing" | grep -q x86_64; then
    HOST_ARCHS="arm64,x86_64"; REQUIRE_ARM64=false
    REQ_KO="macOS 13 Ventura 이상이 필요합니다. Apple Silicon(M1 이후) Mac을 권장하며, Intel Mac에서는 정확도가 낮은 내장 경량 엔진만 사용합니다."
    REQ_EN="Requires macOS 13 Ventura or later. A Mac with Apple silicon (M1 or later) is recommended; Intel Macs use only the built-in light engine, which is less accurate."
    REQ_README="Apple Silicon(M1 이후) Mac 권장. Intel Mac은 내장 경량 엔진만 사용(정확도 낮음)"
else
    HOST_ARCHS="arm64"; REQUIRE_ARM64=true
    REQ_KO="Apple Silicon(M1 이후) Mac과 macOS 13 Ventura 이상이 필요합니다."
    REQ_EN="Requires a Mac with Apple silicon (M1 or later) and macOS 13 Ventura or later."
    REQ_README="Apple Silicon(M1 이후) Mac"
fi

rm -rf "$STAGE" && mkdir -p "$STAGE/root" "$STAGE/resources" "$DIST"
rm -f "$DIST/$NAME.pkg" "$DIST/$NAME-macOS.zip"

render() {
    python3 "$ROOT/packaging/render.py" "$1" "$2" \
        "NAME_KO=$PRODUCT_NAME_KO" "NAME_EN=$PRODUCT_NAME_EN" "PUBLISHER=$PUBLISHER" \
        "COPYRIGHT=$COPYRIGHT" "WEBSITE=$WEBSITE" "WEBSITE_HOST=${WEBSITE#https://}" \
        "SUPPORT_EMAIL=$SUPPORT_EMAIL" "VERSION=$VERSION" "VERSION_DISPLAY=$VERSION_DISPLAY" \
        "BUNDLE_ID=$BUNDLE_ID" "APP_BUNDLE=$APP_BUNDLE" "PKG_NAME=$NAME.pkg" \
        "LEGACY_BUNDLE_ID=$LEGACY_BUNDLE_ID" "LEGACY_APP_BUNDLE=$LEGACY_APP_BUNDLE" \
        "TAGLINE_KO=$TAGLINE_KO" "TAGLINE_EN=$TAGLINE_EN" \
        "ENGINE_KO=$ENGINE_NAME_KO" "ENGINE_EN=$ENGINE_NAME_EN" \
        "TITLE=$PRODUCT_NAME_KO $VERSION_DISPLAY" "HOST_ARCHS=$HOST_ARCHS" "REQUIRE_ARM64=$REQUIRE_ARM64" \
        "REQ_KO=$REQ_KO" "REQ_EN=$REQ_EN" "REQ_README=$REQ_README"
}

echo "== self-test"
"$APP/Contents/MacOS/HangulSpacing" --self-test | tail -1

ditto --norsrc --noextattr "$APP" "$STAGE/root/$APP_BUNDLE"
BUILD="$(plutil -extract CFBundleVersion raw "$APP/Contents/Info.plist")"

# The component package is assembled by hand (cpio + mkbom) rather than with
# pkgbuild, so no extended attributes or AppleDouble files enter the payload.
echo "== pkg"
C="$STAGE/component"
# Expanded-package layout for pkgutil --flatten: Payload is an archive file,
# Scripts is a plain directory that --flatten archives itself.
mkdir -p "$C/Scripts"
render "$ROOT/packaging/macos/scripts/preinstall.in" "$C/Scripts/preinstall"
render "$ROOT/packaging/macos/scripts/postinstall.in" "$C/Scripts/postinstall"
chmod 755 "$C/Scripts/preinstall" "$C/Scripts/postinstall"
(cd "$STAGE/root" && find . | COPYFILE_DISABLE=1 cpio -o --format odc -R 0:80 2>/dev/null | gzip -9 -n) > "$C/Payload"
# Bill of materials owned by root:admin (lsbom lines: path mode uid/gid ...).
mkbom "$STAGE/root" "$STAGE/raw.bom"
lsbom "$STAGE/raw.bom" | awk -F'\t' 'BEGIN{OFS="\t"} {$3="0/80"; print}' > "$STAGE/bom.txt"
mkbom -i "$STAGE/bom.txt" "$C/Bom"
files=$(find "$STAGE/root" | wc -l | tr -d ' ')
kbytes=$(du -sk "$STAGE/root" | cut -f1)
cat > "$C/PackageInfo" <<XML
<?xml version="1.0" encoding="utf-8"?>
<pkg-info overwrite-permissions="true" relocatable="false" identifier="$BUNDLE_ID.pkg" postinstall-action="none" version="$VERSION" format-version="2" install-location="/Library/Input Methods" auth="root">
    <payload numberOfFiles="$files" installKBytes="$kbytes"/>
    <bundle path="./$APP_BUNDLE" id="$BUNDLE_ID" CFBundleShortVersionString="$VERSION" CFBundleVersion="$BUILD"/>
    <bundle-version>
        <bundle id="$BUNDLE_ID"/>
    </bundle-version>
    <upgrade-bundle>
        <bundle id="$BUNDLE_ID"/>
    </upgrade-bundle>
    <update-bundle/>
    <atomic-update-bundle/>
    <strict-identifier>
        <bundle id="$BUNDLE_ID"/>
    </strict-identifier>
    <relocate/>
    <scripts>
        <preinstall file="./preinstall"/>
        <postinstall file="./postinstall"/>
    </scripts>
</pkg-info>
XML
pkgutil --flatten "$C" "$STAGE/component.pkg"
# Verify the installer will find the script, not a nested archive.
pkgutil --expand "$STAGE/component.pkg" "$STAGE/check"
for script in preinstall postinstall; do
    [ -x "$STAGE/check/Scripts/$script" ] || { echo "$script missing from package" >&2; exit 1; }
done
rm -rf "$STAGE/check"
render "$ROOT/packaging/macos/distribution.xml.in" "$STAGE/distribution.xml"
for lang in ko en; do
    L="$STAGE/resources/$lang.lproj"
    mkdir -p "$L"
    for page in welcome conclusion; do
        render "$ROOT/packaging/macos/resources/$lang.lproj/$page.html.in" "$L/$page.html"
    done
    render "$ROOT/packaging/macos/resources/$lang.lproj/Localizable.strings.in" "$L/Localizable.strings"
    cp "$APP/Contents/Resources/Licenses/LICENSE.txt" "$L/license.txt"
done
COPYFILE_DISABLE=1 productbuild --quiet --distribution "$STAGE/distribution.xml" --package-path "$STAGE" \
    --resources "$STAGE/resources" "$STAGE/$NAME.pkg"
if [ -n "${INSTALLER_IDENTITY:-}" ]; then
    productsign --sign "$INSTALLER_IDENTITY" "$STAGE/$NAME.pkg" "$DIST/$NAME.pkg"
else
    mv "$STAGE/$NAME.pkg" "$DIST/$NAME.pkg"
fi

echo "== zip"
Z="$STAGE/zip/$NAME"
mkdir -p "$Z"
cp "$DIST/$NAME.pkg" "$Z/"
cp "$APP/Contents/Resources/uninstall.command" "$Z/"
chmod 755 "$Z/uninstall.command"
render "$ROOT/packaging/macos/README-dist.txt.in" "$Z/README.txt"
cp "$APP/Contents/Resources/Licenses/LICENSE.txt" "$Z/LICENSE.txt"
cp "$ROOT/THIRD_PARTY_NOTICES.md" "$Z/"
ditto -c -k --norsrc --noextattr --keepParent "$Z" "$DIST/$NAME-macOS.zip"

echo "== privacy scan"
PY="${ENGINE_PYTHON:-python3}"
"$PY" "$ROOT/tools/privacy_scan.py" "$APP" "$DIST/$NAME.pkg" "$DIST/$NAME-macOS.zip"
pkgutil --expand-full "$DIST/$NAME.pkg" "$STAGE/expanded" >/dev/null
"$PY" "$ROOT/tools/privacy_scan.py" "$STAGE/expanded"

(cd "$DIST" && shasum -a 256 "$NAME.pkg" "$NAME-macOS.zip" > SHA256SUMS)
# Drop the staged app copies so no second bundle with this ID lingers.
rm -rf "$STAGE"
echo "== done"
ls -lh "$DIST" | tail -n +2
