# Cooler

A personal background fan controller for **MacBookPro18,4 / M1 Max**. It keeps a low airflow floor and raises both fans according to the hottest configured CPU, GPU, or palm-rest reading. It starts when macOS boots and runs without a window or menu-bar item.

Source: `/Users/chetangoel/CodexProjects/cooler`. No external runtime or network access. Swift and IOKit; build requires Xcode Command Line Tools.

An optional **SwiftBar plugin** provides a menu-bar temperature, readings, profile controls, and a local curve viewer. **Cooler Curves**, a small native editor opened from the menu, edits the custom curve. The plugin uses the existing Homebrew Python 3 installation; the controller itself still has no external runtime dependencies.

## Current deployment status

Deployed September 26, 2026 and verified running with the custom curve. All **11 on-device checks passed**, including physical fan response, normal termination, forced crash, stalled controller, watchdog loss, restoration to automatic control, service restart, and installation permissions. The 15 replay checks and four process/signal checks also passed. The running process matches its fresh status, and the installed binary matches the verified build. Macs Fan Control automatic startup is disabled.

Evidence: [live report](artifacts/live-report.json) and [deployment verification](artifacts/deployment-verification.json). Actual sleep/wake, a full reboot, and everyday temperature/noise comfort remain unverified; boot startup is configured through launchd.

**Heavy-load stalls, September 26 evening:** sustained heavy load starved the controller until its watchdog stopped it; see [Recovery and limits](#recovery-and-limits). The fix, launchd's Interactive process type, was installed at 23:31 that night. launchd now reports an interactive process, the controller and watchdog run at priority 31 instead of 20, and the [cadence check](artifacts/cadence-report.json) found a steady loop and no watchdog timeouts. That sample peaked at 80°C, below the 99–107°C of the stalls, so the fix is not yet confirmed under comparable heat; running `python3 tests/cadence.py` after a hot stretch counts every timeout since installation. The [baseline report](artifacts/cadence-before.json) records the old priority 20 and nine timeouts.

## Cooling policy

`config.json` is the original **Cooler** profile. Installation copies it into `/Library/Application Support/Cooler/config.json`, owned by root. SwiftBar profile selection replaces the installed configuration; reinstalling the controller resets it to the source profile. These are starting comfort profiles, not a promise that the laptop can maintain any particular temperature.

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

To tune the profile, use **Edit Custom Curve…** in SwiftBar (below). For source defaults, edit `config.json`, run `check` and the replay tests, then rerun `sudo ./install.sh`. Do not edit the installed file in place; the running service reads its configuration at startup.

Remove the service and return both fans to Apple automatic control:

```sh
sudo '/Library/Application Support/Cooler/uninstall.sh'
```

Removal preserves this repository, test reports, and `/var/log/cooler.log`. Re-enable Macs Fan Control startup yourself if you want to return to it.

## Menu-bar monitor

**Click the fan icon and CPU temperature in the macOS menu bar.** The menu lists CPU, GPU, and palm-rest temperatures and both fans' measured speeds (left · right), then the cooling modes, then **Edit Custom Curve…**. Hold **Option** while it is open to see Cooler's target speeds instead of measured ones, and **View Current Curves…** instead of the editor. That local page shows the installed profile's graphs and exact RPM tables, not temperature history. The menu refreshes every five seconds and when opened. SwiftBar's settings stay under **SwiftBar ›**; its update time and Disable Plugin rows are hidden. Screenshots: [before](artifacts/menu-before.png), [after](artifacts/menu-after.png), [after with Option](artifacts/menu-after-option.png).

Reading the menu needs no administrator access. Refreshes use read-only status, configuration, service queries, and `cooler probe`. SwiftBar does not trigger Cooler's competing-controller check. A warning row, and a warning icon in the menu bar, appear whenever the checked mode is not what the fans are doing: no update from Cooler within ten seconds, status from another process, paused while another fan app is open, or fan control not confirmed. A brief "Resuming control…" row after a pause does not count as a warning. Targets appear only while Cooler is verified in control. Temperatures come from the live probe, including while Cooler is off; missing reads fall back to fresh controller status. Apple automatic is reported only when both hardware modes agree. SwiftBar grays out rows without an action, so readings use explicit light and dark text colors; dark mode has not been checked on screen.

Choose **Apple Automatic**, **Quiet**, **Balanced**, **Cooler**, **Max Cooling**, or your saved **Custom Curve** directly from the menu; hover over a mode to see its minimum speed and full-speed temperature. The checkmark identifies the configured curve (an exact match with a preset is shown as that preset), and no warning means it is active. macOS asks for administrator authorization when applying a change (it may reuse a recent authorization). The menu notes a change in progress, a cancelled change for two minutes, and a failed change for thirty; a success simply moves the checkmark. Cancelling keeps the previous setting. Cooler preserves the original curve shown above.

| Profile | Baseline | Targets at 75°C, left / right | Full speed by |
|---|---:|---:|---:|
| Quiet | 1,200 RPM | 2,803 / 2,964 RPM | 90°C |
| Balanced | 1,500 RPM | 3,640 / 3,871 RPM | 90°C |
| Cooler | 1,800 RPM | 4,386 / 4,687 RPM | 85°C |

The table shows CPU/GPU requests before palm demand or retained speed during cooldown. Each preset has its own palm curve, with full speed at 40°C. Hardware RPM bounds, gradual slowdown, conflict detection, and the existing watchdog remain in effect. Quiet/Balanced comfort and noise have not been measured yet.

**Max Cooling** requests the hardware maximum on both fans, currently **5,779 / 6,241 RPM**, and the menu-bar icon changes to wind while it runs. It stays selected until you choose another mode, including across restarts. It uses the same watchdog, conflict detection, sensor checks, and automatic recovery as the curves. Switching to another mode ends Max; there is no timer. Your saved Custom curve is kept.

**Edit Custom Curve…** opens a native window with CPU/GPU and palm-rest tabs. Drag the blue points or edit their temperature and demand values; the graph and exact left/right RPM update together. Adjust the minimum airflow from 1,200 to 2,500 RPM. Demand is the percentage of each fan's available range above that floor, not a percentage of its total RPM. Add or remove intermediate points as needed. Each curve must rise in temperature, never fall in demand, and end at 100%; invalid settings disable **Save & apply**. Temperatures are limited to 10–90°C, with 2–20 points per curve.

Use **Start from** to copy an installed, saved, Quiet, Balanced, or Cooler curve into the editor. Changes remain a draft until **Save & apply** completes macOS authorization. That saves and activates a separate Custom curve, preserving the presets. A cancelled authorization preserves both the installed and previously saved curve. The saved curve survives profile switches and quitting SwiftBar. Only baseline and curve points are editable; sensor mappings and recovery settings stay unchanged. Opening the editor performs read-only queries and does not change fans.

Changes are serialized and the proposed configuration is validated by the installed controller before interrupting control. Applying a profile stops Cooler, restores Apple automatic, atomically installs the protected configuration, then enables and starts the existing service. Failure after stopping restores the prior configuration and attempts to leave fans on Apple automatic with Cooler disabled. The menu reports errors and confirms a new process before claiming the preset is active. **Apple Automatic** stops and persistently disables Cooler; selecting a preset enables it again. Both choices survive restart. There is no password storage, passwordless sudo rule, or additional privileged helper. The standard macOS authorization API runs fixed service/configuration operations only when you select a control.

Installed locations:

- App: `/Applications/SwiftBar.app` (Homebrew cask, version 2.1.1 at setup).
- Plugin: `~/Library/Application Support/SwiftBar/Plugins/cooler.5s.py`, copied from `monitor/cooler.5s.py`.
- Native editor: `~/Library/Application Support/Cooler/Cooler Curves.app`, built from `monitor/CurveEditor.swift`.
- Saved Custom curve: `~/Library/Application Support/Cooler/custom.json`. This user-owned file is only a proposed configuration when selected; the installed controller validates it again before applying it to the protected system configuration.
- Login startup: `~/Library/LaunchAgents/com.chetangoel.cooler-monitor.plist`. It opens SwiftBar at login; quitting SwiftBar keeps it closed for that session. This is separate from SwiftBar's own Launch at Login checkbox, which can remain off. Actual logout/login remains untested.
- Curve page: SwiftBar's per-plugin cache. Running the script directly uses `~/Library/Caches/CoolerMonitor/curves.html` instead.

To install or update the monitor on this Mac, with Homebrew Python already at `/opt/homebrew/bin/python3`:

```sh
cd /Users/chetangoel/CodexProjects/cooler
brew install --cask swiftbar
/bin/sh monitor/install.sh
python3 tests/monitor.py
python3 tests/profiles.py
python3 tests/curves.py
```

Open SwiftBar once and select that Plugins folder. Allow SwiftBar in **System Settings → Menu Bar** if its item is hidden. Rerun `monitor/install.sh` after changing monitor/editor source. The installer needs Command Line Tools, builds and signs the native editor locally, and replaces the user-owned monitor files without changing the root controller or active curve. An open editor keeps its draft; reopen it after saving to load a newly installed version. The login agent takes effect on the next login. To remove just the monitor, quit SwiftBar and Cooler Curves, remove the plugin, login plist and editor app, and remove SwiftBar if no other plugins use it; Cooler continues controlling the fans independently. Keep `custom.json` if you want to preserve the custom curve.

`tests/monitor.py` runs the complete plugin against controlled files and fake read-only hardware/service queries, then performs a real read-only run. It checks legible readings, targets under Option, curve configuration, automatic/yielded modes, old process status, stale/missing/corrupt status, warning icons, that old successes never read as live control, a stalled probe, sanitized dynamic text, reachable editor and curves page, live temperatures with the daemon stopped, and the read-only refresh boundary. Fixtures use a temporary home folder, so they never touch the real saved curve or action state. Rerunnable evidence is saved in `artifacts/monitor-report.json`, `artifacts/monitor-menu.txt`, and `artifacts/monitor-curves.html`.

`python3 tests/profiles.py` exercises the full exported action scripts with simulated launchd/SMC operations and the real controller's configuration validation/replay. It checks preset ordering, Max/custom installation, restoration of the original Cooler preset, validation/stop/start failures, automatic mode persistence, cancelled authorization, and overlapping actions. The report is `artifacts/profiles-report.json`. `python3 tests/curves.py` checks custom validation, protected sensor/recovery settings, actual read-only editor data, Max at cold/hot temperatures, and automatic recovery during Max. Its report is `artifacts/curves-report.json`. Neither suite performs real fan writes or administrator prompts. `monitor/cooler.5s.py --preview-profile max` and `--preview-custom FILE.json` print the proposed configuration and operations without applying them. A custom file contains exactly `baselineRPM`, `curve`, and `palmCurve`. No unit tests were added.

A separate live check successfully used the installed action and native authorization to reapply **Cooler**, confirming a new healthy controller process, unchanged curve values, protected configuration, manual fan modes, bounded targets, and both fans spinning. See `artifacts/profile-live-check.json`. Apple automatic as a final selection, Quiet/Balanced everyday comfort, and reboot persistence remain unverified on-device; their command/configuration behavior has process-level coverage.

The native editor was visually inspected and exercised on this Mac: baseline changes update both RPM previews, invalid temperature ordering disables Apply, both curve tabs work, and **Save & apply** activated an edited curve through native authorization. The live mode checks selected Max, verified both maximum targets, restored the saved Custom curve, and returned to Cooler while preserving Custom. Evidence and exact settings are in `artifacts/editor-live-check.json`. To repeat the UI check, open the editor, change baseline to 1,900 and the second palm point to 25%, verify that crossing two temperatures disables Apply, fix the order, then Save & apply. Select Max, Custom, and finally Cooler, checking status and targets each time. This repeat check changes real fan settings and may ask for administrator authorization.

SwiftBar execution every five seconds has been verified. The redesigned menu was opened on this Mac and captured normally and with Option held (screenshots above); the solid fan icon was seen in the menu bar under Cooler; warning rows, tooltips, and the other icon states are covered by fixtures but not yet seen on screen. Choosing Max and then Cooler from the SwiftBar menu worked on this Mac, each confirmed by a new controller process. Dark mode, graph dragging through computer automation, the curves page's visual rendering, and reboot persistence remain unverified. The native graph's displayed values, form edits and Apply flow have on-device coverage. Login startup is configured, not reboot-tested.

## Recovery and limits

Only the two fan mode and target keys can be written. Hardware RPM limits are respected. No firmware changes, thermal-manager unlock keys, kernel extensions, or changes to macOS thermal services are used.

Missing/invalid sensors, invalid fan limits, critical macOS thermal pressure, and failed or partial writes trigger automatic control. Both fans must be restored successfully; otherwise the controller exits and its watchdog retries. Three healthy samples are needed before recovery. Startup also restores automatic mode before applying a new curve. Writes use a fresh SMC request and allow up to one second for readback to settle. Installation briefly requests full fan speed to verify control, then restores automatic mode before starting the service. Restoration verifies the fan mode; macOS chooses the target RPM in automatic mode, so that target is left untouched.

An independent watchdog watches a pipe from the controller. If it exits or stalls for ten awake seconds, the watchdog restores automatic control. On a stall it first kills the controller to prevent competing writes. macOS launchd restarts failed processes. If the watchdog itself exits, the controller also restores automatic mode and exits. Duplicate controllers are rejected by an exclusive lock.

launchd runs Cooler as an **Interactive** process. As a standard daemon it ran at utility priority 20 with throttled I/O. On the evening of September 26, sustained heavy load (CPU 99–107°C, load average near 50 on 10 cores) starved it past the ten-second limit nine times in two hours, sometimes again before a restarted controller's first heartbeat. Each time the fans returned to automatic control and launchd restarted Cooler. Interactive gives the controller and its watchdog normal priority (31) without throttled I/O. Profile changes reload the same installed plist, so every Cooler profile keeps it. This cause was diagnosed from the log and priorities, not reproduced with a synthetic load.

These are software recovery measures, not firmware guarantees. Simultaneously killing both processes can leave the last manual setting until launchd restarts the service. A whole-system hang or hardware/SMC failure cannot be recovered by this process. Sleep/wake and reboot behavior require real-device checks; a replay of a time gap is not a substitute. CPU/GPU load, charging, and room temperature all affect achievable cooling.

## Verification

`tests/e2e.py` drives the compiled CLI with simulated sensor/fan input, using the same decision and write transaction as the daemon. It covers CPU-only and GPU-only heat, warm palms, baseline RPM, immediate increases, gradual decreases, missing/invalid sensors, three-sample recovery, conflicts, partial writes, wake gaps, invalid hardware limits, and malformed configuration. The replay mode performs no hardware access.

The failure inventory was written before implementation: incorrect SMC layout/types; non-finite, missing, or partial readings; invalid limits; hidden CPU/GPU hotspots; fan oscillation; partial writes; process crashes/stalls; sleep/wake; competing controllers; wrong hardware; malformed configuration; duplicate processes; unsafe installation permissions; and removal leaving fans in manual mode.

`python3 tests/cadence.py` checks the installed service under this Mac's real workload without changing anything. It confirms launchd's process type and both processes' priorities, samples status updates for two minutes using the file's kernel timestamps, and lists watchdog timeouts logged since the plist was installed. A quiet sample proves little: the report says whether it saw heavy load, meaning CPU at 95°C or above as in every logged stall, so run it during heavy use or with `--seconds 1800`. Load average is reported but not used; it exceeded 70 while the CPU was half idle. Its report is `artifacts/cadence-report.json`; `artifacts/cadence-before.json` is the same check on the old standard-daemon setup.

`tests/lifecycle.py` runs the compiled dry-run CLI and its real watchdog under normal termination, SIGKILL, SIGSTOP, and watchdog loss. It uses the same supervision code and real process pipes/signals, but its recovery callback only logs; it never writes fans.

Read-only probe and dry-run results, plus replay and lifecycle reports, live in `artifacts/`. The baseline was captured while Macs Fan Control held both fans at maximum RPM. It is **not** a baseline of Apple's default behavior and cannot demonstrate a cooling improvement over automatic control.

No unit tests were added. On-device lifecycle checks are in `tests/live.py`; `activate.sh` runs them after installation. They require administrator privileges and briefly interrupt the running service. Run only when Cooler is the sole fan controller. They record actual RPM, exercise normal termination, controller crash/stall, watchdog failure, explicit restoration to auto, and restart. A failure stops Cooler and attempts to restore automatic control. Reports distinguish simulated checks from hardware checks.
