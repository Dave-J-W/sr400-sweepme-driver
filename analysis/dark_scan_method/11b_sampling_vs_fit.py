"""11b. Why more dark counting barely helps (11): the background fit narrows as counts grow.

In 11, P(two scans within 0.2 mV) rose only from 0.26 (11 min) to 0.49 (190 min) on tube T1.
Pure counting noise would shrink as 1/sqrt(time). Suspected cause: _smooth_dark_rate switches to
a quadratic in a NARROWED window wherever the +-1 mV window holds >= DARK_CURVE_MIN_COUNTS (800)
counts and the quadratic wins by DARK_CURVE_LR (4). Longer dwell puts > 800 counts in the tail
windows, so the fit there narrows to ~800 counts and stops improving.

Test: the SAME simulated scans (same seeds as 11, regenerated) analysed three ways:
  driver    the driver's analysis as it is
  no_narrow DARK_CURVE_MIN_COUNTS = 1e12 (never narrow: the straight line over +-1 mV, as
            before 2026-11-11, everywhere)
  tail_line the driver's fit below 6 mV; from 6 mV up the straight line over +-1 mV, never
            narrowed (a module copy whose _smooth_dark_rate is wrapped: _tail_line_module)
Also two longer cases than 11: dwell 480 s + 1 pass and 960 s + 1 pass.

Outputs: out/11b_runs.csv, out/11b_summary.csv
"""

import os
import random
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))  # python -I drops the script folder
import harness as H  # noqa: E402
import campaign as C  # noqa: E402
from dsm_common import load_selftest, write_csv, mean, quantile  # noqa: E402

exec_globals = {"__file__": os.path.join(os.path.dirname(os.path.abspath(__file__)), "11_sampling_design.py")}
SRC = os.path.join(os.path.dirname(os.path.abspath(__file__)), "11_sampling_design.py")
with open(SRC, encoding="utf-8") as h:
    code = h.read().split("if __name__")[0]
exec(compile(code, SRC, "exec"), exec_globals)  # one_run, reproducibility, SEED, TUBE_OPTS, LIGHTS
one_run, reproducibility = exec_globals["one_run"], exec_globals["reproducibility"]
SEED, TUBE_OPTS, LIGHTS = exec_globals["SEED"], exec_globals["TUBE_OPTS"], exec_globals["LIGHTS"]

N = int(sys.argv[1]) if len(sys.argv) > 1 else 150


def _no_narrow():
    m = load_selftest("sr400_no_narrow")
    m.DARK_CURVE_MIN_COUNTS = 1e12
    return m


def _tail_line_module():
    m = load_selftest("sr400_tail_line")
    original = m._smooth_dark_rate
    line_only = load_selftest("sr400_tail_line_inner")
    line_only.DARK_CURVE_MIN_COUNTS = 1e12

    def smooth(rows, abs_v):
        return original(rows, abs_v) if abs_v < 0.006 - 1e-9 else line_only._smooth_dark_rate(rows, abs_v)

    m._smooth_dark_rate = smooth  # analyse_light looks the name up in its module at call time
    return m


ANALYSES = {"driver": None, "no_narrow": _no_narrow(), "tail_line": _tail_line_module()}
CASES = [("g04", 30.0, 0), ("g04", 120.0, 1), ("g02", 60.0, 3), ("g02", 120.0, 3), ("g02", 240.0, 1),
         ("g02", 480.0, 1), ("g02", 960.0, 1)]

if __name__ == "__main__":
    m = H.make_module(H.RULES["current"])
    run_rows, summary = [], []
    truths = {(t, a): C.analyse(H.truth_points(H.load_tube(t, random.Random(0), **TUBE_OPTS)), LIGHTS,
                                loo=False, module=mod)
              for t in ("T1", "T2") for a, mod in ANALYSES.items()}
    for k, v in truths.items():
        print("truth", k, v, flush=True)
    for tube_name in ("T1", "T2"):
        for grid_name, dwell_s, extra in CASES:
            label = f"{tube_name} {grid_name} dwell {dwell_s:g} s + {extra} tail passes"
            opts = {(a, lk): [] for a in ANALYSES for lk in LIGHTS}
            times = []
            for i in range(N):
                rng = random.Random(f"{SEED}|{label}|{i}")  # the same seeds as 11
                points, total = one_run(m, tube_name, grid_name, dwell_s, extra, rng)
                times.append(total)
                for a, mod in ANALYSES.items():
                    res = C.analyse(points, LIGHTS, loo=False, module=mod)
                    run_rows.append({"case": label, "analysis": a, "run": i, "seed": f"{SEED}|{label}|{i}",
                                     "scan_s": total, **res})
                    for lk in LIGHTS:
                        opts[(a, lk)].append(res[f"opt_{lk}"])
            for a in ANALYSES:
                row = {"case": label, "analysis": a, "tube": tube_name, "grid": grid_name, "dwell_s": dwell_s,
                       "extra_passes": extra, "runs": N, "scan_min mean": mean(times) / 60.0}
                for lk in LIGHTS:
                    vals = [v for v in opts[(a, lk)] if v is not None]
                    truth = truths[(tube_name, a)][f"opt_{lk}"]
                    same, near, tr, dist = reproducibility(vals, truth)
                    row.update({f"{lk} truth": truth, f"{lk} P(same)": same, f"{lk} P(<=0.2)": near,
                                f"{lk} P(truth+-0.2)": tr, f"{lk} median": quantile(vals, 0.5),
                                f"{lk} distribution": dist})
                summary.append(row)
                print({k: (round(v, 3) if isinstance(v, float) else v) for k, v in row.items()
                       if "distribution" not in k}, flush=True)
    write_csv("11b_runs.csv", run_rows)
    write_csv("11b_summary.csv", summary)
