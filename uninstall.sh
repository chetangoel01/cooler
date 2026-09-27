#!/bin/sh
# Stops Cooler, returns both fans to Apple automatic control, and removes the
# controller. Homebrew also runs this before every cask upgrade, so the selected
# profile (config.json) stays for the next install; `brew uninstall --zap cooler`
# removes it as well.
set -eu
PATH=/usr/bin:/bin:/usr/sbin:/sbin
export PATH
[ "$(/usr/bin/id -u)" = 0 ] || { echo 'Run with administrator privileges.' >&2; exit 1; }
base='/Library/Application Support/Cooler'
job=system/com.chetangoel.cooler
if /bin/launchctl print "$job" >/dev/null 2>&1; then /bin/launchctl bootout "$job"; fi
if [ -x "$base/cooler" ]; then "$base/cooler" auto; fi
/bin/rm -f /Library/LaunchDaemons/com.chetangoel.cooler.plist "$base/cooler" "$base/status.json" "$base/uninstall.sh"
echo 'Cooler removed; fans restored to Apple automatic control. Your profile is kept for a reinstall.'
