"""02c. Are the count periods within one threshold consistent with ONE steady rate?

02b found some thresholds whose (live time, counts) pair is improbable at any first-window
factor kappa (e.g. dark 16:36 at 3.8 and 5.0 mV). A point probability is not a p-value, so this
script ranks outcomes: under a steady rate (kappa = 1, rate profiled), the p-value is the
probability of an outcome at least as improbable as the observed one, where an outcome is
(live time exactly, counts in a bin of width 2*tol+1 aligned on the observed count).

20 000 runs of the driver's _measure_point per threshold and rate. Seeded.

A small p-value means the periods inside that threshold did not count at one steady Poisson
rate: the rate changed within the threshold (a burst, a drift, a settling effect beyond the
first 10 ms), or the counts are over-dispersed. It cannot say which.

Output: out/02c_stationarity.csv
"""

import collections
import math
import os
import random
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))  # python -I drops the script folder
import harness as H  # noqa: E402
from dsm_common import real_dark, write_csv, LABEL  # noqa: E402

SEED = 202611112
M = 20000
RULE_OF = {"D1": "old", "D2": "r1636"}
FACTORS = (0.94, 1.0, 1.06)

rows = []
for key in ("D1", "D2"):
    pts = real_dark(key)
    m = H.make_module(H.RULES[RULE_OF[key]])
    for i, p in enumerate(pts):
        v = p["abs_v"] * 1e3
        if not (2.6 - 1e-6 <= v <= 6.0 + 1e-6):
            continue
        tol = max(3, int(0.05 * p["counts"]))
        width = 2 * tol + 1
        best = None
        for f in FACTORS:
            rng = random.Random(f"{SEED}-{key}-{i}-{f}")
            r = p["counts"] / p["live_s"] * f
            cells = collections.Counter()
            for _ in range(M):
                q, n, _ = H.measure_single(m, H.flat_tube(r, rng), p["abs_v"], pts[i - 1]["abs_v"])
                b = math.floor((q["counts"] - (p["counts"] - tol)) / width)
                cells[(round(q["live_s"], 6), b)] += 1
            obs = cells.get((round(p["live_s"], 6), 0), 0)
            pval = sum(c for c in cells.values() if c <= obs) / M
            if best is None or obs > best[0]:
                best = (obs, f, pval, len(cells))
        rows.append({"scan": LABEL[key], "level_mV": round(v, 1), "counts": p["counts"],
                     "live_s": p["live_s"], "rate_factor": best[1], "p_cell": best[0] / M,
                     "p_value": best[2], "outcome_cells": best[3]})
        print(rows[-1], flush=True)
write_csv("02c_stationarity.csv", rows)
for scan in ("dark 13:20", "dark 16:36"):
    sel = [r for r in rows if r["scan"] == scan]
    fisher = -2 * sum(math.log(max(r["p_value"], 1.0 / M)) for r in sel)
    print(f"{scan}: {len(sel)} thresholds 2.6-6.0 mV, p < 0.05 at {sum(r['p_value'] < 0.05 for r in sel)}, "
          f"p < 0.01 at {sum(r['p_value'] < 0.01 for r in sel)}; Fisher chi2 {fisher:.1f} on {2 * len(sel)} dof")
