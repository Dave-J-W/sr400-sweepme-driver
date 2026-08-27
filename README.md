# SR400 driver for SweepMe!

A [SweepMe!](https://sweep-me.net) **Logger** driver for the Stanford Research Systems
SR400 two-channel gated photon counter, over RS-232 or GPIB.

| | |
|---|---|
| Driver | [`Logger-Stanford_SR400/`](Logger-Stanford_SR400/) — `main.py` (~2400 lines), [README](Logger-Stanford_SR400/README.md), [tests](Logger-Stanford_SR400/tests/), `license.txt` |
| Columns | `Counter A`, `Counter B`, `Rate A`, `Rate B`, `Count time` |
| Interfaces | RS-232 (COM) and GPIB, via the pysweepme port manager |
| Tests | 383 checks, no hardware required |
| History | [`CHANGELOG.md`](CHANGELOG.md), [`docs/`](docs/) |

Every command the driver sends is documented in the SR400 manual, Revision 2.7,
chapter *Remote Programming* (pp. 37–47), and **audited against it** — see
[`docs/MANUAL_AUDIT.md`](docs/MANUAL_AUDIT.md). Nothing is inferred from generic
SCPI conventions: the SR400 predates IEEE-488.2 and has no `*IDN?`, `*RST` or
`*CLS`, so `connect()` identifies the instrument by reading its counting mode
(`CM`). MIT licensed.

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
10 MHz timebase, or `A for B preset` mode). Gotcha 3 in the driver README has the detail.

## Installing

A SweepMe! driver is a folder. Copy the driver directory — not this repository root —
into your SweepMe! `Drivers` folder, or clone this repo and point SweepMe! at it. Pure
Python over the pysweepme port manager: no vendor library, nothing to compile.

`main.py` is the only entry point SweepMe! will load. `pysweepme`'s
`get_main_py_path()` tries `main_<pyver>_<bitness>.py` for an architecture-specific
build and then falls back to `main.py`; nothing else in a driver folder is ever a
candidate, whatever it is called.

## Why a Logger and not a Switch

Every setting goes to the instrument once, in `configure()`; a measurement point is
then just an acquisition — `measure()` followed by `call()`. That is Logger semantics,
and the folder-name prefix is what actually selects the module. The `# Type:` comment
in `main.py` is documentation, not something the loader reads.

The consequence is that **gate-delay scanning is not wired up**, which matters because a
gate-delay scan is the SR400's characteristic experiment. Everything except the code is now
settled. It belongs in the scan machinery, every command it needs is implemented and
round-trip tested, and the output shape is decided: **a scan returns one row with *N*
columns per counter, and the mode selects the reduction applied to the scan buffer** — not a
different acquisition architecture. One SweepMe! point stays one complete scan; summing is
what `Scan of N periods` does to the buffer, and a gate scan simply does not sum.

Two things fell out of settling it. Driver-stepped rows are not available to a Logger at
all, since handing SweepMe! the x-axis needs the `SweepMode`/`apply()` pair a Logger never
gets. And the decision was smaller than recorded: auto-split and per-period statistics are
both *reductions to a fixed column count*, so neither was ever waiting on it.

[§7.2 of the driver README](Logger-Stanford_SR400/README.md) has the reasoning and the two
sub-decisions; §7.3 is the implementation spec.

## Host-side performance

Two things dominate RS-232 throughput and neither is the baud rate.

The SR400 pads every transmitted character by `WAIT × 3.3 ms` — 20 ms at the factory
default — which the driver zeroes automatically with `SW 0`. And an FTDI USB-serial
adapter holds short reads until its **latency timer** expires, 16 ms by default, charged
per read transaction rather than per byte. `connect()` detects the timer and warns once,
and two actions report and fix it: `report_com_port_latency` (read-only) and
`reduce_com_port_latency`, which writes sysfs on Linux and on Windows generates a `.reg`
file rather than demanding administrator rights. Both are host-side only and send the
instrument nothing, so either is safe to click mid-run. See §8 of the driver README.

Two more actions run a **hardware self-test** in two tiers: `run_self_test` needs no cabling
changes and writes the raw response-format table that retires the driver's remaining
assumptions, and `run_self_test_loopback` uses one BNC from the A DISC output to SIGNAL
INPUT 2 to give counters B and T an exact known pulse train — the only way to test counter B
at all, since it cannot see the internal timebase. Both refuse while the instrument is
counting, restore everything they touch without using a storage slot, and write a timestamped
report. Driver README §9.

`Fast readout (batch queries)` chains counter queries to cut round trips — about 3.5×
fewer at 10 periods per point. Off by default, because the manual both documents chained
queries and advises against them; gotcha 16 quotes both. **Fixing the latency timer is
worth more than enabling it**, and doing both is barely better than fixing the timer
alone.

## Tests

No SR400 required. `tests/test_sr400_virtual.py` implements a simulator of the
documented ASCII command set behind the pysweepme port interface — including the
instrument's buffer limits — and runs the whole driver lifecycle against it.

```bash
python Logger-Stanford_SR400/tests/test_sr400_virtual.py
```

383 checks, covering:

- both measurement modes, and both count-time modes
- the count-time planner as a pure function: every split in the specification, at every
  duty floor, plus the `is_exact` labelling of exact splits that exceed the soft cap on
  periods
- the count-period model including EXTERNAL dwell, and one-significant-digit preset
  rounding on both the count-time and the preset-counts paths
- `A for B preset` mode's `NaN` columns, and every range check
- the OR-accumulating status-byte poll, echo-on detection, and the timeout path
- interface-specific command gating on GPIB versus RS-232, and the front-panel lock cycle
- latency-timer detection and both actions, including that neither writes to the
  instrument
- batched readout proved **identical** to unbatched for 1/2/10/17/33 periods, plus its
  desync, buffer-limit and dead-link failure paths
- both hardware self-test actions: that they complete, restore every setting they touch
  against a full state snapshot, refuse while the instrument reports counting, detect a
  missing loopback cable and stop cleanly, and never send `SE`, `ST` or `RC`
- a round trip of every wrapped command

It does **not** cover anything about the real instrument: response *formats*,
command-processing latency, and all electrical behaviour need hardware. Passing means
the driver's logic is right against a simulator built from the same manual the driver was
written from — not that it measures correctly. The hardware bring-up sequence, in
escalating order, is §5.2 of the driver README.

## Where the driver came from

[`docs/`](docs/) holds the record — start with [`docs/README.md`](docs/README.md).

- [`docs/MANUAL_AUDIT.md`](docs/MANUAL_AUDIT.md) — every command, numeric limit and
  status bit checked against the manual. Nothing in the driver was wrong; three
  documentation defects were fixed, including one constant whose docstring claimed more
  than its source said. Also records a `pdftotext` trap that mis-pairs the abridged
  command list badly enough to make `SW` look like the terminator command.
- [`docs/plans/`](docs/plans/) — the latency-and-batching implementation plan, verbatim,
  plus a rebase note: what it assumed, where each task landed, two deliberate deviations.
- [`docs/drafts/`](docs/drafts/) — an independent early implementation, verbatim, with
  what was taken from it, what was not and why, and two defects in it reproduced against
  the virtual bench.

The drafts disagreed about the RS-232 line terminator, and that was recorded as needing
hardware. It did not — the manual settles it, and the driver's split is correct: `\r` on
RS-232 with echo off, CR LF on GPIB.
