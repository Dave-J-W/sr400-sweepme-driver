# SweepMe! driver — Stanford Research Systems SR400 photon counter

Module: **Logger** · Interfaces: **RS-232 (COM)** and **GPIB**
Files: `main.py`, `selftest.py` (§9), `README.md`, `license.txt`, `tests/test_sr400_virtual.py`

**This README is the operator's reference**: installing, the GUI, the end-of-run tests and their
reports. The design detail is in [`docs/REFERENCE.md`](../docs/REFERENCE.md) in the
sr400-sweepme-driver repository: the 16 gotchas, throughput, open items, and how each self-test and
scan works inside. Both files share one section numbering, so a report that says "gotcha 16" or
"README section 7.1" finds it in one or the other. Choosing a discriminator threshold for the first
time: [`docs/THRESHOLD_SCAN_GUIDE.md`](../docs/THRESHOLD_SCAN_GUIDE.md).

Every command this driver sends is documented in the SR400 manual, chapter *Remote Programming –
Detailed Command List* (manual pp. 37–47). Nothing is inferred from generic SCPI conventions; the
SR400 predates IEEE-488.2 and has **no `*IDN?`, `*RST` or `*CLS`**.

---

## 1. Quick start

1. **On the instrument (front panel, COM menu):**
   - RS-232: set `BAUD`, `BITS`, `PARITY` to match your port (driver defaults: 9600, 8, none)
     and set **`RS-232 ECHO = OFF`**.
   - GPIB: set `GPIB ADDR` to something in 1…30. The driver asserts REN itself (gotcha 12).
2. Copy the whole `Logger-Stanford_SR400` folder into SweepMe!'s custom-driver folder —
   `C:\Users\Public\Documents\SweepMe!\CustomDevices\` for SweepMe! 1.5.7 and 1.5.8 (seen on
   1.5.7.9).
3. Add a **Logger** module, pick the SR400, choose the port.
4. Minimum sanity configuration: switch `Counter A input` from its default `INPUT 1` to
   `10 MHz`, and set `Count time in s = 1` and `Gate A mode = CW`. One measurement point must
   return **Counter A = 10 000 000** and **Rate A = 1.0e7**. If that number is exact, the preset
   arithmetic, the status polling and the buffer read are all working.
5. Then switch `Counter A input` back to `INPUT 1`, connect your PMT, and set the discriminator
   level.

### Why the *Logger* module

Every setting goes to the instrument once, in `configure()`; a measurement point is then just an
acquisition — `measure()` followed by `call()`. That is Logger semantics, and it is what the
folder-name prefix selects. There is no `apply()` and no `SweepMode`: the Logger module does not
render a sweep field, so an `apply()` here would be code that SweepMe! never calls.

**Gate-delay scanning is therefore not yet wired up**, and that is the one real functional gap.
The SR400's characteristic experiment is a gate-delay scan, and this driver can currently only sit
at one gate delay per run. The route is the instrument's own scan machinery rather than a SweepMe!
sweep — `Gate A mode = Scan` plus `GY` (delay step), `DT` and `NP` make the SR400 step its own gate
and fill the scan buffer, which `EA` dumps in one transfer — and every one of those commands is
already implemented and round-trip tested below. The output shape is settled too (§7.2): a scan
returns one row of *N* columns per counter, and the mode picks the reduction. What remains is the
code. §7.3 is the spec.

---

## 2. What one measurement point is

That depends on `Measurement mode`, which is the first GUI field and the only one that changes
the shape of a run.

### Single count period (default)

One SweepMe! point = one SR400 count period. The driver forces `NP 1` and `DT 0` (EXTERNAL
dwell) and starts every period itself, so the point sequence belongs to SweepMe! rather than to
the instrument. Fewest round trips per point, and the easiest timing to reason about. Use this
unless you specifically want the instrument to do the accumulating.

`Periods per point` and `Dwell time in s` do not apply. If you set either of them away from its
default in this mode, the driver says so once rather than letting the field look live.

### Scan of N periods

One SweepMe! point = one SR400 **scan** of `Periods per point` count periods, with the
instrument's own internal dwell between them. The SR400 runs the whole scan from a single `CS`
and the driver sums the buffer entries. This is the mode that owns the instrument's scan
machinery, so it is where gate-delay scanning will land (§7.3).

The command traffic below is the scan mode; the single-period mode is the same with `NP 1`:

```
measure()    CR                       reset counters
             SS                       read+clear the status byte (also reports config errors)
             CS                       start
             SS SS SS …               poll until "scan finished"
             QA 1, QB 1, QA 2, …      read the scan buffer point by point
call()       → [Counter A, Counter B, Rate A, Rate B, Count time]
```

- **Counter A / Counter B** — counts **summed** over all periods of the point.
- **Count time** — the *gross* count period length summed over the point. It is only known when
  counter T is preset **and** its input is the internal 10 MHz clock, because only then does the
  T preset correspond to a time (`count time = T preset / 10 MHz`). Otherwise `NaN`.
- **Rate A / Rate B** — counts ÷ *gross* count time. This is **not** corrected for the gate duty
  cycle. With a gate open for 1 µs at a 1 kHz trigger rate inside a 1 s count period, the true
  photon rate is ~10⁶ times the reported "Rate". Compute the duty-cycle correction yourself from
  the trigger rate and gate width — the SR400 does not know the trigger rate.

---

## 3. GUI parameters

| Parameter | Command | Notes |
|---|---|---|
| `Measurement mode` | `NP`, `DT` | `Single count period` (default) forces `NP 1` + EXTERNAL dwell. `Scan of N periods` uses `Periods per point` and the internal dwell. See §2. |
| `Count mode` | `CM` | Selects which counter is preset. Also resets the counters. |
| `Counter A/B/T input` | `CI` | Hardware-restricted: A ∈ {10 MHz, INPUT 1}, B ∈ {INPUT 1, INPUT 2}, T ∈ {10 MHz, INPUT 2, TRIG}. Wrong combinations are rejected before anything is sent. |
| `Count time mode` | — | `Per period` (default): `Count time in s` is one count period, rounded to the nearest settable value. `Total live time (auto-split)`: it is the **total**, and the driver splits it across periods. See gotcha 3. |
| `Quantize count time to >99% duty cycle` | — | Raises the auto-split duty floor from 80 % to 99 %. Costs accuracy on the total; the plan message says what the other floor would have given. Ignored in `Per period` mode. |
| `Count time in s` | `CP 2` | Used when `Counter T input = 10 MHz`. Converted to clock cycles. One period, or the total, per `Count time mode`. |
| `Preset counts (T or B)` | `CP 1/2` | Used when T counts INPUT 2 / TRIG, or in `A for B preset` mode. |
| `Periods per point` | `NP` | 1…2000. Counts are summed. **`Scan of N periods` only**, and computed by the planner in auto-split mode rather than read from here. |
| `Dwell time in s` | `DT` | 2 ms…60 s, or **exactly 0** for EXTERNAL dwell. **`Scan of N periods` only.** |
| `Trigger slope` / `Trigger level in V` | `TS` / `TL` | ±2.000 V, 1 mV resolution. |
| `Discriminator A/B/T slope` / `level in V` | `DS` / `DL` | ±0.3000 V, 0.2 mV resolution. Mode is forced to FIXED (`DM i,0`). |
| `Gate A/B mode` | `GM` | CW / Fixed / Scan. |
| `Gate A/B delay in s` | `GD` | 0…999.2 ms. |
| `Gate A/B width in s` | `GW` | 5 ns…999.2 ms. |
| `Set PORT levels` + `PORT1/2 level in V` | `PM`, `PL` | **Off by default** so the driver never disturbs external hardware wired to the analog outputs. |
| `Baudrate` | — | COM ports only; must match the SR400's own `BAUD` setting. Ignored on GPIB. |
| `Timeout in s` | — | Margin *added* to the predicted acquisition time. |
| `Fast readout (batch queries)` | — | Chains several `QA`/`QB` queries per line. **Off by default**, and deliberately so — see gotcha 16. Only helps `Scan of N periods`. |
| `Reset instrument at start` | `CL` | Off by default. See gotcha 5. |
| `Lock front panel` | `MI` | RS-232 only; released again in `unconfigure()`. See gotcha 14. |
| `PMT high voltage in V (record only, 0 = not recorded)` | — | Written into every report, scan CSV, figure and the test log. The driver never sets or reads the supply. A light scan is only scored against a dark scan with the same recorded HV. See §9.8. |
| End-of-run tests (five checkboxes) | — | Self-tests and threshold scans, run once after the last point. All off by default. See §9.0. |
| `Print SweepMe! phase` | — | Debug aid. Prints the name of each semantic function as SweepMe! calls it (`connect`, `initialize`, `configure`, `measure`, `call`, `unconfigure`) to the SweepMe! debug console. Off by default and silent when off. |

All of these are applied once, in `configure()`. To vary one of them across a run you currently
have to change it in the GUI and start a new run — see "Why the *Logger* module" above and §7.3.

---

## 4. Gotchas

Sixteen things that cost time if you do not know them, mostly instrument quirks the driver
already handles. The full text is §4 of [`docs/REFERENCE.md`](../docs/REFERENCE.md):

1. `RS-232 WAIT` defaults to 6 — that is 20 ms per character
2. `RS-232 ECHO` must be OFF
3. Presets and the dwell time keep only ONE significant digit
4. Gate delay and width have variable resolution
5. Do not reset the instrument casually
6. Status bits are destructive reads, and that is load-bearing
7. Counter overrun means your data is wrong, not just large
8. A rate error is a physics warning, not a comms error
9. `A for B preset` mode returns −1 for counter B
10. Changing gate parameters while counting corrupts data
11. A gate delay in CW mode does nothing
12. Interface-specific commands
13. Cabling: the SR400 is a DCE
14. A knob turned mid-run silently invalidates the configuration
15. The USB-serial latency timer costs more than the baud rate
16. Batched queries: the manual argues with itself, so this is opt-in

The ones an operator meets first are **3** (one significant digit, so 1.5 s is not a count
period), **8** (a rate error is physics, not comms) and **12** (GPIB needs REN, which the driver
asserts).

---

## 5. Test procedures

### 5.1 Virtual bench (no hardware needed)

`test_sr400_virtual.py` implements a simulator of the SR400 protocol behind the pysweepme port
interface, including the instrument's buffer limits, and runs the full driver lifecycle against
it. It covers:

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
- both hardware self-tests: that they complete, restore every setting they touch
  against a full state snapshot, refuse while the instrument reports counting, detect a
  missing loopback cable and stop cleanly, and never send `SE`, `ST` or `RC`
- both threshold scans against a simulated R8486: adaptive dark timing, the light-leak and
  no-signal refusals, the light probe's refusals, drift flagged, injected hysteresis
  recovered in mV, and the S/√B optimum landing between the noise edge and the level
  where dark counts vanish
- the scans' records and plots: CSV and SVG written beside each report, the CSV re-analysed to
  the same result, the plot regenerated from the CSV alone, and the refusals visible on the
  figure itself; and every committed figure in `docs/` exactly what the code draws from its CSV
- a round trip of every wrapped command

```bash
pip install pysweepme
python tests/test_sr400_virtual.py   # expect "645/645 checks passed"
```

Run this before every hardware session and after every driver edit. Adding a case is one `test_*`
function plus one entry in the tuple at the bottom of `main()`.

It caught three real defects during development: a status byte cleared before it was checked (which
would have swallowed errors from the setup commands), a rounding message that compared against the
requested rather than the applied count time, and a broken EXTERNAL-dwell period model in the
simulator itself.

The simulator is **not** a substitute for hardware. It cannot validate response *formats*, real
command-processing latency, or electrical behaviour.

### 5.2 Hardware, in this order

**Most of this is automated — see §9.** The tier 1 self-test covers steps 1, 3, 5, 6, 9 and 10
below without any cabling change, and writes the response-format table that retires §7.1. Tier 2
covers counter B and the discriminators, which the manual sequence here cannot reach without a
cable. Run them first (§9.0) and use this list for what they leave: the real signal, the gates,
and the failure behaviour.

Escalate only after each step passes. Steps 1–3 are non-destructive.

1. **Communication.** `connect()`. It reads `CM` and validates the answer is 0…3. Failure messages
   distinguish "no answer" from "echo is on" from "unparseable".
2. **Read-only wrappers**, via pysweepme standalone:
   ```python
   import pysweepme
   sr = pysweepme.get_driver("Logger-Stanford_SR400", "path/to/drivers", "COM3")
   sr.set_parameters({"Count time in s": 1.0, "Counter A input": "10 MHz"})
   sr.connect(); sr.initialize()
   print(sr.get_counting_mode(), sr.get_counter_input("A"))
   print(sr.get_counter_preset("T"), sr.get_dwell_time(), sr.get_trigger_level())
   print(sr.get_status_byte(), sr.get_secondary_status_byte())
   ```
   This is where the two remaining format assumptions get confirmed — see §7.1.
3. **Host latency, before timing anything.** Click `report_com_port_latency` (§8) and write the
   number down. Everything in §6.2 is unreliable until you know it, and if it reads 16 ms then
   fixing that is worth more than any other change you can make. Re-run step 6 below with and
   without `Fast readout` once you have it, and use *your* numbers rather than the table's.
4. **Configuration.** `configure()`, then verify on the front panel that COUNT, A/B/T inputs,
   T SET, N PERIODS, DWELL, TRIG LVL, disc levels and gate values match what you asked for. Then
   check `get_status_byte()` returns 0 (no command error from any of the ~25 setup commands).
5. **The 10 MHz self-test.** `Counter A input = 10 MHz`, count time 1 s, gate A CW, one point.
   Expect exactly 10 000 000 counts and Rate A = 1.0e7. Any other number means the preset
   arithmetic or the buffer read is wrong; stop and investigate before trusting real data.
6. **Timing sanity.** Repeat with count time 0.1 s → 1 000 000 counts, and 0.01 s → 100 000.
   Then ask for 3.4 ms and confirm the reported `Count time` comes back as 3 ms (gotcha 3).
7. **Real signal.** `Counter A input = INPUT 1`, gate A CW, discriminator A slope matching your
   pulse polarity (negative NIM pulses → `Fall`), level around −10 mV. Step the discriminator level
   from −0.3 V to 0 V across several runs — you should see a plateau (the discriminator curve). If
   counts are zero everywhere, the slope is wrong.
8. **Gates.** `Gate A mode = Fixed`, width ≈ your expected signal duration, then step
   `Gate A delay in s` across the trigger period. You should recover the time profile of the
   signal. Watch for the rate-error message near the end of the range (gotcha 8). One delay per
   run until §7.3 is settled.
9. **Multi-period.** `Measurement mode = Scan of N periods`, `Periods per point = 10`. Counts
   should scale ×10 and `Count time` ×10. Then repeat with `Fast readout` on and confirm the
   numbers are unchanged and the point is faster.
10. **EXTERNAL dwell.** `Measurement mode = Scan of N periods`, `Dwell time in s = 0`,
    `Periods per point = 3`. Confirm three `CS` are sent and the point completes.
11. **Failure behaviour.** Unplug the interface cable mid-run. The driver must raise, not return
    zeros. Then set `Counter T input = TRIG` with no trigger connected and confirm it times out with
    the "did not finish the count periods" message after roughly `Timeout in s`.
12. **Safety/idle.** After the run, confirm `unconfigure()` left the counters reset and the front
    panel unlocked. PORT levels are deliberately **left as set** — the driver does not zero analog
    outputs that may be driving your experiment.

---

## 6. Throughput and buffering

In §6 of [`docs/REFERENCE.md`](../docs/REFERENCE.md): what the SR400 buffers (6.1), the per-point rate with this driver,
derived from bit times (6.2), and the fast paths the driver leaves off by default (6.3). In
short: the driver zeroes the SR400's per-character `WAIT` itself (gotcha 1); on RS-232 through
an FTDI adapter the latency timer costs more than the baud rate (gotcha 15, §8); and `Fast
readout` is opt-in (gotcha 16). Fixing the latency timer is worth more than enabling it. On GPIB
neither applies.

---

## 7. Open items

In §7 of [`docs/REFERENCE.md`](../docs/REFERENCE.md):

- **7.1 Remaining assumptions** about response formats, which the tier 1 report settles.
- **7.2 Settled: what a multi-value acquisition returns** — one row of *N* columns per
  counter, the mode picking the reduction.
- **7.3 Gate-delay scanning**: the implementation spec. It is the one real functional gap.

---

## 8. Actions

SweepMe! renders `Device.actions` as buttons. The two latency actions are **host-side only and
send the SR400 nothing at all**, so either is safe to click at any time, including in the middle
of a run. The self-test actions reprogram the instrument and refuse while it is counting. No
action can raise; a failure is reported as text.

**On SweepMe! 1.5.7.9 the self-test actions cannot reach the instrument.** Started from a control
widget outside a run, they ran on a driver instance with neither a port name nor an open port, and
refused (measured 2026-11-10). Use the end-of-run tests in §9.0 instead. The action buttons are
kept for SweepMe! versions that hand an action the run's port.

| Action | Does |
|---|---|
| `report_com_port_latency` | Reads the selected COM port's USB-serial latency timer and reports it with the estimated per-point cost for the *current* GUI settings. Read-only. Says "select a port first" rather than failing when no port is chosen, and says the setting does not apply on GPIB. |
| `run_self_test` | Tier 1 of the hardware self-test: everything checkable with no cabling changes. See §9. |
| `run_self_test_loopback` | Tier 2: needs one BNC cable. See §9. |
| `run_threshold_scan_dark` | Discriminator threshold scan on a covered R8486: the lowest usable level. See §9.7. |
| `run_threshold_scan_light` | Threshold scan under gentle, steady light: the upper bound and the optimum. See §9.7. |
| `reduce_com_port_latency` | Tries to set the timer to 1 ms. On Linux it writes sysfs, which takes effect immediately. On Windows it attempts the registry write and, if that is refused for want of administrator rights, writes a `.reg` file into the SweepMe! TEMP folder and tells you the path — run it as administrator, then replug the adapter. |

Why the `.reg` file instead of just writing the key: the measurement path must never require
elevation, or the driver is unusable on a shared lab machine. The action does the diagnosis and
produces the exact remedy without demanding privileges it should not have, and it never half-
succeeds silently. See gotcha 15 for the platform, privilege, replug and persistence caveats — all
four matter, and omitting any one of them generates a bug report.

The driver never touches the latency timer on its own, and never enables `Fast readout` on its
own. Both are absent behaviours on purpose. Nor does it ever run a self-test on its own: the
self-tests reprogram the instrument, so they only ever run when an end-of-run test is ticked or
an action is clicked.

---

## 9. Self-tests and threshold scans

### 9.0 Running them: the end-of-run tests

Under **End-of-run tests** in the Logger module there are five checkboxes, all unticked by default:

| Checkbox | Runs | Physical setup it needs |
|---|---|---|
| `Self-test tier 1 (no cabling)` | §9.3 | none |
| `Self-test tier 2 (A DISC to INPUT 2 cable)` | §9.4 | the loopback cable |
| `Dark settling check (PMT covered)` | §9.8 | PMT covered |
| `Dark threshold scan (PMT covered)` | §9.7 | PMT covered |
| `Light threshold scan (steady light)` | §9.7 | gentle, steady light |

Each test needs its own physical setup, so in practice you make the setup, tick that one test,
and start a short sequence (one point is enough). The run measures as usual. Then the ticked
tests run once, in the order of the table, in `deinitialize()`. By then `connect()` has opened
the port and asserted REN, and `unconfigure()` has left the SR400 idle. The scans first show
their blocking prompt, and each test ends with its summary message and report path. A failing
test is reported in that message and does not raise.

- **Stop** skips the tests, and a stop during a test ends it quietly.
- The dark scan's result is kept for the rest of the SweepMe! session, for the same port, so the
  light scan finds it even though it runs in a separate run.
- **Untick the test afterwards.** The checkboxes are saved with the sequence, so a test left
  ticked runs again at the end of the next run. On the real tube the dark scan takes 10–11
  minutes, and the light scan about 5 at ~40,000 counts/s.

This is the route that works on every SweepMe! version, because the test runs on the run's own
port. On SweepMe! 1.5.7.9 it is the only route: see §8 for why the action buttons fail there.
The same tests are also exposed as actions, for versions that hand an action the run's port.

### 9.2 Safety

An action can be clicked at any moment, including mid-run, so every test, however it is started,
keeps these rules:

- **Refuse while the instrument is counting.** Checked against the instrument (`SI` bit 2), not
  against driver state, because that is the condition where interfering actually destroys data.
  Also refuses while a run is being stopped.
- **Save and restore every setting they touch**, by querying it first and restoring in a `finally`.
  **No storage slot is used**: `ST` would clobber one of the user's nine setup slots and `RC 0` is
  destructive, so neither is ever sent. The report says so explicitly.
- **Never send `SE`.** Reprogramming the RS-232 terminator mid-test can break communication with no
  way back, so the terminator is read-only as far as the self-test is concerned.
- **Leave PORT1/PORT2 alone**, except in tier 2. They may be driving apparatus. Tier 2 drives
  PORT1 only if cable 2 is present, and restores it.
- **Never raise.** A failure is reported as message text.

Progress arrives as one `message_info` per section; the end is a `message_box` with pass/fail counts
and the report path.

### 9.3 Tier 1 — no cabling changes

Eleven sections, from the manual's own known-answer test (10 MHz for 1 s must read exactly
10 000 000; if not, the run aborts) through the raw response formats, the one-significant-digit
rule, chained queries, status-byte semantics, the buffer threshold, the scan machinery,
EXTERNAL dwell, measured throughput and interface gating. Its report is what retires §7.1.
Counter B cannot be tested without a cable, which is why tier 2 exists. The table of what each
section settles is §9.3 of [`docs/REFERENCE.md`](../docs/REFERENCE.md).

### 9.4 Tier 2 — one core cable

```
  CABLE 1 (required)         A DISC out  ──BNC──>  SIGNAL INPUT 2
  CABLE 2 (optional)         PORT1 out   ──BNC──>  INHIBIT in
  CABLE 3 (optional)         DWELL out   ──BNC──>  TRIGGER in
```

Cable 1 gives counters B and T an exact, known pulse train, and is all tier 2 needs. It checks
counter B, both discriminators, and the `A-B`, `A+B` and `A for B preset` modes. Cable 2 shows the
PORT1 D/A really swings; cable 3 gives a real trigger and a gate-width calibration. If cable 1
is missing, tier 2 names the two BNCs to join and stops without changing anything. Why each
cable is safe, and what it settles: §9.4 of [`docs/REFERENCE.md`](../docs/REFERENCE.md).

### 9.6 The report

Every self-test and threshold scan writes a timestamped text file to SweepMe!'s device-data
folder, in a subfolder named after the driver:

```
C:\Users\Public\Documents\SweepMe!\DataDevices\Logger-Stanford_SR400\
    SR400_self_test_tier_1_<timestamp>.txt
    SR400_self_test_tier_2_loopback_<timestamp>.txt
    SR400_threshold_scan_dark_<timestamp>.txt    .csv    .svg
    SR400_threshold_scan_light_<timestamp>.txt   .csv    .svg
    SR400_test_log.csv                           one row per test, appended
```

**`SR400_test_log.csv` is the running log across all of them.** Each test appends one row: when,
which test, PASS/FAIL/ABORTED, the headline, the pass count, the port, the first failure and the
path of the full report. The threshold scans also fill their numbers in, in volts and signed as
typed into *Discriminator A level in V* (−6.4 mV is `-0.0064`):

| Column | Filled by | Meaning |
|---|---|---|
| `recommended_disc_A_level_V` | light scan | the recommended operating threshold |
| `photons_counted_at_recommended` | light scan | fraction of photons counted there, against the reference level |
| `upper_bound_1pct_loss_V` | light scan | the level at which 1 % of photons are lost |
| `lower_bound_V` | dark scan | noise edge + 0.5 mV: go no lower than this |
| `dark_counts_vanish_V` | dark scan | where dark counts stop. Not a good operating point (§9.7) |

A column is blank when that test does not produce the number, or refused to. A log that cannot
be written never costs the report, and the final message says so.

That is `get_folder("DATADEVICES")`: public, persistent, and findable on a remote machine without
knowing which user ran SweepMe!. It is deliberately not `get_folder("TEMP")`, which SweepMe! uses
as scratch space for the current measurement (`AppData\Local\SweepMe!\temp`) — hidden, and not
somewhere a deliverable should live. TEMP is only the fallback if DataDevices cannot be written.
The closing message box gives the exact path either way, and if neither location works it says
why for each rather than just that it failed.

Each report carries the port string, the interface, pass/fail per check, and the raw tables: the
response-format table for tier 1, and the full counts-and-live-time tables for the scans.

**The threshold scans also write a CSV and a plot**, with the same stem in the same folder, so an
operator can choose the threshold by eye rather than take the recommendation on trust:

- **`.csv`** holds the raw record only: counts and live time per threshold, plus repeat and
  direction for the light scan. Rates, edges, the valley and the recommendation are all derived
  on load, so nothing in a figure can disagree with its record. The light CSV names the dark CSV
  it was scored against.
- **`.svg`** is the figure. It is plain SVG, which any web browser opens. SweepMe! 1.5.8 does
  bundle matplotlib (`libs\matplotlib`), but a plain pysweepme environment does not, and the
  figure has to open on whatever machine the report is sent to, SweepMe! or not. SVG needs no
  library to draw and nothing but a browser to view. A plotting failure never costs the data: the
  CSV is written first, and the report says why if the plot was not.

Any figure can be regenerated from its CSV on any machine with Python and nothing installed.
Put the dark CSV beside the light one and the S/√B panel comes back too:

```bash
python selftest.py plot SR400_threshold_scan_light_<timestamp>.csv
```

What the figures show. **Dark:** (a) rate above each threshold on a log axis with Poisson error
bars. Zero-count thresholds are drawn as 95 % upper limits, not as zeros. The noise edge, the
lower bound, and where dark counts vanish are marked, and so is the >1 Mcps region, which is
labelled noise or pickup. (b) Live time per threshold, showing which points reached the count
target and which hit the time cap. **Light:** (a) every pass, so drift and hysteresis are visible
rather than averaged away. (b) The same data normalised and zoomed, because a 1–5 % knee is
invisible on a log axis, with the loss levels and the recommended level. (c) The pulse-height
density with the valley and single-PE peak. (d) S/√B relative to its best, with the
within-5 % band and the levels below the valley shaded "not scored", or **NOT SHOWN** with the
reason when there is no dark scan.

The figures refuse what the data cannot support. An invalid dark scan is plotted, labelled
INVALID, and offers **no lower bound**; its noise edge is marked as a diagnostic only. Under drift
the light figure says NO RECOMMENDATION and labels its loss levels unreliable. Headlines are sized
from their content, so a long refusal pushes the panels down instead of overprinting them.

### 9.7 Threshold scans

> **Choosing a threshold for the first time?** Read
> [`docs/THRESHOLD_SCAN_GUIDE.md`](../docs/THRESHOLD_SCAN_GUIDE.md): setup, each scan, every
> panel of the figures with example figures, and how to enter the result.

Two end-of-run tests for the **R8486 on SIGNAL INPUT 1** (counter A, discriminator A, slope
FALL, gates CW). The **dark scan** (`Dark threshold scan (PMT covered)`) finds the noise edge
and the lowest usable level. The **light scan** (`Light threshold scan (steady light)`), three
up and down passes under gentle steady light, finds where photons start to be lost, and, scored
against the dark scan, recommends the level maximising S/√B. Each shows a blocking prompt
first, checks its condition in the data, and writes a report, CSV and figure (§9.6). The dark
scan keeps its fine grid up to 10 mV, then coarsens and stops in the quiet tail: 10–11 minutes on
the real tube. The light scan's S/√B uses a fitted dark background and scores only from the valley
up. The grid, the sampling rules, the analysis and its provisional constants are §9.7 of [`docs/REFERENCE.md`](../docs/REFERENCE.md).

### 9.8 Dark settling, and comparing PMT high voltages

`PMT high voltage in V (record only, 0 = not recorded)` is a record, not a setting: it goes into
every report, CSV and figure, and a light scan is only scored against a dark scan with the same
recorded HV. **Fill it in for every scan.** At 0 the HV is "not recorded", and `hv-compare` cannot
use the scan. The `Dark settling check (PMT covered)` counts at your operating threshold until
the dark rate stops drifting, and `python selftest.py hv-compare <folder>` compares the scans
taken at several voltages. The procedure is §10 of the
[guide](../docs/THRESHOLD_SCAN_GUIDE.md); how the check and the comparison work is §9.8 of
[`docs/REFERENCE.md`](../docs/REFERENCE.md).
