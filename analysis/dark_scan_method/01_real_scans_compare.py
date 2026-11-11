"""01. The two real dark scans side by side, and what the driver's own analysis makes of them.

Outputs:
  out/01_real_levels.csv     per common level: counts, live, rate, sigma, ratio D2/D1, z
  out/01_real_regions.csv    pooled ratios by region
  out/01_real_driver.csv     noise edge, lower bound, and S/sqrt(B) optimum and band for all
                             four dark x light pairings, plus leave-one-out chi-square checks
"""

import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))  # python -I drops the script folder
from dsm_common import (st, real_dark, light_result, write_csv, mv, key_mv, loo_chi2,
                        ml_common_ratio, LABEL)

d1, d2 = real_dark("D1"), real_dark("D2")
by1 = {key_mv(p["abs_v"]): p for p in d1}
by2 = {key_mv(p["abs_v"]): p for p in d2}
common = sorted(set(by1) & set(by2))

rows = []
for k in common:
    a, b = by1[k], by2[k]
    r1, r2 = a["counts"] / a["live_s"], b["counts"] / b["live_s"]
    s1, s2 = math.sqrt(max(a["counts"], 1)) / a["live_s"], math.sqrt(max(b["counts"], 1)) / b["live_s"]
    # Conditional binomial test of equal rates: given n = c1 + c2, c2 ~ Bin(n, t2/(t1+t2)).
    n = a["counts"] + b["counts"]
    p = b["live_s"] / (a["live_s"] + b["live_s"])
    z = (b["counts"] - n * p) / math.sqrt(n * p * (1 - p)) if n > 0 else float("nan")
    rows.append({"level_mV": k / 10, "c1": a["counts"], "live1_s": a["live_s"], "t1_s": a["t"],
                 "rate1": r1, "sig1": s1, "c2": b["counts"], "live2_s": b["live_s"], "t2_s": b["t"],
                 "rate2": r2, "sig2": s2, "ratio": r2 / r1 if r1 > 0 else float("nan"),
                 "ratio_sig": (r2 / r1) * math.sqrt(1 / max(a["counts"], 1) + 1 / max(b["counts"], 1))
                 if r1 > 0 else float("nan"), "z": z})
write_csv("01_real_levels.csv", rows)


def pooled(lo, hi):
    sel = [r for r in rows if lo - 1e-9 <= r["level_mV"] <= hi + 1e-9]
    c1 = sum(r["c1"] for r in sel)
    c2 = sum(r["c2"] for r in sel)
    rho, rho_sig, chi_common, dof = ml_common_ratio(
        [(r["c1"], r["live1_s"], r["c2"], r["live2_s"]) for r in sel])
    chi = sum(r["z"] ** 2 for r in sel)
    return {"from_mV": lo, "to_mV": hi, "levels": len(sel), "counts1": c1, "counts2": c2,
            "ratio_ml": rho, "ratio_sig": rho_sig, "chi2_common_ratio": chi_common, "dof": dof,
            "chi2_equal_rates": chi, "max_abs_z": max(abs(r["z"]) for r in sel),
            "min_ratio": min(r["ratio"] for r in sel), "max_ratio": max(r["ratio"] for r in sel)}


regions = [pooled(0.4, 2.4), pooled(2.6, 3.6), pooled(3.8, 3.8), pooled(4.0, 5.6), pooled(5.8, 5.8),
           pooled(6.0, 18.0), pooled(6.4, 18.0), pooled(6.0, 7.2), pooled(9.2, 18.0)]
write_csv("01_real_regions.csv", regions)

out = []
for key, pts in (("D1", d1), ("D2", d2)):
    dark = st.analyse_dark(pts)
    for lo, hi in ((6.2e-3, 10e-3), (2.2e-3, 3.6e-3), (3.8e-3, 6.0e-3)):
        chi, n = loo_chi2(pts, lo, hi)
        chi_f, _ = loo_chi2(pts, lo, hi, with_fit_variance=True)
        out.append({"scan": LABEL[key], "quantity": f"LOO chi2/threshold {mv(lo)}-{mv(hi)} mV",
                    "value": chi, "n": n})
        out.append({"scan": LABEL[key], "quantity": f"LOO chi2/threshold incl. fit variance "
                    f"{mv(lo)}-{mv(hi)} mV", "value": chi_f, "n": n})
    out.append({"scan": LABEL[key], "quantity": "noise edge mV", "value": mv(dark["noise_edge_v"])})
    out.append({"scan": LABEL[key], "quantity": "lower bound mV", "value": mv(dark["lower_bound_v"])})
    # t_s is stamped at the END of each threshold, relative to the first stamp
    out.append({"scan": LABEL[key], "quantity": "scan duration s (last t_s + first live)",
                "value": max(p["t"] for p in pts) + pts[0]["live_s"]})
    for lk in ("L1", "L2"):
        light, _ = light_result(pts, lk)
        out.append({"scan": f"{LABEL[key]} x {LABEL[lk]}", "quantity": "S/sqrt(B) optimum mV",
                    "value": mv(light["optimum_v"])})
        out.append({"scan": f"{LABEL[key]} x {LABEL[lk]}", "quantity": "5 % band mV",
                    "value": f"{mv(light['optimum_band_v'][0])}-{mv(light['optimum_band_v'][1])}"})
        out.append({"scan": f"{LABEL[key]} x {LABEL[lk]}", "quantity": "reference (valley) mV",
                    "value": mv(light["reference_v"])})
write_csv("01_real_driver.csv", out)

print("level  rate1  rate2  ratio  z")
for r in rows:
    print(f"{r['level_mV']:5.1f} {r['rate1']:9.4g} {r['rate2']:9.4g} {r['ratio']:6.3f}+-{r['ratio_sig']:.3f} {r['z']:6.1f}")
for g in regions:
    print(g)
for o in out:
    print(o)
