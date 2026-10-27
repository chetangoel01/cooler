#!/bin/sh
# Switches Cooler's profile. The menu runs it through `sudo -n`; the sudoers rule
# installed next to it (sudoers) lets admin users run it without a password.
#   apply-profile automatic          stop Cooler and keep it off (Apple automatic)
#   apply-profile curve < EDIT.json  install baselineRPM, curve and palmCurve from stdin
# Only those three fields are taken from the caller; sensors, model and recovery
# settings always come from the installed profile, and the controller validates
# the result before control is interrupted.
set -eu
PATH=/usr/bin:/bin:/usr/sbin:/sbin
export PATH
umask 077
base='/Library/Application Support/Cooler'
job=system/com.chetangoel.cooler
plist=/Library/LaunchDaemons/com.chetangoel.cooler.plist
case "${1:-}" in automatic|curve) ;; *) echo 'Usage: apply-profile automatic | curve < EDIT.json' >&2; exit 2 ;; esac
[ -x "$base/cooler" ] && [ -f "$plist" ] || { echo 'Cooler is not installed.' >&2; exit 1; }
if /usr/bin/pgrep -x 'Macs Fan Control|Stats|TG Pro|smcFanControl|macfan' >/dev/null; then
  echo 'Quit the other fan controller before switching.' >&2; exit 1
else
  result=$?
  [ "$result" = 1 ] || { echo 'Cannot check for competing controllers.' >&2; exit 1; }
fi
stage=$(/usr/bin/mktemp -d "$base/.profile.XXXXXX")
changing=0
cleanup() {
  result=$?
  trap - EXIT
  if [ "$result" != 0 ] && [ "$changing" = 1 ]; then
    /bin/launchctl disable "$job" || true
    if /bin/launchctl print "$job" >/dev/null 2>&1; then /bin/launchctl bootout "$job" || true; fi
    "$base/cooler" auto || true
    if [ -f "$stage/previous.json" ]; then /bin/mv -f "$stage/previous.json" "$base/config.json"; fi
    echo 'Change failed. Previous profile restored; Apple automatic recovery was attempted. Check the menu status.' >&2
  fi
  /bin/rm -rf "$stage"
  exit "$result"
}
trap cleanup EXIT
if [ "$1" = curve ]; then
  /usr/bin/head -c 65536 > "$stage/edit.json"
  /bin/cp "$base/config.json" "$stage/next.json"
  for key in baselineRPM curve palmCurve; do
    # json works for the curves; plutil cannot emit a bare number as json, so the baseline uses raw.
    value=$(/usr/bin/plutil -extract "$key" json -o - "$stage/edit.json" 2>/dev/null ||
            /usr/bin/plutil -extract "$key" raw -o - "$stage/edit.json")
    /usr/bin/plutil -replace "$key" -json "$value" "$stage/next.json"
  done
  "$base/cooler" check "$stage/next.json" >/dev/null
  /bin/cp -p "$base/config.json" "$stage/previous.json"
  /usr/sbin/chown root:wheel "$stage/next.json"
  /bin/chmod 644 "$stage/next.json"
fi
changing=1
/bin/launchctl disable "$job"
if /bin/launchctl print "$job" >/dev/null 2>&1; then /bin/launchctl bootout "$job"; fi
"$base/cooler" auto
if [ "$1" = curve ]; then
  /bin/mv -f "$stage/next.json" "$base/config.json"
  /bin/launchctl enable "$job"
  /bin/launchctl bootstrap system "$plist"
fi
