#!/bin/sh
# Installs or upgrades Cooler's root controller from Cooler.app. The Homebrew cask
# runs it as root after installing the app. Homebrew runs uninstall.sh before every
# upgrade, so this keeps the selected profile and an Apple Automatic choice, and
# runs the brief full-speed hardware check only on a first install.
#   install-daemon.sh [HELPER RESOURCES]   (default: this app bundle)
set -eu
PATH=/usr/bin:/bin:/usr/sbin:/sbin
export PATH
here=$(cd "$(dirname "$0")" && pwd)
helper=${1:-$here/../Helpers/cooler}
resources=${2:-$here}
base='/Library/Application Support/Cooler'
job=system/com.chetangoel.cooler
plist=/Library/LaunchDaemons/com.chetangoel.cooler.plist
[ "$(/usr/bin/id -u)" = 0 ] || { echo 'Run this as root.' >&2; exit 1; }
if [ "$(/usr/sbin/sysctl -n hw.model)" != MacBookPro18,4 ]; then
  echo 'Cooler controls fans only on MacBookPro18,4; the controller was not installed.' >&2
  exit 0
fi
if /usr/bin/pgrep -x 'Macs Fan Control|Stats|TG Pro|smcFanControl|macfan' >/dev/null; then
  echo 'Quit other fan controllers, then reinstall Cooler.' >&2
  exit 1
fi
first=0
[ -f "$base/config.json" ] || first=1
# Apple Automatic persists as a disabled launchd job; an upgrade keeps it off.
off=0
if /bin/launchctl print-disabled system | /usr/bin/grep -Eq '"com\.chetangoel\.cooler" => (disabled|true)'; then off=1; fi
if /bin/launchctl print "$job" >/dev/null 2>&1; then /bin/launchctl bootout "$job"; fi
if [ -x "$base/cooler" ]; then "$base/cooler" auto; fi
/usr/bin/install -d -o root -g wheel -m 755 "$base"
/usr/bin/install -o root -g wheel -m 755 "$helper" "$base/cooler"
/usr/bin/install -o root -g wheel -m 755 "$resources/uninstall.sh" "$base/uninstall.sh"
if [ "$first" = 1 ]; then
  /usr/bin/install -o root -g wheel -m 644 "$resources/config.json" "$base/config.json"
fi
/usr/bin/install -o root -g wheel -m 644 "$resources/com.chetangoel.cooler.plist" "$plist"
# Files copied out of the downloaded app keep its quarantine flag, and launchd
# refuses to load a quarantined daemon plist.
for installed in "$plist" "$base/cooler" "$base/uninstall.sh" "$base/config.json"; do
  /usr/bin/xattr -d com.apple.quarantine "$installed" 2>/dev/null || true
done
"$base/cooler" auto
if [ "$first" = 1 ]; then "$base/cooler" hardware-check >/dev/null; fi
if [ "$off" = 1 ]; then
  echo 'Cooler is installed and stays off because Apple Automatic is selected.'
  exit 0
fi
/bin/launchctl enable "$job"
/bin/launchctl bootstrap system "$plist"
echo 'Cooler is running.'
