# Dark-scan method study: method or physics? (2026-11-11)

Two real dark scans of the covered R8486 (~1000 V) on 2026-11-10 disagree: 13:20 (13:20 rules) and
16:36 (16:36 rules). This folder tests the working hypothesis that **they differ only in
methodology**. It uses the real data, and a virtual bench that runs the driver's own sampling and
analysis code against a simulated tube tuned to each scan. Every number below comes from a script
in this folder. The script is named in brackets, and its raw output is in `out/`.

## Verdict

**Method does not explain the scans.** Three of the six differences cannot come from method at all:
the 2.6-3.6 mV excess, the 4.0-5.6 mV excess and the lower tail. In every method-only scenario,
at most 1 of 300-400 simulated same-tube pairs reproduced any of them. That holds with Poisson or
over-dispersed counting, discriminator settling, a dark-rate relaxation within the scan, and 60 Hz
modulation. Two further differences, the optimum and the edge, *can* come from method.
The optimum often does; the edge rarely does. A changed tube makes all six typical.

| Observed (16:36 against 13:20) | Method alone, same tube | Needs |
|---|---|---|
| 0.4-2.4 mV: hump agrees, common ratio 1.022 +- 0.013, max \|z\| 2.7 over 11 levels | nothing to explain | - |
| 2.6-3.6 mV: x1.13 to x3.32; z = 16.4 at 3.0 mV (ratio 3.32 +- 0.26, 9.0 sigma); chi-square 506 on 6 levels | **never** (0/400; the 95th percentile of the same-tube chi-square is 12-13, and 30 with 20 ms DAC settling) | a change in the **electronic noise** roll-off at 2.5-3.5 mV |
| 4.0-5.6 mV: x1.23 +- 0.04 (one common factor fits: chi-square 8.5 on 8 dof) | **never** (0/400; same-tube 5-95 % range 0.93-1.07) | the same: extra noise reaching ~6 mV |
| tail >= 6.4 mV: x0.59 +- 0.06 (8 levels) | **never** with Poisson counting (0/400); 1/300 with the tuned over-dispersion | a **dark (single-PE-like) count rate ~40 % lower** at 16:36 |
| noise edge 5.2 -> 6.0 mV | rarely: 0.25 % of pairs (Poisson), 1-2 % (over-dispersed); 5.8 % on the 16:36-like tube | the changed curve (noise-free tubes give 5.2 and 6.0 exactly) |
| S/sqrt(B) optimum 6.8 -> 7.6 mV with both light scans | **often**: 12.8 % of pairs (Poisson), 37.5 % (over-dispersed), and 13.5 % even for two scans under the *same* 13:20 rules | nothing, or a steeper background through 6.4-7.6 mV |

[06, 09, 10; figure `fig3_method_vs_physics.svg`]

So the operator's position holds for **the optimum** and fails for **the curves**. The optimum is
the most method-sensitive output because the top of S/sqrt(B) is flat. On the 13:20-like tube
with light 13:59, 6.6 mV scores 0.11 % below the best level and 7.2 mV 1.5 % below [14]. Counting
noise alone spreads the driver's optimum over 6.0-8.4 mV (sd 0.5-0.7 mV per scan) [06, 07]. The
curves, though, carry two physical changes that no sampling rule makes. **The millivolt is cheap:**
7.6 mV scores 0.95-0.97 of the best on the 13:20-like tube, and 6.8 mV 0.96-0.98 on the 16:36-like
tube. A fixed 7.2 mV scores 0.97-0.998 on both, with either light scan [15].

## The evidence, difference by difference

### Real-data facts [01, 03, 04]

- Durations, from the end of the first threshold to the end of the last: 13:20 1278 s, 16:36
  484 s.
- **The tail ratio is not elapsed time.** 6.0-7.2 mV was measured at t = 241-335 s in *both* scans,
  and there 16:36 reads x0.67 +- 0.07. From 9.2 mV up, 16:36 was earlier (362-484 s against
  486-1004 s), and reads x0.56 +- 0.10. A common within-scan drift cannot make one scan lower at
  the same elapsed time.
- **The 2.8 mV point is not count time.** Both scans counted 2.8 mV for 60 ms in all, each
  starting with the same 10 ms first period. They read 3783 and 9550 counts/s.
- **The dark tail is broader than the photon pulse-height curve.** In the tail fit, the light scans'
  photon fraction eps(V) (log-slope 0.36-0.37 /mV over 7.2-15.2 mV) fits worse than a free
  exponential. For 13:20 the deviance is 102.7 against 65.5 on 31 and 30 dof; the slopes are
  0.27 /mV (13:20) and 0.21 /mV (16:36). The dark counts are not just thermionic single
  photoelectrons with the photon amplitude spectrum.
- **Splicing the scans** (16:36 below X, 13:20 from X up, and the reverse; driver's analysis) [04]:
  - The **edge** flips between X = 6.4 and 6.8 mV. One threshold sets it: 6.4 mV, with 77 counts
    in 13:20 against 36 in 16:36.
  - The 13:20 edge triggers early. The 1 mV log-slopes are 0.71 and 0.50 /mV at 5.2 and 5.4 mV,
    then back above 1 at 5.6 and 5.8 mV (1.10, 1.03) [08].
  - Putting 16:36's 2.6-5.6 mV rates into 13:20 moves neither the edge (5.2) nor the optimum (6.8).
  - **Grid alone:** 13:20 thinned to 16:36's levels moves the optimum from 6.8 to 7.2 mV with both
    light scans. The edge stays at 5.2.
  - **Tail alone:** 13:20 with its rates from 7.2 mV up scaled by 0.59 gives 7.6 mV with both
    light scans. Scaled from 6.4 mV up, it gives 7.6 (light 13:59) and 6.8 (17:24).

### Hypothesis 1: grid and fit

- **Grid.** The 16:36 grid can move the optimum by 0.4 mV on its own: 13:20 thinned to 16:36's
  levels gives 7.2 [04].
- **Spread.** In simulation on one tube, the 16:36 rules widen and lift the optimum's
  distribution. With over-dispersed counting, the share at >= 7.6 mV is 43 % under the 16:36 rules
  against 26 % under the 13:20 rules [10, M0]. The coarse tail makes the fit's +-2 mV windows
  erratic.
- **Edge.** The grid does not move the edge.
- **What moves the optimum** is the background's log-slope over 6.4-7.6 mV, against the photon
  curve's 0.20 /mV [16]:
  - The driver's fitted slope is 0.39 /mV on 13:20 and 0.71 /mV on 16:36.
  - The tuned tubes have 0.35 (T1) and 0.62 (T2).
  - T1 with its dark part x0.59 still has 0.39, and its noise-free optimum stays at 6.8 mV.
  - So a scaled tail alone does not move the optimum; a steeper background does.
  - The real 16:36 scan measured that slope with five 30 s thresholds (6.0-7.2, then 9.2 mV), so
    it is poorly fixed. That is where method and physics are hardest to separate.

### Hypothesis 2: count-time structure (settling, bursts, mains, dead time)

- **The CSV does not log single count periods.** The live time is only a partial fingerprint.
  13:20 at 2.8 mV (227 counts in 60 ms) is consistent with 13 different period sequences [02a].
- **First-window factor kappa.** The driver's `_measure_point` was rerun 3000 times per point on
  the virtual bench, and the likelihood of each observed (live time, counts) was profiled [02b,
  `fig2_time_structure.svg`]. kappa is how many times faster the first 10 ms after a level change
  counts than the rest. kappa = 1 is inside the 95 % interval everywhere:

  | Scan | 2.6-3.6 mV | 3.8-6.0 mV |
  |---|---|---|
  | 13:20 | 1.0-2.0 | 0.5-3.0 |
  | 16:36 | 0.85-1.0 | 0.3-1.2 |

- **No rate change inside any threshold.** Ranked against 20 000 steady-rate runs, no threshold
  from 2.6 to 6.0 mV has p < 0.05 (18 per scan) [02c]. The Fisher statistics are 11.4 and 17.7
  on 36 dof. The test is conservative.
- **Settling goes the wrong way.** A settling effect reads high in *short* windows. The scan that
  reads higher, 16:36, used the *longer* windows at 3.0-3.6 mV, and at 2.8 mV the windows were
  identical.
- **Simulated DAC settling** (tau 1, 5, 20 ms), 60 Hz modulation of depth 0.5, and the measured
  overheads reproduce none of the curve differences [09]. The overheads are 2.8 ms per threshold
  plus 32.3 ms per period, rms 24 ms [02d].
- **What would resolve it:** logging every period, with its counts, length, time since the level
  change, and wall-clock time.

### Hypothesis 3: elapsed time within the scan

- **Drift and the tail slope cannot be separated.** A joint fit of both tails over 7.2-15.2 mV,
  with a common shape and a common drift, leaves the drift undetermined: -0.6 to +2.8 per 1000 s
  in ln(rate), at 95 % [03]. The first attempt ran to 40 mV. There the drift term bent the 13:20
  tail at 15.2 mV, where its time per mV drops, and gave a spurious 2.2 per 1000 s.
- **Simulated relaxations reproduce none of the curve differences.** A dark rate relaxing from x2
  to x1 with tau 600 s or 3000 s, the same before every scan, reproduces 0/300 of the tail, noise
  and 4-5.6 mV differences [09].
- **The scatter is not a slow drift.**
  - In 13:20 the 6.2-10 mV residuals alternate, with a lag-1 correlation of -0.28 [03].
  - A slowly modulated rate (correlation 300 s) is absorbed by the fit, and cannot reproduce the
    real held-out chi-square (P <= 0.03) [07].
- **The tail is over-dispersed, at a level that is the same across levels.**
  - In 13:20 the chi-square per threshold is 3.15 at ~37 counts per threshold and 2.20 at ~10
    counts.
  - Whole clusters of dark counts (compound Poisson, mean size m = 2, var/mean 3) reproduce both
    scans' held-out chi-square. The medians are 3.25 and 2.91, against the real 3.76 and 2.25,
    with P(>= real) of 0.38 and 0.59 [07].
  - A fast-modulated rate (sigma 0.35, 30 s) fits equally: median 3.44. The data cannot tell
    the two apart.
- **Unexplained:** 13:20 at 3.8-6.0 mV is *smoother* than Poisson. Its held-out chi-square is
  0.47; only 1.5 % of Poisson simulations, and none with clusters, are that smooth [07].

### Hypothesis 4: the noise-edge heuristic

- **The edge difference is in the curve.** Across limits of 0.8-1.2 /mV, baselines of 0.8-1.6 mV,
  and one or two levels below the limit, the noise-free tubes' edges always differ by 0.6-0.8 mV
  [08].
- **On the real scans it depends on the heuristic:** from 0.0 mV (limit 0.8, baseline 1.2) to
  1.2 mV (limit 1.0, baseline 1.6).
- **Counting noise spreads the edge.** Redrawn around each tube at the scans' own live times, it
  falls mostly at 5.0-5.6 mV for the 13:20-like tube (99 %; 5.2 in 64 %), and mostly at
  5.6-6.4 mV for the 16:36-like tube (97 %; 6.0 in 40 %).
  - Redrawn around the *observed* counts it hardly moves (5.2 in 95 %). That is the earlier "at
    most 0.2 mV" finding, and it understates the scatter of a repeated scan.

### What physics the unexplained differences need

- **Electronic noise at 2.5-6 mV changed between the scans; the PMT's dark rate is not that.** An
  extra component of ~5e3 counts/s at 2.8 mV, falling to ~2 counts/s at 5.6 mV and ~1 at 6 mV
  (T2 noise minus T1 noise), reproduces all three noise statistics [10, P2]:
  - z >= 16.4 at 3.0 mV: 29 % of pairs;
  - the 2.6-3.6 mV chi-square: 57 %;
  - the 4-5.6 mV ratio: 100 %; it overshoots, at 1.33-1.51.
- **It need not be steady.** Switching on and off at random, with mean on/off times of 900 s, it
  reproduces the three in 10 %, 32 % and 25 % of pairs [09].
- **Candidates**, none tested: pickup or ground currents from other bench equipment; the
  DISC-output pickup the manual warns of below 10 mV; a change in cabling.
- **A lower dark count rate in the tail** (x0.59), i.e. single-PE-like pulses. Candidates: the dark
  rate relaxing over hours after the HV was switched on or after light exposure (the 13:59 light
  scan used room light), or temperature. None is recorded: the HV-on time, the cover time and the
  room temperature were not logged.
- **Both changes together reproduce the whole pattern** [10, P0]. Tube T1 under the 13:20 rules
  against T2 under the 16:36 rules gives per-difference probabilities of 27-53 %, and 5.5 % for
  all four together (edge, optimum, tail, 4-5.6 mV). By likelihood ratio, the exact observed
  outcomes favour the changed tube:

  | Exact outcome | Changed tube (T1 then T2) | Same tube (method only) | Ratio |
  |---|---|---|---|
  | Optimum 6.8 then 7.6 mV, both light scans | 8.5 % | 0.5 % | ~17 |
  | Edge 5.2 then 6.0 mV | 13.5 % | 0.75 % | ~18 |

  [10, M0 against P0]

## The simulated tube, and how well it matches

- **Harness** (`harness.py`):
  - The bench's `VirtualSR400` is imported by path, with a one-line `pysweepme` stub, and
    subclassed onto a virtual clock. It is not modified.
  - The driver's `_measure_point`, `_ceil_count_time`, `_scan_setup`, `threshold_grid`,
    `analyse_dark`, `analyse_light` and `_smooth_dark_rate` run unchanged, on private copies of
    `selftest.py` whose constants set each rule set.
  - The scan loop mirrors `run_threshold_scan_dark`, plus the 13:20 stop-after-3-zeros rule.
- **Tube model:**
  - noise: a tabulated roll-off;
  - dark: an exponential tail, with a flat large-pulse tail above 16 mV;
  - options: clusters, OU modulation, a relaxation, telegraph extra noise, 60 Hz modulation, DAC
    settling, and a first-window factor.
- **Tuning:**
  - T1 and T2 are each tuned to one real scan, through the driver's own smoother below 3.8 mV and
    a Poisson fit of noise plus exponential dark at 3.8-15.2 mV [05].
  - Over-dispersion: clusters of mean size 2 [07].
- **Fit to the data,** chi-square per threshold of each real scan against its tube:

  | Tube | 0.4-2.4 | 2.6-3.6 | 3.8-6.0 | 6.2-10 | 10.2-15.2 mV |
  |---|---|---|---|---|---|
  | T1 (13:20) | 1.12 | 1.26 | 0.40 | 3.15 | 2.20 |
  | T2 (16:36) | 1.58 | 4.20 | 1.87 | 1.00 | 1.35 |

  The tail values are the over-dispersion that the clusters reproduce.
- **Noise-free,** T1 and T2 give exactly the real scans' edges (5.2, 6.0 mV) and optima (6.8,
  7.6 mV, both light scans) [06].
- **Scan durations** are within 1 % (13:20 rules: 1265 s simulated against 1278 s real) and 4 %
  (16:36 rules: 466 s against 484 s).
- **Not modelled:**
  - the light scans' noise, except in [12];
  - the 16:36 noise structure in detail: T2 against 16:36 at 2.6-3.6 mV is 4.2 per threshold.

## Recommended sampling, and its cost

The target: two independent sessions give optima within the 0.2 mV discriminator step. In the
simulations below, the light curve is noise-free on a 0.2 mV grid and the tube has the tuned
over-dispersion [11, 11b, 11c, `fig5_sampling_cost.svg`].

1. **The background fit must stop narrowing above 6 mV. This is a proposed analysis change, for
   the main session.**
   - With the driver's fit as it is, more counting barely helps. P(two scans within 0.2 mV)
     rises only from 0.26 (11 min) to 0.66 (12 h) on T1 with light 13:59, and from 0.23 to 0.66
     on T2.
   - The cause: once a +-1 mV tail window holds >= 800 counts, `_smooth_dark_rate` narrows it to
     a quadratic on ~800 counts. Longer dwell therefore stops reducing the noise.
   - With the straight line kept from 6 mV up and the driver's fit below (`tail_line` in 11b),
     the same scans converge.
   - The noise-free optimum moves only on T2, from 7.4 to 7.6 mV.
2. **The light scan needs 0.2 mV steps over 6-10 mV.** It now steps 0.4 mV above 6 mV, so its
   optimum cannot be finer than 0.4 mV. The extra 10 levels cost seconds at 3e5 counts/s.
3. **Dark scan, with the fit change.** P(two scans within 0.2 mV), with the light 13:59 and 17:24
   stand-ins [11b]:

   | Dark scan | Time | T1: 13:59 / 17:24 | T2: 13:59 / 17:24 |
   |---|---|---|---|
   | current scan as it is | 11 min | 0.28 / 0.37 | 0.23 / 0.24 |
   | + one extra pass over 5.6-10 mV, 0.4 mV grid, 120 s per level | 57 min | 0.54 / 0.88 | 0.53 / 0.52 |
   | 0.2 mV grid over 5.6-10 mV, 4 passes x 60 s | 97 min | 0.76 / 1.00 | 0.83 / 0.85 |
   | 4 x 120 s or 2 x 240 s | 189 min | 0.84-0.86 / 0.97 | 0.92-0.93 / 0.94 |
   | 2 x 480 s | 374 min | 0.93 / 0.97 | 0.96 / 0.96 |

   **About 3 hours of dark counting reaches >= 0.9 in three of the four tube x light cases. 13:59
   light on T1 needs ~6 hours.** The cause is that tube's flat top: 6.6 mV is 0.11 % below 6.8.
4. **Repeats beat dwell when the rate drifts.** T1 with a dark rate relaxing x2 -> x1 (tau
   3000 s), ~190 min in every case, straight-line tail fit [11c]:

   | Passes x dwell | P(within 0.2 mV): 13:59 / 17:24 | P(within 0.2 mV of the truth): 13:59 / 17:24 |
   |---|---|---|
   | 1 x 480 s, one upward pass | 0.91 / 0.84 | **0.00 / 0.04** (every run near 7.6; the truth is 6.8) |
   | 2 x 240 s | 0.70 / 0.94 | 0.28 / 0.97 |
   | 4 x 120 s | 0.77 / 0.97 | 0.79 / 0.98 |
   | 8 x 60 s, alternately down and up | **0.91 / 0.98** | **0.95 / 0.99** |

   Without drift, 2 x 240 s and 4 x 120 s are equivalent (0.86 against 0.84). So the
   recommendation is **many short alternating passes, not long dwell**.
5. **The 0.4 mV dark grid is enough in principle,** because B is a fit evaluated at the light
   levels. With the drift above, the 0.2 mV grid and 8 passes was the configuration tested.

**Recommendation, if reproducibility to 0.2 mV is required:**
- the straight-line tail fit above 6 mV;
- light-scan steps of 0.2 mV over 6-10 mV;
- after the normal dark scan, 7 further alternating passes over 5.6-10 mV at 0.2 mV and 60 s per
  level. That is ~190 min of dark scan, against 11 min now.

**The cheaper alternative, which the simulations favour on cost:** stop chasing the argmax. Either
report the band, or set the level from a plateau rule: 7.2 mV scores >= 0.97 of the best on both
tubes with both light scans [15].
- The current 11-min scan (current rules, over-dispersed tube, 0.2 mV light stand-ins) picks a
  level scoring 0.93-0.94 of the best on average [15, 11b driver fit].
  - Its worst 5 % score <= 0.59-0.62. These are runs whose optimum lands at or above 10 mV, where
    the 10 mV floor's 2 mV steps begin.
  - With the real 0.4 mV light scans and the 13:20 or 16:36 rules, the average is 0.92-0.97
    (10, M0).
- The 57-min option with the fit change scores 0.988-0.995 on average, and >= 0.968 in its worst
  5 %.

**Proposed driver changes, for the main session to decide; none is made here:**
1. In `_smooth_dark_rate`, allow the curvature narrowing only below ~6 mV, or only where the
   straight line is rejected far more strongly than LR > 4 [11b].
2. A 0.2 mV light grid over 6-10 mV.
3. An optional "optimum refinement" stage: alternating dark passes over 5.6-10 mV [11c].
4. Log every count period [02b].

## What is still unknown, and what would settle it

- **Is the 2.6-6 mV excess electronic?** Run a dark scan of 2-7 mV with the HV off, or the anode
  replaced by a 50 ohm terminator, at the start and end of a session, beside the normal dark scan.
  An excess that appears without the PMT is pickup. Moving the DISC output cables would test the
  manual's warning.
- **Does the dark rate relax over hours?** Count at a fixed level, e.g. 8 mV for 60 s every 10 min,
  from HV-on through the session, with the HV-on, cover and light-exposure times written down.
  This separates a between-scan change from within-scan drift. The scans cannot do that: their
  joint fit allows -0.6 to +2.8 per 1000 s.
- **Clusters or a modulated rate?** The over-dispersion could be either. Count 1000 windows of
  0.1 s and 100 of 10 s at 8 mV and compare var/mean against window length. Clusters give a
  constant excess above the cluster duration; a modulated rate gives an excess that grows with the
  window.
- **First-window effects at the level change.** Log every count period (counts, length, time since
  `DL`). The CSV cannot resolve this, and the fingerprint bounds kappa only to ~0.85-2.
- **Why 13:20 is smoother than Poisson at 3.8-6 mV** (held-out chi-square 0.47).
- **The model's own limits.**
  - The decomposition of the 4-8 mV background into noise and dark is not well fixed: the two
    tubes' dark slopes are 0.29 and 0.16 /mV.
  - Two scans of one tube on one day.
  - The over-dispersion model was tuned on 14 tail thresholds.

## Files

All scripts run with an isolated interpreter (`python -I <script>`) from this folder, standard
library only. Each campaign is seeded by a string (campaign, rule, run index), so it is
reproducible. `out/` holds every raw run and level (~43 MB). It is kept on the disk where the
study was run but **not committed**: at that size it would stay in the public repository's
history for good, and the seeded scripts regenerate it. The figures are drawn from it.

| File | What it does |
|---|---|
| `dsm_common.py` | loaders, Poisson deviates, held-out chi-square, common-ratio fit, fine light stand-ins |
| `harness.py` | the study harness: `StudySR400` (bench subclass), `Tube`, `SimDevice`, rule sets, scan loop |
| `campaign.py` | campaign runner (seeded), pair statistics and summaries |
| `01_real_scans_compare.py` | real ratios, z, regions, driver results for the 4 pairings |
| `02a_period_paths_enumeration_deadend.py` | **dead end**: exhaustive period paths (combinatorial, abandoned) |
| `02b_period_fingerprint_sim.py` | first-window factor kappa from the live-time fingerprint |
| `02c_within_threshold_stationarity.py` | steady-rate test inside each threshold |
| `02d_overhead.py` | per-threshold and per-period overheads (corrects an off-by-one in 02b) |
| `03_tail_shape_time_dispersion.py` | tail shape against eps, drift fit, over-dispersion (first attempt kept in `out/03_stdout_first_attempt.txt`) |
| `04_real_data_counterfactuals.py` | grid-only, tail-only and spliced real scans |
| `05_build_tubes.py` | tubes T1 and T2 from the real scans, and their check |
| `06_method_only_poisson.py` | three rule sets on one tube, Poisson, 400 runs each |
| `07_overdispersion_tuning.py` | clusters and modulation against the real held-out chi-square |
| `08_edge_heuristic_sensitivity.py` | slopes, heuristic variants, resampling |
| `09_method_with_effects.py` | settling, drift, intermittent noise, mains |
| `10_physics_campaigns.py` | changed-tube scenarios P0-P3 and method-only M0 |
| `11_sampling_design.py`, `11b_sampling_vs_fit.py`, `11c_repeats_vs_dwell.py` | sampling design, the fit's narrowing, repeats against dwell |
| `12_light_noise.py` | the light scan's own counting noise in the optimum |
| `14_fom_flatness.py`, `15_optimum_cost.py`, `16_background_slopes.py` | flatness of S/sqrt(B), the cost of a wrong optimum, what moves it |
| `13_figures.py` | `fig1_real_scans.svg` ... `fig5_sampling_cost.svg`, from `out/` only |

`12_light_noise.py`: redrawing the light scans' own counts leaves the optimum unchanged in 85-100 %
of draws against the noise-free tubes. The exception is the 16:36-like tube with light 17:24, at
60 %. The light scan is a smaller but not negligible source.
