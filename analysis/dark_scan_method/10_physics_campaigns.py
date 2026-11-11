"""10. Physics against method: the observed pairing reproduced with a changed tube.

All with the tuned tail over-dispersion (07: whole clusters, m = 2, var/mean 3). 400 seeded
runs per side. Pair statistics are the later scan against the earlier, as for the real scans.

  P0  as it happened: T1 under the 13:20 rules, T2 under the 16:36 rules
  P1  tail only: T1 (13:20 rules) against T1 with its dark part x 0.59 (16:36 rules)
  P2  noise edge only: T1 against T1 plus the extra noise (T2 - T1 noise, 2.4-6 mV) always on
  P3  physics under one method: T1 against T2, both under the current rules
  M0  method only, for reference: T1 under 13:20 rules against T1 under 16:36 rules

For each, also the probability of the exact observed outcome: optimum 6.8 then 7.6 mV with
BOTH light scans, and edge 5.2 then 6.0 mV.

Outputs: out/10_<case>_runs.csv / _levels.csv, out/10_summary_pairs.csv
"""

import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))  # python -I drops the script folder
import campaign as C  # noqa: E402
from dsm_common import write_csv, read_csv  # noqa: E402

N = int(sys.argv[1]) if len(sys.argv) > 1 else 400
M = {"cluster_mean": 2.0}


def extra_table():
    t1 = {float(r["v_mV"]): math.exp(float(r["ln_noise"])) for r in read_csv("05_tube_T1.csv")}
    t2 = {float(r["v_mV"]): math.exp(float(r["ln_noise"])) for r in read_csv("05_tube_T2.csv")}
    return [(v, math.log(max(t2[v] - t1[v], 1e-6) if 2.4 - 1e-9 <= v <= 6.0 + 1e-9 else 1e-6))
            for v in sorted(t1)]


EXTRA = dict(M, extra_table=extra_table(), state_always=True)
CASES = {
    "P0": (("old", ("T1", 1.0, 1.0, M)), ("r1636", ("T2", 1.0, 1.0, M))),
    "P1": (("old", ("T1", 1.0, 1.0, M)), ("r1636", ("T1", 0.59, 1.0, M))),
    "P2": (("old", ("T1", 1.0, 1.0, M)), ("r1636", ("T1", 1.0, 1.0, EXTRA))),
    "P3": (("current", ("T1", 1.0, 1.0, M)), ("current+T2", ("T2", 1.0, 1.0, M))),
    "M0": (("old", ("T1", 1.0, 1.0, M)), ("r1636", ("T1", 1.0, 1.0, M))),
}


def exact(ps, runs_a, runs_b):
    n = len(ps)
    opt = sum(1 for a, b in zip(runs_a, runs_b)
              if a["opt_L1"] == 6.8 and a["opt_L2"] == 6.8 and b["opt_L1"] == 7.6 and b["opt_L2"] == 7.6) / n
    edge = sum(1 for a, b in zip(runs_a, runs_b) if a["edge_mV"] == 5.2 and b["edge_mV"] == 6.0) / n
    both = sum(1 for a, b in zip(runs_a, runs_b)
               if a["opt_L1"] == 6.8 and a["opt_L2"] == 6.8 and b["opt_L1"] == 7.6 and b["opt_L2"] == 7.6
               and a["edge_mV"] == 5.2 and b["edge_mV"] == 6.0) / n
    return {"P(opt 6.8 then 7.6, both lights)": opt, "P(edge 5.2 then 6.0)": edge,
            "P(both exactly as observed)": both}


rows, truths = [], []
for case, ((ra, ta), (rb, tb)) in CASES.items():
    per = {ra: ta, rb: tb}
    res = C.run_campaign(f"10_{case}", None, (ra, rb), N, per_rule_tube=per)
    for rule, (tn, ds, ns, to) in per.items():
        t = C.truth_of(tn, ds, ns, {k: v for k, v in to.items()})
        truths.append({"case": case, "side": rule, "tube": tn, "dark_scale": ds,
                       "extra_noise": "extra_table" in to, **t})
    ps = C.pairs(res[ra], res[rb])
    row = C.summarize_pairs(f"{case}: {rb} ({tb[0]} dark x{tb[1]}{' +extra noise' if 'extra_table' in tb[3] else ''}) "
                            f"against {ra} ({ta[0]})", ps)
    row.update(exact(ps, res[ra], res[rb]))
    for side, rule in (("a", ra), ("b", rb)):
        s = C.summarize_runs("", res[rule])
        row[f"{side} opt_L1 distribution"] = s["opt_L1 distribution"]
        row[f"{side} edge distribution"] = s["edge_mV distribution"]
    rows.append(row)
    print(row, flush=True)
write_csv("10_summary_pairs.csv", rows)
write_csv("10_truths.csv", truths)
