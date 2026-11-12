# Handoff notes (internal, not user documentation)

Working notes for whoever picks this up next, human or agent. The public documentation is the
two READMEs, `docs/` and the CHANGELOG. **Their wording is on hold** until the operator decides how
the docs should present the real data. So changes since 2026-11-10 evening are recorded here
first. Keep this file factual and dated. No private names or local paths: this repository is
public.

## State, 2026-11-11

**Bench.** SR400 at GPIB0::23 through an NI GPIB-USB-HS, SweepMe! 1.5.7.9 on the lab PC, R8486 at
~1000 V. The HV is set by hand. The driver records it only when the GUI field is filled in, and in
the 16:36 and 17:24 scans it was left at 0.

**Real data so far, all 2026-11-10:**

| Scan | Where | Notes |
|---|---|---|
| dark 13:20 | `docs/real_data/2026-11-10/` | its report's 1.0 mV lower bound is the since-fixed noise-edge bug; 5.8 mV now |
| light 13:59 | `docs/real_data/2026-11-10/` | ran without its dark scan; S/sqrt(B) optimum 6.8 mV when re-analysed with it |
| dark 16:36 | `analysis/low_signal_threshold/data/` | noise roll-off ~0.2 mV higher, tail above 6 mV ~0.59x the 13:20 one; went coarse at 7.2 mV |
| light 17:24 | `analysis/low_signal_threshold/data/` | gain ~2 % below 13:59's; found the 16:36 dark from disk on its own |

The second pair is **not** in `docs/real_data/` yet. Whether, and how, it goes there is part of the
pending docs decision.

**Settled results (provisional, from these four scans):**

- The S/sqrt(B) optimum for a weak signal is 6.8-7.6 mV across all four dark x light pairings, and
  7.2 mV scores 0.92-0.95 of best in every one. GUI value: negative volts, so 6.8 mV is -0.0068.
- The lower bound moves ~1 mV between runs (5.8 against 6.6 mV). Two different uncertainties,
  not to be confused:
  - Resampling a scan's own counts moves its edge by at most 0.2 mV.
  - Repeating the whole scan on the same tube spreads the edge over 0.6-0.8 mV. That is the
    honest single-scan uncertainty, from the simulations in `analysis/dark_scan_method/`.
  - Even so, method alone gives the 5.2 -> 6.0 mV difference in only 0.25-2 % of simulated pairs.
    So it reflects a change in the curve, as the curve differences themselves do. The optimum's
    6.8 -> 7.6 mV shift, by contrast, is within method (13-38 %).
- The best level against signal rate N is in `analysis/low_signal_threshold/README.md`. It falls
  from 6.8 mV at N <= 5 counts/s to about 5.6 mV at N ~ 100 and the valley near N ~ 10^4.

## Changes since the docs were last written

All are in the code and covered by the virtual bench. **None is yet described in the READMEs,
`docs/` or the CHANGELOG** unless noted.

- `c28134a` Test-log migration on a header change, and the fitted dark background for S/sqrt(B).
  The CHANGELOG does cover these two.
- `3bc1c26` `analysis/low_signal_threshold/`, the low-signal optimum analysis.
- (this commit) **Dark-scan tail floor, `DARK_TAIL_FROM_V` = 10 mV.** Neither the 2 mV steps nor
  the stop may start below it, however quiet the tube. The 16:36 dark went coarse at 7.2 mV, inside
  the optimum region. Replayed on the real rates: 13:20 unchanged (10.1 min); 16:36 gets 11
  thresholds in 6-10 mV instead of 5, for 10.8 min instead of 7.8. The bench's quiet-tube case
  checks it. The virtual bench now reports 609/609; the driver README still says 605.

## Public docs that are now stale (fix when the docs decision is made)

- `docs/SIMULATED_VS_REAL.md`: says the real S/sqrt(B) band collapses to 6.8 mV only. It is now
  6.4-7.6 mV on the first pair, after the fitted background. Its dark-scan timing (15.6 / 10.1 min)
  predates the 10 mV floor.
- `docs/THRESHOLD_SCAN_GUIDE.md` §4 says "about 10 minutes"; it is 10-11 on the real tube with the
  floor.
- `Logger-Stanford_SR400/README.md` §9.7 describes the coarse/stop rules without the floor; the
  test count line says 605.
- CHANGELOG: no entry for the floor, the low-signal analysis, or whatever the analysis-issue work
  below produces.

## Open issues, being worked (delegated 2026-11-11)

Found by the low-signal analysis and confirmed on the real data. Both are in `selftest.py`'s
analysis; both affect the driver's own reports, not only the analysis folder.

1. **`_smooth_dark_rate` reads 4-20 % high between 3.8 and 6 mV.** It fits a straight line in
   log-rate over +-1 mV. The real dark curve bends there, from the steep noise roll-off into the
   dark tail, so a straight line overshoots. Around 2.2-3.6 mV the miss is up to 3.2x, where the
   thresholds hold 200-1236 counts, so it is curvature, not noise.
2. **Below the valley, light minus dark is treated as photons.** At 2.2 mV it reaches 1.42-1.44x
   the valley rate. That is light-induced extra counting (noise pulses riding on photon pulses),
   not sub-valley photoelectrons. It matters for the S/sqrt(B) scan and any high-signal optimum
   (N >~ 1000), where the best level approaches the valley.

## Working conventions that have cost time when skipped

- Run the virtual bench (`Logger-Stanford_SR400/tests/test_sr400_virtual.py`, needs `pysweepme`)
  twice after any change to file naming or timing. Same-second filenames made tests flaky once.
- Every committed figure is regenerated by `selftest.py plot <csv>`, and the bench fails if one
  differs. Regenerate the four in `docs/` after any plotting or analysis change.
- Push only behind the private-name scan. It caught an interpreter path containing the account
  name in a subagent's README on 2026-11-10. That commit was amended before it was ever pushed.
- Deliver code with the file-writing or edit tool, not shell heredocs. Heredocs have corrupted
  escapes and quotes several times in this project.

## 2026-11-11: the two open analysis issues, fixed

This closes both items under "Open issues, being worked" above. Changes are confined to:

- `selftest.py` analysis code;
- `tests/test_sr400_virtual.py`;
- the two regenerated light figures;
- `analysis/low_signal_threshold/`.

The READMEs, `docs/*.md` and the CHANGELOG are untouched.

### 1. `_smooth_dark_rate` follows the bend

**The rule.** It is the straight line in log(rate) over +-1 mV, as before. The exception: where
that window holds >= `DARK_CURVE_MIN_COUNTS` (800) counts and a quadratic in log(rate) beats the
line by a likelihood-ratio statistic > `DARK_CURVE_LR` (4), the window narrows in 0.2 mV steps. It
keeps >= 800 counts and >= 4 thresholds, and the quadratic is fitted there. The thin tail keeps the
line and its full window. A new helper, `_poisson_logpoly`, does the Poisson ML fit of any degree,
with step-halving Newton so a steep window cannot overflow.

**How it was chosen.** Each estimator was judged on data it was not fitted to:

- leave-one-out on both real dark scans;
- binomial thinning (each threshold's counts split 50/50 into two independent Poisson halves; fit
  one half, score the other), which also lets the raw single-threshold rate compete;
- two synthetic cases with known truth.

**What was tried, and why the rest lost:**

- The straight line (the old fit).
- A line in an adaptive window (narrowest holding K = 200 / 400 / 800 counts). It left 2-4 % bias at
  3.8-6 mV and failed on the roll-off.
- A quadratic over +-1 mV. It was biased -3 to -11 % at 3.8-6 mV and noisy in the tail.
- A quadratic in an adaptive window, ungated. It was as good in the bend, but cost rms 4.9 %
  against 3.9 % on a pure exponential tail.
- The raw rate. It was competitive only where a threshold holds hundreds of counts.
- The gated quadratic was kept.

**Before / after on the real data, leave-one-out:**

| | 13:20 before | 13:20 after | 16:36 before | 16:36 after |
|---|---|---|---|---|
| predicted/observed, 3.8-6.0 mV | 1.110 | 1.001 | 1.097 | 1.002 |
| predicted/observed, 2.2-3.6 mV | 1.156 | 0.987 | 1.059 | 0.981 |
| chi-square per held-out threshold, 3.8-6.0 mV | 2.52 | 0.47 | 4.83 | 2.59 |
| chi-square per held-out threshold, 2.2-3.6 mV | 148 | 3.8 | 477 | 11.9 |
| fitted/raw at each threshold, 2.2-3.6 mV | 0.33-1.98 | 0.91-1.12 | 0.31-1.82 | 0.89-1.10 |

**Above 6 mV the fit is unchanged** to 1e-16 on both scans (25 and 7 fitted thresholds).

**Synthetic cases.** These come from the evaluation:

- *A curve with a bend.* It is shaped like the 13:20 scan and sampled like the driver: 200 counts,
  at most 30 s per threshold, 200 draws. Over 3.8-6 mV the bias goes from +7.4 % to +0.7 % and the
  rms from 8.5 % to 5.2 %; a single threshold is 8.0 %. Over 2.2-3.6 mV the rms goes from 60 % to
  5.1 %.
- *A pure exponential tail* (the existing bench case, 200 draws). The rms goes from 3.9 % to 4.2 %.

**Effect on the driver's results.** None on the weak-signal optimum or band of any of the four
real pairings: 6.8, 6.8, 7.6 and 7.6 mV, with the same bands as before.

### 2. S/sqrt(B) is not scored below the valley

**Evidence**, from raw dark rates on both light scans x both dark scans:

- Light minus dark exceeds the valley rate by 38-41 % at 2.2 mV.
- The excess is steady pass to pass: 36-43 % over the six passes.
- It falls with a log-slope of -2.3 to -2.6 per mV. The dark noise falls at -4.2 to -4.5 per mV;
  light minus dark from the valley up falls at -0.05 per mV. So it is on the noise's amplitude
  scale.
- Within ~0.4 mV of the valley the excess is 0.5-2 %, which could be sub-valley photoelectrons.
  The scans cannot separate the two, nor show whether either scales with a weak signal.
- The 1.42-1.44x quoted above was inflated by the old fit's undershoot at 2.2 mV.

**Behaviour now:**

- `analyse_light` scores from the reference level up, and records the largest excess below it
  (`subvalley_excess`).
- It flags `optimum_at_floor` / `band_at_floor`. When the optimum is at the floor, the
  recommendation basis, the headline, the findings (in red) and panel (d) say so.
- `_bright_signal_limits` gives the signal rate N (counts/s at the reference, equal-time background
  run, s/sqrt(s + 2B), 10 N values per decade) from which the 5 % band and then the best level reach
  the floor. Above that rate the report says it cannot judge a lower level.
- Panel (d) shades the unscored region "not scored".
- The old report line "for a bright signal the optimum moves down, to the lowest level above the
  noise edge" was wrong on this tube and is replaced.
- `_absolute_snr` (hv-compare) scores from the reference up too.

**On the real pairings**, the band reaches the valley from N ~ 631 / 794 / 631 / 1000 counts/s and
the best level from ~5012 / 10000 / 5012 / 10000 (D1L1, D1L2, D2L1, D2L2). On the simulated example
figure the numbers are ~250 and ~2000.

### Bench, figures, analysis

- **Virtual bench: 627/627 on two consecutive runs** (was 609).
  - [23g]: one check tightened. On a curvature-free tail the fit may be no worse than 1.25x the
    straight line; it measured 4.0 % against 4.0 %.
  - [23h], new, 17 checks: the synthetic bend (bench draws +1.1 % against +7.4 %), the roll-off
    (5.7 % against 60 % rms), the held-out real 13:20 ratios above, the unchanged tail, the floor on
    real data, the bright-signal limits, hv-compare's floor, the committed figure's wording, and a
    flat-background case whose optimum lands on the floor and must be flagged.
  - No existing real-data expectation changed. Optimum 6.8 mV and band >= 0.8 mV still hold.
- **Regenerated:** `docs/real_data/.../SR400_threshold_scan_light_2026-11-10_135935.svg` and
  `docs/images/example_threshold_scan_light.svg`. The two dark SVGs came out byte-identical.
- **`analysis/low_signal_threshold/`** was re-run on the fixed code, and its README has a dated
  "Update, 2026-11-11" section.
  - No headline "set" level changed.
  - The N = 1000 band now ends at 5.8 mV (was 6.0).
  - Known-background N = 20 now picks 5.8 mV (was 6.0).
  - The low-N cost of 4.4 mV fell (x6.3-11.8 at N = 1, was x7.2-13).

### Still open

- **The real dark tail is over-dispersed.** Leave-one-out chi-square per threshold over 6.2-10 mV
  is 3.8 (13:20) and 2.3 (16:36), the same before and after the fix. That is more than Poisson. It
  would come from the dark rate changing during the scan, or from correlated (bursty) dark counts.
  The fit's quoted sigma does not include it.
- **Bench coverage of the 16:36 scan.** The held-out checks in the bench use only the 13:20 scan,
  the one in `docs/real_data/`. The 16:36 numbers above come from the evaluation, which is not in
  the repository. If the second pair moves to `docs/real_data/`, add it to [23h].
- **The constants are provisional.** `DARK_CURVE_MIN_COUNTS` = 800 and `DARK_CURVE_LR` = 4 were
  tuned on two scans of one tube.
- **High signal rates.** The driver states where its floor limits the answer but cannot find a
  sub-valley optimum. That would need evidence that separates sub-valley photoelectrons from
  light-induced counting: for example light scans at two or more light levels (does the excess
  scale with the light?), or a gated pulsed source.
- **The band edges have no uncertainty.** The driver reports the S/sqrt(B) band without one.
- **Public docs now stale in addition to the list above:**
  - `Logger-Stanford_SR400/README.md`: the light-scan section describes B as the dark rate, says
    nothing about the floor or the curvature fit, and keeps "for S >> B the optimum moves down".
    The test count line still says 605 (now 627).
  - `docs/SIMULATED_VS_REAL.md`: the bright-signal paragraph.
  - `docs/THRESHOLD_SCAN_GUIDE.md`: panel (d) has a grey "not scored" region the guide does not
    mention.

## 2026-11-11: `analysis/photon_background/`, an inseparable photon background

**The operator's model.** The signal N brings a photon background f N, with f assumed between
0.01 % and 50 %:

- it has the same pulse heights as the signal, so the same eps(v) applies;
- it is absent from the signal-off run (dark only), and no threshold separates it from the signal;
- the estimate is N_hat = (C_on - C_off) / (eps (1 + f_assumed) T).

The coordinator's first version (background in both runs, removed by on/off) was withdrawn by the
operator. It survives as a one-paragraph contrast: best level at N (1 + 2f), no systematic. The
folder reads the four 2026-11-10 scans in place, needs only the standard library plus
`selftest.py`, and reruns byte-identically (seeded). `analysis/low_signal_threshold/` is unchanged
apart from a one-line pointer in its README.

### Checked, all four pairings, both figures of merit (equal-time off run; dark known)

- **The statistical part is the photon-free analysis at N' = N (1 + f), exactly.**
  - Per-level variance ratio within 7.8e-16 of 1.
  - Best level, 5 % band edges and valley-floor flags identical in 5152 of 5152 cases (92 N x 7 f).
  - The one-level-for-all-four choice is identical in 154 of 154 cases.
  - The floor and the grid do not break it, because the candidate set is the same.
  - It is not exact only when read off a coarse N table: the nearest row differs in 314 of 1134
    cases, by up to 0.6 mV.
- **Systematic.** The relative bias is (f - f_a)/(1 + f_a) at every level, so to first order
  delta_f/(1 + f), and no threshold changes it.
- **Monte Carlo** (13:20 + 13:59, N = 10/s, f = 0.1, T = 100 s, six levels, 20000 trials,
  f_a = 0.10 and 0.13): bias within 1.5 MC standard errors, spread within 1.0 %.
- **Total.** T_p(v) = V(v)/(p^2 - floor^2). The levels within 5 % of the best time to p equal the
  statistical band for every delta_f (2992 of 2992 cases). At a fixed time T the near-best range
  follows V(v)/V(best) <= 1/0.95^2 + (1/0.95^2 - 1) T/T_cross, with T_cross = V(best)/floor^2;
  checked in 12628 of 12628 cases.

### Results (equal-time off run)

- **Level against N and f.** One level for all four pairings: 6.8 / 6.4 / 5.6 / 4.6 mV at
  N = 1 / 10 / 100 / 1000 for f <= 10 %. At f = 50 % it is at most 0.6 mV lower (N = 200:
  5.6 -> 5.0 mV).
- **The photon background helps the statistics.** The time to 10 % at f = 50 % is x0.49-0.66 of
  the photon-free time. Its whole cost is the floor delta_f/(1 + f): for example 2.7 % at
  f = 10 % +- 3 %, and 10 % at f = 50 % +- 15 %, where a total of 10 % is never reached.
- **Less emphasis on small dark counts appears only at fixed counting time.** On 13:20 + 13:59 at
  f = 10 %, the range within 5 % of the best total precision widens:

  | N | 0.1 x T_cross | T_cross | 10 x T_cross |
  |---:|---:|---:|---:|
  | 10  | 1.2 mV | 2.2 mV | 5.0 mV |
  | 100 | 1.8 mV | 2.4 mV | 5.2 mV |

  In time-to-p terms nothing widens. The low-level cost at N = 10 (4.4 mV) only falls from x3.9 to
  x3.0 between f = 0 and f = 50 %.
- **Where the photon background out-noises the dark term** (f eps N = 2b at the best level):
  f ~ 0.3-0.7 at N = 10, ~0.08-0.09 at N = 100, ~0.03-0.06 at N = 1000. At N = 1 it would need
  f > 2.3, so dark noise always dominates there.

### Still open

- **Spectral mismatch.** If the background's pulse heights differ from the signal's (multi-photon
  pile-up from a pulsed source; light-induced small-pulse counting like the sub-valley excess),
  the bias becomes level-dependent, f (eps_bg/eps - 1)/(1 + f), and the threshold could then
  matter for the systematic. The test is N_hat at two or more levels in the real experiment, or a
  threshold scan of signal plus background compared with the room-light eps(v). No such data
  exists.
- **A time-varying f** adds variance that the model leaves out.
- **f and delta_f are operator inputs.** Nothing in these scans measures them.
- **Inherited from `analysis/low_signal_threshold/`:** the two dark scans disagree by 0.59x in the
  tail; there is no trust below the valley; every level is below 10 mV (pickup-sensitive); the
  second pair's HV is not recorded.

## 2026-11-11: dark-scan method study, `analysis/dark_scan_method/`

Asked: are the 13:20 and 16:36 dark scans different only through method (grid, count times)?
The method: the driver's own `_measure_point`, rule sets and analysis, run on a virtual bench
(`VirtualSR400` subclassed on a virtual clock, not modified), with tubes T1 and T2 tuned to each
real scan. 300-400 seeded scans per case. Everything is in the folder's README. No driver, test or
doc file was touched.

### Verdict: method explains the optimum, not the curves

| Difference (16:36 against 13:20) | Same tube, method only | Changed tube (T1 then T2) |
|---|---|---|
| 2.6-3.6 mV, x1.13-3.32 (z = 16.4 at 3.0 mV) | 0/400 | 27-53 % |
| 4.0-5.6 mV, x1.23 +- 0.04 | 0/400 | 53 % |
| tail >= 6.4 mV, x0.59 +- 0.06 | 0/400 Poisson, 1/300 over-dispersed | 28 % |
| edge 5.2 -> 6.0 mV | 0.25 % Poisson, 1-2 % over-dispersed | 51 % |
| optimum 6.8 -> 7.6 mV, both light scans | 12.8 % Poisson, 37.5 % over-dispersed | 53 % |

- The noise-free tubes reproduce the real edges and optima exactly (5.2 / 6.8 and 6.0 / 7.6 mV).
- Exact observed optimum pair: 8.5 % for the changed tube against 0.5 % for the same tube. Exact
  edge pair: 13.5 % against 0.75 %.
- **Two physical changes are needed.**
  1. Electronic noise at 2.5-6 mV changed: an extra ~5e3 counts/s at 2.8 mV, ~2 counts/s at
     5.6 mV.
  2. The dark (single-PE-like) rate fell ~40 % in the tail.
- **Neither is elapsed time.** At 6.0-7.2 mV both scans were at t = 241-335 s, and the ratio there
  is 0.67 +- 0.07.
- **Neither is count time.** Both scans counted 2.8 mV for 60 ms, and read 3783 against 9550
  counts/s.
- **First-window factor kappa.** From the live-time fingerprint of the driver's own
  `_measure_point`, kappa is consistent with 1: 13:20 1.0-2.0, 16:36 0.85-1.0, at 2.6-3.6 mV.
- **No within-threshold rate change.** None at p < 0.05, over 36 thresholds.
- **Simulated settling, mains and drift fail.** DAC settling (1-20 ms), 60 Hz modulation and a
  common dark relaxation reproduce none of the curve differences.
- **The millivolt is cheap.** The top of S/sqrt(B) is flat:
  - 7.6 mV scores 0.95-0.97 of the best on T1;
  - 6.8 mV scores 0.96-0.98 on T2;
  - a fixed 7.2 mV scores 0.97-0.998 on both.

### Found on the way

- **Over-dispersion.** The tail over-dispersion is level-independent: var/mean ~3, which whole
  clusters of mean size 2 reproduce (held-out chi-square medians 3.25 and 2.91 against the real
  3.76 and 2.25). A slow modulation (300 s) cannot reproduce it.
- **Unexplained smoothness.** 13:20 at 3.8-6 mV is smoother than Poisson (0.47; 1.5 % of
  simulations).
- **The dark tail is broader than the photon curve.** Its exponential slopes are 0.27 and
  0.21 /mV; the light eps falls at 0.36 /mV.
- **The 13:20 edge is set by one threshold:** 6.4 mV, 77 counts. Splicing the scans flips the edge
  between 6.4 and 6.8 mV.
- **Grid only:** 13:20 thinned to the 16:36 levels moves its optimum from 6.8 to 7.2 mV.
- **Analysis issue, proposed and not made:** `_smooth_dark_rate`'s curvature narrowing caps the
  optimum's precision.
  - Any +-1 mV tail window with >= 800 counts narrows to ~800 counts.
  - So with the driver's fit, P(two scans within 0.2 mV) only goes from 0.26 (11 min) to 0.66
    (12 h).
  - With the straight line kept from 6 mV up, it reaches 0.84-0.97 at ~190 min (T1), and
    0.92-0.94 (T2).
- **Under a drifting dark rate, interleave.** On T1 with drift, ~190 min:
  - one 480 s upward pass is reproducible (0.91) but biased: 0 % within 0.2 mV of the truth;
  - 8 alternating passes of 60 s reach 0.91-0.98, and 95-99 % within 0.2 mV of the truth.
- **The light grid limits the optimum.** The real light scans step 0.4 mV above 6 mV, so their
  optimum cannot resolve 0.2 mV.

### Proposed, for the main session to decide

1. Narrow the dark fit only below ~6 mV.
2. A 0.2 mV light grid over 6-10 mV.
3. An optional refinement stage: 7 alternating dark passes over 5.6-10 mV at 0.2 mV and 60 s,
   ~3 h. Or else report the band, or use a plateau level such as 7.2 mV.
4. Log every count period.

### Still open

- **Is the 2.6-6 mV excess pickup?** Test it with a dark scan with the HV off, or a 50 ohm
  terminator.
- **The dark-rate history.** It needs a fixed-level monitor (e.g. 8 mV, 60 s every 10 min) from
  HV-on, with the HV-on and cover times recorded.
- **Clusters or modulation?** Distinguish them by var/mean against window length at 8 mV.
- **The noise and dark decomposition at 4-8 mV is poorly fixed** by two scans.
- **`out/` holds ~43 MB of raw runs.** Kept on the study's disk, not committed (in `.gitignore`):
  the seeded scripts regenerate it. Committing it would keep 43 MB in the public history for good.

## 2026-11-11: the study's changes 1, 2 and 4 made; the band's middle recommended

The operator chose changes 1, 2 and 4 from the study's list and deferred 3 (alternating dark
passes) "for later/never". All three are made in `selftest.py`. The recommendation now also
follows the study's cheaper alternative: the middle of the band, not the argmax.

- **1. The fit narrows only below 6 mV** (`DARK_CURVE_BELOW_V = 0.006`). From 6 mV up,
  `_smooth_dark_rate` is the straight line over +-1 mV however many counts the window holds. This
  is the study's `tail_line`. On the two real dark scans it changes nothing: B is identical at
  every scored level, old code against new. The guide's simulated example **does** change. Its
  dark scan holds more counts at 6.0-6.4 mV, so the old fit narrowed there. B rises 13 % at
  6.0 mV and 8 % at 6.4 mV. Its optimum moves from 6.4 to 6.8 mV, and its band from 6.0-7.6 to
  5.8-8.0 mV. It now counts 86.7 % of photons, against 89.8 %. (Found by the documents session
  after f2f9600; that commit's message and this note's first version missed it.)
- **2. The light scan has its own grid,** `light_threshold_grid()`, with 0.2 mV steps from 0.4 to
  10.0 mV. It has 75 levels, against `threshold_grid()`'s 65. Below 6 mV and above 10 mV it is the
  dark grid. The dark scan's grid is unchanged.
- **4. Every count period is logged** to `<scan stem>.periods.csv` beside the scan CSV, for both
  scans. It has one row per period, with `point` (the 1-based row of the scan CSV), `period`,
  `counts`, `live_s` and `since_level_s` (time from the level change to the period's start).
  `read_scan_csv` returns its raw rows with `kind: periods`. The driver's own CSV lookups skip it
  by `kind`; the bench's `_newest(..., ".csv")` skips it by name.
- **The recommendation is the band's middle.** This is the scored level nearest the midpoint of
  the 5 % band's two ends; ties go to the higher score. Its own score may fall below 0.95, because
  the band need not be contiguous. It is used down to `FOM_MIDDLE_MIN = 0.90`, and only when the
  band spans more than one level and is not at the floor. Otherwise the plain optimum is
  recommended, as before. The basis text names the band, the middle's own score, whether the band
  is split, and the single best level.
  - **What the real data showed, which the study's model tubes did not:** 7.2 mV scores only
    0.92-0.95 on all four pairings, in both independent light scans. The light efficiency is
    smooth there; the dip is in B. The +-1 mV sliding window gains and loses dark thresholds as it
    moves, so B is not monotonic over 7.2-8.0 mV (16:36: 0.93, 0.67, 0.72 cps at 7.2, 7.6,
    8.0 mV). Part of the 7.6 mV "peak" is that local dip in B.
  - So a rule that picks only among in-band levels returned the noisy argmax again. That was my
    first version, caught on the real data before commit.
  - The four pairings are now recommended at 6.8, 6.8, 7.6 and 7.2 mV (D1L1, D1L2, D2L1, D2L2).
    Before, they were 6.8, 6.8, 7.6 and 7.6. D2L1's band is one level, so that is its optimum.
    D1L1's band is 6.4-7.6 mV, with an unscored midpoint of 7.0. 6.8 and 7.2 tie there, and 6.8
    wins on score.
- **Bench: 665 checks**, section [23i], run three times. The three committed light figures (both
  real, and the guide's example) were regenerated. Their recommendation text changed, and it is one
  line longer, so everything below it moves down 17 px. On the two real figures the panels' data
  are as before. The example's S/sqrt(B) panel moved with its background, as in item 1.
- **`analysis/low_signal_threshold` re-run.** No optimum, band or time changed. Only the bootstrap
  spreads moved (in resampled scans the narrowing had sometimes switched on at 6 mV and above).
  The README's counting-statistics paragraph is updated with the before and after numbers.
  `analysis/photon_background` re-ran byte-identical.
- **`analysis/dark_scan_method` is not re-run.** It is a record of the driver as it was. Its
  "driver" arm is the pre-change fit; it is now the same as its `tail_line` arm.

### Still open

- **Docs.** The documents session owns them. These still describe the old behaviour: the
  recommended level for the second real run (7.6, now 7.2 mV), the light grid (0.4 mV above
  6 mV), the background fit's narrowing, and the absence of the periods file.
- **B's roughness above 6 mV** is the next limit on reproducibility, and nothing here fixes it.
  A fit with a window that does not jump would help: one straight line over the whole tail from
  6 mV, or a kernel-weighted window. Test it on the study's simulators before changing the driver.
- **Change 3 (alternating dark passes)** is deferred by the operator.
