"""06. Method alone, Poisson counting: the same tube scanned under the three rule sets.

Tubes T1 (tuned to dark 13:20) and T2 (tuned to dark 16:36), each scanned 400 times under the
13:20 rules ("old"), the 16:36 rules ("r1636") and the current rules ("current"). Counting is
pure Poisson, no other effect. For each tube:
  - the spread of the noise edge and the S/sqrt(B) optimum per rule set (out/06_summary_runs.csv);
  - pair statistics, run i of one rule set against run i of another, as the real 16:36 against
    13:20 (out/06_summary_pairs.csv): how often method alone reproduces each observed difference.

Raw outputs: out/06_T1_runs.csv, out/06_T1_levels.csv, out/06_T2_runs.csv, out/06_T2_levels.csv.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))  # python -I drops the script folder
import campaign as C  # noqa: E402
from dsm_common import write_csv  # noqa: E402

N = int(sys.argv[1]) if len(sys.argv) > 1 else 400
RULES = ("old", "r1636", "current")

summary_runs, summary_pairs = [], []
for tube in ("T1", "T2"):
    truth = C.truth_of(tube)
    summary_runs.append({"case": f"{tube} truth (infinite counting, fine grid)", **truth})
    res = C.run_campaign(f"06_{tube}", tube, RULES, N)
    for rule in RULES:
        summary_runs.append(C.summarize_runs(f"{tube} {rule}", res[rule], truth))
    for a, b in (("old", "r1636"), ("old", "current"), ("old", "old"), ("r1636", "current")):
        if a == b:
            # two independent old-rule runs: the first half against the second half
            half = N // 2
            ps = C.pairs(res[a][:half], res[a][half:2 * half])
        else:
            ps = C.pairs(res[a], res[b])
        summary_pairs.append(C.summarize_pairs(f"{tube}: {b} against {a}", ps))
obs = C.observed()
summary_pairs.append({"comparison": "OBSERVED 16:36 against 13:20",
                      **{k: v for k, v in obs.items()}})
write_csv("06_summary_runs.csv", summary_runs)
write_csv("06_summary_pairs.csv", summary_pairs)
for r in summary_runs:
    print(r)
for r in summary_pairs:
    print(r)
