# SR400 driver for SweepMe!

> **Abstract.** A SweepMe! Logger driver for the SRS SR400 photon counter, over RS-232 or GPIB, with
> hardware self-tests and discriminator threshold scans for an R8486 photomultiplier, run from the
> GUI at the end of a run. It works on hardware with SweepMe! 1.5.7.9 over GPIB (2026-11-10), and a
> virtual bench tests it with no instrument. To install, copy `Logger-Stanford_SR400/` into
> SweepMe!'s `CustomDevices` folder. Gate-delay scanning is the one missing feature. The table below
> says where to read next.

[SweepMe!](https://sweep-me.net) · Stanford Research Systems SR400 two-channel gated photon
counter · MIT licensed.

| | |
|---|---|
| Driver | [`Logger-Stanford_SR400/`](Logger-Stanford_SR400/): `main.py`, `selftest.py`, [README](Logger-Stanford_SR400/README.md), [tests](Logger-Stanford_SR400/tests/), `license.txt` |
| Columns | `Counter A`, `Counter B`, `Rate A`, `Rate B`, `Count time` |
| Interfaces | RS-232 (COM) and GPIB, via the pysweepme port manager |
| Tests | a virtual bench, no hardware required ([driver README §5.1](Logger-Stanford_SR400/README.md)) |
| History | [`CHANGELOG.md`](CHANGELOG.md), [`docs/HISTORY.md`](docs/HISTORY.md) |

Every command the driver sends is documented in the SR400 manual, Revision 2.7,
chapter *Remote Programming* (pp. 37–47), and **audited against it** — see
[`docs/MANUAL_AUDIT.md`](docs/MANUAL_AUDIT.md). Nothing is inferred from generic
SCPI conventions: the SR400 predates IEEE-488.2 and has no `*IDN?`, `*RST` or
`*CLS`, so `connect()` identifies the instrument by reading its counting mode
(`CM`).

## Where to read

| You want to | Read |
|---|---|
| install the driver and take counts | [driver README](Logger-Stanford_SR400/README.md) §1–3 |
| choose the discriminator threshold, step by step | [`docs/THRESHOLD_SCAN_GUIDE.md`](docs/THRESHOLD_SCAN_GUIDE.md) |
| run a self-test, and find its report | [driver README](Logger-Stanford_SR400/README.md) §9 |
| see real scans of the tube, and how they differ from the simulated examples | [`docs/SIMULATED_VS_REAL.md`](docs/SIMULATED_VS_REAL.md), [`docs/real_data/`](docs/real_data/) |
| know why the driver does what it does: gotchas, throughput, open items, test internals | [`docs/REFERENCE.md`](docs/REFERENCE.md) |
| go deeper into the threshold choice | [`analysis/`](analysis/): the low-signal optimum and the photon-background case |

[`docs/README.md`](docs/README.md) indexes everything in `docs/`.

## Two things to decide before you start

Everything else in the GUI has a sensible default. These two change the shape of a
run, so they sit at the top of the panel.

**`Measurement mode`** — how one SweepMe! point maps onto SR400 count periods:

- **Single count period** (default) — one point is one count period. `NP 1` plus an
  EXTERNAL dwell; the driver starts each period, so SweepMe! owns the point sequence.
  Fewest round trips, simplest timing.
- **Scan of N periods** — one point is one SR400 scan of *N* periods on the
  instrument's internal dwell, summed. This mode owns the SR400's scan machinery.

**`Count time mode`** — whether `Count time in s` means one period or the total:

- **Per period** (default) — one count period, rounded to the nearest settable value.
- **Total live time (auto-split)** — the total, split across periods for you.

A count period is quantised: the T preset keeps one significant digit, so there is no
1.5 s count *period*. But *N* periods of a settable length reach an exact total, so
auto-split takes 1.6 s and runs 2 × 0.8 s — exact to the timebase's 25 ppm. It holds
an 80 % duty floor by default, with a `>99 % duty cycle` tick box for when the dead
time between periods matters, and it plans both floors at once so it can tell you what
the other would have given. It refuses where a preset is not a time (counter T off the
10 MHz timebase, or `A for B preset` mode). Gotcha 3 has the detail.

## Installing

A SweepMe! driver is a folder. Copy the driver directory — not this repository root — into
SweepMe!'s custom-driver folder, which for SweepMe! 1.5.7 and 1.5.8 is

```
C:\Users\Public\Documents\SweepMe!\CustomDevices\Logger-Stanford_SR400\
```

(`get_folder("CUSTOMDEVICES")`; SweepMe! creates it on first start). Pure Python over the
pysweepme port manager: no vendor library, nothing to compile. `main.py` is the only entry point
SweepMe! loads; `selftest.py` beside it is loaded by the driver itself.

**What has been tested, and on what.** No minimum SweepMe! version has been established. The
evidence is:

- **On hardware: SweepMe! 1.5.7.9**, on the lab PC, with the SR400 on GPIB through an NI
  GPIB-USB-HS. On 2026-11-10, connect and *Retrieve data* worked and counts were returned, and
  the dark and light threshold scans ran as end-of-run tests ([`docs/real_data/`](docs/real_data/)).
  On this version the self-tests and scans cannot reach the instrument when run as actions,
  because SweepMe! gives the action neither a port name nor an open port. So they are run as
  end-of-run tests, ticked in the GUI (driver README §9.0).
- **On the virtual bench**, through standalone pysweepme from PyPI: 1.5.8.4 (the 1.5.8 line),
  1.5.6.17 and 1.6.1.5. The bench passes, the sibling `selftest.py` loads, and all six actions
  resolve. The 1.5.7 line has not been run on the bench, though its last PyPI release, 1.5.7.5,
  has the `message_box(msg, blocking=...)` that the threshold scans' prompts rely on. pysweepme
  1.5.8.4 has no `pysweepme.load_source`, so the driver's importlib fallback is the path that
  runs there.

SweepMe! compiles pysweepme into its executable, so the copy it bundles cannot be inspected. The
PyPI releases are stand-ins for it, not the same code.

## What is not there yet

**Gate-delay scanning.** The driver is a Logger: every setting goes to the instrument once, in
`configure()`, and a point is just an acquisition. A gate-delay scan, the SR400's characteristic
experiment, therefore belongs in the instrument's own scan machinery. Every command it needs is
implemented and round-trip tested, and the output shape is settled (one row of *N* columns per
counter). What remains is the code. [`docs/REFERENCE.md`](docs/REFERENCE.md) §7.2 has the
reasoning and §7.3 the implementation spec.

## Tests

No SR400 required. `tests/test_sr400_virtual.py` implements a simulator of the
documented ASCII command set behind the pysweepme port interface — including the
instrument's buffer limits and a simulated R8486 — and runs the whole driver lifecycle against it.

```bash
python Logger-Stanford_SR400/tests/test_sr400_virtual.py
```

What it covers, and the expected count, are in §5.1 of the driver README. Passing means the
driver's logic is right against a simulator built from the same manual the driver was written
from — not that it measures correctly. The hardware bring-up sequence is §5.2.

## Where the driver came from

[`docs/HISTORY.md`](docs/HISTORY.md) records the drafts it grew from, what was taken from them
and why, and the latency-and-batching plan ([`docs/plans/`](docs/plans/)).
[`docs/MANUAL_AUDIT.md`](docs/MANUAL_AUDIT.md) checks every command, numeric limit and status bit
against the manual.
