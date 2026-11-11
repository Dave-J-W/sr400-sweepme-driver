"""07. Tune the tail over-dispersion to the real scans' held-out chi-square.

Measured (01, leave-one-out with the driver's own fit, (obs - pred)^2 / pred per threshold):
                     6.2-10 mV        3.8-6.0 mV      2.2-3.6 mV
    dark 13:20       3.76 (n = 10)    0.47 (n = 12)   3.83 (n = 8)
    dark 16:36       2.25 (n = 4)     2.59 (n = 12)   11.9 (n = 8)

The same statistic is computed on simulated scans of T1 (13:20 rules) and T2 (16:36 rules) for
three over-dispersion models of the dark counts:
  - Poisson (none);
  - clusters counted whole (compound Poisson, var/mean = 2m - 1 at every level), m = 1.5 .. 4;
  - a slowly modulated dark rate (log-normal OU, sigma 0.15-0.35, correlation 30 s or 300 s),
    whose excess variance grows with the counts per threshold.
For each: the median and 90th percentile of the statistic, and how often a simulated scan is
at least as dispersed as the real one. 200 seeded runs per case.

The real tail's own evidence on the model (03): chi-square per threshold against a smooth fit
was 3.15 at ~37 counts per threshold (6.2-10 mV) and 2.20 at ~10 counts (10.2-15.2 mV) in
13:20. A modulated rate predicts the excess to scale with the counts (about 3.7x larger at 37
than at 10 counts); whole clusters predict it level-independent.

Outputs: out/07_<case>_runs.csv and _levels.csv for each case, out/07_summary.csv
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))  # python -I drops the script folder
import campaign as C  # noqa: E402
from dsm_common import write_csv, quantile  # noqa: E402

N = int(sys.argv[1]) if len(sys.argv) > 1 else 200
REAL = {"T1": {"loo_6.2_10": 3.76, "loo_3.8_6.0": 0.47, "loo_2.2_3.6": 3.83},
        "T2": {"loo_6.2_10": 2.25, "loo_3.8_6.0": 2.59, "loo_2.2_3.6": 11.9}}
CASES = [("poisson", {})]
CASES += [(f"cluster_m{m:g}", {"cluster_mean": m}) for m in (1.5, 2.0, 2.5, 3.0, 4.0)]
CASES += [(f"mod_s{s:g}_tau{t:g}", {"mod_sigma": s, "mod_tau_s": t})
          for s in (0.15, 0.25, 0.35) for t in (30.0, 300.0)]

rows = []
for case, opts in CASES:
    for tube, rule in (("T1", "old"), ("T2", "r1636")):
        res = C.run_campaign(f"07_{case}_{tube}", tube, (rule,), N, tube_opts=opts)
        runs = res[rule]
        row = {"case": case, "tube": tube, "rule": rule, "runs": N}
        for key in ("loo_6.2_10", "loo_3.8_6.0", "loo_2.2_3.6"):
            vals = [r[key] for r in runs if r[key] == r[key]]
            row[f"{key} median"] = quantile(vals, 0.5)
            row[f"{key} q90"] = quantile(vals, 0.9)
            row[f"{key} P(>= real)"] = sum(1 for v in vals if v >= REAL[tube][key]) / len(vals)
        row["edge sd"] = C.summarize_runs("", runs)["edge_mV sd"]
        row["opt_L1 sd"] = C.summarize_runs("", runs)["opt_L1 sd"]
        rows.append(row)
        print(row, flush=True)
write_csv("07_summary.csv", rows)
