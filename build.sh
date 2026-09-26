#!/bin/sh
set -eu
cd "$(dirname "$0")"
mkdir -p build
xcrun swiftc -swift-version 5 -O Sources/SMC.swift Sources/Control.swift Sources/main.swift -framework IOKit -o build/cooler
codesign --force --sign - build/cooler
