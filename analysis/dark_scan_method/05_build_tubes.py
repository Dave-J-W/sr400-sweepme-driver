"""05. Build the simulated tubes from the real scans.

Each tube is two tables, in ln(counts/s) against |level| in mV:
  noise  below 3.8 mV: the driver's own smoother (_smooth_dark_rate) on the real scan, minus the
         dark part (under 1 % there); from 3.8 mV: the ln-quadratic noise term of the joint fit
         noise + exponential dark over 3.8-15.2 mV (03_tail_shape_time_dispersion.py).
  dark   the exponential dark term of that fit to 16 mV; above, a flat large-pulse tail read off
         the 13:20 scan's 16-36 mV thresholds (9 counts in 7 x 30 s at 18-30 mV, none at 32-36),
         which matters only for when the 13:20 rules stop.

T1 is tuned to dark 13:20, T2 to dark 16:36. "Same tube" campaigns use one of them for every
rule set.

Outputs: out/05_tube_T1.csv, out/05_tube_T2.csv (v_mV, ln_noise, ln_dark), out/05_tube_check.csv
(real rate / tube rate at each real level, and the Poisson z).
"""

import csv
import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))  # python -I drops the script folder
from dsm_common import st, real_dark, write_csv, read_csv, OUT, LABEL  # noqa: E402

fits = read_csv("03_tail_fits.csv")


def params(scan):
    for f in fits:
        if f["scan"] == scan and f["model"].startswith("noise ln-quadratic + dark exponential"):
            return [float(x) for x in f["params"].split()]
    raise KeyError(scan)


FAR_TAIL = [(18.0, 0.045), (30.0, 0.03), (34.0, 0.005), (40.0, 0.0005)]  # cps, from 13:20
LEVELS = [round(0.2 * k, 1) for k in range(1, 81)] + [17.0, 18.0, 20.0, 22.0, 26.0, 30.0, 34.0, 40.0]
LEVELS = sorted(set(LEVELS))

checks = []
for name, key in (("T1", "D1"), ("T2", "D2")):
    q = params(LABEL[key])
    pts = real_dark(key)
    rows = sorted((st._rate_row(p) for p in pts), key=lambda r: r["abs_v"])

    def dark(v):
        if v <= 16.0:
            return math.exp(q[0] - q[4] * (v - 10.0))
        d16 = math.exp(q[0] - q[4] * 6.0)
        # ln-linear from the exponential at 16 mV to the far-tail points (never above them)
        knots = [(16.0, d16)] + [(x, min(y, d16)) for x, y in FAR_TAIL]
        for (x0, y0), (x1, y1) in zip(knots[:-1], knots[1:]):
            if x0 <= v <= x1:
                return math.exp(math.log(y0) + (math.log(y1) - math.log(y0)) * (v - x0) / (x1 - x0))
        return knots[-1][1]

    def noise(v):
        if v < 3.8 - 1e-9:
            fit = st._smooth_dark_rate(rows, v * 1e-3)
            return max(fit[0] - dark(v), 1e-6)
        x = min(v, 10.0) - 4.0
        ln = q[1] + q[2] * x + q[3] * x * x
        if v > 10.0:  # continue ln-linearly with the 10 mV slope
            ln += (q[2] + 2 * q[3] * 6.0) * (v - 10.0)
        return math.exp(ln)

    table = [{"v_mV": v, "ln_noise": math.log(noise(v)), "ln_dark": math.log(dark(v))} for v in LEVELS]
    path = os.path.join(OUT, f"05_tube_{name}.csv")
    with open(path, "w", newline="", encoding="utf-8") as h:
        w = csv.DictWriter(h, fieldnames=["v_mV", "ln_noise", "ln_dark"])
        w.writeheader()
        for r in table:
            w.writerow({k: f"{v:.6f}" for k, v in r.items()})
    for r in rows:
        v = r["abs_v"] * 1e3
        mu = (noise(v) + dark(v)) * r["live_s"]
        checks.append({"tube": name, "scan": LABEL[key], "level_mV": round(v, 1), "counts": r["counts"],
                       "expected": mu, "ratio": r["counts"] / mu, "z": (r["counts"] - mu) / math.sqrt(mu),
                       "noise_cps": noise(v), "dark_cps": dark(v)})
write_csv("05_tube_check.csv", checks)
for name in ("T1", "T2"):
    for lo, hi in ((0.4, 2.4), (2.6, 3.6), (3.8, 6.0), (6.2, 10.0), (10.2, 15.2), (16.0, 40.0)):
        sel = [c for c in checks if c["tube"] == name and lo - 1e-6 <= c["level_mV"] <= hi + 1e-6]
        if sel:
            print(f"{name} {lo}-{hi} mV: n {len(sel)}, sum counts / sum expected "
                  f"{sum(c['counts'] for c in sel) / sum(c['expected'] for c in sel):.3f}, "
                  f"chi2/n {sum(c['z'] ** 2 for c in sel) / len(sel):.2f}")
