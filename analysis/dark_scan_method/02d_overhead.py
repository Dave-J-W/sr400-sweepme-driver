"""02d. Time overhead per threshold and per count period, for the simulator's clock.

t_s is stamped when a threshold ENDS (selftest._measure_point returns time.monotonic() after
counting), relative to the first threshold's stamp. So for threshold i > 0:
    t_s[i] - t_s[i-1] = overhead_i + live_i,
and overhead_i = a + b * (number of count periods of threshold i). The number of periods is not
logged; it is taken as the mean over the driver's own _measure_point runs (virtual bench, flat
rate = the threshold's measured rate) that reproduce the observed live time exactly.
(Replaces the off-by-one regression in 02b.)

Output: out/02d_overhead.csv
"""

import math
import os
import random
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))  # python -I drops the script folder
import harness as H  # noqa: E402
from dsm_common import real_dark, write_csv, LABEL  # noqa: E402

SEED = 202611113
RULE_OF = {"D1": "old", "D2": "r1636"}
over = []
for key in ("D1", "D2"):
    pts = real_dark(key)
    m = H.make_module(H.RULES[RULE_OF[key]])
    for i in range(1, len(pts)):
        p = pts[i]
        rng = random.Random(f"{SEED}-{key}-{i}")
        r = max(p["counts"], 0.5) / p["live_s"]
        ns = []
        for _ in range(400):
            q, n, _ = H.measure_single(m, H.flat_tube(r, rng), p["abs_v"], pts[i - 1]["abs_v"])
            if abs(q["live_s"] - p["live_s"]) < 1e-7:
                ns.append(n)
        over.append({"scan": LABEL[key], "level_mV": round(p["abs_v"] * 1e3, 1), "live_s": p["live_s"],
                     "overhead_s": p["t"] - pts[i - 1]["t"] - p["live_s"],
                     "mean_periods": sum(ns) / len(ns) if ns else None})
write_csv("02d_overhead.csv", over)
for scan in ("dark 13:20", "dark 16:36", None):
    sel = [o for o in over if o["mean_periods"] is not None and (scan is None or o["scan"] == scan)]
    n = len(sel)
    sx = sum(o["mean_periods"] for o in sel); sy = sum(o["overhead_s"] for o in sel)
    sxx = sum(o["mean_periods"] ** 2 for o in sel); sxy = sum(o["mean_periods"] * o["overhead_s"] for o in sel)
    b = (n * sxy - sx * sy) / (n * sxx - sx * sx)
    a = (sy - b * sx) / n
    res = [o["overhead_s"] - a - b * o["mean_periods"] for o in sel]
    print(f"{scan or 'both'}: overhead {a * 1e3:.1f} ms per threshold + {b * 1e3:.1f} ms per period "
          f"(n = {n}, rms residual {math.sqrt(sum(x * x for x in res) / n) * 1e3:.1f} ms, "
          f"max {max(abs(x) for x in res) * 1e3:.1f} ms)")
