# Simulated versus real threshold scans

The [threshold-scan guide](THRESHOLD_SCAN_GUIDE.md) is illustrated with figures from the driver's
**simulated** R8486 ([`images/`](images/)). This page sets each of those figures beside the **first
real scans** of the tube, taken on 2026-11-10 ([`real_data/2026-11-10/`](real_data/2026-11-10/)).
It goes panel by panel, says what the simulator gets right and wrong, and says what each
difference means when you read your own figure.

Every number below is computed by the driver's current analysis from the raw CSVs, not read off
a figure. All four figures are regenerated from their CSVs by `selftest.py plot`, and the test
bench fails if a committed figure differs from what the code draws.

**Conditions of the real scans.** R8486 on SIGNAL INPUT 1, discriminator A, slope FALL; SR400 over
GPIB (NI GPIB-USB-HS); SweepMe! 1.5.7.9. Dark: tube covered. Light: room light, 3.3e5 counts/s at
6 mV. The PMT high voltage is not recorded in these files.

**The simulated examples predate two driver changes**, so their sampling differs from a scan
made today. They were recorded before fast thresholds counted to 500 and before the dark scan
switched to 2 mV steps below 1 counts/s. The analysis drawn on them is current.

---

## Dark scan

| Simulated | Real, 2026-11-10 |
|---|---|
| ![Simulated dark threshold scan](images/example_threshold_scan_dark.svg) | ![Real dark threshold scan, 2026-11-10](real_data/2026-11-10/SR400_threshold_scan_dark_2026-11-10_132008.svg) |

### Panel (a): dark count rate above each threshold

| | Simulated | Real |
|---|---|---|
| Rate at 0.4 mV | 6.4e6 counts/s, the maximum | 3.9e4 counts/s |
| Shape below 2 mV | falls monotonically from the lowest level | **rises** to a hump, 2.3e5 counts/s at 1.2 mV, then falls |
| Above 1e6 counts/s ("oscillation" shading) | up to 1.0 mV | never reached: no shading |
| Rate at 3 / 5 / 6 mV | 3.8e3 / 18.7 / 6.5 counts/s | 741 / 7.9 / 2.4 counts/s |
| Rate at 8 / 10 / 14.8 mV | 4.7 / 3.4 / 0.79 counts/s | 1.6 / 0.36 / 0.17 counts/s |
| Noise edge, lower bound | 5.2 mV, 5.8 mV | 5.2 mV, 5.8 mV (GUI `-0.0058`) |
| Dark counts vanish (zero in 30 s) | from 20.0 mV | from 32.0 mV |

**What differs, and what it means:**

- **The real noise does not keep rising as the threshold drops: it has a hump.** Below about
  1.2 mV the real count rate *falls* as the threshold is lowered. The simulator has no such hump.
  This is what broke the first version of the noise-edge search: it read the rising part as
  "flat" and reported 1.0 mV. That is the lower bound printed in the real scan's own report
  (`SR400_threshold_scan_dark_2026-11-10_132008.txt`, made by the driver as it was then). The
  search now starts at the hump's peak. On a real figure, ignore everything left of the hump.
- **The real tail is about ten times lower than the simulator's above 8 mV**, and it reaches
  zero later. The simulator gives dark pulses the same sizes as single-photon pulses, so its tail
  follows the single-PE spectrum. The real tail falls much faster than that. The inference,
  not yet tested, is that most real dark pulses are smaller than a single photoelectron's. Either
  way, the simulator's dark tail is not a model of this tube. The noise edge coincides at 5.2 mV in both,
  but treat that as a coincidence, not a validation.
- **Both put the lower bound at 5.8 mV.** In the real scan the roll-off has two slopes: steep
  (3.9–4.8 per mV in log-rate) from 2.0 to 2.8 mV, then 1.2–2.2 per mV from 3.2 to 5.0 mV, before
  the dark tail flattens to 0.3–0.7 per mV. The "flat" limit of 1.0 per mV was chosen from this scan.
  It is provisional until more scans confirm it.

### Panel (b): live time per threshold

| | Simulated | Real |
|---|---|---|
| Thresholds, range | 57, 0.4–24 mV | 63, 0.4–36 mV |
| Live time | 16.7 min | 21.1 min |
| At the 30 s cap | 29 thresholds | 39 thresholds, 93 % of the time, from 5.2 mV up |

The real scan spent most of its time on a tail of 0–3 counts per threshold, which sets no bound.
That is why the dark scan now steps 2 mV once the rate is below 1 counts/s at two thresholds in
a row. Replayed on these rates, the current rules take 15.6 min.

---

## Light scan

| Simulated | Real, 2026-11-10 |
|---|---|
| ![Simulated light threshold scan](images/example_threshold_scan_light.svg) | ![Real light threshold scan, 2026-11-10](real_data/2026-11-10/SR400_threshold_scan_light_2026-11-10_135935.svg) |

The real light scan was **recorded without its dark scan**: the dark result was held only in
memory and was lost when SweepMe! restarted. Its own report
(`SR400_threshold_scan_light_2026-11-10_135935.txt`) therefore recommends the valley, 4.0 mV. The
figure above was regenerated with the dark scan found beside it, which is what the driver now
does on its own.

### Panel (a): count rate, every pass

| | Simulated | Real |
|---|---|---|
| Rate at 0.4 mV | 6.4e6 counts/s, the maximum | 4.5e4 counts/s |
| Maximum | at 0.4 mV | 5.9e5 counts/s at 2.0 mV (the noise hump again) |
| Rate at the reference level | 3.9e4 counts/s at 4.8 mV | 3.8e5 counts/s at 4.0 mV |
| Drift over the scan | 0 % (not modelled) | 0.90 %, within the 2 % tolerance |
| Hysteresis, up minus down | 0 (not modelled) | +0.031 ± 0.011 mV, not flagged |

The real light was about ten times brighter than the simulated one and above the 2e5 counts/s
warning. At the SR400's 5 ns pulse-pair resolution that costs about 0.2 % of counts, which is
below the scan's ±0.5 % resolution. It is still better to dim the source next time.

### Panel (b): counts relative to the reference level

| Count loss vs the reference | Simulated (reference 4.8 mV) | Real (reference 4.0 mV) |
|---|---|---|
| 0.1 % | not separable (±0.09 mV) | not separable (±0.12 mV) |
| 1 % | 5.0 ± 0.1 mV | 4.2 ± 0.1 mV (GUI `-0.0042`) |
| 2 % | 5.2 ± 0.1 mV | 4.6 ± 0.1 mV |
| 5 % | 5.6 ± 0.1 mV | 5.0 ± 0.1 mV |
| 10 % | 6.4 ± 0.1 mV | 5.6 ± 0.1 mV |

The two curves have the same shape: neither has a flat plateau above the valley. The real curve
falls by about 1 % per 0.2 mV discriminator step from the start.

**Why 0.1 % is refused in both.** A count loss is the difference between two Poisson rates. With
about 7e4 counts per level, as in both scans, that difference is uncertain by ±0.5 %, so a 0.1 %
loss cannot be told apart from the reference. Separating it needs about 8e6 counts per level,
about a hundred times what this scan collected per level over its six passes. The figure says this instead of
printing a level.

### Panel (c): pulse-height density, light and dark

| | Simulated | Real |
|---|---|---|
| Valley | 4.8 mV | 4.0 mV |
| Single-PE peak | 10.0 mV | 8.0 mV |
| Peak / valley | 2.0 | 3.45 |
| Density ≤ 0 (rate rising with level) | nowhere | 0.4–2.0 mV, shaded |

The real tube separates single photons from noise **better** than the simulator assumes: its
valley is deeper relative to its peak. Both its valley and its peak sit lower in voltage.

Panel (c) now plots the **dark** scan's density alongside the light, on a log axis, because the
light density is about 1e4 times the dark. In the real figure the dark density falls to about
1 count/s per mV by 6 mV, where the light's is 3.7e4: more than four decades apart. The region where the light rate rises
with the level has no meaning as a density, so it is shaded and named rather than drawn. The
count-loss levels, with their uncertainties and GUI values, are in the box under the panel.

### Panel (d): S/√B, relative to its best

| | Simulated | Real |
|---|---|---|
| Optimum | 6.4 mV | 6.8 mV (GUI `-0.0068`) |
| Within 5 % of the best | 6.0–7.6 mV | 6.8 mV only |
| Photons counted at the optimum, vs the reference | 90 % | 76 % |

The real curve is jagged where the simulated one is smooth, so its "within 5 %" band shrinks to a
single level. The cause is the dark scan's statistics: above about 6 mV the real dark rate is
1–2 counts/s, so a 30 s threshold holds only 30–60 dark counts, and √B is uncertain by 13–18 %
at each level. A longer dark count at 5–8 mV would smooth this. Until then, treat 6–7 mV as the
optimum region rather than 6.8 mV exactly.

**This optimum assumes a weak, background-limited signal.** At the real light level the dark rate
is negligible at any threshold above the valley: 7.9 counts/s at 5 mV against 3.6e5. For a
bright signal like that, a lower level such as 5.2 mV keeps more photons. That is about 92 % of
the reference rate, against 76 % at 6.8 mV.

---

## Regenerating

From the repository root:

```bash
python Logger-Stanford_SR400/selftest.py plot docs/real_data/2026-11-10/SR400_threshold_scan_dark_2026-11-10_132008.csv docs/real_data/2026-11-10/SR400_threshold_scan_light_2026-11-10_135935.csv
```

```bash
python Logger-Stanford_SR400/selftest.py plot docs/images/example_threshold_scan_dark.csv docs/images/example_threshold_scan_light.csv
```

Each command plots the dark scan first. The light plot then finds the dark scan: from its own
CSV header, or failing that from the newest dark CSV for the same port beside it.
