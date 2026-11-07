# Cooler

A personal background fan controller for the **M5 Pro MacBook Pro (Mac17,13)**. It keeps a low airflow floor and raises both fans according to the hottest configured CPU, GPU, or palm-rest reading. It starts when macOS boots and runs without a window or menu-bar item. It refuses to control the fans on any other Mac model, because sensor and fan keys differ between models.

Cooler was first built for the 16-inch M1 Max MacBook Pro (MacBookPro18,4). In November 2026 its sensor map and fan keys were replaced with this Mac's; M1 Max support remains in git history (commit `f7dedfc` and earlier).

The controller is Swift and IOKit, with no external runtime or network access. A **SwiftBar plugin** provides a menu-bar temperature, readings, profile controls, and a local curve viewer. **Cooler.app**, a small native editor opened from the menu, edits the custom curve and carries the controller for installation. The plugin uses Homebrew Python 3; the controller itself has no external runtime dependencies.

## Install with Homebrew

```sh
brew install chetangoel01/tap/cooler
```

This installs Cooler.app, plus SwiftBar and Homebrew Python as dependencies, then asks for your administrator password to install the controller, its profile helper, and the sudo rule that lets the menu switch profiles without asking again. It adds the SwiftBar plugin and the login agent that opens SwiftBar at login. A first install writes the default Cooler profile and briefly runs both fans at full speed to confirm control. `brew upgrade cooler` keeps the selected profile, keeps Cooler off if Apple Automatic was selected, and skips the full-speed check. `brew uninstall cooler` stops Cooler, returns the fans to Apple automatic, and keeps the profile for a reinstall; `brew uninstall --zap cooler` removes it and the saved Custom curve too. The controller runs only on a Mac17,13. The published release, 1.0.2, predates M5 support and installs no controller on this Mac, so install from source (below) until a new release. Do not reinstall or upgrade to the 1.0.2 cask meanwhile: Homebrew runs the uninstaller first, which removes the source-installed controller, and the cask then restores the old menu plugin. These install and upgrade rules are checked by `python3 tests/cask.py` (`artifacts/cask-report.json`), and the cask has been installed on one Mac, the M1 Max. There, the upgrade from 1.0.1 to 1.0.2 kept the profile unchanged, restarted the controller, replaced the plugin and login agent with the app's copies, removed the old editor copy, and the menu opened the installed Cooler.app. The first installs exposed two packaging bugs, both now covered by that test: launchd refused daemon files that kept the download's quarantine flag, and `~` paths in cask steps resolved to Homebrew's temporary home folder.

## Current deployment status

**M5 Pro, installed November 7, 2026** from source with `sudo ./activate.sh`, and running the Cooler curve. All **11 on-device checks passed** ([live report](artifacts/live-report.json)): both fans took manual mode and bounded targets and were spinning, and normal termination, a forced crash, a stalled controller, and watchdog loss each restored automatic control and recovered. Stopping returned both fans to automatic, a restart reapplied the curve, and the installed files are protected. The replay, lifecycle, profile, curve, cask, and monitor checks also pass, and the SwiftBar menu shows live CPU, GPU, and palm temperatures, fan speeds, and targets. The sensor and fan keys were mapped beforehand without writing to the SMC; see [M5 Pro sensors and fans](#m5-pro-sensors-and-fans).

The installer's two-second full-speed check ([result](artifacts/hardware-check.json)) confirmed that both fans accepted manual mode and their maximum targets, but they still read 0 RPM at that point, having started from a stop. The live check confirmed physical spinning eight seconds into control. Neither check held the fans at 8,400 / 9,072 RPM long enough to confirm they reach full speed. Sleep/wake, a full reboot, and everyday noise and comfort remain unverified.

Migration Assistant carried over the M1 Max installation: its daemon restarted every three seconds, refusing the new model, until it was disabled. The installed profile still named M1 Max sensors, and the menu showed CPU and GPU as unavailable. The source install replaced that profile with `config.json`, which reset the selected profile to Cooler. Macs Fan Control ran the fans in between and is now quit.

### M1 Max history

Deployed September 26, 2026 and verified running with the custom curve. All **11 on-device checks passed**, including physical fan response, normal termination, forced crash, stalled controller, watchdog loss, restoration to automatic control, service restart, and installation permissions. The 15 replay checks and four process/signal checks also passed. Evidence: [deployment verification](artifacts/deployment-verification.json); the M1 Max live report and hardware check are `artifacts/live-report.json` and `artifacts/hardware-check.json` as of commit `f7dedfc`, since the M5 install overwrote both. Actual sleep/wake, a full reboot, and everyday temperature/noise comfort were not verified.

**Heavy-load stalls, September 26 evening:** sustained heavy load starved the controller until its watchdog stopped it; see [Recovery and limits](#recovery-and-limits). The fix, launchd's Interactive process type, was installed at 23:31 that night. launchd then reported an interactive process, the controller and watchdog ran at priority 31 instead of 20, and the [cadence check](artifacts/cadence-report.json) found a steady loop and no watchdog timeouts. That sample peaked at 80°C, below the 99–107°C of the stalls, so the fix was never confirmed under comparable heat; running `python3 tests/cadence.py` after a hot stretch counts every timeout since installation. The [baseline report](artifacts/cadence-before.json) records the old priority 20 and nine timeouts.

## Cooling policy

`config.json` is the original **Cooler** profile. Installation copies it into `/Library/Application Support/Cooler/config.json`, owned by root. SwiftBar profile selection replaces the installed configuration; reinstalling the controller resets it to the source profile. These are starting comfort profiles, not a promise that the laptop can maintain any particular temperature.

| CPU or GPU temperature | Left fan | Right fan |
|---|---:|---:|
| 45°C or below | 2,000 RPM | 2,000 RPM |
| 55°C | 2,640 RPM | 2,707 RPM |
| 65°C | 3,920 RPM | 4,122 RPM |
| 75°C | 6,160 RPM | 6,597 RPM |
| 85°C or above | 8,400 RPM | 9,072 RPM |

Speeds are fractions of each fan's range above the floor: the higher of the profile's baseline (1,800 RPM) and the fan's hardware minimum (2,000 RPM on this Mac). The palm-rest curve independently requests 0% of that range at 30°C, 20% at 33°C, 50% at 36°C, and 100% at 40°C. The highest request wins. Values between points are interpolated. Both fans are read every two seconds; increases are immediate and decreases are limited to 40 RPM per second. A gap longer than ten seconds restores automatic mode and requires three healthy samples before resuming.

The curve fractions were tuned on the M1 Max, whose fans ran 1,200–5,779 / 6,241 RPM. This Mac's fans span 2,000–8,400 / 9,072 RPM, so the same temperature now asks for more speed: 75°C meant 4,386 / 4,687 RPM there and means 6,160 / 6,597 RPM here. Cooler also follows the hottest of 18 CPU cores rather than an average, so it reads higher than tools that average them. Noise and comfort on this Mac have not been judged yet.

See the [comparison with recorded Apple automatic targets](artifacts/curve-comparison.png) and [data and limits](artifacts/curve-comparison-notes.md). It was made on the M1 Max and compares the configured curve with six saved automatic-mode snapshots, not a recovered Apple curve or a controlled temperature/noise benchmark.

## M5 Pro sensors and fans

Every SMC key on this Mac was listed with read-only SMC requests ([temperature and fan keys](artifacts/m5-smc-keys.tsv)). Only 1 of the 14 M1 Max CPU/GPU keys exists here. The sensors were then identified by load, sampling every temperature key once a second while 18 busy processes loaded every CPU core, and again while a Metal compute kernel loaded the GPU. Macs Fan Control held the fans near 5,650 / 6,220 RPM throughout, so absolute temperatures were lower than they would be under Apple's control; the rises identify the sensors. Per-key results are in [the sensor report](artifacts/m5-sensor-discovery.json).

- **CPU:** the 18 per-core keys Stats lists for the M5 (`Tp00`–`Tp0K` for the 6 Super cores, `Tp0O`–`Tp0y` for the 12 Performance cores). All 18 rose 22–25°C under CPU load, more than any other key, and 13–16°C under GPU load.
- **GPU:** all 42 `Tg` keys. Each rose more under GPU load (19–29°C) than under CPU load (about 14°C). Stats' M5 GPU list was written for the base M5: one of its keys, `Tg1g`, does not exist on this M5 Pro, and it leaves out the hottest GPU sensors here.
- **Palm rest:** `Ts0P`/`Ts1P`, the same keys as on the M1 Max. They stayed flat under both loads, as skin sensors should. They do **not** measure the entire underside, and they have not been checked by touch on this Mac.
- **Fans:** two, with hardware limits of 2,000–8,400 RPM (left) and 2,000–9,072 RPM (right). The manual-mode keys are `F0md`/`F1md`, lowercase, where the M1 Max used `F0Md`. Stats writes these directly on the M5, and this Mac has no `Ftst` unlock key. Targets remain `F0Tg`/`F1Tg`. Under Apple automatic control both mode keys read 0, and at idle macOS stops both fans (target and speed 0 RPM). Whenever Cooler is in control the fans run at 2,000 RPM or more, so an idle Mac is audibly louder with Cooler than without it.

Five more CPU-side keys (`Tp1E`, `Tp1I`, `Tp1Q`, `Tp1U`, `Tp1g`) rose about 18°C under CPU load and 15°C under GPU load, and were left out as neither per-core nor GPU sensors. See [source attribution](THIRD_PARTY_NOTICES.md).

## Install, inspect, change, remove

Quit Macs Fan Control first and turn off its automatic startup. Keep it installed if desired, but do not run two fan controllers together. Cooler detects Macs Fan Control, Stats, TG Pro, smcFanControl, and macfan by process name, relinquishes control, and waits while any runs. This list cannot detect every possible tool.

To build and install the controller from source instead (this resets the installed profile to `config.json` and runs the on-device checks):

```sh
cd cooler
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

Status includes the PID that wrote it and updates every two seconds. A fresh file alone is not proof that a newly restarted process is ready. Logs record mode transitions and failures, not continuous readings. After a macOS update, check that the status timestamp is fresh and the mode is `custom`; this Mac runs macOS 27.2 build 26B8125.

To tune the profile, use **Edit Custom Curve…** in SwiftBar (below). For source defaults, edit `config.json`, run `check` and the replay tests, then rerun `sudo ./install.sh`. Do not edit the installed file in place; the running service reads its configuration at startup.

Remove the service and return both fans to Apple automatic control with `brew uninstall cooler`, or for a source install:

```sh
sudo '/Library/Application Support/Cooler/uninstall.sh'
```

Removal keeps the selected profile (`config.json`), this repository, test reports, and `/var/log/cooler.log`; `brew uninstall --zap cooler` removes the profile and log too. Re-enable Macs Fan Control startup yourself if you want to return to it.

## Menu-bar monitor

**Click the fan icon and CPU temperature in the macOS menu bar.** The menu lists CPU, GPU, and palm-rest temperatures and both fans' measured speeds (left · right), then the cooling modes, then **Edit Custom Curve…**. Hold **Option** while it is open to see Cooler's target speeds instead of measured ones, and **View Current Curves…** instead of the editor. That local page shows the installed profile's graphs and exact RPM tables, not temperature history. The menu refreshes every five seconds and when opened. SwiftBar's settings stay under **SwiftBar ›**; its update time and Disable Plugin rows are hidden. Screenshots from the M1 Max: [before](artifacts/menu-before.png), [after](artifacts/menu-after.png), [after with Option](artifacts/menu-after-option.png).

Reading the menu needs no administrator access. Refreshes use read-only status, configuration, service queries, and `cooler probe`. SwiftBar does not trigger Cooler's competing-controller check. A warning row, and a warning icon in the menu bar, appear whenever the checked mode is not what the fans are doing: no update from Cooler within ten seconds, status from another process, paused while another fan app is open, or fan control not confirmed. A brief "Resuming control…" row after a pause does not count as a warning. Targets appear only while Cooler is verified in control. Temperatures come from the live probe, including while Cooler is off; missing reads fall back to fresh controller status. Apple automatic is reported only when both hardware modes agree. SwiftBar grays out rows without an action, so readings use explicit light and dark text colors; dark mode has not been checked on screen.

Choose **Apple Automatic**, **Quiet**, **Balanced**, **Cooler**, **Max Cooling**, or your saved **Custom Curve** directly from the menu; hover over a mode to see its minimum speed and full-speed temperature. The checkmark identifies the configured curve (an exact match with a preset is shown as that preset), and no warning means it is active. Switching does not ask for a password. The menu notes a change in progress for two minutes and a failed change for thirty; a success simply moves the checkmark. A failed change keeps the previous setting. Cooler preserves the original curve shown above.

| Profile | Baseline | Targets at 75°C, left / right | Full speed by |
|---|---:|---:|---:|
| Quiet | 1,200 RPM | 4,240 / 4,475 RPM | 90°C |
| Balanced | 1,500 RPM | 5,200 / 5,536 RPM | 90°C |
| Cooler | 1,800 RPM | 6,160 / 6,597 RPM | 85°C |

The presets' baselines date from the M1 Max, whose fans could run at 1,200 RPM. This Mac's fans never run below 2,000 RPM, so all three presets idle at 2,000 RPM and differ only in their curves; the mode tooltips show that effective minimum. The table shows CPU/GPU requests before palm demand or retained speed during cooldown. Each preset has its own palm curve, with full speed at 40°C. Hardware RPM bounds, gradual slowdown, conflict detection, and the existing watchdog remain in effect. Quiet/Balanced comfort and noise have not been measured yet.

**Max Cooling** requests the hardware maximum on both fans, **8,400 / 9,072 RPM** on this Mac, and the menu-bar icon changes to wind while it runs. It stays selected until you choose another mode, including across restarts. It uses the same watchdog, conflict detection, sensor checks, and automatic recovery as the curves. Switching to another mode ends Max; there is no timer. Your saved Custom curve is kept.

**Edit Custom Curve…** opens a compact graph editor with CPU & GPU and Palm rest tabs. Drag a point to move it, or double-click the graph to add one; the + and − buttons add a point in the widest gap or remove the selected one. The selected point's temperature and speed can be typed exactly, with its left/right RPM beside them. Speed runs from Min, the minimum airflow, to Full: the percentage of each fan's range above that floor, not of its total RPM. While Cooler is running, a dashed line marks the current temperature on the curve. Adjust the minimum airflow from 1,200 to 2,500 RPM; on this Mac anything below 2,000 RPM has no effect, because that is the fans' hardware minimum. Points stay in order as you edit: temperatures rise, speed never falls, and the last point stays at Full. Temperatures are limited to 10–90°C, with 2–20 points per curve.

Use **Presets** to copy the installed, saved, Quiet, Balanced, or Cooler curve into the editor. The window subtitle says whether the curve shown is Active or Not applied, and **Apply** turns blue when there is something to apply. Changes remain a draft until **Apply** succeeds. That saves and activates a separate Custom curve, preserving the presets. A failed apply preserves both the installed and previously saved curve. The saved curve survives profile switches and quitting SwiftBar. Only baseline and curve points are editable; sensor mappings and recovery settings stay unchanged. Opening the editor performs read-only queries and does not change fans.

Changes are serialized and the proposed configuration is validated by the installed controller before interrupting control. Applying a profile stops Cooler, restores Apple automatic, atomically installs the protected configuration, then enables and starts the existing service. Failure after stopping restores the prior configuration and attempts to leave fans on Apple automatic with Cooler disabled. The menu reports errors and confirms a new process before claiming the preset is active. **Apple Automatic** stops and persistently disables Cooler; selecting a preset enables it again. Both choices survive restart. Profile changes run through one root-owned helper, `/Library/Application Support/Cooler/apply-profile`, which the menu calls with `sudo -n`. The rule in `/etc/sudoers.d/cooler` (source: `sudoers`) lets admin users run exactly `apply-profile automatic` and `apply-profile curve` without a password; the installers check it with `visudo` before installing it, and uninstall removes it. The helper reads only `baselineRPM`, `curve`, and `palmCurve` from the caller and merges them into the installed profile with `plutil`, so sensors, model, and recovery settings cannot be changed through it. The tradeoff: any process running as an admin user can switch the fan profile silently. It cannot do anything else as root. If the rule is missing, the menu reports it and asks you to reinstall.

Installed locations:

- App: `/Applications/SwiftBar.app` (Homebrew cask, version 2.1.1 at setup).
- Plugin: `~/Library/Application Support/SwiftBar/Plugins/cooler.5s.py`, copied from `monitor/cooler.5s.py`.
- Native editor: `/Applications/Cooler.app`, built from `monitor/CurveEditor.swift` by `scripts/release.sh`. The controller ships inside it at `Contents/Helpers/cooler`.
- Profile helper: `/Library/Application Support/Cooler/apply-profile` (from `apply-profile.sh`), with its sudo rule at `/etc/sudoers.d/cooler` (from `sudoers`).
- Saved Custom curve: `~/Library/Application Support/Cooler/custom.json`. This user-owned file is only a proposed configuration when selected; the installed controller validates it again before applying it to the protected system configuration.
- Login startup: `~/Library/LaunchAgents/com.chetangoel.cooler-monitor.plist`. It opens SwiftBar at login; quitting SwiftBar keeps it closed for that session. This is separate from SwiftBar's own Launch at Login checkbox, which can remain off. Actual logout/login remains untested.
- Curve page: SwiftBar's per-plugin cache. Running the script directly uses `~/Library/Caches/CoolerMonitor/curves.html` instead.

The Homebrew cask installs all of this. To try plugin changes from source, with Homebrew Python already at `/opt/homebrew/bin/python3`:

```sh
cd cooler
/bin/sh monitor/install.sh
python3 tests/monitor.py
python3 tests/profiles.py
python3 tests/curves.py
```

Open SwiftBar once and select that Plugins folder. Allow SwiftBar in **System Settings → Menu Bar** if its item is hidden. `monitor/install.sh` replaces only the plugin and login agent, without changing the root controller or active curve. The editor is Cooler.app; `./scripts/release.sh --no-notarize` builds a signed copy in `build/release/export`. The login agent takes effect on the next login. To remove just the monitor, quit SwiftBar and Cooler, remove the plugin, login plist and `/Applications/Cooler.app`, and remove SwiftBar if no other plugins use it; the controller continues independently. Keep `custom.json` if you want to preserve the custom curve.

## Releasing

Bump `CFBundleShortVersionString` in `app/Info.plist`, commit, then run `./scripts/release.sh`. It generates the Xcode project from `project.yml`, archives with Developer ID signing, notarizes and staples the app and DMG, tags the version, publishes a GitHub release with the DMG attached, and writes `packaging/cooler.rb` with the new version and checksum into [chetangoel01/homebrew-tap](https://github.com/chetangoel01/homebrew-tap). Pass `--no-publish` to stop after the notarized DMG, or `--no-notarize` to build and sign locally without uploading anything. Requires a notarytool keychain profile for the team (`NOTARY_PROFILE`, default `meeting-recorder`), `xcodegen`, `create-dmg`, and an authenticated `gh` CLI.

`tests/monitor.py` runs the complete plugin against controlled files and fake read-only hardware/service queries, then performs a real read-only run. It checks legible readings, targets under Option, curve configuration, automatic/yielded modes, old process status, stale/missing/corrupt status, warning icons, that old successes never read as live control, a stalled probe, sanitized dynamic text, reachable editor and curves page, live temperatures with the daemon stopped, and the read-only refresh boundary. Fixtures use a temporary home folder, so they never touch the real saved curve or action state. Rerunnable evidence is saved in `artifacts/monitor-report.json`, `artifacts/monitor-menu.txt`, and `artifacts/monitor-curves.html`.

`python3 tests/profiles.py` runs `apply-profile.sh` with the plugin's proposals, simulated launchd/SMC operations, and the real controller's configuration validation/replay. It checks preset ordering, Max/custom installation, restoration of the original Cooler preset, validation/stop/start failures, automatic mode persistence, that the helper ignores every field but the curves and rejects other modes and malformed values, a missing sudo rule, and overlapping actions. `python3 tests/cask.py` also checks that both the helper and the sudo rule are installed and removed. The report is `artifacts/profiles-report.json`. `python3 tests/curves.py` checks custom validation, protected sensor/recovery settings, actual read-only editor data, Max at cold/hot temperatures, and automatic recovery during Max. Its report is `artifacts/curves-report.json`. Neither suite performs real fan writes or uses sudo. `monitor/cooler.5s.py --preview-profile max` and `--preview-custom FILE.json` print the helper mode, the fields it receives, and the resulting configuration without applying them. A custom file contains exactly `baselineRPM`, `curve`, and `palmCurve`. No unit tests were added.

A separate live check successfully used the installed action and native authorization to reapply **Cooler**, confirming a new healthy controller process, unchanged curve values, protected configuration, manual fan modes, bounded targets, and both fans spinning. See `artifacts/profile-live-check.json`. Apple automatic as a final selection, Quiet/Balanced everyday comfort, and reboot persistence remain unverified on-device; their command/configuration behavior has process-level coverage.

On September 27, removing a point crashed the editor: a row outlived the shortened curve and read past its end. The crash was reproduced on the M1 Max and fixed; the editor reads and writes a point only while it exists, and its controls keep the curve they were made for, so an edit in progress stays in its own curve when switching tabs (that last case is covered by code review). The editor was then rebuilt around its graph: it opens at 640 × 350 points instead of 760 × 670 and carries no instructional text ([before](artifacts/editor-before.png), [after](artifacts/editor-after.png), [palm rest](artifacts/editor-after-palm.png)). `python3 tests/editor_ui.py` opens the installed editor, checks its size, removes and adds points with the + and − buttons, and switches tabs through accessibility actions, then confirms it is still running, closed without applying, and left no crash report or change to the installed or saved curve. Its runner needs Accessibility access, and it refuses to start while the editor is open. It sends no keystrokes or clicks at screen positions: macOS does not bring the editor to the front for an automation client, so such input could reach another app. Evidence: `artifacts/editor-ui-report.json`.

The original table-based editor was visually inspected and exercised on the M1 Max: baseline changes update both RPM previews, invalid temperature ordering disables Apply, both curve tabs work, and **Save & apply** activated an edited curve through native authorization. The live mode checks selected Max, verified both maximum targets, restored the saved Custom curve, and returned to Cooler while preserving Custom. Evidence and exact settings are in `artifacts/editor-live-check.json`. To repeat a live check with the current editor, open it, set the minimum to 2,100 and the second palm point to 25%, then Apply. Select Max, Custom, and finally Cooler from the menu, checking status and targets each time. This changes real fan settings.

SwiftBar execution every five seconds has been verified. The redesigned menu was opened on the M1 Max and captured normally and with Option held (screenshots above); the solid fan icon was seen in the menu bar under Cooler; warning rows, tooltips, and the other icon states are covered by fixtures but not yet seen on screen. Choosing Max and then Cooler from the SwiftBar menu worked on the M1 Max, each confirmed by a new controller process. Dark mode, graph dragging through computer automation, the curves page's visual rendering, and reboot persistence remain unverified. The native graph's displayed values, form edits and Apply flow have on-device coverage. Login startup is configured, not reboot-tested.

## Recovery and limits

Only the two fan mode keys (`F0md`/`F1md`) and two target keys (`F0Tg`/`F1Tg`) can be written. Hardware RPM limits are respected. No firmware changes, thermal-manager unlock keys, kernel extensions, or changes to macOS thermal services are used.

Missing/invalid sensors, invalid fan limits, critical macOS thermal pressure, and failed or partial writes trigger automatic control. Both fans must be restored successfully; otherwise the controller exits and its watchdog retries. Three healthy samples are needed before recovery. Startup also restores automatic mode before applying a new curve. Writes use a fresh SMC request and allow up to one second for readback to settle. Installation briefly requests full fan speed to verify control, then restores automatic mode before starting the service. Restoration verifies the fan mode; macOS chooses the target RPM in automatic mode, so that target is left untouched.

An independent watchdog watches a pipe from the controller. If it exits or stalls for ten awake seconds, the watchdog restores automatic control. On a stall it first kills the controller to prevent competing writes. macOS launchd restarts failed processes. If the watchdog itself exits, the controller also restores automatic mode and exits. Duplicate controllers are rejected by an exclusive lock.

launchd runs Cooler as an **Interactive** process. As a standard daemon it ran at utility priority 20 with throttled I/O. On the M1 Max, on the evening of September 26, sustained heavy load (CPU 99–107°C, load average near 50 on 10 cores) starved it past the ten-second limit nine times in two hours, sometimes again before a restarted controller's first heartbeat. Each time the fans returned to automatic control and launchd restarted Cooler. Interactive gives the controller and its watchdog normal priority (31) without throttled I/O. Profile changes reload the same installed plist, so every Cooler profile keeps it. This cause was diagnosed from the log and priorities, not reproduced with a synthetic load.

These are software recovery measures, not firmware guarantees. Simultaneously killing both processes can leave the last manual setting until launchd restarts the service. A whole-system hang or hardware/SMC failure cannot be recovered by this process. Sleep/wake and reboot behavior require real-device checks; a replay of a time gap is not a substitute. CPU/GPU load, charging, and room temperature all affect achievable cooling.

## Verification

`tests/e2e.py` drives the compiled CLI with simulated sensor/fan input, using the same decision and write transaction as the daemon. It covers CPU-only and GPU-only heat, warm palms, baseline RPM, immediate increases, gradual decreases, missing/invalid sensors, three-sample recovery, conflicts, partial writes, wake gaps, invalid hardware limits, and malformed configuration. The replay mode performs no hardware access.

The failure inventory was written before implementation: incorrect SMC layout/types; non-finite, missing, or partial readings; invalid limits; hidden CPU/GPU hotspots; fan oscillation; partial writes; process crashes/stalls; sleep/wake; competing controllers; wrong hardware; malformed configuration; duplicate processes; unsafe installation permissions; and removal leaving fans in manual mode.

`python3 tests/cadence.py` checks the installed service under this Mac's real workload without changing anything. It confirms launchd's process type and both processes' priorities, samples status updates for two minutes using the file's kernel timestamps, and lists watchdog timeouts logged since the plist was installed. A quiet sample proves little: the report says whether it saw heavy load, meaning CPU at 95°C or above as in every logged stall, so run it during heavy use or with `--seconds 1800`. Load average is reported but not used; it exceeded 70 while the CPU was half idle. Its report is `artifacts/cadence-report.json`; `artifacts/cadence-before.json` is the same check on the old standard-daemon setup.

`tests/lifecycle.py` runs the compiled dry-run CLI and its real watchdog under normal termination, SIGKILL, SIGSTOP, and watchdog loss. It uses the same supervision code and real process pipes/signals, but its recovery callback only logs; it never writes fans.

Read-only probe and dry-run results, plus replay and lifecycle reports, live in `artifacts/`. The M1 Max baseline was captured while Macs Fan Control held both fans at maximum RPM. It is **not** a baseline of Apple's default behavior and cannot demonstrate a cooling improvement over automatic control.

No unit tests were added. On-device lifecycle checks are in `tests/live.py`; `activate.sh` runs them after installation. They require administrator privileges and briefly interrupt the running service. Run only when Cooler is the sole fan controller. They record actual RPM, exercise normal termination, controller crash/stall, watchdog failure, explicit restoration to auto, and restart. A failure stops Cooler and attempts to restore automatic control. Reports distinguish simulated checks from hardware checks.
