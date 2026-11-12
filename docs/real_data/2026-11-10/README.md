# Real threshold scans, 2026-11-10

> **Abstract.** Two real runs of the R8486, each a dark and a light threshold scan, from 2026-11-10.
> The CSVs are as measured, the first run's reports and test log as written, and the figures are
> redrawn by the current code. The first run's own reports hold two errors since corrected: a 1.0 mV
> lower bound, and a recommendation of the valley made without the dark scan. Re-analysed, the first
> run recommends 6.8 mV and the second 7.2 mV; the second's single best level is 7.6 mV. The HV was
> 1000 V for the first run and was not recorded for the second.

The first dark and light threshold scans of the R8486 on the SR400: two runs, the same afternoon,
kept as measured. Compared against the simulated examples, panel by panel, in
[`../../SIMULATED_VS_REAL.md`](../../SIMULATED_VS_REAL.md).

**Setup, both runs.** R8486 on SIGNAL INPUT 1, counter A, discriminator A, slope FALL, gates CW.
SR400 at GPIB address 23 through an NI GPIB-USB-HS, driven by SweepMe! 1.5.7.9, the scans run as
end-of-run tests. Dark: tube covered. Light: room light.

| Run | Dark scan | Light scan | Light at the reference level | PMT high voltage |
|---|---|---|---|---|
| first | 13:20 | 13:59 | 3.8e5 counts/s at 4.0 mV | **1000 V**, from the operator, recorded here afterwards; the files do not contain it |
| second | 16:36 | 17:24 | 3.9e5 counts/s at 3.8 mV | **not recorded**: the driver's HV field was left at 0, so the files say "not recorded". The bench was set to about 1000 V that day |

## Files

| File | What it is | Status |
|---|---|---|
| `SR400_threshold_scan_dark_2026-11-10_132008.csv` | first run, raw counts and live time per threshold | **as measured**, byte for byte |
| `SR400_threshold_scan_light_2026-11-10_135935.csv` | first run, raw counts and live time per threshold, per pass | **as measured**, byte for byte |
| `SR400_threshold_scan_dark_2026-11-10_132008.txt` | the report the driver wrote at the time | as written, **with a since-fixed error, see below** |
| `SR400_threshold_scan_light_2026-11-10_135935.txt` | the report the driver wrote at the time | as written, **made without the dark scan, see below** |
| `SR400_test_log.csv` | the driver's test log, the first run's two rows | as written |
| `SR400_threshold_scan_dark_2026-11-10_163608.csv` | second run, raw counts and live time per threshold | **as measured**, byte for byte |
| `SR400_threshold_scan_light_2026-11-10_172444.csv` | second run, raw counts and live time per threshold, per pass | **as measured**, byte for byte |
| `*.svg` | the figures | **regenerated** from the CSVs by the current code |

The CSVs are the record. The second run's two CSVs are also in
[`../../../analysis/low_signal_threshold/data/`](../../../analysis/low_signal_threshold/data/),
where the analysis reads them; the copies here are byte-identical to those. Its reports and
test-log rows are not in the repository.

## What the driver concluded at the time, and what has since been corrected

The `.txt` reports and the test log are kept unchanged, because they show what the driver
concluded at the time. Some of it has since been corrected:

1. **The first dark report's lower bound of 1.0 mV is wrong.** Below 1.2 mV the real rate rises
   with the threshold, and the noise-edge search of the time read that rise as flat. Re-analysed
   from this CSV by the current code, the noise edge is **5.2 mV** and the lower bound **5.8 mV**
   (GUI `-0.0058`).
2. **The first light report recommends the valley, 4.0 mV, because it ran without the dark
   scan.** The dark result was held only in memory and was lost when SweepMe! restarted. The
   figure here was regenerated with the dark scan found beside it. It gives the
   background-limited optimum as **6.8 mV** (GUI `-0.0068`), counting 76 % of the photons
   counted at the reference level, with S/√B within 5 % of its best from 6.4 to 7.6 mV. 6.8 mV is
   also the band's middle, so it is the recommendation.
3. **The second dark scan went to 2 mV steps at 7.2 mV**, inside the region where the best level
   lies, so it has only 5 thresholds between 6 and 10 mV. That was the sampling rule of the time.
   The dark scan now keeps its fine steps up to 10 mV, which on these rates would have given 11
   thresholds there, in 10.8 minutes instead of 7.8. The scan itself is valid: noise edge
   **6.0 mV**, lower bound **6.6 mV** (GUI `-0.0066`).
4. **The second light scan found its dark scan on its own**, from disk, so it was scored against
   it at the time and its CSV names it. Re-analysed by the current code, the optimum is **7.6 mV**
   (GUI `-0.0076`), counting 62 % of the photons at the reference level, with S/√B within 5 % of
   its best from 6.8 to 7.6 mV. The scan now recommends the middle of that band, **7.2 mV**
   (GUI `-0.0072`), counting 67 % and scoring 0.92 of the best; that is what its figure shows.

**The two dark scans differ** more than counting noise allows: the second reads higher at
3–5 mV and about 0.6 of the first in the tail, with its noise edge 0.8 mV higher. A
[study of the difference](../../../analysis/dark_scan_method/README.md) concluded that the scan method explains the
optimum moving from 6.8 to 7.6 mV, but not the differences in the curves. By the study, those
need a change in the tube or its surroundings between the runs, which nothing recorded can
identify.
[`../../SIMULATED_VS_REAL.md`](../../SIMULATED_VS_REAL.md) summarises it, with what would settle
it.

Every figure here is drawn by the current analysis, which differs from the one the reports were
made with in three ways. The dark background behind S/√B is a fitted curve rather than each
threshold's own rate, levels below the valley are not scored, and the recommendation is the
middle of the 5 % band rather than its single best level. All three are described in
[`../../REFERENCE.md`](../../REFERENCE.md) §9.7.

The test bench checks that committed figures are exactly what `selftest.py plot` draws from these
CSVs, that the copies here match the analysis folder's byte for byte, and pins the re-analysed
levels of both runs.

To regenerate the figures, from the repository root:

```bash
python Logger-Stanford_SR400/selftest.py plot docs/real_data/2026-11-10/SR400_threshold_scan_dark_2026-11-10_132008.csv docs/real_data/2026-11-10/SR400_threshold_scan_light_2026-11-10_135935.csv
```

```bash
python Logger-Stanford_SR400/selftest.py plot docs/real_data/2026-11-10/SR400_threshold_scan_dark_2026-11-10_163608.csv docs/real_data/2026-11-10/SR400_threshold_scan_light_2026-11-10_172444.csv
```

Plot each dark scan before its light scan. The first light scan's CSV names no dark scan, so the
plot uses the newest dark CSV for the same port beside it that is not later than the light scan:
the 13:20 one, even with the 16:36 one in the folder. The second light scan's CSV names its own.
