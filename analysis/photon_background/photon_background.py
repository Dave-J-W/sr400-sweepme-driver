"""Best SR400 discriminator level when the signal brings an inseparable photon background.

One command regenerates every output in this folder from the raw scan CSVs:

    python -I photon_background.py      (from this folder; standard library only)

Pure standard library plus the driver's own selftest.py (loaded by path, never modified). The four
2026-11-10 scans are read in place: the first pair from docs/real_data/2026-11-10/, the second from
analysis/low_signal_threshold/data/.

THE MODEL (the operator's situation, 2026-11-11)

  The signal of N photons/s (N = counts/s it would give at the valley level, as in
  analysis/low_signal_threshold) arrives with a photon background of f*N: stray light, scatter or
  fluorescence that comes only with the signal. It is made of photoelectrons, so it has the signal's
  pulse-height distribution and the threshold keeps the same fraction eps(v) of it. It is NOT in
  the signal-off run, which measures the dark rate b(v) only, and no threshold can separate it from
  the signal. So, counting for T in each run,

      on run:  C_on  ~ Poisson((eps*N*(1+f) + b) * T)
      off run: C_off ~ Poisson(b * T)
      estimate N_hat = (C_on - C_off) / (eps * (1 + f_assumed) * T)

  Two figures of merit, as before:
    equal_time_dark  the off run is as long as the on run (clock time 2T): m = 2
    known_dark       b(v) known precisely from a separate long dark run: m = 1
  with relative variance of N_hat, per unit counting time,

      V(v) = (eps*N*(1+f) + m*b) / (eps*N*(1+f))^2

  which is the photon-free relative variance at N' = N*(1+f). The systematic part: an uncertainty
  delta_f on the assumed f gives a relative error delta_f / (1 + f) on N_hat, the same at every
  level, because eps cancels. Total relative uncertainty after counting time T:

      sigma_tot(v, T) = sqrt(V(v) / T + sigma_sys^2)

  so the time to reach a total precision p is T_p(v) = V(v) / (p^2 - sigma_sys^2), infinite when
  p <= sigma_sys. This script checks each of these numerically (exact scaling on all four
  pairings, and a seeded Monte Carlo of the on/off estimate) rather than assuming it.

  b(v) is selftest._smooth_dark_rate; eps(v) = (light - b) / (light - b at the valley); candidate
  levels are the light scan's measured levels from the valley up, within the dark scan's range,
  where the fit is defined (as in analysis/low_signal_threshold).
"""

import csv
import importlib.util
import math
import os
import random
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))

_spec = importlib.util.spec_from_file_location(
    "sr400_selftest", os.path.join(ROOT, "Logger-Stanford_SR400", "selftest.py"))
st = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(st)

# ----------------------------------------------------------------------------- inputs
_REAL = os.path.join(ROOT, "docs", "real_data", "2026-11-10")
_SECOND = os.path.join(ROOT, "analysis", "low_signal_threshold", "data")
DARKS = {
    "D1": ("dark 13:20", os.path.join(_REAL, "SR400_threshold_scan_dark_2026-11-10_132008.csv")),
    "D2": ("dark 16:36", os.path.join(_SECOND, "SR400_threshold_scan_dark_2026-11-10_163608.csv")),
}
LIGHTS = {
    "L1": ("light 13:59", os.path.join(_REAL, "SR400_threshold_scan_light_2026-11-10_135935.csv")),
    "L2": ("light 17:24", os.path.join(_SECOND, "SR400_threshold_scan_light_2026-11-10_172444.csv")),
}
PAIRINGS = (("D1", "L1"), ("D1", "L2"), ("D2", "L1"), ("D2", "L2"))
PAIR_COLORS = {"D1L1": "#1f77b4", "D1L2": "#17becf", "D2L1": "#d62728", "D2L2": "#ff7f0e"}

N_VALUES = (1, 2, 5, 10, 20, 50, 100, 200, 500, 1000, 10000)
N_TABLE = (1, 10, 100, 1000)
F_VALUES = (0.0001, 0.001, 0.01, 0.03, 0.1, 0.2, 0.5)
# delta_f: relative to f (10, 30, 100 %) or absolute (1 and 5 percentage points of the signal).
DELTA_SPECS = (("rel", 0.10), ("rel", 0.30), ("rel", 1.00), ("abs", 0.01), ("abs", 0.05))
CASES = (("equal_time_dark", 2.0), ("known_dark", 1.0))
BAND = 0.95            # "within 5 %": figure of merit >= 0.95 of best, i.e. sigma <= best / 0.95
BAND10 = 0.90
P_TARGETS = (0.05, 0.10, 0.20)
FIXED_MV = (4.4, 5.2, 6.0, 6.8, 7.6, 9.2)
N_DENSE = [10.0 ** (k / 20.0) for k in range(0, 81)]          # 1 .. 1e4, 20 per decade
N_HEAT = [10.0 ** (k / 10.0) for k in range(0, 41)]           # 1 .. 1e4, 10 per decade
F_HEAT = [10.0 ** (-4 + k / 8.0) for k in range(0, 30)] + [0.5]  # 1e-4 .. 0.5
T_OVER_TCROSS = [10.0 ** (k / 10.0) for k in range(-20, 21)]  # 0.01 .. 100
SEED = 20261111
MC_TRIALS = 20000


def mv(v):
    return round(v * 1e3, 1)


def gui(v_mv):
    return st._gui_volts(v_mv * 1e-3)


def delta_of(f, spec):
    kind, x = spec
    return x * f if kind == "rel" else x


def spec_label(spec):
    kind, x = spec
    return f"delta_f = {x:.0%} of f" if kind == "rel" else f"delta_f = {x:.0%} absolute"


def sigma_sys(f, spec):
    return delta_of(f, spec) / (1.0 + f)


# ----------------------------------------------------------------------------- Poisson draws
def poisson(lam, rng):
    """Exact Poisson variate. Knuth below 10, Hoermann's PTRS transformed rejection above."""
    if lam <= 0:
        return 0
    if lam < 10:
        limit, k, p = math.exp(-lam), 0, 1.0
        while True:
            p *= rng.random()
            if p <= limit:
                return k
            k += 1
    slam, loglam = math.sqrt(lam), math.log(lam)
    b = 0.931 + 2.53 * slam
    a = -0.059 + 0.02483 * b
    invalpha = 1.1239 + 1.1328 / (b - 3.4)
    vr = 0.9277 - 3.6224 / (b - 2)
    while True:
        u = rng.random() - 0.5
        v = rng.random()
        us = 0.5 - abs(u)
        k = int(math.floor((2 * a / us + b) * u + lam + 0.43))
        if us >= 0.07 and v <= vr:
            return k
        if k < 0 or (us < 0.013 and v > us):
            continue
        if (math.log(v) + math.log(invalpha) - math.log(a / (us * us) + b)
                <= -lam + k * loglam - math.lgamma(k + 1)):
            return k


# ----------------------------------------------------------------------------- inputs per pairing
def candidates(dark_rows, light_rows, ref_v):
    """eps and b per level, from the valley up (the driver's floor), within the dark scan's range."""
    top = max(r["abs_v"] for r in dark_rows)
    ref_row = st._value_at(light_rows, ref_v)
    assert abs(ref_row["abs_v"] - ref_v) < 1e-9, "reference level missing from light scan"
    denom = ref_row["rate"] - st._smooth_dark_rate(dark_rows, ref_v)[0]
    out = []
    for r in light_rows:
        v = r["abs_v"]
        if v < ref_v - 1e-9 or v > top + 1e-9:
            continue
        fit = st._smooth_dark_rate(dark_rows, v)
        if fit is None:
            continue
        eps = (r["rate"] - fit[0]) / denom
        if eps > 0 and fit[0] > 0:
            out.append({"v": v, "mv": mv(v), "eps": eps, "b": fit[0]})
    return out


def by_mv(cands):
    return {c["mv"]: c for c in cands}


# ----------------------------------------------------------------------------- the model
def var_rel(c, n, f, m):
    """Relative variance of N_hat per second of counting (each run), photon background f."""
    s = c["eps"] * n * (1.0 + f)
    return (s + m * c["b"]) / (s * s)


def var_rel_subtractable(c, n, f, m):
    """Contrast case: the photon background is ALSO in the off run and is subtracted by on/off."""
    s = c["eps"] * n
    return (s * (1.0 + 2.0 * f) + m * c["b"]) / (s * s) if m == 2.0 else (s * (1.0 + f) + c["b"]) / (s * s)


def stat_opt(cands, n, f, m, var=var_rel):
    """Level minimising the statistical variance, and the band within 5 % of the best FOM."""
    vals = [var(c, n, f, m) for c in cands]
    i = min(range(len(vals)), key=lambda k: vals[k])
    inside = [k for k, x in enumerate(vals) if x <= vals[i] / BAND ** 2]
    return {"i": i, "c": cands[i], "var": vals[i], "vals": vals,
            "band_lo": cands[min(inside)]["mv"], "band_hi": cands[max(inside)]["mv"],
            "contiguous": len(inside) == max(inside) - min(inside) + 1,
            "at_floor": i == 0, "band_lo_at_floor": min(inside) == 0}


def time_to(var, p, ss):
    """Counting time (each run) to total precision p; infinite at or below the systematic floor."""
    return var / (p * p - ss * ss) if p - ss > 1e-12 else float("inf")


def fixed_t_band(vals, cands, t, ss, frac):
    """Levels whose total uncertainty after counting time t is within 1/frac of the best one."""
    tot = [math.sqrt(x / t + ss * ss) for x in vals]
    best = min(tot)
    inside = [k for k, x in enumerate(tot) if x <= best / frac]
    return cands[min(inside)]["mv"], cands[max(inside)]["mv"], inside


def common_levels(nominal):
    return sorted(set.intersection(*(set(by_mv(nominal[d + l])) for d, l in PAIRINGS)))


def robust(nominal, common, n, f, m):
    """One level for all four pairings (least worst-case time penalty), and the common 5 % band."""
    best = {d + l: stat_opt(nominal[d + l], n, f, m) for d, l in PAIRINGS}
    looks = {k: by_mv(nominal[k]) for k in best}

    def worst(v):
        return max(var_rel(looks[k][v], n, f, m) / best[k]["var"] for k in best)

    pick = min(common, key=worst)
    inside = [v for v in common if all(var_rel(looks[k][v], n, f, m) <= best[k]["var"] / BAND ** 2 for k in best)]
    return {"pick": pick, "worst": worst(pick), "inside": inside, "best": best}


def two_sig(x):
    if not math.isfinite(x):
        return x
    return float(f"{x:.2g}")


def fmt_t(x):
    if not math.isfinite(x):
        return "never"
    if x >= 1e4:
        return f"{x:.2g}".replace("e+0", "e").replace("e+", "e")
    return f"{x:.3g}"


def fmt_range(lo, hi, unit="", fmt="{:.3g}"):
    if lo == hi:
        return fmt.format(lo) + unit
    return fmt.format(lo) + "-" + fmt.format(hi) + unit


# ----------------------------------------------------------------------------- SVG helpers
class Panel(st._Panel):
    """selftest's _Panel with optional log x, decade labels and minor log ticks."""

    def __init__(self, svg, x, y, w, h, xlim, ylim, log_x=False, log_y=False):
        self.log_x = log_x
        super().__init__(svg, x, y, w, h, xlim, ylim, log_y)

    def px(self, v):
        if not self.log_x:
            return super().px(v)
        t = (math.log10(v) - math.log10(self.x0)) / (math.log10(self.x1) - math.log10(self.x0))
        return self.x + t * self.w

    @staticmethod
    def _dec(k):
        return {-4: "1e-4", -3: "0.001", -2: "0.01", -1: "0.1", 0: "1", 1: "10", 2: "100",
                3: "1000"}.get(k, f"1e{k}")

    def frame(self, title, xlabel, ylabel, xticks=None, ylabels=None):
        s = self.svg
        if self.log_x:
            for k in range(math.floor(math.log10(self.x0)), math.ceil(math.log10(self.x1)) + 1):
                for m in range(1, 10):
                    v = m * 10.0 ** k
                    if not (self.x0 * 0.999 <= v <= self.x1 * 1.001):
                        continue
                    X = self.px(v)
                    s.line(X, self.y, X, self.y + self.h, "#e4e4e4" if m == 1 else "#f4f4f4", 1)
                    s.line(X, self.y + self.h, X, self.y + self.h + (5 if m == 1 else 2.5), "#222", 1)
                    if m == 1:
                        s.text(X, self.y + self.h + 16, self._dec(k), 10, "middle")
        else:
            for tick in (xticks or st._nice_ticks(self.x0, self.x1)):
                X = self.px(tick)
                s.line(X, self.y, X, self.y + self.h, "#eeeeee", 1)
                s.line(X, self.y + self.h, X, self.y + self.h + 4, "#222", 1)
                s.text(X, self.y + self.h + 16, st._fmt(tick), 10, "middle")
        if self.log_y:
            for k in range(math.floor(math.log10(self.y0) + 1e-9), math.ceil(math.log10(self.y1) - 1e-9) + 1):
                for m in range(1, 10):
                    v = m * 10.0 ** k
                    if not (self.y0 * 0.999 <= v <= self.y1 * 1.001):
                        continue
                    Y = self.py(v)
                    s.line(self.x, Y, self.x + self.w, Y, "#e4e4e4" if m == 1 else "#f6f6f6", 1)
                    s.line(self.x - (5 if m == 1 else 2.5), Y, self.x, Y, "#222", 1)
                    if m == 1:
                        s.text(self.x - 7, Y + 4, self._dec(k), 10, "end")
        else:
            for tick in st._nice_ticks(self.y0, self.y1, 6):
                Y = self.py(tick)
                s.line(self.x, Y, self.x + self.w, Y, "#eeeeee", 1)
                s.line(self.x - 4, Y, self.x, Y, "#222", 1)
                s.text(self.x - 6, Y + 4, (ylabels or st._fmt)(tick), 10, "end")
        s.rect(self.x, self.y, self.w, self.h, stroke="#222")
        s.text(self.x, self.y - 8, title, 13, weight="bold")
        s.text(self.x + self.w / 2, self.y + self.h + 34, xlabel, 11, "middle")
        s.text(self.x - 48, self.y + self.h / 2, ylabel, 11, "middle", rotate=-90)

    def polygon(self, pts, color, opacity):
        coords = " ".join(f"{self.px(x):.1f},{self.py(y):.1f}" for x, y in pts)
        self.svg.parts.append(f'<polygon points="{coords}" fill="{color}" fill-opacity="{opacity}" '
                              f'stroke="none" clip-path="url(#{self.clip})"/>')


PROVENANCE = ("eps(v) from room-light scans (light 13:59, light 17:24); b(v) from the 2026-11-10 dark "
              "scans (dark 13:20, dark 16:36), fitted by selftest._smooth_dark_rate. R8486 at ~1000 V "
              "(operator; HV not in the files). The photon background is a MODEL: fraction f of the "
              "signal, same pulse heights, absent from the off run.")

# Sequential palette for levels (dark blue = low level, yellow = high level), 3.8 .. 7.6 mV.
_PALETTE = ((0.0, (68, 1, 84)), (0.25, (59, 82, 139)), (0.5, (33, 145, 140)),
            (0.75, (94, 201, 98)), (1.0, (253, 231, 37)))
LEVEL_LO, LEVEL_HI = 3.8, 7.6


def level_color(level):
    t = min(max((level - LEVEL_LO) / (LEVEL_HI - LEVEL_LO), 0.0), 1.0)
    for (t0, c0), (t1, c1) in zip(_PALETTE, _PALETTE[1:]):
        if t <= t1:
            u = (t - t0) / (t1 - t0)
            return "#%02x%02x%02x" % tuple(int(round(a + (b - a) * u)) for a, b in zip(c0, c1))
    return "#%02x%02x%02x" % _PALETTE[-1][1]


# ----------------------------------------------------------------------------- figures
def fig_optimum_plane(nominal, common):
    svg = st._Svg(1200, 1020)
    svg.text(30, 26, "Best discriminator level for a signal of N counts/s with an inseparable photon "
             "background f*N", 15, weight="bold")
    titles = {"equal_time_dark": "A. Dark measured in an off run of equal length",
              "known_dark": "B. Dark known precisely (separate long dark run)"}
    for k, (case, m) in enumerate(CASES):
        x0 = 90 + k * 560
        p = Panel(svg, x0, 70, 440, 300, (N_HEAT[0], N_HEAT[-1]), (F_HEAT[0], 0.5), log_x=True, log_y=True)
        # frame (ticks, labels) first, then the cells over its grid lines, then the outline again
        p.frame(titles[case], "N: signal rate, counts/s at the valley level", "photon background fraction f")
        for i, n in enumerate(N_HEAT):
            nlo = math.sqrt(N_HEAT[i - 1] * n) if i else n
            nhi = math.sqrt(N_HEAT[i + 1] * n) if i + 1 < len(N_HEAT) else n
            for j, f in enumerate(F_HEAT):
                flo = math.sqrt(F_HEAT[j - 1] * f) if j else f
                fhi = math.sqrt(F_HEAT[j + 1] * f) if j + 1 < len(F_HEAT) else f
                lvl = robust(nominal, common, n, f, m)["pick"]
                X0, X1 = p.px(nlo), p.px(nhi)
                Y0, Y1 = p.py(fhi), p.py(flo)
                svg.rect(X0, Y0, X1 - X0 + 0.6, Y1 - Y0 + 0.6, fill=level_color(lvl), clip=p.clip)
        svg.rect(p.x, p.y, p.w, p.h, stroke="#222")
        # lines of constant N' = N (1 + f): the photon-free answer is constant along each
        for c_n in (2, 10, 100, 1000):
            pts = [(c_n / (1 + f), f) for f in F_HEAT]
            p.series([x for x, _ in pts], [y for _, y in pts], "#ffffff", width=1.0, dash="4,3")
            svg.text(p.px(c_n / 1.2) + 3, p.py(0.2), f"N' = {c_n}", 9, "start", color="#ffffff")
    # colour bar
    bx, by, bw = 90, 432, 440
    svg.text(bx, by - 6, "best level (one level for all four pairings), mV; GUI value = -level/1000 V", 11)
    steps = [round(LEVEL_LO + 0.2 * k, 1) for k in range(int(round((LEVEL_HI - LEVEL_LO) / 0.2)) + 1)]
    w = bw / len(steps)
    for k, s in enumerate(steps):
        svg.rect(bx + k * w, by, w + 0.5, 14, fill=level_color(s))
        if k % 2 == 0:
            svg.text(bx + k * w + w / 2, by + 27, f"{s:.1f}", 9, "middle")
    st._text_block(svg, 650, by + 4, 92, [
        "Dashed white: lines of constant N' = N (1 + f). The statistical optimum is exactly the photon-free one "
        "at N', so the level is constant along each. They are nearly vertical: f acts like a brighter signal, "
        "by at most x1.5 at f = 50 %."], size=10)

    # band panels: robust level and the common 5 % band against N, for f = 0, 0.1, 0.5
    colors = {0.0: "#555555", 0.1: "#1f77b4", 0.5: "#d62728"}
    for k, (case, m) in enumerate(CASES):
        x0 = 90 + k * 560
        p = Panel(svg, x0, 500, 440, 300, (1, 1e4), (3.6, 8.0), log_x=True)
        p.frame(("C. " if k == 0 else "D. ") + titles[case][3:], "N: signal rate, counts/s at the valley level",
                "best level |v| (mV)")
        for f, color in colors.items():
            rob = [robust(nominal, common, n, f, m) for n in N_DENSE]
            up = [(n, max(r["inside"]) + 0.05) for n, r in zip(N_DENSE, rob)]
            lo = [(n, min(r["inside"]) - 0.05) for n, r in zip(N_DENSE, rob)]
            p.polygon(up + lo[::-1], color, 0.10)
            p.series(N_DENSE, [r["pick"] for r in rob], color, width=1.8,
                     label=f"f = {f:g}: one level for all four; shaded: within 5 % in all four")
        p.hline(4.0, "#8e44ad", "valley 4.0 / 3.8 mV: lowest level scored", dash="2,3", left=True)
        p.hline(3.8, "#8e44ad", "", dash="2,3")
        p.legend()
    st._text_block(svg, 30, 860, 175, [
        PROVENANCE,
        "Statistical optimum only. The systematic error from an uncertain f does not depend on the level, so it "
        "does not move the best level; see fig_total_time_vs_level.svg and fig_flatness_fixed_time.svg for what "
        "it does change. Levels are the scanned grid (0.2 mV steps below 6 mV, 0.4 mV above); every level shown "
        "is below 10 mV, so valid only with the cables as they were (manual p. 22).",
    ], size=11)
    return svg.render()


def fig_time_vs_level(nominal, key="D1L1"):
    svg = st._Svg(1200, 900)
    svg.text(30, 26, "Counting time to a TOTAL precision p, statistical plus the systematic from an uncertain f "
             f"({DARKS[key[:2]][0]} + {LIGHTS[key[2:]][0]}, equal-time off run)", 15, weight="bold")
    cands = nominal[key]
    f = 0.1
    colors = ("#555555", "#1f77b4", "#2ca02c", "#d62728", "#9467bd", "#ff7f0e")
    specs = [None] + list(DELTA_SPECS)
    best_notes = []
    for row, n in enumerate((10, 100)):
        y0 = 70 + row * 380
        # A/C: time to p = 10 % against level
        p = Panel(svg, 90, y0, 480, 280, (3.6, 15.4), (0.1, 1e6) if n == 10 else (0.01, 1e5), log_y=True)
        p.frame(f"{'AC'[row]}. N = {n} counts/s, f = 10 %: time to total p = 10 % against level",
                "discriminator level |v| (mV)", "time per run T (s)")
        for spec, color in zip(specs, colors):
            ss = 0.0 if spec is None else sigma_sys(f, spec)
            ts = [time_to(var_rel(c, n, f, 2.0), 0.10, ss) for c in cands]
            label = ("statistics only" if spec is None else spec_label(spec)) + f" (floor {ss:.1%})"
            if not all(math.isfinite(t) for t in ts):
                p.legend_items.append((label + ": never", color, None, "2,2", True, True))
                continue
            p.series([c["mv"] for c in cands], ts, color, width=1.5, label=label)
            o = stat_opt(cands, n, f, 2.0)
            p.series([o["c"]["mv"]], [time_to(o["var"], 0.10, ss)], color, marker="o")
        p.vline(10.0, st._C["pickup"], "10 mV", slot=0)
        p.legend()
        # B/D: time at the best level against p, diverging at each floor
        q = Panel(svg, 680, y0, 480, 280, (0.005, 0.5), (0.1, 1e6) if n == 10 else (0.01, 1e5),
                  log_x=True, log_y=True)
        q.frame(f"{'BD'[row]}. Same N and f: time at the best level against target p",
                "target total relative precision p", "time per run T (s)")
        o = stat_opt(cands, n, f, 2.0)
        ps = [10.0 ** (-2.3 + k / 60.0) for k in range(0, 121)]
        for spec, color in zip(specs, colors):
            ss = 0.0 if spec is None else sigma_sys(f, spec)
            pts = [(pp, time_to(o["var"], pp, ss)) for pp in ps if pp > ss * 1.0005]
            q.series([x for x, _ in pts], [y for _, y in pts], color, width=1.5)
            if ss > 0:
                q.vline(ss, color, "", dash="2,3")
        best_notes.append(f"N = {n}: best level {o['c']['mv']} mV, the photon-free optimum at N' = {n * 1.1:g}")
    st._text_block(svg, 30, 830, 175, [
        PROVENANCE,
        "A, C: every finite curve is the statistics-only curve times the same factor 1 / (1 - floor^2 / p^2), so on "
        "a log axis they are parallel and the best level and the levels within 5 % of the best TIME do not change "
        "with delta_f. B, D: dotted verticals are the systematic floors; the time diverges as p approaches each one ("
        + "; ".join(best_notes) + "). T is the length of each run (on and off); clock time 2T.",
    ], size=11)
    return svg.render()


def fig_flatness(nominal, key="D1L1"):
    svg = st._Svg(1200, 760)
    svg.text(30, 26, "At a FIXED counting time, how flat is total precision against level? "
             f"({DARKS[key[:2]][0]} + {LIGHTS[key[2:]][0]}, f = 10 %, equal-time off run)", 15, weight="bold")
    cands = nominal[key]
    f = 0.1
    colors = {1: "#9467bd", 10: "#1f77b4", 100: "#2ca02c", 1000: "#d62728"}
    p = Panel(svg, 90, 70, 480, 320, (0.01, 100), (3.6, 18.6), log_x=True)
    p.frame("A. Levels within 5 % of the best total precision", "T / T_cross  (T_cross: counting noise = systematic)",
            "discriminator level |v| (mV)")
    q = Panel(svg, 680, 70, 480, 320, (0.01, 100), (0, 15), log_x=True)
    q.frame("B. Width of that range (5 %: solid, 10 %: dashed)", "T / T_cross", "range of levels (mV)")
    for n, color in colors.items():
        o = stat_opt(cands, n, f, 2.0)
        ss = 1.0  # any floor: the band depends only on T / T_cross
        t_cross = o["var"] / ss ** 2
        lo5, hi5, w5, w10 = [], [], [], []
        for r in T_OVER_TCROSS:
            a, b, _ = fixed_t_band(o["vals"], cands, r * t_cross, ss, BAND)
            c, d, _ = fixed_t_band(o["vals"], cands, r * t_cross, ss, BAND10)
            lo5.append(a); hi5.append(b); w5.append(b - a); w10.append(d - c)
        p.polygon(list(zip(T_OVER_TCROSS, [h + 0.05 for h in hi5])) + list(zip(T_OVER_TCROSS, [l - 0.05 for l in lo5]))[::-1],
                  color, 0.12)
        p.series(T_OVER_TCROSS, lo5, color, width=1.4, label=f"N = {n} counts/s (best {o['c']['mv']} mV)")
        p.series(T_OVER_TCROSS, hi5, color, width=1.4)
        q.series(T_OVER_TCROSS, w5, color, width=1.6, label=f"N = {n}")
        q.series(T_OVER_TCROSS, w10, color, width=1.2, dash="4,3")
    p.hline(cands[-1]["mv"], "#555", f"top of the scored range ({cands[-1]['mv']} mV)", dash="2,3", left=True)
    p.legend()
    q.legend()
    for panel in (p, q):
        panel.vline(1.0, "#555", "T = T_cross", slot=5)
    st._text_block(svg, 30, 460, 175, [
        "How to read it. T_cross = V(best) / sigma_sys^2 is the counting time (each run) at which the counting noise "
        "at the best level equals the systematic floor from delta_f. Counting much less than T_cross (left), the "
        "statistics dominate and the range is the photon-free 5 % band at N' = N (1 + f). Counting much longer "
        "(right), the total approaches the systematic floor at every level, so the range spreads over most of the "
        "scored range: the threshold matters less and less, but so does the extra counting time.",
        "The range depends only on T / T_cross and N', not on delta_f itself: a larger delta_f just makes T_cross "
        "shorter. In terms of time to reach a target precision p the range does NOT widen (fig_total_time_vs_level): "
        "the systematic multiplies every level's time by the same factor.",
        PROVENANCE,
    ], size=11)
    return svg.render()


def fig_f_equal_dark(f_eq):
    svg = st._Svg(1200, 600)
    svg.text(30, 26, "Photon background fraction at which it adds as much counting noise as the dark "
             "counts, at the best level", 15, weight="bold")
    for k, (case, m) in enumerate(CASES):
        p = Panel(svg, 90 + k * 560, 70, 440, 320, (1, 1e4), (1e-4, 100), log_x=True, log_y=True)
        p.frame(("A. Equal-time off run: f N eps = 2 b" if m == 2 else "B. Dark known: f N eps = b"),
                "N: signal rate, counts/s at the valley level", "f (fraction of the signal)")
        p.svg.rect(p.x, p.py(0.5), p.w, p.py(1e-4) - p.py(0.5), fill="#f39c12", opacity=0.10)
        for d, l in PAIRINGS:
            key = d + l
            pts = f_eq[(key, case)]
            p.series([n for n, _ in pts], [x for _, x in pts], PAIR_COLORS[key], width=1.6,
                     label=f"{DARKS[d][0]} + {LIGHTS[l][0]}")
        p.hline(0.5, "#b9770e", "f = 50 %, top of the operator's range", dash="3,3")
        p.legend()
    st._text_block(svg, 30, 450, 175, [
        "Above a curve, the photon background contributes more to the on-run counting noise than the dark counts "
        "do; below it, the dark counts dominate. Shaded: the operator's range f = 0.01 % to 50 %. At N ~ 1 count/s "
        "the dark counts dominate the noise for any f in that range; at N = 10 the photon background takes over "
        "from f ~ 30-70 %, at N = 100 from ~8-9 %, at N = 1000 from ~3-6 % (equal-time off run). Either way the "
        "best level only moves as N -> N (1 + f).",
        PROVENANCE,
    ], size=11)
    return svg.render()


# ----------------------------------------------------------------------------- main
def main():
    rng = random.Random(SEED)
    nominal, meta = {}, {}
    darks = {k: st.analyse_dark(st.read_scan_csv(p)[1]) for k, (_, p) in DARKS.items()}
    lights = {k: st.analyse_light(st.read_scan_csv(p)[1], None) for k, (_, p) in LIGHTS.items()}
    for d, l in PAIRINGS:
        nominal[d + l] = candidates(darks[d]["rows"], lights[l]["rows"], lights[l]["reference_v"])
    common = common_levels(nominal)
    lines = []
    say = lines.append
    say("PHOTON BACKGROUND -- machine-written summary (do not edit; regenerate)")
    say(f"python {sys.version.split()[0]}, Monte Carlo {MC_TRIALS} trials per level, seed {SEED}")
    say("")
    say("CANDIDATE LEVELS (valley up, within the dark scan, fit defined)")
    for d, l in PAIRINGS:
        c = nominal[d + l]
        say(f"  {d}{l}: {len(c)} levels {c[0]['mv']}-{c[-1]['mv']} mV; valley {mv(lights[l]['reference_v'])} mV")

    # ---- 1. the statistical scaling, checked level by level and optimum by optimum --------------
    say("")
    say("CHECK 1: statistical part = photon-free analysis at N' = N (1 + f)")
    worst_ratio, checked, mismatch, floor_cases = 0.0, 0, [], 0
    for d, l in PAIRINGS:
        cands = nominal[d + l]
        for case, m in CASES:
            for n in N_DENSE + list(N_VALUES):
                for f in F_VALUES:
                    a = stat_opt(cands, n, f, m)
                    b = stat_opt(cands, n * (1 + f), 0.0, m)
                    for c, va, vb in zip(cands, a["vals"], b["vals"]):
                        worst_ratio = max(worst_ratio, abs(va / vb - 1.0))
                    checked += 1
                    same = (a["i"] == b["i"] and a["band_lo"] == b["band_lo"] and a["band_hi"] == b["band_hi"]
                            and a["at_floor"] == b["at_floor"] and a["band_lo_at_floor"] == b["band_lo_at_floor"])
                    if not same:
                        mismatch.append((d + l, case, n, f))
                    floor_cases += a["band_lo_at_floor"]
    say(f"  per-level variance, (N, f) against photon-free at N': max |ratio - 1| = {worst_ratio:.1e} "
        f"(floating point only)")
    say(f"  best level, 5 % band edges and floor flags compared in {checked} cases (4 pairings x 2 cases x "
        f"{len(N_DENSE) + len(N_VALUES)} N x {len(F_VALUES)} f): {len(mismatch)} differ")
    rob_mis = sum(1 for case, m in CASES for n in N_VALUES for f in F_VALUES
                  if robust(nominal, common, n, f, m)["pick"] != robust(nominal, common, n * (1 + f), 0.0, m)["pick"]
                  or robust(nominal, common, n, f, m)["inside"] != robust(nominal, common, n * (1 + f), 0.0, m)["inside"])
    say(f"  one-level-for-all-four choice and its common band: {rob_mis} of {len(CASES) * len(N_VALUES) * len(F_VALUES)} differ")
    # Where it is NOT exact: reading the photon-free answer off a table tabulated only at N_VALUES.
    lookup_diff, lookup_max, lookup_n = 0, 0.0, 0
    for case, m in CASES:
        for n in N_DENSE:
            for f in F_VALUES:
                exact = robust(nominal, common, n * (1 + f), 0.0, m)["pick"]
                row = min(N_VALUES, key=lambda x: abs(math.log(x) - math.log(n * (1 + f))))
                table = robust(nominal, common, row, 0.0, m)["pick"]
                lookup_n += 1
                if abs(exact - table) > 1e-9:
                    lookup_diff += 1
                    lookup_max = max(lookup_max, abs(exact - table))
    say(f"  NOT exact only when the photon-free answer is read off a table at N = {', '.join(map(str, N_VALUES))}: "
        f"nearest-row lookup of N' differs in {lookup_diff} of {lookup_n} (N, f) cases, by up to {lookup_max:.1f} mV "
        f"(the table's own discreteness, not the model)")
    say(f"  valley floor: the 5 % band reaches the valley in {floor_cases} of {checked} cases, identically at "
        f"(N, f) and at N' (the floor is the same candidate set)")

    # ---- 2. Monte Carlo of the on/off estimate: bias and spread --------------------------------
    say("")
    say("CHECK 2: Monte Carlo of N_hat = (C_on - C_off) / (eps (1 + f_assumed) T), D1L1, N = 10/s, true f = 0.1, T = 100 s")
    cands = nominal["D1L1"]
    look = by_mv(cands)
    mc_rows = []
    for f_assumed in (0.10, 0.13):
        for v in FIXED_MV:
            c = look.get(v)
            if c is None:
                continue
            n, f, t = 10.0, 0.10, 100.0
            lam_on = (c["eps"] * n * (1 + f) + c["b"]) * t
            lam_off = c["b"] * t
            est = [(poisson(lam_on, rng) - poisson(lam_off, rng)) / (c["eps"] * (1 + f_assumed) * t) / n
                   for _ in range(MC_TRIALS)]
            mean = sum(est) / len(est)
            sd = math.sqrt(sum((x - mean) ** 2 for x in est) / (len(est) - 1))
            pred_bias = (f - f_assumed) / (1 + f_assumed)
            pred_sd = math.sqrt(var_rel(c, n, f, 2.0) / t) * (1 + f) / (1 + f_assumed)
            mc_rows.append((f_assumed, v, mean - 1, pred_bias, sd, pred_sd, sd / math.sqrt(MC_TRIALS)))
            say(f"  f_assumed {f_assumed:.2f}, {v:.1f} mV: bias {mean - 1:+.4f} (model {pred_bias:+.4f}, MC +-"
                f"{sd / math.sqrt(MC_TRIALS):.4f}); relative sd {sd:.4f} (model {pred_sd:.4f})")
    worst_bias = max(abs(r[2] - r[3]) / r[6] for r in mc_rows)
    worst_sd = max(abs(r[4] / r[5] - 1) for r in mc_rows)
    say(f"  worst bias disagreement {worst_bias:.1f} MC standard errors; worst sd disagreement {worst_sd:.1%} "
        f"(MC precision on an sd ~{1 / math.sqrt(2 * MC_TRIALS):.1%})")
    say("  the bias is the same at every level: the threshold does not change the systematic")

    # ---- results.csv: statistical optimum over pairing x N x f x case ---------------------------
    header = ["pairing", "figure_of_merit", "N_counts_per_s_at_valley", "f", "N_equivalent_photon_free",
              "opt_level_mV", "opt_gui_V", "band5pct_lo_mV", "band5pct_hi_mV", "band_lo_at_valley_floor",
              "opt_at_valley_floor", "eps_at_opt", "dark_b_at_opt_cps", "photon_bg_counted_cps",
              "rel_variance_per_s_at_opt", "T_stat_to_10pct_s", "T_stat_to_10pct_f0_s",
              "photon_free_opt_at_N_equiv_mV", "matches_photon_free"]
    header += [f"T_stat_to_10pct_at_{v:.1f}mV_s" for v in FIXED_MV]
    rows = []
    for d, l in PAIRINGS:
        cands = nominal[d + l]
        look = by_mv(cands)
        for case, m in CASES:
            for n in N_VALUES:
                for f in (0.0,) + F_VALUES:
                    o = stat_opt(cands, n, f, m)
                    ref = stat_opt(cands, n * (1 + f), 0.0, m)
                    o0 = stat_opt(cands, n, 0.0, m)
                    c = o["c"]
                    row = [f"{DARKS[d][0]} + {LIGHTS[l][0]}", case, n, f, f"{n * (1 + f):.6g}", c["mv"], gui(c["mv"]),
                           o["band_lo"], o["band_hi"], o["band_lo_at_floor"], o["at_floor"], f"{c['eps']:.4f}",
                           f"{c['b']:.4g}", f"{c['eps'] * n * f:.4g}", f"{o['var']:.5g}",
                           f"{time_to(o['var'], 0.1, 0.0):.4g}", f"{time_to(o0['var'], 0.1, 0.0):.4g}",
                           ref["c"]["mv"], ref["c"]["mv"] == c["mv"] and ref["band_lo"] == o["band_lo"]
                           and ref["band_hi"] == o["band_hi"]]
                    row += [f"{time_to(var_rel(look[v], n, f, m), 0.1, 0.0):.4g}" if v in look else "" for v in FIXED_MV]
                    rows.append(row)
    with open(os.path.join(HERE, "results.csv"), "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(header)
        w.writerows(rows)

    # ---- total_uncertainty.csv: systematic floor, T_cross, time to p, fixed-time bands ------------
    t_header = ["pairing", "figure_of_merit", "N_counts_per_s_at_valley", "f", "delta_f_spec", "delta_f",
                "sigma_sys", "best_level_mV", "T_cross_s"]
    t_header += [f"T_to_total_{p:.0%}_s" for p in P_TARGETS]
    t_header += ["band5_time_to_p_lo_mV", "band5_time_to_p_hi_mV",
                 "band5_at_T_cross_lo_mV", "band5_at_T_cross_hi_mV",
                 "band5_at_10T_cross_lo_mV", "band5_at_10T_cross_hi_mV"]
    t_rows = []
    time_band_mis, time_band_n = 0, 0
    for d, l in PAIRINGS:
        cands = nominal[d + l]
        for case, m in CASES:
            for n in N_VALUES:
                for f in F_VALUES:
                    o = stat_opt(cands, n, f, m)
                    for spec in DELTA_SPECS:
                        ss = sigma_sys(f, spec)
                        tc = o["var"] / ss ** 2
                        # levels within 5 % of the best TIME to p = 20 % (or the smallest p above the floor)
                        p_use = next((p for p in P_TARGETS[::-1] if p - ss > 1e-12), None)
                        if p_use is not None:
                            ts = [time_to(x, p_use, ss) for x in o["vals"]]
                            inside = [k for k, x in enumerate(ts) if x <= min(ts) / BAND ** 2]
                            tb = (cands[min(inside)]["mv"], cands[max(inside)]["mv"])
                            time_band_n += 1
                            time_band_mis += tb != (o["band_lo"], o["band_hi"])
                        else:
                            tb = ("", "")
                        b1 = fixed_t_band(o["vals"], cands, tc, ss, BAND)
                        b10 = fixed_t_band(o["vals"], cands, 10 * tc, ss, BAND)
                        t_rows.append([f"{DARKS[d][0]} + {LIGHTS[l][0]}", case, n, f, f"{spec[0]} {spec[1]:g}",
                                       f"{delta_of(f, spec):.6g}", f"{ss:.5g}", o["c"]["mv"], f"{tc:.4g}"]
                                      + [fmt_t(time_to(o["var"], p, ss)) for p in P_TARGETS]
                                      + [tb[0], tb[1], b1[0], b1[1], b10[0], b10[1]])
    with open(os.path.join(HERE, "total_uncertainty.csv"), "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(t_header)
        w.writerows(t_rows)
    say("")
    say("CHECK 3: the systematic multiplies every level's time-to-p by the same factor")
    say(f"  levels within 5 % of the best time to p, against the statistical 5 % band: {time_band_mis} of "
        f"{time_band_n} (pairing x case x N x f x delta_f, with p the largest of {P_TARGETS} above the floor) differ")

    # ---- fixed counting time: how wide the near-best range is, as a function of T / T_cross --------
    say("")
    say("CHECK 4: at fixed counting time T the near-best range depends only on T / T_cross and N'")
    say("  closed form: within 5 % of the best total precision <=> V(v) / V(best) <= 1/0.95^2 + (1/0.95^2 - 1) T / T_cross")
    form_mis, form_n = 0, 0
    for d, l in PAIRINGS:
        cands = nominal[d + l]
        for n in N_VALUES:
            for f in F_VALUES:
                o = stat_opt(cands, n, f, 2.0)
                for r in T_OVER_TCROSS:
                    _, _, inside = fixed_t_band(o["vals"], cands, r * o["var"], 1.0, BAND)
                    limit = 1 / BAND ** 2 + (1 / BAND ** 2 - 1) * r
                    formula = [k for k, x in enumerate(o["vals"]) if x / o["var"] <= limit * (1 + 1e-12)]
                    form_n += 1
                    form_mis += inside != formula
    say(f"  direct band against the closed form: {form_mis} of {form_n} cases differ")
    say("  D1L1, f = 0.1, equal-time off run: levels within 5 % [10 %] of the best total precision at T = r * T_cross")
    flat_rows = []
    for n in N_TABLE:
        o = stat_opt(nominal["D1L1"], n, 0.1, 2.0)
        parts = []
        for r in (0.1, 0.3, 1.0, 3.0, 10.0):
            a, b, _ = fixed_t_band(o["vals"], nominal["D1L1"], r * o["var"], 1.0, BAND)
            c, e, _ = fixed_t_band(o["vals"], nominal["D1L1"], r * o["var"], 1.0, BAND10)
            parts.append(f"r={r:g}: {a}-{b} [{c}-{e}]")
            flat_rows.append([n, 0.1, r, a, b, round(b - a, 1), c, e, round(e - c, 1)])
        say(f"    N={n:>4} (best {o['c']['mv']} mV): " + "; ".join(parts))
    with open(os.path.join(HERE, "flatness_fixed_time.csv"), "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["N_counts_per_s_at_valley", "f", "T_over_T_cross", "band5_lo_mV", "band5_hi_mV", "band5_width_mV",
                    "band10_lo_mV", "band10_hi_mV", "band10_width_mV"])
        w.writerows(flat_rows)

    # ---- the operator's table: one level and one common band across the four pairings -----------
    say("")
    say("OPERATOR TABLE (equal-time off run; one level for all four pairings; T common to all four = geometric")
    say("  mean of their T_cross, 2 significant figures; 'within 5 %' = within 5 % of the best total precision")
    say("  at that T in all four pairings)")
    op_rows = []
    for n in N_TABLE:
        for f, spec in ([(0.1, s) for s in DELTA_SPECS] + [(0.01, ("rel", 0.30)), (0.5, ("rel", 0.30))]):
            m = 2.0
            rob = robust(nominal, common, n, f, m)
            ss = sigma_sys(f, spec)
            tcs = [rob["best"][k]["var"] / ss ** 2 for k in rob["best"]]
            t1 = two_sig(math.exp(sum(math.log(x) for x in tcs) / len(tcs)))
            bands = {}
            for mult in (1, 10):
                lo_all, hi_all = [], []
                for k in rob["best"]:
                    a, b, _ = fixed_t_band(rob["best"][k]["vals"], nominal[k], mult * t1, ss, BAND)
                    lo_all.append(a)
                    hi_all.append(b)
                bands[mult] = (max(lo_all), min(hi_all))
            p10 = [time_to(rob["best"][k]["var"], 0.10, ss) for k in rob["best"]]
            op_rows.append([n, f, f"{spec[0]} {spec[1]:g}", f"{delta_of(f, spec):.4g}", f"{ss:.4g}", rob["pick"],
                            gui(rob["pick"]), min(rob["inside"]), max(rob["inside"]), t1,
                            bands[1][0], bands[1][1], two_sig(10 * t1), bands[10][0], bands[10][1],
                            fmt_t(min(p10)), fmt_t(max(p10))])
            say(f"  N={n:>4}, f={f:g} {spec_label(spec)} (+-{delta_of(f, spec):.3g}): floor {ss:.2%}; set {rob['pick']} mV "
                f"(GUI {gui(rob['pick'])}); statistical 5 % band {min(rob['inside'])}-{max(rob['inside'])} mV; "
                f"after T = {t1:g} s within 5 %: {bands[1][0]}-{bands[1][1]} mV; after {two_sig(10 * t1):g} s: "
                f"{bands[10][0]}-{bands[10][1]} mV; time to total 10 %: {fmt_t(min(p10))}-{fmt_t(max(p10))} s")
    with open(os.path.join(HERE, "operator_table.csv"), "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["N_counts_per_s_at_valley", "f", "delta_f_spec", "delta_f", "sigma_sys", "set_level_mV",
                    "set_gui_V", "stat_band5_all_lo_mV", "stat_band5_all_hi_mV", "T_s", "band5_at_T_lo_mV",
                    "band5_at_T_hi_mV", "T10_s", "band5_at_T10_lo_mV", "band5_at_T10_hi_mV",
                    "T_to_total_10pct_min_s", "T_to_total_10pct_max_s"])
        w.writerows(op_rows)

    # ---- the statistical grid the operator sets the level from ----------------------------------
    for case, m in CASES:
        say("")
        say(f"STATISTICAL OPTIMUM, one level for all four pairings -- {case} (level mV [common 5 % band])")
        for n in N_VALUES:
            say(f"  N={n:>5}: " + "  ".join(
                f"f={f:g}: {robust(nominal, common, n, f, m)['pick']} "
                f"[{min(robust(nominal, common, n, f, m)['inside'])}-{max(robust(nominal, common, n, f, m)['inside'])}]"
                for f in (0.0,) + F_VALUES))
    with open(os.path.join(HERE, "robust_choice.csv"), "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["figure_of_merit", "N_counts_per_s_at_valley", "f", "set_level_mV", "set_gui_V",
                    "worst_time_penalty_over_pairings", "band5_all_lo_mV", "band5_all_hi_mV",
                    "opt_mV_D1L1_D1L2_D2L1_D2L2", "T_stat_to_10pct_min_s", "T_stat_to_10pct_max_s"])
        for case, m in CASES:
            for n in N_VALUES:
                for f in (0.0,) + F_VALUES:
                    r = robust(nominal, common, n, f, m)
                    ts = [time_to(r["best"][k]["var"], 0.1, 0.0) for k in r["best"]]
                    w.writerow([case, n, f, r["pick"], gui(r["pick"]), f"{r['worst']:.3f}", min(r["inside"]),
                                max(r["inside"]), " ".join(str(r["best"][k]["c"]["mv"]) for k in r["best"]),
                                f"{min(ts):.4g}", f"{max(ts):.4g}"])

    # ---- how much less does dark suppression matter? -----------------------------------------
    say("")
    say("HOW MUCH THE PHOTON BACKGROUND MOVES THINGS (equal-time off run, one level for all four)")
    for n in N_VALUES:
        r0, r5 = robust(nominal, common, n, 0.0, 2.0), robust(nominal, common, n, 0.5, 2.0)
        t0 = [time_to(r0["best"][k]["var"], 0.1, 0.0) for k in r0["best"]]
        t5 = [time_to(r5["best"][k]["var"], 0.1, 0.0) for k in r5["best"]]
        ratio = [b / a for a, b in zip(t0, t5)]
        pen = []
        for v in (4.4, 5.2, 6.8, 7.6):
            p0 = max(var_rel(by_mv(nominal[k])[v], n, 0.0, 2.0) / r0["best"][k]["var"] for k in r0["best"])
            p5 = max(var_rel(by_mv(nominal[k])[v], n, 0.5, 2.0) / r5["best"][k]["var"] for k in r5["best"])
            pen.append(f"{v}: x{p0:.2f}->x{p5:.2f}")
        say(f"  N={n:>5}: level f=0 {r0['pick']} -> f=0.5 {r5['pick']} mV; statistical time to 10 % x"
            f"{min(ratio):.2f}-{max(ratio):.2f}; worst-case time penalty of fixed levels f=0 -> f=0.5: " + ", ".join(pen))

    # ---- f at which photon-background noise equals the dark noise, at the best level --------------
    f_eq = {}
    fgrid = [10.0 ** (-5 + k / 30.0) for k in range(0, 211)]
    say("")
    say("F AT WHICH PHOTON-BACKGROUND COUNTS EQUAL THE DARK TERM (f eps N = m b) AT THE BEST LEVEL")
    for d, l in PAIRINGS:
        key = d + l
        for case, m in CASES:
            pts = []
            for n in N_HEAT:
                hit = None
                for f in fgrid:
                    c = stat_opt(nominal[key], n, f, m)["c"]
                    if f * c["eps"] * n >= m * c["b"]:
                        hit = f
                        break
                if hit is not None:
                    pts.append((n, hit))
            f_eq[(key, case)] = pts
            show = {round(n): x for n, x in pts if round(n) in (1, 10, 100, 1000, 10000)}
            say(f"  {key} {case}: " + ", ".join(f"N={k}: f={show[k]:.3g}" for k in sorted(show)))

    # ---- contrast: a photon background that the off run DOES see ---------------------------------
    say("")
    say("CONTRAST: photon background also in the off run, removed by on/off (equal time): best level = photon-free at N (1 + 2f), no systematic")
    for n in (10, 100):
        for f in (0.1, 0.5):
            a = stat_opt(nominal["D1L1"], n, f, 2.0)["c"]["mv"]
            b = stat_opt(nominal["D1L1"], n, f, 2.0, var=var_rel_subtractable)["c"]["mv"]
            c0 = stat_opt(nominal["D1L1"], n, 0.0, 2.0)["c"]["mv"]
            say(f"  D1L1 N={n}, f={f}: photon-free {c0} mV; inseparable (N(1+f)) {a} mV; subtractable (N(1+2f)) {b} mV")

    text = "\n".join(lines) + "\n"
    with open(os.path.join(HERE, "summary.txt"), "w", encoding="utf-8") as fh:
        fh.write(text)
    figures = {"fig_optimum_N_f.svg": fig_optimum_plane(nominal, common),
               "fig_total_time_vs_level.svg": fig_time_vs_level(nominal),
               "fig_flatness_fixed_time.svg": fig_flatness(nominal),
               "fig_f_equal_dark.svg": fig_f_equal_dark(f_eq)}
    for name, body in figures.items():
        with open(os.path.join(HERE, name), "w", encoding="utf-8") as fh:
            fh.write(body)
    print(text.encode("ascii", "replace").decode("ascii"))
    print("wrote results.csv, total_uncertainty.csv, operator_table.csv, robust_choice.csv, flatness_fixed_time.csv, summary.txt, "
          + ", ".join(figures))


if __name__ == "__main__":
    main()
