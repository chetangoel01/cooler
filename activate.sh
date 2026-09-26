#!/bin/sh
set -eu
cd "$(dirname "$0")"
echo 'Installing Cooler and checking fan control and recovery (about one minute).'
./install.sh
/usr/bin/python3 tests/live.py
echo 'Cooler is active. You can close this Terminal window.'
