"""03. The dark tail (>= 6 mV): its shape, a drift in time, and its over-dispersion, from the
real scans only.

Questions:
  (a) Does the dark tail have the photon pulse-height shape? eps(V) = R_light(V) / R_light(ref)
      from each light scan (light >> dark there: 3e5 against ~2 counts/s). If dark counts are
      single photoelectrons, dark(V) = A * eps(V) with one amplitude A per scan.
  (b) A drift in time within a scan. Within one scan level and time rise together, so a drift is
      degenerate with the tail's slope. The two scans map level to time differently (13:20:
      6.4-18 mV over 270-1004 s; 16:36: over 272-484 s), so a joint fit with a common shape and a
      common drift rate can separate them, if the statistics allow.
  (c) Over-dispersion: chi-square of the tail against the smooth fit, in level bands, and the
      lag-1 correlation of the residuals in time order (positive: slow rate changes spanning
      neighbouring thresholds; near zero: independent excess scatter within each 30 s window).

Outputs: out/03_eps.csv, out/03_tail_fits.csv, out/03_tail_residuals.csv, out/03_drift_profile.csv
"""

import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))  # python -I drops the script folder
from dsm_common import st, real_dark, light_passes, write_csv, LABEL  # noqa: E402


def eps_table(light_key):
    """[(v_mV, eps)] from the merged light rows: rate / rate at the reference (valley)."""
    light = st.analyse_light(light_passes(light_key), None)
    ref = light["reference_v"]
    rref = st._value_at(light["rows"], ref)["rate"]
    return [(r["abs_v"] * 1e3, r["rate"] / rref) for r in light["rows"]], ref * 1e3


def interp(table, v):
    """Linear in ln(eps) between the light levels."""
    for (x0, y0), (x1, y1) in zip(table[:-1], table[1:]):
        if x0 <= v <= x1:
            return math.exp(math.log(y0) + (math.log(y1) - math.log(y0)) * (v - x0) / (x1 - x0))
    (x0, y0), (x1, y1) = table[-2], table[-1]
    return math.exp(math.log(y1) + (math.log(y1) - math.log(y0)) * (v - x1) / (x1 - x0))


eps = {}
eps_rows = []
for lk in ("L1", "L2"):
    tab, ref = eps_table(lk)
    eps[lk] = tab
    for v, e in tab:
        eps_rows.append({"light": LABEL[lk], "level_mV": v, "eps": e, "reference_mV": ref})
write_csv("03_eps.csv", eps_rows)


def poisson_fit(data, model_of, n_par, start):
    """Poisson ML by Nelder-Mead on log-parameters-free space. data: [(counts, live, x...)].
    model_of(params, row) -> rate. Returns (params, -2 lnL + const, deviance)."""
    def nll(p):
        s = 0.0
        for row in data:
            mu = model_of(p, row) * row["live_s"]
            if mu <= 0:
                return 1e300
            s += mu - row["counts"] * math.log(mu)
        return s

    # Nelder-Mead, standard coefficients
    simplex = [list(start)]
    for i in range(n_par):
        q = list(start)
        q[i] += 0.1 if abs(q[i]) < 1 else 0.1 * abs(q[i])
        simplex.append(q)
    values = [nll(q) for q in simplex]
    for _ in range(4000):
        order = sorted(range(len(simplex)), key=lambda k: values[k])
        simplex = [simplex[k] for k in order]
        values = [values[k] for k in order]
        if abs(values[-1] - values[0]) < 1e-10:
            break
        centroid = [sum(q[i] for q in simplex[:-1]) / n_par for i in range(n_par)]
        refl = [c + (c - w) for c, w in zip(centroid, simplex[-1])]
        fr = nll(refl)
        if fr < values[0]:
            exp_ = [c + 2 * (c - w) for c, w in zip(centroid, simplex[-1])]
            fe = nll(exp_)
            simplex[-1], values[-1] = (exp_, fe) if fe < fr else (refl, fr)
        elif fr < values[-2]:
            simplex[-1], values[-1] = refl, fr
        else:
            con = [c + 0.5 * (w - c) for c, w in zip(centroid, simplex[-1])]
            fc = nll(con)
            if fc < values[-1]:
                simplex[-1], values[-1] = con, fc
            else:
                best = simplex[0]
                simplex = [best] + [[b + 0.5 * (q_i - b) for b, q_i in zip(best, q)] for q in simplex[1:]]
                values = [values[0]] + [nll(q) for q in simplex[1:]]
    p = simplex[0]
    dev = 0.0
    for row in data:
        mu = model_of(p, row) * row["live_s"]
        c = row["counts"]
        dev += 2 * (mu - c + (c * math.log(c / mu) if c > 0 else 0.0))
    return p, 2 * values[0], dev


def tail_rows(key, lo, hi=40.0):
    return [dict(p, v=p["abs_v"] * 1e3, scan=key) for p in real_dark(key)
            if lo - 1e-6 <= p["abs_v"] * 1e3 <= hi + 1e-6]


fits = []
# (a) dark = A * eps(V) above 7.2 mV and above 6.4 mV, against a free exponential.
for key in ("D1", "D2"):
    for lo in (6.4, 7.2):
        data = tail_rows(key, lo)
        for lk in ("L1", "L2"):
            tab = eps[lk]
            p, m2ll, dev = poisson_fit(data, lambda q, r: math.exp(q[0]) * interp(tab, r["v"]), 1, [0.5])
            fits.append({"scan": LABEL[key], "from_mV": lo, "model": f"A*eps ({LABEL[lk]})",
                         "A_cps_at_ref": math.exp(p[0]), "slope_per_mV": None, "deviance": dev,
                         "n": len(data), "dof": len(data) - 1})
        p, m2ll, dev = poisson_fit(data, lambda q, r: math.exp(q[0] - q[1] * (r["v"] - 10.0)), 2, [0.0, 0.2])
        fits.append({"scan": LABEL[key], "from_mV": lo, "model": "exponential",
                     "A_cps_at_ref": math.exp(p[0]), "slope_per_mV": p[1], "deviance": dev,
                     "n": len(data), "dof": len(data) - 2})

# eps itself as a log-slope, for comparison with the exponential fit
for lk in ("L1", "L2"):
    e7, e15 = interp(eps[lk], 7.2), interp(eps[lk], 15.2)
    fits.append({"scan": LABEL[lk], "from_mV": 7.2, "model": "eps log-slope 7.2-15.2 mV",
                 "slope_per_mV": math.log(e7 / e15) / 8.0})

# Joint: total(V) = noise(V) + dark(V), noise ln-quadratic per scan, 3.8-15.2 mV, with the dark
# part either A_k eps(V) or an exponential A_k exp(-b (V - 10)). (A first attempt ran to 40 mV
# with A*eps; eps, extrapolated beyond the light scan's 18 mV, has no counts there, which made
# the 16-40 mV band's chi-square meaningless: kept in out/03_stdout_first_attempt.txt.)
joint = {}
for key in ("D1", "D2"):
    data = tail_rows(key, 3.8, 15.2)
    tab = eps["L1"]

    def model_eps(q, r, tab=tab):
        x = r["v"] - 4.0
        return math.exp(q[0]) * interp(tab, r["v"]) + math.exp(q[1] + q[2] * x + q[3] * x * x)

    def model_exp(q, r):
        x = r["v"] - 4.0
        return math.exp(q[0] - q[4] * (r["v"] - 10.0)) + math.exp(q[1] + q[2] * x + q[3] * x * x)

    for name, model, n_par, start in (("A*eps (light 13:59)", model_eps, 4, [0.8, 4.0, -1.5, 0.05]),
                                      ("exponential", model_exp, 5, [0.0, 4.0, -1.5, 0.05, 0.25])):
        p, m2ll, dev = poisson_fit(data, model, n_par, start)
        if name == "exponential":
            joint[key] = (p, model, data)
            dark6 = math.exp(p[0] - p[4] * (6.0 - 10.0))
        else:
            dark6 = math.exp(p[0]) * interp(tab, 6.0)
        fits.append({"scan": LABEL[key], "from_mV": 3.8, "model": f"noise ln-quadratic + dark {name}, to 15.2 mV",
                     "A_cps_at_ref": math.exp(p[0]), "slope_per_mV": p[4] if n_par == 5 else None,
                     "deviance": dev, "n": len(data), "dof": len(data) - n_par,
                     "noise_at_6mV_cps": math.exp(p[1] + p[2] * 2 + p[3] * 4),
                     "noise_at_7.2mV_cps": math.exp(p[1] + p[2] * 3.2 + p[3] * 3.2 ** 2),
                     "dark_at_6mV_cps": dark6, "params": " ".join(f"{x:.5g}" for x in p)})
write_csv("03_tail_fits.csv", fits)
for f in fits:
    print({k: (round(v, 4) if isinstance(v, float) else v) for k, v in f.items()})

# (c) residuals against the joint fit, chi-square by band, lag-1 correlation in time order.
res_rows = []
for key in ("D1", "D2"):
    p, model, data = joint[key]
    for r in data:
        mu = model(p, r) * r["live_s"]
        res_rows.append({"scan": LABEL[key], "level_mV": r["v"], "t_s": r["t"], "counts": r["counts"],
                         "expected": mu, "pearson": (r["counts"] - mu) / math.sqrt(mu)})
write_csv("03_tail_residuals.csv", res_rows)
for scan in ("dark 13:20", "dark 16:36"):
    for lo, hi in ((3.8, 6.0), (6.2, 10.0), (10.2, 15.2), (6.2, 15.2)):
        sel = [r for r in res_rows if r["scan"] == scan and lo - 1e-6 <= r["level_mV"] <= hi + 1e-6]
        if len(sel) < 2:
            continue
        chi = sum(r["pearson"] ** 2 for r in sel)
        pr = [r["pearson"] for r in sel]
        mu = sum(pr) / len(pr)
        num = sum((a - mu) * (b - mu) for a, b in zip(pr[:-1], pr[1:]))
        den = sum((a - mu) ** 2 for a in pr)
        print(f"{scan} {lo}-{hi} mV: chi2/n = {chi / len(sel):.2f} (n = {len(sel)}), "
              f"mean expected counts {sum(r['expected'] for r in sel) / len(sel):.1f}, "
              f"lag-1 corr {num / den:+.2f}")

# (b) common-shape, common-drift joint fit of both tails over 7.2-15.2 mV:
#     rate_k(V, t) = A_k * exp(-b (V - 10)) * exp(-g (t - 600 s) / 1000 s)
# First attempt (kept in out/03_stdout_first_attempt.txt) used 7.2-40 mV. That let the drift
# term bend the 13:20 tail at 15.2 mV, where its time per mV drops from 75 to 15 s, and so fit
# the flatter large-pulse tail above 15 mV as a "drift" (g = 2.2 per 1000 s). Above 15.2 mV the
# 16:36 scan has one threshold, so the range is cut there; within it each scan's time per mV is
# constant, and g is then fixed only by the difference between the two scans' slopes.
data = tail_rows("D1", 7.2, 15.2) + tail_rows("D2", 7.2, 15.2)


def drift_model(q, r):
    a = q[0] if r["scan"] == "D1" else q[1]
    return math.exp(a - q[2] * (r["v"] - 10.0) - q[3] * (r["t"] - 600.0) / 1000.0)


p, m2ll, dev = poisson_fit(data, drift_model, 4, [0.0, -0.5, 0.2, 0.0])
prof = []
for g in [x / 10.0 for x in range(-30, 31, 2)]:
    def fixed(q, r, g=g):
        return drift_model([q[0], q[1], q[2], g], r)
    pg, m2g, devg = poisson_fit(data, fixed, 3, p[:3])
    prof.append({"drift_per_1000s": g, "delta_2lnL": m2g - m2ll,
                 "ratio_D2_D1_at_same_t": math.exp(pg[1] - pg[0]), "slope_per_mV": pg[2]})
write_csv("03_drift_profile.csv", prof)
inside = [r["drift_per_1000s"] for r in prof if r["delta_2lnL"] <= 3.84]
print(f"joint drift fit >= 7.2 mV: g = {p[3]:.2f} per 1000 s (ln rate), 95 % range "
      f"{min(inside):.1f} to {max(inside):.1f}; slope {p[2]:.3f}/mV; "
      f"D2/D1 at equal t {math.exp(p[1] - p[0]):.2f}; deviance {dev:.1f} on {len(data) - 4} dof")
