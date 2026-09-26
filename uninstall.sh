#!/bin/sh
set -eu
[ "$(id -u)" = 0 ] || { echo 'Run with administrator privileges.' >&2; exit 1; }
base='/Library/Application Support/Cooler'
if /bin/launchctl print system/com.chetangoel.cooler >/dev/null 2>&1; then
  /bin/launchctl bootout system/com.chetangoel.cooler
fi
"$base/cooler" auto
/bin/rm -f /Library/LaunchDaemons/com.chetangoel.cooler.plist
/bin/rm -f "$base/cooler" "$base/config.json" "$base/status.json" "$base/uninstall.sh"
/bin/rmdir "$base"
echo 'Cooler removed; fans restored to Apple automatic control. Source and logs preserved.'
