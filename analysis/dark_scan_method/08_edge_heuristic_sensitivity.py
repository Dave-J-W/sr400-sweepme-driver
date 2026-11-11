"""08. How much of the noise-edge difference (5.2 against 6.0 mV) is the heuristic itself?

The driver's edge: the first level, from the rate maximum up, at which the log-slope over a
>= 1 mV baseline is below 1.0 /mV at that level and at the next one (selftest._noise_edge).

  (a) the slope at every level of both real scans, and which pair of levels triggers;
  (b) the edge under nearby heuristics (limit 0.8 / 1.0 / 1.2 per mV; baseline 0.8 / 1.0 / 1.2 /
      1.6 mV; one level instead of two below the limit), on the real scans and on the noise-free
      tubes T1 and T2 (fine grid, and the 16:36 scan's own grid);
  (c) resampling: each real scan's counts redrawn (i) Poisson around the observed counts,
      (ii) Poisson around the tube's expectation at the scan's own live times, (iii) as (ii) with
      whole-cluster over-dispersion (m = 2, var/mean 3) on the dark part. 2000 draws each.

Outputs: out/08_slopes.csv, out/08_variants.csv, out/08_resampling.csv
"""

import math
import os
import random
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))  # python -I drops the script folder
import harness as H  # noqa: E402
from dsm_common import (st, load_selftest, real_dark, write_csv, mv, key_mv, poisson,  # noqa: E402
                        LABEL)

d = {"D1": real_dark("D1"), "D2": real_dark("D2")}
levels_d2 = [p["abs_v"] for p in d["D2"]]

# (a) slopes
slope_rows = []
for key, pts in d.items():
    res = st.analyse_dark(pts)
    for r in res["rows"]:
        slope_rows.append({"scan": LABEL[key], "level_mV": mv(r["abs_v"]), "rate": r["rate"],
                           "log_slope_per_mV": r.get("log_slope_per_mv"),
                           "edge_mV": mv(res["noise_edge_v"])})
write_csv("08_slopes.csv", slope_rows)
for key in d:
    seq = [(r["level_mV"], round(r["log_slope_per_mV"], 2) if r["log_slope_per_mV"] is not None else None)
           for r in slope_rows if r["scan"] == LABEL[key] and 4.6 <= r["level_mV"] <= 7.6]
    print(LABEL[key], seq)

# (b) variants
tubes = {n: H.load_tube(n, random.Random(0)) for n in ("T1", "T2")}
truth_fine = {n: H.truth_points(t) for n, t in tubes.items()}
truth_d2grid = {n: H.truth_points(t, levels_d2) for n, t in tubes.items()}
datasets = {"real 13:20": d["D1"], "real 16:36": d["D2"],
            "T1 noise-free, fine grid": truth_fine["T1"], "T2 noise-free, fine grid": truth_fine["T2"],
            "T1 noise-free, 16:36 grid": truth_d2grid["T1"], "T2 noise-free, 16:36 grid": truth_d2grid["T2"]}


def edge_with(points, limit, window, two=True):
    m = load_selftest(f"sr400_edge_{limit}_{window}_{two}")
    m.NOISE_SLOPE_PER_MV = limit
    m.SLOPE_WINDOW_V = window * 1e-3
    rows = sorted((m._rate_row(p) for p in points), key=lambda r: r["abs_v"])
    if two:
        e, _ = m._noise_edge(rows)
        return mv(e) if e else None
    _, slopes = m._noise_edge(rows)
    peak = max(range(len(rows)), key=lambda i: rows[i]["rate"])
    for i in range(peak, len(slopes)):
        if slopes[i] is not None and slopes[i] < limit:
            return mv(rows[i]["abs_v"])
    return None


variant_rows = []
for limit in (0.8, 1.0, 1.2):
    for window in (0.8, 1.0, 1.2, 1.6):
        for two in (True, False):
            row = {"limit_per_mV": limit, "baseline_mV": window, "levels_below": 2 if two else 1}
            for name, pts in datasets.items():
                row[name] = edge_with(pts, limit, window, two)
            variant_rows.append(row)
write_csv("08_variants.csv", variant_rows)
for r in variant_rows:
    print(r)

# (c) resampling
SEED = 20261108
res_rows = []
for key, tube_name in (("D1", "T1"), ("D2", "T2")):
    tube = tubes[tube_name]
    for mode in ("around observed", "around tube", "around tube, clusters m=2"):
        rng = random.Random(f"{SEED}-{key}-{mode}")
        edges = {}
        for _ in range(2000):
            pts = []
            for p in d[key]:
                v = p["abs_v"] * 1e3
                if mode == "around observed":
                    c = poisson(rng, p["counts"])
                else:
                    noise_mu = tube.noise(v) * p["live_s"]
                    dark_mu = tube.dark_mean(v, 1e9) * p["live_s"]
                    c = poisson(rng, noise_mu)
                    if "clusters" in mode:
                        for _ in range(poisson(rng, dark_mu / 2.0)):
                            k = 1
                            while rng.random() > 0.5:
                                k += 1
                            c += k
                    else:
                        c += poisson(rng, dark_mu)
                pts.append(dict(p, counts=c))
            e = st.analyse_dark(pts)["noise_edge_v"]
            k = mv(e) if e else None
            edges[k] = edges.get(k, 0) + 1
        total = sum(edges.values())
        for k, c in sorted(edges.items(), key=lambda kv: (kv[0] is None, kv[0] or 0)):
            res_rows.append({"scan": LABEL[key], "mode": mode, "edge_mV": k, "fraction": c / total})
        print(LABEL[key], mode, {k: round(c / total, 3) for k, c in sorted(edges.items(),
                                                                         key=lambda kv: (kv[0] is None, kv[0] or 0))})
write_csv("08_resampling.csv", res_rows)
