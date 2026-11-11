"""Shared loaders and small helpers for the dark-scan method study (analysis/dark_scan_method).

Standard library only. The driver's analysis (selftest.py) is loaded by path and never modified;
its functions are used as they are: analyse_dark, analyse_light, _smooth_dark_rate,
threshold_grid, _measure_point, read_scan_csv, _Svg, _Panel.

Run every script in this folder with an isolated interpreter (python -I) from this folder.
"""

import csv
import importlib.util
import math
import os
import random

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
OUT = os.path.join(HERE, "out")
os.makedirs(OUT, exist_ok=True)


def load_selftest(name="sr400_selftest_dsm"):
    """A fresh copy of the driver's selftest.py module. Each copy has its own module constants,
    so a rule set can be emulated by overriding constants on one copy without touching another."""
    spec = importlib.util.spec_from_file_location(
        name, os.path.join(ROOT, "Logger-Stanford_SR400", "selftest.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


st = load_selftest()

DARK_FILES = {
    "D1": os.path.join(ROOT, "docs", "real_data", "2026-11-10",
                       "SR400_threshold_scan_dark_2026-11-10_132008.csv"),
    "D2": os.path.join(ROOT, "analysis", "low_signal_threshold", "data",
                       "SR400_threshold_scan_dark_2026-11-10_163608.csv"),
}
LIGHT_FILES = {
    "L1": os.path.join(ROOT, "docs", "real_data", "2026-11-10",
                       "SR400_threshold_scan_light_2026-11-10_135935.csv"),
    "L2": os.path.join(ROOT, "analysis", "low_signal_threshold", "data",
                       "SR400_threshold_scan_light_2026-11-10_172444.csv"),
}
LABEL = {"D1": "dark 13:20", "D2": "dark 16:36", "L1": "light 13:59", "L2": "light 17:24"}


def real_dark(key):
    """Points of a real dark scan, as read_scan_csv returns them (abs_v, counts, live_s, t)."""
    return st.read_scan_csv(DARK_FILES[key])[1]


def real_light(key):
    return st.read_scan_csv(LIGHT_FILES[key])[1]


_LIGHT_CACHE = {}


def light_passes(key):
    """Real light passes for "L1"/"L2"; "L1f"/"L2f" are the fine-grid stand-ins (see
    fine_light)."""
    if key not in _LIGHT_CACHE:
        _LIGHT_CACHE[key] = fine_light(key[:2]) if key.endswith("f") else real_light(key)
    return _LIGHT_CACHE[key]


def fine_light(key, live_s=1.0):
    """A noise-free light scan on a 0.2 mV grid from 0.4 to 18 mV, made from a real one.

    The real light scans step 0.4 mV above 6 mV, so their optimum cannot be resolved finer than
    0.4 mV. For the sampling study the light curve is fixed and noise-free: the merged real rate
    at its own levels, ln-linearly interpolated to the 0.2 mV midpoints. Counts = rate x live,
    with live chosen so every level holds >= 1e8 counts (so the light adds no noise). Two
    identical passes (up and down) so analyse_light's drift and hysteresis fits stay neutral."""
    real = st.analyse_light(real_light(key), None)["rows"]
    known = [(r["abs_v"] * 1e3, math.log(r["rate"])) for r in real]
    levels = [round(0.2 * k, 1) for k in range(2, 91)]
    pts = []
    for v in levels:
        for (x0, y0), (x1, y1) in zip(known[:-1], known[1:]):
            if x0 - 1e-9 <= v <= x1 + 1e-9:
                ln = y0 + (y1 - y0) * (v - x0) / (x1 - x0)
                break
        else:
            continue
        rate = math.exp(ln)
        live = max(live_s, 1e8 / rate)
        pts.append({"abs_v": v * 1e-3, "level_v": -v * 1e-3, "counts": int(round(rate * live)),
                    "live_s": live, "t": 0.0})
    return [{"direction": "up", "repeat": 1, "points": [dict(p, t=float(i)) for i, p in enumerate(pts)]},
            {"direction": "down", "repeat": 1,
             "points": [dict(p, t=float(len(pts) + i)) for i, p in enumerate(reversed(pts))]}]


def mv(v):
    return round(v * 1e3, 4)


def key_mv(v):
    """Integer key in units of 0.1 mV, robust against float noise."""
    return int(round(v * 1e4))


def write_csv(name, rows, columns=None):
    """Write rows (list of dicts) to out/<name>; returns the path."""
    path = os.path.join(OUT, name)
    if columns is None:
        columns = []
        for r in rows:
            for k in r:
                if k not in columns:
                    columns.append(k)
    with open(path, "w", newline="", encoding="utf-8") as handle:
        w = csv.DictWriter(handle, fieldnames=columns, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow({k: fmt(r.get(k)) for k in columns})
    return path


def read_csv(name):
    with open(os.path.join(OUT, name), encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def fmt(x):
    if x is None:
        return ""
    if isinstance(x, float):
        if not math.isfinite(x):
            return "nan"
        return f"{x:.6g}"
    return x


def poisson(rng, lam):
    """Poisson deviate, standard library only. Knuth for small means, a normal-corrected
    transformed-rejection (PTRS, Hormann 1993) for large ones."""
    if lam <= 0:
        return 0
    if lam < 30:
        L, k, p = math.exp(-lam), 0, 1.0
        while True:
            p *= rng.random()
            if p <= L:
                return k
            k += 1
    slam, loglam = math.sqrt(lam), math.log(lam)
    b = 0.931 + 2.53 * slam
    a = -0.059 + 0.02483 * b
    inv_alpha = 1.1239 + 1.1328 / (b - 3.4)
    vr = 0.9277 - 3.6224 / (b - 2)
    while True:
        u = rng.random() - 0.5
        v = rng.random()
        us = 0.5 - abs(u)
        k = math.floor((2 * a / us + b) * u + lam + 0.43)
        if us >= 0.07 and v <= vr:
            return int(k)
        if k < 0 or (us < 0.013 and v > us):
            continue
        if (math.log(v) + math.log(inv_alpha) - math.log(a / (us * us) + b)
                <= -lam + k * loglam - math.lgamma(k + 1)):
            return int(k)


def quantile(xs, q):
    s = sorted(xs)
    if not s:
        return float("nan")
    pos = q * (len(s) - 1)
    lo = int(math.floor(pos))
    hi = min(lo + 1, len(s) - 1)
    return s[lo] + (s[hi] - s[lo]) * (pos - lo)


def mean(xs):
    xs = list(xs)
    return sum(xs) / len(xs) if xs else float("nan")


def sd(xs):
    xs = list(xs)
    if len(xs) < 2:
        return float("nan")
    m = mean(xs)
    return math.sqrt(sum((x - m) ** 2 for x in xs) / (len(xs) - 1))


def loo_chi2(points, lo_v, hi_v, with_fit_variance=False):
    """Leave-one-out chi-square per threshold of the driver's dark fit over [lo_v, hi_v].

    Each threshold is predicted by _smooth_dark_rate from the others. By default chi-square is
    (observed - predicted)^2 / predicted, the definition that reproduces the handoff notes'
    numbers (3.76 and 2.25 over 6.2-10 mV). with_fit_variance adds the prediction's own variance
    to the denominator, which is the fairer test of over-dispersion (it can only lower the value).
    Returns (chi-square per threshold, number of thresholds)."""
    rows = sorted((st._rate_row(p) for p in points), key=lambda r: r["abs_v"])
    total, n = 0.0, 0
    for i, r in enumerate(rows):
        if not (lo_v - 1e-9 <= r["abs_v"] <= hi_v + 1e-9):
            continue
        others = rows[:i] + rows[i + 1:]
        fit = st._smooth_dark_rate(others, r["abs_v"])
        if fit is None:
            continue
        expected = fit[0] * r["live_s"]
        var = expected + ((fit[1] * expected) ** 2 if with_fit_variance else 0.0)
        total += (r["counts"] - expected) ** 2 / var
        n += 1
    return (total / n if n else float("nan")), n


def ml_common_ratio(pairs):
    """ML estimate of rho in rate2 = rho * rate1, each level's rate1 free (a nuisance), from
    [(c1, t1, c2, t2), ...]. Conditional on n = c1 + c2, c2 ~ Bin(n, rho t2 / (t1 + rho t2)).
    Returns (rho, sigma from the curvature, chi-square of the common-ratio fit, dof)."""
    pairs = [p for p in pairs if p[0] + p[2] > 0]

    def score(log_rho):
        rho = math.exp(log_rho)
        g = h = 0.0
        for c1, t1, c2, t2 in pairs:
            n = c1 + c2
            q = rho * t2 / (t1 + rho * t2)
            g += c2 - n * q
            h += n * q * (1 - q)
        return g, h

    x = 0.0
    for _ in range(100):
        g, h = score(x)
        step = g / h
        x += step
        if abs(step) < 1e-12:
            break
    _, h = score(x)
    rho = math.exp(x)
    chi = 0.0
    for c1, t1, c2, t2 in pairs:
        n = c1 + c2
        q = rho * t2 / (t1 + rho * t2)
        chi += (c2 - n * q) ** 2 / (n * q * (1 - q))
    return rho, rho / math.sqrt(h), chi, len(pairs) - 1


def light_result(dark_points, light_key):
    """analyse_light on a real light scan with the given dark points as background."""
    dark = st.analyse_dark(dark_points)
    return st.analyse_light(light_passes(light_key), dark), dark
