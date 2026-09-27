#!/bin/sh
# Development install of the SwiftBar plugin and its login agent from this source.
# The curve editor is Cooler.app: install it with the Homebrew cask, or copy the
# app built by scripts/release.sh --no-notarize into /Applications.
set -eu
cd "$(dirname "$0")/.."
mkdir -p "$HOME/Library/Application Support/SwiftBar/Plugins" "$HOME/Library/LaunchAgents"
install -m 755 monitor/cooler.5s.py "$HOME/Library/Application Support/SwiftBar/Plugins/cooler.5s.py"
install -m 644 monitor/com.chetangoel.cooler-monitor.plist "$HOME/Library/LaunchAgents/com.chetangoel.cooler-monitor.plist"
echo 'SwiftBar plugin installed.'
