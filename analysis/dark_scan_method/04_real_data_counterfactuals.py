"""04. Counterfactuals on the real data: which part of which scan moves the edge and the optimum?

All on the measured counts, through the driver's own analyse_dark / analyse_light:
  (a) grid only: dark 13:20 thinned to the 16:36 scan's levels (same counts at each kept level);
  (b) tail level only: dark 13:20 with every rate from a level up scaled by 0.59 (live time
      divided by 0.59, so the Poisson weight of each threshold is unchanged);
  (c) splices: 16:36 below a level X and 13:20 from X up, and the reverse, for X from 2.6 to
      10 mV. Where the result jumps as X passes a region, that region carries the difference;
  (d) the 2.6-5.6 mV difference only: dark 13:20 with its 2.6-5.6 mV rates scaled to the 16:36
      ones (the measured ratio at each level).

Output: out/04_counterfactuals.csv
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))  # python -I drops the script folder
from dsm_common import st, real_dark, light_passes, write_csv, mv, key_mv  # noqa: E402

d1, d2 = real_dark("D1"), real_dark("D2")
levels2 = {key_mv(p["abs_v"]) for p in d2}
by2 = {key_mv(p["abs_v"]): p for p in d2}
by1 = {key_mv(p["abs_v"]): p for p in d1}


def evaluate(name, pts, note=""):
    dark = st.analyse_dark(pts)
    row = {"case": name, "note": note, "levels": len(pts),
           "levels_6_to_10mV": sum(1 for p in pts if 6.0e-3 - 1e-9 <= p["abs_v"] <= 10e-3 + 1e-9),
           "edge_mV": mv(dark["noise_edge_v"]) if dark["noise_edge_v"] else None,
           "lower_bound_mV": mv(dark["lower_bound_v"]) if dark["lower_bound_v"] else None}
    for lk in ("L1", "L2"):
        light = st.analyse_light(light_passes(lk), dark)
        row[f"opt_{lk}_mV"] = mv(light["optimum_v"]) if light["optimum_v"] else None
        band = light["optimum_band_v"]
        row[f"band_{lk}_mV"] = f"{mv(band[0])}-{mv(band[1])}" if band else ""
    return row


rows = [evaluate("dark 13:20 as measured", d1), evaluate("dark 16:36 as measured", d2)]

# (a) grid only
thin = [p for p in d1 if key_mv(p["abs_v"]) in levels2]
rows.append(evaluate("13:20 on the 16:36 levels", thin, "same counts, levels not in 16:36 dropped"))
# (a') the 16:36 coarse tail is 7.2, 9.2, ... The 13:20 scan also has 7.6-8.8 etc.; dropping only
# 7.6-9.2 tests the window widening alone.
thin2 = [p for p in d1 if not (7.4e-3 < p["abs_v"] < 9.1e-3)]
rows.append(evaluate("13:20 without 7.6-8.8 mV", thin2, "the gap the 16:36 grid has above 7.2 mV"))

# (b) tail level only
for start in (6.0, 6.4, 7.2):
    for factor in (0.59, 0.75):
        scaled = [dict(p, live_s=p["live_s"] / factor) if p["abs_v"] >= start * 1e-3 - 1e-9 else dict(p)
                  for p in d1]
        rows.append(evaluate(f"13:20, rates from {start} mV x {factor}", scaled))
        rows.append(evaluate(f"13:20 on 16:36 levels, rates from {start} mV x {factor}",
                             [p for p in scaled if key_mv(p["abs_v"]) in levels2]))

# (c) splices
for x in (2.6, 3.0, 3.8, 4.0, 5.0, 5.8, 6.0, 6.4, 6.8, 7.2, 8.0, 10.0):
    k = key_mv(x * 1e-3)
    lo2_hi1 = [p for p in d2 if key_mv(p["abs_v"]) < k] + [p for p in d1 if key_mv(p["abs_v"]) >= k]
    lo1_hi2 = [p for p in d1 if key_mv(p["abs_v"]) < k] + [p for p in d2 if key_mv(p["abs_v"]) >= k]
    rows.append(evaluate(f"16:36 below {x} mV, 13:20 from it", lo2_hi1))
    rows.append(evaluate(f"13:20 below {x} mV, 16:36 from it", lo1_hi2))

# (d) only the 2.6-5.6 mV difference
mixed = []
for p in d1:
    k = key_mv(p["abs_v"])
    if 26 <= k <= 56 and k in by2:
        q = by2[k]
        ratio = (q["counts"] / q["live_s"]) / (p["counts"] / p["live_s"])
        mixed.append(dict(p, live_s=p["live_s"] / ratio))
    else:
        mixed.append(dict(p))
rows.append(evaluate("13:20 with 2.6-5.6 mV rates of 16:36", mixed, "same counts, rates scaled"))
mixed2 = [dict(p, live_s=p["live_s"] / ((by2[key_mv(p["abs_v"])]["counts"] / by2[key_mv(p["abs_v"])]["live_s"])
                                         / (p["counts"] / p["live_s"])))
          if 38 <= key_mv(p["abs_v"]) <= 56 else dict(p) for p in d1]
rows.append(evaluate("13:20 with 3.8-5.6 mV rates of 16:36", mixed2, "same counts, rates scaled"))

write_csv("04_counterfactuals.csv", rows)
for r in rows:
    print(f"{r['case']:<55} edge {r['edge_mV']!s:>5}  opt L1 {r['opt_L1_mV']!s:>5} ({r['band_L1_mV']:>9})  "
          f"opt L2 {r['opt_L2_mV']!s:>5} ({r['band_L2_mV']:>9})  n6-10 {r['levels_6_to_10mV']}")
