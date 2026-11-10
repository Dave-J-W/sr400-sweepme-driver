# Real threshold scans, 2026-11-10

The first dark and light threshold scans of the R8486 on the SR400, kept as measured. Compared
against the simulated examples, panel by panel, in [`../../SIMULATED_VS_REAL.md`](../../SIMULATED_VS_REAL.md).

**Setup.** R8486 on SIGNAL INPUT 1, counter A, discriminator A, slope FALL, gates CW. SR400 at
GPIB address 23 through an NI GPIB-USB-HS, driven by SweepMe! 1.5.7.9. Dark: tube covered. Light:
room light, 3.3e5 counts/s at 6 mV. **PMT high voltage: 1000 V**, for both scans. That is from
the operator, recorded here afterwards; the CSVs and reports do not contain it.

| File | What it is | Status |
|---|---|---|
| `SR400_threshold_scan_dark_2026-11-10_132008.csv` | raw counts and live time per threshold | **as measured**, byte for byte |
| `SR400_threshold_scan_light_2026-11-10_135935.csv` | raw counts and live time per threshold, per pass | **as measured**, byte for byte |
| `SR400_threshold_scan_dark_2026-11-10_132008.txt` | the report the driver wrote at the time | as written, **with a since-fixed error, see below** |
| `SR400_threshold_scan_light_2026-11-10_135935.txt` | the report the driver wrote at the time | as written, **made without the dark scan, see below** |
| `SR400_test_log.csv` | the driver's test log, both rows | as written |
| `*.svg` | the figures | **regenerated** from the CSVs by the current code |

The CSVs are the record. The `.txt` reports and the test log are kept unchanged, because they
show what the driver concluded at the time, and two of those conclusions have since been
corrected:

1. **The dark report's lower bound of 1.0 mV is wrong.** Below 1.2 mV the real rate rises with
   the threshold, and the noise-edge search of the time read that rise as flat. Re-analysed
   from this CSV by the current code, the noise edge is **5.2 mV** and the lower bound **5.8 mV**
   (GUI `-0.0058`).
2. **The light report recommends the valley, 4.0 mV, because it ran without the dark scan.** The
   dark result was held only in memory and was lost when SweepMe! restarted. The figure here was
   regenerated with the dark scan found beside it. It gives the background-limited optimum as
   **6.8 mV**, counting 76 % of the photons counted at the reference level. For a bright
   signal a lower level keeps more photons; see the comparison page.

The test bench reads these CSVs. It checks that the committed figures are exactly what
`selftest.py plot` draws from them, and it pins the re-analysed levels.

To regenerate the figures, from the repository root:

```bash
python Logger-Stanford_SR400/selftest.py plot docs/real_data/2026-11-10/SR400_threshold_scan_dark_2026-11-10_132008.csv docs/real_data/2026-11-10/SR400_threshold_scan_light_2026-11-10_135935.csv
```
