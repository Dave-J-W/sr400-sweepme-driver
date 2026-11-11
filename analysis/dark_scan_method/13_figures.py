"""13. Figures, from the CSVs in out/ only (standard library; selftest's _Svg/_Panel helpers).

  fig1_real_scans.svg        the two real dark scans, the tuned tubes, and their ratio
  fig2_time_structure.svg    tail residuals against elapsed time; first-window factor kappa
  fig3_method_vs_physics.svg how often each scenario reproduces each observed difference
  fig4_optimum_spread.svg    distributions of the optimum and the edge: method only vs physics
  fig5_sampling_cost.svg     reproducibility of the optimum against dark-scan time
"""

import csv
import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))  # python -I drops the script folder
from dsm_common import st, HERE, OUT, read_csv  # noqa: E402

BLUE, RED, GREY, GREEN, ORANGE = "#1f77b4", "#d62728", "#7f7f7f", "#2ca02c", "#ff7f0e"


def save(svg, name):
    with open(os.path.join(HERE, name), "w", encoding="utf-8") as h:
        h.write(svg.render())


def f(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return float("nan")


# --------------------------------------------------------------------------- figure 1
def fig1():
    levels = read_csv("01_real_levels.csv")
    t1 = read_csv("05_tube_T1.csv")
    t2 = read_csv("05_tube_T2.csv")
    d1 = [r for r in read_csv("05_tube_check.csv") if r["tube"] == "T1"]
    d2 = [r for r in read_csv("05_tube_check.csv") if r["tube"] == "T2"]
    svg = st._Svg(1200, 960)
    svg.text(40, 30, "Two real dark scans of the covered R8486, 2026-11-10: 13:20 (13:20 rules) and 16:36 (16:36 rules)",
             15, weight="bold")
    p = st._Panel(svg, 100, 70, 1040, 430, (0, 20), (0.02, 4e5), log_y=True)
    p.frame("(a) dark rate against |threshold|, raw rate = counts / live time, +-1 sigma Poisson",
            "|threshold| (mV)", "counts / s")
    for rows, tube, color, marker, name in ((d1, t1, BLUE, "o", "13:20"), (d2, t2, RED, "^", "16:36")):
        xs = [f(r["level_mV"]) for r in rows]
        live = [f(r["counts"]) / max(f(r["noise_cps"]) + f(r["dark_cps"]), 1e-12) / 1.0 for r in rows]
        rates = [f(r["counts"]) / (f(r["expected"]) / (f(r["noise_cps"]) + f(r["dark_cps"]))) for r in rows]
        sig = [math.sqrt(max(f(r["counts"]), 1)) / (f(r["expected"]) / (f(r["noise_cps"]) + f(r["dark_cps"])))
               for r in rows]
        p.errorbars(xs, rates, sig, color)
        p.series(xs, rates, color, marker=marker, line=False, label=f"real {name} (zero counts not drawn)")
        tx = [f(r["v_mV"]) for r in tube if f(r["v_mV"]) <= 20]
        p.series(tx, [math.exp(f(r["ln_noise"])) + math.exp(f(r["ln_dark"])) for r in tube if f(r["v_mV"]) <= 20],
                 color, dash="5,3", width=1.2, label=f"tube {'T1' if name == '13:20' else 'T2'} (tuned to {name})")
    p.legend()
    for k, line in enumerate(("Above 6 mV each threshold is 30 s and holds 0-77 counts.",
                              "16:36 went to 2 mV steps at 7.2 mV and stopped at 18 mV;",
                              "13:20 kept 0.4 mV steps to 15.2 mV and ran to 36 mV.")):
        svg.text(p.px(8.2), p.py(4e3) + 15 * k, line, 11, color="#555", italic=True)

    q = st._Panel(svg, 100, 580, 1040, 300, (0, 20), (0, 4.6))
    q.frame("(b) rate ratio 16:36 / 13:20 at the levels both scans measured, +-1 sigma Poisson", "|threshold| (mV)",
            "ratio 16:36 / 13:20")
    for lo, hi, color, text, k in ((2.5, 3.7, "#d62728", "2.6-3.6 mV: x1.13-3.32 (z = 16 at 3.0)", 0),
                                   (3.9, 5.7, "#ff7f0e", "4.0-5.6 mV: x1.23 +- 0.04", 1),
                                   (6.2, 18.5, "#1f77b4", "6.4-18 mV: x0.59 +- 0.06", 0)):
        q.band(lo, hi, color, "", 0.10)
        svg.text(q.px(lo) + 4, q.y + 34 + 14 * k, text, 10, color="#333", italic=True)
    q.hline(1.0, GREY, "equal rates")
    levels = [r for r in levels if f(r["level_mV"]) <= 16.0]
    xs = [f(r["level_mV"]) for r in levels]
    ys = [f(r["ratio"]) for r in levels]
    q.errorbars(xs, ys, [f(r["ratio_sig"]) for r in levels], "#222")
    q.series(xs, ys, "#222", marker="o", line=False)
    svg.text(q.px(0.3), q.y + 16, "0.4-2.4 mV (one 10-20 ms period each): agree, max |z| = 2.7 over 11 levels",
             10, color="#333", italic=True)
    svg.text(40, 940, "Source: out/01_real_levels.csv, out/05_tube_*.csv. In (b) 18 mV (13:20: 1 count, ratio 5 +- 5) is "
             "not drawn.", 10, color="#555")
    save(svg, "fig1_real_scans.svg")


# --------------------------------------------------------------------------- figure 2
def fig2():
    res = read_csv("03_tail_residuals.csv")
    prof = read_csv("02b_kappa_profile.csv")
    svg = st._Svg(1200, 900)
    svg.text(40, 30, "Time structure: is either scan's difference tied to elapsed time or to the first count window?",
             15, weight="bold")
    p = st._Panel(svg, 100, 70, 1040, 330, (0, 1050), (-4.5, 4.5))
    p.frame("(a) tail residuals (6.2-15.2 mV) against elapsed time in the scan, Pearson (obs - fit)/sqrt(fit)",
            "elapsed time t_s in the scan (s)", "residual (sigma)")
    p.hline(0.0, GREY, "")
    p.hline(2.0, GREY, "+2", left=True)
    p.hline(-2.0, GREY, "-2", left=True)
    for scan, color, marker in (("dark 13:20", BLUE, "o"), ("dark 16:36", RED, "^")):
        sel = [r for r in res if r["scan"] == scan and 6.2 - 1e-6 <= f(r["level_mV"]) <= 15.2 + 1e-6]
        p.series([f(r["t_s"]) for r in sel], [f(r["pearson"]) for r in sel], color, marker=marker,
                 line=True, width=0.8, label=f"{scan}: chi2/n = {sum(f(r['pearson']) ** 2 for r in sel) / len(sel):.2f}"
                                             f" (n = {len(sel)})")
    p.legend()
    p.note("Fit: noise ln-quadratic + exponential dark, per scan (03). 13:20 alternates high/low from 6.4 mV: "
           "lag-1 correlation -0.28 over 6.2-10 mV.", line=0, corner="br")
    p.note("Same elapsed time, different rates: at 6.0-7.2 mV both scans were at t = 241-335 s, and 16:36 reads x0.67.",
           line=1, corner="br")

    q = st._Panel(svg, 100, 490, 1040, 330, (0.25, 3.05), (0, 12))
    q.frame("(b) first 10-ms window counting kappa x the later windows: profile likelihood from the live-time fingerprint",
            "kappa (first-window rate / later rate)", "-2 delta ln L")
    q.hline(3.84, GREY, "95 % (3.84)")
    styles = {("dark 13:20", "2.6-3.6"): (BLUE, None, "o"), ("dark 13:20", "3.8-6.0"): (BLUE, "5,3", "o"),
              ("dark 16:36", "2.6-3.6"): (RED, None, "^"), ("dark 16:36", "3.8-6.0"): (RED, "5,3", "^")}
    for (scan, region), (color, dash, marker) in styles.items():
        sel = sorted((r for r in prof if r["scan"] == scan and r["region_mV"] == region), key=lambda r: f(r["kappa"]))
        q.series([f(r["kappa"]) for r in sel], [min(f(r["delta_2lnL"]), 11.8) for r in sel], color, marker=marker,
                 dash=dash, label=f"{scan}, {region} mV")
    q.vline(1.0, GREEN, "kappa = 1: no first-window effect", slot=0)
    q.legend()
    svg.text(40, 866, "(b): values above 12 drawn at 12; 9 kappa values, 3 rates, 3000 runs of the driver's "
             "_measure_point per point. The CSVs do not log single count periods; the total live time is a partial "
             "fingerprint.", 10, color="#555")
    svg.text(40, 882, "Source: out/03_tail_residuals.csv, out/02b_kappa_profile.csv.", 10, color="#555")
    save(svg, "fig2_time_structure.svg")


# --------------------------------------------------------------------------- figure 3
def fig3():
    rows = []
    s06 = {r["comparison"]: r for r in read_csv("06_summary_pairs.csv")}
    s09 = {r["comparison"]: r for r in read_csv("09_summary_pairs.csv")}
    s10 = {r["comparison"].split(":")[0]: r for r in read_csv("10_summary_pairs.csv")}
    rows.append(("METHOD ONLY, same tube T1: 16:36 rules against 13:20 rules", None))
    rows.append(("Poisson counting", s06["T1: r1636 against old"]))
    rows.append(("+ tail over-dispersion (clusters, var/mean 3)", s09["clusters_only: r1636 against old"]))
    cases = (("dac_tau_20ms", "+ DAC settling, tau 20 ms"),
             ("dac_tau_5ms", "+ DAC settling, tau 5 ms"),
             ("drift_x1_tau600s", "+ dark rate relaxing x2 -> x1, tau 600 s"),
             ("drift_x1_tau3000s", "+ dark rate relaxing x2 -> x1, tau 3000 s"),
             ("mains_0.5", "+ 60 Hz modulation of the noise, depth 0.5"),
             (None, "SAME TUBE + AN INTERMITTENT EXTRA NOISE SOURCE (environment, not method)"),
             ("extra_noise_on_off", "extra noise on/off (mean on 120 s, off 600 s)"),
             ("extra_noise_on_off_long", "extra noise on/off (mean on 900 s, off 900 s)"))
    for case, label in cases:
        if case is None:
            rows.append((label, None))
            continue
        key = f"{case}: r1636 against old"
        if key in s09:
            rows.append((label, s09[key]))
    rows.append(("PHYSICS, a changed tube (with over-dispersion)", None))
    rows.append(("tail only: dark part x0.59", s10["P1"]))
    rows.append(("noise edge only: extra noise 2.4-6 mV", s10["P2"]))
    rows.append(("both: T1 then T2 (as tuned to the two scans)", s10["P0"]))
    rows.append(("both, same (current) rules for both scans", s10["P3"]))
    cols = [("P(d_edge >= +0.8)", "edge up\n>= 0.8 mV"),
            ("P(d_opt both lights >= +0.8)", "optimum up\n>= 0.8 mV,\nboth lights"),
            ("P(z_3.0 >= obs)", "3.0 mV\nz >= 16.4"),
            ("P(chi2_eq_2.6_3.6 >= obs)", "2.6-3.6 mV\nchi2 >= 506"),
            ("P(ratio_4.0_5.6 >= obs)", "4.0-5.6 mV\nratio >= 1.23"),
            ("P(ratio_tail_6.4 <= obs)", "tail >= 6.4 mV\nratio <= 0.59")]
    top, rowh, left, colw = 150, 30, 420, 125
    height = top + rowh * len(rows) + 90
    svg = st._Svg(1200, height)
    svg.text(40, 30, "How often does each scenario reproduce each observed difference? (16:36 scan against 13:20 scan)",
             15, weight="bold")
    svg.text(40, 52, "Fraction of seeded simulated pairs (300-400 each) at least as extreme as observed, in the observed "
             "direction. 0 means none of the pairs.", 11, color="#444")
    for j, (_, head) in enumerate(cols):
        for k, line in enumerate(head.split("\n")):
            svg.text(left + colw * j + colw / 2, top - 52 + 14 * k, line, 11, "middle", weight="bold")
    y = top
    for label, r in rows:
        if r is None:
            svg.text(40, y + 20, label, 12, weight="bold", color="#333")
            y += rowh
            continue
        svg.text(52, y + 20, label, 11)
        for j, (key, _) in enumerate(cols):
            v = f(r[key])
            shade = int(255 - 200 * min(max(v, 0.0), 1.0) ** 0.5)
            fill = f"#{shade:02x}{shade:02x}ff" if v > 0 else "#ffffff"
            svg.rect(left + colw * j + 2, y + 3, colw - 4, rowh - 6, fill=fill, stroke="#cccccc")
            text = "0" if v == 0 else (f"{v:.3f}" if v < 0.01 else f"{v:.2f}")
            svg.text(left + colw * j + colw / 2, y + 20, text, 11, "middle",
                     color="#ffffff" if v > 0.6 else "#111")
        y += rowh
    svg.text(40, y + 26, "0 means none of 300-400 pairs (< ~1/300). In every row but the last, the earlier scan used the "
             "13:20 rules and the later one the 16:36 rules, as in the real data; the last row uses the current rules "
             "for both.", 10, color="#555")
    svg.text(40, y + 42, "Source: out/06_summary_pairs.csv, out/09_summary_pairs.csv, out/10_summary_pairs.csv.",
             10, color="#555")
    save(svg, "fig3_method_vs_physics.svg")


# --------------------------------------------------------------------------- figure 4
def hist(svg, panel, values, offset, width, color, label):
    counts = {}
    for v in values:
        counts[v] = counts.get(v, 0) + 1
    n = len(values)
    for v, c in counts.items():
        x = min(v, panel.x1 - 0.2)
        X0, X1 = panel.px(x + offset - width / 2), panel.px(x + offset + width / 2)
        Y = panel.py(c / n)
        svg.rect(X0, Y, X1 - X0, panel.y + panel.h - Y, fill=color, opacity=0.8, clip=panel.clip)
    panel.legend_items.append((label, color, "o", None, True, False))


def fig4():
    m0 = read_csv("10_M0_runs.csv")
    p0 = read_csv("10_P0_runs.csv")
    a_old = [r for r in m0 if r["rule"] == "old"]
    a_new = [r for r in m0 if r["rule"] == "r1636"]
    b_new = [r for r in p0 if r["rule"] == "r1636"]
    svg = st._Svg(1200, 900)
    svg.text(40, 30, "Spread of the driver's results from counting alone (one tube) against a changed tube; "
             "400 seeded scans each", 15, weight="bold")
    for k, (key, title, lo, hi, obs, step) in enumerate((
            ("opt_L1", "(a) S/sqrt(B) optimum with light 13:59 (levels 0.4 mV apart; values >= 9.8 mV pooled at 9.8)",
             5.6, 10.0, (6.8, 7.6), 0.4),
            ("edge_mV", "(b) noise edge (levels 0.2 mV apart; values >= 6.8 mV pooled at 6.8)", 4.4, 7.0,
             (5.2, 6.0), 0.2))):
        p = st._Panel(svg, 100, 80 + 420 * k, 1040, 320, (lo, hi), (0, 0.75))
        p.frame(title, "level (mV); each group of three bars is centred on its level", "fraction of scans")
        vals = lambda rows: [min(f(r[key]), hi - 0.2) for r in rows if r[key] not in ("", None)]
        w = step * 0.27
        hist(svg, p, vals(a_old), -w, w * 0.9, BLUE, "T1, 13:20 rules (method only)")
        hist(svg, p, vals(a_new), 0.0, w * 0.9, "#9467bd", "T1, 16:36 rules (method only)")
        hist(svg, p, vals(b_new), w, w * 0.9, RED, "T2, 16:36 rules (physics + method)")
        p.vline(obs[0], BLUE, f"observed 13:20: {obs[0]:g}", slot=0)
        p.vline(obs[1], RED, f"observed 16:36: {obs[1]:g}", slot=1)
        p.legend()
    svg.text(40, 880, "Tubes with the tuned tail over-dispersion. Source: out/10_M0_runs.csv, out/10_P0_runs.csv.",
             10, color="#555")
    save(svg, "fig4_optimum_spread.svg")


# --------------------------------------------------------------------------- figure 5
def fig5():
    first = read_csv("11_summary.csv")
    rows = read_csv("11b_summary.csv")
    svg = st._Svg(1200, 940)
    svg.text(40, 30, "Reproducibility of the optimum against dark-scan time: more counting helps only if the tail fit "
             "stops narrowing", 15, weight="bold")
    xmax = 760.0
    for k, tube in enumerate(("T1", "T2")):
        p = st._Panel(svg, 100, 80 + 420 * k, 1040, 320, (0, xmax), (0, 1.45))
        p.frame(f"({'ab'[k]}) tube {tube}: P(two independent dark scans give optima within 0.2 mV), "
                f"0.2 mV light grid, light noise-free", "mean dark-scan time (min)", "probability")
        grey = [r for r in first if r["tube"] == tube]
        p.series([f(r["scan_min mean"]) for r in grey], [f(r["L1f P(<=0.2)"]) for r in grey], "#bbbbbb",
                 marker="o", line=False, label="all 21 sampling variants of 11, driver fit, light 13:59")
        for analysis, dash, name in (("driver", "5,3", "driver fit"),
                                     ("tail_line", None, "straight-line tail fit above 6 mV")):
            for lk, color, lname in (("L1f", BLUE, "light 13:59"), ("L2f", RED, "light 17:24")):
                sel = sorted((r for r in rows if r["tube"] == tube and r["analysis"] == analysis),
                             key=lambda r: f(r["scan_min mean"]))
                p.series([f(r["scan_min mean"]) for r in sel], [f(r[f"{lk} P(<=0.2)"]) for r in sel], color,
                         marker="o", dash=dash, filled=analysis == "tail_line", label=f"{name}, {lname}")
        p.hline(0.9, GREY, "0.9", left=True)
        p.legend()
    svg.text(40, 900, "Each point: 150 seeded scans of a tube with the tuned tail over-dispersion. Points of 11b, by "
             "time: 0.4 mV grid 30 s x1 and 120 s x2; 0.2 mV grid 60 s x4, 120 s x4, 240 s x2, 480 s x2, 960 s x2",
             10, color="#555")
    svg.text(40, 916, "(dwell per level over 5.6-10 mV x passes there). Source: out/11_summary.csv, "
             "out/11b_summary.csv.", 10, color="#555")
    save(svg, "fig5_sampling_cost.svg")


if __name__ == "__main__":
    which = sys.argv[1:] or ["1", "2", "3", "4", "5"]
    for w in which:
        {"1": fig1, "2": fig2, "3": fig3, "4": fig4, "5": fig5}[w]()
        print("figure", w, "written")
