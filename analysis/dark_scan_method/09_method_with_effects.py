"""09. Method plus time-structure effects, still on ONE tube: can a time-dependent effect, through
the different count times and ordering of the rule sets, produce the observed differences?

Tube T1 (13:20-like), the tuned tail over-dispersion (07: whole clusters, m = CLUSTER_M), and one
effect at a time:
  dac_tau_{1,5,20}ms    discriminator-DAC settling after each level change (exponential, from
                        the previous level); bites where the first 10-ms periods carry the count
  drift_x1_tau600s      dark rate relaxing as 1 + 1.0 exp(-t / 600 s) from the scan start
                        (same history before every scan)
  drift_x1_tau3000s     the same, slower
  extra_noise_on_off    an extra noise component, the shape of (T2 noise - T1 noise) at
                        2.4-6 mV, switching on and off at random (mean on 120 s, off 600 s)
  extra_noise_on_off_long   the same, mean on 900 s, off 900 s (an hour-scale environment)
  mains_0.5             noise rate modulated 1 + 0.5 cos(2 pi 60 Hz t), random phase
Each case: 300 runs per rule set (old, r1636, current), seeded; per-rule spread, and the pair
statistics r1636 against old (run i against run i), as for the real scans.

Outputs: out/09_<case>_runs.csv / _levels.csv, out/09_summary_runs.csv, out/09_summary_pairs.csv
"""

import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))  # python -I drops the script folder
import campaign as C  # noqa: E402
from dsm_common import write_csv, read_csv  # noqa: E402

N = int(sys.argv[1]) if len(sys.argv) > 1 else 300
CLUSTER_M = float(sys.argv[2]) if len(sys.argv) > 2 else 2.0
RULES = ("old", "r1636", "current")


def extra_table():
    t1 = {float(r["v_mV"]): math.exp(float(r["ln_noise"])) for r in read_csv("05_tube_T1.csv")}
    t2 = {float(r["v_mV"]): math.exp(float(r["ln_noise"])) for r in read_csv("05_tube_T2.csv")}
    out = []
    for v in sorted(t1):
        e = t2[v] - t1[v] if 2.4 - 1e-9 <= v <= 6.0 + 1e-9 else 0.0
        out.append((v, math.log(max(e, 1e-6))))
    return out


base = {"cluster_mean": CLUSTER_M}
CASES = [
    ("clusters_only", {}),
    ("dac_tau_1ms", {"dac_tau_s": 0.001}),
    ("dac_tau_5ms", {"dac_tau_s": 0.005}),
    ("dac_tau_20ms", {"dac_tau_s": 0.020}),
    ("drift_x1_tau600s", {"dark_excess": 1.0, "dark_tau_s": 600.0}),
    ("drift_x1_tau3000s", {"dark_excess": 1.0, "dark_tau_s": 3000.0}),
    ("extra_noise_on_off", {"extra_table": extra_table(), "extra_on_s": 120.0, "extra_off_s": 600.0}),
    ("extra_noise_on_off_long", {"extra_table": extra_table(), "extra_on_s": 900.0, "extra_off_s": 900.0}),
    ("mains_0.5", {"mains_depth": 0.5}),
]

if __name__ == "__main__":
    s_runs, s_pairs = [], []
    for case, opts in CASES:
        o = dict(base, **opts)
        truth = C.truth_of("T1", tube_opts={k: v for k, v in o.items() if k != "extra_table"})
        res = C.run_campaign(f"09_{case}", "T1", RULES, N, tube_opts=o)
        for rule in RULES:
            s_runs.append(C.summarize_runs(f"{case} {rule}", res[rule], truth))
        for a, b in (("old", "r1636"), ("old", "current")):
            s_pairs.append(C.summarize_pairs(f"{case}: {b} against {a}", C.pairs(res[a], res[b])))
        print(s_pairs[-2], flush=True)
    write_csv("09_summary_runs.csv", s_runs)
    write_csv("09_summary_pairs.csv", s_pairs)
