# SR400 driver — technical reference

> **Abstract.** The design detail behind the driver README, under the same section numbers. §4 lists
> 16 instrument gotchas, among them one-significant-digit presets, GPIB's need for REN and
> destructive status reads. §6 explains throughput: on RS-232 the FTDI latency timer costs more than
> the baud rate. §7 holds the open items, including the gate-delay scanning spec. §9 explains how
> each self-test and scan works: the grids, the dark scan's adaptive sampling and 10 mV floor, the
> fitted dark background, why levels below the valley are not scored, the recommendation (the middle
> of the band within 5 % of the best S/√B), the settling check and the HV comparison. Constants
> tuned on the two real dark scans of one tube are marked provisional.

The design detail behind [`Logger-Stanford_SR400/README.md`](../Logger-Stanford_SR400/README.md),
the operator's reference. **Both files share one section numbering**: §1–3, §5, §8 and §9.0,
§9.2 and §9.6 are in the driver README; §4, §6, §7 and the detail of §9 are here. A "§" in either
file, or in a message from the driver ("gotcha 16", "README section 7.1"), means that shared
numbering.

New to the discriminator threshold? Start with [THRESHOLD_SCAN_GUIDE.md](THRESHOLD_SCAN_GUIDE.md)
instead; §9.7 here is the reference behind it.

Every command the driver sends is documented in the SR400 manual, chapter *Remote Programming –
Detailed Command List* (manual pp. 37–47), and audited against it: [MANUAL_AUDIT.md](MANUAL_AUDIT.md).

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

**GPIB needs REN, and must not be device-cleared.** Two lines in the manual's GPIB capabilities
section decide whether GPIB works at all:

- *"The SR400 will respond to commands only if it is addressed to listen and the Remote Enable
  line (REN) is asserted."* Without REN, a query is accepted at the handshake level and then never
  answered, so the read times out with nothing received. **Measured** on 2026-11-10 with an NI
  GPIB-USB-HS: REN was still off after an interface clear even with *Assert REN when SC* ticked in
  NI MAX, and `CM` timed out with 0 bytes. With REN asserted by hand it answered `3<cr><lf>`.
  `connect()` therefore asserts REN and addresses the SR400 itself, through VISA's
  `control_ren(VI_GPIB_REN_ASSERT_ADDRESS)`, before its first command. The REM LED lights once the
  SR400 is in remote.
- DCL and SDC are both answered *"Same as CL command"*, which resets the whole setup. pysweepme clears
  every port right after opening it, and on GPIB that clear is an SDC. Nothing restores the setup
  afterwards. So the driver sets `port_properties["clear"]` off for **every** port type, from
  `__init__` onwards, which also covers a port opened for an action before the GUI parameters
  arrive. On COM, where the clear would only have flushed the serial buffers, `connect()` discards
  stale input itself: it reads only the bytes already waiting and changes no setting. The
  deliberate reset is still available as *Reset instrument at start*, after which `configure()`
  applies the GUI settings again.

If GPIB still fails, NI's **GPIB Interactive Control** (ibic) will test the bus without
SweepMe!: `ibsic`, `ibsre 1`, `ibdev 0 23 0 13 1 0`, `ibwrt "CM\r"`, `ibrd 100`. Use your own
address in place of 23. **Never use `ibclr`**, because it is a device clear and resets the SR400.
Close ibic before you start SweepMe!.

If `iblines` shows **NRFD** asserted after `ibsic` (`ATN REN NRFD NDAC` rather than
`ATN REN NDAC`), the SR400's GPIB input has stopped accepting data, and every write times out
with 0 bytes sent. **Measured** on 2026-11-10, after a series of ibic sessions: REM was lit, ERR
was off, the display and knob still responded, the port had vanished from SweepMe!'s port list,
and only a power cycle cleared it. The cause was not identified.

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

Audited against the manual (Revision 2.7, 11/2018) — see [`docs/MANUAL_AUDIT.md`](MANUAL_AUDIT.md)
for what was checked and what changed. **All four are retired by running `run_self_test` (§9)**:
section 2 of its report is the raw response-format table, and sections 4 and 8 settle the
behavioural two. That report is the artefact that closes this list out. Every command, every numeric limit and every status bit in
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

## 9. Self-tests and threshold scans: how they work

### Why the self-tests exist

The virtual bench proves the driver's *logic* against a simulator built from the same manual the
driver was written from. It cannot prove anything about a real instrument: response formats, real
latency, or any electrical behaviour. §7.1 lists exactly those assumptions. These two actions are
how they get closed out, and **the report file is the deliverable** — it is what retires §7.1 and
what to attach to a bug report.

Both work over RS-232 or GPIB.

### 9.1 Why two actions rather than one with a prompt

An action takes no arguments, and `message_box` cannot return an answer. So there is no way to ask
"is the loopback cable connected?" and branch on the reply. Consent to the loopback tier is
expressed by **clicking `run_self_test_loopback`**; declining it is not clicking it. A
prompt-and-branch design cannot work here, so it was not attempted.

Tier 2 does not ask about cabling either — it **probes**. A count of zero on INPUT 2 is a more
reliable answer than a human confirmation, and if the cable is absent the action names the two BNCs
to join and stops without touching anything else.

### 9.3 Tier 1 — no cabling changes

| # | Section | Settles |
|---|---|---|
| 1 | **Known answer** — 10 MHz for 1 s must read exactly 10000000 (the manual's own test, p. 33) | If this fails the run **aborts**: the preset arithmetic, status polling and buffer read are all suspect, so nothing below it means anything |
| 2 | **Response formats** — the RAW string from ~50 getters, verbatim, before any `float()` | §7.1 items 1–2. Whether `CP 2` answers `1E1` or `10`, what `TL`'s sign and decimals look like, and every other format currently *assumed* |
| 3 | **One-significant-digit rule** — `CP 2,12` → `1E1`, `DT 2.2E-3` → `2E-3` | Gotcha 3, and the whole count-time planner, which is built on this being true |
| 4 | **Chained queries** — `CM;CI 0;GD 0` must give three answers in order | §7.1 item 3, the only unverified assumption behind `Fast readout`. Reports an explicit **recommendation** on whether to enable it |
| 5 | **Status byte semantics** — the read is destructive; `TL 5` really does set bit 7 | Gotcha 6, and that error detection is wired to reality rather than to the simulator |
| 6 | **Buffer threshold** — a ~250-character line sets bit 7 | `BUFFER_ERROR_CHARS = 240`, which `BATCH_MAX_LINE_CHARS` derives from (gotcha 16) |
| 7 | **Timebase cross-check** — count the crystal against `time.perf_counter()` | Catches a wrong preset scaling. It cannot measure the 25 ppm spec: a PC clock is not that good |
| 8 | **Scan machinery** — 10 periods, buffer indexing, `NN`, and `QA 11` → −1 | The `Scan of N periods` mode, and §7.1 item 1 |
| 9 | **EXTERNAL dwell** — three periods, one `CS` each | The `Single count period` mode's acquisition path |
| 10 | **Throughput, measured** — ms/query with `SW 0` and `SW 6`, plus the latency timer | Converts §6.2 from *derived* to *measured* for your setup. Restores `SW 0` afterwards |
| 11 | **Interface gating** — `MI`/`SW` refused on GPIB, `SV` refused on RS-232 | Gotcha 12 |

**Counter B cannot be exercised in tier 1.** Counter A can count the internal 10 MHz timebase, but
counter B accepts only INPUT 1 or INPUT 2 (manual, `CI`) — so with no cable there is no known pulse
train to give it. That asymmetry is the entire reason tier 2 exists.

The long durations are module constants in `selftest.py` (`KNOWN_ANSWER_SECONDS` and friends) so the
bench can shrink them; on hardware the defaults are the values that matter.

### 9.4 Tier 2 — one core cable

```
  CABLE 1 (required)         A DISC out  ──BNC──>  SIGNAL INPUT 2
  CABLE 2 (optional)         PORT1 out   ──BNC──>  INHIBIT in
  CABLE 3 (optional)         DWELL out   ──BNC──>  TRIGGER in
```

**Cable 1** is the whole idea. The A DISC output emits one NIM pulse per count A registers —
*including* when A is counting the internal 10 MHz — so a single BNC hands counters B and T an
exact, known pulse train. Impedances match: NIM into 50 Ω, and the signal inputs are internally
50 Ω terminated, so no terminator or attenuator is needed. The −0.7 V pulse is outside the ±300 mV
linear range but well inside the ±5 V protection limit and is short, so the manual's 10 µs overload
caveat does not apply. The B discriminator is set to FALL at about −100 mV, comfortably above the
≈10 mV region where the manual warns of DISC-to-signal pickup causing oscillation.

With cable 1, tier 2 checks: counter B against an exact reference; both discriminators' slope and
threshold behaviour; `A-B` and `A+B` modes (which must give 0 and 2×, since both counters see the
same train); and `A for B preset` mode, confirming that `QB` really returns −1 by design — the
behaviour an earlier draft treated as an error, which made that whole counting mode unusable.

**Cable 2** is the only way to confirm the D/A produces actual voltage. The SR400 has no ADC, so
`PL` readback proves only that the register was written. PORT1 at 0 V lets counting proceed; at
**+5 V** it inhibits. Clamped to +5 V deliberately — never the full ±10 V range into a TTL input.

**Cable 3** gives a real trigger (TTL, one pulse per dwell, threshold ≈ +1.5 V) and confirms the
trigger discriminator and secondary status bit 0. Combined with cable 1 it enables a **gate-width
calibration**: with T on TRIG preset to *N* gates and gate B FIXED at width *W*, counting the
looped-back 10 MHz gives ≈ `1e7 × N × W` counts, so `counts / (1e7 × N)` is the *effective* gate
width. Sweeping *W* across the resolution bands of gotcha 4 measures the gate generator against the
crystal — the closest this instrument can come to putting a scope on itself.

### 9.5 What neither tier verifies

- **Absolute PORT output voltage** — needs a DVM. Tier 2 shows only that it swings.
- **Gate timing to nanosecond accuracy** — needs an oscilloscope. The calibration above is good to
  a few percent, not to nanoseconds.
- **Signal-input linearity, offset and bandwidth** — needs a calibrated source.
- **Real photon-counting behaviour** — PMT pulse-height distribution, dark counts, dead-time losses,
  afterpulsing. A discriminator plateau on a real PMT is the only test for that, and it is an
  experiment rather than a self-test.

### 9.7 Threshold scans

> **Operating them for the first time?** Read [`docs/THRESHOLD_SCAN_GUIDE.md`](THRESHOLD_SCAN_GUIDE.md)
> instead: a step-by-step walkthrough for someone who has just learned what the discriminator
> threshold is, covering setup, each scan, how to read every panel of the figures — with simulated
> example figures — and how to enter the result. This section is the technical reference behind it.

For the **R8486 bare tube on SIGNAL INPUT 1**: counter A, discriminator A, slope FALL, gates CW.
A threshold scan measures the *integral* pulse-height distribution — the count rate above each
discriminator level — and the operating threshold belongs between its noise edge and its
single-photoelectron shoulder. The two halves of that answer need different light, hence two
scans, run as the end-of-run tests `Dark threshold scan (PMT covered)` and `Light threshold scan
(steady light)` (also exposed as the actions `run_threshold_scan_dark` and
`run_threshold_scan_light`). Each first shows a **blocking** message stating the condition ("Cover the R8486 and make
sure NO light can reach it", "Ensure gentle, STEADY light on the R8486"). That is an
acknowledgement gate, not a question (§9.1 still holds): an OK proves nothing about the bench, so
each scan also checks its condition in the data and stops if it was not met.

**The grids.** The dark scan (`threshold_grid`, 65 levels): 0.2 mV steps from 0.4 to 6.0 mV,
0.4 mV to 15.2 mV, 2 mV to 40 mV. The light scan (`light_threshold_grid`, 75 levels): the same,
but with 0.2 mV steps all the way to 10.0 mV, because the weak-signal optimum and its band lie in
6–10 mV on the real tube, and with 0.4 mV steps there the light scan could not place the optimum
finer than 0.4 mV. The extra levels cost seconds per pass at a usable light level. Every level is
a multiple of the discriminator's 0.2 mV resolution, so every level in the report is one the SR400
actually applied. The real light scans of 2026-11-10 predate the light grid, and step 0.4 mV
above 6 mV.

**Dark (covered tube) — the lower bound.** Sweeps upward with **adaptive count times**: each
threshold counts to 500 counts (~4.5 % Poisson) where that takes under 10 s, and otherwise to 200
counts (~7 %) or 30 s, whichever first. The next period is sized from the rate so far, and every
period is rounded *up* to a settable count time and read back. Once the rate is below 1 cps at two
thresholds in a row, the scan steps 2 mV at a time. It stops once three thresholds in a row are
below 0.5 cps, because the tail beyond sets no bound. **Neither the 2 mV steps nor the stop may
start below 10 mV** (`DARK_TAIL_FROM_V`), however quiet the tube. The second real dark scan
(2026-11-10 16:36) fell below 1 cps at 7.2 mV and went coarse there, in the middle of the
optimum region, leaving 5 thresholds in 6–10 mV where the background fit (below) wants many; the
optimum region plus the fit's ±1 mV ends near 9 mV, and 10 mV is also the manual's pickup
boundary. Replayed on the real rates, the first real scan (13:20), which ran to 36 mV in 21
minutes on the earlier rules, stops at 14.0 mV after 10.1 minutes, unchanged by the floor; the
16:36 scan gets 11 thresholds in 6–10 mV instead of 5, for 10.8 minutes instead of 7.8. The
500-count, 10 s, 1 cps, 0.5 cps and 10 mV values are **provisional**, from those two scans. It
reports:

- the **noise edge** — searched from the **rate maximum** upward, where the log-slope of the curve
  drops below 1.0 /mV over a 1 mV baseline (heuristic, and labelled so). The lower bound is the
  noise edge + 0.5 mV. The search starts at the maximum because a real tube's rate *rises* with
  the threshold below about 1.2 mV, a noise hump. The first version started at the lowest level,
  read that rise as flat, and reported 1.0 mV for the real scan. The current code gives 5.2 mV,
  lower bound 5.8 mV. The 1.0 /mV limit separates that scan's noise roll-off (1.2–4.8 /mV) from
  its dark tail (0.3–0.7 /mV), and is provisional until more scans confirm it. From a single scan
  the edge is uncertain by more than its 0.2 mV step. Redrawn at the real scans' own live times
  around tubes tuned to each, it spreads over about 0.6–0.8 mV (5.0–5.6 and 5.6–6.4 mV)
  ([dark-scan method study](../analysis/dark_scan_method/README.md)). Resampling the observed
  counts instead hardly moves it, which understates the scatter of a repeated scan.
- where **dark counts vanish**, if the scan got that far; with the 0.5 cps stop it usually does
  not, and the report says so. *That is not the operating point*: a level that kills every dark
  count is above most single-PE pulses too. The light scan measures what it costs.
- anything above 1 Mcps as electronic noise, DISC pickup or oscillation, not dark counts.

Refuses its own result if 10 mV reads more than 500 cps (~60× the measured dark rate: light is
reaching the tube) or the lowest threshold reads nothing at all (cable or HV).

**Light (gentle, steady source) — the upper bound, and the optimum.** A probe at 6 mV first:
below 2000 cps (or 20× the dark rate) there is no usable light; above 1 Mcps dead-time loss would
bend the curve, and both stop before sweeping. Then **three repeats of an up pass and a down
pass**, 10 000 counts (~1 %) per threshold per pass. It reports the valley of the pulse-height
density, and the levels where counts fall 0.1/1/2/5/10 % below the valley rate. Each level comes
with its uncertainty in mV, from the Poisson uncertainty of the two rates it compares, and with
the settable GUI value. A loss that sits within its own uncertainty of the reference is reported
**NOT SEPARABLE**, with the counts per level it would need, instead of as a level. On the real scan
that is 0.1 %, at ~7e4 counts per level, where ~8e6 would be needed. With a dark scan it also
gives the photon loss at the level where dark counts vanished.

**Which dark scan.** The one from this SweepMe! session if there is one. Otherwise the newest
valid dark-scan CSV for the same port in the results folder, read back and re-analysed by the
current code. The report names the file and its age, and flags it if it is over 24 h old.
`selftest.py plot` does the same for a light CSV whose header names no dark scan: it uses the
newest same-port dark CSV beside it that is not later than the light scan.

*Drift and hysteresis are separated by signature, not lumped.* Each pass's light level, measured on
the near-flat region, is fitted as `c + a·(time) + η·(direction)`. Drift is the time term over the
scan (flagged above 2 %, and it blocks the recommendation); hysteresis is then the **sideways shift
in mV** between up and down curves on the steep shoulder, with only the time term divided out.
Fitting the direction term is what keeps a not-quite-flat region from cancelling half the
hysteresis, or passing it off as drift.

**The figure of merit** is **S/√B**, from both scans together, when a dark scan is found: S is
the photon fraction from the light scan (light minus dark, relative to the reference level), B the
fitted dark background. Its maximum is the background-limited optimum, and it is what proves the
zero-dark level is wrong rather than merely asserting it. Raising the threshold strips electronic
noise faster than it removes photons. That lasts until the remaining dark counts are themselves
single-PE pulses. From there S and B fall together and S/√B only drops.

**The recommendation is the middle of the band**, not the maximum. The band is every scored level
within 5 % of the best (`FOM_BAND`). The recommended level is the scored level nearest the
midpoint of the band's two ends, ties going to the higher score. It is used only when it scores at
least 0.90 of the best (`FOM_MIDDLE_MIN`), the band spans more than one level and the band does
not reach the lowest scored level; otherwise the plain optimum is recommended. The basis text
says which, gives the band, the middle's own score and the single best level, and says when the
band is not contiguous (some levels inside it score below 0.95). The reason: the top of S/√B is
flat, so its argmax moves from scan to scan more than the band does (dark-scan method study,
[`../analysis/dark_scan_method/`](../analysis/dark_scan_method/README.md)). Without a dark scan the
recommendation falls back to the valley, and says so.

*B is a local fit to the dark scan, not each threshold's own rate* (`_smooth_dark_rate`). Above
about 6 mV a real dark threshold holds 16–60 counts, so B taken level by level is ±13–25 %, five
times the 5 % band, and the band collapsed to one level in both real light scans. The fit is by
Poisson maximum likelihood, so zero-count thresholds count correctly:

- **In the thin tail**, a straight line in log(rate) over ±1 mV
  (`DARK_SMOOTH_HALF_WIDTH_V`), widened up to ±4 mV until it holds 3 thresholds and 20 dark counts
  (`FOM_MIN_DARK_COUNTS`). A level whose window cannot reach that is not scored: a near-zero
  background estimate would make any SNR look enormous. Nor is any level beyond the dark scan's
  last threshold, where the fit would be an extrapolation.
- **Where the curve bends** (the noise roll-off turning into the dark tail, 2–6 mV on the real
  tube) a straight line overshoots. **Below 6 mV only** (`DARK_CURVE_BELOW_V`), where the ±1 mV
  window holds at least 800 counts
  (`DARK_CURVE_MIN_COUNTS`) and a quadratic in log(rate) beats the line by a likelihood-ratio
  statistic above 4 (`DARK_CURVE_LR`), the window narrows in 0.2 mV steps, keeping at least 800
  counts and 4 thresholds, and the quadratic is fitted there. Chosen on held-out data: each real
  dark threshold left out in turn and predicted from the rest. Over 3.8–6 mV predicted/observed
  counts were 1.110 and 1.097 for the line on the two real dark scans, and are 1.001 and 1.002 now.
  From 6 mV up the fit is always the straight line over ±1 mV, however many counts the window
  holds. The dark-scan method study found that narrowing there capped the optimum's
  reproducibility: a narrowed window keeps only about 800 counts, so longer dark counting stopped
  reducing its noise. On the two real dark scans this limit changes no result, because their
  tails never held enough counts to narrow.

The fitted B is not smooth above 6 mV. The ±1 mV window gains and loses dark thresholds as it
moves, so on the real scans B is not monotonic over 7.2–8.0 mV (on the 16:36 scan 0.93, 0.67 and
0.72 counts/s at 7.2, 7.6 and 8.0 mV). Part of the 7.6 mV optimum there is that local dip in B.
A fit whose window does not jump would help; none is made.

The window width, 800 counts and the likelihood-ratio threshold are **provisional**, tuned on two
scans of one tube. The real dark tail is also over-dispersed (more scatter between thresholds than
Poisson), which the fit's quoted uncertainty does not include.

*Levels below the reference are not scored* (the grey "not scored" region of panel (d)). Light
minus dark there is not photon counting: on both real light scans it exceeds the reference rate
by 38–41 % at 2.2 mV, steadily (36–43 % pass by pass), and the excess falls with a log-slope of
−2.3 to −2.6 per mV, on the electronic noise's amplitude scale, against −0.05 per mV for light
minus dark just above the valley. It is counted as `subvalley_excess` and reported. So the lowest scored level
is the reference itself. When the optimum is at it, the recommendation, the headline, the
findings and panel (d) say so in red, since a lower level might score higher.

*S/√B is the weak-signal limit.* For a signal of N counts/s at the reference, against a background
run of equal length, the figure of merit is s/√(s + 2B), with s the photon fraction times N, and
its best level falls as N rises. The report gives the N (10 values per decade) from which the 5 %
band, and then the best level, reach the lowest scored level (`_bright_signal_limits`). Above that
rate it says it cannot judge whether a lower level would be better.

On the simulated tube (noise edge 5.2 mV, valley 4.8 mV) the optimum is **−6.8 mV, counting
87 % of photons**, with S/√B within 5 % of best from 5.8 to 8.0 mV; the band's middle is the
optimum itself, so that is the recommendation. The band reaches the valley from N ≈ 250 counts/s
and the best level from ≈ 2000. (Before the fit stopped narrowing above 6 mV, the simulator's
thicker dark tail gave −6.4 mV.) On the first real pair (2026-11-10, dark 13:20, light 13:59) the
optimum and the recommendation are **−6.8 mV, counting 76 %**, within 5 % of best from 6.4 to
7.6 mV, reaching the valley from N ≈ 630 and ≈ 5000 counts/s. On the second (16:36, 17:24) the
optimum is 7.6 mV and the recommendation, the band's middle, 7.2 mV. See [`SIMULATED_VS_REAL.md`](SIMULATED_VS_REAL.md). At
15.2 mV the real S/√B has fallen to 0.20 of best. The strict window — noise edge to 1 % loss — is *empty* there, which the report states
rather than treating as a failure. For the R8486 at 1000 V that is expected and is the evidence for
the Stage 2 preamp. Below 10 mV any recommendation is valid only with the cables exactly as they
were for the scan (manual p. 22).

Both scans keep the safety invariants of §9.2: refuse while counting (before prompting), restore
everything without a storage slot, never send `SE`, never raise. Each writes its report, CSV, period
log and SVG plot together (§9.6); a scan refused at the light probe writes the report only, because there
was no sweep to plot.

### 9.8 Dark settling, and comparing PMT high voltages

**The HV is a record, not a setting.** The field `PMT high voltage in V (record only, 0 = not
recorded)` goes into every report header, every scan CSV (`# hv_V:`), every figure and the test
log's `pmt_hv_V` column. The driver never sets or reads the supply. **A light scan only uses a
dark scan taken at the same recorded HV**, whether from memory, from the session cache or from
disk, because another HV is another gain. Before this rule, a light scan could silently be scored
against the background of a different voltage.

**The settling check** (`run_dark_settling`, end-of-run test `Dark settling check (PMT covered)`)
counts at the GUI's `Discriminator A level`, because that is the rate the measurement depends on.
It uses blocks of at least 60 s and 1000 counts, at most 180 s. After each block it fits a
Poisson-weighted straight line through blocks spanning the last 5 minutes, and at least three of
them. It calls the rate settled when the slope is within 2σ of zero, and gives up after 30
minutes. The report and figure give the measured drift in %/min with its uncertainty, and the
smallest drift the check could have resolved at that count rate, flagged when that is coarser than
the 0.5 %/min it aims for (`SETTLE_DRIFT_TARGET`: 5 % over a 10-minute dark scan). With fewer than 100 counts in
the window it reports **CANNOT JUDGE**. The raw blocks go to a CSV (`kind: settle`, times since
the check began).

*Why a slope, not block-to-block agreement.* The first design compared consecutive blocks. On the
bench, at 69 cps, 1000-count blocks lasted 15 s and differed by 1.4 % each. The test passed
straight away while the simulated rate was still falling about 6 % a minute: a comparison only
sees drift that is fast relative to its own window. All the settling values are **provisional**:
no real settling curve of this tube has been measured.

**`python selftest.py hv-compare <folder>`** pairs **every** light scan that has a recorded HV
with the newest same-port, same-HV dark scan and settling check before it, and re-analyses them.
Repeated light scans at one HV are replicates. Each replicate's best (S − B)/√B is corrected to the
median photon rate, light minus dark at the valley, by the ratio of the two. Signal scales with
the light and background does not, so this is exact while the signal stays proportional. Each HV
then gets the replicates' mean and standard error. A second table, `_replicates.csv`, lists every
scan in time order. It writes the two tables and a five-panel figure: (a) valley and single-PE
peak, (b) peak/valley, (c) dark rate at half the peak, (d) the corrected best (S − B)/√B, mean ±
SE, against HV, and (e) the light level of each scan in the order taken, so a source drift is
seen rather than assumed. The verdict is a pure function, `_hv_verdict`, tested on constructed
rows. It names an optimum only with at least three comparable
HVs, a photon rate (light minus dark, at the valley) that agrees within 50 % across all scans, and a
best S/√B strictly inside the range. With replicates it reports the optimum as **NOT RESOLVED**
from the runner-up when their gap is under twice its uncertainty. Light that varies by more than
50 % across the scans blocks the comparison, since proportional correction is then in doubt.
A NOT SETTLED voltage is left out. An optimum that counts under half the photons is flagged as
weak-signal only. A light scan whose HV field was left at 0 has no recorded HV and is not
compared at all: both scans of the second real run (2026-11-10, 16:36 and 17:24) are like that.

The measurement procedure, interleaved replicates over 975–1075 V in 25 V steps, two or three
rounds, with the settling check and dark scan on each voltage's first visit and light scans only
after that, is §10 of [THRESHOLD_SCAN_GUIDE.md](THRESHOLD_SCAN_GUIDE.md).

Two bugs were found on the way, and are fixed for every scan:

- **The pulse-height density was undefined on the 2 mV grid above 15.2 mV**, so a single-PE peak
  that the gain had moved past 15 mV could never be found. It stuck at 16 mV whatever the HV. The
  stencil now falls back to the neighbouring rows there; fine-grid results are unchanged.
- **Reports written in the same second overwrote each other**, since names carry the time to the
  second. A clash now gets `_2`, `_3`, ... on every file of the set, which sort after the original name.
