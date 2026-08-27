# Changelog

Newest first. Gotcha and section numbers refer to
[`Logger-Stanford_SR400/README.md`](Logger-Stanford_SR400/README.md).

## Unreleased

### Added

- **`Count time mode`**, with `Per period` (default, unchanged behaviour) and
  `Total live time (auto-split)`. A single count period is quantised to `d × 10ᵏ` cycles, so 1.5 s
  is not a settable period — but *N* settable periods reach an exact total, and auto-split finds
  the split with the fewest periods (equivalently the highest duty cycle) subject to a soft cap on
  *N* and a 50 % duty floor. 1.5 s becomes 3 × 0.5 s, exact to the timebase's 25 ppm. The planner
  is the module-level pure function `plan_count_time()`, testable without a `Device`. In
  `Per period` mode the rounding warning now names the exact decomposition inline. Documents
  **gotcha 3**, which is split into its two separate claims.

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
