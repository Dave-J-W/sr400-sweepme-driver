"""14. How flat is S/sqrt(B) at the top? The reason the optimum is fragile.

For the noise-free tubes T1 and T2 (infinite counting) and the fine light stand-ins, the
relative figure of merit S/sqrt(B) / best at every scored level (0.2 mV apart), from the
driver's own analyse_light. A level whose relative value is within a fraction x of 1 can be
displaced to the top by a relative error of about x in the ratio of eps/sqrt(B) between it and
the best level, i.e. by an error of about 2x in the RATIO of the two background values.

Output: out/14_fom_top.csv
"""

import os
import random
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))  # python -I drops the script folder
import harness as H  # noqa: E402
from dsm_common import st, light_passes, write_csv, mv  # noqa: E402

rows = []
for tube in ("T1", "T2"):
    dark = st.analyse_dark(H.truth_points(H.load_tube(tube, random.Random(0))))
    for lk in ("L1f", "L2f", "L1", "L2"):
        light = st.analyse_light(light_passes(lk), dark)
        for f in light["fom"]:
            if True:  # every scored level (the top five are printed)
                rows.append({"tube": tube, "light": lk, "level_mV": mv(f["abs_v"]), "relative_fom": f["relative"],
                             "efficiency": f["efficiency"], "dark_rate_cps": f["dark_rate"]})
        top = sorted((r for r in rows if r["tube"] == tube and r["light"] == lk),
                     key=lambda r: -r["relative_fom"])[:5]
        print(tube, lk, [(r["level_mV"], round(r["relative_fom"], 4)) for r in top])
write_csv("14_fom_top.csv", rows)
