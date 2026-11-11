"""Best SR400 discriminator level for a weak signal of N photons/s, from the 2026-11-10 scans.

One command regenerates every output in this folder from the raw scan CSVs:

    python -I low_signal_optimum.py      (from this folder; standard library only)

Pure standard library plus the driver's own selftest.py (loaded by path, never modified).

DEFINITIONS (they are the whole answer, so they are stated once, here, and used everywhere)

  level v      |discriminator threshold| in mV. The SweepMe! GUI takes it as negative volts:
               6.8 mV is typed -0.0068.
  ref          the reference level of a light scan: the valley of its pulse-height density, as
               found by selftest.analyse_light (reference_v).
  b(v)         dark (background) rate at v, counts/s, from selftest._smooth_dark_rate: a local
               Poisson maximum-likelihood fit rate = exp(a + b x) over the dark thresholds within
               +-1 mV (widened until it holds 3 thresholds and 20 counts). Used instead of the
               single threshold's own rate because above 6 mV a single dark threshold holds only
               a few tens of counts (+-13-25 %), which would make the optimum jump between
               neighbouring levels on counting noise alone.
  eps(v)       photon detection fraction relative to the reference level:
               eps(v) = (R_light(v) - b(v)) / (R_light(ref) - b(ref)), from the room-light scan.
  N            signal rate in "counts at the valley": the rate of signal pulses that would be
               counted at the reference level. So the signal counted at v is s = eps(v) * N.
               Quantum efficiency, collection efficiency and photoelectron pulses below the
               valley are outside this definition and outside this analysis.

FIGURES OF MERIT, per sqrt(second) of counting time
  known_background       F1 = s / sqrt(s + b)    background known precisely from a separate,
                                                 much longer dark measurement.
  equal_time_background  F2 = s / sqrt(s + 2 b)  signal-on and signal-off runs of equal length T.
  Time to 10 % relative precision on N: T = 1 / (0.1 F)^2. For equal_time_background T is the
  length of EACH run (signal-on and signal-off), so the clock time is 2 T.

ASSUMPTIONS (also in README.md)
  * The electronic-noise and dark rates with the signal present equal those of the dark scan.
  * eps(v) measured with room light (single photoelectrons at ~3.8e5 counts/s) is the eps of the
    real signal: the real signal must also be single-photon pulses with the same pulse-height
    distribution (same HV, same cabling, same tube).
  * Candidate levels are the light scan's measured levels, above the noise hump (where the rate
    stops rising with level), no higher than the dark scan's highest level (no extrapolation of
    the dark fit) and where the dark fit is defined. Below 6 mV they are 0.2 mV apart, above
    6 mV 0.4 mV apart, so the optimum is resolved to 0.4 mV there.
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
# The first pair is referenced in place in docs/; the second pair was copied byte for byte into
# data/ (originals: the lab PC's results folder, sent as the zips darkscanagain_ and redarkscanagain_).
DARKS = {
    "D1": ("dark 13:20", os.path.join(ROOT, "docs", "real_data", "2026-11-10",
                                      "SR400_threshold_scan_dark_2026-11-10_132008.csv")),
    "D2": ("dark 16:36", os.path.join(HERE, "data", "SR400_threshold_scan_dark_2026-11-10_163608.csv")),
}
LIGHTS = {
    "L1": ("light 13:59", os.path.join(ROOT, "docs", "real_data", "2026-11-10",
                                       "SR400_threshold_scan_light_2026-11-10_135935.csv")),
    "L2": ("light 17:24", os.path.join(HERE, "data", "SR400_threshold_scan_light_2026-11-10_172444.csv")),
}
PAIRINGS = (("D1", "L1"), ("D1", "L2"), ("D2", "L1"), ("D2", "L2"))
PAIR_COLORS = {"D1L1": "#1f77b4", "D1L2": "#17becf", "D2L1": "#d62728", "D2L2": "#ff7f0e"}

N_VALUES = (1, 2, 5, 10, 20, 50, 100, 200, 500, 1000, 10000)
N_CURVE = [10.0 ** (k / 20.0) for k in range(-20, 101)]     # 0.1 .. 1e5, for the figures
FIXED_MV = (4.4, 5.2, 6.0, 6.8, 7.6, 9.2)  # 9.2, not 9.0: 9.0 mV was not measured in either light scan
CASES = (("known_background", 1.0), ("equal_time_background", 2.0))
BAND = 0.95          # "within 5 %" of the best figure of merit (= within 10.8 % of the shortest time)
PRECISION = 0.10     # relative precision on N for the time figures
DRAWS = 400          # Poisson resamples of every raw count
SEED = 20261110
DEAD_TIME_S = 5e-9   # SR400 pulse-pair resolution, manual p. 5 (as quoted in selftest.py)
PICKUP_SAFE_MV = st.PICKUP_SAFE_V * 1e3
SINGLE_SETTING_RANGES = ((1, 10), (1, 100), (1, 1000), (1, 10000), (100, 10000))
# Lowest candidate level. HEADLINE: the light scan's valley (reference). Measured here: below the
# valley the light-on rate exceeds photons + dark noise (light - dark = 1.44x the valley rate at
# 2.2 mV, where real sub-valley photoelectrons cannot plausibly be 44 %), so eps > 1 there includes
# light-induced extra counts that a weak signal may not produce in the same proportion; and across
# the steep 2.2-3.6 mV roll-off the +-1 mV exponential dark fit misses the raw dark rate by up to
# ~2x. Counting below the valley is also outside the definition of N. "hump" (every level above
# the rate maximum) is run as a sensitivity check only.
FLOORS = ("valley", "hump")
# b(v) estimators: "fit" = selftest._smooth_dark_rate everywhere (HEADLINE); "hybrid" = the
# threshold's own raw rate where it holds >= HYBRID_MIN_COUNTS counts (<= 5 % Poisson), the fit
# elsewhere. Sensitivity check on the fit's bias where the dark curve is steep and curved.
# "fit_x0.9" / "fit_x1.1": the fit scaled by 0.9 / 1.1 at every level. Measured here: between 3.8
# and 6.0 mV the fit sits 4-20 % ABOVE the raw thresholds (which hold < 400 counts there, so the
# hybrid does not touch them); +-10 % brackets that bias.
B_MODES = ("fit", "hybrid", "fit_x0.9", "fit_x1.1")
HYBRID_MIN_COUNTS = 400


def mv(v):
    return round(v * 1e3, 1)


def gui(v_mv):
    return st._gui_volts(v_mv * 1e-3)


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


def resample_points(points, rng):
    return [dict(p, counts=poisson(p["counts"], rng)) for p in points]


def resample_passes(passes, rng):
    return [dict(ps, points=resample_points(ps["points"], rng)) for ps in passes]


# ----------------------------------------------------------------------------- core analysis
def dark_fits(dark_rows, levels):
    """b(v) fit for each level, None where the driver's fit refuses or v is beyond the scan."""
    top = max(r["abs_v"] for r in dark_rows)
    out = {}
    for v in levels:
        out[v] = st._smooth_dark_rate(dark_rows, v) if v <= top + 1e-9 else None
    return out


def b_at(dark_rows, v, fits, b_mode):
    """(rate, relative sigma, counts) of the background at v under the chosen estimator."""
    fit = fits.get(v) if v in fits else st._smooth_dark_rate(dark_rows, v)
    if fit is None or b_mode == "fit":
        return fit
    if b_mode.startswith("fit_x"):
        return fit[0] * float(b_mode[5:]), fit[1], fit[2]
    raw = st._value_at(dark_rows, v)
    if abs(raw["abs_v"] - v) < 1e-9 and raw["counts"] >= HYBRID_MIN_COUNTS:
        return raw["rate"], 1.0 / math.sqrt(raw["counts"]), raw["counts"]
    return fit


def candidates(dark_rows, light_rows, ref_v, fits=None, floor="valley", b_mode="fit"):
    """Per-level eps and b for one pairing, restricted to levels where both are defensible."""
    if fits is None:
        fits = dark_fits(dark_rows, [r["abs_v"] for r in light_rows] + [ref_v])
    # The noise hump: below the rate maximum the rate RISES with level, so neither a dark rate
    # nor a light-minus-dark difference there is a property of a threshold.
    hump = max(max(dark_rows, key=lambda r: r["rate"])["abs_v"],
               max(light_rows, key=lambda r: r["rate"])["abs_v"])
    ref_row = st._value_at(light_rows, ref_v)
    assert abs(ref_row["abs_v"] - ref_v) < 1e-9, "reference level missing from light scan"
    ref_b = b_at(dark_rows, ref_v, fits, b_mode)
    denom = ref_row["rate"] - ref_b[0]
    out = []
    for r in light_rows:
        v = r["abs_v"]
        if v <= hump + 1e-9 or (floor == "valley" and v < ref_v - 1e-9):
            continue
        fit = b_at(dark_rows, v, fits, b_mode) if fits.get(v) is not None else None
        if fit is None:
            continue
        b, b_rel, b_counts = fit
        eps = (r["rate"] - b) / denom
        if eps <= 0 or b <= 0:
            continue
        out.append({"v": v, "mv": mv(v), "eps": eps, "b": b, "b_rel": b_rel,
                    "b_window_counts": b_counts, "light_rate": r["rate"], "light_counts": r["counts"]})
    return out


def fom(c, n, m):
    s = c["eps"] * n
    return s / math.sqrt(s + m * c["b"])


def t10(c, n, m):
    return 1.0 / (PRECISION * fom(c, n, m)) ** 2


def optimum(cands, n, m):
    vals = [fom(c, n, m) for c in cands]
    i = max(range(len(vals)), key=lambda k: vals[k])
    inside = [k for k, f in enumerate(vals) if f >= BAND * vals[i]]
    return {"c": cands[i], "fom": vals[i], "t10": 1.0 / (PRECISION * vals[i]) ** 2,
            "band_lo": cands[min(inside)]["mv"], "band_hi": cands[max(inside)]["mv"],
            "contiguous": len(inside) == max(inside) - min(inside) + 1,
            # At the lowest allowed level the true optimum may lie lower: the data cannot say.
            "at_floor": i == 0, "band_lo_at_floor": min(inside) == 0}


def optimum_n0(cands):
    """N -> 0: maximise eps / sqrt(b), the driver's background-limited S/sqrt(B)."""
    return max(cands, key=lambda c: c["eps"] / math.sqrt(c["b"]))


def by_mv(cands):
    return {c["mv"]: c for c in cands}


def common_levels(nominal):
    return sorted(set.intersection(*(set(by_mv(nominal[d + l]["cands"])) for d, l in PAIRINGS)))


def robust(nominal, common, n, m):
    """One level for all four pairings: the one whose worst time penalty over pairings is least,
    and the levels within 5 % of the best figure of merit in every pairing at once."""
    best = {d + l: optimum(nominal[d + l]["cands"], n, m) for d, l in PAIRINGS}
    looks = {k: by_mv(nominal[k]["cands"]) for k in best}

    def worst(v):
        return max(t10(looks[k][v], n, m) / best[k]["t10"] for k in best)

    pick = min(common, key=worst)
    inside_all = [v for v in common if all(fom(looks[k][v], n, m) >= BAND * best[k]["fom"] for k in best)]
    return {"pick": pick, "worst": worst(pick), "inside_all": inside_all, "best": best,
            "times": [t10(looks[k][pick], n, m) for k in best]}


def quantile(sorted_vals, q):
    return sorted_vals[int(round(q * (len(sorted_vals) - 1)))]


# ----------------------------------------------------------------------------- verification
def crossing(cands, target):
    """Level (mV) where eps first falls through target, linearly interpolated."""
    for a, b in zip(cands, cands[1:]):
        if a["eps"] >= target > b["eps"]:
            return a["mv"] + (b["mv"] - a["mv"]) * (a["eps"] - target) / (a["eps"] - b["eps"])
    return None


def log_crossing(rows, target):
    """Level (mV) where a dark rate first falls through target cps, past the hump; log interp."""
    peak = max(range(len(rows)), key=lambda i: rows[i]["rate"])
    for a, b in zip(rows[peak:], rows[peak + 1:]):
        if a["rate"] >= target > b["rate"] > 0:
            t = (math.log(a["rate"]) - math.log(target)) / (math.log(a["rate"]) - math.log(b["rate"]))
            return (a["abs_v"] + (b["abs_v"] - a["abs_v"]) * t) * 1e3
    return None


# ----------------------------------------------------------------------------- SVG helpers
class Panel(st._Panel):
    """selftest's _Panel with an optional log x axis and minor log ticks."""

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
        return {-3: "0.001", -2: "0.01", -1: "0.1", 0: "1", 1: "10", 2: "100", 3: "1000"}.get(k, f"1e{k}")

    def frame(self, title, xlabel, ylabel, xticks=None):
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
                s.text(self.x - 6, Y + 4, st._fmt(tick), 10, "end")
        s.rect(self.x, self.y, self.w, self.h, stroke="#222")
        s.text(self.x, self.y - 8, title, 13, weight="bold")
        s.text(self.x + self.w / 2, self.y + self.h + 34, xlabel, 11, "middle")
        s.text(self.x - 48, self.y + self.h / 2, ylabel, 11, "middle", rotate=-90)

    def polygon(self, pts, color, opacity):
        coords = " ".join(f"{self.px(x):.1f},{self.py(y):.1f}" for x, y in pts)
        self.svg.parts.append(f'<polygon points="{coords}" fill="{color}" fill-opacity="{opacity}" '
                              f'stroke="none" clip-path="url(#{self.clip})"/>')


PROVENANCE = ("eps(v) from room-light scans (light 13:59, light 17:24); b(v) from the 2026-11-10 "
              "dark scans (dark 13:20, dark 16:36). R8486 at ~1000 V (operator; HV not in the files).")


def footer(svg, y, lines):
    return st._text_block(svg, 30, y, 175, lines, size=11)


# ----------------------------------------------------------------------------- figures
def fig_inputs(data, nominal):
    svg = st._Svg(1200, 560)
    svg.text(30, 26, "Measured inputs: photon detection fraction eps(v) and dark rate b(v), 2026-11-10",
             15, weight="bold")
    # Panel A: eps
    pa = Panel(svg, 90, 70, 470, 330, (0, 18.5), (0, 1.3))
    pa.frame("A. eps(v) = (light - dark) / same at the valley",
             "discriminator level |v| (mV)", "eps (fraction of valley-level counts)")
    pa.band(0, min(l["ref_v"] for l in data["lights"].values()) * 1e3, st._C["noise"], "", opacity=0.30)
    svg.text(pa.px(2.0), pa.py(0.12), "excluded from", 10, "middle", color="#555", italic=True)
    svg.text(pa.px(2.0), pa.py(0.06), "the headline", 10, "middle", color="#555", italic=True)
    pa.vline(PICKUP_SAFE_MV, st._C["pickup"], "10 mV: below, pickup-sensitive", slot=0)
    for (dk, lk), color in (("D1", "L1"), "#1f77b4"), (("D1", "L2"), "#d62728"):
        cands = nominal[dk + lk]["variants"][("hump", "fit")]
        xs = [c["mv"] for c in cands]
        pa.series(xs, [c["eps"] for c in cands], color, marker="o",
                  label=f"{LIGHTS[lk][0]} minus {DARKS[dk][0]}, measured", width=1.2)
        ref = data["lights"][lk]["ref_v"] * 1e3
        X = pa.px(ref)
        svg.line(X, pa.y, X, pa.y + pa.h, color, 1.2, dash="2,3")
        svg.text(X - 4, pa.py(0.56 if lk == "L1" else 0.50), f"valley {ref:.1f} mV", 10, "end", color=color)
    pa.legend()
    # Panel B: dark rate
    pb = Panel(svg, 670, 70, 500, 330, (0, 37), (0.01, 1e6), log_y=True)
    pb.frame("B. dark rate: raw thresholds and the smoothed b(v)",
             "discriminator level |v| (mV)", "dark rate (counts/s)")
    pb.band(0, 1.2, st._C["noise"], "noise hump", opacity=0.35)
    pb.vline(PICKUP_SAFE_MV, st._C["pickup"], "10 mV", slot=0)
    for dk, color in (("D1", "#1f77b4"), ("D2", "#d62728")):
        rows = data["darks"][dk]["rows"]
        hit = [r for r in rows if r["counts"] > 0]
        pb.series([r["abs_v"] * 1e3 for r in hit], [r["rate"] for r in hit], color, marker="o",
                  line=False, label=f"{DARKS[dk][0]}: counts/live time, measured")
        pb.errorbars([r["abs_v"] * 1e3 for r in hit], [r["rate"] for r in hit],
                     [r["sigma"] for r in hit], color)
        zero = [r for r in rows if r["counts"] == 0]
        pb.series([r["abs_v"] * 1e3 for r in zero], [r["upper95"] for r in zero], color, marker="v",
                  line=False, filled=False)
        cands = nominal[dk + "L1"]["variants"][("hump", "fit")]
        pb.series([c["mv"] for c in cands], [c["b"] for c in cands], color, width=2.0,
                  label=f"{DARKS[dk][0]}: b(v), local Poisson fit (+-1 mV)")
    pb.legend()
    footer(svg, 450, [
        PROVENANCE,
        f"A: eps is plotted with the 13:20 dark subtracted; with the 16:36 dark it differs by at most "
        f"{data['eps_dark_diff']:.3%} at any headline candidate level (valley and above). Poisson error "
        f"on eps is ~0.5 % per level, smaller than the markers. B: error bars are Poisson; open "
        f"triangles are thresholds with zero counts, plotted at the 95 % upper limit 3/T.",
        f"Grey, panel A: below the valley eps reaches {data['eps_below_max']:.2f}: the light-on rate there "
        f"is more than photons + dark noise, and the dark fit (panel B) misses the raw dark rate by up to "
        f"x{data['fit_raw_max']:.1f} on the steep 2.2-3.6 mV roll-off. Levels below the valley are "
        f"therefore left out of the headline answer (sensitivity check only).",
        "The 16:36 dark scan is coarse above 7.2 mV (7.2, 9.2, 11.2 ... mV), so its b(v) between "
        "those points is a fit across a +-2 mV window, not a local measurement. "
        "Light-scan counts are summed over 3 up and 3 down passes at each level.",
    ])
    return svg.render()


def fig_optimum_vs_n(nominal, boot):
    svg = st._Svg(1200, 1090)
    svg.text(30, 26, "Best discriminator level against signal rate N, with the 5 % tolerance band",
             15, weight="bold")
    tops = {"equal_time_background": 70, "known_background": 545}
    titles = {"equal_time_background":
              "A. Background measured in equal time (signal-on and signal-off runs of equal length)",
              "known_background": "B. Background known precisely (from a separate long dark run)"}
    common = common_levels(nominal)
    for case, m in CASES:
        p = Panel(svg, 90, tops[case], 960, 300, (0.1, 1e5), (3.4, 8.2), log_x=True)
        p.frame(titles[case], "N: signal rate in counts/s at the valley level (log scale)",
                "best level |v| (mV)")
        rob = [robust(nominal, common, n, m) for n in N_CURVE]
        # Shaded: within 5 % of the best figure of merit in ALL four pairings at once, drawn as
        # +-0.1 mV around the measured levels so a single-level band is still visible.
        # Where no level is within 5 % in all four pairings, nothing is shaded.
        runs, run = [], []
        for n, r in zip(N_CURVE, rob):
            if r["inside_all"]:
                run.append((n, min(r["inside_all"]) - 0.1, max(r["inside_all"]) + 0.1))
            elif run:
                runs.append(run)
                run = []
        if run:
            runs.append(run)
        for run in runs:
            p.polygon([(n, hi) for n, _, hi in run] + [(n, lo) for n, lo, _ in run[::-1]], "#888888", 0.22)
        empty = [n for n, r in zip(N_CURVE, rob) if not r["inside_all"]]
        p.legend_items.append(("within 5 % in all four pairings", "#bbbbbb", None, None, True, True))
        p.series(N_CURVE, [r["pick"] for r in rob], "#111111", width=2.4, dash="7,4",
                 label="one level for all four (least worst-case time)")
        for k, (dk, lk) in enumerate(PAIRINGS):
            key, color = dk + lk, PAIR_COLORS[dk + lk]
            opts = [optimum(nominal[key]["cands"], n, m) for n in N_CURVE]
            p.series(N_CURVE, [o["c"]["mv"] for o in opts], color, width=1.3,
                     label=f"best level, {DARKS[dk][0]} + {LIGHTS[lk][0]}")
            shift = 10 ** (0.035 * (k - 1.5))
            xs = [n * shift for n in N_VALUES]
            ys = [optimum(nominal[key]["cands"], n, m)["c"]["mv"] for n in N_VALUES]
            for x, n in zip(xs, N_VALUES):
                b = boot[(key, n, case)]
                p.svg.line(p.px(x), p.py(b["p16"]), p.px(x), p.py(b["p84"]), color, 1.4, clip=p.clip)
            p.series(xs, ys, color, marker="o", line=False)
        p.hline(4.0, "#8e44ad", "", dash="2,3")
        p.hline(3.8, "#8e44ad", "", dash="2,3")
        svg.text(p.x + 6, p.py(4.0) - 4, "valleys 4.0 mV (light 13:59), 3.8 mV (light 17:24): the lowest "
                 "level allowed", 10, color="#8e44ad")
        # GUI values on the right-hand axis
        for t in range(4, 9):
            Y = p.py(t)
            svg.line(p.x + p.w, Y, p.x + p.w + 4, Y, "#222", 1)
            svg.text(p.x + p.w + 7, Y + 4, f"{-t / 1000:.4f}", 10)
        svg.text(p.x + p.w + 62, p.y + p.h / 2, "GUI value (V)", 11, "middle", rotate=90)
        p.legend()
        at_floor = [n for n in N_CURVE if any(optimum(nominal[d + l]["cands"], n, m)["at_floor"]
                                               for d, l in PAIRINGS)]
        lo_floor = [n for n in N_CURVE if any(optimum(nominal[d + l]["cands"], n, m)["band_lo_at_floor"]
                                               for d, l in PAIRINGS)]
        caption = ["Dots: the requested N (offset sideways per pairing); bars: 16-84 % range of the best "
                   f"level over {DRAWS} Poisson resamples of every raw count."]
        if empty:
            where = (f"N <= {empty[-1]:.2g}" if empty[0] == N_CURVE[0]
                     else f"N from {empty[0]:.3g} to {empty[-1]:.3g}")
            caption.append(f"No level is within 5 % in all four pairings for {where} counts/s (unshaded): "
                           f"there the two dark scans disagree more than the band is wide.")
        if lo_floor:
            caption.append(f"In at least one pairing the 5 % band reaches the valley from N ~ {lo_floor[0]:.0f}"
                           + (f", and the best level from N ~ {at_floor[0]:.0f}" if at_floor else "")
                           + " counts/s (grid of 20 N values per decade): beyond that the true lower edge or "
                             "optimum may lie below the valley, which this analysis does not trust (see fig_inputs).")
        st._text_block(svg, p.x, p.y + p.h + 56, 160, caption, size=11)
    footer(svg, 1010, [
        PROVENANCE,
        "N is the signal rate that would be counted at the valley level; quantum efficiency and pulses "
        "below the valley are not included. Every level shown is below 10 mV: valid only with the "
        "cables routed as during these scans (manual p. 22, DISC-output pickup).",
        "Levels resolved to the scanned grid: 0.2 mV steps below 6 mV, 0.4 mV above. Within 5 % of "
        "the best figure of merit = within 10.8 % of the shortest counting time.",
    ])
    return svg.render()


def fig_time_vs_level(nominal):
    svg = st._Svg(1200, 860)
    svg.text(30, 26, "Counting time to measure N to 10 % against discriminator level "
             "(background measured in equal time)", 15, weight="bold")
    n_show = (1, 10, 100, 1000, 10000)
    colors = ("#1f77b4", "#2ca02c", "#ff7f0e", "#d62728", "#9467bd")
    m = 2.0
    for k, (dk, lk) in enumerate(PAIRINGS):
        key = dk + lk
        cands = [c for c in nominal[key]["cands"] if 3.0 <= c["mv"] <= 15.2]
        x0, y0 = 90 + (k % 2) * 560, 70 + (k // 2) * 340
        p = Panel(svg, x0, y0, 480, 260, (3.0, 15.4), (1e-3, 1e8), log_y=True)
        p.frame(f"{'ABCD'[k]}. {DARKS[dk][0]} + {LIGHTS[lk][0]}", "discriminator level |v| (mV)",
                "time per run T (s)")
        for v in FIXED_MV:
            Y = p.y + p.h
            svg.line(p.px(v), p.y, p.px(v), Y, "#bbbbbb", 1, dash="1,3")
        p.vline(PICKUP_SAFE_MV, st._C["pickup"], "10 mV", slot=0)
        for n, color in zip(n_show, colors):
            p.series([c["mv"] for c in cands], [t10(c, n, m) for c in cands], color, width=1.4,
                     label=f"N = {n} counts/s")
            o = optimum(nominal[key]["cands"], n, m)
            band = [c for c in cands if o["band_lo"] <= c["mv"] <= o["band_hi"]]
            p.series([c["mv"] for c in band], [t10(c, n, m) for c in band], color, width=5.0)
            p.series([o["c"]["mv"]], [o["t10"]], color, marker="o")
        p.legend()
    footer(svg, 760, [
        PROVENANCE,
        "T = (eps N + 2 b) / (0.1 eps N)^2 is the length of EACH of the signal-on and signal-off runs "
        "(clock time 2T). Thick segment: levels within 5 % of the best figure of merit; dot: best "
        "level. Dotted grey verticals: the fixed comparison levels 4.4, 5.2, 6.0, 6.8, 7.6, 9.2 mV.",
        "Curves join the measured levels (0.2 mV apart below 6 mV, 0.4 mV above); nothing is "
        "interpolated between them.",
    ])
    return svg.render()


def fig_cost(nominal):
    svg = st._Svg(1200, 860)
    svg.text(30, 26, "What a fixed level costs: counting time relative to the best level for each N "
             "(background measured in equal time)", 15, weight="bold")
    colors = ("#9467bd", "#1f77b4", "#2ca02c", "#ff7f0e", "#d62728", "#8c564b")
    m = 2.0
    ns = [n for n in N_CURVE if 1.0 <= n <= 1e4 * 1.0001]
    for k, (dk, lk) in enumerate(PAIRINGS):
        key = dk + lk
        cands = nominal[key]["cands"]
        lookup = by_mv(cands)
        x0, y0 = 90 + (k % 2) * 560, 70 + (k // 2) * 340
        p = Panel(svg, x0, y0, 480, 260, (1, 1e4), (1, 30), log_x=True, log_y=True)
        p.frame(f"{'ABCD'[k]}. {DARKS[dk][0]} + {LIGHTS[lk][0]}",
                "N: signal rate in counts/s at the valley level", "T(fixed level) / T(best level)")
        p.series([1, 1e4], [1 / BAND ** 2] * 2, "#555", width=1.0, dash="4,3",
                 label="x1.108: edge of the 5 % band")
        for v, color in zip(FIXED_MV, colors):
            c = lookup.get(v)
            if c is None:
                continue
            ys = [t10(c, n, m) / optimum(cands, n, m)["t10"] for n in ns]
            p.series(ns, ys, color, width=1.6, label=f"{v:.1f} mV (GUI {gui(v):.4f})")
        p.legend()
    footer(svg, 760, [
        PROVENANCE,
        "A ratio of 2 means the fixed level needs twice the counting time of the best level for the "
        "same 10 % precision on N. All levels shown are below 10 mV: pickup-sensitive.",
    ])
    return svg.render()


# ----------------------------------------------------------------------------- main
def main():
    rng = random.Random(SEED)
    data = {"darks": {}, "lights": {}}
    for k, (label, path) in DARKS.items():
        meta, points = st.read_scan_csv(path)
        assert meta.get("kind") == "dark", path
        res = st.analyse_dark(points)
        data["darks"][k] = {"meta": meta, "points": points, "result": res, "rows": res["rows"]}
    for k, (label, path) in LIGHTS.items():
        meta, passes = st.read_scan_csv(path)
        assert meta.get("kind") == "light", path
        res = st.analyse_light(passes, None)
        data["lights"][k] = {"meta": meta, "passes": passes, "result": res, "rows": res["rows"],
                             "ref_v": res["reference_v"]}

    nominal = {}
    for dk, lk in PAIRINGS:
        key = dk + lk
        drv = st.analyse_light(data["lights"][lk]["passes"], data["darks"][dk]["result"])
        cands = candidates(data["darks"][dk]["rows"], data["lights"][lk]["rows"], data["lights"][lk]["ref_v"])
        n0 = optimum_n0(cands)
        # Same argmax as the driver's S/sqrt(B): its eps differs only by a constant factor.
        assert abs(n0["v"] - drv["optimum_v"]) < 1e-9, (key, n0["v"], drv["optimum_v"])
        nominal[key] = {"cands": cands, "driver": drv, "n0": n0, "variants": {}}
        for floor in FLOORS:
            for b_mode in B_MODES:
                nominal[key]["variants"][(floor, b_mode)] = candidates(
                    data["darks"][dk]["rows"], data["lights"][lk]["rows"], data["lights"][lk]["ref_v"],
                    floor=floor, b_mode=b_mode)
        assert nominal[key]["variants"][("valley", "fit")] == cands

    # ---- Poisson resampling of every raw count ---------------------------------------------
    samples = {}
    for draw in range(DRAWS):
        drows = {k: st.analyse_dark(resample_points(d["points"], rng))["rows"] for k, d in data["darks"].items()}
        lrows = {k: st.analyse_light(resample_passes(l["passes"], rng), None)["rows"]
                 for k, l in data["lights"].items()}
        levels = sorted({r["abs_v"] for rows in lrows.values() for r in rows}
                        | {l["ref_v"] for l in data["lights"].values()})
        fits = {k: dark_fits(rows, levels) for k, rows in drows.items()}
        for dk, lk in PAIRINGS:
            cands = candidates(drows[dk], lrows[lk], data["lights"][lk]["ref_v"], fits[dk])
            for case, m in CASES:
                for n in N_VALUES:
                    o = optimum(cands, n, m)
                    samples.setdefault((dk + lk, n, case), []).append((o["c"]["mv"], o["t10"]))
            samples.setdefault((dk + lk, 0, "n0"), []).append((optimum_n0(cands)["mv"], None))
    boot = {}
    for key, vals in samples.items():
        levels = sorted(v for v, _ in vals)
        mode = max(set(levels), key=levels.count)
        times = sorted(t for _, t in vals if t is not None)
        boot[key] = {"median": quantile(levels, 0.5), "p16": quantile(levels, 0.16),
                     "p84": quantile(levels, 0.84), "mode": mode,
                     "mode_frac": levels.count(mode) / len(levels),
                     "t_p16": quantile(times, 0.16) if times else None,
                     "t_p84": quantile(times, 0.84) if times else None}

    # ---- results.csv ---------------------------------------------------------------------
    header = ["pairing", "dark_csv", "light_csv", "reference_mV", "N_counts_per_s_at_valley",
              "figure_of_merit", "opt_level_mV", "opt_gui_V", "band5pct_lo_mV", "band5pct_hi_mV",
              "band_contiguous", "eps_at_opt", "b_at_opt_cps", "b_rel_sigma_at_opt",
              "signal_counted_at_opt_cps", "fom_at_opt_per_sqrt_s", "T10_at_opt_s",
              "T10_at_opt_boot16_s", "T10_at_opt_boot84_s"]
    header += [f"T10_at_{v:.1f}mV_s" for v in FIXED_MV]
    header += ["boot_opt_median_mV", "boot_opt_p16_mV", "boot_opt_p84_mV", "boot_opt_mode_mV",
               "boot_mode_fraction", "opt_at_floor_valley", "band_lo_at_floor_valley",
               "pickup_sensitive_below_10mV"]
    out_rows = []
    for dk, lk in PAIRINGS:
        key = dk + lk
        cands = nominal[key]["cands"]
        lookup = by_mv(cands)
        for n in N_VALUES:
            for case, m in CASES:
                o = optimum(cands, n, m)
                c = o["c"]
                b = boot[(key, n, case)]
                row = [f"{DARKS[dk][0]} + {LIGHTS[lk][0]}", os.path.basename(DARKS[dk][1]),
                       os.path.basename(LIGHTS[lk][1]), mv(data["lights"][lk]["ref_v"]), n, case,
                       c["mv"], gui(c["mv"]), o["band_lo"], o["band_hi"], o["contiguous"],
                       f"{c['eps']:.4f}", f"{c['b']:.4g}", f"{c['b_rel']:.3f}", f"{c['eps'] * n:.4g}",
                       f"{o['fom']:.4g}", f"{o['t10']:.4g}", f"{b['t_p16']:.4g}", f"{b['t_p84']:.4g}"]
                row += [f"{t10(lookup[v], n, m):.4g}" if v in lookup else "" for v in FIXED_MV]
                row += [b["median"], b["p16"], b["p84"], b["mode"], f"{b['mode_frac']:.2f}",
                        o["at_floor"], o["band_lo_at_floor"],
                        "yes" if c["mv"] < PICKUP_SAFE_MV else "no"]
                out_rows.append(row)
    with open(os.path.join(HERE, "results.csv"), "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(header)
        w.writerows(out_rows)

    # ---- inputs.csv: the measured per-level quantities every result is built from -------------
    with open(os.path.join(HERE, "inputs.csv"), "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["pairing", "level_mV", "gui_V", "light_counts_summed_6_passes", "light_rate_cps",
                    "eps", "b_fit_cps", "b_fit_rel_sigma", "b_fit_window_counts",
                    "dark_raw_counts_at_level", "dark_raw_live_s_at_level", "below_valley_sensitivity_only"])
        for dk, lk in PAIRINGS:
            raw = {round(r["abs_v"], 5): r for r in data["darks"][dk]["rows"]}
            for c in nominal[dk + lk]["variants"][("hump", "fit")]:
                r = raw.get(round(c["v"], 5))
                w.writerow([f"{DARKS[dk][0]} + {LIGHTS[lk][0]}", c["mv"], gui(c["mv"]), c["light_counts"],
                            f"{c['light_rate']:.5g}", f"{c['eps']:.4f}", f"{c['b']:.4g}", f"{c['b_rel']:.3f}",
                            c["b_window_counts"], r["counts"] if r else "", r["live_s"] if r else "",
                            c["v"] < data["lights"][lk]["ref_v"] - 1e-9])

    # ---- one level robust across the four pairings -----------------------------------------
    common = common_levels(nominal)
    robust_rows = []
    for case, m in CASES:
        for n in N_VALUES:
            r = robust(nominal, common, n, m)
            inside_all = r["inside_all"]
            robust_rows.append([case, n, r["pick"], gui(r["pick"]), f"{r['worst']:.3f}",
                                min(inside_all) if inside_all else "", max(inside_all) if inside_all else "",
                                (len(inside_all) == common.index(max(inside_all)) - common.index(min(inside_all)) + 1)
                                if inside_all else "",
                                " ".join(f"{r['best'][k]['c']['mv']}" for k in r["best"]),
                                f"{min(r['times']):.4g}", f"{max(r['times']):.4g}"])
    with open(os.path.join(HERE, "robust_choice.csv"), "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["figure_of_merit", "N_counts_per_s_at_valley", "robust_level_mV", "robust_gui_V",
                    "worst_time_penalty_over_pairings", "band5pct_all_pairings_lo_mV",
                    "band5pct_all_pairings_hi_mV", "band_all_contiguous",
                    "opt_mV_D1L1_D1L2_D2L1_D2L2", "T10_at_robust_min_over_pairings_s",
                    "T10_at_robust_max_over_pairings_s"])
        w.writerows(robust_rows)

    single = []
    for case, m in CASES:
        for lo, hi in SINGLE_SETTING_RANGES:
            ns = [n for n in N_VALUES if lo <= n <= hi]
            def worst_all(v):
                return max(t10(by_mv(nominal[k]["cands"])[v], n, m)
                           / optimum(nominal[k]["cands"], n, m)["t10"]
                           for k in (d + l for d, l in PAIRINGS) for n in ns)
            pick = min(common, key=worst_all)
            single.append((case, lo, hi, pick, worst_all(pick)))

    # ---- verification of the stated facts ----------------------------------------------------
    lines = []
    say = lines.append
    say("LOW-SIGNAL DISCRIMINATOR OPTIMUM -- machine-written summary (do not edit; regenerate)")
    say(f"python {sys.version.split()[0]}, {DRAWS} Poisson resamples, seed {SEED}")
    say("")
    say("INPUT FILES")
    for k, (label, path) in list(DARKS.items()) + list(LIGHTS.items()):
        meta = (data["darks"].get(k) or data["lights"].get(k))["meta"]
        say(f"  {k} {label}: {os.path.relpath(path, ROOT)}  (when {meta.get('when')}, "
            f"hv_V field: {meta.get('hv_V', 'absent')!r})")
    say("")
    say("VERIFIED FACTS")
    for k, d in data["darks"].items():
        rows = d["rows"]
        r = d["result"]
        peak = max(rows, key=lambda x: x["rate"])
        mid = [x["counts"] for x in rows if 6.0 < x["abs_v"] * 1e3 <= 10.0 + 1e-6]
        say(f"  {k} {DARKS[k][0]}: {len(rows)} thresholds {mv(rows[0]['abs_v'])}-{mv(rows[-1]['abs_v'])} mV, "
            f"total live {sum(x['live_s'] for x in rows):.0f} s; noise hump peak {peak['rate']:.4g} cps at "
            f"{mv(peak['abs_v'])} mV; dark rate falls through 1000 cps at {log_crossing(rows, 1000):.2f} mV, "
            f"100 cps at {log_crossing(rows, 100):.2f} mV, 10 cps at {log_crossing(rows, 10):.2f} mV; "
            f"driver noise edge {mv(r['noise_edge_v'])} mV; counts per threshold for 6 < v <= 10 mV: "
            f"{min(mid)}-{max(mid)} ({len(mid)} thresholds)")
    shared = sorted(set(round(x["abs_v"], 5) for x in data["darks"]["D1"]["rows"])
                    & set(round(x["abs_v"], 5) for x in data["darks"]["D2"]["rows"]))
    for lo_mv, hi_mv in ((6.0, 7.3), (6.0, 18.1), (8.0, 18.1)):
        sel = [v for v in shared if lo_mv < v * 1e3 <= hi_mv]
        pooled = {}
        for k in ("D1", "D2"):
            rows = {round(x["abs_v"], 5): x for x in data["darks"][k]["rows"]}
            pooled[k] = (sum(rows[v]["counts"] for v in sel), sum(rows[v]["live_s"] for v in sel))
        r1, r2 = pooled["D1"][0] / pooled["D1"][1], pooled["D2"][0] / pooled["D2"][1]
        say(f"  dark tail, thresholds common to both scans in ({lo_mv}, {hi_mv}] mV "
            f"[{', '.join(str(mv(v)) for v in sel)}]: D1 {pooled['D1'][0]} counts, D2 {pooled['D2'][0]} counts "
            f"in equal live time; D2/D1 = {r2 / r1:.2f} +- {r2 / r1 * math.sqrt(1 / pooled['D1'][0] + 1 / pooled['D2'][0]):.2f}")
    for k, l in data["lights"].items():
        r = l["result"]
        cands = nominal["D1" + k]["cands"]
        at6 = by_mv(cands).get(6.0)
        say(f"  {k} {LIGHTS[k][0]}: valley (reference) {mv(r['reference_v'])} mV, light rate there "
            f"{r['plateau_rate']:.4g} cps, at 6.0 mV {at6['light_rate']:.4g} cps; driver drift "
            f"{r['drift']:.2%} (flagged: {r['drift_flagged']}); counts per level "
            f"{min(x['counts'] for x in l['rows'])}-{max(x['counts'] for x in l['rows'])}; eps falls through "
            f"0.75 / 0.5 / 0.25 at {crossing(cands, 0.75):.2f} / {crossing(cands, 0.5):.2f} / "
            f"{crossing(cands, 0.25):.2f} mV (D1 dark)")
        say(f"     dead-time bias at 5 ns: loss {r['plateau_rate'] * DEAD_TIME_S:.2%} at the valley, "
            f"{at6['light_rate'] * DEAD_TIME_S:.2%} at 6.0 mV, so eps(6.0 mV) is biased by "
            f"{(r['plateau_rate'] - at6['light_rate']) * DEAD_TIME_S:+.2%} (relative)")
    g = [crossing(nominal["D1" + k]["cands"], 0.5) for k in ("L1", "L2")]
    g25 = [crossing(nominal["D1" + k]["cands"], 0.25) for k in ("L1", "L2")]
    say(f"  gain proxy: eps = 0.5 at {g[0]:.2f} (L1) vs {g[1]:.2f} mV (L2): ratio L1/L2 {g[0] / g[1]:.3f}; "
        f"eps = 0.25 at {g25[0]:.2f} vs {g25[1]:.2f} mV: ratio {g25[0] / g25[1]:.3f}")
    data["eps_dark_diff"] = max(
        abs(a["eps"] / b["eps"] - 1) for lk in ("L1", "L2")
        for a, b in zip(nominal["D1" + lk]["cands"], nominal["D2" + lk]["cands"]) if a["mv"] == b["mv"])
    say(f"  eps with D1 vs D2 subtracted, max relative difference over headline candidate levels: "
        f"{data['eps_dark_diff']:.3%}")
    for k, l in data["lights"].items():
        hump = nominal["D1" + k]["variants"][("hump", "fit")]
        below = [c for c in hump if c["v"] < l["ref_v"] - 1e-9]
        data["eps_below_max"] = max([data.get("eps_below_max", 0.0)] + [c["eps"] for c in below])
        say(f"  {k} below the valley: eps = " + ", ".join(f"{c['mv']}:{c['eps']:.3f}" for c in below)
            + f"; light rate maximum {max(l['rows'], key=lambda r: r['rate'])['rate']:.4g} cps at "
            f"{mv(max(l['rows'], key=lambda r: r['rate'])['abs_v'])} mV")
    for k, d in data["darks"].items():
        parts, low, steep = [], [], []
        for r in d["rows"]:
            if 2.2 - 1e-6 <= r["abs_v"] * 1e3 <= 6.0 + 1e-6:
                f = st._smooth_dark_rate(d["rows"], r["abs_v"])
                parts.append(f"{mv(r['abs_v'])}:{f[0] / r['rate']:.2f}")
                low.append(r["counts"])
                if r["abs_v"] * 1e3 <= 3.6 + 1e-6:
                    steep.append(r["counts"])
                    ratio = max(f[0] / r["rate"], r["rate"] / f[0])
                    data["fit_raw_max"] = max(data.get("fit_raw_max", 1.0), ratio)
        say(f"  {k} fitted/raw dark rate, 2.2-6.0 mV (raw counts per level {min(low)}-{max(low)}; "
            f"2.2-3.6 mV {min(steep)}-{max(steep)}): " + " ".join(parts))
    say("")
    say("CANDIDATE LEVELS per pairing")
    for dk, lk in PAIRINGS:
        c = nominal[dk + lk]["cands"]
        say(f"  {dk}{lk}: {len(c)} levels, {c[0]['mv']}-{c[-1]['mv']} mV")
    say("")
    say("N -> 0 LIMIT (maximise eps/sqrt(b), the driver's S/sqrt(B)); asserted equal to analyse_light's optimum_v")
    for dk, lk in PAIRINGS:
        key = dk + lk
        drv = nominal[key]["driver"]
        b = boot[(key, 0, "n0")]
        say(f"  {key}: {nominal[key]['n0']['mv']} mV (driver {mv(drv['optimum_v'])} mV, band "
            f"{mv(drv['optimum_band_v'][0])}-{mv(drv['optimum_band_v'][1])} mV); resampled median {b['median']}, "
            f"16-84 % {b['p16']}-{b['p84']} mV, mode {b['mode']} in {b['mode_frac']:.0%}")
    for case, m in CASES:
        say("")
        say(f"OPTIMUM BY PAIRING -- {case}  (level mV [5 % band] | resampled 16-84 % | T10 at optimum s)")
        for n in N_VALUES:
            parts = []
            for dk, lk in PAIRINGS:
                key = dk + lk
                o = optimum(nominal[key]["cands"], n, m)
                b = boot[(key, n, case)]
                parts.append(f"{key} {o['c']['mv']}{'<' if o['at_floor'] else ''} "
                             f"[{'<' if o['band_lo_at_floor'] else ''}{o['band_lo']}-{o['band_hi']}"
                             f"{'' if o['contiguous'] else '*'}] |{b['p16']}-{b['p84']}| {o['t10']:.3g}")
            say(f"  N={n:>5}: " + ";  ".join(parts))
        say("  (* = band not contiguous on the measured grid; < = at the floor, the valley: the true "
            "optimum or band edge may lie lower)")
        say("")
        say(f"ROBUST LEVEL ACROSS THE FOUR PAIRINGS -- {case}")
        for r in (x for x in robust_rows if x[0] == case):
            say(f"  N={r[1]:>5}: {r[2]} mV (GUI {r[3]}), worst penalty x{r[4]}; within 5 % in all four: "
                f"{r[5]}-{r[6]} mV (contiguous {r[7]}); optima {r[8]}; T10 there {r[9]}-{r[10]} s")
        empty = [n for n in N_CURVE if not robust(nominal, common, n, m)["inside_all"]]
        say("  on the dense N grid 0.1-1e5: no level within 5 % in all four pairings at N = "
            + (", ".join(f"{n:.3g}" for n in empty) if empty else "none"))
        below = [n for n in N_CURVE if n < 1]
        say("  N -> 0 side (N < 1): robust level " + ", ".join(
            f"{n:.2g}:{robust(nominal, common, n, m)['pick']}" for n in below[::4]))
        say("")
        say(f"FIXED LEVELS: T10 (s) per pairing -- {case}")
        for n in N_VALUES:
            parts = []
            for v in FIXED_MV:
                ts = [t10(by_mv(nominal[d + l]["cands"])[v], n, m) for d, l in PAIRINGS]
                pen = [t10(by_mv(nominal[d + l]["cands"])[v], n, m) / optimum(nominal[d + l]["cands"], n, m)["t10"]
                       for d, l in PAIRINGS]
                parts.append(f"{v}: {min(ts):.3g}-{max(ts):.3g} (x{min(pen):.2f}-{max(pen):.2f})")
            say(f"  N={n:>5}: " + "; ".join(parts))
        say("")
        say(f"ONE SETTING FOR A RANGE OF N -- {case} (minimise the worst time penalty over N and pairings)")
        for c, lo, hi, pick, pen in single:
            if c == case:
                say(f"  N {lo}-{hi}: {pick} mV (GUI {gui(pick)}), worst penalty x{pen:.3f}")
    say("")
    say("SENSITIVITY: candidate floor x background estimator (nominal data; level mV per pairing "
        "D1L1 D1L2 D2L1 D2L2, '<' = at the floor)")
    sens_rows = []
    for case, m in CASES:
        say(f"  {case}")
        for n in N_VALUES:
            parts = []
            for floor in FLOORS:
                for b_mode in B_MODES:
                    picks = []
                    for d, l in PAIRINGS:
                        cands = nominal[d + l]["variants"][(floor, b_mode)]
                        o = optimum(cands, n, m)
                        # Cost of the headline choice if this variant were the truth.
                        head = optimum(nominal[d + l]["cands"], n, m)["c"]["mv"]
                        hc = by_mv(cands).get(head)
                        pen = t10(hc, n, m) / o["t10"] if hc else float("nan")
                        sens_rows.append([d + l, case, n, floor, b_mode, o["c"]["mv"], o["band_lo"],
                                          o["band_hi"], o["at_floor"], f"{o['t10']:.4g}", head, f"{pen:.3f}"])
                        picks.append(f"{o['c']['mv']}{'<' if o['at_floor'] else ''}")
                    parts.append(f"{floor}/{b_mode}: {' '.join(picks)}")
            say(f"    N={n:>5}: " + " | ".join(parts))
    worst = {}
    for r in sens_rows:
        if r[11] != "nan":
            key = (r[1], r[3], r[4])
            worst[key] = max(worst.get(key, 0.0), float(r[11]))
    say("  worst time penalty of the headline optimum if a variant were the truth (over N and pairings):")
    for (case, floor, b_mode), pen in sorted(worst.items()):
        say(f"    {case} {floor}/{b_mode}: x{pen:.3f}")
    with open(os.path.join(HERE, "sensitivity.csv"), "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["pairing", "figure_of_merit", "N_counts_per_s_at_valley", "floor", "b_estimator",
                    "opt_level_mV", "band5pct_lo_mV", "band5pct_hi_mV", "opt_at_floor", "T10_at_opt_s",
                    "headline_opt_mV", "time_penalty_of_headline_opt_under_this_variant"])
        w.writerows(sens_rows)
    text = "\n".join(lines) + "\n"
    with open(os.path.join(HERE, "summary.txt"), "w", encoding="utf-8") as fh:
        fh.write(text)

    figures = {"fig_inputs.svg": fig_inputs(data, nominal),
               "fig_optimum_vs_N.svg": fig_optimum_vs_n(nominal, boot),
               "fig_time_vs_level.svg": fig_time_vs_level(nominal),
               "fig_cost_of_fixed_levels.svg": fig_cost(nominal)}
    for name, body in figures.items():
        with open(os.path.join(HERE, name), "w", encoding="utf-8") as fh:
            fh.write(body)
    print(text.encode("ascii", "replace").decode("ascii"))
    print("wrote results.csv, robust_choice.csv, sensitivity.csv, inputs.csv, summary.txt, " + ", ".join(figures))


if __name__ == "__main__":
    main()
