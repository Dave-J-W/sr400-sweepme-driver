"""11c. Repeats against dwell, at a fixed ~190 min, when the dark rate drifts.

With time-independent over-dispersion (11b), one long pass and several short interleaved passes
are equivalent (T1, 190 min: P(<= 0.2) 0.86 for 240 s + 1 pass, 0.84 for 120 s + 3 passes). A
slow drift is where they differ: a single upward pass turns the drift into a slope of the dark
curve, while alternating down/up passes cancel its linear part.

Tube T1 with whole-cluster over-dispersion (m = 2) AND a dark rate relaxing as
1 + 1.0 exp(-t / 3000 s) from the start of the scan (an arbitrary but plausible stand-in for a
tube still settling after HV-on or light). Fits: the driver's, and the straight-line tail fit
of 11b. Optimum region sampled 0.2 mV apart over 5.6-10 mV, ~190 min in total:
  480 s x 1 pass (up only), 240 s x 2 passes, 120 s x 4, 60 s x 8.
120 seeded runs each.

Outputs: out/11c_runs.csv, out/11c_summary.csv
"""

import os
import random
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))  # python -I drops the script folder
import harness as H  # noqa: E402
import campaign as C  # noqa: E402
from dsm_common import write_csv, mean  # noqa: E402

MAIN_MARK = chr(10) + "if __name__ == "
SRC = os.path.join(os.path.dirname(os.path.abspath(__file__)), "11_sampling_design.py")
g = {"__file__": SRC}
with open(SRC, encoding="utf-8") as h:
    exec(compile(h.read().split(MAIN_MARK)[0], SRC, "exec"), g)
SRC_B = os.path.join(os.path.dirname(os.path.abspath(__file__)), "11b_sampling_vs_fit.py")
gb = {"__file__": SRC_B, "__name__": "not_main"}
with open(SRC_B, encoding="utf-8") as h:
    # split on the line that starts the main block, not on the phrase (11b quotes it itself)
    exec(compile(h.read().split(MAIN_MARK)[0], SRC_B, "exec"), gb)

N = int(sys.argv[1]) if len(sys.argv) > 1 else 120
SEED = 2026111113
g["TUBE_OPTS"] = {"cluster_mean": 2.0, "dark_excess": 1.0, "dark_tau_s": 3000.0}
LIGHTS = ("L1f", "L2f")
ANALYSES = {"driver": None, "tail_line": gb["ANALYSES"]["tail_line"]}
CASES = [(480.0, 0), (240.0, 1), (120.0, 3), (60.0, 7)]

if __name__ == "__main__":
    m = H.make_module(H.RULES["current"])
    truth = {a: C.analyse(H.truth_points(H.load_tube("T1", random.Random(0), **g["TUBE_OPTS"])), LIGHTS,
                          loo=False, module=mod) for a, mod in ANALYSES.items()}
    print("truth (drift gone, t -> infinity)", truth, flush=True)
    run_rows, summary = [], []
    for dwell_s, extra in CASES:
        label = f"T1+drift g02 dwell {dwell_s:g} s + {extra} tail passes"
        opts = {(a, lk): [] for a in ANALYSES for lk in LIGHTS}
        times = []
        for i in range(N):
            rng = random.Random(f"{SEED}|{label}|{i}")
            points, total = g["one_run"](m, "T1", "g02", dwell_s, extra, rng)
            times.append(total)
            for a, mod in ANALYSES.items():
                res = C.analyse(points, LIGHTS, loo=False, module=mod)
                run_rows.append({"case": label, "analysis": a, "run": i, "seed": f"{SEED}|{label}|{i}",
                                 "scan_s": total, **res})
                for lk in LIGHTS:
                    opts[(a, lk)].append(res[f"opt_{lk}"])
        for a in ANALYSES:
            row = {"case": label, "analysis": a, "dwell_s": dwell_s, "extra_passes": extra, "runs": N,
                   "scan_min mean": mean(times) / 60.0}
            for lk in LIGHTS:
                vals = [v for v in opts[(a, lk)] if v is not None]
                same, near, tr, dist = g["reproducibility"](vals, truth[a][f"opt_{lk}"])
                row.update({f"{lk} P(same)": same, f"{lk} P(<=0.2)": near, f"{lk} P(truth+-0.2)": tr,
                            f"{lk} distribution": dist})
            summary.append(row)
            print({k: (round(v, 3) if isinstance(v, float) else v) for k, v in row.items()}, flush=True)
    write_csv("11c_runs.csv", run_rows)
    write_csv("11c_summary.csv", summary)
