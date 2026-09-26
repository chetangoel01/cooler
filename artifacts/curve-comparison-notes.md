# Apple automatic fan control: comparison limits

Researched September 26, 2026 for Cooler on MacBookPro18,4 (M1 Max). Primary sources only; no machine settings changed.

- Apple says internal temperature sensors trigger cooling fans. Fan response also depends on ambient temperature: warmer surroundings can make fans start earlier and run faster. [Apple: About fans and fan noise](https://support.apple.com/en-us/101576)
- Apple describes automatic cooling qualitatively, without temperature-to-RPM values in either of the support documents reviewed. The focused Apple-domain searches for `MacBookPro18,4 fan` and `M1 Max fan curve` did not find a published model-specific curve. This is a limited research result, not proof that no such information exists anywhere. [Apple: About fans and fan noise](https://support.apple.com/en-us/101576), [Apple: Acceptable operating temperatures](https://support.apple.com/en-us/102336)

## What the comparison can honestly show

The repository contains six saved probes with both `F0Md` and `F1Md` in automatic mode. They cover approximately 70–82°C on the hottest of Cooler's configured CPU/GPU sensors, from September 26, 2026 at 20:51–21:21 UTC. The [comparison chart](curve-comparison.png) shows those observed **target RPM** readings as unconnected points against Cooler's configured CPU/GPU targets. They are not enough to recover Apple's full curve. A single temperature axis also cannot capture all the influences Apple documents on fan response.

At the first saved snapshot, CPU was 77.118°C, GPU 69.919°C, and palm 30.996°C. Apple automatic targets were 2,317 / 2,502 RPM; actual fans were approximately 2,335 / 2,521 RPM. Cooler's installed rule would request 4,681 / 5,016 RPM at those sensor values, before any retained target from gradual slowdown. That is roughly twice the target RPM, not a claim of twice the cooling or a measured drop in temperature.

Sources are listed individually with values in [curve-comparison-data.json](curve-comparison-data.json). Some probes were taken after installation or recovery checks and are not steady-state observations; the final restoration probe still had actual fans decelerating. The original `baseline.json` was manual full-speed control and is excluded. Dry-run output is calculated Cooler behavior and is also excluded from Apple observations. No fan settings were changed to make this comparison.

Each computed Cooler comparison target is verified through the existing compiled controller's read-only `replay` command. The plot includes the 1,800 RPM baseline and full speed at 85°C. Palm-rest demand can raise targets further; it was lower than CPU/GPU demand in all six saved samples. Actual targets can also remain above the plotted line during gradual slowdown.

Rebuild with `python3 analysis/plot_curve_comparison.py` from the repository after installing Matplotlib in an isolated environment. This creates PNG, SVG, and a JSON data artifact, and verifies the six calculated targets against `build/cooler`. The graph generation environment is separate from the installed controller and monitor.
