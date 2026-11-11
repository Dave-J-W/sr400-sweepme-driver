"""Campaign runner and pair statistics for the dark-scan method study.

A campaign = one tube (T1 or T2, with options) scanned n times under each rule set, each run
seeded by the string f"{seed}|{campaign}|{rule}|{i}" (Python's str seeding is deterministic),
then analysed by the driver's own analyse_dark and analyse_light (real light scans 13:59 and
17:24 as the photon curve). Every run's summary and every run's levels up to 18 mV are written
to out/<campaign>_runs.csv and out/<campaign>_levels.csv, so each number can be recomputed.

Pair statistics compare run i of rule A with run i of rule B (independent streams) exactly as
01_real_scans_compare.py compares the two real scans.
"""

import math
import os
import random
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import harness as H  # noqa: E402
from dsm_common import (st, light_passes, write_csv, mv, key_mv, loo_chi2,  # noqa: E402
                        ml_common_ratio, real_dark, quantile, mean)

LIGHTS = ("L1", "L2")


def analyse(points, lights=LIGHTS, loo=True, module=None):
    """The driver's analysis of one dark scan against the real (or fine stand-in) light scans.
    module: a selftest copy with overridden analysis constants (default: the unmodified one)."""
    mod = module or st
    dark = mod.analyse_dark(points)
    out = {"edge_mV": mv(dark["noise_edge_v"]) if dark["noise_edge_v"] else None,
           "bound_mV": mv(dark["lower_bound_v"]) if dark["lower_bound_v"] else None}
    for lk in lights:
        light = mod.analyse_light(light_passes(lk), dark)
        out[f"opt_{lk}"] = mv(light["optimum_v"]) if light["optimum_v"] else None
        band = light["optimum_band_v"]
        out[f"band_lo_{lk}"] = mv(band[0]) if band else None
        out[f"band_hi_{lk}"] = mv(band[1]) if band else None
    if loo:
        out["loo_6.2_10"] = loo_chi2(points, 6.2e-3, 10e-3)[0]
        out["loo_2.2_3.6"] = loo_chi2(points, 2.2e-3, 3.6e-3)[0]
        out["loo_3.8_6.0"] = loo_chi2(points, 3.8e-3, 6.0e-3)[0]
    return out


def run_campaign(name, tube_name, rule_names, n, seed=20261111, tube_opts=None, dark_scale=1.0,
                 noise_scale=1.0, grid=None, consts=None, lights=LIGHTS, loo=True, repeats=1,
                 save=True, start_clock=0.0, per_rule_tube=None):
    """Returns {rule: [run dict with 'points' and metrics]}.

    consts: {rule: {CONSTANT: value}} extra module overrides; grid: {rule: [levels V]} or None;
    repeats: scans per run, merged level by level (counts and live add);
    per_rule_tube: {rule: (tube_name, dark_scale, noise_scale, tube_opts)} to give a rule its
    own tube (the physics campaigns)."""
    tube_opts = tube_opts or {}
    results = {}
    run_rows, level_rows = [], []
    for rule in rule_names:
        base = rule.split("+")[0]
        m = H.make_module(H.RULES[base], (consts or {}).get(rule))
        tn, ds, ns, to = (per_rule_tube or {}).get(rule, (tube_name, dark_scale, noise_scale, tube_opts))
        runs = []
        for i in range(n):
            rng = random.Random(f"{seed}|{name}|{rule}|{i}")
            scans, total_s = [], 0.0
            for k in range(repeats):
                tube = H.load_tube(tn, rng, dark_scale=ds, noise_scale=ns, **to)
                pts, secs = H.run_dark_scan(m, H.RULES[base], tube,
                                            grid=(grid or {}).get(rule),
                                            start_clock=start_clock + total_s)
                scans.append(pts)
                total_s += secs
            points = H.combine_points(scans) if repeats > 1 else scans[0]
            metrics = analyse(points, lights, loo)
            row = {"campaign": name, "tube": tn, "rule": rule, "run": i, "seed": f"{seed}|{name}|{rule}|{i}",
                   "repeats": repeats, "levels": len(points),
                   "levels_6_10": sum(1 for p in points if 6.0e-3 - 1e-9 <= p["abs_v"] <= 10e-3 + 1e-9),
                   "scan_s": total_s, **metrics}
            run_rows.append(row)
            runs.append(dict(row, points=points))
            for p in points:
                if p["abs_v"] <= 18.0e-3 + 1e-9:
                    level_rows.append({"campaign": name, "rule": rule, "run": i,
                                       "level_mV": round(p["abs_v"] * 1e3, 1), "counts": p["counts"],
                                       "live_s": round(p["live_s"], 6), "t_s": round(p["t"], 3)})
        results[rule] = runs
    if save:
        write_csv(f"{name}_runs.csv", run_rows)
        write_csv(f"{name}_levels.csv", level_rows)
    return results


# ----------------------------------------------------------------------------- pair statistics

def _by_level(points):
    return {key_mv(p["abs_v"]): p for p in points}


def pair_stats(pa, pb):
    """Statistics of scan b against scan a, as for the real 16:36 against 13:20."""
    a, b = _by_level(pa), _by_level(pb)
    common = sorted(set(a) & set(b))

    def z(k):
        n = a[k]["counts"] + b[k]["counts"]
        q = b[k]["live_s"] / (a[k]["live_s"] + b[k]["live_s"])
        return (b[k]["counts"] - n * q) / math.sqrt(n * q * (1 - q)) if n > 0 else 0.0

    def ratio_sigma(k):
        ca, cb = max(a[k]["counts"], 1), max(b[k]["counts"], 1)
        r = (cb / b[k]["live_s"]) / (ca / a[k]["live_s"])
        return r, r * math.sqrt(1 / ca + 1 / cb)

    def ml(lo, hi):
        sel = [(a[k]["counts"], a[k]["live_s"], b[k]["counts"], b[k]["live_s"])
               for k in common if lo <= k <= hi]
        return ml_common_ratio(sel) if sel else (float("nan"),) * 4

    r30, s30 = ratio_sigma(30) if 30 in common else (float("nan"), float("nan"))
    return {"z_3.0": z(30) if 30 in common else float("nan"),
            "ratio_3.0": r30, "ratio_sigmas_3.0": (r30 - 1) / s30 if s30 == s30 else float("nan"),
            "chi2_eq_2.6_3.6": sum(z(k) ** 2 for k in common if 26 <= k <= 36),
            "max_z_2.6_3.6": max((z(k) for k in common if 26 <= k <= 36), default=float("nan")),
            "ratio_4.0_5.6": ml(40, 56)[0], "ratio_tail_6.4": ml(64, 180)[0],
            "ratio_below_2.4_max_abs_z": max((abs(z(k)) for k in common if k <= 24), default=float("nan"))}


OBSERVED = None


def observed():
    """The same statistics on the real scans (16:36 against 13:20)."""
    global OBSERVED
    if OBSERVED is None:
        OBSERVED = pair_stats(real_dark("D1"), real_dark("D2"))
        OBSERVED.update({"d_edge": 0.8, "d_opt_L1": 0.8, "d_opt_L2": 0.8})
    return OBSERVED


def pairs(runs_a, runs_b):
    out = []
    for ra, rb in zip(runs_a, runs_b):
        s = pair_stats(ra["points"], rb["points"])
        for key in ("edge_mV", "opt_L1", "opt_L2"):
            short = {"edge_mV": "d_edge", "opt_L1": "d_opt_L1", "opt_L2": "d_opt_L2"}[key]
            s[short] = (rb[key] - ra[key]) if (ra[key] is not None and rb[key] is not None) else float("nan")
        s["run"] = ra["run"]
        out.append(s)
    return out


def summarize_pairs(label, ps):
    """Fractions of pairs reaching each observed difference, in its observed direction."""
    obs = observed()
    n = len(ps)

    def frac(cond):
        return sum(1 for p in ps if cond(p)) / n if n else float("nan")

    return {
        "comparison": label, "pairs": n,
        "P(d_edge >= +0.8)": frac(lambda p: p["d_edge"] >= 0.8 - 1e-9),
        "P(|d_edge| >= 0.8)": frac(lambda p: abs(p["d_edge"]) >= 0.8 - 1e-9),
        "P(d_opt both lights >= +0.8)": frac(lambda p: p["d_opt_L1"] >= 0.8 - 1e-9 and p["d_opt_L2"] >= 0.8 - 1e-9),
        "P(|d_opt_L1| >= 0.8)": frac(lambda p: abs(p["d_opt_L1"]) >= 0.8 - 1e-9),
        "P(z_3.0 >= obs)": frac(lambda p: p["z_3.0"] >= obs["z_3.0"]),
        "P(chi2_eq_2.6_3.6 >= obs)": frac(lambda p: p["chi2_eq_2.6_3.6"] >= obs["chi2_eq_2.6_3.6"]),
        "P(ratio_4.0_5.6 >= obs)": frac(lambda p: p["ratio_4.0_5.6"] >= obs["ratio_4.0_5.6"]),
        "P(ratio_tail_6.4 <= obs)": frac(lambda p: p["ratio_tail_6.4"] <= obs["ratio_tail_6.4"]),
        "median z_3.0": quantile([p["z_3.0"] for p in ps], 0.5),
        "q95 chi2_eq_2.6_3.6": quantile([p["chi2_eq_2.6_3.6"] for p in ps], 0.95),
        "q05..q95 ratio_tail_6.4": f"{quantile([p['ratio_tail_6.4'] for p in ps], 0.05):.3f}.."
                                   f"{quantile([p['ratio_tail_6.4'] for p in ps], 0.95):.3f}",
        "q05..q95 ratio_4.0_5.6": f"{quantile([p['ratio_4.0_5.6'] for p in ps], 0.05):.3f}.."
                                  f"{quantile([p['ratio_4.0_5.6'] for p in ps], 0.95):.3f}",
        "P(all of edge, opt, tail, 4-5.6)": frac(
            lambda p: p["d_edge"] >= 0.8 - 1e-9 and p["d_opt_L1"] >= 0.8 - 1e-9 and p["d_opt_L2"] >= 0.8 - 1e-9
            and p["ratio_tail_6.4"] <= obs["ratio_tail_6.4"] and p["ratio_4.0_5.6"] >= obs["ratio_4.0_5.6"]),
    }


def summarize_runs(label, runs, truth=None):
    def dist(key):
        vals = [r[key] for r in runs if r[key] is not None]
        counts = {}
        for v in vals:
            counts[round(v, 1)] = counts.get(round(v, 1), 0) + 1
        return " ".join(f"{k:g}:{c}" for k, c in sorted(counts.items())), vals

    out = {"case": label, "runs": len(runs)}
    for key in ("edge_mV", "opt_L1", "opt_L2"):
        text, vals = dist(key)
        out[f"{key} distribution"] = text
        out[f"{key} mean"] = mean(vals)
        out[f"{key} sd"] = (sum((v - mean(vals)) ** 2 for v in vals) / max(len(vals) - 1, 1)) ** 0.5
        if truth and truth.get(key) is not None:
            out[f"{key} P(within 0.2 of truth)"] = sum(1 for v in vals if abs(v - truth[key]) <= 0.2 + 1e-9) / len(vals)
            out[f"{key} P(exact truth)"] = sum(1 for v in vals if abs(v - truth[key]) < 1e-6) / len(vals)
    out["scan_s mean"] = mean(r["scan_s"] for r in runs)
    out["levels_6_10 mean"] = mean(r["levels_6_10"] for r in runs)
    if "loo_6.2_10" in runs[0]:
        for k in ("loo_6.2_10", "loo_2.2_3.6", "loo_3.8_6.0"):
            vals = [r[k] for r in runs if r[k] == r[k]]
            out[f"{k} median"] = quantile(vals, 0.5)
            out[f"{k} q90"] = quantile(vals, 0.9)
    return out


def truth_of(tube_name, dark_scale=1.0, noise_scale=1.0, tube_opts=None, lights=LIGHTS):
    tube = H.load_tube(tube_name, random.Random(0), dark_scale=dark_scale, noise_scale=noise_scale,
                       **(tube_opts or {}))
    return analyse(H.truth_points(tube), lights, loo=False)
