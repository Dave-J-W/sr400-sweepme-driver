# SweepMe! driver — Stanford Research Systems SR400 photon counter

Module: **Logger** · Interfaces: **RS-232 (COM)** and **GPIB** · Files: `main.py`, `README.md`,
`license.txt`, `tests/test_sr400_virtual.py`

Every command this driver sends is documented in the SR400 manual, chapter *Remote Programming –
Detailed Command List* (manual pp. 37–47). Nothing is inferred from generic SCPI conventions; the
SR400 predates IEEE-488.2 and has **no `*IDN?`, `*RST` or `*CLS`**.

---

## 1. Quick start

1. **On the instrument (front panel, COM menu):**
   - RS-232: set `BAUD`, `BITS`, `PARITY` to match your port (driver defaults: 9600, 8, none)
     and set **`RS-232 ECHO = OFF`**.
   - GPIB: set `GPIB ADDR` to something in 1…30.
2. Copy the whole `Logger-Stanford_SR400` folder into your SweepMe! device-class directory.
3. Add a **Logger** module, pick the SR400, choose the port.
4. Minimum sanity configuration: `Counter A input = 10 MHz`, `Count time in s = 1`,
   `Gate A mode = CW`. One measurement point must return
   **Counter A = 10 000 000** and **Rate A = 1.0e7**. If that number is exact, the preset
   arithmetic, the status polling and the buffer read are all working.
5. Then switch `Counter A input` to `INPUT 1`, connect your PMT, and set the discriminator level.

### Why the *Logger* module

Every setting goes to the instrument once, in `configure()`; a measurement point is then just an
acquisition — `measure()` followed by `call()`. That is Logger semantics, and it is what the
folder-name prefix selects. There is no `apply()` and no `SweepMode`: the Logger module does not
render a sweep field, so an `apply()` here would be code that SweepMe! never calls.

**Sweeping a gate delay is therefore not yet wired up.** The SR400's characteristic experiment is
a gate-delay scan, and this driver can currently only sit at one gate delay per run. The intended
route is the instrument's own scan machinery rather than a SweepMe! sweep: `Gate A mode = Scan`
plus `GY` (delay step), `DT` (dwell) and `NP` (number of points) make the SR400 step its own gate
and fill the scan buffer, which `EA` then dumps in one transfer. Every one of those commands is
already implemented and round-trip tested below — what is missing is the decision about how to
present a whole scan through `call()`, which returns one row per point. See §7.3, and §7.2 for the decision it shares with auto-split.

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
| `Print SweepMe! phase` | — | Debug aid. Prints the name of each semantic function as SweepMe! calls it (`connect`, `initialize`, `configure`, `measure`, `call`, `unconfigure`) to the SweepMe! debug console. Off by default and silent when off. |

All of these are applied once, in `configure()`. To vary one of them across a run you currently
have to change it in the GUI and start a new run — see "Why the *Logger* module" above and §7.3.

---

## 4. Gotchas

These are the things that cost time if you do not know them. Most are instrument quirks, not driver
quirks; the driver handles them, but you should know they exist.

### 1. `RS-232 WAIT` defaults to 6 — that is 20 ms per character

The SR400 inserts `WAIT × 3.3 ms` between *every character it sends*. At the factory default of 6,
a nine-digit count value takes ~180 ms to arrive regardless of baud rate. The driver sends `SW 0`
in `initialize()` on every RS-232 connection, which is what the manual itself recommends. **If you
talk to the instrument with anything other than this driver, send `SW 0` first**, or you will
conclude the SR400 is broken when it is merely polite.

### 2. `RS-232 ECHO` must be OFF

With echo ON the SR400 sends the command back plus `OK>` / `??>` prompts, and uses `CR LF` instead
of `CR` as its terminator. Every read then returns garbage. There is **no remote command to turn
echo off** — it is a front-panel-only setting. `connect()` detects the condition and says so
explicitly rather than failing with a parse error.

### 3. Presets and the dwell time keep only ONE significant digit

`CP` and `DT` silently truncate. The manual is explicit: `CP2,10`, `CP2,1E1`, `CP2,0.1E2` and
`CP2,12` **all** set T SET to `1E1`.

There are exactly **108** settable presets — `d × 10ᵏ` for d ∈ 1…9, k ∈ 0…11, spanning 1 count to
9E11 (25 hours). So the settable count *periods* are those 108 values over 10 MHz: 1, 2, 3 … 9 ms,
then 10, 20, 30 … 90 ms, and so on.

Two claims follow, and they are easy to conflate:

**(a) There is no 1.5 s count period.** Nor 250 ms, nor 15 ms. In `Count time mode = Per period`
the driver rounds to the *nearest* settable value (the instrument would truncate), sends an
unambiguous `2E4`-style string, reads the applied value back, and reports the **real** count time
in the `Count time` variable. Ask for 3.4 ms and you get 3 ms, plus a message saying so.

**(b) 1.5 s of total counting is available.** *N* periods of a settable length reach an exact
total live time, because the quantisation constrains one period, not the experiment:

| Split of 1.5 s | Live time | Wall time (2 ms dwell) | Duty |
|---|---|---|---|
| 3 × 0.5 s | 1.5 s | 1.504 s | 99.73 % |
| 5 × 0.3 s | 1.5 s | 1.508 s | 99.47 % |
| 15 × 0.1 s | 1.5 s | 1.528 s | 98.17 % |

Set `Count time mode` to **`Total live time (auto-split)`** and `Count time in s` to 1.5, and the
driver picks the first row: it prefers the exact split with the **fewest** periods, which is also
the one with the highest duty cycle, so one preference covers both. It reports the plan once, and
it computes `Periods per point` rather than reading it. A multi-period plan needs the instrument to
run a scan, so `Measurement mode` is promoted to `Scan of N periods` and the message says so.

**Live time is crystal-accurate; wall time is not the same thing.** The count period is a whole
number of 10 MHz cycles and the timebase is specified at **25 ppm from 0 to 50 °C** (manual p. 5),
so *N* periods of *t* is exactly *N × t* of counting to 25 ppm no matter how it is split.
Splitting costs wall clock, not accuracy: the run takes `(N−1) × dwell` longer than it counts. The
manual notes the internal dwell "may have 200 ns of indeterminacy" — that is in the **dead** time
between periods, so it never touches the live time or the counts.

**The duty floor is 80 % by default, and there is a tick box for 99 %.** Duty is
`live / (live + dead)` — how much of the wall clock was actually spent counting. At 80 % most
people never think about it: type 1.6 s, get 2 × 0.8 s, exact, 99.9 % duty. Tick
**`Quantize count time to >99% duty cycle`** when the dead time itself matters — a drifting
source, or anything where a 20 % longer wall clock changes the answer.

Tightening the floor can only cost accuracy, never add it, because fewer periods means a coarser
total. The driver plans **both** floors in one pass and tells you what the other would have given,
so the tick box is a decision rather than a guess:

> auto-split — 3 × 0.05 s = 0.15 s of live counting, exactly the requested total. 97.4 % duty …
> Duty floor 80 %. At the 99 % floor it would instead be 1 × 0.2 s (0.2 s, 100.0 % duty).

and with the box ticked, the same request reports the reverse:

> auto-split — 1 × 0.2 s = 0.2 s of live counting, the closest reachable total (0.2 s requested
> 0.15 s) … Duty floor 99 %. At the 80 % floor it would instead be 3 × 0.05 s (exact, 97.4 % duty).

**Auto-split refuses unless a preset is a time.** It needs `Counter T input = 10 MHz` and a
counting mode other than `A for B preset`. Anywhere else the T preset counts *events*, not clock
cycles, so there is no total live time to divide up and the request is meaningless rather than
merely awkward — `configure()` raises and names both remedies. `Per period` mode still works
normally in those configurations, via `Preset counts (T or B)`.

**Below roughly 20 ms of total, do not split.** The 2 ms minimum dwell is then a large fraction of
each period, and the duty floor will refuse most splits and hand back a single rounded period
instead — which is the right answer. Worked examples at the 80 % default: 15 ms → 2 × 8 ms
(88.9 % duty, *not* the exact 3 × 5 ms, which is only 78.9 %); 3.4 ms → 1 × 3 ms, *not* the exact
17 × 0.2 ms, which would be 9.6 %. In
`Per period` mode the rounding warning names the exact decomposition inline when a usable one
exists, so you do not have to work it out or find this section:

> 1.5 s is not a settable count period, so it was rounded to 2 s — the T preset keeps only one
> significant digit. 1.5 s is reachable exactly as 3 count periods of 0.5 s: set `Count time in s`
> to 0.5, `Periods per point` to 3 and `Measurement mode` to `Scan of N periods` — or just set
> `Count time mode` to `Total live time (auto-split)` and let the driver do it.

**If you step `Count time in s` across runs** in `Per period` mode, the reachable values are
logarithmically spaced, not linear; use explicit `d × 10ᵏ` values. In auto-split mode any total is
accepted and you get the closest reachable one, labelled exact or not.

### 4. Gate delay and width have variable resolution

Resolution is 1 ns below 1 µs and 1 part in ~1000 above it, in bands (mantissa 1000–2048 → step 1,
2048–4096 → step 2, 4096–8192 → step 4, 8192–9992 → step 8 in the 4th digit). Near 10 µs the
allowed values are 9.984, 9.992, 10.00, 10.01 µs … The SR400 rounds to the nearest allowed value
itself, so a fine gate-delay sweep will contain **repeated x-values** in the middle of a band. If
you need the actually-applied delay, read it back with `get_gate_delay("A")` (`GD i`) or, during an
instrument-internal scan, `get_gate_scan_delay("A")` (`GZ i`).

### 5. Do not reset the instrument casually

`CL` restores the default setup **and** clears the SRQ mask **and** resets the RS-232 terminator
sequence **and** clears the communication buffers. It is off by default (per the handoff's rule
about destructive resets interfering with other modules sharing the instrument). Turn it on once if
a previous program left the terminator changed via `SE` — that is the one failure mode a normal
reconnect cannot fix, because the driver's `EOL` no longer matches what the instrument sends.
`CL` must be alone on its command line, which the driver guarantees.

### 6. Status bits are destructive reads, and that is load-bearing

Reading `SS` returns the byte **and clears it**; reading `SS j` clears bit *j*. So a naive
"poll bit 1, then check bit 7" loses errors. The driver reads the whole byte and **OR-accumulates**
every byte received during a wait, so no error bit is dropped while polling. It also reads and
checks the byte *before* starting each count, which is how a command error left over from
`configure()` gets reported instead of silently discarded.

Bits: 0 front-panel parameter changed · 1 data ready · 2 scan finished · 3 counter overrun ·
4 rate error · 5 recall error · 6 SRQ · 7 command error.

### 7. Counter overrun means your data is wrong, not just large

Counters hold 10⁹ counts. Bit 3 fires at 1E9−1 and the driver **raises**, because a wrapped counter
returns a plausible-looking wrong number. At 200 MHz input that is 5 s of counting; at 1 MHz, 1000 s.
Reduce the count time or attenuate.

### 8. A rate error is a physics warning, not a comms error

Bit 4 fires when a gate is missed — the gate delay or width exceeds the trigger period minus 1 µs
(max trigger rate is 1 MHz). The driver reports it as a message and keeps the data, because the data
is real, just collected over fewer gates than you think. **This silently breaks normalisation** in a
gate-delay sweep: as the delay grows past the trigger period, you lose gates and the counts drop for
a reason that has nothing to do with your sample. Watch for the message.

### 9. `A for B preset` mode returns −1 for counter B

In that mode B is the preset counter, so `QB` returns −1 by design. The driver reports Counter B,
Rate B **and** Count time as `NaN`, because the count period length is now determined by the signal
and is genuinely unknown. `EB` and `ET` also error out in this mode.

### 10. Changing gate parameters while counting corrupts data

The manual: "It is recommended that the counters be paused before changing gate values." All gate
programming happens in `configure()`, and `configure()` ends with `CR`; `measure()` then opens with
`CR` of its own. This also satisfies the stricter rule that *start values of scanned parameters may
only be adjusted when the counters are in reset*.

### 11. A gate delay in CW mode does nothing

In CW the gate is continuously open and the delay line is inactive, so `Gate A/B delay in s` is
accepted by the instrument and then ignored. The driver reports this as a **message, not an
error** — the configuration counts perfectly well, the delay just has no effect. It says the same
about a `Discriminator T level` while counter T is on the 10 MHz timebase. Both checks live in
`_check_configuration()` and fire only when the setting differs from its default, so a normal run
stays quiet.

### 12. Interface-specific commands

`MI` (front panel lock), `SW` (wait interval) and `SE` (terminator) are **RS-232 only**. `SV`
(SRQ mask) is **GPIB only**. The driver skips or rejects them depending on the port in use — a
`Lock front panel = True` on a GPIB port is silently a no-op (use REN/LLO/GTL from your controller
instead).

### 13. Cabling: the SR400 is a DCE

It connects **straight-through** to a PC/terminal (which is a DTE). Connecting it to another DCE
needs a null-modem cable. It also waits for CTS before transmitting, so an adapter that does not
pass CTS will make the instrument appear mute. The manual's own advice: if the first command after
power-up fails, send a few bare carriage returns to flush both UARTs.

---

### 14. A knob turned mid-run silently invalidates the configuration

Status bit 0 means a parameter was changed from the front panel. The driver reports it as a
message, because it cannot undo it and the counts themselves are still valid — but the instrument
is no longer necessarily in the state `configure()` left it in, so anything you infer from the GUI
settings may now be wrong. Enable `Lock front panel` (RS-232 only) for unattended runs.

---

### 15. The USB-serial latency timer costs more than the baud rate

Not an SR400 quirk at all — a host one, and the most common reason a working SR400 feels broken.

An FTDI or Prolific USB-serial adapter does not deliver a short inbound packet immediately. It
holds it until its **latency timer** expires. The Windows default is **16 ms**. This driver makes
several *read* round trips per measurement point, and the timer is charged per read transaction,
not per byte — so at the default it costs tens of ms per point. That is more than the actual bit
time at 19200 baud, and more than doubling the baud rate would win back.

`connect()` reads the timer and warns **once** if it is above 4 ms. Two actions (§8) report it and
try to change it. What the warning tells you, and why each part matters:

- **FTDI-based adapters only.** A native RS-232 port and most non-FTDI adapters have no such
  setting, and the driver then reports the value as *unknown* — never as *fine*.
- **RS-232 only.** GPIB has no equivalent and is never checked.
- **Windows needs administrator rights** to write it, which is why the action generates a `.reg`
  file rather than demanding elevation. Linux sysfs writes usually succeed for the owning user.
- **Windows needs a replug** (or a reboot) before the new value takes effect. Skipping this is the
  reason people report that changing it "did not work".
- **The setting is global to that adapter and persists** after SweepMe! closes. Changing it on a
  shared machine changes it for everyone and everything using that adapter.

The driver never changes it on its own. Nothing happens without an explicit action click.

### 16. Batched queries: the manual argues with itself, so this is opt-in

The SR400 accepts several commands on one line separated by `;`, **including queries**, and answers
each in order. The manual's own example is `CM;CI0;GD0<cr>` → `1<cr>1<cr>1.2E-6<cr>`.

The same manual also says: *"In general, it is good programming practice to receive the response
from one query command before sending another command."*

Both statements are the manual's. This feature lives in the gap between them, which is exactly why
`Fast readout (batch queries)` is **off by default and never enabled automatically**. Do not
"simplify" the driver by flipping that default — the conservative choice is documented here so it
survives contact with a future maintainer.

Why it is worth having anyway: chained answers arrive in one USB packet, so the first read pulls
the whole packet in and later reads return with no latency wait (gotcha 15). The saving scales with
`Periods per point`, which is precisely the setting someone reaches for when they want throughput.

What the driver does to keep it safe:

- Lines are capped at 180 characters and 10 commands, both well below the 240-character
  command-line error threshold and the 256-character output buffer. Overrunning the *output*
  buffer erases every buffered value, which costs the whole scan, not one number.
- Before every batched write, the port is checked for unread bytes. Stale bytes are the one
  corruption that counting answers cannot catch — you get the right *number* of answers, shifted
  by one, and every value is silently wrong. If any are found the driver drains and refuses.
- On any batched failure it resynchronises (drain, then a validated `CM` — **never** `CL`, which
  would wipe the user's setup mid-run), re-reads the point one query at a time, tells you, and
  disables fast readout for the rest of the run.
- Configuration and status polling are **never** batched. Writes do not pay the latency penalty,
  a batch discards everything after an error on the line, and the status poll must be a fresh read
  each time or the OR-accumulation in gotcha 6 breaks.

Batched and unbatched readout are asserted to return identical values on the bench for 1, 2, 10,
17 and 33 periods. If they ever diverge, that is a bug in the driver, not a tuning knob.

---

## 5. Test procedures

### 5.1 Virtual bench (no hardware needed)

`test_sr400_virtual.py` implements a simulator of the SR400 protocol behind the pysweepme port
interface and runs the full driver lifecycle against it — 90 assertions over 15 scenarios: single
point, multi-period summing, EXTERNAL dwell, gate/discriminator/PORT/count-time sweeps, `A for B
preset`, eleven range rejections, command-error and overrun handling, timeout, echo detection,
wrapper round-trips, the GPIB path, and `CL`.

```bash
pip install pysweepme
python tests/test_sr400_virtual.py   # expect "348/348 checks passed"
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

### 6.1 What the SR400 buffers

| Buffer | Size | Behaviour |
|---|---|---|
| Command input | 256 characters | Commands processed in order received; no need to wait between them. Multiple commands per line separated by `;`, executed on the terminating CR. |
| Output | 256 characters **per interface** (RS-232 and GPIB have separate buffers) | Responses queue here. |
| Scan data | `N PERIODS` points (up to 2000) **per counter** | "All count data is internally buffered for one scan." Readable during the scan (`QA m`) or dumped afterwards (`EA`/`EB`/`ET`). **Reset at the start of every scan** — a new scan or a counter reset destroys the previous scan's data. |
| COM `DATA` window | last 254 received characters | Front-panel debug playback of what the instrument actually received. Cleared by any COM change or buffer overflow. |

Two failure modes to respect:

- Exceeding 240 characters in a communication buffer sets the **command-error bit** and flashes ERR.
- A genuine overflow shows `DATA BUFFER OVERFLOW` on the LCD for 5 s and **erases all buffered
  data**. With a 256-character output buffer that is roughly **25 queued count values** of slack —
  the relevant limit if you use the streaming `F` commands and your host falls behind.

### 6.2 Per-point rate with this driver (polled, one round trip at a time)

A single-period point costs about **47 characters** on the wire:
`CR`(3) + `SS`(3+2) + `CS`(3) + two `SS` polls(10) + `QA 1`(5+8) + `QB 1`(5+8), plus the second `CR`.
Bit time at 8N1 is 10 bits/character.

| Path | Bit time / point | Realistic total / point | Points per second |
|---|---|---|---|
| RS-232, 9600 baud, `SW 0` | ~49 ms | ~60–90 ms | ~11–17 |
| RS-232, 19200 baud, `SW 0` | ~24 ms | ~35–60 ms | ~17–28 |
| **RS-232 via USB adapter, 19200, default 16 ms latency timer** | ~24 ms | **~110–140 ms** | **~7–9** |
| RS-232 via USB adapter, 19200, latency timer set to 1 ms | ~24 ms | ~40–65 ms | ~15–25 |
| GPIB via USB controller (e.g. NI GPIB-USB-HS) | negligible | ~10–30 ms | ~30–100 |
| RS-232, 19200, `SW` left at the default 6 | ~24 ms + ~400 ms wait | ~450 ms | ~2 |

Ten periods per point, where the readout dominates and batching has something to work with
(**derived** from the read-transaction counts, using the bench's measured round-trip reduction):

| Path, `Periods per point = 10` | Read transactions | Latency cost alone | Fast readout |
|---|---|---|---|
| USB adapter, 16 ms timer, `Fast readout` off | ~25 | ~400 ms | — |
| USB adapter, 16 ms timer, `Fast readout` on | ~7 | ~112 ms | ~3.5× fewer round trips |
| USB adapter, 1 ms timer, `Fast readout` off | ~25 | ~25 ms | — |
| USB adapter, 1 ms timer, `Fast readout` on | ~7 | ~7 ms | fixing the timer matters more |

The transaction counts are **measured on the bench** (the suite asserts the reduction); the latency
products are **derived** from them and the adapter's documented default. Note the ordering: fixing
the latency timer beats enabling fast readout, and doing both is barely better than fixing the
timer alone. Reach for gotcha 15 before gotcha 16.

The "realistic total" column adds per-command instrument processing latency. **The manual does not
specify the SR400's command-processing time**, so that part is an estimate (a few ms per command for
a 1980s 8-bit micro); treat the table as an order-of-magnitude guide and measure your own setup with
step 5 below.

Three things dominate, in order:

1. **`SW` (the character wait interval).** Default 6 = 20 ms *per character sent*. This is the single
   biggest factor and the driver zeroes it automatically. Manual, "Common software problems": *use
   `SW0` at the beginning of your program to speed up transmission*.
2. **USB-serial latency timer.** An FTDI/Prolific adapter batches incoming bytes and waits for its
   latency timer (default **16 ms**) before delivering a short read. With ~5 query round trips per
   point that is ~80 ms of pure dead time. Windows: Device Manager → the COM port → Port Settings →
   Advanced → *Latency Timer* → 1 ms. This is usually the largest single improvement available for
   an RS-232 setup, larger than going from 9600 to 19200 baud.
3. **Number of round trips.** GPIB wins here not because 1 MB/s beats 19.2 kbaud (the SR400's
   firmware, not the bus, sets the byte rate) but because the per-transaction overhead is ~1 ms
   instead of ~16 ms. **If you need short count times at a high point rate, use GPIB.**

Note what is *absent* from the table: the count time itself. At 19200 baud a 1 ms count period costs
~35 ms of overhead — you spend **97 % of the experiment talking about the measurement**.

### 6.3 The fast paths, and why the driver does not use them by default

The 2 ms minimum dwell time bounds the instrument at ≤ ~500 count periods/s no matter what. To get
anywhere near that you must stop doing one round trip per period:

- **Scan, then bulk dump (`EA`/`EB`/`ET`).** Acquire N periods at the instrument's own pace
  (`N × (count time + dwell)`), then read the whole buffer with one command. 2000 points at 2 ms
  dwell + 1 ms count = ~6 s of acquisition, then ~9 chars/point × 2000 = 18 000 characters ≈ **9.4 s
  at 19200 baud** (much less on GPIB). Effective rate ~130 points/s.
- **Stream during the scan (`FA`/`FB`/`FT`).** The SR400 pushes each point as it completes. The
  manual notes the transfer is "limited only by the baud rate and the character wait interval", and
  that points accumulating faster than they can be sent are buffered. With only 256 characters of
  output buffer (~25 points) you must keep up or lose the whole scan to an overflow. Requires an
  interrupt-driven or fast host read loop.

The driver uses point-by-point `QA m`/`QB m` instead because that is the method the manual
recommends for **full handshaking**: one lost or desynchronised value in an `E`/`F` transfer corrupts
every subsequent point, whereas an addressed read is self-describing and retryable. Both fast paths
are available as wrapped functions — `dump_scan_buffer(counter, n)` and
`start_scan_with_data_transfer(counter)` — if you want to build a high-throughput variant.

**Practical guidance:** if you need more than ~20 points/s of *SweepMe!* points, the answer is not a
faster interface — it is to make one SweepMe! point a whole scan. Set `Periods per point` high and
treat the summed counts as your datum, or fork `measure()` to use `dump_scan_buffer()` and return
per-period data. Increasing `Periods per point` with the current implementation amortises the
`CR`/`SS`/`CS` overhead but still costs two queries per period, so it helps by roughly 2× rather
than 10×.

---

## 7. Open items

### 7.1 Remaining assumptions

Audited against the manual (Revision 2.7, 11/2018) — see [`docs/MANUAL_AUDIT.md`](../docs/MANUAL_AUDIT.md)
for what was checked and what changed. Every command, every numeric limit and every status bit in
this driver is now a quotation rather than an inference. Four assumptions survive. The first two
are response-format details, and both are parsed through `float()` so integers, reals and
`1E1`-style floats all work regardless; the last two are behavioural and need the bench.

1. **Scan-finished bit with `NP 1`.** The manual says bit 2 is set at the end of a scan when the
   end mode is STOP, but does not say whether a one-period scan qualifies. The driver accepts
   data-ready **or** scan-finished when `Periods per point = 1`, so either behaviour works.
2. **`TL`/`DL` response sign and decimal formatting.** Assumed `+2.000` / `-0.0100`. The manual
   specifies the *resolutions* (1 mV and 0.2 mV) and shows a `GD` response (`1.2E-6`) but no
   worked `TL` or `DL` response. Confirm during hardware step 2.
3. **How deep a chained query the firmware will answer.** The manual documents `;`-chaining, says
   the SR400 "processes the commands in the order received", and gives a three-query worked
   example — but says nothing about a ten-deep chain. This is the one genuinely new assumption
   behind `Fast readout` (gotcha 16). Compare a batched and an unbatched point during hardware
   step 9.
4. **That a gate scan steps the delay once per count period, filling the scan buffer in order
   from the start delay.** The manual describes the scan buffer in terms of count periods and
   documents `GY`/`GZ` for the delay scan, but shows no worked example tying the two together.
   §7.3 rests on it, so confirm it before trusting a scan's x-axis: run a 4-point scan and check
   the four buffer entries against four separate single-delay measurements at the same delays.

**Resolved by the audit, previously listed here:** the `CP i` response format. The manual states it
outright — *"In the above example, the string `1E1` is returned"* — so it is no longer an
assumption.

### 7.2 Settled: what a multi-value acquisition returns

**Decision: a scan returns one row with *N* columns per counter, and the mode selects the
*reduction* applied to the scan buffer — not a different acquisition architecture.**

One SweepMe! point stays one complete, self-contained SR400 scan. What changes between modes is
only what the driver does with the *N* buffer entries it already reads.

| Mode | Reduction | Columns |
|---|---|---|
| `Single count period` | none needed (*N* = 1) | fixed 5 |
| `Scan of N periods` | **sum** — repeat-and-accumulate | fixed 5 |
| `Total live time (auto-split)` | **sum** — the point of asking for 1.6 s is one number for 1.6 s | fixed 5 |
| Gate-delay scan (§7.3, not implemented) | **none** — the *N* values *are* the measurement | 5 + 2*N* |
| Per-period statistics (not wanted yet) | mean, sample std, Fano factor | fixed 5 + 3 |

#### Why this and not the alternatives

The three candidates recorded here previously were driver-stepped rows, *N* columns, and a sidecar
file. Two are now ruled out on facts rather than taste.

**Driver-stepped rows is not available to a Logger.** The idea was to step `GD` per point and let
the SweepMe! sweep loop own the x-axis. But a Logger renders no `SweepMode` field and never calls
`apply()` — that is the whole reason those were deleted. Handing SweepMe! the x-axis requires the
Switch module, which was explicitly rejected. The driver could step `GD` internally and emit the
delay as a column, but then a "point" means *1/N of a hidden acquisition*: stopping mid-run yields
a partial curve, the state is invisible, and it collides with `Periods per point` and auto-split.
Every other decision in this driver has held the line that **one point is one well-defined
acquisition**, and this would be the one that breaks it.

***N* columns is feasible, and that was the open question.** The worry was that `self.variables`
would have to be built from the GUI parameters. It can be: `Logger-LJ_ADC_DJW` in the LabJack
drivers repo does exactly that, assembling `self.variables` and `self.units` per channel inside
`parse_GUIparameter()`. Dynamic column counts are ordinary pysweepme practice on the version
SweepMe! ships, so the objection does not survive.

**The sidecar file is worse for the actual experiment.** It keeps the column count stable, but the
data leaves the SweepMe! table: no live plot, and the user has to correlate files by hand. Keep it
in reserve for *N* beyond the column cap below, not as the primary shape.

#### What this makes smaller

Recording the decision as shared by three features overstated it. Two of the three are
**reductions to a fixed column count** — the auto-split sum, and statistics, which is three
columns whatever *N* is. Neither ever needed this decision; both only needed the per-period list,
which `_read_scan_buffer()` already has because it reads `QA m`/`QB m` per period and adds them up
as it goes. Retaining the list instead of a running total is the entire data-collection change for
either, with no extra instrument traffic.

So exactly **one** feature needed an output-shape decision: the gate scan. The other two were
waiting on nothing.

#### Two sub-decisions that come with it

**The x values are columns, not column names.** A gate scan emits `Gate A delay 0…N-1` alongside
`Counter A 0…N-1`, which is why the row is 5 + 2*N* wide rather than 5 + *N*. Encoding the delay in
the column name would make the x-axis a string to be parsed, and — the real reason — the SR400
**rounds gate delays within resolution bands** (gotcha 4), so the applied delay is not reliably
`start + i × step`. The x values have to be data.

Those columns carry the *nominal* delays. Reading the applied value costs one `GZ` round trip per
point, which would throw away the single-transfer `EA` readout that makes the scan worth using.
Nominal is good to the ~0.1 % of gotcha 4; if a measurement needs better, read `GZ` per point and
accept the round trips.

**Cap the scan at 256 points.** `NP` allows 2000, but 2000 scan points is 4005 columns, which is
not a table anyone can use and not a shape SweepMe! should be asked to render. 256 points is a
generous decay curve. Above the cap, `configure()` should refuse and name the sidecar as the
option that would lift it — rather than silently producing something unusable.

### 7.3 Gate-delay scanning: what implementing it now involves

Not implemented. The output shape is settled (§7.2), so what remains is mechanical — the command
layer is already complete and round-trip tested: `GM` (scan mode), `GY` (delay step), `GZ` (read
the applied scan delay), `NP`, `DT`, `EA`/`EB` (buffer dump).

`Measurement mode` gains a third value, **`Gate delay scan`**, rather than overloading
`Scan of N periods` — so summing and not-summing never share a code path, which was the fourth
option weighed in §7.2 and is the right call for the same reason the count-time modes are separate.

What it needs:

1. **GUI**: `Gate A delay start in s`, `Gate A delay step in s`, and reuse `Periods per point` as
   the scan length *N* (that is what `NP` is in scan mode). Refuse *N* > 256, per §7.2.
2. **`configure()`**: `GM 0,2` (SCAN), `GD 0,<start>`, `GY 0,<step>`, `NP <N>`, internal dwell.
   The existing gate-CW warning in `_check_configuration()` already covers the case where someone
   selects a scan with the gate in CW mode — it needs promoting from a message to a refusal in
   this mode, because a scan with no gate is not a scan.
3. **`self.variables`**: built in `get_GUIparameter()` as
   `["Counter A i", "Gate A delay i", …] + the fixed five`, following the
   `Logger-LJ_ADC_DJW` pattern.
4. **`measure()`**: unchanged acquisition. Only the reduction differs —
   `_read_scan_buffer()` returns the per-period list instead of a sum. That is the one function
   that needs a flag, and both paths already share `_parse_scan_point()`.
5. **Readout**: prefer `EA`/`EB` (whole buffer, one transfer) over per-point `QA m`. Note `EA` may
   only be sent while paused at the end of a scan, and the driver already forces scan end mode
   STOP, so that precondition holds.
6. **Bench**: the simulator models the scan buffer and `EA` already. The test that matters is that
   a scan's *N* columns equal *N* separate single-delay measurements at the same delays.

The one thing to verify on hardware first: that a scan's buffer really does hold one entry per
gate-delay step, ordered from the start delay. The manual's scan-buffer description is about count
periods; that gate scanning steps the delay once per count period is stated but not shown in a
worked example. That belongs in §7.1 as an assumption until confirmed.

---

## 8. Actions

SweepMe! renders `Device.actions` as buttons. Both of this driver's actions are **host-side only
and send the SR400 nothing at all**, so either is safe to click at any time, including in the
middle of a run. Both are also written so they cannot raise; a failure is reported as text.

| Action | Does |
|---|---|
| `report_com_port_latency` | Reads the selected COM port's USB-serial latency timer and reports it with the estimated per-point cost for the *current* GUI settings. Read-only. Says "select a port first" rather than failing when no port is chosen, and says the setting does not apply on GPIB. |
| `reduce_com_port_latency` | Tries to set the timer to 1 ms. On Linux it writes sysfs, which takes effect immediately. On Windows it attempts the registry write and, if that is refused for want of administrator rights, writes a `.reg` file into the SweepMe! TEMP folder and tells you the path — run it as administrator, then replug the adapter. |

Why the `.reg` file instead of just writing the key: the measurement path must never require
elevation, or the driver is unusable on a shared lab machine. The action does the diagnosis and
produces the exact remedy without demanding privileges it should not have, and it never half-
succeeds silently. See gotcha 15 for the platform, privilege, replug and persistence caveats — all
four matter, and omitting any one of them generates a bug report.

The driver never touches the latency timer on its own, and never enables `Fast readout` on its
own. Both are absent behaviours on purpose.
