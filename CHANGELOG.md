# Changelog

Newest first. Gotcha and section numbers refer to
[`Logger-Stanford_SR400/README.md`](Logger-Stanford_SR400/README.md).

## Unreleased

### Fixed

- **GPIB now works: `connect()` asserts REN.** The SR400 answers GPIB commands only while the
  Remote Enable line is asserted. On the bench (NI GPIB-USB-HS, 2026-11-10), REN stayed off even
  with *Assert REN when SC* ticked in NI MAX, and every query timed out with nothing received. The
  driver now calls VISA's `control_ren(VI_GPIB_REN_ASSERT_ADDRESS)` before its first command, so
  it no longer depends on that board setting. A Prologix controller, which has no `control_ren()`,
  is left to handle REN itself. Gotcha **12**. **Confirmed on hardware** the same day: with the
  fix, *Retrieve data* in SweepMe! 1.5.7.9 connected over GPIB and returned counts.
- **A GPIB connect no longer resets the SR400.** pysweepme clears every port after opening it.
  On GPIB that clear is a Selected Device Clear, which the SR400 treats as `CL`, so the setup
  reverted to defaults on every connect even with *Reset instrument at start* off, and nothing put
  it back. The driver now never lets pysweepme clear a port, on any port type and at any point,
  including ports opened for an action before the GUI parameters arrive. On COM, where the clear
  only flushed the serial buffers, `connect()` now discards stale input itself, reading only the
  bytes already waiting and changing no setting.
- **The no-answer error names the right interface.** On GPIB it now asks about power, the cable
  and `GPIB ADDR`, and quotes the bus error. The RS-232 baud, parity and echo advice it used to
  give is now shown only for COM ports.
- **Actions started without the GUI parameters now find their port.** On SweepMe! 1.5.7.9, the
  self-test and the dark threshold scan, started from a control widget with asynchronous
  execution, refused with "select a port first" although a port was selected. The driver instance
  they ran on had apparently never received `get_GUIparameter()`. Every action now takes the port
  name from the open port object (`port_properties["ID"]`) when it has none. The self-test and the
  scans also assert REN themselves on GPIB, since they may run without `connect()`. If there is no
  port object either, the refusal now says so, as a diagnostic. **On 1.5.7.9 that is what
  happened:** the action had neither a port name nor a port. The working route there is the new
  end-of-run tests (below).
- **Tier 1 no longer fails on GPIB.** Its RS-232-only check treated the driver's own refusal of
  `SW` and `MI` as a failure. A GPIB run reported 20/22; it now reports 22/22.
- **Stopping a run no longer shows an exception.** On SweepMe! 1.5.7.9 every stop raised
  *"The measurement was stopped while waiting for the SR400 count data"*, although nothing had
  failed. A stop during counting now leaves the SR400 idle and ends the point quietly, with every
  value NaN rather than a partial count. Timeouts and instrument errors still raise.

### Changed

- **The self-tests and threshold scans can be ticked as end-of-run tests.** Four new GUI
  checkboxes, all unticked by default. Each ticked test runs once in `deinitialize()`, after the
  run's last point, on the run's own open port, so it works on any SweepMe! version. A stop skips
  them. The dark scan's result is kept for the SweepMe! session, per port, so a light scan in a
  later run still finds it. Driver README **§9.0**; the threshold-scan guide now uses them.
- **The docs name the SweepMe! version actually used on hardware: 1.5.7.9**, not 1.5.8.9 as
  previously written.
- **`Counter A input` defaults to `INPUT 1`** rather than `10 MHz`, since counting the PMT is the
  normal use. The 10 MHz known-answer check in the quick start now asks for `10 MHz` explicitly.

### Added

- **[`THRESHOLD_SCAN_GUIDE.md`](Logger-Stanford_SR400/THRESHOLD_SCAN_GUIDE.md)**, a step-by-step
  operator's guide to the threshold scans, written for someone who has just learned what the
  discriminator threshold is. It covers what the scans are looking for and why "zero dark counts"
  is the wrong answer, a setup checklist, each scan in order, how to read every panel of both
  figures, how to enter the result (in volts: −6.4 mV is `-0.0064`), when to repeat the scans, and
  what each refusal message means. It lives in the driver folder, so it travels with the driver,
  and the scan prompts, the SweepMe! description pane and §9.7 all point to it.

- **Recorded data and plots for both threshold scans.** Each writes a raw CSV (counts and live
  time per threshold) and an SVG figure beside its report, under the same stem. The figures are
  drawn as plain SVG, which any browser opens, so they need no plotting library to draw and
  nothing but a browser to view, on any machine the report reaches. They are drawn from the CSV,
  so `python selftest.py plot <csv>`
  regenerates any of them anywhere. The figures carry the refusals: an invalid dark scan offers
  no lower bound, and a drifting light scan labels its loss levels unreliable. Documents
  **§9.6**, **§9.7**.

- **Discriminator threshold scans**, `run_threshold_scan_dark` and `run_threshold_scan_light`,
  for the R8486 on SIGNAL INPUT 1. Each shows a blocking acknowledgement prompt for its condition
  and then verifies the condition from the data. Dark: adaptive count times (200 counts or 30 s
  per threshold), noise edge, where dark counts vanish, light-leak and no-signal refusals. Light:
  probe-gated, three up/down repeats, valley, loss levels, drift and hysteresis separated by a
  time/direction fit, and — with a dark scan — the S/√B background-limited optimum, which shows
  quantitatively why a zero-dark-count threshold is not the optimum. Documents **§9.7**.

- **Two-tier hardware self-test, as SweepMe! actions** (`run_self_test`,
  `run_self_test_loopback`), implemented in a new sibling module `selftest.py`. Tier 1 needs no
  cabling change and covers the manual's known-answer test, the raw response format of ~50
  getters, the one-significant-digit rule, chained queries, status-byte semantics, the 240-char
  buffer threshold, the timebase, the scan machinery, EXTERNAL dwell, measured throughput and
  interface gating. Tier 2 uses one BNC (A DISC output → SIGNAL INPUT 2) to give counters B and T
  an exact known pulse train — the only way to exercise counter B, which cannot see the internal
  timebase — plus two optional cables for the INHIBIT input and a gate-width calibration against
  the crystal. Both refuse while the instrument is counting, restore every setting they touch
  without using a storage slot, never send `SE`, and write a timestamped report to
  `Public\Documents\SweepMe!\DataDevices\Logger-Stanford_SR400\` (TEMP only as a fallback). The report's response-format table is what retires **§7.1**. Documents **§9**, and
  **§5.2** and **§7.1** now point at it.

- **`Count time mode`**, with `Per period` (default, unchanged behaviour) and
  `Total live time (auto-split)`. A single count period is quantised to `d × 10ᵏ` cycles, so 1.5 s
  is not a settable period — but *N* settable periods reach an exact total, and auto-split finds
  the split with the fewest periods (equivalently the highest duty cycle) subject to a soft cap on
  *N* and a 50 % duty floor. 1.5 s becomes 3 × 0.5 s, exact to the timebase's 25 ppm. The planner
  is the module-level pure function `plan_count_time()`, testable without a `Device`. In
  `Per period` mode the rounding warning now names the exact decomposition inline. Documents
  **gotcha 3**, which is split into its two separate claims.
- **`Quantize count time to >99% duty cycle`.** The auto-split duty floor is 80 % by default —
  type a count time and start counting, without thinking about dead time — and this raises it to
  99 % for when the dead time itself matters. `plan_count_time_tiers()` evaluates every floor in a
  single enumeration, so a plan always exists at 99 % and the message can price what the other
  floor would have given instead of leaving it to be guessed.
- Auto-split **refuses** unless `Counter T input = 10 MHz` and the counting mode is not
  `A for B preset`. Anywhere else the T preset counts events rather than clock cycles, so there is
  no total live time to divide; `configure()` raises and names both remedies.

- **USB-serial latency-timer detection.** `connect()` reads the selected COM port's FTDI latency
  timer and warns once if it is above 4 ms, with the estimated per-point cost for the current
  settings. FTDI-only, RS-232-only, and an unknown value is reported as unknown rather than as
  acceptable. Documents **gotcha 15**.
- **Two actions**, `report_com_port_latency` and `reduce_com_port_latency` (**§8**). Both are
  host-side only and send the instrument nothing, so either is safe to click mid-run. The reducer
  writes sysfs on Linux; on Windows it attempts the registry write and falls back to generating a
  `.reg` file rather than demanding administrator rights, so the measurement path never needs
  elevation. Documents **gotcha 15**.
- **`Fast readout (batch queries)`**, off by default. Chains up to 10 `QA`/`QB` queries per line
  within the instrument's buffer limits, cutting read round trips by ~3.5× at 10 periods per point.
  Off by default because the manual both documents chained queries and advises against them; it
  disables itself and re-reads unbatched if the link ever goes out of step. Documents
  **gotcha 16**.
- **`Measurement mode`**, with `Single count period` (default, `NP 1` + EXTERNAL dwell) and
  `Scan of N periods` (the previous multi-period behaviour). Documents **§2**.
- **`Baudrate`** as a GUI parameter; 9600 was hardcoded.
- **`Print SweepMe! phase`**, a debug option naming each semantic function as SweepMe! calls it.
- **Front-panel-change reporting.** Status bit 0 was read and ignored; it now reports from
  `_check_status()`. Documents **gotcha 14**.

### Fixed

- **Early exits wrote the report before the restore.** Tier 1's known-answer abort, tier 2's
  missing-cable stop and the light scan's probe refusals returned from inside the `try`, so their
  reports lacked the "every setting was restored" line, which is exactly when it matters. They now
  leave through a sentinel exception and write the report after the restore.

- **Audited every command, numeric limit and status bit against the manual** (Revision 2.7). Nothing
  was wrong. `BUFFER_ERROR_CHARS = 240` overclaimed its source and now distinguishes the manual quote
  from the inference; the `CP` response format moved from assumption to quotation, shortening
  **§7.1**; and the RS-232 terminator disagreement between the drafts turned out to be settled by the
  manual rather than needing hardware. See [docs/MANUAL_AUDIT.md](docs/MANUAL_AUDIT.md).

- **Preset rounding was silent in half the configurations.** `CP` keeps one significant digit. The
  driver rounded and read back the *count time*, but `Preset counts (T or B)` — which governs
  whenever counter T is off the timebase, and in `A for B preset` mode — was rounded with nothing
  said, and that branch has no `Count time` column that could have revealed it. Asking for 1.5e6
  counts got 2e6 in silence.
- **A timeout left the SR400 counting.** `pause_counting()` (`CH`) is now sent before raising, on
  both the timeout and the run-stopped paths.
- **The test suite could not run at all.** It looked for `Switch-Stanford_SR400/main.py` beside
  itself while both READMEs pointed at `../test_sr400_virtual.py`; neither path existed once the
  files were flattened into one folder.

### Changed

- **Settled the output shape for a multi-value acquisition (§7.2).** A scan returns one row with
  *N* columns per counter, and the measurement mode selects the *reduction* applied to the scan
  buffer rather than a different acquisition architecture — so one SweepMe! point stays one
  complete, self-contained scan. Driver-stepped rows were ruled out because a Logger never gets
  the `SweepMode`/`apply()` pair that would let SweepMe! own the x-axis; *N* dynamic columns were
  confirmed feasible by the `Logger-LJ_ADC_DJW` precedent; the sidecar file is held in reserve for
  *N* above the 256-point column cap. Two sub-decisions: the delay values are columns rather than
  parsed out of column names, because the SR400 rounds delays within resolution bands
  (**gotcha 4**) so the applied delay is not reliably `start + i × step`; and they carry the
  nominal delays, because reading `GZ` per point would throw away the single-transfer `EA`
  readout. Recording the decision as shared by three features overstated it — auto-split and
  per-period statistics are both reductions to a fixed column count, so only gate scanning was
  ever waiting on it. §7.3 is now the implementation spec, and §7.1 gains the one hardware
  assumption it rests on.

- **Switch → Logger.** The module renders no `SweepMode` field and never calls `apply()`, so
  `apply()` and the whole sweep-mode branch were unreachable and are gone. Gate-delay scanning is
  consequently not wired up; see **§7.2** for the open output-shape decision.
- **`_check_sweep_mode_is_usable()` → `_check_configuration()`.** Two of its checks were about the
  instrument rather than about sweeping and are kept as messages, not exceptions: a gate delay set
  while the gate is CW, and a T discriminator level while counter T counts the timebase. The SR400
  accepts both and counts correctly, so refusing to configure was wrong. Both fire only when the
  setting differs from its default. Documents **gotcha 11**.
- **GUI layout grouped under headings**, with the two scan-only fields under their own heading so
  the common "just count" case reads top to bottom without stepping over parameters it ignores.
- Repository restructured into `Logger-Stanford_SR400/` with `tests/`, matching the layout of the
  LabJack SweepMe! drivers repo.
