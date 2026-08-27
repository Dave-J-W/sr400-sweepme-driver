# SR400 driver for SweepMe!

A [SweepMe!](https://sweep-me.net) Logger driver for the Stanford Research Systems
SR400 two-channel gated photon counter, over RS-232 or GPIB.

| Driver | Reads | Notes |
|---|---|---|
| [`Logger-Stanford_SR400`](Logger-Stanford_SR400/) | Counts and rates on counters A and B, summed over the count periods of one point, plus the applied count time | [README](Logger-Stanford_SR400/README.md), [tests](Logger-Stanford_SR400/tests/) |

Every command the driver sends is documented in the SR400 manual, chapter *Remote
Programming – Detailed Command List* (manual pp. 37–47). Nothing is inferred from
generic SCPI conventions: the SR400 predates IEEE-488.2 and has **no `*IDN?`,
`*RST` or `*CLS`**, so `connect()` identifies the instrument by reading its
counting mode (`CM`) instead. MIT licensed — see `license.txt` in the driver
folder.

## Installing

A SweepMe! driver is a folder. Copy the driver directory — not this repository
root — into your SweepMe! `Drivers` folder, or clone this repo and point SweepMe!
at it. The driver is pure Python over the pysweepme port manager; there is no
vendor library to install and nothing to compile.

`main.py` is the only entry point SweepMe! will load. `pysweepme`'s
`get_main_py_path()` tries `main_<pyver>_<bitness>.py` for an
architecture-specific build and then falls back to `main.py`; nothing else in a
driver folder is ever a candidate, whatever it is called.

## Why a Logger and not a Switch

Every setting goes to the instrument once, in `configure()`; a measurement point
is then just an acquisition — `measure()` followed by `call()`. That is Logger
semantics, and the folder-name prefix is what actually selects the module. The
`# Type:` comment in `main.py` is documentation, not something the loader reads.

The consequence is that **sweeping a gate delay is not wired up yet**, which
matters because a gate-delay scan is the SR400's characteristic experiment. The
command layer for the instrument's own scan machinery is complete and tested;
what is undecided is how to present *N* scan points through a `call()` that
returns one row. That decision is written up in
[§7.2 of the driver README](Logger-Stanford_SR400/README.md) and should be settled
before any gate-scan GUI parameters are added.

## Where the driver came from

[`docs/`](docs/) holds the record. Three drafts were written before the driver was
settled; two of them turned out to be byte-identical copies of each other, and the
third — [`docs/drafts/SRS_SR400.py`](docs/drafts/SRS_SR400.py) — was a genuinely
independent 595-line implementation. **Start with
[`docs/README.md`](docs/README.md):** it records what was taken from that draft and
what was deliberately not, two defects in it that are easy to reproduce by accident,
and the one question the two drafts disagree on that only hardware can settle (the
RS-232 line terminator).

## Tests

The suite needs no SR400. `tests/test_sr400_virtual.py` implements a simulator of
the documented ASCII command set behind the pysweepme port interface and runs the
whole driver lifecycle against it.

```bash
python Logger-Stanford_SR400/tests/test_sr400_virtual.py
```

109 checks: the count-period model including EXTERNAL dwell, the one-significant-
digit preset rounding, `A for B preset` mode's `NaN` columns, every range check,
the OR-accumulating status-byte poll, the echo-on and timeout failure paths,
interface-specific command gating on GPIB versus RS-232, the front-panel lock
lifecycle, the GUI options, and a round trip of every wrapped command.

It does **not** cover anything about the real instrument: response *formats*,
command-processing latency, and all electrical behaviour need hardware. Passing
means the driver's logic is right against a simulator built from the same manual
the driver was written from — not that it measures correctly. The hardware
bring-up sequence, in escalating order, is §5.2 of the driver README.
