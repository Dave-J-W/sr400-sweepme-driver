"""16. What actually moves the optimum: the background's log-slope through 6.4-7.6 mV.

S/sqrt(B) peaks where d ln(eps)/dV = (1/2) d ln(B)/dV. eps (light 13:59) falls at ~0.20 /mV over
6.4-7.6 mV, so the optimum moves up when the background falls faster than ~0.4 /mV there. This
prints the noise-free background of each tube at 6-8 mV, its log-slope over 6.4-7.6 mV, and the
share of electronic noise in it at 6.8 mV, for T1, T2 and T1 with its dark part x 0.59 (whose
noise-free optimum stays at 6.8 mV: 10_truths.csv).

Output: out/16_background_slopes.txt
"""

import math
import os
import random
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))  # python -I drops the script folder
import harness as H  # noqa: E402
from dsm_common import st, light_passes, OUT  # noqa: E402

lines = []
for name, kw in (("T1", {}), ("T2", {}), ("T1 dark x0.59", {"dark_scale": 0.59})):
    t = H.load_tube(name.split()[0], random.Random(0), **kw)
    b = t.truth
    lines.append(f"{name} B(6.0..8.0) {[round(b(v), 3) for v in (6.0, 6.4, 6.8, 7.2, 7.6, 8.0)]} "
                 f"log-slope 6.4-7.6: {math.log(b(6.4) / b(7.6)) / 1.2:.3f} /mV "
                 f"noise share at 6.8: {t.noise(6.8) / b(6.8):.2f}")
for lk in ("L1", "L2"):
    rows = {round(x["abs_v"] * 1e3, 1): x["rate"] for x in st.analyse_light(light_passes(lk), None)["rows"]}
    lines.append(f"light {lk} eps log-slope 6.4-7.6: {math.log(rows[6.4] / rows[7.6]) / 1.2:.3f} /mV")
for key in ("D1", "D2"):
    from dsm_common import real_dark
    rows = sorted((st._rate_row(p) for p in real_dark(key)), key=lambda r: r["abs_v"])
    fit = {v: st._smooth_dark_rate(rows, v * 1e-3)[0] for v in (6.4, 7.6)}
    lines.append(f"real {key}: driver's fitted B log-slope 6.4-7.6: {math.log(fit[6.4] / fit[7.6]) / 1.2:.3f} /mV")
with open(os.path.join(OUT, "16_background_slopes.txt"), "w", encoding="utf-8") as h:
    h.write("\n".join(lines) + "\n")
print("\n".join(lines))
