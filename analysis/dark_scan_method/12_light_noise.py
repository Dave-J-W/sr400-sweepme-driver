"""12. How much does the LIGHT scan's own counting noise move the optimum?

Each real light scan's counts are redrawn, pass by pass and level by level, Poisson around the
measured counts (500 seeded draws), and scored against a fixed dark background: the noise-free
tubes T1 and T2, and the two real dark scans. The spread is what the light scan alone
contributes; the dark scan's sampling is fixed.

Output: out/12_light_noise.csv
"""

import os
import random
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))  # python -I drops the script folder
import harness as H  # noqa: E402
from dsm_common import st, real_light, real_dark, write_csv, mv, poisson  # noqa: E402

SEED = 2026111112
N = int(sys.argv[1]) if len(sys.argv) > 1 else 500
darks = {"T1 noise-free": H.truth_points(H.load_tube("T1", random.Random(0))),
         "T2 noise-free": H.truth_points(H.load_tube("T2", random.Random(0))),
         "real 13:20": real_dark("D1"), "real 16:36": real_dark("D2")}
rows = []
for lk in ("L1", "L2"):
    passes = real_light(lk)
    for dname, dpts in darks.items():
        dark = st.analyse_dark(dpts)
        base = st.analyse_light(passes, dark)["optimum_v"]
        rng = random.Random(f"{SEED}|{lk}|{dname}")
        dist = {}
        for _ in range(N):
            redrawn = [dict(ps, points=[dict(p, counts=poisson(rng, p["counts"])) for p in ps["points"]])
                       for ps in passes]
            o = st.analyse_light(redrawn, dark)["optimum_v"]
            k = mv(o) if o else None
            dist[k] = dist.get(k, 0) + 1
        same = dist.get(mv(base), 0) / N
        rows.append({"light": lk, "dark": dname, "optimum_as_measured_mV": mv(base),
                     "P(redrawn optimum unchanged)": same,
                     "distribution": " ".join(f"{k:g}:{c}" for k, c in sorted(dist.items()))})
        print(rows[-1], flush=True)
write_csv("12_light_noise.csv", rows)
