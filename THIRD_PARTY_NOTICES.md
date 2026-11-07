# Third-party notices

The SMC wire layout follows [Stats](https://github.com/exelban/stats), retrieved 2026-09-26. The per-generation sensor keys for M1–M4, the M5 CPU keys, and the choice between `F0md` and `F0Md` mode keys follow Stats as retrieved 2026-11-07 (`Sources/Hardware.swift`). The M5 GPU keys and the M6 CPU and GPU keys were identified by load tests on an M5 Pro and an M6 Mac mini. The fallback that sets the thermal-manager flag (`Ftst`) when an M3 or M4 Mac refuses a direct mode write, and clears it to restore automatic control, follows Stats (`SMC/smc.swift`) as retrieved 2026-11-07 and the [macos-smc-fan research](https://github.com/agoodkind/macos-smc-fan) (MIT) that Stats credits.

MIT License

Copyright (c) 2019 Serhiy Mytrovtsiy

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.

Palm sensor labels (`Ts0P`, `Ts1P`) follow the community mapping in [Asahi Linux's SMC documentation](https://asahilinux.org/docs/hw/soc/smc/), retrieved 2026-09-26. These are not Apple-certified surface temperature measurements.
