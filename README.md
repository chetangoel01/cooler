# Cooler

A personal background fan controller for **MacBookPro18,4 / M1 Max**. It keeps a low airflow floor and raises both fans according to the hottest configured CPU, GPU, or palm-rest reading. It starts when macOS boots and runs without a window or menu-bar item.

Source: `/Users/chetangoel/CodexProjects/cooler`. No external runtime or network access. Swift and IOKit; build requires Xcode Command Line Tools.

An optional **SwiftBar monitor** now provides a menu-bar temperature, a dropdown with readings, and a local curve viewer. The monitor uses the existing Homebrew Python 3 installation; the controller itself still has no external runtime dependencies.

## Current deployment status

Deployed September 26, 2026 and verified running with the custom curve. All **11 on-device checks passed**, including physical fan response, normal termination, forced crash, stalled controller, watchdog loss, restoration to automatic control, service restart, and installation permissions. The 15 replay checks and four process/signal checks also passed. The running process matches its fresh status, and the installed binary matches the verified build. Macs Fan Control automatic startup is disabled.

Evidence: [live report](artifacts/live-report.json) and [deployment verification](artifacts/deployment-verification.json). Actual sleep/wake, a full reboot, and everyday temperature/noise comfort remain unverified; boot startup is configured through launchd.

## Cooling policy

`config.json` is the source configuration. Installation copies it into `/Library/Application Support/Cooler/config.json`, owned by root. This is a starting comfort profile, not a promise that the laptop can maintain any particular temperature.

| CPU or GPU temperature | Left fan | Right fan |
|---|---:|---:|
| 45°C or below | 1,800 RPM | 1,800 RPM |
| 55°C | 2,198 RPM | 2,244 RPM |
| 65°C | 2,994 RPM | 3,132 RPM |
| 75°C | 4,386 RPM | 4,687 RPM |
| 85°C or above | 5,779 RPM | 6,241 RPM |

The palm-rest curve independently requests 0% of the range above the baseline at 30°C, 20% at 33°C, 50% at 36°C, and 100% at 40°C. The highest request wins. Values between points are interpolated. Both fans are read every two seconds; increases are immediate and decreases are limited to 40 RPM per second. A gap longer than ten seconds restores automatic mode and requires three healthy samples before resuming.

CPU/GPU sensor mapping follows Stats. `Ts0P`/`Ts1P` are community-identified palm-rest sensors; they do **not** measure the entire underside. These labels and readings should be checked against comfort in everyday use. See [source attribution](THIRD_PARTY_NOTICES.md).

See the [comparison with recorded Apple automatic targets](artifacts/curve-comparison.png) and [data and limits](artifacts/curve-comparison-notes.md). This compares our configured curve with six saved automatic-mode snapshots, not a recovered Apple curve or a controlled temperature/noise benchmark.

## Install, inspect, change, remove

Quit Macs Fan Control first and turn off its automatic startup. Keep it installed if desired, but do not run two fan controllers together. Cooler detects Macs Fan Control, Stats, TG Pro, smcFanControl, and macfan by process name, relinquishes control, and waits while any runs. This list cannot detect every possible tool.

```sh
cd /Users/chetangoel/CodexProjects/cooler
./build.sh
python3 tests/e2e.py
python3 tests/lifecycle.py
./build/cooler check config.json
sudo ./activate.sh
```

Inspect the current mode, temperatures, requested RPM, and timestamp:

```sh
cat '/Library/Application Support/Cooler/status.json'
'/Library/Application Support/Cooler/cooler' probe
launchctl print system/com.chetangoel.cooler
tail /var/log/cooler.log
```

Status includes the PID that wrote it and updates every two seconds. A fresh file alone is not proof that a newly restarted process is ready. Logs record mode transitions and failures, not continuous readings. After a macOS update, check that the status timestamp is fresh and the mode is `custom`; this machine currently runs macOS 27.0 build 26A428, outside Macs Fan Control's published support list at implementation time.

To tune the profile, edit the source `config.json`, run `check` and the replay tests, then rerun `sudo ./install.sh`. Do not edit the installed file in place; the running service reads its configuration at startup.

Remove the service and return both fans to Apple automatic control:

```sh
sudo '/Library/Application Support/Cooler/uninstall.sh'
```

Removal preserves this repository, test reports, and `/var/log/cooler.log`. Re-enable Macs Fan Control startup yourself if you want to return to it.

## Menu-bar monitor

**Click the fan icon and CPU temperature in the macOS menu bar.** The dropdown shows CPU, GPU, and palm-rest readings plus both fans' actual RPM and requested targets. It refreshes every five seconds and when opened. **View cooling curves…** opens a local page with CPU/GPU and palm-rest graphs and exact RPM tables. Those graphs describe the installed profile, not temperature history; reopen the page after changing the profile.

The monitor reads the installed status and configuration and calls only `cooler probe`. It never writes fans, changes the profile, or requires administrator access. SwiftBar does not trigger Cooler's competing-controller check. Status older than ten seconds is marked stale and its temperatures/targets are hidden. Missing sensor reads are displayed as unavailable. When Cooler yields to another controller, the menu says it is paused; Apple automatic is shown only when both hardware modes agree.

Installed locations:

- App: `/Applications/SwiftBar.app` (Homebrew cask, version 2.1.1 at setup).
- Plugin: `~/Library/Application Support/SwiftBar/Plugins/cooler.5s.py`, copied from `monitor/cooler.5s.py`.
- Login startup: `~/Library/LaunchAgents/com.chetangoel.cooler-monitor.plist`. It opens SwiftBar at login; quitting SwiftBar keeps it closed for that session. This is separate from SwiftBar's own Launch at Login checkbox, which can remain off. Actual logout/login remains untested.
- Curve page: SwiftBar's per-plugin cache. Running the script directly uses `~/Library/Caches/CoolerMonitor/curves.html` instead.

To install or update the monitor on this Mac, with Homebrew Python already at `/opt/homebrew/bin/python3`:

```sh
cd /Users/chetangoel/CodexProjects/cooler
brew install --cask swiftbar
mkdir -p "$HOME/Library/Application Support/SwiftBar/Plugins" "$HOME/Library/LaunchAgents"
install -m 755 monitor/cooler.5s.py "$HOME/Library/Application Support/SwiftBar/Plugins/cooler.5s.py"
install -m 644 monitor/com.chetangoel.cooler-monitor.plist "$HOME/Library/LaunchAgents/com.chetangoel.cooler-monitor.plist"
python3 tests/monitor.py
```

Open SwiftBar once and select that Plugins folder. Allow SwiftBar in **System Settings → Menu Bar** if its item is hidden. The plugin is a regular copy, so repeat the `install` command after editing its source. The login agent takes effect on the next login. To remove just the monitor, quit SwiftBar, remove its plugin and the login plist, and remove SwiftBar if no other plugins use it; Cooler continues controlling the fans independently.

`tests/monitor.py` runs the complete plugin against controlled files and a fake hardware probe, then performs a real read-only run. It checks readings, curve configuration, automatic/yielded modes, stale/missing/corrupt status, a stalled probe, and the read-only command boundary. Rerunnable evidence is saved in `artifacts/monitor-report.json`, `artifacts/monitor-menu.txt`, and `artifacts/monitor-curves.html`. No unit tests were added.

Deployment also confirmed successful execution inside SwiftBar every five seconds. Visual menu/graph review remains unverified: app automation repeatedly reopened SwiftBar's recovery notice, and the preview browser disallowed local file URLs. Login startup is configured, not reboot-tested.

## Recovery and limits

Only the two fan mode and target keys can be written. Hardware RPM limits are respected. No firmware changes, thermal-manager unlock keys, kernel extensions, or changes to macOS thermal services are used.

Missing/invalid sensors, invalid fan limits, critical macOS thermal pressure, and failed or partial writes trigger automatic control. Both fans must be restored successfully; otherwise the controller exits and its watchdog retries. Three healthy samples are needed before recovery. Startup also restores automatic mode before applying a new curve. Writes use a fresh SMC request and allow up to one second for readback to settle. Installation briefly requests full fan speed to verify control, then restores automatic mode before starting the service. Restoration verifies the fan mode; macOS chooses the target RPM in automatic mode, so that target is left untouched.

An independent watchdog watches a pipe from the controller. If it exits or stalls for ten awake seconds, the watchdog restores automatic control. On a stall it first kills the controller to prevent competing writes. macOS launchd restarts failed processes. If the watchdog itself exits, the controller also restores automatic mode and exits. Duplicate controllers are rejected by an exclusive lock.

These are software recovery measures, not firmware guarantees. Simultaneously killing both processes can leave the last manual setting until launchd restarts the service. A whole-system hang or hardware/SMC failure cannot be recovered by this process. Sleep/wake and reboot behavior require real-device checks; a replay of a time gap is not a substitute. CPU/GPU load, charging, and room temperature all affect achievable cooling.

## Verification

`tests/e2e.py` drives the compiled CLI with simulated sensor/fan input, using the same decision and write transaction as the daemon. It covers CPU-only and GPU-only heat, warm palms, baseline RPM, immediate increases, gradual decreases, missing/invalid sensors, three-sample recovery, conflicts, partial writes, wake gaps, invalid hardware limits, and malformed configuration. The replay mode performs no hardware access.

The failure inventory was written before implementation: incorrect SMC layout/types; non-finite, missing, or partial readings; invalid limits; hidden CPU/GPU hotspots; fan oscillation; partial writes; process crashes/stalls; sleep/wake; competing controllers; wrong hardware; malformed configuration; duplicate processes; unsafe installation permissions; and removal leaving fans in manual mode.

`tests/lifecycle.py` runs the compiled dry-run CLI and its real watchdog under normal termination, SIGKILL, SIGSTOP, and watchdog loss. It uses the same supervision code and real process pipes/signals, but its recovery callback only logs; it never writes fans.

Read-only probe and dry-run results, plus replay and lifecycle reports, live in `artifacts/`. The baseline was captured while Macs Fan Control held both fans at maximum RPM. It is **not** a baseline of Apple's default behavior and cannot demonstrate a cooling improvement over automatic control.

No unit tests were added. On-device lifecycle checks are in `tests/live.py`; `activate.sh` runs them after installation. They require administrator privileges and briefly interrupt the running service. Run only when Cooler is the sole fan controller. They record actual RPM, exercise normal termination, controller crash/stall, watchdog failure, explicit restoration to auto, and restart. A failure stops Cooler and attempts to restore automatic control. Reports distinguish simulated checks from hardware checks.
