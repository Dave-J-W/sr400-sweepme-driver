"""02a. DEAD END, kept as the operator asked. Superseded by 02b_period_fingerprint_sim.py.

Why it was abandoned: exhaustive enumeration of period sequences is fine where a threshold took
one or two periods, but the number of sequences consistent with one (counts, live) pair grows
combinatorially once periods of 10-20 ms can repeat (dark 13:20 at 2.8 mV, 227 counts in 60 ms,
already has 13), and the exact likelihood over them did not finish in 10 minutes. 02b gets the
same information by running the driver's own _measure_point many times on the virtual bench.
Running this file is not needed for any result in the README.

02. What the CSVs reveal about the individual count periods inside each threshold.

The CSV keeps one row per threshold: total counts and total live time. It does NOT keep the count
periods _measure_point added up. But the period lengths are not free: the first is 10 ms, and
each later one is sized from the counts so far (selftest._measure_point, rounded up to a settable
CP value by selftest._ceil_count_time). So the total live time is a fingerprint of the path, and
it constrains how many counts the first 10 ms period held.

For each threshold this script enumerates every period sequence and every split of the counts
that the driver's own rules allow, and reports
  - the possible period sequences;
  - the allowed range of first-period counts c1, hence the first-period rate (the 10 ms right
    after the level was set) against the rate in the rest of the threshold;
  - the exact likelihood of the observed (counts, live) under a model in which the first period
    counts at kappa times the rate of the later ones (kappa = 1: no settling or burst effect).

Rules (as they were when each scan was taken, from git history):
  dark 13:20  target 200 counts, at most 30 s, no fast target
  dark 16:36  target 200 counts, at most 30 s; 500 where 500 take < 10 s
Both: first period 10 ms, at most 10 s per period.

It also measures the per-threshold overhead (t_s step minus live time) against the number of
periods, which the simulator uses.

Outputs: out/02_periods.csv, out/02_kappa_profile.csv, out/02_overhead.csv
"""

import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))  # python -I drops the script folder
from dsm_common import st, real_dark, write_csv, LABEL


class _Clock:
    CLOCK_FREQUENCY = 1e7


CLK = _Clock()
RULES = {"D1": dict(target=200, max_s=30.0, fast=0, fast_s=0.0),
         "D2": dict(target=200, max_s=30.0, fast=500, fast_s=10.0)}


def target_of(c, live, rule):
    t = rule["target"]
    if rule["fast"] > t and c > 0 and rule["fast"] * live / c < rule["fast_s"]:
        t = rule["fast"]
    return t


def terminated(c, live, rule):
    return c >= target_of(c, live, rule) or live >= rule["max_s"] - 1e-9


def next_period(c, live, prev, rule):
    """The driver's own sizing (selftest._measure_point), then its rounding."""
    t = target_of(c, live, rule)
    remaining = rule["max_s"] - live
    needed = (t - c) * live / c if c > 0 else prev * 10.0
    period = max(st.MIN_PERIOD_SECONDS, min(needed * 1.1, remaining))
    return min(st._ceil_count_time(CLK, period), st.MAX_PERIOD_SECONDS)


def paths(total, live_final, rule):
    """All period sequences, each with the allowed set of cumulative counts after each period.

    Returns a list of (periods, [set of C_1], [set of C_2], ...) where C_k is the cumulative count
    after period k; C_last = total. Exhaustive over counts 0..total."""
    first = min(st._ceil_count_time(CLK, st.MIN_PERIOD_SECONDS), st.MAX_PERIOD_SECONDS)
    results = []
    memo = {}

    def possible_nexts(live, prev):
        key = (round(live, 7), prev)
        if key not in memo:
            nexts = set()
            for c in range(total + 1):
                if terminated(c, live, rule):
                    continue
                p = next_period(c, live, prev, rule)
                if live + p <= live_final + 1e-7:
                    nexts.add(p)
            memo[key] = sorted(nexts)
        return memo[key]

    def extend(seq, live):
        # live = sum(seq); the states after the last period are all C in 0..total for now
        if abs(live - live_final) < 1e-7:
            results.append(tuple(seq))
            return
        for p in possible_nexts(live, seq[-1]):
            extend(seq + [p], live + p)

    extend([first], first)
    out = []
    for seq in results:
        # Backward pass: the cumulative counts allowed after each period.
        lives = [sum(seq[:k + 1]) for k in range(len(seq))]
        allowed = [None] * len(seq)
        allowed[-1] = {total} if terminated(total, lives[-1], rule) else set()
        ok = True
        for k in range(len(seq) - 2, -1, -1):
            later_min = min(allowed[k + 1]) if allowed[k + 1] else None
            s = set()
            if later_min is not None:
                for c in range(0, max(allowed[k + 1]) + 1):
                    if terminated(c, lives[k], rule):
                        continue
                    if next_period(c, lives[k], seq[k], rule) != seq[k + 1]:
                        continue
                    if any(c2 >= c for c2 in allowed[k + 1]):
                        s.add(c)
            allowed[k] = s
            if not s:
                ok = False
                break
        if ok:
            # forward pass: C_{k+1} must be >= some allowed C_k
            for k in range(1, len(seq)):
                lo = min(allowed[k - 1])
                allowed[k] = {c for c in allowed[k] if c >= lo}
            out.append((seq, allowed))
    return out


def log_pois(k, lam):
    if lam <= 0:
        return 0.0 if k == 0 else -math.inf
    return k * math.log(lam) - lam - math.lgamma(k + 1)


def path_likelihood(seq, allowed, total, rate, kappa):
    """P(the path and its total) when period 1 counts at kappa*rate and the rest at rate.
    Forward recursion over cumulative counts, restricted to the allowed sets. States more than
    12 sigma from the cumulative mean are dropped (their weight is < 1e-30 of the total)."""
    mean = kappa * rate * seq[0]

    def plausible(c, m):
        return abs(c - m) <= 12.0 * math.sqrt(m + 1.0) + 3.0

    probs = {c: math.exp(log_pois(c, mean)) for c in allowed[0] if plausible(c, mean)}
    for k in range(1, len(seq)):
        lam = rate * seq[k]
        mean += lam
        new = {}
        last = k == len(seq) - 1
        for c2 in allowed[k]:
            if not last and not plausible(c2, mean):
                continue
            acc = 0.0
            for c1, w in probs.items():
                if c2 >= c1 and w > 0:
                    acc += w * math.exp(log_pois(c2 - c1, lam))
            if acc > 0:
                new[c2] = acc
        probs = new
    return probs.get(total, 0.0)


if sys.argv[1:] == ["first"]:
    # The part that does finish: the period sequences of the first thresholds of 13:20 that
    # need more than one period (writes out/02a_first_paths.txt).
    lines = []
    for p in real_dark("D1")[:13]:
        found = paths(p["counts"], p["live_s"], RULES["D1"])
        lines.append(f"13:20 {p['abs_v'] * 1e3:.1f} mV, {p['counts']} counts in {p['live_s']:g} s: "
                     f"{len(found)} period sequence(s); first-period counts "
                     f"{min(min(a[0]) for _, a in found)}-{max(max(a[0]) for _, a in found)}; "
                     f"e.g. {' + '.join(f'{x:g}' for x in found[0][0])} s")
    with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "out", "02a_first_paths.txt"), "w",
              encoding="utf-8") as h:
        h.write("\n".join(lines) + "\n")
    print("\n".join(lines))
    sys.exit(0)

period_rows, prof_rows, over_rows = [], [], []
structures = {}
for key in ("D1", "D2"):
    pts = real_dark(key)
    rule = RULES[key]
    for i, p in enumerate(pts):
        found = paths(p["counts"], p["live_s"], rule)
        structures[(key, i)] = found
        total, live = p["counts"], p["live_s"]
        for seq, allowed in found:
            c1 = sorted(allowed[0])
            rest_live = live - seq[0]
            row = {"scan": LABEL[key], "level_mV": round(p["abs_v"] * 1e3, 1), "counts": total,
                   "live_s": live, "n_paths": len(found), "periods_s": "+".join(f"{x:g}" for x in seq),
                   "n_periods": len(seq), "c1_min": c1[0], "c1_max": c1[-1],
                   "rate_all": total / live}
            if rest_live > 0:
                row["rate1_min"] = c1[0] / seq[0]
                row["rate1_max"] = c1[-1] / seq[0]
                row["rate_rest_min"] = (total - c1[-1]) / rest_live
                row["rate_rest_max"] = (total - c1[0]) / rest_live
                # P-value-like summary: under kappa = 1 the expected c1 is total*seq0/live
                row["c1_expected_if_kappa1"] = total * seq[0] / live
            period_rows.append(row)
        if not found:
            period_rows.append({"scan": LABEL[key], "level_mV": round(p["abs_v"] * 1e3, 1),
                                "counts": total, "live_s": live, "n_paths": 0})
        # overhead: time from this row's start to the next row's start, minus live time
        if i + 1 < len(pts) and found:
            over_rows.append({"scan": LABEL[key], "level_mV": round(p["abs_v"] * 1e3, 1),
                              "n_periods": len(found[0][0]), "live_s": live,
                              "overhead_s": pts[i + 1]["t"] - p["t"] - live,
                              "unique_path": len(found) == 1})
write_csv("02_periods.csv", period_rows)
write_csv("02_overhead.csv", over_rows)

# Overhead model: overhead = a + b * n_periods, least squares on unique-path thresholds.
for key in ("dark 13:20", "dark 16:36", None):
    sel = [r for r in over_rows if r["unique_path"] and (key is None or r["scan"] == key)]
    n = len(sel)
    sx = sum(r["n_periods"] for r in sel); sy = sum(r["overhead_s"] for r in sel)
    sxx = sum(r["n_periods"] ** 2 for r in sel); sxy = sum(r["n_periods"] * r["overhead_s"] for r in sel)
    b = (n * sxy - sx * sy) / (n * sxx - sx * sx)
    a = (sy - b * sx) / n
    resid = [r["overhead_s"] - a - b * r["n_periods"] for r in sel]
    print(f"overhead {key or 'both'}: {a * 1e3:.1f} ms per threshold + {b * 1e3:.1f} ms per period, "
          f"rms residual {math.sqrt(sum(x * x for x in resid) / n) * 1e3:.1f} ms, n={n}")

# kappa profile: region by region, the joint likelihood over thresholds with > 1 period, the
# per-threshold rate profiled out (maximised on a grid around total/live).
REGIONS = ((2.6, 3.6), (3.8, 5.8), (6.0, 40.0), (2.6, 40.0))


def profile(key, lo, hi, kappa):
    total_ll = 0.0
    used = 0
    for i, p in enumerate(real_dark(key)):
        v = p["abs_v"] * 1e3
        if not (lo - 1e-6 <= v <= hi + 1e-6):
            continue
        found = structures[(key, i)]
        if not found or all(len(seq) < 2 for seq, _ in found):
            continue
        # The rate is profiled on a small grid around its closed-form value for this kappa
        # (all counts over the kappa-weighted live time).
        p1 = found[0][0][0]
        r0 = max(p["counts"], 0.5) / (p["live_s"] - p1 + kappa * p1)
        best = -math.inf
        for f in (0.9, 0.95, 1.0, 1.05, 1.1):
            like = sum(path_likelihood(seq, allowed, p["counts"], r0 * f, kappa) for seq, allowed in found)
            if like > 0:
                best = max(best, math.log(like))
        total_ll += best
        used += 1
    return total_ll, used


KAPPAS = [0.25, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0, 1.1, 1.25, 1.5, 1.75, 2.0, 2.5, 3.0, 4.0]
for key in ("D1", "D2"):
    for lo, hi in REGIONS:
        lls = []
        for kappa in KAPPAS:
            ll, used = profile(key, lo, hi, kappa)
            lls.append(ll)
        best = max(lls)
        ll1 = lls[KAPPAS.index(1.0)]
        for kappa, ll in zip(KAPPAS, lls):
            prof_rows.append({"scan": LABEL[key], "region_mV": f"{lo}-{hi}", "kappa": kappa,
                              "delta_2lnL": 2 * (best - ll), "thresholds": used})
        kbest = KAPPAS[lls.index(best)]
        inside = [k for k, ll in zip(KAPPAS, lls) if 2 * (best - ll) <= 3.84]
        print(f"{LABEL[key]} {lo}-{hi} mV: kappa_best {kbest}, 95 % range {min(inside)}-{max(inside)}, "
              f"2 dlnL at kappa=1: {2 * (best - ll1):.2f}, thresholds {used}")
write_csv("02_kappa_profile.csv", prof_rows)

for r in period_rows:
    if r.get("level_mV", 0) <= 6.0 or r.get("n_paths", 1) != 1:
        print({k: (round(v, 3) if isinstance(v, float) else v) for k, v in r.items()})
