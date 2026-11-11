"""15. What does a wrong optimum COST? Score every simulated optimum on the tube's true curve.

The S/sqrt(B) top is flat (14): on T1 with light 13:59, 6.6 mV is 0.1 % below the best (6.8),
so "the same level to 0.2 mV" is a harder target than "a level within 1-2 % of the best". For
every run of the campaigns, the level the driver chose is scored by the true relative figure of
merit of that tube at that level (out/14_fom_top.csv, noise-free tube, the driver's own
analyse_light). Also scored: fixed levels, which need no dark scan at all.

Output: out/15_cost.csv
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))  # python -I drops the script folder
from dsm_common import read_csv, write_csv, quantile, mean  # noqa: E402

truth = {}
for r in read_csv("14_fom_top.csv"):
    truth[(r["tube"], r["light"], round(float(r["level_mV"]), 1))] = float(r["relative_fom"])


def score(tube, light, level):
    if level in ("", None):
        return 0.0
    return truth.get((tube, light, round(float(level), 1)), 0.0)  # an unscored level counts as 0


rows = []


def summarize(label, tube, light, levels):
    s = [score(tube, light, v) for v in levels]
    rows.append({"case": label, "tube": tube, "light": light, "runs": len(s), "mean score": mean(s),
                 "q05 score": quantile(s, 0.05), "P(score >= 0.99)": sum(x >= 0.99 for x in s) / len(s),
                 "P(score >= 0.98)": sum(x >= 0.98 for x in s) / len(s),
                 "P(score >= 0.95)": sum(x >= 0.95 for x in s) / len(s)})


# real-light campaigns: 06 (Poisson) and 10 (tuned over-dispersion)
for name, tube in (("06_T1", "T1"), ("06_T2", "T2")):
    runs = read_csv(f"{name}_runs.csv")
    for rule in ("old", "r1636", "current"):
        for lk in ("L1", "L2"):
            summarize(f"{name} {rule} (Poisson)", tube, lk, [r[f"opt_{lk}"] for r in runs if r["rule"] == rule])
for case in ("M0", "P0"):
    runs = read_csv(f"10_{case}_runs.csv")
    for rule in sorted({r["rule"] for r in runs}):
        tube = runs[[r["rule"] for r in runs].index(rule)]["tube"]
        for lk in ("L1", "L2"):
            summarize(f"10_{case} {rule} (over-dispersed)", tube, lk,
                      [r[f"opt_{lk}"] for r in runs if r["rule"] == rule])
# fine-light design campaigns: 11 (driver fit) and 11b (three fits)
for r_case in sorted({r["case"] for r in read_csv("11_runs.csv")}):
    sel = [r for r in read_csv("11_runs.csv") if r["case"] == r_case]
    for lk in ("L1f", "L2f"):
        summarize(f"11 {r_case} [driver fit]", sel[0]["tube"], lk, [r[f"opt_{lk}"] for r in sel])
b = read_csv("11b_runs.csv")
for r_case in sorted({r["case"] for r in b}):
    for a in ("driver", "tail_line"):
        sel = [r for r in b if r["case"] == r_case and r["analysis"] == a]
        tube = r_case.split()[0]
        for lk in ("L1f", "L2f"):
            summarize(f"11b {r_case} [{a} fit]", tube, lk, [r[f"opt_{lk}"] for r in sel])
# fixed levels
for level in (6.8, 7.0, 7.2, 7.6):
    for tube in ("T1", "T2"):
        for lk in ("L1", "L2", "L1f", "L2f"):
            summarize(f"fixed {level} mV, no dark scan", tube, lk, [level])
write_csv("15_cost.csv", rows)
for r in rows:
    if r["case"].startswith(("fixed", "10_", "06_T1 current", "06_T2 current")) or "[tail_line" in r["case"]:
        print({k: (round(v, 3) if isinstance(v, float) else v) for k, v in r.items()})
