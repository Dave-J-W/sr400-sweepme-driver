"""02b. Is there a first-window effect (DAC settling, a burst at the level change)? The CSV's
live time as a fingerprint of the count periods.

The CSV keeps one row per threshold (total counts, total live time), not the count periods that
_measure_point added up. But the period lengths are not free: the first is 10 ms right after the
level is set, and each later one is sized from the counts so far. So the total live time and
the total counts (which overshoots the target when the early periods under-read the rate)
carry information on how the first 10 ms compared with the rest. They do not resolve it fully:
dark 13:20 at 2.8 mV (227 counts in 60 ms) is consistent with 13 different period sequences
(02a). The driver would have to log each period (counts, length, time since the level change)
to resolve it.

Method: for every threshold of both real scans from 2.6 to 6.0 mV (where count times differ
between the scans and the first window is a sizeable part of the total), run the driver's own
_measure_point on the virtual bench, under the rules of that scan, 3000 times per hypothesis,
with the first period's expected counts multiplied by kappa (kappa = 1: no first-window effect),
and the rate profiled over a small grid. The likelihood of the observed (live time exactly,
counts within +-max(3, 5 %)) is the fraction of runs that reproduce it. Seeded.

Also: the per-threshold time overhead (t_s step minus live), regressed on the mean number of
periods the simulation needs for that live time; the harness uses this.

Outputs: out/02b_fingerprint.csv (per threshold and kappa), out/02b_kappa_profile.csv,
out/02b_overhead.csv
"""

import math
import os
import random
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))  # python -I drops the script folder
import harness as H  # noqa: E402
from dsm_common import real_dark, write_csv, LABEL  # noqa: E402

SEED = 20261111
M = 3000
KAPPAS = (0.3, 0.5, 0.7, 0.85, 1.0, 1.2, 1.5, 2.0, 3.0)
RATE_FACTORS = (0.94, 1.0, 1.06)
RULE_OF = {"D1": "old", "D2": "r1636"}

rows, over = [], []
for key in ("D1", "D2"):
    pts = real_dark(key)
    m = H.make_module(H.RULES[RULE_OF[key]])
    for i, p in enumerate(pts):
        v = p["abs_v"] * 1e3
        if not (2.6 - 1e-6 <= v <= 6.0 + 1e-6):
            continue
        prev = pts[i - 1]["abs_v"] if i > 0 else None
        tol = max(3, int(0.05 * p["counts"]))
        for kappa in KAPPAS:
            best = (-1.0, None)
            for f in RATE_FACTORS:
                rng = random.Random(f"{SEED}-{key}-{i}-{kappa}-{f}")
                r = p["counts"] / (p["live_s"] - 0.01 + kappa * 0.01) * f
                hits, live_hits, periods = 0, 0, []
                for _ in range(M):
                    tube = H.flat_tube(r, rng, first_factor=kappa)
                    q, n, _ = H.measure_single(m, tube, p["abs_v"], prev)
                    if abs(q["live_s"] - p["live_s"]) < 1e-7:
                        live_hits += 1
                        periods.append(n)
                        if abs(q["counts"] - p["counts"]) <= tol:
                            hits += 1
                like = hits / M
                if like > best[0]:
                    best = (like, f, live_hits / M, sum(periods) / len(periods) if periods else None)
            rows.append({"scan": LABEL[key], "level_mV": round(v, 1), "counts": p["counts"],
                         "live_s": p["live_s"], "kappa": kappa, "best_rate_factor": best[1],
                         "p_joint": best[0], "p_live": best[2], "mean_periods_given_live": best[3],
                         "tolerance_counts": tol})
        print(LABEL[key], round(v, 1), [(r_["kappa"], round(r_["p_joint"], 4)) for r_ in rows[-len(KAPPAS):]],
              flush=True)
write_csv("02b_fingerprint.csv", rows)

# Profile likelihood of kappa, by region, with a floor of 0.5/M on each probability.
prof = []
REGIONS = ((2.6, 3.6), (3.8, 6.0), (2.6, 6.0))
for scan in ("dark 13:20", "dark 16:36"):
    for lo, hi in REGIONS:
        lls = []
        for kappa in KAPPAS:
            sel = [r for r in rows if r["scan"] == scan and r["kappa"] == kappa
                   and lo - 1e-6 <= r["level_mV"] <= hi + 1e-6]
            lls.append(sum(math.log(max(r["p_joint"], 0.5 / M)) for r in sel))
        best = max(lls)
        for kappa, ll in zip(KAPPAS, lls):
            prof.append({"scan": scan, "region_mV": f"{lo}-{hi}", "kappa": kappa,
                         "delta_2lnL": 2 * (best - ll), "thresholds": len(sel)})
        inside = [k for k, ll in zip(KAPPAS, lls) if 2 * (best - ll) <= 3.84]
        print(f"{scan} {lo}-{hi} mV: best kappa {KAPPAS[lls.index(best)]}, 95 % interval "
              f"{min(inside)}-{max(inside)} (grid), 2 dlnL at kappa = 1: "
              f"{2 * (best - lls[KAPPAS.index(1.0)]):.2f}")
write_csv("02b_kappa_profile.csv", prof)

# The overhead regression that was here paired each threshold's live time with the NEXT
# threshold's time step. t_s is stamped at the END of a threshold, so that was off by one (it
# printed 723 ms per threshold, rms residual 1.7 s: see out/02b_stdout.txt). Corrected and
# moved to 02d_overhead.py.
