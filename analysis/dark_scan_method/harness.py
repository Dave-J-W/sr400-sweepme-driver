"""Study harness: the driver's real dark-scan sampling code against an extended virtual SR400.

What is reused, unmodified:
  - VirtualSR400 from Logger-Stanford_SR400/tests/test_sr400_virtual.py, imported by path with a
    stub for the one pysweepme import it needs. Its command parser (DL, CP, CR, CS, SS, QA, DM,
    DS ...) and its one-significant-digit CP preset are what the driver talks to here.
  - selftest._measure_point (the adaptive counter), selftest._ceil_count_time, threshold_grid,
    _scan_setup, analyse_dark, analyse_light, _smooth_dark_rate. Each campaign loads its own copy
    of selftest.py so a rule set is emulated by overriding that copy's module constants.

What is new here:
  - StudySR400, a VirtualSR400 subclass on a virtual clock (no wall-clock waiting, fully
    seeded), whose SIGNAL INPUT 1 is a Tube object instead of the bench's analytic PMT;
  - Tube: tabulated noise roll-off plus dark single-PE counts with the light scan's amplitude
    shape, and optional effects: over-dispersed dark counts (clusters, or a slowly modulated
    rate), a dark-rate relaxation, an extra noise component that switches on and off
    (telegraph), mains-phase modulation of the noise, and discriminator-DAC settling;
  - SimDevice, the few driver methods _measure_point calls, each sent as the SR400 command the
    real driver sends (main.py), with per-command overheads measured on the real scans;
  - run_dark_scan, the scan loop of selftest.run_threshold_scan_dark (2026-11-11), line for
    line minus reporting and files, plus the stop-after-3-zeros rule of the 13:20 scan.

Rule sets (RULES): "old" = the 13:20 scan, "r1636" = the 16:36 scan, "current" = the driver now.
"""

import importlib.util
import math
import os
import random
import sys
import time as _real_time
import types

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from dsm_common import ROOT, load_selftest, poisson  # noqa: E402


# ----------------------------------------------------------------------------- the bench's simulator

def _load_bench():
    if "pysweepme" not in sys.modules:
        pkg = types.ModuleType("pysweepme")
        sub = types.ModuleType("pysweepme.EmptyDeviceClass")

        class EmptyDevice:  # the bench only patches get_folder onto it
            pass

        sub.EmptyDevice = EmptyDevice
        pkg.EmptyDeviceClass = sub
        sys.modules["pysweepme"] = pkg
        sys.modules["pysweepme.EmptyDeviceClass"] = sub
    path = os.path.join(ROOT, "Logger-Stanford_SR400", "tests", "test_sr400_virtual.py")
    spec = importlib.util.spec_from_file_location("sr400_virtual_bench_dsm", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


bench = _load_bench()


# ----------------------------------------------------------------------------- tube model

def _interp_log(table, v_mv):
    """Linear interpolation of ln(rate) in a sorted [(v_mV, ln_rate), ...]; linear extrapolation
    from the end segments."""
    if v_mv <= table[0][0]:
        (x0, y0), (x1, y1) = table[0], table[1]
    elif v_mv >= table[-1][0]:
        (x0, y0), (x1, y1) = table[-2], table[-1]
    else:
        lo, hi = 0, len(table) - 1
        while hi - lo > 1:
            mid = (lo + hi) // 2
            if table[mid][0] <= v_mv:
                lo = mid
            else:
                hi = mid
        (x0, y0), (x1, y1) = table[lo], table[hi]
    return y0 + (y1 - y0) * (v_mv - x0) / (x1 - x0)


class Tube:
    """Count-rate model of the covered R8486 on SIGNAL INPUT 1, as a function of the effective
    |threshold| (mV) and the time since the scan started (s).

    rate(V, t) = noise(V) * mains(t) + extra(V) * state(t) + dark(V, t)
      noise(V)   exp(interpolated ln-rate table), the electronic noise roll-off
      extra(V)   an optional extra noise component, on only while state(t) = 1 (telegraph process
                 with mean on/off durations), or always on (state_always = True)
      dark(V,t)  dark_cps * shape(V) * (1 + dark_excess * exp(-(t + dark_t0_s) / dark_tau_s))
                 * modulation(t); shape(V) = the light scan's photon fraction, 1 at the valley
    Counting effects:
      cluster_mean > 1: dark counts arrive in clusters (geometric size, that mean); counts are
                 compound Poisson (over-dispersed). cluster_mode "whole": a cluster above the
                 threshold counts whole, var/mean = 2 m - 1 at every level (what the real tail
                 shows: chi-square ~3 at both ~37 and ~10 counts per threshold); "thin": each
                 pulse has its own amplitude, so the excess falls as the level rises
      mod_sigma > 0: dark rate multiplied by exp(mod_sigma * X(t) - mod_sigma^2 / 2), X an
                 Ornstein-Uhlenbeck process with correlation time mod_tau_s
      dac_tau_s > 0: after each level change the effective level relaxes from the old level to
                 the new one with this time constant (exponential settling)
      mains_depth > 0: noise multiplied by 1 + mains_depth * cos(2 pi mains_hz t + phase)
    """

    def __init__(self, noise_table, shape_table, dark_cps, rng, **opts):
        self.noise_table = noise_table
        self.shape_table = shape_table
        self.dark_cps = dark_cps
        self.rng = rng
        o = dict(extra_table=None, state_always=False, extra_on_s=60.0, extra_off_s=600.0,
                 extra_start_on=None, dark_excess=0.0, dark_tau_s=600.0, dark_t0_s=0.0,
                 cluster_mean=1.0, cluster_from_mv=3.0, mod_sigma=0.0, mod_tau_s=60.0,
                 dac_tau_s=0.0, mains_depth=0.0, mains_hz=60.0, noise_scale=1.0,
                 first_factor=1.0, cluster_mode="whole")
        unknown = set(opts) - set(o)
        if unknown:
            raise ValueError(f"unknown tube options {sorted(unknown)}")
        o.update(opts)
        self.o = o
        # telegraph state
        self._state = None
        self._next_switch = 0.0
        # OU state
        self._x = rng.gauss(0.0, 1.0)
        self._x_t = 0.0
        self._phase = rng.random() * 2.0 * math.pi
        self.shape_floor = math.exp(_interp_log(shape_table, o["cluster_from_mv"]))

    # --- components
    def noise(self, v_mv):
        return self.o["noise_scale"] * math.exp(_interp_log(self.noise_table, v_mv))

    def extra(self, v_mv):
        t = self.o["extra_table"]
        return 0.0 if t is None else math.exp(_interp_log(t, v_mv))

    def shape(self, v_mv):
        return math.exp(_interp_log(self.shape_table, v_mv))

    def dark_mean(self, v_mv, t):
        o = self.o
        relax = 1.0 + o["dark_excess"] * math.exp(-(t + o["dark_t0_s"]) / o["dark_tau_s"])
        return self.dark_cps * self.shape(v_mv) * relax

    def truth(self, v_mv, t=1e9, with_extra=True):
        """The noise-free expected rate (no modulation, extra noise on if with_extra and the
        component is always on)."""
        extra = self.extra(v_mv) if (with_extra and self.o["state_always"]) else 0.0
        return self.noise(v_mv) + extra + self.dark_mean(v_mv, t)

    # --- time-dependent pieces
    def _extra_state_segments(self, t0, t1):
        """[(a, b, state)] covering [t0, t1] for the telegraph extra-noise component."""
        o = self.o
        if o["extra_table"] is None:
            return [(t0, t1, 0)]
        if o["state_always"]:
            return [(t0, t1, 1)]
        if self._state is None:
            p_on = o["extra_on_s"] / (o["extra_on_s"] + o["extra_off_s"])
            self._state = (1 if self.rng.random() < p_on else 0) if o["extra_start_on"] is None \
                else int(o["extra_start_on"])
            mean = o["extra_on_s"] if self._state else o["extra_off_s"]
            self._next_switch = t0 + self.rng.expovariate(1.0 / mean)
        out, a = [], t0
        while self._next_switch < t1:
            out.append((a, self._next_switch, self._state))
            a = self._next_switch
            self._state = 1 - self._state
            mean = o["extra_on_s"] if self._state else o["extra_off_s"]
            self._next_switch = a + self.rng.expovariate(1.0 / mean)
        out.append((a, t1, self._state))
        return out

    def _modulation_mean(self, t0, t1):
        """Mean of the dark-rate modulation factor over [t0, t1], advancing the OU process."""
        o = self.o
        if o["mod_sigma"] <= 0.0:
            return 1.0
        tau, s = o["mod_tau_s"], o["mod_sigma"]

        def step_to(t):
            dt = t - self._x_t
            if dt > 0:
                a = math.exp(-dt / tau)
                self._x = a * self._x + math.sqrt(1 - a * a) * self.rng.gauss(0.0, 1.0)
                self._x_t = t

        step_to(t0)
        n = max(1, min(200, int(math.ceil((t1 - t0) / (tau / 10.0)))))
        acc = 0.0
        for k in range(n):
            ta = t0 + (t1 - t0) * k / n
            tb = t0 + (t1 - t0) * (k + 1) / n
            fa = math.exp(s * self._x - 0.5 * s * s)
            step_to(tb)
            fb = math.exp(s * self._x - 0.5 * s * s)
            acc += 0.5 * (fa + fb) * (tb - ta)
        return acc / (t1 - t0)

    def _mains_mean(self, t0, t1):
        o = self.o
        if o["mains_depth"] <= 0.0:
            return 1.0
        w = 2.0 * math.pi * o["mains_hz"]
        integral = (math.sin(w * t1 + self._phase) - math.sin(w * t0 + self._phase)) / w
        return 1.0 + o["mains_depth"] * integral / (t1 - t0)

    # --- one count period
    def count(self, v_mv, v_prev_mv, t_change, t0, T, first=False):
        """Counts in a period [t0, t0 + T] at level v_mv (set at t_change, from v_prev_mv).
        first: this is the first period after the level was set; first_factor != 1 scales its
        expected counts (a generic stand-in for any effect confined to that first window)."""
        o = self.o
        t1 = t0 + T
        # Effective level over the period: settling, sampled on a grid fine at the start.
        if o["dac_tau_s"] > 0.0 and abs(v_prev_mv - v_mv) > 1e-9:
            edges = sorted({t0, t1} | {min(t1, max(t0, t_change + o["dac_tau_s"] * f))
                                       for f in (0.05, 0.1, 0.2, 0.35, 0.5, 0.75, 1, 1.5, 2, 3, 4, 6, 9, 14)})
        else:
            edges = [t0, t1]
        noise_int = extra_int = dark_shape_int = 0.0
        segments = self._extra_state_segments(t0, t1)
        for a, b in zip(edges[:-1], edges[1:]):
            if b <= a:
                continue
            mid = 0.5 * (a + b)
            v_eff = v_mv
            if o["dac_tau_s"] > 0.0:
                v_eff = v_mv + (v_prev_mv - v_mv) * math.exp(-(mid - t_change) / o["dac_tau_s"])
            noise_int += self.noise(v_eff) * (b - a)
            dark_shape_int += self.shape(v_eff) * (b - a)
            if o["extra_table"] is not None:
                on = sum(max(0.0, min(b, sb) - max(a, sa)) for sa, sb, s in segments if s)
                extra_int += self.extra(v_eff) * on
        noise_mu = noise_int * self._mains_mean(t0, t1) + extra_int
        relax = 1.0 + o["dark_excess"] * math.exp(-(0.5 * (t0 + t1) + o["dark_t0_s"]) / o["dark_tau_s"])
        dark_mu = self.dark_cps * dark_shape_int * relax * self._modulation_mean(t0, t1)
        if first and o["first_factor"] != 1.0:
            noise_mu *= o["first_factor"]
            dark_mu *= o["first_factor"]
        counts = poisson(self.rng, noise_mu)
        if o["cluster_mean"] > 1.0 and o["cluster_mode"] == "whole":
            # Clusters counted whole: var/mean of the dark counts = 2 m - 1 at every level.
            m = o["cluster_mean"]
            p_geo = 1.0 / m
            for _ in range(poisson(self.rng, dark_mu / m)):
                k = 1
                while self.rng.random() > p_geo:
                    k += 1
                counts += k
        elif o["cluster_mean"] > 1.0:
            # Clusters of pulses with amplitude above cluster_from_mv; each pulse survives the
            # threshold with probability shape(V) / shape(cluster_from_mv).
            surv = min(1.0, (dark_shape_int / T) / self.shape_floor)
            m = o["cluster_mean"]
            clusters = poisson(self.rng, dark_mu / max(surv, 1e-12) / m)
            p_geo = 1.0 / m
            for _ in range(clusters):
                k = 1
                while self.rng.random() > p_geo:
                    k += 1
                for _ in range(k):
                    if self.rng.random() < surv:
                        counts += 1
        else:
            counts += poisson(self.rng, dark_mu)
        return counts


# ----------------------------------------------------------------------------- the instrument

class StudySR400(bench.VirtualSR400):
    """The bench's VirtualSR400 on a virtual clock, with a Tube on SIGNAL INPUT 1.

    A START (CS) runs one count period at once: the clock advances by the count time plus the
    measured per-period overhead, and the counts come from the tube. Every other command is the
    bench's own handler."""

    def __init__(self, tube, overhead_level_s=0.0, overhead_period_s=0.0):
        super().__init__(pmt={})
        self.tube = tube
        self.clock = 0.0
        self.overhead_level_s = overhead_level_s
        self.overhead_period_s = overhead_period_s
        self.prev_abs_mv = 0.0
        self.changed_at = 0.0

    def sim_time(self):
        return self.clock

    def _advance(self):
        return  # periods complete inside CS

    def _cmd_DL(self, a):
        old = abs(self.disc_level[int(a[0])]) * 1e3 if a else 0.0
        super()._cmd_DL(a)
        if len(a) > 1 and int(a[0]) == 0:
            self.prev_abs_mv = old
            self.changed_at = self.clock
            self.clock += self.overhead_level_s
            self.fresh = True

    fresh = False
    periods_run = 0

    def _cmd_CS(self, a):
        if self.points_done >= self.periods:
            return
        T = self.count_time
        v = abs(self.disc_level[0]) * 1e3
        counts = self.tube.count(v, self.prev_abs_mv, self.changed_at, self.clock, T, first=self.fresh)
        self.fresh = False
        self.periods_run += 1
        self.clock += T + self.overhead_period_s
        self.buffer.append((counts, 0))
        self.points_done += 1
        self.status |= 1 << 1
        if self.points_done >= self.periods:
            self._end_of_scan()


class SimDevice:
    """The driver methods _measure_point and _scan_setup call, as the commands main.py sends."""

    CLOCK_FREQUENCY = 1e7
    STATUS_DATA_READY = 1 << 1
    STATUS_SCAN_FINISHED = 1 << 2

    def __init__(self, sim):
        self.port = sim

    def _query(self, command):
        self.port.write(command)
        return self.port.read()

    def reset_counters(self):
        self.port.write("CR")

    def set_count_time(self, seconds):
        value = seconds * self.CLOCK_FREQUENCY
        exponent = math.floor(math.log10(value))
        mantissa = int(round(value / 10.0 ** exponent))
        if mantissa >= 10:
            mantissa, exponent = 1, exponent + 1
        self.port.write(f"CP 2,{mantissa}E{exponent}")

    def get_counter_preset(self, counter):
        return float(self._query("CP 2" if counter == "T" else "CP 1"))

    def set_discriminator_level(self, discriminator, level):
        self.port.write(f"DL 0,{level:.4f}")

    def set_discriminator_mode(self, discriminator, mode):
        self.port.write("DM 0,0" if mode == "Fixed" else "DM 0,1")

    def set_discriminator_slope(self, discriminator, slope):
        self.port.write("DS 0,1" if slope == "Fall" else "DS 0,0")

    def get_status_byte(self):
        return int(self._query("SS"))

    def start_counting(self):
        self.port.write("CS")

    def _wait_for_status(self, mask, timeout):
        accumulated = 0
        for _ in range(3):
            accumulated |= self.get_status_byte()
            if accumulated & mask:
                return accumulated
        raise RuntimeError("virtual period did not complete")

    def get_scan_point(self, counter, point):
        return int(self._query(f"Q{counter} {point}"))


class _VirtualTime:
    """Stands in for the time module inside a selftest copy: monotonic() is the virtual clock."""

    def __init__(self, sim):
        self.sim = sim

    def monotonic(self):
        return self.sim.clock

    def time(self):
        return self.sim.clock

    def sleep(self, seconds):
        return None

    def strftime(self, *a):
        return _real_time.strftime(*a)


# ----------------------------------------------------------------------------- rule sets

# Overheads measured on the real scans (02d_overhead.py, out/02d_overhead.csv).
OVERHEAD_LEVEL_S = 0.0028   # 02d_overhead.py, both scans
OVERHEAD_PERIOD_S = 0.0323  # rms residual 24 ms per threshold

RULES = {
    # 13:20: 200 counts or 30 s, the whole grid, stop after 3 zero-count thresholds at 30 s.
    "old": dict(DARK_TARGET_COUNTS=200, DARK_MAX_SECONDS=30.0, DARK_FAST_TARGET_COUNTS=0,
                DARK_FAST_SECONDS=0.0, DARK_COARSE_BELOW_CPS=-1.0, DARK_TAIL_FROM_V=0.0,
                stop="zeros", DARK_STOP_AFTER=3),
    # 16:36: + 500 counts where that takes < 10 s; 2 mV steps after two thresholds < 1 cps;
    # stop after three < 0.5 cps. No floor.
    "r1636": dict(DARK_TARGET_COUNTS=200, DARK_MAX_SECONDS=30.0, DARK_FAST_TARGET_COUNTS=500,
                  DARK_FAST_SECONDS=10.0, DARK_COARSE_BELOW_CPS=1.0, DARK_COARSE_STEP_V=0.002,
                  DARK_STOP_BELOW_CPS=0.5, DARK_STOP_AFTER=3, DARK_TAIL_FROM_V=0.0, stop="rate"),
    # now: as 16:36, but neither coarse steps nor the stop below 10 mV.
    "current": dict(DARK_TARGET_COUNTS=200, DARK_MAX_SECONDS=30.0, DARK_FAST_TARGET_COUNTS=500,
                    DARK_FAST_SECONDS=10.0, DARK_COARSE_BELOW_CPS=1.0, DARK_COARSE_STEP_V=0.002,
                    DARK_STOP_BELOW_CPS=0.5, DARK_STOP_AFTER=3, DARK_TAIL_FROM_V=0.010, stop="rate"),
}


def make_module(rules, extra=None):
    """A private copy of selftest.py with the rule set's constants applied."""
    m = load_selftest(f"sr400_selftest_rules_{id(rules)}_{random.random()}")
    for k, v in {**rules, **(extra or {})}.items():
        if k.isupper():
            setattr(m, k, v)
    return m


def run_dark_scan(m, rules, tube, grid=None, overhead_level_s=OVERHEAD_LEVEL_S,
                  overhead_period_s=OVERHEAD_PERIOD_S, start_clock=0.0, dwell=None):
    """One dark scan with module copy m under rules. Mirrors selftest.run_threshold_scan_dark.

    Returns (points, total scan seconds). grid overrides threshold_grid() (levels in V).
    dwell: optional callable abs_v -> (target_counts, max_seconds) replacing DARK_TARGET_COUNTS
    and DARK_MAX_SECONDS at that level (a proposed sampling rule; None = the module's)."""
    sim = StudySR400(tube, overhead_level_s, overhead_period_s)
    sim.clock = start_clock
    m.time = _VirtualTime(sim)
    device = SimDevice(sim)
    m._scan_setup(device)
    started = sim.clock
    points = []
    grid = list(grid) if grid is not None else m.threshold_grid()
    coarse = False
    slow_in_a_row = 0
    low_in_a_row = 0
    zeros = 0
    for index, abs_v in enumerate(grid):
        if coarse and abs_v < points[-1]["abs_v"] + m.DARK_COARSE_STEP_V - 1e-9:
            continue
        target, max_s = (m.DARK_TARGET_COUNTS, m.DARK_MAX_SECONDS) if dwell is None else dwell(abs_v)
        point = m._measure_point(device, abs_v, target, max_s,
                                 m.DARK_FAST_TARGET_COUNTS, m.DARK_FAST_SECONDS)
        point["t"] -= start_clock
        points.append(point)
        rate = point["counts"] / point["live_s"]
        peak_rate = max(p["counts"] / p["live_s"] for p in points)
        slow_in_a_row = slow_in_a_row + 1 if rate < m.DARK_COARSE_BELOW_CPS < peak_rate else 0
        if not coarse and slow_in_a_row >= 2 and abs_v >= m.DARK_TAIL_FROM_V - 1e-9:
            coarse = True
        if index == 0 and point["counts"] == 0:
            break
        if rules.get("stop") == "zeros":
            zero_at_max = point["counts"] == 0 and point["live_s"] >= m.DARK_MAX_SECONDS * 0.999
            zeros = zeros + 1 if zero_at_max else 0
            if zeros >= m.DARK_STOP_AFTER:
                break
        else:
            low_in_a_row = (low_in_a_row + 1 if rate < m.DARK_STOP_BELOW_CPS < peak_rate
                            and abs_v >= m.DARK_TAIL_FROM_V - 1e-9 else 0)
            if low_in_a_row >= m.DARK_STOP_AFTER:
                break
    # t is stamped at the end of each point; the CSV's t_s is relative to the first stamp
    t0 = points[0]["t"]
    for p in points:
        p["t"] -= t0
    return points, sim.clock - started


def measure_single(m, tube, abs_v, prev_abs_v=None, overhead_level_s=OVERHEAD_LEVEL_S,
                   overhead_period_s=OVERHEAD_PERIOD_S):
    """One call of the driver's _measure_point at abs_v (V) under module copy m's constants.
    Returns (point, number of count periods, seconds from level change to the end)."""
    sim = StudySR400(tube, overhead_level_s, overhead_period_s)
    m.time = _VirtualTime(sim)
    device = SimDevice(sim)
    m._scan_setup(device)
    if prev_abs_v is not None:
        device.set_discriminator_level("A", -prev_abs_v)
    start = sim.clock
    point = m._measure_point(device, abs_v, m.DARK_TARGET_COUNTS, m.DARK_MAX_SECONDS,
                             m.DARK_FAST_TARGET_COUNTS, m.DARK_FAST_SECONDS)
    return point, sim.periods_run, sim.clock - start


def flat_tube(rate_cps, rng, **opts):
    """A tube with the same rate at every level (for single-threshold experiments)."""
    ln = math.log(max(rate_cps, 1e-300))
    return Tube([(0.0, ln), (100.0, ln)], [(0.0, 0.0), (100.0, 0.0)], 0.0, rng, **opts)


def load_tube(name, rng, dark_scale=1.0, noise_scale=1.0, **opts):
    """Tube T1 (tuned to dark 13:20) or T2 (dark 16:36), from out/05_tube_<name>.csv."""
    import csv
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "out", f"05_tube_{name}.csv")
    with open(path, encoding="utf-8") as h:
        rows = list(csv.DictReader(h))
    noise = [(float(r["v_mV"]), float(r["ln_noise"])) for r in rows]
    dark = [(float(r["v_mV"]), float(r["ln_dark"])) for r in rows]
    return Tube(noise, dark, dark_scale, rng, noise_scale=noise_scale, **opts)


def truth_points(tube, grid_v=None, live_s=1e7):
    """Noise-free dark 'scan' of a tube: expected counts over a very long live time, on the fine
    0.2 mV grid to 40 mV. Fed to analyse_dark / analyse_light it gives the method's answer in
    the limit of infinite counting."""
    grid_v = grid_v or [round(0.0002 * k, 4) for k in range(2, 201)]
    return [{"abs_v": v, "level_v": -v, "counts": int(round(tube.truth(v * 1e3) * live_s)),
             "live_s": live_s, "t": 0.0} for v in grid_v]


def combine_points(runs):
    """Merge repeated scans level by level: counts and live time add (as analyse_light does)."""
    merged = {}
    for pts in runs:
        for p in pts:
            k = int(round(p["abs_v"] * 1e4))
            if k not in merged:
                merged[k] = {"abs_v": p["abs_v"], "level_v": p["level_v"], "counts": 0,
                             "live_s": 0.0, "t": p["t"]}
            merged[k]["counts"] += p["counts"]
            merged[k]["live_s"] += p["live_s"]
    return [merged[k] for k in sorted(merged)]
