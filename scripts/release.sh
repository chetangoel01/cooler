#!/bin/bash
# Builds, signs (Developer ID), notarizes, staples, packages, and publishes Cooler
# as a GitHub release, then updates the cask in chetangoel01/homebrew-tap.
# Prereqs: Developer ID cloud signing for team P48VDW72LU, a notarytool keychain
# profile for that team (NOTARY_PROFILE, default "meeting-recorder"), xcodegen,
# create-dmg, and an authenticated gh CLI. Bump CFBundleShortVersionString in
# app/Info.plist and commit first; the version tag must not already exist.
#   --no-publish   stop after the notarized DMG
#   --no-notarize  build and sign locally only; nothing is uploaded or published
set -euo pipefail

cd "$(dirname "$0")/.."

PUBLISH=1
NOTARIZE=1
for arg in "$@"; do
    case "$arg" in
        --no-publish) PUBLISH=0 ;;
        --no-notarize) NOTARIZE=0; PUBLISH=0 ;;
        *) echo "usage: $0 [--no-publish] [--no-notarize]" >&2; exit 2 ;;
    esac
done

TEAM_ID="P48VDW72LU"
PROFILE="${NOTARY_PROFILE:-meeting-recorder}"
BUILD_DIR="build/release"
ARCHIVE="$BUILD_DIR/Cooler.xcarchive"
EXPORT_DIR="$BUILD_DIR/export"
VERSION=$(plutil -extract CFBundleShortVersionString raw app/Info.plist)
TAG="v$VERSION"
DMG="$BUILD_DIR/Cooler-$VERSION.dmg"

if [[ $PUBLISH == 1 ]]; then
    echo "==> Pre-flight for $TAG"
    gh auth status >/dev/null
    if git rev-parse "$TAG" >/dev/null 2>&1; then
        echo "error: tag $TAG already exists; bump CFBundleShortVersionString first" >&2
        exit 1
    fi
    if [[ -n "$(git status --porcelain)" ]]; then
        echo "error: working tree is not clean; commit before releasing" >&2
        exit 1
    fi
fi

rm -rf "$BUILD_DIR"
mkdir -p "$BUILD_DIR"

echo "==> Generating the Xcode project"
xcodegen generate --quiet

echo "==> Archiving"
xcodebuild archive \
  -project Cooler.xcodeproj \
  -scheme Cooler \
  -configuration Release \
  -destination 'generic/platform=macOS' \
  -archivePath "$ARCHIVE" \
  -allowProvisioningUpdates \
  -quiet

echo "==> Exporting with Developer ID signing"
cat > "$BUILD_DIR/exportOptions.plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>method</key>
    <string>developer-id</string>
    <key>teamID</key>
    <string>$TEAM_ID</string>
    <key>signingStyle</key>
    <string>automatic</string>
    <key>destination</key>
    <string>export</string>
</dict>
</plist>
PLIST

xcodebuild -exportArchive \
  -archivePath "$ARCHIVE" \
  -exportOptionsPlist "$BUILD_DIR/exportOptions.plist" \
  -exportPath "$EXPORT_DIR" \
  -allowProvisioningUpdates

APP="$EXPORT_DIR/Cooler.app"

echo "==> Verifying signatures"
codesign --verify --deep --strict "$APP"
for code in "$APP" "$APP/Contents/Helpers/cooler"; do
    details=$(codesign -dvv "$code" 2>&1)
    grep -q "Authority=Developer ID Application" <<<"$details" || { echo "error: $code is not Developer ID signed" >&2; exit 1; }
    grep -q "flags=.*runtime" <<<"$details" || { echo "error: $code lacks the hardened runtime" >&2; exit 1; }
done

if [[ $NOTARIZE == 1 ]]; then
    echo "==> Notarizing the app"
    ZIP="$BUILD_DIR/Cooler-notarize.zip"
    ditto -c -k --keepParent "$APP" "$ZIP"
    xcrun notarytool submit "$ZIP" --keychain-profile "$PROFILE" --wait
    xcrun stapler staple "$APP"
    spctl -a -vv --type execute "$APP"
fi

echo "==> Building the DMG"
DMG_ROOT="$BUILD_DIR/dmg-root"
mkdir -p "$DMG_ROOT"
cp -R "$APP" "$DMG_ROOT/"
create-dmg \
    --volname "Cooler" \
    --window-size 540 320 \
    --icon-size 110 \
    --icon "Cooler.app" 140 150 \
    --app-drop-link 400 150 \
    --hide-extension "Cooler.app" \
    --no-internet-enable \
    "$DMG" "$DMG_ROOT"

if [[ $NOTARIZE == 1 ]]; then
    # Notarize and staple the DMG itself; an unstapled DMG is rejected even when its app is fine.
    echo "==> Notarizing the DMG"
    xcrun notarytool submit "$DMG" --keychain-profile "$PROFILE" --wait
    xcrun stapler staple "$DMG"
    MOUNT="$BUILD_DIR/dmg-verify"
    hdiutil attach "$DMG" -nobrowse -readonly -mountpoint "$MOUNT" -quiet
    spctl -a -vv --type execute "$MOUNT/Cooler.app"
    xcrun stapler validate "$MOUNT/Cooler.app"
    hdiutil detach "$MOUNT" -quiet
fi

if [[ $PUBLISH == 1 ]]; then
    echo "==> Publishing $TAG"
    git tag "$TAG"
    git push origin HEAD:main "$TAG"
    gh release create "$TAG" \
        "$DMG#Cooler $VERSION (signed + notarized DMG)" \
        --title "Cooler $VERSION" \
        --generate-notes

    echo "==> Updating the Homebrew tap"
    TAP_DIR="$BUILD_DIR/homebrew-tap"
    SHA256=$(shasum -a 256 "$DMG" | cut -d' ' -f1)
    git clone -q "git@github.com:chetangoel01/homebrew-tap.git" "$TAP_DIR"
    sed -e "s/^  version \".*\"/  version \"$VERSION\"/" -e "s/^  sha256 \".*\"/  sha256 \"$SHA256\"/" \
        packaging/cooler.rb > "$TAP_DIR/Casks/cooler.rb"
    git -C "$TAP_DIR" add Casks/cooler.rb
    if ! grep -q '^## Cooler' "$TAP_DIR/README.md"; then
        cat >> "$TAP_DIR/README.md" <<'README'

## Cooler

```bash
brew install chetangoel01/tap/cooler
```

Fan curves and menu bar temperatures for the 16-inch M1 Max MacBook Pro.
Upgrade with `brew upgrade cooler`. Source and releases:
https://github.com/chetangoel01/cooler
README
        git -C "$TAP_DIR" add README.md
    fi
    git -C "$TAP_DIR" commit -qm "cooler $VERSION"
    git -C "$TAP_DIR" push -q origin main
fi

echo "==> Done"
echo "App:  $APP"
echo "DMG:  $DMG"
if [[ $PUBLISH == 1 ]]; then
    gh release view "$TAG" --json url -q '.url'
fi
