# Discriminator level when the signal brings an inseparable photon background

**PROVISIONAL.** The scans are the same four 2026-11-10 scans as `../low_signal_threshold/` (two
dark, two room-light; R8486 at ~1000 V). The photon background is a **model**, not a measurement.
Every number below comes from `photon_background.py` run on the raw CSVs. `summary.txt`, the CSVs
and the figures hold them in full.

**The operator's situation (2026-11-11).**

- The signal of **N photons/s** brings a photon background at an **assumed fraction f** of it
  (0.01 % to 50 %): stray light, scatter or fluorescence.
- The background has the signal's pulse heights, so no threshold can separate it from the signal.
- It is **absent from the signal-off run**, which measures the dark rate only.

The estimate is therefore

    N_hat = (C_on - C_off) / (eps * (1 + f) * T)

using the assumed f.

N is defined as in the low-signal analysis: the signal counts/s at the valley level (4.0 mV in the
13:59 light scan, 3.8 mV in the 17:24 one). T is the length of each run, so the clock time is 2T.

## The answer

**1. Set the threshold as if there were no photon background, for a signal of N' = N (1 + f).**
For f up to 10 % that is the photon-free level itself, except where N sits next to a step: at
N = 200 the level drops from 5.6 to 5.0 mV between f = 1 % and 3 %, a near-tie. At f = 50 % it is
at most 0.6 mV lower. The uncertainty on f does not move the best level at all.

**2. Whether a "good enough" level is good enough depends on how you use the time.**

- *If you count until you reach a target total precision p*, the threshold matters exactly as much
  as without any photon background. The levels within 5 % of the best counting time are the same
  for every delta_f; only the times grow, by 1 / (1 - floor^2/p^2), and never arrive if p is at or
  below the floor.
- *If your counting time is fixed*, the threshold matters less and less once the counting noise
  falls below the systematic floor. That is where the photon background really takes the
  emphasis off small dark counts. The crossover time is **T_cross = V(best) / floor^2**, where V
  is the relative variance per second of counting at the best level; it is the time at which the
  counting noise at the best level equals the floor.

**Headline table: f = 10 % +- 3 % (delta_f = 30 % of f, floor 2.7 %), signal-off run as long as the
signal run, one level for all four dark x light pairings.**

| N (counts/s at the valley) | set | type in the GUI | within 5 % of the best **time** to any p | T_cross (each run) | within 5 % of the best **total precision** after T_cross | after 10 x T_cross | time to total 10 % (each run) |
|---:|---:|---:|---|---:|---|---|---:|
| 1    | 6.8 mV | -0.0068 | 6.8 mV only | 6800 s | 6.4-7.6 mV | 5.6-9.2 mV | 440-670 s |
| 10   | 6.4 mV | -0.0064 | 6.0-6.8 mV | 210 s | 5.8-7.2 mV | 5.0-9.2 mV | 16-18 s |
| 100  | 5.6 mV | -0.0056 | 4.8-6.4 mV | 15 s | 4.6-6.8 mV | 4.0-9.2 mV | 1.2 s |
| 1000 | 4.6 mV | -0.0046 | 4.0*-5.8 mV | 1.3 s | 4.0*-6.4 mV | 4.0*-8.8 mV | 0.10-0.11 s |

\* 4.0 mV is the valley, the lowest level scored. Below it, light minus dark is not photon counting
(see `../low_signal_threshold/`).

**How to read a row** (N = 10/s, f = 10 % +- 3 %):

- Set 6.4 mV (type -0.0064).
- If you count about 210 s per run, any level from 5.8 to 7.2 mV gives a total precision within 5 %
  of the best.
- If you count 2100 s per run, anything from 5.0 to 9.2 mV does. By then the total is close to the
  2.7 % floor at every level, so neither the threshold nor the extra time helps much.
- Reaching a total of 10 % takes 16-18 s per run.

"T_cross" in the table is the time common to all four pairings (the geometric mean of their
T_cross, to two significant figures). The ranges are those that hold in all four pairings at
once. The time ranges cover the four pairings.

**Other delta_f at f = 10 %** (`operator_table.csv`):

| N | delta_f | floor | T_cross | within 5 % after T_cross | after 10 x T_cross | time to total 10 % |
|---:|---|---:|---:|---|---|---:|
| 10  | 10 % of f (+-0.01) or 1 % absolute | 0.91 % | 1900 s | 5.8-7.2 mV | 5.0-9.2 mV | 15-17 s |
| 10  | 5 % absolute (+-0.05) | 4.5 % | 77 s | 5.8-7.2 mV | 5.0-9.2 mV | 19-21 s |
| 10  | 100 % of f (+-0.1) | 9.1 % | 19 s | 5.8-7.2 mV | 5.0-9.2 mV | 87-96 s |
| 100 | 10 % of f or 1 % absolute | 0.91 % | 130 s | 4.6-6.8 mV | 4.0-8.8 mV | 1.1 s |
| 100 | 5 % absolute | 4.5 % | 5.3 s | 4.6-6.8 mV | 4.0-8.8 mV | 1.4 s |
| 100 | 100 % of f | 9.1 % | 1.3 s | 4.6-6.8 mV | 4.0-8.8 mV | 6.2-6.4 s |

The set level and the time-to-p band are those of the headline table for every delta_f. A larger
delta_f only shortens T_cross. The ranges at a given multiple of T_cross are the same, up to the
rounding of T to two significant figures: at N = 100, 10 x T_cross gives 4.0-9.2 mV for
delta_f = 30 % of f but 4.0-8.8 mV for the others.

**f = 1 % and f = 50 %, both with delta_f = 30 % of f:**

| N | f +- delta_f | floor | set | within 5 % of the best time | T_cross | within 5 % after T_cross | time to total 10 % |
|---:|---|---:|---:|---|---:|---|---:|
| 1    | 1 % +- 0.3 % | 0.30 % | 6.8 mV | 6.8 mV only | 660000 s | 6.4-7.6 mV | 470-720 s |
| 10   | 1 % +- 0.3 % | 0.30 % | 6.4 mV | 6.0-6.8 mV | 20000 s | 5.8-7.2 mV | 17-19 s |
| 100  | 1 % +- 0.3 % | 0.30 % | 5.6 mV | 5.0-6.4 mV | 1400 s | 4.6-6.8 mV | 1.2 s |
| 1000 | 1 % +- 0.3 % | 0.30 % | 4.6 mV | 4.0*-5.8 mV | 120 s | 4.0*-6.4 mV | 0.11 s |
| 1    | 50 % +- 15 % | 10 % | 6.8 mV | 6.8 mV only | 300 s | 6.4-7.6 mV | **never** |
| 10   | 50 % +- 15 % | 10 % | 6.0 mV | 5.8-6.8 mV | 11 s | 5.6-7.2 mV | **never** |
| 100  | 50 % +- 15 % | 10 % | 5.6 mV | 4.6-6.0 mV | 0.78 s | 4.4-6.8 mV | **never** |
| 1000 | 50 % +- 15 % | 10 % | 4.4 mV | 4.0*-5.8 mV | 0.07 s | 4.0*-6.4 mV | **never** |

At f = 50 % +- 15 % the systematic floor is 10 %, so no counting time and no threshold reaches a
total of 10 %. The time to total 5 % or 20 % for every case is in `total_uncertainty.csv`.

**The level against N and f** (one level for all four pairings, signal-off run as long as the
signal run; `robust_choice.csv`):

| N | f <= 3 % | f = 10 % | f = 20 % | f = 50 % |
|---:|---|---|---|---|
| 1     | 6.8 | 6.8 | 6.8 | 6.8 |
| 10    | 6.4 | 6.4 | 6.4 | 6.0 |
| 50    | 5.8 | 5.8 | 5.8 | 5.6 |
| 100   | 5.6 | 5.6 | 5.6 | 5.6 |
| 200   | 5.6 (f <= 1 %), 5.0 (f = 3 %) | 5.0 | 5.0 | 5.0 |
| 500   | 5.0 | 5.0 | 4.8 | 4.6 |
| 1000  | 4.6 | 4.6 | 4.4 | 4.4 |
| 10000 | 4.0* | 4.0* | 4.0* | 4.0* |

All values are in mV. With the dark rate known from a long separate run, the levels are 0-0.6 mV
lower, as in the photon-free case (`summary.txt`). **Every level here is below 10 mV**, so it is
valid only with the cables routed as during the scans (SR400 manual p. 22).

## How much emphasis does the photon background take off the dark counts?

Honestly, three answers, depending on the question.

**On the best level: little.**

- The photon background acts like a brighter signal, by at most a factor 1.5 at f = 50 %.
- From f = 0 to f = 50 % the best level moves by at most 0.6 mV (at N = 200), and by 0.2-0.4 mV
  at N = 10, 50, 500 and 1000. Elsewhere it does not move.
- The cost of a dark-heavy low level falls only a little. At N = 10, 4.4 mV costs x3.9 the best
  counting time at f = 0 and x3.0 at f = 50 % (worst case over the pairings). At N = 1 it is
  x11.8 and x10.2.
- The cost of a high, dark-suppressing level rises slightly: 7.6 mV at N = 10 goes from x1.21
  to x1.26.

**On the counting statistics: it helps.** In this model the background photons are counted with
the signal, and the estimate divides them back out with the assumed f. So they add information
about N as well as counts.

- The statistical time to 10 % *falls* at f = 50 %, to x0.49-0.66 of the photon-free time
  (x0.49 at N = 1, x0.66 at N >= 1000).
- The whole cost of the background is the systematic delta_f / (1 + f). This assumes f is
  constant; see Caveats.

**On total precision at a fixed counting time: this is where it matters.** The near-best range
depends only on T / T_cross. On the 13:20 + 13:59 pair, at f = 10 % (`flatness_fixed_time.csv`),
the range within 5 % of the best total precision is:

| N | best | T = 0.1 x T_cross | T = T_cross | T = 10 x T_cross |
|---:|---:|---|---|---|
| 1    | 6.8 mV | 6.4-7.6 mV (1.2 mV wide) | 5.8-7.6 mV (1.8) | 5.2-9.6 mV (4.4) |
| 10   | 6.0 mV | 5.6-6.8 mV (1.2) | 5.4-7.6 mV (2.2) | 4.6-9.6 mV (5.0) |
| 100  | 5.6 mV | 4.6-6.4 mV (1.8) | 4.4-6.8 mV (2.4) | 4.0-9.2 mV (5.2) |
| 1000 | 4.6 mV | 4.0-6.0 mV (2.0) | 4.0-6.4 mV (2.4) | 4.0-8.8 mV (4.8) |

- At T = T_cross the acceptable range is 1.2-1.8x as wide as at 0.1 x T_cross, where the
  statistics still dominate.
- At 10 x T_cross it is 2.4-4.2x as wide, and reaches 8.8-9.6 mV, where dark counts are low but
  photons are lost.
- Exact rule: a level is within 5 % of the best total precision when
  V(v)/V(best) <= 1/0.95^2 + (1/0.95^2 - 1) x T/T_cross. This was checked against the direct
  calculation in 12628 of 12628 cases.

**Where the photon background out-noises the dark counts** (`fig_f_equal_dark.svg`). This is
the f at which, at the best level, the photon background counts equal the dark term (f eps N = 2b
with an equal-length off run):

| N | f (range over the four pairings) |
|---:|---|
| 1     | 2.3-4.3: beyond the operator's range, so dark noise always dominates |
| 10    | 0.29-0.68 |
| 100   | 0.08-0.09 |
| 1000  | 0.03-0.06 |
| 10000 | 0.012-0.019 |

Above that f, dark suppression no longer limits the counting noise. Even then it does not move
the best level beyond N -> N (1 + f).

## The scaling result, and where it is not exact

**Statistical part.** Var(C_on - C_off) = (eps N (1+f) + 2b) T, so the relative variance of N_hat
per second is

    (eps N' + 2b) / (eps N')^2,   with N' = N (1 + f)

That is exactly the photon-free relative variance at N'. With the dark known precisely, 2b
becomes b and the same N' applies.

Checked on all four pairings and both cases, over 92 N values from 1 to 1e4 and seven f values,
5152 cases in all:

- The per-level variance ratio deviates from 1 by at most 7.8e-16.
- The best level, the 5 % band edges and the valley-floor flags are identical in all 5152 cases.
- The one-level-for-all-four choice and its common band are identical in 154 of 154 cases.

**The valley floor** does not break it. The candidate levels are the same set at (N, f) and at
N', so whenever the band or the optimum reaches the valley it does so for both (1700 of 5152
cases for the band). **Discreteness** does not break it either, because both are evaluated on the
same measured grid.

**It is not exact when you look the answer up in a coarse table.** Reading the photon-free answer
for N' off the nearest row of a table tabulated at N = 1, 2, 5, 10, ... 10000 gives a different
level in 314 of 1134 cases, by up to 0.6 mV. That is the table's discreteness, not the model.
This analysis evaluates N' directly.

**Systematic part.** If the true fraction is f and the assumed one is f_a,

    E[N_hat] / N = (1 + f) / (1 + f_a)

So the relative bias is (f - f_a) / (1 + f_a) at every level: eps cancels. To first order the
systematic is delta_f / (1 + f), and no threshold reduces it.

**A Monte Carlo of the on/off estimate confirms both parts.** It used Poisson draws for the 13:20 +
13:59 pair at N = 10/s, f = 0.1, T = 100 s, six levels, 20000 trials each, with f_a = 0.10 and
0.13.

- The bias agreed with (f - f_a)/(1 + f_a) = -2.65 % within 1.5 Monte Carlo standard errors at
  every level.
- The spread agreed with the formula to 1.0 % (Monte Carlo precision about 0.5 %).

**Total.** sigma_tot^2 = V/T + floor^2, so T_p(v) = V(v) / (p^2 - floor^2). The factor
1/(p^2 - floor^2) is the same at every level. So the levels within 5 % of the best time are the
statistical 5 % band for every delta_f: 2992 of 2992 cases agree.

## Contrast: a photon background that the signal-off run does see

If the background is present in both runs (for example stray room light) and on/off removes it,
there is no systematic. The variance becomes (eps N (1+2f) + 2b)/(eps N)^2, which scales the same
way with N' = N (1 + 2f): a brighter equivalent signal, by up to x2. For example, on the 13:20 +
13:59 pair at N = 100, f = 0.5, the best level is 5.0 mV for a subtractable background against
5.6 mV for an inseparable one. That is not the operator's case.

## Caveats, and what would change the answer

- **The background's pulse heights might differ from the signal's.** Everything above assumes the
  threshold keeps the same fraction eps(v) of background as of signal. If the background keeps
  eps_bg(v) instead, the estimate's relative bias becomes f (eps_bg(v)/eps(v) - 1)/(1 + f), and
  it then **depends on the level**. The threshold could then reduce the bias, or increase it.
  - *Multi-photon pile-up* (several photoelectrons in one pulse, for example from a pulsed
    source) makes bigger pulses: eps_bg > eps at high levels, so a high threshold keeps relatively
    more background. Random pile-up is negligible at these rates (5 ns x 1e4 counts/s = 5e-5).
  - *Light-induced small-pulse counting*, like the excess measured below the valley with room
    light (38-41 % of the valley rate at 2.2 mV), makes smaller pulses: a higher threshold
    removes more of it. Only levels from the valley up are scored here, and the room-light eps(v)
    already contains whatever of it survives there.
  - **What would tell.** First, measure N_hat at two or more thresholds in the real experiment:
    if the spectra match, N_hat agrees across levels within its statistics; a trend with level is
    a spectral difference. Second, take a threshold scan with the real signal and background, and
    compare its shape, normalised to the valley, with the room-light eps(v). Excess above about
    10 mV would point to pile-up; excess near the valley would point to light-induced counting.
    No such data exists yet, and none is assumed here.
- **f might not be constant.** If f fluctuates between or during runs, that adds variance that
  this model does not include. A level-independent systematic still cannot be reduced by the
  threshold.
- **f and delta_f come from outside this analysis.** The whole systematic budget rests on them.
  The operator assumes f, it cannot be measured with these scans, and delta_f is the honest
  statement of that assumption.
- **Inherited from the low-signal analysis:**
  - the two dark scans disagree by a real factor of 0.59 in the tail, which is the main spread
    between pairings;
  - no level below the valley is trusted;
  - levels are on the scanned grid (0.2 mV steps below 6 mV, 0.4 mV above);
  - every level here is below 10 mV, so it holds only with the cables as they were;
  - the HV of the second pair is not recorded.

  The counting-statistics resampling of the low-signal analysis applies at N' and is not
  repeated here.

## Reproduce

From this folder, with Python 3.10 or later (standard library only):

```bash
python -I photon_background.py
```

It reads the four scan CSVs in place: the first pair from `docs/real_data/2026-11-10/`, the second
from `analysis/low_signal_threshold/data/`. It loads `Logger-Stanford_SR400/selftest.py` by path
without modifying it, and it is seeded, so reruns are byte-identical.

## Files

| File | What it is |
|---|---|
| `photon_background.py` | the analysis; regenerates every file below |
| `results.csv` | pairing x figure of merit x N (1-10000) x f (0, 1e-4 ... 0.5): statistical optimum, 5 % band, floor flags, eps, b, photon background counted, time to 10 % at the optimum and fixed levels, and the photon-free optimum at N' with a match flag |
| `total_uncertainty.csv` | pairing x figure of merit x N x f x delta_f: systematic floor, T_cross, time to a total of 5 / 10 / 20 %, the time-to-p band, the near-best range after T_cross and 10 x T_cross |
| `operator_table.csv` | the operator tables above (one level for all four pairings) |
| `robust_choice.csv` | one level for all four pairings, per N, f and figure of merit |
| `flatness_fixed_time.csv` | the near-best range against T / T_cross |
| `summary.txt` | machine-written: every check and table |
| `fig_optimum_N_f.svg` | best level on the N-f plane (heat map), with lines of constant N'; and the level with its common 5 % band against N, at f = 0, 0.1, 0.5 |
| `fig_total_time_vs_level.svg` | time to a total of 10 % against level for each delta_f, and time against p, diverging at each floor |
| `fig_flatness_fixed_time.svg` | the near-best range and its width against T / T_cross |
| `fig_f_equal_dark.svg` | the f at which the photon background matches the dark term, against N |
