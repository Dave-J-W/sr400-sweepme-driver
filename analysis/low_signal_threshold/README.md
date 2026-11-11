# Best discriminator level for a weak signal (R8486 on the SR400, 2026-11-10 scans)

**PROVISIONAL.** Two dark scans and two room-light scans from one afternoon. The two dark scans
disagree by more than counting noise (see Robustness), so the dark rate is not yet pinned down well
enough for the low-N answers to be final. Every number below comes from `low_signal_optimum.py` run
on the raw CSVs. `summary.txt`, `results.csv` and `robust_choice.csv` hold the same numbers in full.

If the signal brings a photon background that cannot be separated from it, see
[`../photon_background/`](../photon_background/README.md).

## Update, 2026-11-11: re-run on the driver's corrected background fit

This analysis found two problems in the driver's analysis code. Both are now fixed in
`selftest.py`, and every number on this page has been regenerated with the fixed code.

1. **The background fit `b(v)` read high where the dark curve bends.** It used to be a straight line
   in log(rate) over +-1 mV. Each real dark threshold was left out in turn and predicted from the
   rest. Over 3.8-6 mV the predictions summed to 1.110x (13:20 scan) and 1.097x (16:36 scan) the
   observed counts. Over 2.2-3.6 mV they were wrong by up to 3x at single thresholds.
   - **The fix.** Where the +-1 mV window holds at least 800 counts and a quadratic in log(rate)
     fits it significantly better, the fit narrows its window and goes quadratic.
   - **Held-out ratios now** are 1.001 and 1.002 over 3.8-6 mV.
   - **Above 6 mV**, where the real windows hold fewer counts, the fit is exactly the old one, so
     the thin-tail noise reduction is kept.
   - **Fitted/raw on the same data** is now 0.89-1.12 over 2.2-3.6 mV, against 0.31-1.98 before.
2. **Below the valley, the driver scored light minus dark as photons.** It no longer does. It scores
   S/sqrt(B) from the valley up, which is what this analysis already did. It also reports the signal
   rate from which that floor limits its answer.

**What changed here.**

- No headline "set" level changed: the equal-time table and the one-setting choices are as before.
- The 5 % band at N = 1000 now ends at 5.8 mV rather than 6.0 mV.
- With the background known, N = 20 now picks 5.8 mV instead of 6.0 mV. Some band edges moved by
  one grid step.
- The cost of 4.4 and 5.2 mV at low N fell a little (4.4 mV at N = 1: x6.3-11.8, was x7.2-13),
  because b(v) at 4-5 mV is no longer overestimated.
- With the old fit's bias gone, light minus dark at 2.2 mV is 1.38-1.41x the valley rate (it was
  1.42-1.44x).

## The answer

**Your signal is N photons/s, where N means the signal counts/s you would see with the
discriminator at the valley of the pulse-height spectrum** (4.0 mV in the 13:59 light scan, 3.8 mV
in the 17:24 one). The table assumes the usual measurement: **signal-on and signal-off runs of equal
length**. Each "set" value is the one level that does best across all four dark x light pairings,
meaning it has the smallest worst-case time penalty. The "within 5 %" range is the set of levels whose
significance is within 5 % of the best in **all four** pairings, which is the same as counting time
within 10.8 % of the shortest.

| signal N (counts/s at the valley) | set | type in the GUI | anything in this range is within 5 % | time per run for 10 % on N |
|---:|---:|---:|---|---:|
| 1     | 6.8 mV | -0.0068 | 6.8 mV only | 500-730 s |
| 2     | 6.8 mV | -0.0068 | 6.8 mV only | 160-220 s |
| 5     | 6.8 mV | -0.0068 | 6.4-6.8 mV | 41-51 s |
| 10    | 6.4 mV | -0.0064 | 6.0-6.8 mV | 17-19 s |
| 20    | 6.0 mV | -0.0060 | 5.6-6.8 mV | 7.4-7.7 s |
| 50    | 5.8 mV | -0.0058 | 5.4-6.4 mV | 2.6 s |
| 100   | 5.6 mV | -0.0056 | 5.0-6.4 mV | 1.2 s |
| 200   | 5.6 mV | -0.0056 | 4.6-6.0 mV | 0.58 s |
| 500   | 5.0 mV | -0.0050 | 4.2-6.0 mV | 0.22 s |
| 1000  | 4.6 mV | -0.0046 | 4.0*-5.8 mV | 0.11 s |
| 10000 | 4.0 mV* | -0.0040 | 4.0*-5.6 mV | 0.010 s |

\* The valley, the lowest level this analysis allows. At N >= ~300-600 counts/s the lower band edge,
and at N >= ~2000-4500 the optimum, may lie below it, but the data there cannot be trusted (see
Method).

The time is the length of **each** run (signal on, signal off), so the clock time is twice that.
The range covers the four pairings. To reach a precision p other than 10 %, multiply by (0.1/p)^2.

**If you want one setting and do not know N well:**

- N between 1 and 10: **6.8 mV (-0.0068)**. You lose at most 4 % in time against the best level for
  each N.
- N between 1 and 100: **6.8 mV (-0.0068)**, at most 17 % more time.
- N anywhere from 1 to 10000: **6.4 mV (-0.0064)**, at most 25 % more time.
- N between 100 and 10000: **5.0 mV (-0.0050)**, at most 6 % more time.

**Every level in this table is below 10 mV.** The SR400 manual (p. 22) warns that the DISC outputs
can be picked up by the input below 10 mV. These results hold only with the cables routed as they
were during the scans.

**What N means.** N is the rate of signal pulses that would be counted at the valley level. It
does not include quantum efficiency, or photoelectrons whose pulses fall below the valley. To get N
back from a measurement at level v, divide the background-subtracted rate by eps(v). At the levels
above, eps(v) for the 13:59 / 17:24 light scans is: 6.8 mV 0.756 / 0.742, 6.4 mV 0.814 / 0.790,
6.0 mV 0.862 / 0.847, 5.6 mV 0.903 / 0.893, 5.0 mV 0.950 / 0.939, 4.6 mV 0.977 / 0.960, 4.0 mV
1.000 / 0.990 (`inputs.csv`). The ~2 % difference between the two scans is a gain change (see
Robustness). For a quantitative measurement, measure eps at your operating level on the day.

### If the background is known precisely instead

This is the case where a separate, much longer dark run gives b(v), so only the signal run counts.
Best levels across the four pairings, from `robust_choice.csv`:

| N | 1 | 2 | 5 | 10 | 20 | 50 | 100 | 200 | 500 | 1000 | 10000 |
|---|---|---|---|---|---|---|---|---|---|---|---|
| set (mV) | 6.8 | 6.8 | 6.4 | 6.0 | 5.8 | 5.6 | 5.6 | 5.0 | 4.6 | 4.4 | 4.0* |
| within 5 % in all four (mV) | 6.8 | 6.4-6.8 | 6.0-6.8 | 5.6-6.8 | 5.4-6.4 | 5.0-6.4 | 4.6-6.0 | 4.2-6.0 | 4.0*-5.8 | 4.0*-5.8 | 4.0*-5.4 |
| time for 10 % (s) | 315-433 | 112-142 | 34-39 | 15 | 6.6-6.8 | 2.4 | 1.2 | 0.55 | 0.21 | 0.10 | 0.010 |

The optimum is 0-0.6 mV lower than in the equal-time case for the same N. Here the background
weighs half as much, so the trade-off tips sooner towards keeping photons.

### What a fixed level costs (equal-time background)

The factor is the counting time at the fixed level divided by the time at the best level for that
N. The range covers the four pairings (`summary.txt`, `fig_cost_of_fixed_levels.svg`).

| N | 4.4 mV | 5.2 mV | 6.0 mV | 6.8 mV | 7.6 mV | 9.2 mV |
|---:|---|---|---|---|---|---|
| 1     | x6.3-11.8 | x2.0-4.0 | x1.13-1.56 | x1.00-1.04 | x1.00-1.14 | x1.8-2.2 |
| 10    | x2.9-3.9 | x1.31-1.70 | x1.00-1.06 | x1.00-1.03 | x1.11-1.21 | x1.9-2.0 |
| 100   | x1.22-1.30 | x1.02-1.04 | x1.01-1.04 | x1.12-1.17 | x1.32-1.40 | x2.1-2.2 |
| 1000  | x1.00-1.01 | x1.02-1.04 | x1.10-1.11 | x1.25-1.26 | x1.47-1.52 | x2.3-2.4 |
| 10000 | x1.01 | x1.07 | x1.15-1.16 | x1.31-1.33 | x1.54-1.59 | x2.4-2.5 |

9.2 mV replaces the 9.0 mV in the brief because 9.0 mV was not measured in either light scan, and
nothing here is interpolated. Low levels are costly at low N because the dark rate climbs steeply
below ~5 mV. High levels cost about a factor 2 at any N because they throw away photons: eps(9.2 mV)
is 0.39-0.42.

## How the optimum moves with N

- **N -> 0.** The optimum is the driver's background-limited S/sqrt(B) optimum: 6.8 mV with the 13:20
  dark scan and 7.6 mV with the 16:36 one. The code checks this against `analyse_light`'s
  `optimum_v` and stops if they differ. The background at that optimum is only 0.7-1.6 counts/s
  (1.64 at 6.8 mV in the 13:20 dark, 0.67 at 7.6 mV in the 16:36 dark), so N = 1 is not deep in the
  background-limited regime. In the equal-time case the D2 pairings stay at 7.6 mV up to N ~ 1 and
  then drop to 6.8 mV. The D1 pairings are at 6.8 mV throughout.
- **N ~ 5-20.** The optimum drops to 5.8-6.8 mV.
- **N ~ 50-200.** 5.0-6.0 mV. That is **below the driver's noise edge** (5.2 mV for the 13:20 dark,
  6.0 mV for the 16:36 dark). The dark rate there (7.9-10.5 counts/s at 5.0 mV) is small next to N.
- **N >= 1000.** 4.4-4.6 mV. The best level reaches the valley in at least one pairing from N ~ 4500
  counts/s (equal time), or ~2200 with the background known. The driver now reports the same kind of
  limit for its own scans: for the 13:20 + 13:59 pair, the band reaches the valley from ~630 counts/s
  and the best level from ~5000. It uses a coarser N grid (10 per decade) and a single pairing.

This tube has no level "clear of the noise" (the driver already reports that the strict window is
empty without a preamp), so the high-N optimum is set by the trade-off itself. It ends at the
valley, the reference level, rather than at a noise edge.

**Flatness.** In each pairing the 5 % band is 0.4-1.4 mV wide at N <= 20 and 1.6-2.2 mV at N >=
500, where its lower edge is at or near the valley floor. At N = 1-2 (equal time) the band common to all four
pairings shrinks to the single level 6.8 mV, because the two dark scans pull in opposite directions.
For N <= 0.2 counts/s (0.1 with the background known) no level is within 5 % in all four pairings at
once.

## Method

1. Read the four raw CSVs with `selftest.read_scan_csv` and analyse them with
   `selftest.analyse_dark` and `selftest.analyse_light`. Light counts are summed over the 3 up and 3
   down passes at each level. The reference level is the valley found by `analyse_light`.
2. **b(v)** is `selftest._smooth_dark_rate`, the driver's own background estimate. It is a Poisson
   maximum-likelihood fit of log(rate) to the dark thresholds within +-1 mV, widened until it holds 3
   thresholds and 20 counts. It is linear in the level, except where the curve bends and the window
   holds at least 800 counts: there it is quadratic over a narrower window (since 2026-11-11; see the
   update above). I used it rather than the single threshold's rate because a dark threshold
   between 6 and 10 mV holds only 11-77 counts (13:20 scan) or 16-36 counts (16:36 scan), which is
   +-11-30 %. That alone would make the optimum jump between neighbouring levels.
3. **eps(v)** = (R_light(v) - b(v)) / (R_light(ref) - b(ref)). The driver's own efficiency does not
   subtract b at the reference. That differs by a constant factor only, so the argmax is the same.
4. For each N and each figure of merit, F1 = s/sqrt(s + b) and F2 = s/sqrt(s + 2b) with s = eps N, I
   find the best level among the candidates and the band of levels with F >= 0.95 F_max. The time to
   10 % is T = 1/(0.1 F)^2, which gives T = (s + 2b)/(0.1 s)^2 for F2.
5. **Candidate levels** are the light scan's measured levels that are (a) at or above the valley,
   (b) no higher than the dark scan's highest level, so the dark fit is never extrapolated, and (c)
   where the dark fit is defined. That gives 4.0 or 3.8 up to 18.0 mV for the 13:20 dark and up to
   15.2 mV for the 16:36 dark. The grid is 0.2 mV below 6 mV and 0.4 mV above, so 7.0 and 7.4 mV
   (settable, but not measured) are never candidates.
6. **Robust choice.** Over the levels common to all four pairings, pick the one whose worst time
   penalty across pairings is smallest, and report the levels within 5 % in every pairing.
7. **Counting statistics.** 400 Poisson resamples (seed 20261110) of every raw count, dark and light,
   followed by the whole chain again: the light-pass merge, the dark fit, eps and the optimum. The
   valley stays at its nominal level so that N keeps one meaning. Ranges quoted as "16-84 %" are
   over those resamples.

**Why levels below the valley are excluded.** They are run only as a sensitivity check
(`fig_inputs.svg`, panel A, grey). The driver now excludes them from its own S/sqrt(B) scan for the
same reasons:

- Below the valley the light-on rate is more than photons plus dark noise. Light minus dark rises to
  1.38-1.41x the valley rate at 2.2 mV, and the light rate peaks at 5.9e5 counts/s at 2.0 mV against
  3.8e5 at the valley. The excess is steady across all six passes (36-43 % at 2.2 mV). It falls with
  the level at a log-slope of -2.3 to -2.6 per mV, close to the dark noise's -4.2 to -4.5 per mV and
  far from the -0.05 per mV of light minus dark just above the valley. So it lives on the noise's
  amplitude scale, not the photoelectrons'. These numbers come from the raw dark rates, computed
  while fixing the driver, and are recorded in `notes/HANDOFF.md`.
- Within ~0.4 mV of the valley the excess is only 0.5-2 % and could be sub-valley photoelectrons.
  The scans cannot tell the two apart, nor whether either would scale with a weak signal.
- Counting below the valley is outside the definition of N.
- Until 2026-11-11 there was a fourth reason: the dark fit missed the raw rate by up to 3x on the
  2.2-3.6 mV roll-off. That is fixed (see the update above).

## Assumptions

- The noise and dark rates during the real measurement equal those of the dark scan. With the 13:20
  and 16:36 scans differing by a factor of 0.59 in the tail, this is the weakest assumption.
- eps from room light (single photoelectrons at ~3.8e5 counts/s) applies to the real signal. That
  needs the same HV, tube and cabling, and a signal of single-photon pulses, not multi-photon
  bursts.
- Counting is Poisson. The 5 ns pulse-pair dead time costs 0.19 % at the valley and 0.16 % at 6 mV
  in the light scans, so eps(6 mV) is biased by +0.03 %, which is negligible. It is irrelevant at the
  weak-signal rates the answer is for.
- Signal-on and signal-off runs of equal length for F2. For F1, a background known with negligible
  error.
- The HV is ~1000 V for both pairs. No file records it: the 16:36 and 17:24 files have an empty
  `hv_V` field, and the 13:20 and 13:59 files have none. The operator's 1000 V is documented for
  the first pair only.

## Robustness

**Across the four pairings** (`summary.txt`, "OPTIMUM BY PAIRING").

- *Which dark scan* is the main effect, at N <= 20. With the 13:20 dark the optimum is 0-0.8 mV
  lower than with the 16:36 dark: at N = 1 (equal time) 6.8 vs 7.6 mV, at N = 2-5 the same 6.8 mV,
  at N = 10 6.0 vs 6.8 mV.
- *Which light scan* (a ~2 % gain difference) moves the optimum by 0.2 mV at a few N, and by 0.4 mV
  once (16:36 dark, N = 20 equal time and N = 10 known background: 6.4 vs 6.0 mV). The time
  difference there is under 3 %.
- At N >= 50 all four agree within 0.6 mV, and the robust level's time is within 0.8 % of each
  pairing's own best.
- At N = 1 the robust 6.8 mV costs at most 4.2 % against the D2 pairings' 7.6 mV.

**The two dark scans really differ.** This is measured, not counting noise:

- Over the thresholds both scans share above 6 mV, the 16:36 tail is 0.59 +- 0.06 of the 13:20 tail
  (140 vs 239 counts in equal live time).
- The 16:36 noise roll-off is 0.11-0.18 mV higher. It crosses 1000 / 100 / 10 counts/s at 3.11 /
  3.75 / 5.02 mV, against 2.96 / 3.64 / 4.84 mV.
- The scans were taken at 13:20 (before the 13:59 room-light scan) and 16:36 (after it). Why they
  differ (dark adaptation, temperature, something else) is not known from these files.
- *Added 2026-11-11:* the later study in [`../dark_scan_method/`](../dark_scan_method/README.md)
  simulated both scans' methods on one tube. The curve differences above arise from method
  alone in at most 1 of 300-400 pairs, so they are a change in the tube or its electronics. The
  difference between the optima (6.8 against 7.6 mV) arises from method alone in 13-38 % of pairs,
  so that part of the spread is within method. A full repeat scan's noise edge spreads over
  0.6-0.8 mV, much more than resampling one scan's counts suggests.

**Counting statistics.** These are the 16-84 % ranges of the resampled optimum (`results.csv`, 88
rows):

- In 78 rows the range is at most 0.4 mV wide: one level or two neighbouring grid levels.
- It is 0.8 mV (6.8-7.6 mV) for the 16:36-dark pairings at N = 1 (both figures of merit) and N = 2
  (equal time). On this data 6.8 and 7.6 mV are a near tie there.
- It is 0.8 mV (6.0-6.8 mV) for both 13:20-dark pairings at N = 2 (known background) and N = 5
  (equal time).
- In the N -> 0 limit the 13:20-dark optima are 6.8 mV in 88 % and 96 % of resamples. The 16:36-dark
  optima are 7.6 mV in 78 % and 72 % (16-84 % ranges 7.2-7.6 and 6.8-7.6 mV).

**Sensitivity to the analysis choices** (`sensitivity.csv`, "SENSITIVITY" in `summary.txt`). Three
alternatives, tested separately:

- allowing levels below the valley;
- replacing the fit by the raw dark rate wherever a threshold holds >= 400 counts;
- scaling b(v) by 0.9 or 1.1.

They move individual optima by 0.2-0.4 mV at some N, and below the valley to 3.2-4.2 mV at N = 10000.
If any of them were the truth, the headline level would cost at most 1.0 % more time (equal-time
background) or 2.6 % (background known). Both worst cases are from allowing levels below the valley.
The +-10 % and raw-rate checks cost at most 0.3 %. The optimum is flat enough that these choices do
not matter in practice.

**Checked against the brief.**

- The light rate is 3.25e5 / 3.27e5 counts/s at 6.0 mV and 3.77e5 / 3.86e5 at the valley.
- The gain proxy, the level where eps falls through 0.5 or 0.25, differs by 2.0-2.2 % between the
  light scans: 8.57 vs 8.39 mV. The 1.7 % in the brief matches the driver's *light-drift* figure for
  the 17:24 scan (1.74 %, not flagged). The 13:59 scan's drift is 0.90 %.

## What would change the answer

- **A different HV or gain.** Every level scales with the gain, so redo both scans.
- **Re-routed cables.** Pickup below 10 mV: redo the dark scan at least.
- **A different dark rate on the day,** from dark adaptation, temperature or light leaks. A lower dark
  rate moves the low-N optimum up, towards 7.6 mV. A higher one moves it down. The 13:20 and 16:36
  scans bracket what has been seen so far.
- **Gating** (pulsed source, SR400 gate). The background scales by the gate duty cycle, which
  behaves like a larger N/b and moves the optimum down. Re-run the script with b scaled by the duty
  cycle.
- **A preamp.** It would separate noise from single photoelectrons and make all of this obsolete.
- **Multi-photon pulses** in the real signal. eps would be higher at high levels.

## What is not known

- The HV of the second pair (the files do not record it).
- Whether the dark rate was stationary during each 8-21 minute dark scan. Each threshold was
  measured at a different time, so a falling dark rate would tilt b(v).
- Whether the noise rate with the signal present equals the dark-scan noise rate. Below the valley
  there is direct evidence that, with room light, it does not.
- The uncertainty of the band edges. Resampling was done for the optimum level and its time only.
- Levels between the measured grid points above 6 mV (7.0, 7.4 mV, ...).

## Reproduce

From this folder, with any Python 3.10 or later (standard library only):

```bash
python -I low_signal_optimum.py
```

This runs from this folder, takes a few seconds and needs only the standard library plus
`Logger-Stanford_SR400/selftest.py`, which is loaded by path and not modified. The output is
identical from run to run (seeded). To add a new scan pair, add it to `DARKS` / `LIGHTS` and
`PAIRINGS` at the top of the script.

## Files

| File | What it is |
|---|---|
| `low_signal_optimum.py` | the analysis: regenerates everything below from the raw CSVs |
| `data/SR400_threshold_scan_dark_2026-11-10_163608.csv` | raw dark scan, 16:36, copied byte for byte (SHA-256 b4dc153d...) |
| `data/SR400_threshold_scan_light_2026-11-10_172444.csv` | raw light scan, 17:24, copied byte for byte (SHA-256 117a5909...) |
| `../../docs/real_data/2026-11-10/SR400_threshold_scan_{dark_..._132008,light_..._135935}.csv` | the first pair, read in place |
| `results.csv` | one row per pairing x N x figure of merit: optimum (mV, GUI V), 5 % band, eps, b, time to 10 % at the optimum and at the fixed levels, resampled range |
| `robust_choice.csv` | one level for all four pairings, per N and figure of merit |
| `sensitivity.csv` | the optimum under the alternative candidate floor and b(v) estimators (hybrid, x0.9, x1.1) |
| `inputs.csv` | per-level eps, b(v), raw counts for each pairing |
| `summary.txt` | machine-written: verified facts, every table above in full |
| `fig_inputs.svg` | measured eps(v) and raw dark rate with the fitted b(v) |
| `fig_optimum_vs_N.svg` | best level against N, both figures of merit, all four pairings, the common 5 % band |
| `fig_time_vs_level.svg` | time to 10 % against level for N = 1, 10, 100, 1000, 10000 |
| `fig_cost_of_fixed_levels.svg` | time penalty of fixed levels against N |
