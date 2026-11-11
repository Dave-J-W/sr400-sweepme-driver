"""11. What dark-scan sampling makes the S/sqrt(B) optimum reproducible to the 0.2 mV step?

The optimum is resolved only as finely as the light scan's grid: the real light scans step
0.4 mV above 6 mV. This study therefore scores against the fine-grid light stand-ins "L1f" and
"L2f" (dsm_common.fine_light: the real light curves, interpolated to 0.2 mV, noise-free), so the
dark scan's sampling is the only source of scatter. (12_light_noise.py adds the light scan's own
counting noise back.)

Every run starts as a current-rules dark scan (driver constants as of 2026-11-11); the options
change only the optimum region:
  grid   "g04": the driver's grid (0.4 mV steps from 6.4 mV); "g02": 0.2 mV steps to 10 mV
  dwell  seconds per threshold from 5.6 to 10 mV, counting to that time (no count target)
  tail   extra passes over 5.6-10 mV after the scan, alternately down and up, merged level by
         level with the scan (counts and live time add): 0, 1 or 3 extra passes
Tubes T1 and T2, tuned tail over-dispersion (whole clusters, m = 2). 150 seeded runs per case.

Reproducibility measures, per light scan:
  P(same)      probability that two independent runs give the same optimum
  P(<= 0.2)    probability that two independent runs are within 0.2 mV of each other
  P(truth)     probability that a run is within 0.2 mV of the tube's infinite-counting optimum
from the empirical distribution of the optimum. Cost: mean dark-scan time in minutes.

Outputs: out/11_runs.csv (every run), out/11_summary.csv
"""

import os
import random
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))  # python -I drops the script folder
import harness as H  # noqa: E402
import campaign as C  # noqa: E402
from dsm_common import write_csv, mv, mean, quantile  # noqa: E402

N = int(sys.argv[1]) if len(sys.argv) > 1 else 150
SEED = 2026111111
LIGHTS = ("L1f", "L2f")
TUBE_OPTS = {"cluster_mean": 2.0}
TAIL_LO, TAIL_HI = 0.0056, 0.0100


def grid_for(name, m):
    base = m.threshold_grid()
    if name == "g04":
        return base
    fine = [round(0.0002 * k, 4) for k in range(2, 51)]  # 0.4 .. 10.0 mV
    return sorted(set(fine) | {v for v in base if v > 0.0100 + 1e-9})


def tail_grid(name, down):
    step = 0.0002 if name == "g02" else 0.0004
    if name == "g04":
        levels = [round(v, 4) for v in (0.0056, 0.0058, 0.0060)] + \
                 [round(0.0064 + 0.0004 * k, 4) for k in range(10)]
    else:
        levels = [round(0.0056 + step * k, 4) for k in range(23)]
    levels = [v for v in levels if TAIL_LO - 1e-9 <= v <= TAIL_HI + 1e-9]
    return list(reversed(levels)) if down else levels


def one_run(m, tube_name, grid_name, dwell_s, extra_passes, rng):
    def dwell(v):
        if TAIL_LO - 1e-9 <= v <= TAIL_HI + 1e-9:
            return 10 ** 9, dwell_s
        return m.DARK_TARGET_COUNTS, m.DARK_MAX_SECONDS

    scans, total = [], 0.0
    tube = H.load_tube(tube_name, rng, **TUBE_OPTS)
    pts, secs = H.run_dark_scan(m, H.RULES["current"], tube, grid=grid_for(grid_name, m), dwell=dwell)
    scans.append(pts)
    total += secs
    for k in range(extra_passes):
        # same tube object: its time-dependent state carries on (here only the clusters)
        more, secs = H.run_dark_scan(m, H.RULES["current"], tube, grid=tail_grid(grid_name, down=(k % 2 == 0)),
                                     dwell=dwell, start_clock=total)
        scans.append(more)
        total += secs
    points = H.combine_points(scans) if len(scans) > 1 else scans[0]
    return points, total


def reproducibility(vals, truth):
    n = len(vals)
    counts = {}
    for v in vals:
        counts[v] = counts.get(v, 0) + 1
    p = {v: c / n for v, c in counts.items()}
    same = sum(q * q for q in p.values())
    near = sum(p[a] * p[b] for a in p for b in p if abs(a - b) <= 0.2 + 1e-9)
    tr = sum(1 for v in vals if truth is not None and abs(v - truth) <= 0.2 + 1e-9) / n
    return same, near, tr, " ".join(f"{v:g}:{counts[v]}" for v in sorted(counts))


CASES = []
for grid_name in ("g04", "g02"):
    for dwell_s in (30.0, 60.0, 120.0):
        for extra in (0, 1, 3):
            CASES.append((grid_name, dwell_s, extra))
CASES += [("g02", 240.0, 0), ("g02", 240.0, 1), ("g02", 30.0, 7)]

if __name__ == "__main__":
    m = H.make_module(H.RULES["current"])
    run_rows, summary = [], []
    truths = {t: C.truth_of(t, tube_opts=TUBE_OPTS, lights=LIGHTS) for t in ("T1", "T2")}
    for t, tr in truths.items():
        print(t, "truth", tr, flush=True)
    for tube_name in ("T1", "T2"):
        for grid_name, dwell_s, extra in CASES:
            label = f"{tube_name} {grid_name} dwell {dwell_s:g} s + {extra} tail passes"
            opts = {lk: [] for lk in LIGHTS}
            edges, times = [], []
            for i in range(N):
                rng = random.Random(f"{SEED}|{label}|{i}")
                points, total = one_run(m, tube_name, grid_name, dwell_s, extra, rng)
                res = C.analyse(points, LIGHTS, loo=False)
                run_rows.append({"case": label, "tube": tube_name, "grid": grid_name, "dwell_s": dwell_s,
                                 "extra_passes": extra, "run": i, "seed": f"{SEED}|{label}|{i}",
                                 "scan_s": total, **res})
                for lk in LIGHTS:
                    opts[lk].append(res[f"opt_{lk}"])
                edges.append(res["edge_mV"])
                times.append(total)
            row = {"case": label, "tube": tube_name, "grid": grid_name, "dwell_s": dwell_s,
                   "extra_passes": extra, "runs": N, "scan_min mean": mean(times) / 60.0,
                   "scan_min q90": quantile(times, 0.9) / 60.0}
            for lk in LIGHTS:
                vals = [v for v in opts[lk] if v is not None]
                same, near, tr, dist = reproducibility(vals, truths[tube_name][f"opt_{lk}"])
                row.update({f"{lk} truth": truths[tube_name][f"opt_{lk}"], f"{lk} P(same)": same,
                            f"{lk} P(<=0.2)": near, f"{lk} P(truth+-0.2)": tr,
                            f"{lk} sd": (sum((v - mean(vals)) ** 2 for v in vals) / (len(vals) - 1)) ** 0.5,
                            f"{lk} distribution": dist})
            e = [v for v in edges if v is not None]
            row["edge sd"] = (sum((v - mean(e)) ** 2 for v in e) / (len(e) - 1)) ** 0.5
            summary.append(row)
            print({k: (round(v, 3) if isinstance(v, float) else v) for k, v in row.items()
                   if "distribution" not in k}, flush=True)
    write_csv("11_runs.csv", run_rows)
    write_csv("11_summary.csv", summary)
