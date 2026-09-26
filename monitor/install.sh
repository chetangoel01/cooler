#!/bin/sh
set -eu
cd "$(dirname "$0")/.."
app='build/Cooler Curves.app'
mkdir -p "$app/Contents/MacOS"
xcrun swiftc -swift-version 5 -O -parse-as-library monitor/CurveEditor.swift -framework SwiftUI -framework AppKit -o "$app/Contents/MacOS/CoolerCurves"
cat > "$app/Contents/Info.plist" <<'PLIST'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
<key>CFBundleIdentifier</key><string>com.chetangoel.cooler-curves</string>
<key>CFBundleName</key><string>Cooler Curves</string>
<key>CFBundleExecutable</key><string>CoolerCurves</string>
<key>CFBundlePackageType</key><string>APPL</string>
<key>CFBundleShortVersionString</key><string>1.0</string>
<key>NSHighResolutionCapable</key><true/>
</dict></plist>
PLIST
codesign --force --sign - "$app"
destination="$HOME/Library/Application Support/Cooler"
mkdir -p "$destination" "$HOME/Library/Application Support/SwiftBar/Plugins" "$HOME/Library/LaunchAgents"
# Stage a replacement, preserving the executable inode used by any open editor.
stage=$(mktemp -d "$destination/.editor.XXXXXX")
ditto "$app" "$stage/Cooler Curves.app"
if [ -d "$destination/Cooler Curves.app" ]; then
  mv "$destination/Cooler Curves.app" "$stage/previous.app"
fi
if ! mv "$stage/Cooler Curves.app" "$destination/Cooler Curves.app"; then
  if [ -d "$stage/previous.app" ]; then mv "$stage/previous.app" "$destination/Cooler Curves.app"; fi
  exit 1
fi
rm -rf "$stage"
install -m 755 monitor/cooler.5s.py "$HOME/Library/Application Support/SwiftBar/Plugins/cooler.5s.py"
install -m 644 monitor/com.chetangoel.cooler-monitor.plist "$HOME/Library/LaunchAgents/com.chetangoel.cooler-monitor.plist"
echo 'SwiftBar controls and Cooler Curves installed.'
