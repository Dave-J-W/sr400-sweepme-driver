# Historical record: the drafts this driver came from

Nothing in this folder is loadable by SweepMe!. It is kept so the reasoning
behind [`Logger-Stanford_SR400`](../Logger-Stanford_SR400/) stays recoverable.

## What the drafts were

Three files were written independently before the driver was settled:

| Draft | Fate |
|---|---|
| `From Claude Opus5/` | Became the driver. See commit `d56abea`. |
| `From GPT/` | **Byte-identical** to the above — same MD5 on all three files. It was a copy, not a second opinion, so there was nothing to merge. Deleted in `bf1403f`. |
| [`drafts/SRS_SR400.py`](drafts/SRS_SR400.py) | A genuinely independent implementation, 595 lines against the kept driver's ~1400. Kept here. |

`SRS_SR400.py` is not a driver folder and has no `main.py`, so SweepMe! cannot
load it even by accident. It also predates the Switch → Logger decision.

## What was taken from `SRS_SR400.py`

Three things, ported in the same commit that filed this note:

1. **`Baudrate` as a GUI parameter.** The kept driver hardcoded 9600. The draft
   exposed the SR400's supported rates and pushed the choice into
   `port_properties`, which is strictly better on serial.
2. **Front-panel-change detection.** The draft checked status bit 0 during its
   poll and logged that someone had turned a knob. The kept driver read that bit
   and ignored it. It now reports it from `_check_status()`, so every path that
   interprets a status byte covers it — a changed parameter means the instrument
   no longer matches what `configure()` sent.
3. **`CH` before raising on timeout.** The draft stopped the counters before
   throwing. The kept driver just threw, leaving the SR400 counting into a scan
   nobody would read. Now applied on both the timeout and the run-stopped paths.

## Taken later: the draft's measurement architecture, as a mode

This was originally recorded here as "not taken". That was wrong, and it was
reversed: the draft's `NP 1` + `DT 0` architecture is now the **`Single count
period`** mode *and the default*, with the kept driver's multi-period behaviour as
**`Scan of N periods`**. The two were never really alternatives — `NP 1` is the
special case — so offering both costs nothing, and the simple path no longer drags
the scan machinery's assumptions along with it. The draft was right that this
should be the default.

## What was deliberately not taken

- **String presets (`"1E7"`).** The draft passed the preset through verbatim,
  which is honest about the SR400's native format and skips the kept driver's
  rounding arithmetic — but see the defect below. The kept driver's
  round-to-nearest plus read-back reports what the instrument *actually* used,
  which matters more. A synthesis (string entry **and** read-back) would be
  better than either and is not done.
- **`units = ["counts", "counts"]`.** Cosmetic; the kept driver's five columns
  use `""` for the two raw counts.
- **Coupling `PM` into `set_port_level()`.** The kept driver keeps PORT output
  off behind an explicit checkbox so it never disturbs external hardware wired
  to the analog outputs.

## Two verified defects in `SRS_SR400.py`

Both were reproduced by running the draft against the virtual SR400 in
[`Logger-Stanford_SR400/tests/`](../Logger-Stanford_SR400/tests/), not just read
off the source. Recorded because they are easy mistakes to make again.

**1. `A FOR B PRESET` mode always raises.** `_parse_count()` rejects any negative
value, but the manual specifies `QB` returns −1 *by design* in that mode, because
B is then the preset counter:

```
A FOR B PRESET -> RuntimeError: SR400 counter B returned -1; the data point was not available.
```

One of the four counting modes is unusable. The kept driver reports `NaN` for
Counter B, Rate B and Count time there.

**2. Preset truncation is silent and invisible.** `CP` keeps only the most
significant digit, and the draft neither rounds nor reads back.

Worth stressing that the kept driver had **half of this same bug**. It rounded and
read back the *count time*, but `Preset counts (T or B)` — which governs whenever
counter T is not on the timebase, and in `A for B preset` mode — was rounded
silently, and that branch has no count-time column that could have revealed it.
Asking 1.5e6 got you 2e6 with nothing said. Found while answering a question about
this entry, and fixed. The draft's version of the bug:

```
asked T preset : 15000 cycles = 1.5 ms
instrument holds: 10000.0 cycles = 0.001 s
driver reports  : [50.0, 1.0]   (variables: ['Count A', 'Count B'])
```

The draft outputs no count-time or rate column, so a hand-computed rate is 33%
low with nothing in the data to reveal it.

## One unresolved question the drafts disagree on

The two disagree about line terminators, and only hardware can settle it:

| | Kept driver | `SRS_SR400.py` |
|---|---|---|
| RS-232 | `EOL: "\r"` | `EOL: "\r\n"` |
| GPIB | `GPIB_EOLwrite: "\r"`, `GPIB_EOLread: "\n"` | same `"\r\n"` both ways |

The kept driver's split follows the manual's statement that with `ECHO=OFF` the
SR400 answers on RS-232 with **CR only**, while GPIB always terminates CR LF. If
that is right, the draft's reads wait for an LF that never arrives and every
serial query times out. The simulator ignores terminators, so this cannot be
tested off the bench — check it first during hardware bring-up (driver README
§5.2).

Related: the draft never sends `SW 0`. At the factory default `WAIT=6` the SR400
pads **every character it transmits** by 6 × 3.3 ms ≈ 20 ms, so a nine-digit
count takes ~180 ms regardless of baud rate. Not incorrect, but it makes RS-232
look broken, and the draft polls the status byte every 10 ms.
