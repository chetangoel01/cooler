#!/bin/sh
set -eu
cd "$(dirname "$0")"
[ "$(id -u)" = 0 ] || { echo 'Run this installer with administrator privileges.' >&2; exit 1; }
[ "$(sysctl -n hw.model)" = MacBookPro18,4 ] || { echo 'Unsupported Mac model.' >&2; exit 1; }
if /usr/bin/pgrep -x 'Macs Fan Control|Stats|TG Pro|smcFanControl|macfan' >/dev/null; then
  echo 'Quit other fan controllers before installing Cooler.' >&2
  exit 1
fi
./build/cooler check config.json >/dev/null
/usr/bin/codesign --verify --strict build/cooler
plist=/Library/LaunchDaemons/com.chetangoel.cooler.plist
base='/Library/Application Support/Cooler'
if /bin/launchctl print system/com.chetangoel.cooler >/dev/null 2>&1; then
  /bin/launchctl bootout system/com.chetangoel.cooler
fi
if [ -x "$base/cooler" ]; then "$base/cooler" auto; fi
/usr/bin/install -d -o root -g wheel -m 755 "$base"
/usr/bin/install -o root -g wheel -m 755 build/cooler "$base/cooler"
/usr/bin/install -o root -g wheel -m 644 config.json "$base/config.json"
/usr/bin/install -o root -g wheel -m 644 com.chetangoel.cooler.plist "$plist"
/usr/bin/install -o root -g wheel -m 755 uninstall.sh "$base/uninstall.sh"
"$base/cooler" auto
/bin/launchctl enable system/com.chetangoel.cooler
/bin/launchctl bootstrap system "$plist"
echo 'Cooler installed. Status: /Library/Application Support/Cooler/status.json'
