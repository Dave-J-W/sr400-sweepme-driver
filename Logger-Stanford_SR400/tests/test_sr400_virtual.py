"""Virtual test bench for the SweepMe! SR400 driver.

Implements a simulator of the SR400 command set (as documented in the SR400 manual, chapter
"REMOTE PROGRAMMING") behind the pysweepme port interface (write/read) and runs the complete
SweepMe! driver lifecycle against it.

Run with:  python tests/test_sr400_virtual.py
"""

from __future__ import annotations

import importlib.util
import math
import os
import re
import sys
import time
from pathlib import Path
from unittest.mock import MagicMock

# --- make pysweepme importable outside Windows ---------------------------------
sys.modules.setdefault("clr", MagicMock())

from pysweepme.EmptyDeviceClass import EmptyDevice  # noqa: E402

# FolderManager is Windows specific; the driver does not use the temp folder.
EmptyDevice.get_folder = lambda self, identifier: "/tmp"  # type: ignore[assignment]


def load_driver(path: Path):
    """Import the driver's main.py as a module."""
    spec = importlib.util.spec_from_file_location("sr400_driver", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# ==============================================================================
#  SR400 simulator
# ==============================================================================

CLOCK = 1e7


class FakeVisaTimeout(Exception):
    """What pyvisa raises when a GPIB read finds nothing to read: VisaIOError, VI_ERROR_TMO."""

    error_code = -1073807339

    def __init__(self):
        super().__init__("VI_ERROR_TMO (-1073807339): Timeout expired before operation completed.")


class VirtualSR400:
    """A minimal but faithful SR400 that speaks the documented ASCII protocol."""

    def __init__(
        self,
        rate_input1: float = 5.0e4,
        rate_input2: float = 1.0e3,
        echo: bool = False,
        loopback: bool = False,
        pmt: dict | None = None,
        time_scale: float = 1.0,
    ):
        self.rate = {"10 MHz": CLOCK, "INPUT 1": rate_input1, "INPUT 2": rate_input2, "TRIG": 1.0e3}
        self.echo = echo

        # Models self-test cable 1: a BNC from the A DISC output to SIGNAL INPUT 2, which
        # feeds whatever counter A is counting -- including the internal 10 MHz -- back into
        # INPUT 2. That is what gives counters B and T a known pulse train, and it is the only
        # way the tier-2 pass path is reachable without hardware.
        self.loopback = loopback

        # Models an R8486-like bare tube on SIGNAL INPUT 1 for the threshold scans: what a
        # counter sees there depends on ITS OWN discriminator (manual: each counter has one),
        # through an integral pulse-height distribution with a steep noise edge, a valley and a
        # single-photoelectron shoulder. Keys, all overridable: dark_rate, light_rate (cps of
        # photoelectrons), spe_mean, spe_sigma, spe_exp_fraction, spe_exp_scale (V),
        # noise_rate (cps at 0 V), noise_scale (V), drift_per_s (fractional change of the light
        # per simulated second), hysteresis_v (effective-threshold lag behind the direction of
        # travel). None leaves INPUT 1 on the plain rate_input1 model, so nothing older changes.
        self.pmt = None
        if pmt is not None:
            self.pmt = {
                "dark_rate": 8.0, "light_rate": 0.0,
                "spe_mean": 0.010, "spe_sigma": 0.004,
                "spe_exp_fraction": 0.15, "spe_exp_scale": 0.0015,
                "noise_rate": 2.0e7, "noise_scale": 0.00035,
                "drift_per_s": 0.0, "hysteresis_v": 0.0,
                # 0 keeps the old monotonic noise. Measured 2026-11-10 on the real tube: the
                # rate PEAKS (~2.3e5 cps at 1.2 mV) and falls again below that, by about e per
                # 0.45 mV. noise_peak_v > 0 models that hump.
                "noise_peak_v": 0.0, "noise_rise_v": 0.00045,
                # A dark rate relaxing after an HV change or light exposure:
                # dark_rate * (1 + dark_excess * exp(-t / dark_tau_s)), t in simulated seconds.
                "dark_excess": 0.0, "dark_tau_s": 600.0,
                **pmt,
            }
        self._disc_shift = {0: 0.0, 1: 0.0, 2: 0.0}

        # Simulated seconds per wall-clock second. A real dark scan is 15-20 minutes of
        # counting; at 1000x the bench runs it in about a second with the real constants.
        self.time_scale = time_scale
        self._t0 = time.time()

        self.log: list[str] = []
        self.out: list[str] = []

        # instrument state, initialised with the documented default setup
        self.counting_mode = 0
        self.counter_input = {0: 1, 1: 2, 2: 0}  # A=INPUT 1, B=INPUT 2, T=10 MHz
        self.preset = {1: 1e3, 2: 1e7}  # B SET, T SET
        self.periods = 1
        self.scan_end_mode = 0
        self.dwell = 1.0
        self.dac_source = 0
        self.dac_range = 0
        self.display_mode = 0
        self.trigger_slope = 0
        self.trigger_level = 2.000
        self.disc_slope = {0: 1, 1: 1, 2: 1}
        self.disc_mode = {0: 0, 1: 0, 2: 0}
        self.disc_level = {0: -0.010, 1: -0.010, 2: -0.010}
        self.disc_step = {0: 0.0, 1: 0.0, 2: 0.0}
        self.port_mode = {1: 0, 2: 0}
        self.port_level = {1: 0.0, 2: 0.0}
        self.port_step = {1: 0.0, 2: 0.0}
        self.gate_mode = {0: 0, 1: 0}
        self.gate_delay = {0: 0.0, 1: 0.0}
        self.gate_width = {0: 0.005e-6, 1: 0.005e-6}
        self.gate_step = {0: 0.0, 1: 0.0}
        self.rs232_wait = 6
        self.front_panel_mode = 0
        self.srq_mask = 0
        self.message = ""

        self.status = 0
        self.secondary = 0

        # set by the buffer-limit guards; asserted by the batching tests
        self.line_overflowed = False
        self.buffer_overflowed = False

        self.running = False
        self.period_start = 0.0
        self.points_done = 0
        self.buffer: list[tuple[int, int]] = []

    # SR400 buffer limits, enforced so that a driver which overruns a buffer fails here instead
    # of appearing to work and then losing a scan on real hardware.
    #
    # 256 is quoted: "a command input buffer of 256 characters", and an output buffer "of 256
    # characters" whose overflow "erases" all buffered data (manual p. 37). 240 is the manual's
    # ERR-LED threshold for "a communication buffer has exceeded 240 characters" (p. 37);
    # treating that as also setting status bit 7, and as discarding the rest of the line, is a
    # deliberately strict *inference* -- the manual only states the discard for errors generally.
    # Strict is the right direction for a simulator: the driver caps itself at 180.
    COMMAND_LINE_ERROR_CHARS = 240
    OUTPUT_BUFFER_CHARS = 256

    # ---------------------------------------------------------------- port API
    def write(self, command: str) -> None:
        self.log.append(command)
        if self.echo:  # ECHO = ON returns the command and an OK> prompt
            self.out.append(command)
            self.out.append("OK>")

        # Per the inference documented above: treat an over-long line as an error, and then
        # apply the manual's stated consequence of an error -- "any commands remaining on the
        # current command line (up to the next <cr>) are lost".
        if len(command) + 1 > self.COMMAND_LINE_ERROR_CHARS:
            self.status |= 1 << 7
            self.line_overflowed = True
            return

        for single in command.split(";"):
            self._execute(single.strip())

    # Set by make_device() for a GPIB port name. An empty read then raises as pyvisa does
    # (measured 2026-11-10: a GPIB drain died with VI_ERROR_TMO). Returning "" on GPIB is
    # what let tier 1 pass here "over GPIB" while failing on the bench.
    gpib = False

    def read(self) -> str:
        if self.out:
            return self.out.pop(0)
        if self.gpib:
            self.empty_gpib_reads = getattr(self, "empty_gpib_reads", 0) + 1
            raise FakeVisaTimeout
        return ""

    def in_waiting(self) -> int:
        """Pending response characters, as a COM port would report them."""
        return sum(len(entry) + 1 for entry in self.out)

    def inject_stale_response(self, text: str) -> None:
        """Prepend a bogus pending response, simulating a desynchronised link."""
        self.out.insert(0, text)

    # ------------------------------------------------------------ count model
    @property
    def count_time(self) -> float:
        """Length of one count period, if it is determined by the T preset and the clock."""
        if self.counting_mode == 3:  # A for B preset
            return self.preset[1] / max(self._rate_for(self._input_name(1)), 1e-12)
        source = self._input_name(2)
        return self.preset[2] / max(self._rate_for(source), 1e-12)

    def _input_name(self, counter: int) -> str:
        names = {0: "10 MHz", 1: "INPUT 1", 2: "INPUT 2", 3: "TRIG"}
        return names[self.counter_input[counter]]

    DISC_PULSE_V = -0.7
    """Amplitude of the A DISC output, a negative NIM pulse. Only relevant under loopback."""

    def _discriminator_sees(self, counter: int) -> bool:
        """Whether counter i's discriminator fires on the looped-back DISC pulse.

        Cable 1 carries a negative NIM pulse of about -0.7 V. A discriminator set to RISE never
        crosses upward on it, and a threshold outside the band (DISC_PULSE_V, 0) is either on
        the wrong side of the baseline or deeper than the pulse ever goes. Modelled only under
        loopback: without the cable there is no defined pulse shape to reason about.
        """
        if not self.loopback:
            return True
        if self._input_name(counter) not in ("INPUT 1", "INPUT 2"):
            return True
        if self.disc_slope[counter] != 1:  # 1 = FALL
            return False
        return self.DISC_PULSE_V < self.disc_level[counter] < 0.0

    def sim_time(self) -> float:
        """Simulated seconds since construction."""
        return (time.time() - self._t0) * self.time_scale

    def _spe_survival(self, amplitude: float) -> float:
        """P(single-PE pulse amplitude > amplitude): Gaussian peak plus a low exponential tail."""
        p = self.pmt
        mu, sigma = p["spe_mean"], p["spe_sigma"]
        norm = 0.5 * math.erfc(-mu / (sigma * math.sqrt(2.0)))
        gaussian = 0.5 * math.erfc((amplitude - mu) / (sigma * math.sqrt(2.0))) / norm
        exponential = math.exp(-amplitude / p["spe_exp_scale"])
        f = p["spe_exp_fraction"]
        return (1.0 - f) * gaussian + f * exponential

    def _pmt_rate(self, counter: int) -> float:
        """Count rate counter i sees from the tube, through discriminator i."""
        p = self.pmt
        level = self.disc_level[counter]
        effective = abs(level) + self._disc_shift[counter]
        noise = p["noise_rate"] * math.exp(-max(effective, 0.0) / p["noise_scale"])
        peak = p["noise_peak_v"]
        if peak > 0.0 and effective < peak:
            at_peak = p["noise_rate"] * math.exp(-peak / p["noise_scale"])
            noise = at_peak * math.exp(-(peak - effective) / p["noise_rise_v"])
        # A negative anode pulse only fires a FALL discriminator with a negative threshold.
        if self.disc_slope[counter] != 1 or level >= 0.0:
            return noise
        light = p["light_rate"] * (1.0 + p["drift_per_s"] * self.sim_time())
        dark = p["dark_rate"] * (1.0 + p["dark_excess"] * math.exp(-self.sim_time() / p["dark_tau_s"]))
        return noise + (dark + max(light, 0.0)) * self._spe_survival(max(effective, 0.0))

    def _rate_for(self, source: str) -> float:
        """Pulse rate at a source, with cable 1 feeding counter A's source into INPUT 2."""
        if self.loopback and source == "INPUT 2":
            return self.rate[self._input_name(0)]
        return self.rate[source]

    def _counter_rate(self, counter: int) -> float:
        if self.pmt is not None and self._input_name(counter) == "INPUT 1":
            return self._pmt_rate(counter)
        return self._rate_for(self._input_name(counter))

    def _counts_for_period(self) -> tuple[int, int]:
        duration = self.count_time
        counts_a = int(round(self._counter_rate(0) * duration))
        counts_b = int(round(self._counter_rate(1) * duration))

        if not self._discriminator_sees(0):
            counts_a = 0
        if not self._discriminator_sees(1):
            counts_b = 0

        if self.counting_mode == 3:
            counts_b = -1  # counter B is the preset counter
        elif self.counting_mode == 1:
            counts_a = counts_a - counts_b  # A-B for T preset
        elif self.counting_mode == 2:
            counts_a = counts_a + counts_b  # A+B for T preset

        return counts_a, counts_b

    def _complete_period(self) -> None:
        self.buffer.append(self._counts_for_period())
        self.points_done += 1
        self.status |= 1 << 1  # Data Ready
        if self.buffer[-1][0] >= 1e9 - 1:
            self.status |= 1 << 3  # Counter Overrun

    def _end_of_scan(self) -> None:
        self.running = False
        self.secondary &= ~(1 << 2)
        if self.scan_end_mode == 0:
            self.status |= 1 << 2  # Scan Finished

    def _advance(self) -> None:
        """Let simulated time pass: complete the count periods that are due."""
        if not self.running:
            return

        elapsed = (time.time() - self.period_start) * self.time_scale

        if self.dwell == 0:
            # EXTERNAL dwell: one START runs exactly one count period, then the instrument
            # waits indefinitely for the next START.
            if elapsed >= self.count_time:
                self._complete_period()
                if self.points_done >= self.periods:
                    self._end_of_scan()
                else:
                    self.running = False  # waiting for the next START
                    self.secondary &= ~(1 << 2)
            return

        period = max(self.count_time + self.dwell, 1e-9)
        target = min(self.periods, int(elapsed // period))
        while self.points_done < target:
            self._complete_period()

        if self.points_done >= self.periods:
            self._end_of_scan()

    # -------------------------------------------------------------- execution
    def _execute(self, command: str) -> None:
        if command == "":
            return

        letters = command[:2].upper()
        argument = command[2:].replace(" ", "")
        arguments = [a for a in argument.split(",") if a != ""]

        handler = getattr(self, f"_cmd_{letters}", None)
        if handler is None:
            self.status |= 1 << 7  # Command Error
            return

        try:
            handler(arguments)
        except (ValueError, IndexError, KeyError):
            self.status |= 1 << 7  # parameter out of range / illegal command

        self._advance()

    def _answer(self, text: str) -> None:
        # DATA BUFFER OVERFLOW: the output buffer is finite and overrunning it erases
        # everything buffered, which costs the whole scan rather than one value.
        if sum(len(entry) + 1 for entry in self.out) + len(text) + 1 > self.OUTPUT_BUFFER_CHARS:
            self.out.clear()
            self.buffer_overflowed = True
            return

        self.out.append(text)

    @staticmethod
    def _sci(value: float) -> str:
        """Format like the SR400 does for presets and dwell times, e.g. '1E7'."""
        if value == 0:
            return "0"
        exponent = math.floor(math.log10(abs(value)))
        mantissa = int(round(value / 10.0**exponent))
        return f"{mantissa}E{exponent}"

    @staticmethod
    def _limit(value: float, low: float, high: float) -> float:
        if not low <= value <= high:
            raise ValueError
        return value

    @staticmethod
    def _one_digit(value: float) -> float:
        exponent = math.floor(math.log10(value))
        return float(int(value / 10.0**exponent)) * 10.0**exponent  # truncation, as documented

    # --- MODE -----------------------------------------------------------------
    def _cmd_CM(self, a):
        if not a:
            self._answer(str(self.counting_mode))
            return
        self.counting_mode = int(self._limit(int(a[0]), 0, 3))
        self._reset()

    def _cmd_CI(self, a):
        counter = int(self._limit(int(a[0]), 0, 2))
        allowed = {0: (0, 1), 1: (1, 2), 2: (0, 2, 3)}[counter]
        if len(a) == 1:
            self._answer(str(self.counter_input[counter]))
            return
        source = int(a[1])
        if source not in allowed:
            raise ValueError
        self.counter_input[counter] = source

    def _cmd_CP(self, a):
        counter = int(self._limit(int(a[0]), 1, 2))
        if len(a) == 1:
            self._answer(self._sci(self.preset[counter]))
            return
        self.preset[counter] = self._one_digit(self._limit(float(a[1]), 1.0, 9e11))

    def _cmd_NP(self, a):
        if not a:
            self._answer(str(self.periods))
            return
        self.periods = int(self._limit(int(a[0]), 1, 2000))

    def _cmd_NN(self, a):
        self._answer(str(self.points_done))

    def _cmd_NE(self, a):
        if not a:
            self._answer(str(self.scan_end_mode))
            return
        self.scan_end_mode = int(self._limit(int(a[0]), 0, 1))

    def _cmd_DT(self, a):
        if not a:
            self._answer(self._sci(self.dwell) if self.dwell else "0")
            return
        value = float(a[0])
        if value == 0:
            self.dwell = 0.0
            return
        self.dwell = self._one_digit(self._limit(value, 2e-3, 6e1))

    def _cmd_AS(self, a):
        if not a:
            self._answer(str(self.dac_source))
            return
        self.dac_source = int(self._limit(int(a[0]), 0, 3))

    def _cmd_AM(self, a):
        if not a:
            self._answer(str(self.dac_range))
            return
        self.dac_range = int(self._limit(int(a[0]), 0, 7))

    def _cmd_SD(self, a):
        if not a:
            self._answer(str(self.display_mode))
            return
        self.display_mode = int(self._limit(int(a[0]), 0, 1))

    # --- LEVELS ---------------------------------------------------------------
    def _cmd_TS(self, a):
        if not a:
            self._answer(str(self.trigger_slope))
            return
        self.trigger_slope = int(self._limit(int(a[0]), 0, 1))

    def _cmd_TL(self, a):
        if not a:
            self._answer(f"{self.trigger_level:+.3f}")
            return
        self.trigger_level = self._limit(float(a[0]), -2.000, 2.000)

    def _cmd_DS(self, a):
        i = int(self._limit(int(a[0]), 0, 2))
        if len(a) == 1:
            self._answer(str(self.disc_slope[i]))
            return
        self.disc_slope[i] = int(self._limit(int(a[1]), 0, 1))

    def _cmd_DM(self, a):
        i = int(self._limit(int(a[0]), 0, 2))
        if len(a) == 1:
            self._answer(str(self.disc_mode[i]))
            return
        self.disc_mode[i] = int(self._limit(int(a[1]), 0, 1))

    def _cmd_DL(self, a):
        i = int(self._limit(int(a[0]), 0, 2))
        if len(a) == 1:
            self._answer(f"{self.disc_level[i]:+.4f}")
            return
        new = self._limit(float(a[1]), -0.3000, 0.3000)
        if self.pmt is not None and self.pmt["hysteresis_v"]:
            h = self.pmt["hysteresis_v"]
            if abs(new) > abs(self.disc_level[i]):
                self._disc_shift[i] = -h / 2.0
            elif abs(new) < abs(self.disc_level[i]):
                self._disc_shift[i] = +h / 2.0
        self.disc_level[i] = new

    def _cmd_DY(self, a):
        i = int(self._limit(int(a[0]), 0, 2))
        if len(a) == 1:
            self._answer(f"{self.disc_step[i]:+.4f}")
            return
        self.disc_step[i] = self._limit(float(a[1]), -0.0200, 0.0200)

    def _cmd_DZ(self, a):
        i = int(self._limit(int(a[0]), 0, 2))
        self._answer(f"{self.disc_level[i]:+.4f}")

    def _cmd_PM(self, a):
        i = int(self._limit(int(a[0]), 1, 2))
        if len(a) == 1:
            self._answer(str(self.port_mode[i]))
            return
        self.port_mode[i] = int(self._limit(int(a[1]), 0, 1))

    def _cmd_PL(self, a):
        i = int(self._limit(int(a[0]), 1, 2))
        if len(a) == 1:
            self._answer(f"{self.port_level[i]:+.3f}")
            return
        self.port_level[i] = self._limit(float(a[1]), -10.000, 10.000)

    def _cmd_PY(self, a):
        i = int(self._limit(int(a[0]), 1, 2))
        if len(a) == 1:
            self._answer(f"{self.port_step[i]:+.3f}")
            return
        self.port_step[i] = self._limit(float(a[1]), -0.500, 0.500)

    def _cmd_PZ(self, a):
        i = int(self._limit(int(a[0]), 1, 2))
        self._answer(f"{self.port_level[i]:+.3f}")

    # --- GATES ----------------------------------------------------------------
    def _cmd_GM(self, a):
        i = int(self._limit(int(a[0]), 0, 1))
        if len(a) == 1:
            self._answer(str(self.gate_mode[i]))
            return
        self.gate_mode[i] = int(self._limit(int(a[1]), 0, 2))

    def _cmd_GD(self, a):
        i = int(self._limit(int(a[0]), 0, 1))
        if len(a) == 1:
            self._answer(f"{self.gate_delay[i]:.4E}")
            return
        self.gate_delay[i] = self._limit(float(a[1]), 0.0, 999.2e-3)

    def _cmd_GW(self, a):
        i = int(self._limit(int(a[0]), 0, 1))
        if len(a) == 1:
            self._answer(f"{self.gate_width[i]:.4E}")
            return
        self.gate_width[i] = self._limit(float(a[1]), 0.005e-6, 999.2e-3)

    def _cmd_GY(self, a):
        i = int(self._limit(int(a[0]), 0, 1))
        if len(a) == 1:
            self._answer(f"{self.gate_step[i]:.4E}")
            return
        self.gate_step[i] = self._limit(float(a[1]), 0.0, 99.92e-3)

    def _cmd_GZ(self, a):
        i = int(self._limit(int(a[0]), 0, 1))
        self._answer(f"{self.gate_delay[i]:.4E}")

    # --- FRONT PANEL ----------------------------------------------------------
    def _cmd_CS(self, a):
        if self.points_done >= self.periods:
            return  # paused at the end of a scan, START has no effect
        self.running = True
        self.period_start = time.time()
        self.secondary |= 1 << 2

    def _cmd_CH(self, a):
        if self.running:
            self.running = False
        else:
            self._reset()

    def _cmd_CR(self, a):
        self._reset()

    def _cmd_CK(self, a):
        self._limit(int(a[0]), 0, 13)

    def _cmd_RR(self, a):
        pass

    def _cmd_RL(self, a):
        pass

    def _cmd_SC(self, a):
        self._answer("2")

    def _cmd_MI(self, a):
        self.front_panel_mode = int(self._limit(int(a[0]), 0, 2))

    def _cmd_MS(self, a):
        self.message = a[0] if a else ""

    def _cmd_MD(self, a):
        self._limit(int(a[0]), 1, 6)

    def _cmd_MM(self, a):
        self._answer("1")

    def _cmd_ML(self, a):
        self._answer("1")

    # --- STORE / RECALL / INTERFACE -------------------------------------------
    def _cmd_ST(self, a):
        self._limit(int(a[0]), 1, 9)

    def _cmd_RC(self, a):
        self._limit(int(a[0]), 0, 9)
        self._reset()

    def _cmd_CL(self, a):
        log = self.log
        self.__init__(self.rate["INPUT 1"], self.rate["INPUT 2"], self.echo)
        self.log = log  # the command history of the test bench survives the instrument reset

    def _cmd_SS(self, a):
        self._advance()
        if a:
            bit = int(self._limit(int(a[0]), 0, 7))
            value = (self.status >> bit) & 1
            self.status &= ~(1 << bit)
            self._answer(str(value))
            return
        self._answer(str(self.status))
        self.status = 0

    def _cmd_SI(self, a):
        self._advance()
        if a:
            bit = int(self._limit(int(a[0]), 0, 2))
            self._answer(str((self.secondary >> bit) & 1))
            return
        self._answer(str(self.secondary))

    def _cmd_SV(self, a):
        if not a:
            self._answer(str(self.srq_mask))
            return
        self.srq_mask = int(self._limit(int(a[0]), 0, 255))

    def _cmd_SW(self, a):
        if not a:
            self._answer(str(self.rs232_wait))
            return
        self.rs232_wait = int(self._limit(int(a[0]), 0, 25))

    def _cmd_SE(self, a):
        for code in a:
            self._limit(int(code), 0, 127)

    # --- DATA -----------------------------------------------------------------
    def _cmd_QA(self, a):
        self._answer(str(self._data("A", a)))

    def _cmd_QB(self, a):
        self._answer(str(self._data("B", a)))

    def _data(self, counter: str, a) -> int:
        self._advance()
        index = 0 if counter == "A" else 1
        if counter == "B" and self.counting_mode == 3:
            return -1
        if a:
            point = int(self._limit(int(a[0]), 1, 2000))
            if point > self.points_done:
                return -1
            return self.buffer[point - 1][index]
        if self.points_done == 0:
            return -1
        return self.buffer[-1][index]

    def _cmd_XA(self, a):
        self._answer("0")

    def _cmd_XB(self, a):
        self._answer("0" if self.counting_mode != 3 else "-1")

    def _cmd_EA(self, a):
        for point in self.buffer:
            self._answer(str(point[0]))

    def _cmd_EB(self, a):
        for point in self.buffer:
            self._answer(str(point[1]))

    def _reset(self) -> None:
        self.running = False
        self.points_done = 0
        self.buffer = []
        self.secondary &= ~(1 << 2)


# ==============================================================================
#  test bench
# ==============================================================================

FAILURES: list[str] = []
CHECKS = 0


def check(condition: bool, description: str) -> None:
    global CHECKS
    CHECKS += 1
    if condition:
        print(f"  ok    {description}")
    else:
        print(f"  FAIL  {description}")
        FAILURES.append(description)


def make_device(driver, instrument, **overrides):
    """Create a configured Device instance connected to the simulator."""
    device = driver.Device()
    parameters = device.set_GUIparameter()
    parameters = {key: (value[0] if isinstance(value, list) else value) for key, value in parameters.items()}
    parameters["Port"] = "COM3"
    parameters.update(overrides)
    device.get_GUIparameter(parameters)
    device.port = instrument
    if isinstance(instrument, VirtualSR400):
        instrument.gpib = str(parameters["Port"]).upper().startswith("GPIB")

    # The latency lookup reads the host's registry or sysfs, so leaving it live would make this
    # bench depend on whether the machine running it happens to have an FTDI adapter on the same
    # port name. It does on at least one development machine. Tests that care about the latency
    # timer override this themselves.
    device._get_com_latency_timer = lambda: None

    return device


def run_point(device):
    """One Logger measurement point: measure() then call().

    A Logger has no apply() and no self.value -- everything the instrument needs was sent in
    configure(), so a point is just an acquisition.
    """
    device.measure()
    return device.call()


# ------------------------------------------------------------------ test cases


def test_single_point(driver):
    print("\n[1] single count period, counter A on the 10 MHz timebase")
    sr400 = VirtualSR400()
    device = make_device(
        driver,
        sr400,
        **{
            "Counter A input": "10 MHz",
            "Counter B input": "INPUT 2",
            "Count time in s": 0.01,
            "Dwell time in s": 2e-3,
        },
    )
    device.connect()
    device.initialize()
    device.configure()
    result = run_point(device)
    device.unconfigure()

    counts_a, counts_b, rate_a, rate_b, count_time = result
    check(math.isclose(count_time, 0.01, rel_tol=1e-9), f"count time is 0.01 s (got {count_time})")
    check(counts_a == 1e5, f"counter A counted 1e5 clock cycles (got {counts_a})")
    check(math.isclose(rate_a, 1e7, rel_tol=1e-6), f"rate A is 10 MHz (got {rate_a:.4g})")
    check(counts_b == 10, f"counter B counted 10 INPUT 2 pulses (got {counts_b})")
    check(math.isclose(rate_b, 1e3, rel_tol=1e-6), f"rate B is 1 kHz (got {rate_b:.4g})")
    check("SW 0" in sr400.log, "SW 0 was sent on RS-232 to switch off the character wait")
    check(sr400.periods == 1 and sr400.scan_end_mode == 0, "NP 1 and NE 0 (stop at end of scan)")
    check(sr400.preset[2] == 1e5, f"T preset is 1e5 clock cycles (got {sr400.preset[2]:g})")
    check(sr400.disc_mode == {0: 0, 1: 0, 2: 0}, "all discriminators were set to FIXED")
    check(sr400.log[-1] == "CR", "the counters are reset in unconfigure()")
    check(sr400.out == [], "no unread answers are left in the output buffer")


def test_multiple_periods(driver):
    print("\n[2] several count periods per point, summed")
    sr400 = VirtualSR400()
    device = make_device(
        driver,
        sr400,
        **{
            "Counter A input": "INPUT 1",
            "Counter B input": "INPUT 1",
            "Measurement mode": "Scan of N periods",
            "Count time in s": 0.01,
            "Dwell time in s": 2e-3,
            "Periods per point": 5,
        },
    )
    device.connect()
    device.initialize()
    device.configure()
    counts_a, counts_b, rate_a, _, count_time = run_point(device)

    check(sr400.periods == 5, "NP 5 was programmed")
    check(counts_a == 5 * 500, f"counts of 5 periods were summed (got {counts_a})")
    check(math.isclose(count_time, 0.05, rel_tol=1e-9), f"count time is 5 x 0.01 s (got {count_time})")
    check(math.isclose(rate_a, 5e4, rel_tol=1e-6), f"rate A is 50 kHz (got {rate_a:.4g})")
    check(counts_b == counts_a, "counter B on the same input gives the same counts")


def test_external_dwell(driver):
    print("\n[3] EXTERNAL dwell: one START per count period")
    sr400 = VirtualSR400()
    device = make_device(
        driver,
        sr400,
        **{
            "Counter A input": "INPUT 1",
            "Measurement mode": "Scan of N periods",
            "Count time in s": 0.005,
            "Dwell time in s": 0,
            "Periods per point": 3,
        },
    )
    device.connect()
    device.initialize()
    device.configure()
    counts_a = run_point(device)[0]

    starts = sum(1 for command in sr400.log if command == "CS")
    check(sr400.dwell == 0.0, "DT 0 selected the EXTERNAL dwell")
    check(starts == 3, f"one CS per count period was sent (got {starts})")
    check(counts_a == 3 * 250, f"counts of 3 periods were summed (got {counts_a})")


def test_gate_delay_configuration(driver):
    print("\n[4] gate A delay and width reach the instrument in configure()")

    # Each delay is its own configuration: a Logger sets the gate once, at configure() time.
    for delay in (0.0, 1.2e-6, 1e-3):
        sr400 = VirtualSR400()
        device = make_device(
            driver,
            sr400,
            **{
                "Gate A mode": "Fixed",
                "Gate A delay in s": delay,
                "Gate A width in s": 5e-6,
                "Counter A input": "INPUT 1",
                "Count time in s": 0.002,
                "Dwell time in s": 2e-3,
            },
        )
        device.connect()
        device.initialize()
        device.configure()
        run_point(device)

        check(
            math.isclose(sr400.gate_delay[0], delay, rel_tol=1e-9, abs_tol=1e-15),
            f"gate A delay {delay:g} s was applied (instrument holds {sr400.gate_delay[0]:g})",
        )
        check(sr400.gate_mode[0] == 1, f"gate A is in FIXED mode (delay {delay:g} s)")
        check(
            math.isclose(sr400.gate_width[0], 5e-6, rel_tol=1e-9),
            f"gate A width 5 us was applied (delay {delay:g} s)",
        )
        check(
            any(command.startswith("GD 0,") for command in sr400.log),
            f"the delay was set with the GD command including the gate index (delay {delay:g} s)",
        )


def test_count_time_and_rounding(driver):
    print("\n[5] count time, incl. the one-significant-digit T preset rounding")

    def configured_point(count_time):
        sr400 = VirtualSR400()
        device = make_device(
            driver,
            sr400,
            **{
                "Counter A input": "10 MHz",
                "Count time in s": count_time,
                "Dwell time in s": 2e-3,
            },
        )
        device.connect()
        device.initialize()
        device.configure()
        return run_point(device)

    counts_a, _, rate_a, _, count_time = configured_point(0.002)
    check(math.isclose(count_time, 0.002, rel_tol=1e-9), f"2 ms count time applied (got {count_time})")
    check(counts_a == 2e4, f"counter A counted 2e4 clock cycles (got {counts_a})")
    check(math.isclose(rate_a, 1e7, rel_tol=1e-6), "the rate stays 10 MHz for the clock input")

    # 3.4 ms is not representable: the T preset keeps one significant digit -> 3 ms
    counts_a, _, _, _, count_time = configured_point(0.0034)
    check(
        math.isclose(count_time, 0.003, rel_tol=1e-9),
        f"3.4 ms was rounded to the reachable 3 ms and reported back (got {count_time})",
    )
    check(counts_a == 3e4, f"counts follow the applied count time (got {counts_a})")


def test_discriminator_and_port_configuration(driver):
    print("\n[6] discriminator level and PORT output reach the instrument in configure()")
    sr400 = VirtualSR400()
    device = make_device(
        driver,
        sr400,
        **{
            "Discriminator A level in V": -0.0252,
            "Counter A input": "INPUT 1",
            "Count time in s": 0.002,
            "Dwell time in s": 2e-3,
        },
    )
    device.connect()
    device.initialize()
    device.configure()
    run_point(device)
    check(
        math.isclose(sr400.disc_level[0], -0.0252, abs_tol=1e-9),
        f"discriminator A level -25.2 mV was applied (got {sr400.disc_level[0]})",
    )
    check(
        any(command == "DL 0,-0.0252" for command in sr400.log),
        "the level was sent with 0.1 mV formatting, matching the 0.2 mV resolution",
    )

    sr400 = VirtualSR400()
    device = make_device(
        driver,
        sr400,
        **{
            "Set PORT levels": True,
            "PORT1 level in V": 5.0,
            "Counter A input": "INPUT 1",
            "Count time in s": 0.002,
            "Dwell time in s": 2e-3,
        },
    )
    device.connect()
    device.initialize()
    device.configure()
    run_point(device)
    check(math.isclose(sr400.port_level[1], 5.0, abs_tol=1e-9), "PORT1 was set to 5 V")
    check(sr400.port_mode[1] == 0, "PORT1 was put into FIXED mode")


def test_b_preset_mode(driver):
    print("\n[7] counting mode 'A for B preset'")
    sr400 = VirtualSR400()
    device = make_device(
        driver,
        sr400,
        **{
            "Count mode": "A for B preset",
            "Counter A input": "INPUT 1",
            "Counter B input": "INPUT 2",
            "Preset counts (T or B)": 100,
            "Dwell time in s": 2e-3,
        },
    )
    device.connect()
    device.initialize()
    device.configure()
    counts_a, counts_b, rate_a, _, count_time = run_point(device)

    check(sr400.counting_mode == 3, "CM 3 was programmed")
    check(sr400.preset[1] == 100, f"counter B was preset to 100 counts (got {sr400.preset[1]:g})")
    check(counts_a > 0, f"counter A returned data (got {counts_a})")
    check(math.isnan(counts_b), "counter B is reported as NaN because it is the preset counter")
    check(math.isnan(count_time), "the count time is NaN because it depends on the signal")
    check(math.isnan(rate_a), "the rate is NaN when the count time is unknown")


def test_parameter_validation(driver):
    print("\n[8] range checks and configuration errors")
    sr400 = VirtualSR400()
    device = make_device(driver, sr400, **{"Counter A input": "INPUT 1", "Count time in s": 0.002})
    device.port = sr400

    def expect_error(function, description):
        try:
            function()
        except Exception:
            check(True, description)
        else:
            check(False, description)

    expect_error(lambda: device.set_trigger_level(2.5), "trigger level beyond +-2 V is rejected")
    expect_error(lambda: device.set_discriminator_level("A", 0.4), "discriminator level beyond +-0.3 V is rejected")
    expect_error(lambda: device.set_port_level(1, 12.0), "PORT level beyond +-10 V is rejected")
    expect_error(lambda: device.set_gate_width("A", 1e-9), "gate width below 5 ns is rejected")
    expect_error(lambda: device.set_gate_delay("A", 1.5), "gate delay above 999.2 ms is rejected")
    expect_error(lambda: device.set_number_of_periods(2001), "more than 2000 periods is rejected")
    expect_error(lambda: device.set_dwell_time(1e-3), "a dwell time below 2 ms is rejected")
    expect_error(lambda: device.set_counter_input("A", "INPUT 2"), "INPUT 2 is rejected for counter A")
    expect_error(lambda: device.set_counter_input("T", "INPUT 1"), "INPUT 1 is rejected for counter T")
    expect_error(lambda: device.set_counter_preset("A", 10), "counter A cannot be preset")
    expect_error(lambda: device.set_srq_mask(4), "the GPIB-only SV command is rejected on RS-232")

    check(
        not any(command in ("TL 2.500", "DL 0,0.4000") for command in sr400.log),
        "no out-of-range command reached the instrument",
    )

    # A gate delay set while the gate is in CW mode is ignored by the instrument. That is a
    # warning, not an error: the SR400 accepts it and counts perfectly well, the delay just
    # does nothing. configure() must go through and the user must be told.
    messages = []
    device_cw = make_device(
        driver,
        sr400,
        **{"Gate A mode": "CW", "Gate A delay in s": 1e-6, "Count time in s": 0.002},
    )
    device_cw.message_info = messages.append
    device_cw.configure()
    check(
        any("CW" in str(message) for message in messages),
        f"a gate delay in CW mode is reported as a message, not an error (got {messages})",
    )

    # Likewise a T discriminator level that cannot matter, because T counts the timebase.
    messages = []
    device_t = make_device(
        driver,
        sr400,
        **{"Counter T input": "10 MHz", "Discriminator T level in V": -0.05, "Count time in s": 0.002},
    )
    device_t.message_info = messages.append
    device_t.configure()
    check(
        any("T discriminator" in str(message) for message in messages),
        f"an unused T discriminator level is reported as a message (got {messages})",
    )


def test_instrument_error_reporting(driver):
    print("\n[9] status byte handling")
    sr400 = VirtualSR400()
    device = make_device(driver, sr400, **{"Counter A input": "INPUT 1", "Count time in s": 0.002})
    device.connect()
    device.initialize()
    device.configure()

    sr400.status |= 1 << 7  # command error
    try:
        device.measure()
    except Exception as exc:
        check("command error" in str(exc), f"a command error is raised with a clear message: {exc}")
    else:
        check(False, "a command error is raised")

    # counter overrun: 1e9 counts within the count period
    sr400 = VirtualSR400(rate_input1=1e12)
    device = make_device(
        driver,
        sr400,
        **{"Counter A input": "INPUT 1", "Count time in s": 0.002, "Dwell time in s": 2e-3},
    )
    device.connect()
    device.initialize()
    device.configure()
    try:
        device.measure()
    except Exception as exc:
        check("overran" in str(exc), f"a counter overrun is raised: {exc}")
    else:
        check(False, "a counter overrun is raised")


def test_timeout(driver):
    print("\n[10] timeout while the count period never finishes")
    sr400 = VirtualSR400()
    device = make_device(
        driver,
        sr400,
        **{
            "Counter A input": "INPUT 1",
            "Counter T input": "TRIG",
            "Preset counts (T or B)": 1e6,
            "Dwell time in s": 2e-3,
            "Timeout in s": 1.0,
        },
    )
    sr400.rate["TRIG"] = 1e-6  # practically no trigger pulses -> the period never ends
    device.connect()
    device.initialize()
    device.configure()

    start = time.time()
    try:
        device.measure()
    except Exception as exc:
        duration = time.time() - start
        check("did not finish" in str(exc), f"a timeout is raised: {exc}")
        check(0.9 < duration < 3.0, f"the timeout takes about the configured 1 s (took {duration:.2f} s)")
    else:
        check(False, "a timeout is raised")

    # --- a user stop is not a fault --------------------------------------------------
    # Measured on SweepMe! 1.5.7.9: every stop showed "Exception: The measurement was stopped
    # while waiting for the SR400 count data", although nothing had gone wrong.
    sr400 = VirtualSR400()
    device = make_device(
        driver,
        sr400,
        **{
            "Counter A input": "INPUT 1",
            "Counter T input": "TRIG",
            "Preset counts (T or B)": 1e6,
            "Dwell time in s": 2e-3,
            "Timeout in s": 30.0,
        },
    )
    sr400.rate["TRIG"] = 1e-6  # the period never ends on its own, so only the stop can end it
    device.connect()
    device.initialize()
    device.configure()
    polls = {"n": 0}

    def stop_after_two_polls():
        polls["n"] += 1
        return polls["n"] > 2

    device.is_run_stopped = stop_after_two_polls
    start = time.time()
    try:
        device.measure()
        raised = ""
    except Exception as exc:  # noqa: BLE001
        raised = str(exc)
    duration = time.time() - start
    check(raised == "", f"a user stop during counting raises nothing (raised {raised!r})")
    check(duration < 5.0, f"and ends the wait promptly, not at the timeout (took {duration:.2f} s)")
    check(not sr400.running, "and leaves the SR400 idle rather than counting")
    values = device.call()
    check(
        len(values) == len(device.variables) and all(v != v for v in values),
        f"and the interrupted point is NaN throughout, never a partial count (got {values})",
    )


def test_echo_detection(driver):
    print("\n[11] detection of a wrong COM menu setting (RS-232 ECHO = ON)")
    sr400 = VirtualSR400(echo=True)
    device = make_device(driver, sr400, **{"Count time in s": 0.002})
    try:
        device.connect()
    except Exception as exc:
        check("ECHO" in str(exc), f"echo mode is detected and explained: {exc}")
    else:
        check(False, "echo mode is detected")

    # a silent instrument
    class DeadPort:
        def write(self, command):
            pass

        def read(self):
            return ""

    device = make_device(driver, DeadPort(), **{"Count time in s": 0.002})
    try:
        device.connect()
    except Exception as exc:
        check("No answer" in str(exc), "a silent port produces a helpful message")
    else:
        check(False, "a silent port produces a helpful message")


def test_wrapped_command_layer(driver):
    print("\n[12] round trip of the wrapped command functions")
    sr400 = VirtualSR400()
    device = make_device(driver, sr400, **{"Count time in s": 0.002})

    device.set_counting_mode("A+B for T preset")
    check(device.get_counting_mode() == "A+B for T preset", "counting mode set/read round trip (CM)")

    device.set_counter_input("T", "TRIG")
    check(device.get_counter_input("T") == "TRIG", "counter input set/read round trip (CI)")

    device.set_trigger_slope("Fall")
    check(device.get_trigger_slope() == "Fall", "trigger slope set/read round trip (TS)")

    device.set_trigger_level(-1.234)
    check(math.isclose(device.get_trigger_level(), -1.234, abs_tol=1e-9), "trigger level round trip (TL)")

    device.set_gate_mode("B", "Scan")
    check(device.get_gate_mode("B") == "Scan", "gate mode set/read round trip (GM)")

    device.set_gate_delay_scan_step("B", 1e-6)
    check(math.isclose(device.get_gate_delay_scan_step("B"), 1e-6, rel_tol=1e-6), "gate scan step round trip (GY)")

    device.set_discriminator_scan_step("T", -0.002)
    check(
        math.isclose(device.get_discriminator_scan_step("T"), -0.002, abs_tol=1e-9),
        "discriminator scan step round trip (DY)",
    )

    device.set_port_scan_step(2, 0.25)
    check(math.isclose(device.get_port_scan_step(2), 0.25, abs_tol=1e-9), "PORT scan step round trip (PY)")

    device.set_dwell_time(0.02)
    check(math.isclose(device.get_dwell_time(), 0.02, rel_tol=1e-9), "dwell time round trip (DT)")

    device.set_display_mode("Hold")
    check(device.get_display_mode() == "Hold", "display mode round trip (SD)")

    device.set_dac_source("A-B")
    check(device.get_dac_source() == "A-B", "D/A source round trip (AS)")

    device.set_dac_range(3)
    check(device.get_dac_range() == 3, "D/A range round trip (AM)")

    device.set_rs232_wait(2)
    check(device.get_rs232_wait() == 2, "RS-232 wait interval round trip (SW)")

    device.set_display_message("SWEEPME RUN")
    check(sr400.message == "SWEEPME_RUN", "spaces in the LCD message become underscores (MS)")

    device.set_front_panel_mode("Remote")
    check(sr400.front_panel_mode == 1, "front panel mode was set (MI)")
    device.set_front_panel_mode("Local")

    check(device.get_cursor_position() == 2, "cursor position is read (SC)")
    check(device.get_menu_number() == 1 and device.get_menu_line() == 1, "menu number and line are read (MM/ML)")
    check(device.get_secondary_status_byte() >= 0, "secondary status byte is read (SI)")
    check(device.is_counting() is False, "the counting flag of the secondary status byte is read")
    check(device.get_counter_contents("A") == 0, "counter contents are read while in reset (XA)")

    device.press_key(13)
    device.turn_knob_right()
    device.turn_knob_left()
    device.store_settings(4)
    device.recall_settings(0)
    check(sr400.status & (1 << 7) == 0, "none of the wrapped commands produced a command error")

    # buffer dump after a completed scan
    sr400 = VirtualSR400()
    device = make_device(
        driver,
        sr400,
        **{
            "Measurement mode": "Scan of N periods",
            "Counter A input": "INPUT 1",
            "Count time in s": 0.002,
            "Dwell time in s": 2e-3,
            "Periods per point": 4,
        },
    )
    device.connect()
    device.initialize()
    device.configure()
    device.measure()
    dump = device.dump_scan_buffer("A", 4)
    check(len(dump) == 4 and all(value == 100 for value in dump), f"EA dumps the whole scan buffer (got {dump})")


def test_front_panel_lock_lifecycle(driver):
    print("\n[13] front panel lock is released again")
    sr400 = VirtualSR400()
    device = make_device(
        driver,
        sr400,
        **{"Lock front panel": True, "Counter A input": "INPUT 1", "Count time in s": 0.002},
    )
    device.connect()
    device.initialize()
    device.configure()
    check(sr400.front_panel_mode == 1, "the front panel was locked in configure()")
    device.unconfigure()
    check(sr400.front_panel_mode == 0, "the front panel was returned to local in unconfigure()")


def test_gpib_specifics(driver):
    print("\n[14] GPIB port: RS-232 only commands are skipped")
    sr400 = VirtualSR400()
    device = make_device(
        driver,
        sr400,
        Port="GPIB0::23::INSTR",
        **{"Lock front panel": True, "Counter A input": "INPUT 1", "Count time in s": 0.002},
    )
    device.connect()
    device.initialize()
    device.configure()
    device.measure()

    check(not any(command.startswith("SW") for command in sr400.log), "SW is not sent via GPIB")
    check(not any(command.startswith("MI") for command in sr400.log), "MI is not sent via GPIB")
    device.set_srq_mask(4)
    check(sr400.srq_mask == 4, "the SRQ mask can be set via GPIB")

    # --- REN: the SR400 ignores GPIB commands unless Remote Enable is asserted ----------
    # Measured 2026-11-10 on a GPIB-USB-HS: REN off -> CM timed out with 0 bytes.
    class FakeVisaResource:
        def __init__(self, instrument, fail=False):
            self.instrument = instrument
            self.fail = fail
            self.ren_calls = []  # (mode, number of commands already written)

        def control_ren(self, mode):
            self.ren_calls.append((mode, len(self.instrument.log)))
            if self.fail:
                raise RuntimeError("VI_ERROR_NCIC")

    sr400 = VirtualSR400()
    sr400.port = FakeVisaResource(sr400)
    device = make_device(driver, sr400, Port="GPIB0::23::INSTR", **{"Counter A input": "INPUT 1"})
    device.connect()
    check(
        sr400.port.ren_calls == [(3, 0)],
        f"connect() asserts REN and addresses the SR400 (VI_GPIB_REN_ASSERT_ADDRESS = 3) before "
        f"the first command (got {sr400.port.ren_calls})",
    )

    sr400 = VirtualSR400()
    sr400.port = FakeVisaResource(sr400)
    device = make_device(driver, sr400, **{"Counter A input": "INPUT 1"})
    device.connect()
    check(sr400.port.ren_calls == [], "a COM port never touches REN")

    sr400 = VirtualSR400()
    sr400.port = FakeVisaResource(sr400, fail=True)
    device = make_device(driver, sr400, Port="GPIB0::23::INSTR", **{"Counter A input": "INPUT 1"})
    try:
        device.connect()
        check(False, "a failing REN assertion raises")
    except Exception as exc:
        check(
            "REN" in str(exc) and "VI_ERROR_NCIC" in str(exc),
            f"a failing REN assertion is named, with the bus error: {exc}",
        )
    check(sr400.log == [], "nothing is written after REN could not be asserted")

    # A port object with no VISA resource behind it (Prologix, or this bench) still connects.
    sr400 = VirtualSR400()
    device = make_device(driver, sr400, Port="GPIB0::23::INSTR", **{"Counter A input": "INPUT 1"})
    device.connect()
    check(True, "a GPIB port without control_ren() still connects")

    # --- no device clear on GPIB: the SR400 treats SDC as CL --------------------------
    device = make_device(driver, VirtualSR400(), Port="GPIB0::23::INSTR")
    check(
        device.port_properties.get("clear") is False,
        "pysweepme's port clear is off for GPIB (SDC would reset the SR400 like CL)",
    )
    device = make_device(driver, VirtualSR400(), Port="COM3")
    check(
        device.port_properties.get("clear") is False,
        "pysweepme's port clear is off for COM too: the driver never lets it clear a port",
    )

    # COM: connect() discards stale input itself, so the CM check still sees a clean answer.
    sr400 = VirtualSR400()
    sr400.inject_stale_response("garbage")
    device = make_device(driver, sr400, Port="COM3", **{"Counter A input": "INPUT 1"})
    try:
        device.connect()
        check(True, "a COM connect discards stale input before the CM check")
    except Exception as exc:
        check(False, f"a COM connect discards stale input before the CM check (raised {exc})")
    check(sr400.log[:1] == ["CM"], f"and sends nothing before CM (sent {sr400.log[:3]})")

    # --- Counter A defaults to INPUT 1 -------------------------------------------------
    parameters = driver.Device().set_GUIparameter()
    check(
        parameters["Counter A input"][0] == "INPUT 1",
        f"Counter A input defaults to INPUT 1 (got {parameters['Counter A input']})",
    )

    # --- the GPIB no-answer message is about GPIB, not RS-232 ---------------------------
    class DeadPort:
        def write(self, command):
            pass

        def read(self):
            return ""

    device = make_device(driver, DeadPort(), Port="GPIB0::23::INSTR")
    try:
        device.connect()
        check(False, "a silent GPIB port raises")
    except Exception as exc:
        text = str(exc)
        check(
            "GPIB ADDR" in text and "GPIB0::23::INSTR" in text and "BAUD" not in text,
            f"a silent GPIB port gets a GPIB-specific message: {text}",
        )


def test_reset_at_start(driver):
    print("\n[15] optional instrument reset at the start")
    sr400 = VirtualSR400()
    sr400.trigger_level = 0.5
    device = make_device(
        driver,
        sr400,
        **{"Reset instrument at start": True, "Counter A input": "INPUT 1", "Count time in s": 0.002},
    )
    device.connect()
    device.initialize()
    check("CL" in sr400.log, "CL was sent")
    check(sr400.trigger_level == 2.000, "the instrument returned to its default trigger level")
    device.configure()
    device.measure()
    check(device.call()[0] == 100, "a measurement works after the reset")


def test_ported_gui_options(driver):
    print("\n[16] Baudrate, phase printing, front-panel changes, CH on timeout")
    import io
    import contextlib

    # --- Baudrate reaches the port properties -----------------------------------
    sr400 = VirtualSR400()
    device = make_device(driver, sr400, **{"Baudrate": "19200", "Counter A input": "INPUT 1"})
    check(
        device.port_properties["baudrate"] == 19200,
        f"the Baudrate field reaches port_properties as an int (got "
        f"{device.port_properties['baudrate']!r})",
    )

    # --- 'Print SweepMe! phase' off by default, and silent ----------------------
    sr400 = VirtualSR400()
    device = make_device(driver, sr400, **{"Counter A input": "INPUT 1", "Count time in s": 0.002})
    device.message_info = lambda message: None  # also writes to stdout; not what is under test
    captured = io.StringIO()
    with contextlib.redirect_stdout(captured):
        device.connect()
        device.initialize()
        device.configure()
        run_point(device)
    check(captured.getvalue() == "", f"nothing is printed while the option is off (got {captured.getvalue()!r})")

    # --- ... and names every phase when on --------------------------------------
    sr400 = VirtualSR400()
    device = make_device(
        driver,
        sr400,
        **{"Print SweepMe! phase": True, "Counter A input": "INPUT 1", "Count time in s": 0.002},
    )
    device.message_info = lambda message: None
    captured = io.StringIO()
    with contextlib.redirect_stdout(captured):
        device.connect()
        device.initialize()
        device.configure()
        run_point(device)
        device.unconfigure()
    printed = captured.getvalue()
    for phase in ("connect", "initialize", "configure", "measure", "call", "unconfigure"):
        check(f": {phase}" in printed, f"the '{phase}' phase is printed")
    check("COM3" in printed, "the phase line names the port")

    # --- a front-panel change during the run is reported, not raised ------------
    sr400 = VirtualSR400()
    device = make_device(driver, sr400, **{"Counter A input": "INPUT 1", "Count time in s": 0.002})
    device.connect()
    device.initialize()
    device.configure()
    messages = []
    device.message_info = messages.append
    sr400.status |= 1 << 0  # PARAMETER CHANGED, as if someone turned a knob
    counts = run_point(device)[0]
    check(counts == 100, f"the point still returns data (got {counts})")
    check(
        any("front panel" in str(message) for message in messages),
        f"the front-panel change is reported as a message (got {messages})",
    )

    # --- a timeout leaves the instrument paused rather than counting ------------
    sr400 = VirtualSR400()
    device = make_device(
        driver,
        sr400,
        **{
            "Counter A input": "INPUT 1",
            "Counter T input": "TRIG",
            "Preset counts (T or B)": 1e6,
            "Dwell time in s": 2e-3,
            "Timeout in s": 1.0,
        },
    )
    sr400.rate["TRIG"] = 1e-6
    device.connect()
    device.initialize()
    device.configure()
    try:
        device.measure()
    except Exception:
        pass
    check("CH" in sr400.log, "CH was sent so the SR400 is not left counting after a timeout")
    check(not sr400.running, "the simulator is no longer counting")


def test_measurement_modes(driver):
    print("\n[17] the two measurement modes, and preset read-back without a count time")

    # --- simple mode forces NP 1 and an EXTERNAL dwell --------------------------
    sr400 = VirtualSR400()
    device = make_device(
        driver,
        sr400,
        **{
            "Measurement mode": "Single count period",
            "Counter A input": "INPUT 1",
            "Count time in s": 0.002,
        },
    )
    device.connect()
    device.initialize()
    device.configure()
    counts_a = run_point(device)[0]
    check(sr400.periods == 1, f"NP 1 was programmed (instrument holds {sr400.periods})")
    check(sr400.dwell == 0.0, f"DT 0 selected the EXTERNAL dwell (holds {sr400.dwell})")
    check(counts_a == 100, f"one count period of 2 ms at 50 kHz gives 100 counts (got {counts_a})")
    check(sum(1 for c in sr400.log if c == "CS") == 1, "exactly one CS per point")

    # --- ... and says so when the scan-only fields were set ---------------------
    sr400 = VirtualSR400()
    device = make_device(
        driver,
        sr400,
        **{
            "Measurement mode": "Single count period",
            "Counter A input": "INPUT 1",
            "Count time in s": 0.002,
            "Periods per point": 7,
            "Dwell time in s": 0.5,
        },
    )
    messages = []
    device.message_info = messages.append
    device.connect()
    device.initialize()
    device.configure()
    check(sr400.periods == 1, "'Periods per point' is overridden to 1 in the simple mode")
    check(
        any("Periods per point" in str(m) and "Dwell time in s" in str(m) for m in messages),
        f"both overridden fields are named in one message (got {messages})",
    )

    # --- ... and stays quiet on a default configuration -------------------------
    sr400 = VirtualSR400()
    device = make_device(driver, sr400, **{"Counter A input": "INPUT 1", "Count time in s": 0.002})
    messages = []
    device.message_info = messages.append
    device.connect()
    device.initialize()
    device.configure()
    check(
        not any("only applies" in str(m) for m in messages),
        f"a default single-period configuration produces no override message (got {messages})",
    )
    check(
        device.measurement_mode == "Single count period",
        "the simple mode is the default",
    )

    # --- scan mode runs the instrument's own scan and sums it -------------------
    sr400 = VirtualSR400()
    device = make_device(
        driver,
        sr400,
        **{
            "Measurement mode": "Scan of N periods",
            "Counter A input": "INPUT 1",
            "Count time in s": 0.002,
            "Dwell time in s": 2e-3,
            "Periods per point": 4,
        },
    )
    device.connect()
    device.initialize()
    device.configure()
    counts_a, _, _, _, count_time = run_point(device)
    check(sr400.periods == 4, f"NP 4 was programmed (instrument holds {sr400.periods})")
    check(sr400.dwell == 2e-3, f"the internal dwell was kept (holds {sr400.dwell})")
    check(counts_a == 4 * 100, f"the four periods were summed (got {counts_a})")
    check(
        math.isclose(count_time, 4 * 0.002, rel_tol=1e-9),
        f"the count time covers all four periods (got {count_time})",
    )
    check(sum(1 for c in sr400.log if c == "CS") == 1, "one CS starts the whole scan")

    # --- an unknown mode is refused rather than silently treated as one of them -
    sr400 = VirtualSR400()
    device = make_device(driver, sr400, **{"Counter A input": "INPUT 1"})
    device.measurement_mode = "Whatever"
    try:
        device._apply_measurement_mode()
    except Exception as exc:
        check("Whatever" in str(exc), f"an unknown measurement mode is refused: {exc}")
    else:
        check(False, "an unknown measurement mode is refused")

    # --- the preset rounding is reported even with no Count time column ---------
    sr400 = VirtualSR400()
    sr400.rate["TRIG"] = 1e5
    device = make_device(
        driver,
        sr400,
        **{
            "Counter A input": "INPUT 1",
            "Counter T input": "TRIG",
            "Preset counts (T or B)": 1.5e6,
        },
    )
    messages = []
    device.message_info = messages.append
    device.connect()
    device.initialize()
    device.configure()
    check(
        math.isnan(device.actual_count_time),
        "the count time is unknown when T does not count the timebase",
    )
    check(
        any("rounded to" in str(m) and "counts" in str(m) for m in messages),
        f"the silent CP rounding of the preset is now reported (got {messages})",
    )


def test_latency_detection(driver):
    print("\n[18] USB-serial latency timer detection")

    # --- the lookup is incapable of raising, whatever the port string ----------
    device = driver.Device()
    for port in ("COM3", "/dev/ttyUSB0", "ttyUSB9", "GPIB0::23::INSTR", ""):
        device.port_string = port
        try:
            value = device._get_com_latency_timer()
            ok = value is None or isinstance(value, int)
        except Exception:
            ok = False
        check(ok, f"the latency lookup returns None or an int for {port!r} and does not raise")

    # --- a high value warns once, and only once -------------------------------
    sr400 = VirtualSR400()
    device = make_device(driver, sr400, **{"Counter A input": "INPUT 1"})
    device._get_com_latency_timer = lambda: 16
    messages = []
    device.message_info = messages.append
    device.connect()
    check(device._latency_warning_shown, "a 16 ms latency timer sets the warning flag")
    check(
        any("16 ms" in str(m) and "replug" in str(m).lower() for m in messages),
        f"the warning names the value and the replug requirement (got {len(messages)} messages)",
    )
    device.connect()
    check(len(messages) == 1, f"the warning is emitted once per run (got {len(messages)})")

    # --- a low value says nothing ---------------------------------------------
    sr400 = VirtualSR400()
    device = make_device(driver, sr400, **{"Counter A input": "INPUT 1"})
    device._get_com_latency_timer = lambda: 1
    messages = []
    device.message_info = messages.append
    device.connect()
    check(not device._latency_warning_shown, "a 1 ms latency timer does not warn")
    check(messages == [], f"nothing is reported for a good value (got {messages})")

    # --- an unknown value is not treated as bad, and not as good either --------
    sr400 = VirtualSR400()
    device = make_device(driver, sr400, **{"Counter A input": "INPUT 1"})
    device._get_com_latency_timer = lambda: None
    messages = []
    device.message_info = messages.append
    device.connect()
    check(messages == [], f"an unknown latency timer produces no scary message (got {messages})")

    # --- a raising lookup must not break connect() ----------------------------
    def boom():
        raise RuntimeError("registry on fire")

    sr400 = VirtualSR400()
    device = make_device(driver, sr400, **{"Counter A input": "INPUT 1"})
    device._get_com_latency_timer = boom
    try:
        device.connect()
        check(True, "a raising latency lookup does not break connect()")
    except Exception as exc:
        check(False, f"a raising latency lookup does not break connect() (raised {exc})")

    # --- GPIB never triggers the check ----------------------------------------
    sr400 = VirtualSR400()
    device = make_device(driver, sr400, **{"Port": "GPIB0::23::INSTR", "Counter A input": "INPUT 1"})
    device._get_com_latency_timer = lambda: 16
    messages = []
    device.message_info = messages.append
    device.connect()
    check(not device._latency_warning_shown, "a GPIB port never warns about a latency timer")


def test_latency_actions(driver):
    print("\n[19] the two latency actions send the instrument nothing")

    check(
        driver.Device.actions[:2] == ["report_com_port_latency", "reduce_com_port_latency"],
        f"both latency actions are declared first (got {driver.Device.actions})",
    )

    for port in ("COM3", "GPIB0::23::INSTR", ""):
        for name in ("report_com_port_latency", "reduce_com_port_latency"):
            sr400 = VirtualSR400()
            device = make_device(driver, sr400, **{"Port": port, "Counter A input": "INPUT 1"})
            boxes = []
            device.message_box = boxes.append
            action = getattr(device, name, None)
            check(callable(action), f"{name} resolves to a callable")
            traffic_before = len(sr400.log)
            try:
                action()
                raised = False
            except Exception:
                raised = True
            check(not raised, f"{name} does not raise for port {port!r}")
            check(len(boxes) >= 1, f"{name} says something for port {port!r}")
            # I4: a diagnostic must be safe to click mid-experiment.
            check(
                len(sr400.log) == traffic_before,
                f"{name} sends the instrument nothing for port {port!r}",
            )

    # the report names the port when there is one
    sr400 = VirtualSR400()
    device = make_device(driver, sr400, **{"Counter A input": "INPUT 1"})
    device._get_com_latency_timer = lambda: 16
    boxes = []
    device.message_box = boxes.append
    device.report_com_port_latency()
    check(any("COM3" in str(t) for t in boxes), f"the report names the port (got {boxes})")

    # an already-low value is left alone
    sr400 = VirtualSR400()
    device = make_device(driver, sr400, **{"Counter A input": "INPUT 1"})
    device._get_com_latency_timer = lambda: 1
    boxes = []
    device.message_box = boxes.append
    device.reduce_com_port_latency()
    check(
        any("already" in str(t) for t in boxes),
        f"an already-low latency timer is not rewritten (got {boxes})",
    )


def test_batched_readout(driver):
    print("\n[20] batched readout equals unbatched readout, and fails safe")

    def one_point(periods, batched, seed_rate=5.0e4):
        sr400 = VirtualSR400(rate_input1=seed_rate)
        device = make_device(
            driver,
            sr400,
            **{
                "Measurement mode": "Scan of N periods",
                "Counter A input": "INPUT 1",
                "Counter B input": "INPUT 1",
                "Count time in s": 0.002,
                "Dwell time in s": 2e-3,
                "Periods per point": periods,
                "Fast readout (batch queries)": batched,
            },
        )
        device.connect()
        device.initialize()
        device.configure()
        writes_before = len(sr400.log)
        values = run_point(device)
        return values, sr400, len(sr400.log) - writes_before

    # --- equivalence: this is the test that actually matters -------------------
    for periods in (1, 2, 10, 17, 33):
        plain, _, plain_writes = one_point(periods, False)
        fast, sr_fast, fast_writes = one_point(periods, True)
        check(
            plain == fast,
            f"{periods} periods: batched and unbatched agree ({plain} vs {fast})",
        )
        if periods > 1:
            check(
                fast_writes < plain_writes,
                f"{periods} periods: batching cuts round trips ({fast_writes} < {plain_writes})",
            )

    # --- chunking respects the buffer limits ----------------------------------
    _, sr400, _ = one_point(33, True)
    device = driver.Device()
    long_lines = [c for c in sr400.log if len(c) > device.BATCH_MAX_LINE_CHARS]
    crowded = [c for c in sr400.log if c.count(";") + 1 > device.BATCH_MAX_COMMANDS]
    check(not long_lines, f"no command line exceeds {device.BATCH_MAX_LINE_CHARS} chars")
    check(not crowded, f"no line carries more than {device.BATCH_MAX_COMMANDS} commands")
    check(not sr400.buffer_overflowed, "the output buffer never overflowed")
    check(not sr400.line_overflowed, "no command line was long enough to be truncated")

    # --- stale bytes are detected, not paired up ------------------------------
    sr400 = VirtualSR400()
    device = make_device(
        driver,
        sr400,
        **{
            "Measurement mode": "Scan of N periods",
            "Counter A input": "INPUT 1",
            "Count time in s": 0.002,
            "Dwell time in s": 2e-3,
            "Periods per point": 4,
            "Fast readout (batch queries)": True,
        },
    )
    messages = []
    device.message_info = messages.append
    device.connect()
    device.initialize()
    device.configure()

    # The stale byte has to appear immediately before the batched read, not before the status
    # poll -- otherwise it desynchronises the status byte instead, which is a different failure.
    original_batched = device._query_batched
    injected = {"done": False}

    def inject_then_batch(queries):
        if not injected["done"]:
            injected["done"] = True
            sr400.inject_stale_response("999999")
        return original_batched(queries)

    device._query_batched = inject_then_batch
    values = run_point(device)
    check(injected["done"], "the stale response was injected before a batched read")
    check(values[0] == 4 * 100, f"the desynchronised point still returns correct data ({values[0]})")
    check(not device.batch_queries, "fast readout disabled itself after the desync")
    check(
        any("fast readout" in str(m).lower() for m in messages),
        f"the fallback is reported to the user (got {messages})",
    )

    # --- a dead link raises, naming the offending line ------------------------
    class SilentPort(VirtualSR400):
        def read(self):
            return ""

    sr400 = SilentPort()
    device = make_device(driver, sr400, **{"Counter A input": "INPUT 1"})
    device.batch_queries = True
    device.periods = 3
    device.counter_b_is_readable = False
    try:
        device._query_batched(device._scan_point_queries())
        check(False, "a port that answers nothing raises")
    except Exception as exc:
        check("QA 1" in str(exc), f"the failure names the command line: {exc}")

    # --- over-long batches are refused before anything is written -------------
    sr400 = VirtualSR400()
    device = make_device(driver, sr400, **{"Counter A input": "INPUT 1"})
    before = len(sr400.log)
    try:
        device._query_batch([f"QA {i}" for i in range(1, device.BATCH_MAX_COMMANDS + 5)])
        check(False, "an oversized batch is refused")
    except Exception:
        check(True, "an oversized batch is refused")
    check(len(sr400.log) == before, "the oversized batch was not written to the port")

    # --- configuration and status polling are never batched -------------------
    _, sr400, _ = one_point(10, True)
    config_lines = sr400.log[: sr400.log.index("CS")]
    check(
        not any(";" in line for line in config_lines),
        "no configuration command line was batched",
    )
    check(
        not any(";" in line and "SS" in line for line in sr400.log),
        "the status poll was never batched",
    )


def test_count_time_planner(driver):
    print("\n[21] the count-time planner, as a pure function")

    check(len(driver.representable_presets()) == 108, "there are 108 representable T presets")
    check(driver.representable_presets()[0] == 9 * 10**11, "the largest preset is 9E11")
    check(driver.representable_presets()[-1] == 1, "the smallest preset is 1")

    # (total, periods, count_time, is_exact) -- every case named in the specification.
    table = [
        (1.5, 3, 0.5, True),
        (2.5, 5, 0.5, True),
        (1.2, 2, 0.6, True),
        (0.15, 3, 0.05, True),
        (7.7, 11, 0.7, True),
        (0.5, 1, 0.5, True),
        (1e-4, 1, 1e-4, True),
        (3.4e-3, 1, 3e-3, False),
        (1.5e-6, 1, 2e-6, False),
        # Exact splits that exceed the soft cap on periods. These are the is_exact labelling
        # cases: the plan is rejected by the *preference* and then chosen by the fallback, so
        # a driver that derived is_exact from which branch ran would get both of these wrong.
        (0.999, 111, 9e-3, True),
        (1234.0, 617, 2.0, True),
    ]

    for total, periods, count_time, is_exact in table:
        plan = driver.plan_count_time(total)
        check(
            plan.periods == periods,
            f"{total:g} s splits into {periods} periods (got {plan.periods})",
        )
        check(
            math.isclose(plan.count_time, count_time, rel_tol=1e-9),
            f"{total:g} s uses a {count_time:g} s count period (got {plan.count_time:g})",
        )
        check(
            plan.is_exact is is_exact,
            f"{total:g} s is labelled is_exact={is_exact} (got {plan.is_exact})",
        )
        if is_exact:
            check(
                math.isclose(plan.total_time, total, rel_tol=1e-9),
                f"{total:g} s is reached exactly (got {plan.total_time:g})",
            )

    # is_exact must come from comparing the achieved total against the request, never from
    # which branch produced the candidate. These two are the cases that tell the difference:
    # each has an exact split that the *preference* rejects for exceeding the soft cap, and
    # that the fallback then chooses anyway. Assert the over-cap condition explicitly, or a
    # future change to soft_max_periods would quietly stop exercising the distinction and the
    # mislabelling it guards against is silent.
    for total, periods in ((0.999, 111), (1234.0, 617)):
        plan = driver.plan_count_time(total)
        check(
            plan.periods == periods > 100,
            f"{total:g} s needs {periods} periods, above the soft cap of 100 "
            f"(got {plan.periods})",
        )
        check(
            plan.is_exact,
            f"{total:g} s is still labelled exact despite exceeding the soft cap",
        )

    # The rejected-exact note has to say what exactness would have cost, or it is not
    # actionable -- 3.4 ms is reachable as 17 x 0.2 ms, at a duty cycle nobody wants.
    plan = driver.plan_count_time(3.4e-3)
    check("17" in plan.note and "duty" in plan.note, f"the note prices the exact split: {plan.note}")

    # An exact split that is merely large says so rather than claiming it was rejected.
    plan = driver.plan_count_time(0.999)
    check(plan.is_exact and "111" in plan.note, f"the over-cap note explains itself: {plan.note}")

    # EXTERNAL dwell has no inter-period gap, so duty never constrains the choice.
    plan = driver.plan_count_time(3.4e-3, dwell=0.0)
    check(
        plan.is_exact and plan.periods == 17 and plan.duty_cycle == 1.0,
        f"with EXTERNAL dwell the exact 17-period split is taken (got {plan})",
    )

    # Duty is real arithmetic, not a label.
    plan = driver.plan_count_time(1.5)
    expected_duty = 1.5 / (1.5 + 2 * 2e-3)
    check(
        math.isclose(plan.duty_cycle, expected_duty, rel_tol=1e-9),
        f"duty is live/(live+dead) (got {plan.duty_cycle:.6f}, expected {expected_duty:.6f})",
    )
    check(driver.plan_count_time(0.5).duty_cycle == 1.0, "a single period is 100% duty")

    # Guard rails.
    for bad in (0.0, -1.0, float("nan"), float("inf")):
        try:
            driver.plan_count_time(bad)
            check(False, f"a total of {bad} is refused")
        except ValueError:
            check(True, f"a total of {bad} is refused")
        except Exception as exc:
            check(False, f"a total of {bad} is refused with ValueError (got {type(exc).__name__})")

    # Never exceed the instrument's own NP limit, whatever is asked for.
    plan = driver.plan_count_time(1e-3, min_duty=0.0, soft_max_periods=100000)
    check(plan.periods <= 2000, f"the plan never exceeds NP 2000 (got {plan.periods})")

    # --- several duty floors, planned together ---------------------------------
    check(driver.DUTY_TIERS == (0.5, 0.8, 0.99), f"the tiers are 50/80/99% (got {driver.DUTY_TIERS})")

    # The driver's default floor is 80%: typing a count time and starting should not need a
    # decision about dead time.
    plan_default = driver.plan_count_time(0.015)
    plan_80 = driver.plan_count_time(0.015, min_duty=0.8)
    check(
        (plan_default.periods, plan_default.count_time) == (plan_80.periods, plan_80.count_time),
        "the default duty floor is 80%",
    )

    # A plan at *every* tier, for every total -- that is what makes the 99% option always
    # offerable rather than something that can fail. A single period is 100% duty by
    # definition, so the fallback can always satisfy any floor.
    for total in (1.6, 1.5, 0.15, 0.05, 0.015, 3.4e-3, 1.5e-6, 1234.0):
        tiers = driver.plan_count_time_tiers(total)
        check(
            set(tiers) == set(driver.DUTY_TIERS),
            f"{total:g} s yields a plan at every tier (got {sorted(tiers)})",
        )
        for floor, plan in tiers.items():
            check(
                plan.duty_cycle >= floor - 1e-12,
                f"{total:g} s at a {floor:.0%} floor actually meets it "
                f"(got {plan.duty_cycle:.1%})",
            )
            check(
                1 <= plan.periods <= 2000,
                f"{total:g} s at a {floor:.0%} floor stays within NP limits",
            )

    # One enumeration, so a tier read together must equal the same tier read alone.
    tiers = driver.plan_count_time_tiers(0.15)
    check(
        tiers[0.99] == driver.plan_count_time(0.15, min_duty=0.99),
        "a tier from the joint pass equals the same floor planned on its own",
    )

    # Tightening the floor can only cost accuracy, never improve it. 0.15 s is exactly
    # 3 x 0.05 s at 97.4% duty, which a 99% floor refuses.
    tiers = driver.plan_count_time_tiers(0.15)
    check(tiers[0.8].is_exact and tiers[0.8].periods == 3, "0.15 s is exact at an 80% floor")
    check(
        not tiers[0.99].is_exact and tiers[0.99].periods == 1,
        f"a 99% floor gives up exactness on 0.15 s (got {tiers[0.99]})",
    )
    check(
        tiers[0.99].duty_cycle >= tiers[0.8].duty_cycle,
        "the tighter floor does deliver the better duty it was asked for",
    )


def test_auto_split_mode(driver):
    print("\n[22] auto-split mode against the instrument, and the Per-period remedy")

    # --- the plan is what actually gets programmed ------------------------------
    sr400 = VirtualSR400()
    device = make_device(
        driver,
        sr400,
        **{
            "Count time mode": "Total live time (auto-split)",
            "Counter A input": "10 MHz",
            "Count time in s": 1.5,
        },
    )
    messages = []
    device.message_info = messages.append
    device.connect()
    device.initialize()
    device.configure()

    check(sr400.periods == 3, f"NP 3 was programmed (instrument holds {sr400.periods})")
    check(
        math.isclose(sr400.preset[2] / 1e7, 0.5, rel_tol=1e-9),
        f"the T preset is a 0.5 s count period (holds {sr400.preset[2] / 1e7} s)",
    )
    check(sr400.dwell == 2e-3, f"the dwell was set to the 2 ms minimum (holds {sr400.dwell})")
    check(
        device.measurement_mode == "Scan of N periods",
        "a multi-period plan promotes the measurement mode to the scan",
    )

    counts_a, _, rate_a, _, count_time = run_point(device)
    # 10 MHz for 0.5 s per period, three periods.
    check(counts_a == 3 * 5e6, f"the summed counts are periods x per-period counts (got {counts_a})")
    check(
        math.isclose(count_time, 1.5, rel_tol=1e-9),
        f"the reported Count time is the achieved total (got {count_time})",
    )
    check(math.isclose(rate_a, 1e7, rel_tol=1e-6), f"the rate is still 10 MHz (got {rate_a})")
    check(
        any("3 x 0.5" in str(m) and "exactly" in str(m) for m in messages),
        f"the plan is reported once, with the split and its exactness (got {messages})",
    )

    # --- a total that needs no split leaves the mode alone ----------------------
    sr400 = VirtualSR400()
    device = make_device(
        driver,
        sr400,
        **{
            "Count time mode": "Total live time (auto-split)",
            "Counter A input": "10 MHz",
            "Count time in s": 0.5,
        },
    )
    device.connect()
    device.initialize()
    device.configure()
    check(sr400.periods == 1, "an already-representable total stays at NP 1")
    check(
        device.measurement_mode == "Single count period",
        "a single-period plan does not promote the measurement mode",
    )
    check(run_point(device)[0] == 5e6, "the single-period auto-split point still counts")

    # --- an inexact total is reported as inexact --------------------------------
    sr400 = VirtualSR400()
    device = make_device(
        driver,
        sr400,
        **{
            "Count time mode": "Total live time (auto-split)",
            "Counter A input": "10 MHz",
            "Count time in s": 3.4e-3,
        },
    )
    messages = []
    device.message_info = messages.append
    device.connect()
    device.initialize()
    device.configure()
    check(
        any("closest reachable" in str(m) for m in messages),
        f"an inexact auto-split says so rather than implying exactness (got {messages})",
    )

    # --- EXTERNAL dwell survives auto-split ------------------------------------
    sr400 = VirtualSR400()
    device = make_device(
        driver,
        sr400,
        **{
            "Count time mode": "Total live time (auto-split)",
            "Counter A input": "10 MHz",
            "Count time in s": 1.5,
            "Dwell time in s": 0,
        },
    )
    messages = []
    device.message_info = messages.append
    device.connect()
    device.initialize()
    device.configure()
    check(sr400.dwell == 0.0, f"an EXTERNAL dwell is kept, not raised to 2 ms (holds {sr400.dwell})")
    check(sr400.periods == 3, "the split is unchanged by the EXTERNAL dwell")
    check(
        any("EXTERNAL" in str(m) for m in messages),
        f"the message drops the duty term for an EXTERNAL dwell (got {messages})",
    )
    check(run_point(device)[0] == 3 * 5e6, "the EXTERNAL-dwell auto-split point counts correctly")

    # --- Per period is untouched, and now names the remedy ---------------------
    sr400 = VirtualSR400()
    device = make_device(
        driver,
        sr400,
        **{"Counter A input": "10 MHz", "Count time in s": 1.5},
    )
    messages = []
    device.message_info = messages.append
    device.connect()
    device.initialize()
    device.configure()
    check(sr400.periods == 1, "Per period mode does not split anything")
    check(
        math.isclose(sr400.preset[2] / 1e7, 2.0, rel_tol=1e-9),
        f"Per period still rounds 1.5 s to the nearest settable 2 s (holds {sr400.preset[2] / 1e7})",
    )
    warning = " ".join(str(m) for m in messages)
    check("not a settable count period" in warning, "the rounding is still reported")
    check(
        "3 count periods of 0.5" in warning,
        f"the warning names the exact decomposition (got {warning!r})",
    )
    check(
        "auto-split" in warning,
        "the warning names the mode that would do it for you",
    )

    # A representable per-period count time must stay silent.
    sr400 = VirtualSR400()
    device = make_device(driver, sr400, **{"Counter A input": "10 MHz", "Count time in s": 0.5})
    messages = []
    device.message_info = messages.append
    device.connect()
    device.initialize()
    device.configure()
    check(
        not any("settable count period" in str(m) for m in messages),
        f"a representable count time produces no rounding warning (got {messages})",
    )

    # --- 1.6 s, the case this mode exists for ---------------------------------
    sr400 = VirtualSR400()
    device = make_device(
        driver,
        sr400,
        **{
            "Count time mode": "Total live time (auto-split)",
            "Counter A input": "10 MHz",
            "Count time in s": 1.6,
        },
    )
    device.connect()
    device.initialize()
    device.configure()
    check(sr400.periods == 2, f"1.6 s runs as 2 periods (instrument holds {sr400.periods})")
    check(
        math.isclose(sr400.preset[2] / 1e7, 0.8, rel_tol=1e-9),
        f"1.6 s uses a 0.8 s count period (holds {sr400.preset[2] / 1e7})",
    )
    counts_a, _, _, _, count_time = run_point(device)
    check(counts_a == 2 * 8e6, f"1.6 s of 10 MHz is 1.6e7 counts (got {counts_a})")
    check(math.isclose(count_time, 1.6, rel_tol=1e-9), f"1.6 s is reported back (got {count_time})")

    # --- the >99% duty tick box ------------------------------------------------
    def configured(total, high_duty):
        sr = VirtualSR400()
        dev = make_device(
            driver,
            sr,
            **{
                "Count time mode": "Total live time (auto-split)",
                "Quantize count time to >99% duty cycle": high_duty,
                "Counter A input": "10 MHz",
                "Count time in s": total,
            },
        )
        notes = []
        dev.message_info = notes.append
        dev.connect()
        dev.initialize()
        dev.configure()
        return dev, sr, notes

    device, sr400, messages = configured(0.15, False)
    check(sr400.periods == 3, f"0.15 s is 3 x 0.05 s at the default floor (holds {sr400.periods})")
    check(
        any("80%" in str(m) for m in messages),
        f"the message names the duty floor in use (got {messages})",
    )
    check(
        any("99%" in str(m) and "instead" in str(m) for m in messages),
        f"the message prices the other floor (got {messages})",
    )

    device, sr400, messages = configured(0.15, True)
    check(sr400.periods == 1, f"ticking >99% duty gives 1 period (holds {sr400.periods})")
    check(
        math.isclose(sr400.preset[2] / 1e7, 0.2, rel_tol=1e-9),
        f"and a 0.2 s count period (holds {sr400.preset[2] / 1e7})",
    )
    check(
        any("99%" in str(m) and "closest reachable" in str(m) for m in messages),
        f"the >99% plan admits it is no longer exact (got {messages})",
    )
    check(
        any("80%" in str(m) and "exact" in str(m) for m in messages),
        f"and says the 80% floor would have been exact (got {messages})",
    )

    # 1.6 s is exact at both floors, so the tick box changes nothing and says nothing about it.
    device, sr400, messages = configured(1.6, True)
    check(sr400.periods == 2, "1.6 s is 2 x 0.8 s at a 99% floor too")
    check(
        not any("instead" in str(m) for m in messages),
        f"no trade-off is reported when there is none (got {messages})",
    )

    # --- auto-split refuses where a preset is not a time -----------------------
    for overrides, fragment in (
        ({"Counter T input": "TRIG"}, "Counter T input"),
        ({"Counter T input": "INPUT 2"}, "Counter T input"),
        ({"Count mode": "A for B preset", "Counter B input": "INPUT 2"}, "A for B preset"),
    ):
        sr400 = VirtualSR400()
        device = make_device(
            driver,
            sr400,
            **{
                "Count time mode": "Total live time (auto-split)",
                "Counter A input": "10 MHz",
                "Count time in s": 1.6,
                **overrides,
            },
        )
        device.connect()
        device.initialize()
        try:
            device.configure()
            check(False, f"auto-split is refused for {overrides}")
        except Exception as exc:
            check(
                fragment in str(exc) and "Per period" in str(exc),
                f"auto-split refusal names the cause and the remedy: {exc}",
            )

    # Per period is unaffected by the same configurations.
    sr400 = VirtualSR400()
    sr400.rate["TRIG"] = 1e5
    device = make_device(
        driver,
        sr400,
        **{"Counter A input": "10 MHz", "Counter T input": "TRIG", "Preset counts (T or B)": 1e5},
    )
    device.connect()
    device.initialize()
    device.configure()
    check(True, "Per period still configures with counter T off the timebase")

    # --- an unknown mode is refused -------------------------------------------
    sr400 = VirtualSR400()
    device = make_device(driver, sr400, **{"Counter A input": "10 MHz"})
    device.count_time_mode = "Whatever"
    try:
        device._apply_count_time_mode()
        check(False, "an unknown count time mode is refused")
    except Exception as exc:
        check("Whatever" in str(exc), f"an unknown count time mode is refused: {exc}")


def _report_dir(tmpdir):
    """Where the self-test reports land when get_folder() returns tmpdir for every identifier:
    DATADEVICES first, in a subfolder named after the driver."""
    return os.path.join(tmpdir, "Logger-Stanford_SR400")


def _instrument_snapshot(sr400):
    """Every piece of instrument state a self-test could plausibly disturb.

    Compared before and after to prove the restore is complete. Deliberately includes the PORT
    levels, which may be driving apparatus, and the RS-232 terminator, which must never be
    touched at all.
    """
    return {
        "counting_mode": sr400.counting_mode,
        "counter_input": dict(sr400.counter_input),
        "preset": dict(sr400.preset),
        "periods": sr400.periods,
        "scan_end_mode": sr400.scan_end_mode,
        "dwell": sr400.dwell,
        "dac_source": sr400.dac_source,
        "dac_range": sr400.dac_range,
        "display_mode": sr400.display_mode,
        "trigger_slope": sr400.trigger_slope,
        "trigger_level": sr400.trigger_level,
        "disc_slope": dict(sr400.disc_slope),
        "disc_mode": dict(sr400.disc_mode),
        "disc_level": dict(sr400.disc_level),
        "disc_step": dict(sr400.disc_step),
        "port_mode": dict(sr400.port_mode),
        "port_level": dict(sr400.port_level),
        "port_step": dict(sr400.port_step),
        "gate_mode": dict(sr400.gate_mode),
        "gate_delay": dict(sr400.gate_delay),
        "gate_width": dict(sr400.gate_width),
        "gate_step": dict(sr400.gate_step),
        "front_panel_mode": sr400.front_panel_mode,
        "srq_mask": sr400.srq_mask,
    }


def _selftest_device(driver, sr400, tmpdir, **over):
    device = make_device(driver, sr400, **over)
    device.get_folder = lambda identifier: tmpdir
    device._get_com_latency_timer = lambda: None
    return device


def test_self_test_actions(driver):
    print("\n[23] the two hardware self-test actions, against the simulator")

    import tempfile

    tmpdir = tempfile.mkdtemp(prefix="sr400_selftest_")

    # The self-test's real timings are what matter on hardware -- the known-answer test is the
    # manual's own one-second check. Against this simulator the counts are exact by
    # construction whatever the duration, and the simulator advances on wall-clock time, so
    # running them full length would add ~15 s to a suite meant to run after every edit.
    # Shrink the durations, keep every code path.
    st = driver.selftest
    saved_timings = (
        st.KNOWN_ANSWER_SECONDS,
        st.TIMEBASE_REPEATS,
        st.SCAN_COUNT_TIME,
        st.EXTERNAL_COUNT_TIME,
        st.THROUGHPUT_QUERIES,
        st.TRIGGER_PROBE_TIMEOUT,
    )
    st.KNOWN_ANSWER_SECONDS = 0.01
    st.TIMEBASE_REPEATS = 2
    st.SCAN_COUNT_TIME = 0.002
    st.EXTERNAL_COUNT_TIME = 0.002
    st.THROUGHPUT_QUERIES = 10

    check(
        driver.selftest is not None,
        f"the sibling selftest module loaded ({driver._selftest_error or 'no error'})",
    )
    for name in ("run_self_test", "run_self_test_loopback"):
        check(name in driver.Device.actions, f"{name} is declared as an action")
        check(callable(getattr(driver.Device, name, None)), f"{name} is callable")

    # --- tier 1 completes, and restores everything -----------------------------
    sr400 = VirtualSR400()
    device = _selftest_device(driver, sr400, tmpdir, **{"Counter A input": "10 MHz"})
    boxes = []
    device.message_box = boxes.append
    device.message_info = lambda message: None

    before = _instrument_snapshot(sr400)
    try:
        device.run_self_test()
        raised = ""
    except Exception as exc:
        raised = str(exc)
    check(not raised, f"tier 1 completes without raising ({raised or 'clean'})")
    check(len(boxes) == 1, f"tier 1 reports exactly one message_box (got {len(boxes)})")
    check("checks passed" in boxes[-1], f"the summary carries a pass count: {boxes[-1][:60]}...")

    after = _instrument_snapshot(sr400)
    differing = {k: (before[k], after[k]) for k in before if before[k] != after[k]}
    check(not differing, f"tier 1 restored every setting it touched (differing: {differing})")

    # --- the forbidden commands ------------------------------------------------
    for command in ("SE", "ST", "RC"):
        offenders = [c for c in sr400.log if c.split()[0].upper() == command]
        check(not offenders, f"tier 1 never sent {command} (found {offenders[:3]})")

    # --- the report file is written and carries the deliverable ---------------
    reports = [f for f in os.listdir(_report_dir(tmpdir)) if f.startswith("SR400_self_test_tier_1")]
    check(bool(reports), f"tier 1 wrote a report file (found {reports})")
    check(
        os.path.isdir(_report_dir(tmpdir)),
        "reports go to DATADEVICES/<driver>, not SweepMe!'s per-run TEMP folder",
    )
    if reports:
        text = open(os.path.join(_report_dir(tmpdir), reports[0])).read()
        check("response formats" in text, "the report contains the raw response-format table")
        # The value depends on the count time, which the bench shrinks -- so assert the
        # format. Whether CP answers "1E5" or "100000" is exactly what this table exists to
        # record, and either is a valid raw response to capture.
        cp_row = [l for l in text.splitlines() if l.strip().startswith("CP 2")]
        check(bool(cp_row), f"the table has a CP 2 row (got {cp_row})")
        check(
            bool(cp_row) and re.search(r"'\s*[-+0-9.eE]+\s*'", cp_row[0]) is not None,
            f"and it shows the raw response quoted verbatim: {cp_row[0].strip() if cp_row else ''}",
        )
        check("No instrument storage slot was used" in text, "the report states no slot was used")
        check("throughput" in text, "the report contains the measured throughput section")
        check(
            "Counter B is untestable here" in text,
            "the report explains why tier 2 exists",
        )

    # --- refuses while the instrument is counting ------------------------------
    sr400 = VirtualSR400()
    device = _selftest_device(driver, sr400, tmpdir, **{"Counter A input": "10 MHz"})
    boxes = []
    device.message_box = boxes.append
    device.message_info = lambda message: None
    sr400.secondary |= 1 << 2  # the SR400 reports itself as counting
    traffic_before = len(sr400.log)
    device.run_self_test()
    check(
        any("counting" in str(t) for t in boxes),
        f"tier 1 refuses while the SR400 is counting (got {boxes})",
    )
    # One status query to find out, and nothing else.
    changed = [c for c in sr400.log[traffic_before:] if not c.startswith("SI")]
    check(not changed, f"and it changed nothing while refusing (sent {changed})")

    # --- and while a run is being stopped -------------------------------------
    sr400 = VirtualSR400()
    device = _selftest_device(driver, sr400, tmpdir, **{"Counter A input": "10 MHz"})
    boxes = []
    device.message_box = boxes.append
    device.message_info = lambda message: None
    device.is_run_stopped = lambda: True
    device.run_self_test()
    check(
        any("being stopped" in str(t) for t in boxes),
        f"tier 1 refuses while a run is being stopped (got {boxes})",
    )

    # --- tier 2 stops cleanly with no cable ----------------------------------
    sr400 = VirtualSR400()
    sr400.rate["INPUT 2"] = 0.0  # nothing on INPUT 2: the loopback cable is absent
    device = _selftest_device(driver, sr400, tmpdir, **{"Counter A input": "10 MHz"})
    boxes = []
    device.message_box = boxes.append
    device.message_info = lambda message: None
    before = _instrument_snapshot(sr400)
    try:
        device.run_self_test_loopback()
        raised = ""
    except Exception as exc:
        raised = str(exc)
    check(not raised, f"tier 2 completes without raising when the cable is absent ({raised or 'clean'})")
    joined = " ".join(str(t) for t in boxes)
    check("DISC output" in joined, f"it names the two BNCs to join (got {joined[:120]})")
    check(
        "INPUT 2" in joined,
        "it names the destination input, not just 'connect a cable'",
    )
    after = _instrument_snapshot(sr400)
    differing = {k: (before[k], after[k]) for k in before if before[k] != after[k]}
    check(not differing, f"and it restored everything before stopping (differing: {differing})")

    # --- tier 2 passes with the cable modelled -------------------------------
    sr400 = VirtualSR400(loopback=True)
    device = _selftest_device(driver, sr400, tmpdir, **{"Counter A input": "10 MHz"})
    boxes = []
    device.message_box = boxes.append
    device.message_info = lambda message: None
    before = _instrument_snapshot(sr400)
    try:
        device.run_self_test_loopback()
        raised = ""
    except Exception as exc:
        raised = str(exc)
    check(not raised, f"tier 2 completes without raising with the cable ({raised or 'clean'})")
    check(
        "0 checks passed" not in boxes[-1] and "checks passed" in boxes[-1],
        f"tier 2 ran its checks with the cable present: {boxes[-1][:80]}...",
    )
    check(
        "Failed:" not in boxes[-1],
        f"and every tier-2 check passed against the simulator: {boxes[-1][:200]}",
    )

    after = _instrument_snapshot(sr400)
    differing = {k: (before[k], after[k]) for k in before if before[k] != after[k]}
    check(not differing, f"tier 2 restored every setting including PORT levels (differing: {differing})")

    for command in ("SE", "ST", "RC"):
        offenders = [c for c in sr400.log if c.split()[0].upper() == command]
        check(not offenders, f"tier 2 never sent {command} (found {offenders[:3]})")

    # --- a broken selftest module degrades to a message, not a crash ----------
    sr400 = VirtualSR400()
    device = _selftest_device(driver, sr400, tmpdir, **{"Counter A input": "10 MHz"})
    boxes = []
    device.message_box = boxes.append
    saved_module = driver.selftest
    try:
        driver.selftest = None
        device.run_self_test()
        check(
            any("could not be loaded" in str(t) for t in boxes),
            f"a missing selftest module degrades to a message (got {boxes})",
        )
    finally:
        driver.selftest = saved_module

    # --- no port selected ------------------------------------------------------
    sr400 = VirtualSR400()
    device = _selftest_device(driver, sr400, tmpdir, **{"Port": "", "Counter A input": "10 MHz"})
    boxes = []
    device.message_box = boxes.append
    device.run_self_test()
    check(
        any("select a port" in str(t) for t in boxes),
        f"with no port selected it says so rather than failing (got {boxes})",
    )

    device.port = None
    boxes.clear()
    device.run_self_test()
    check(
        any("no open port" in str(t) for t in boxes),
        f"with no port object at all the refusal says so, for diagnosis (got {boxes})",
    )

    # --- an action on an instance that never received the GUI parameters -------
    # Measured on SweepMe! 1.5.7.9, 2026-11-10: an action started from a control widget with
    # asynchronous execution refused with "select a port first" although a port was selected.
    # A pysweepme Port still carries its resource name in port_properties["ID"].
    class FakeVisaResource:
        def __init__(self):
            self.ren_calls = []

        def control_ren(self, mode):
            self.ren_calls.append(mode)

    sr400 = VirtualSR400()
    sr400.port_properties = {"ID": "GPIB0::23::INSTR"}
    sr400.port = FakeVisaResource()
    device = _selftest_device(driver, sr400, tmpdir, **{"Port": "", "Counter A input": "10 MHz"})
    boxes = []
    device.message_box = boxes.append
    device.message_info = lambda message: None
    device.run_self_test()
    check(
        device.port_string == "GPIB0::23::INSTR" and not device.is_rs232,
        f"the action adopts the port name from the open port (got {device.port_string!r})",
    )
    check(
        sr400.port.ren_calls == [3],
        f"the action asserts REN itself on GPIB (got {sr400.port.ren_calls})",
    )
    check(
        any("checks passed" in str(t) for t in boxes)
        and not any("select a port" in str(t) for t in boxes),
        f"and tier 1 then runs instead of refusing (got {boxes})",
    )
    check(
        not any("Failed:" in str(t) for t in boxes),
        f"and every tier-1 check passes on GPIB, including the RS-232-only refusals (got {boxes})",
    )
    check(
        not any(command.split()[0] in ("SW", "MI") for command in sr400.log if command.split()),
        "tier 1 on GPIB never sends SW or MI",
    )

    check(
        driver.Device().port_properties.get("clear") is False,
        "before any GUI parameters arrive the port clear is off, so an early-opened GPIB port "
        "is never device-cleared (the SR400 treats SDC as CL)",
    )

    (
        st.KNOWN_ANSWER_SECONDS,
        st.TIMEBASE_REPEATS,
        st.SCAN_COUNT_TIME,
        st.EXTERNAL_COUNT_TIME,
        st.THROUGHPUT_QUERIES,
        st.TRIGGER_PROBE_TIMEOUT,
    ) = saved_timings


def _scan_device(driver, sr400, tmpdir):
    """A device wired for the threshold scans, with every prompt and message captured."""
    device = make_device(driver, sr400, **{"Port": "GPIB0::23::INSTR"})
    device.get_folder = lambda identifier: tmpdir
    # Windows sleeps in ~15 ms quanta, which would dominate a simulated scan; poll flat out.
    device.poll_interval = 0.0
    log = {"boxes": [], "blocking": [], "info": []}

    def box(message, blocking=False):
        (log["blocking"] if blocking else log["boxes"]).append(message)

    device.message_box = box
    device.message_info = log["info"].append
    return device, log


def test_end_of_run_tests(driver):
    print("\n[23b] end-of-run tests: ticked in the GUI, run in deinitialize() on the run's port")

    import tempfile

    tmpdir = tempfile.mkdtemp(prefix="sr400_endrun_")
    st = driver.selftest
    labels = [entry[0] for entry in driver.Device.END_OF_RUN_TESTS]
    # By runner, not by position: inserting a test (the settling check) must not re-aim these.
    by_runner = {entry[2]: entry[0] for entry in driver.Device.END_OF_RUN_TESTS}
    TIER1, DARK, LIGHT = (by_runner['run_tier1'], by_runner['run_threshold_scan_dark'],
                          by_runner['run_threshold_scan_light'])

    gui = driver.Device().set_GUIparameter()
    check(
        all(gui.get(label) is False for label in labels),
        f"all {len(labels)} end-of-run tests are GUI checkboxes, unticked by default ({labels})",
    )

    class FakeReport:
        def __init__(self, failures=()):
            self.failures = list(failures)
            self.aborted = False
            self.checks = 3
            self.passed = 3 - len(self.failures)
            self.headline = ""
            self.write_error = ""
            self.extra_paths = {}

    def run_device(**ticked):
        """A device that has completed a normal run up to and including unconfigure()."""
        sr400 = VirtualSR400()
        device = _selftest_device(
            driver, sr400, tmpdir, Port="GPIB0::23::INSTR",
            **{"Counter A input": "INPUT 1", "Count time in s": 0.002}, **ticked,
        )
        boxes = []
        device.message_box = lambda message, blocking=False: boxes.append((str(message), blocking))
        device.message_info = lambda message: None
        device.connect()
        device.initialize()
        device.configure()
        run_point(device)
        device.unconfigure()
        return sr400, device, boxes

    saved = {name: getattr(st, name) for name in
             ("KNOWN_ANSWER_SECONDS", "TIMEBASE_REPEATS", "SCAN_COUNT_TIME",
              "EXTERNAL_COUNT_TIME", "THROUGHPUT_QUERIES", "run_tier1",
              "run_threshold_scan_dark")}
    try:
        st.KNOWN_ANSWER_SECONDS = 0.01
        st.TIMEBASE_REPEATS = 2
        st.SCAN_COUNT_TIME = 0.002
        st.EXTERNAL_COUNT_TIME = 0.002
        st.THROUGHPUT_QUERIES = 10

        # --- nothing ticked: deinitialize() does nothing -------------------------------
        sr400, device, boxes = run_device()
        sent_before = len(sr400.log)
        device.deinitialize()
        check(boxes == [] and len(sr400.log) == sent_before,
              f"with nothing ticked deinitialize() sends and shows nothing (got {boxes})")

        # --- tier 1 ticked: nothing before measuring, the test after ---------------------
        sr400, device, boxes = run_device(**{TIER1: True})
        check(boxes == [], f"a ticked test does not run before or during the measurement (got {boxes})")
        device.deinitialize()
        check(
            any("tier 1: 22/22 checks passed" in m for m, _ in boxes),
            f"tier 1 runs in deinitialize() over GPIB and passes 22/22 (got {boxes})",
        )

        # --- every test leaves a row in the running log beside its report --------------
        import csv

        log_path = os.path.join(tmpdir, "Logger-Stanford_SR400", st.Report.LOG_NAME)
        check(os.path.exists(log_path), f"a test log is written beside the reports ({log_path})")
        check(any("Test log" in m for m, _ in boxes), "and the summary names it")
        with open(log_path, newline="", encoding="utf-8") as handle:
            rows_before = list(csv.DictReader(handle))
        last = rows_before[-1] if rows_before else {}
        check(
            last.get("test") == "self-test tier 1" and last.get("result") == "PASS"
            and last.get("passed") == "22" and last.get("port") == "GPIB0::23::INSTR"
            and os.path.exists(last.get("report", "")),
            f"its last row records this tier-1 run and points at the report (got {last})",
        )
        sr400, device, boxes = run_device(**{TIER1: True})
        device.deinitialize()
        with open(log_path, newline="", encoding="utf-8") as handle:
            rows_after = list(csv.DictReader(handle))
        check(len(rows_after) == len(rows_before) + 1,
              f"a second test appends one row, not a new file ({len(rows_before)} -> {len(rows_after)})")

        # --- a failing test is reported, not raised -----------------------------------
        st.run_tier1 = lambda device: (FakeReport(failures=["known-answer count wrong"]), None)
        sr400, device, boxes = run_device(**{TIER1: True})
        try:
            device.deinitialize()
            raised = ""
        except Exception as exc:  # noqa: BLE001
            raised = str(exc)
        check(raised == "", f"a failing end-of-run test does not raise (raised {raised!r})")
        check(any("known-answer count wrong" in m for m, _ in boxes),
              f"and its failure is shown in the summary (got {boxes})")
        st.run_tier1 = saved["run_tier1"]

        # --- a test that raises is reported, and the ones after it are skipped -----------
        # Measured 2026-11-10: a GPIB VI_ERROR_TMO in tier 1 reached SweepMe! as a Python
        # error with no summary.
        ran = []

        def raising_tier1(device):
            raise FakeVisaTimeout

        st.run_tier1 = raising_tier1
        saved_dark = st.run_threshold_scan_dark
        st.run_threshold_scan_dark = lambda device: (ran.append("dark"), (FakeReport(), None))[1]
        sr400, device, boxes = run_device(**{TIER1: True, DARK: True})
        try:
            device.deinitialize()
            raised = ""
        except Exception as exc:  # noqa: BLE001
            raised = str(exc)
        check(raised == "", f"an end-of-run test that raises does not raise (raised {raised!r})")
        check(any("VI_ERROR_TMO" in m and "stopped with an error" in m for m, _ in boxes),
              f"and the error is shown in a message (got {boxes})")
        check(ran == [] and any("Not run: threshold scan (dark)" in m for m, _ in boxes),
              f"and the tests after it are skipped and named (got {ran}, {boxes})")
        st.run_tier1 = saved["run_tier1"]
        st.run_threshold_scan_dark = saved_dark

        # --- a scan: blocking prompt first, summary after --------------------------------
        order = []

        def fake_dark(device):
            order.append("scan")
            return FakeReport(), None

        st.run_threshold_scan_dark = fake_dark
        sr400, device, boxes = run_device(**{DARK: True})
        device.message_box = lambda message, blocking=False: (
            order.append("prompt" if blocking else "summary"), boxes.append((str(message), blocking)),
        )
        device.deinitialize()
        check(order == ["prompt", "scan", "summary"],
              f"the dark scan's blocking prompt comes before the scan, the summary after (got {order})")
        check(boxes and boxes[0][0] == st.PROMPT_DARK, "and the prompt is the scan's own text")

        # --- a stopped run skips them; a stop during one ends it quietly ------------------
        ran = []
        st.run_threshold_scan_dark = lambda device: (ran.append("dark"), (FakeReport(), None))[1]
        sr400, device, boxes = run_device(**{DARK: True})
        device.is_run_stopped = lambda: True
        device.deinitialize()
        check(ran == [] and boxes == [], f"a stopped run skips the end-of-run tests (got {ran}, {boxes})")

        def stopped(device):
            raise driver.RunStopped("stopped")

        st.run_threshold_scan_dark = stopped
        sr400, device, boxes = run_device(**{DARK: True})
        try:
            device.deinitialize()
            raised = ""
        except Exception as exc:  # noqa: BLE001
            raised = str(exc)
        check(raised == "", f"a stop during an end-of-run test raises nothing (raised {raised!r})")

        # --- they run in the declared order -----------------------------------------
        ran = []
        st.run_tier1 = lambda device: (ran.append("tier 1"), (FakeReport(), None))[1]
        st.run_threshold_scan_dark = lambda device: (ran.append("dark"), (FakeReport(), None))[1]
        sr400, device, boxes = run_device(**{DARK: True, TIER1: True})
        device.deinitialize()
        check(ran == ["tier 1", "dark"], f"tier 1 runs before the dark scan (got {ran})")

        # --- the dark result reaches a light scan run on a fresh instance -------------
        saved_light = st.run_threshold_scan_light
        seen = {}

        def fake_dark_valid(device):
            device._dark_threshold_scan = {"valid": True, "marker": "dark run"}
            return FakeReport(), None

        def fake_light(device):
            seen["dark"] = getattr(device, "_dark_threshold_scan", None)
            return FakeReport(), None

        try:
            driver.Device._session_dark_scans.clear()
            st.run_threshold_scan_dark = fake_dark_valid
            st.run_threshold_scan_light = fake_light
            sr400, device, boxes = run_device(**{DARK: True})
            device.deinitialize()
            sr400, device, boxes = run_device(**{LIGHT: True})  # a new instance
            device.deinitialize()
            check(
                (seen.get("dark") or {}).get("marker") == "dark run",
                f"a light scan in a later run, on a new instance, sees the dark result (got {seen})",
            )
            seen.clear()
            sr400 = VirtualSR400()
            device = _selftest_device(driver, sr400, tmpdir, Port="COM3", **{LIGHT: True})
            device.message_box = lambda message, blocking=False: None
            device.message_info = lambda message: None
            device.deinitialize()
            check(seen.get("dark") is None,
                  f"but not a light scan on a different port (got {seen})")
        finally:
            st.run_threshold_scan_light = saved_light
            driver.Device._session_dark_scans.clear()
    finally:
        for name, value in saved.items():
            setattr(st, name, value)


def test_gpib_drain(driver):
    print("\n[23c] draining a GPIB port: a read timeout is the empty answer")

    class TimedResource:
        """A pyvisa resource: only its timeout (ms) matters here."""

        def __init__(self):
            self.timeout = 20000
            self.seen = []

    sr400 = VirtualSR400()
    device = make_device(driver, sr400, Port="GPIB0::23::INSTR")
    resource = TimedResource()
    sr400.port = resource
    original_read = sr400.read

    def read_noting_timeout():
        resource.seen.append(resource.timeout)
        return original_read()

    sr400.read = read_noting_timeout
    sr400.out = ["3", "3"]
    try:
        device._drain_port()
        raised = ""
    except Exception as exc:  # noqa: BLE001
        raised = str(exc)
    check(raised == "", f"a GPIB drain ends quietly on VI_ERROR_TMO (raised {raised!r})")
    check(sr400.out == [] and getattr(sr400, "empty_gpib_reads", 0) == 1,
          f"after reading what was waiting, and one timed-out read (left {sr400.out})")
    check(resource.seen and all(t == driver.Device.DRAIN_TIMEOUT_MS for t in resource.seen),
          f"the reads ran on the short drain timeout (saw {resource.seen} ms)")
    check(resource.timeout == 20000, f"and the run's timeout is restored (got {resource.timeout})")

    class BrokenRead(VirtualSR400):
        def read(self):
            raise OSError("GPIB bus error")

    broken = BrokenRead()
    device = make_device(driver, broken, Port="GPIB0::23::INSTR")
    broken.port = TimedResource()
    try:
        device._drain_port()
        raised = ""
    except OSError as exc:
        raised = str(exc)
    check(raised == "GPIB bus error", f"any other read error still raises (got {raised!r})")
    check(broken.port.timeout == 20000, "and the timeout is restored on that path too")

    sr400 = VirtualSR400()
    device = make_device(driver, sr400)  # COM3
    sr400.port = TimedResource()
    sr400.out = ["3"]
    device._drain_port()
    check(sr400.out == [] and sr400.port.timeout == 20000,
          "a COM drain still stops on '' and never touches a VISA timeout")


# The first real dark scan: R8486 covered, SR400 over GPIB, SweepMe! 1.5.7.9, 2026-11-10.
# (|level| in V, counts, live s), as written to its CSV. It is the regression fixture for the
# noise-edge bug it exposed: the rate rises below 1.2 mV, and the old search reported 0.4 mV.
REAL_DARK_SCAN_2026_11_10 = (
    (0.00040, 389, 0.010000), (0.00060, 623, 0.010000), (0.00080, 1204, 0.010000), (0.00100, 2129, 0.010000),
    (0.00120, 2322, 0.010000), (0.00140, 1873, 0.010000), (0.00160, 1297, 0.010000), (0.00180, 744, 0.010000),
    (0.00200, 430, 0.010000), (0.00220, 295, 0.010000), (0.00240, 203, 0.010000), (0.00260, 247, 0.020000),
    (0.00280, 227, 0.060000), (0.00300, 200, 0.270000), (0.00320, 242, 0.810000), (0.00340, 402, 2.210000),
    (0.00360, 235, 2.210000), (0.00380, 223, 2.810000), (0.00400, 237, 4.210000), (0.00420, 265, 8.010000),
    (0.00440, 221, 10.210000), (0.00460, 212, 14.210000), (0.00480, 204, 19.210000), (0.00500, 200, 25.210000),
    (0.00520, 180, 30.210000), (0.00540, 127, 30.210000), (0.00560, 109, 30.210000), (0.00580, 81, 30.210000),
    (0.00600, 71, 30.210000), (0.00640, 77, 30.210000), (0.00680, 29, 30.210000), (0.00720, 49, 30.210000),
    (0.00760, 33, 30.210000), (0.00800, 49, 30.210000), (0.00840, 35, 30.210000), (0.00880, 31, 30.210000),
    (0.00920, 38, 30.210000), (0.00960, 26, 30.210000), (0.01000, 11, 30.210000), (0.01040, 16, 30.210000),
    (0.01080, 13, 30.210000), (0.01120, 22, 30.210000), (0.01160, 16, 30.210000), (0.01200, 8, 30.210000),
    (0.01240, 7, 30.210000), (0.01280, 2, 30.210000), (0.01320, 17, 30.210000), (0.01360, 10, 30.210000),
    (0.01400, 3, 30.210000), (0.01440, 2, 30.210000), (0.01480, 5, 30.210000), (0.01520, 6, 30.210000),
    (0.01600, 3, 30.210000), (0.01800, 1, 30.210000), (0.02000, 2, 30.210000), (0.02200, 1, 30.210000),
    (0.02400, 1, 30.210000), (0.02600, 0, 30.210000), (0.02800, 3, 30.210000), (0.03000, 1, 30.210000),
    (0.03200, 0, 30.210000), (0.03400, 0, 30.210000), (0.03600, 0, 30.210000),
)


def test_real_dark_scan(driver):
    print("\n[23d] the first real dark scan (2026-11-10), re-analysed")
    st = driver.selftest
    points = [{"abs_v": v, "level_v": -v, "counts": n, "live_s": t, "t": 0.0}
              for v, n, t in REAL_DARK_SCAN_2026_11_10]
    result = st.analyse_dark(points)
    check(result["valid"], f"the real covered-tube scan is valid ({result['reasons']})")
    peak = max(result["rows"], key=lambda r: r["rate"])
    check(abs(peak["abs_v"] - 0.0012) < 1e-9,
          f"its rate peaks at 1.2 mV, inside the noise hump (got {peak['abs_v'] * 1e3:.1f} mV)")
    edge = result["noise_edge_v"]
    check(edge is not None and abs(edge - 0.0052) < 1e-9,
          f"the noise edge is found above the hump, at 5.2 mV, not at the lowest level "
          f"(got {edge * 1e3 if edge else None} mV; the old search said 0.4)")
    bound = result["lower_bound_v"]
    check(bound is not None and abs(bound - 0.0058) < 1e-9,
          f"so the lower bound is 5.8 mV (got {bound * 1e3 if bound else None} mV; was 1.0)")
    check(st._gui_volts(bound) == -0.0058, "and its GUI value is -0.0058 V")


def test_real_scans_in_repo(driver):
    print("\n[23e] the real 2026-11-10 scans in docs/real_data: figures, loss levels, dark found beside")

    import shutil
    import tempfile

    st = driver.selftest
    real = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
                        "docs", "real_data", "2026-11-10")
    dark_name = "SR400_threshold_scan_dark_2026-11-10_132008"
    light_name = "SR400_threshold_scan_light_2026-11-10_135935"
    for name in (dark_name, light_name):
        for suffix in (".csv", ".txt", ".svg"):
            check(os.path.exists(os.path.join(real, name + suffix)), f"docs/real_data/2026-11-10/{name}{suffix} is committed")
    if not os.path.exists(os.path.join(real, light_name + ".csv")):
        return

    # The figures are regenerated from the raw CSVs, in a scratch folder, and must match.
    work = tempfile.mkdtemp(prefix="sr400_real_")
    for name in (dark_name, light_name):
        shutil.copy(os.path.join(real, name + ".csv"), work)
    for name in (dark_name, light_name):
        fresh = open(st.plot_csv(os.path.join(work, name + ".csv")), encoding="utf-8").read()
        published = open(os.path.join(real, name + ".svg"), encoding="utf-8").read()
        check(fresh == published, f"{name}.svg is exactly what selftest.py plot makes from its CSV -- "
                                  f"if not, regenerate it")
    light_svg = open(os.path.join(real, light_name + ".svg"), encoding="utf-8").read()
    check("found beside this file" in light_svg,
          "the light CSV names no dark scan, so plot finds the dark CSV beside it, and says so")
    check("dark scan, covered tube" in light_svg, "panel (c) draws the dark density alongside the light")
    check("NOT SEPARABLE" in light_svg, "and its readout refuses the 0.1 % level rather than print it")

    # The real light scan, analysed with the real dark scan.
    _, dark_points = st.read_scan_csv(os.path.join(real, dark_name + ".csv"))
    _, passes = st.read_scan_csv(os.path.join(real, light_name + ".csv"))
    dark = st.analyse_dark(dark_points)
    result = st.analyse_light(passes, dark)
    check(abs(result["valley_v"] - 0.004) < 1e-9 and abs(result["peak_v"] - 0.008) < 1e-9,
          f"the real tube's valley is 4.0 mV and its single-PE peak 8.0 mV "
          f"(got {result['valley_v']}, {result['peak_v']})")
    tenth, one = result["loss_detail"][0.001], result["loss_detail"][0.01]
    check(tenth is not None and not tenth["separable"],
          f"0.1 % loss is not separable from the reference at ~7e4 counts per level (got {tenth})")
    check(one is not None and one["separable"] and abs(one["settable_v"] - 0.0042) < 1e-9
          and st._gui_volts(one["settable_v"]) == -0.0042,
          f"1 % loss is at the settable 4.2 mV, GUI -0.0042 (got {one})")
    check(0.05 < one["sigma_mv"] < 0.2, f"with an honest uncertainty of about 0.1 mV (got {one['sigma_mv']:.3f})")

    # --- the second real run, 16:36 dark and 17:24 light --------------------------------------
    dark2_name = "SR400_threshold_scan_dark_2026-11-10_163608"
    light2_name = "SR400_threshold_scan_light_2026-11-10_172444"
    for name in (dark2_name, light2_name):
        for suffix in (".csv", ".svg"):
            check(os.path.exists(os.path.join(real, name + suffix)), f"docs/real_data/2026-11-10/{name}{suffix} is committed")
    if not os.path.exists(os.path.join(real, light2_name + ".csv")):
        return
    analysis_copy = os.path.join(os.path.dirname(os.path.dirname(real)), os.pardir, "analysis",
                                 "low_signal_threshold", "data")
    for name in (dark2_name, light2_name):
        mine = os.path.join(real, name + ".csv")
        theirs = os.path.join(analysis_copy, name + ".csv")
        check(os.path.exists(theirs) and open(mine, "rb").read() == open(theirs, "rb").read(),
              f"{name}.csv is byte-identical to the copy the low-signal analysis reads")

    # All four CSVs in one folder, as committed: each light scan must still find ITS dark scan.
    work = tempfile.mkdtemp(prefix="sr400_real_both_")
    for name in (dark_name, light_name, dark2_name, light2_name):
        shutil.copy(os.path.join(real, name + ".csv"), work)
    for name in (dark_name, light_name, dark2_name, light2_name):
        fresh = open(st.plot_csv(os.path.join(work, name + ".csv")), encoding="utf-8").read()
        published = open(os.path.join(real, name + ".svg"), encoding="utf-8").read()
        check(fresh == published, f"{name}.svg is exactly what selftest.py plot makes from its CSV, with both "
                                  f"runs in the folder -- if not, regenerate it")
    light1_svg = open(os.path.join(real, light_name + ".svg"), encoding="utf-8").read()
    light2_svg = open(os.path.join(real, light2_name + ".svg"), encoding="utf-8").read()
    check(dark_name + ".csv" in light1_svg and dark2_name not in light1_svg,
          "with the 16:36 dark in the folder, the 13:59 light still uses the 13:20 dark, not a later one")
    check(dark2_name + ".csv" in light2_svg and "found beside" not in light2_svg,
          "the 17:24 light uses the 16:36 dark its own CSV names")

    _, dark2_points = st.read_scan_csv(os.path.join(real, dark2_name + ".csv"))
    _, passes2 = st.read_scan_csv(os.path.join(real, light2_name + ".csv"))
    dark2 = st.analyse_dark(dark2_points)
    check(abs(dark2["noise_edge_v"] - 0.0060) < 1e-9 and abs(dark2["lower_bound_v"] - 0.0066) < 1e-9,
          f"the 16:36 dark: noise edge 6.0 mV, lower bound 6.6 mV, GUI -0.0066 "
          f"(got {dark2['noise_edge_v']}, {dark2['lower_bound_v']})")
    result2 = st.analyse_light(passes2, dark2)
    check(abs(result2["valley_v"] - 0.0038) < 1e-9 and abs(result2["peak_v"] - 0.0072) < 1e-9,
          f"the 17:24 light: valley 3.8 mV, single-PE peak 7.2 mV (got {result2['valley_v']}, {result2['peak_v']})")
    # The four dark x light pairings, as the folder README and SIMULATED_VS_REAL tabulate them.
    expected = {(dark_name, light_name): 0.0068, (dark_name, light2_name): 0.0068,
                (dark2_name, light_name): 0.0076, (dark2_name, light2_name): 0.0076}
    darks = {dark_name: dark, dark2_name: dark2}
    lights = {light_name: passes, light2_name: passes2}
    got = {k: st.analyse_light(lights[k[1]], darks[k[0]])["optimum_v"] for k in expected}
    check(all(abs(got[k] - v) < 1e-9 for k, v in expected.items()),
          f"the S/sqrt(B) optimum on the four pairings is 6.8, 6.8, 7.6, 7.6 mV, as the docs tabulate "
          f"(got {[round(v * 1e3, 1) for v in got.values()]})")
    lo, hi = result2["optimum_band_v"]
    check(abs(lo - 0.0068) < 1e-9 and abs(hi - 0.0076) < 1e-9,
          f"and on the second run its 5 % band is 6.8-7.6 mV (got {lo * 1e3:.1f}-{hi * 1e3:.1f})")


def test_settling_and_hv(driver):
    print("\n[23f] the PMT HV record, the dark settling check, and hv-compare")

    import csv
    import tempfile

    st = driver.selftest
    field = driver.Device.PMT_HV_FIELD
    check(driver.Device().set_GUIparameter().get(field) == 0.0, f"'{field}' is a GUI field, 0 by default")
    device = make_device(driver, VirtualSR400(), **{field: 1000})
    check(device.pmt_hv_v == 1000.0, "an entered HV reaches the driver")
    device = make_device(driver, VirtualSR400())
    check(device.pmt_hv_v is None, "0 means not recorded")

    # --- settling: a relaxing dark rate is waited out, a steady one passes quickly ---------------
    def settle_device(tmp, hv, **pmt):
        # 2e3x, not 1e5x: at 1e5x the set-up alone lasts thousands of simulated seconds, and a
        # 10-minute dark transient would be over before the first block.
        sr400 = VirtualSR400(pmt=pmt, time_scale=2e3)
        device, log = _scan_device(driver, sr400, tmp)
        device.pmt_hv_v = hv
        return device, log

    tmp = tempfile.mkdtemp(prefix="sr400_settle_")
    device, _ = settle_device(tmp, 1000.0)
    report, path = st.run_dark_settling(device)
    _, blocks = st.read_scan_csv(path.replace(".txt", ".csv"))
    res = st.analyse_settle(blocks)
    earliest = max(st.SETTLE_WINDOW_SECONDS, 3 * st.SETTLE_BLOCK_MAX_SECONDS)  # 5 min AND 3 blocks
    check(res["settled"] and res["settled_after_s"] <= earliest + st.SETTLE_BLOCK_MAX_SECONDS,
          f"a steady dark rate settles as soon as {st.SETTLE_WINDOW_SECONDS / 60:g} min of blocks are in "
          f"(after {res['settled_after_s']:.0f} s, {report.headline})")
    text = open(path).read()
    check("PMT HV          : 1000 V" in text, "the report header records the PMT HV")
    check("would" in text and "also have passed" in text and "per minute" in text,
          "and states the measured drift and the slowest drift the test could miss")

    device, _ = settle_device(tmp, 1000.0, dark_excess=3.0, dark_tau_s=600.0)
    report, path = st.run_dark_settling(device)
    _, blocks = st.read_scan_csv(path.replace(".txt", ".csv"))
    res = st.analyse_settle(blocks)
    check(res["settled"] and res["settled_after_s"] is not None,
          f"a dark rate relaxing 4x -> 1x with tau 10 min is reported settled ({report.headline})")
    check(res["settled"] and res["settled_rate"] < 0.6 * res["rows"][0]["rate"],
          f"and its settled rate is well below the first block's "
          f"({res['settled_rate']:.3g} against {res['rows'][0]['rate']:.3g} cps)")
    check(res["settled"] and res["settled_after_s"] > 2 * st.SETTLE_WINDOW_SECONDS,
          f"which takes well over the minimum {st.SETTLE_WINDOW_SECONDS / 60:g} min "
          f"({res['settled_after_s'] / 60 if res['settled_after_s'] else 0:.1f} min)")

    device, _ = settle_device(tmp, 1000.0, dark_excess=20.0, dark_tau_s=900.0)
    report, path = st.run_dark_settling(device)
    check(report.failures != [] and "NOT SETTLED" in report.headline,
          f"a rate still falling ~13 % per block at the cap is NOT SETTLED ({report.headline})")
    rows = list(csv.DictReader(open(os.path.join(_report_dir(tmp), st.Report.LOG_NAME), encoding="utf-8")))
    settled_rows = [r for r in rows if r["test"] == "dark settling check" and r["settle_minutes"]]
    check(settled_rows and all(r["pmt_hv_V"] == "1000" for r in rows),
          "the test log carries the HV on every row, and the settling time where it settled")
    svg = path.replace(".txt", ".svg")
    check(os.path.exists(svg) and "PMT HV 1000 V" in open(svg, encoding="utf-8").read(),
          "the settling figure is written, with the HV on it")

    # --- a light scan never uses a dark scan taken at another HV --------------------------------
    tmp = tempfile.mkdtemp(prefix="sr400_hvpair_")
    device, _ = settle_device(tmp, 900.0)
    st.run_threshold_scan_dark(device)
    sr400 = VirtualSR400(pmt={"light_rate": 5.0e4}, time_scale=1e5)
    light_dev, _ = _scan_device(driver, sr400, tmp)
    light_dev.pmt_hv_v = 1000.0
    light_dev._dark_threshold_scan = device._dark_threshold_scan  # in memory, from 900 V
    report, path = st.run_threshold_scan_light(light_dev)
    text = open(path).read()
    check("taken at PMT HV 900" in text and "from disk" not in text,
          "a light scan at 1000 V refuses the 900 V dark scan in memory, and finds none on disk at 1000 V")

    # --- hv-compare over four HVs: gain rises with HV, dark counts climb steeply above 1000 V -----
    tmp = tempfile.mkdtemp(prefix="sr400_hvcmp_")
    for hv in (900.0, 1000.0, 1100.0, 1200.0):
        g = (hv / 1000.0) ** 6
        pmt = {"spe_mean": 0.010 * g, "spe_sigma": 0.004 * g, "spe_exp_scale": 0.0015 * g}
        sr400 = VirtualSR400(pmt=dict(pmt), time_scale=1e5)
        dev, _ = _scan_device(driver, sr400, tmp)
        dev.pmt_hv_v = hv
        dev.discriminator_levels["A"] = -0.0040
        st.run_dark_settling(dev)
        st.run_threshold_scan_dark(dev)
        sr400.pmt["light_rate"] = 5.0e4
        st.run_threshold_scan_light(dev)
    table, figure, verdict = st.hv_compare(_report_dir(tmp))
    rows = list(csv.DictReader(open(table, encoding="utf-8")))
    check([r["hv_V"] for r in rows] == ["900", "1000", "1100", "1200"],
          f"hv-compare finds one row per HV, in order (got {[r['hv_V'] for r in rows]})")
    peaks = [float(r["spe_peak_mV"]) for r in rows if r["spe_peak_mV"]]
    check(len(peaks) >= 3 and peaks == sorted(peaks) and len(set(peaks)) == len(peaks),
          f"the single-PE peak rises strictly with HV, as the gain does, also past 15 mV where the "
          f"grid is coarse (got {peaks} mV)")

    # Two reports written in the same second must both survive.
    tmp2 = tempfile.mkdtemp(prefix="sr400_clash_")
    dev2, _ = _scan_device(driver, VirtualSR400(), tmp2)
    first = st.Report(dev2, "clash test").write("2026-11-10 12:00:00", {".csv": "first"})
    second = st.Report(dev2, "clash test").write("2026-11-10 12:00:00", {".csv": "second"})
    check(first != second and os.path.exists(first) and os.path.exists(second)
          and open(first.replace(".txt", ".csv")).read() == "first",
          f"a second report in the same second gets its own name and leaves the first intact "
          f"({os.path.basename(first)}, {os.path.basename(second)})")
    check(all(r["dark_csv"] and r["settle_csv"] for r in rows)
          and all(r["settled"] in ("True", "") for r in rows),
          f"each HV is paired with its own dark scan and settling check, none NOT SETTLED "
          f"(settled: {[r['settled'] for r in rows]})")
    # With a dark rate that does not grow with HV, more gain only separates photons from noise
    # better, so the best is at the top of the range -- and the right answer is "extend it".
    check(any("edge of the range scanned (1200 V)" in line for line in verdict)
          and not any(line.startswith("+OPTIMUM") for line in verdict),
          f"when S/sqrt(B) still rises at the top HV, no optimum is named and the range is to be "
          f"extended ({verdict})")

    # The decision itself, on constructed rows.
    def row(hv, snr, **extra):
        return dict({"hv": hv, "problem": "", "photon_rate": 4.0e4, "best_snr": snr,
                     "best_snr_v": 0.0064, "snr_photon_fraction": 0.9, "settled": True}, **extra)

    verdict, optimum, _ = st._hv_verdict([row(900, 1.0e4), row(1000, 1.5e4), row(1100, 1.2e4)])
    check(optimum is not None and optimum["hv"] == 1000 and any("counting 90%" in v for v in verdict),
          f"a turnover inside the range names that HV, with the photon fraction ({verdict})")
    verdict, optimum, _ = st._hv_verdict([row(900, 1.0e4), row(1000, 1.5e4)])
    check(optimum is None and any("at least 3 needed" in v for v in verdict), "two HVs are not enough")
    verdict, optimum, _ = st._hv_verdict([row(900, 1.0e4), row(1000, 1.5e4, settled=False), row(1100, 1.2e4),
                                          row(1200, 1.1e4)])
    check(optimum is not None and optimum["hv"] == 1100 and any("NOT SETTLED" in v for v in verdict),
          f"an HV that had not settled is left out, and says why ({verdict})")
    verdict, optimum, _ = st._hv_verdict([row(900, 1.0e4), row(1000, 1.5e4, snr_photon_fraction=0.3),
                                          row(1100, 1.2e4)])
    check(any("throws away most photons" in v for v in verdict),
          "a weak-signal optimum that keeps under half the photons is flagged")
    check(os.path.exists(figure) and "(d) best S/sqrt(B)" in open(figure, encoding="utf-8").read(),
          "and the comparison figure is written")

    # Guards: the light must be the same at every HV, and an optimum needs three HVs.
    tmp = tempfile.mkdtemp(prefix="sr400_hvcmp_light_")
    for hv, light in ((900.0, 5.0e4), (1000.0, 2.0e4), (1100.0, 5.0e4)):
        g = (hv / 1000.0) ** 6
        sr400 = VirtualSR400(pmt={"spe_mean": 0.010 * g, "spe_sigma": 0.004 * g}, time_scale=1e5)
        dev, _ = _scan_device(driver, sr400, tmp)
        dev.pmt_hv_v = hv
        st.run_threshold_scan_dark(dev)
        sr400.pmt["light_rate"] = light
        st.run_threshold_scan_light(dev)
    _, figure, verdict = st.hv_compare(_report_dir(tmp))
    check(any("NOT compared" in line for line in verdict) and not any(l.startswith("+OPTIMUM") for l in verdict),
          f"light that differs between HVs blocks the S/sqrt(B) comparison ({verdict[:1]})")
    check("NOT SHOWN" in open(figure, encoding="utf-8").read(), "and panel (d) says NOT SHOWN")
    check(any("settling unknown" in line or "settling is unknown" in line for line in verdict),
          "an HV with no settling check is marked as unknown, not as settled")

    # --- interleaved replicates under a light that dims 30 % between rounds -----------------------
    # Dark and settling once per HV, on the first visit; later rounds are light scans only, each
    # paired with its HV's dark scan. The correction must bring each HV's replicates together.
    tmp = tempfile.mkdtemp(prefix="sr400_hvrep_")
    sims = {}
    for round_number, light in ((1, 5.0e4), (2, 3.5e4)):
        for hv in (975.0, 1000.0, 1025.0):
            g = (hv / 1000.0) ** 6
            if hv not in sims:
                sims[hv] = VirtualSR400(pmt={"spe_mean": 0.010 * g, "spe_sigma": 0.004 * g,
                                             "spe_exp_scale": 0.0015 * g}, time_scale=1e5)
            sr400 = sims[hv]
            dev, _ = _scan_device(driver, sr400, tmp)
            dev.pmt_hv_v = hv
            if round_number == 1:
                sr400.pmt["light_rate"] = 0.0
                st.run_threshold_scan_dark(dev)
            sr400.pmt["light_rate"] = light
            st.run_threshold_scan_light(dev)
    table, figure, verdict = st.hv_compare(_report_dir(tmp))
    rows = list(csv.DictReader(open(table, encoding="utf-8")))
    check([r["n_replicates"] for r in rows] == ["2", "2", "2"] and all(r["best_abs_snr_se"] for r in rows),
          f"each HV has its two replicates, and so an error bar ({[(r['hv_V'], r['n_replicates']) for r in rows]})")
    reps = list(csv.DictReader(open(table.replace(".csv", "_replicates.csv"), encoding="utf-8")))
    check(len(reps) == 6 and all(r["dark_csv"] for r in reps),
          f"the replicate table has all six light scans, each paired with its HV's one dark scan ({len(reps)})")
    for hv in ("975", "1000", "1025"):
        mine = [r for r in reps if r["hv_V"] == hv]
        raw = [float(r["best_abs_snr"]) for r in mine]
        fixed = [float(r["best_abs_snr_corrected"]) for r in mine]
        check(len(mine) == 2 and abs(raw[0] / raw[1] - 1) > 0.2 and abs(fixed[0] / fixed[1] - 1) < 0.08,
              f"at {hv} V the 30 % dimmer round reads {abs(raw[0] / raw[1] - 1):.0%} lower raw, but the "
              f"corrected replicates agree to {abs(fixed[0] / fixed[1] - 1):.1%}")
    check(any("corrected to a common light level" in line for line in verdict),
          "the verdict says the S/sqrt(B) values are light-corrected")
    svg = open(figure, encoding="utf-8").read()
    check("(e) light level of each scan" in svg and "grey = each scan" in svg,
          "the figure shows every replicate and the light level over time")


# The lab PC's test log as it was on 2026-11-10 17:24: a 15-column header from the driver that
# started it, and two 18-column rows appended by a later driver, so their values sat under the
# wrong headings. Report paths shortened.
MISALIGNED_LOG_2026_11_10 = """when,test,result,recommended_disc_A_level_V,photons_counted_at_recommended,lower_bound_V,upper_bound_1pct_loss_V,dark_counts_vanish_V,headline,passed,checks,port,interface,first_failure,report
2026-11-10 13:20:08,threshold scan dark,PASS,,,-0.001,,-0.032,"lower bound 1.0 mV, dark counts vanish from 32.0 mV",2,2,GPIB0::23::INSTR,GPIB,,dark_132008.txt
2026-11-10 13:59:35,threshold scan light,PASS,-0.004,1.0,,-0.0042,,"recommended A DISC LVL -4.0 mV, counting 100% of photons",5,5,GPIB0::23::INSTR,GPIB,,light_135935.txt
2026-11-10 16:36:08,threshold scan dark,PASS,,,,-0.0066,,,,,"lower bound 6.6 mV (GUI -0.0066), dark counts vanish from none",2,2,GPIB0::23::INSTR,GPIB,,dark_163608.txt
2026-11-10 17:24:44,threshold scan light,PASS,,-0.0068,0.7418,,-0.004,,,,"recommended A DISC LVL -6.8 mV (type -0.0068 in the GUI), counting 74% of photons",5,5,GPIB0::23::INSTR,GPIB,,light_172444.txt
"""


def test_log_migration_and_smooth_background(driver):
    print("\n[23g] the test log migrates to the current columns; S/sqrt(B) uses a fitted background")

    import csv
    import random
    import tempfile

    st = driver.selftest
    tmp = tempfile.mkdtemp(prefix="sr400_logmig_")
    dev, _ = _scan_device(driver, VirtualSR400(), tmp)
    folder = _report_dir(tmp)
    os.makedirs(folder, exist_ok=True)
    with open(os.path.join(folder, st.Report.LOG_NAME), "w", newline="", encoding="utf-8") as handle:
        handle.write(MISALIGNED_LOG_2026_11_10)
    report = st.Report(dev, "migration test")
    report.write("2026-11-10 18:00:00")
    rows = list(csv.DictReader(open(os.path.join(folder, st.Report.LOG_NAME), encoding="utf-8")))
    by_when = {r["when"]: r for r in rows}
    check(tuple(rows[0].keys()) == st.Report.LOG_COLUMNS, "the log is rewritten under the current header")
    check(by_when["2026-11-10 16:36:08"]["lower_bound_V"] == "-0.0066"
          and by_when["2026-11-10 16:36:08"]["upper_bound_1pct_loss_V"] == "",
          f"the 16:36 dark row's lower bound is back under lower_bound_V ({by_when['2026-11-10 16:36:08']})")
    light = by_when["2026-11-10 17:24:44"]
    check(light["recommended_disc_A_level_V"] == "-0.0068" and light["photons_counted_at_recommended"] == "0.7418"
          and light["upper_bound_1pct_loss_V"] == "-0.004",
          f"the 17:24 light row's values are under their own headings ({light})")
    check(by_when["2026-11-10 13:20:08"]["lower_bound_V"] == "-0.001"
          and by_when["2026-11-10 13:59:35"]["upper_bound_1pct_loss_V"] == "-0.0042",
          "and the old-layout rows keep their values")
    check("2026-11-10 18:00:00" in by_when, "the new row is appended after the migration")
    backups = [f for f in os.listdir(folder) if f.startswith("SR400_test_log_before_column_migration_")]
    check(len(backups) == 1 and open(os.path.join(folder, backups[0]), encoding="utf-8").read()
          == MISALIGNED_LOG_2026_11_10, "the original log is kept beside it, byte for byte")
    st.Report(dev, "migration test").write("2026-11-10 18:00:01")
    check(len([f for f in os.listdir(folder) if f.startswith("SR400_test_log_before_column_migration_")]) == 1,
          "a log already on the current header is not migrated again")

    # --- the fitted background: an exponential dark tail sampled with Poisson noise --------------
    random.seed(7)

    def poisson(lam):
        import math as m
        L, k, p = m.exp(-lam), 0, 1.0
        while True:
            p *= random.random()
            if p <= L:
                return k
            k += 1

    true = lambda v: 6.0 * math.exp(-(v - 0.005) / 0.0025)  # 6 cps at 5 mV, e-fold per 2.5 mV
    levels = [round(0.005 + 0.0002 * i, 4) for i in range(26)] + [0.012, 0.014]
    points = [{"abs_v": v, "level_v": -v, "counts": poisson(true(v) * 30.0), "live_s": 30.0, "t": 0.0}
              for v in levels]
    rows = st.analyse_dark(points)["rows"]
    errors, pulls = [], []
    for v in (0.0056, 0.0064, 0.0072, 0.0080, 0.0090):
        rate, sigma, counts = st._smooth_dark_rate(rows, v)
        errors.append(abs(rate / true(v) - 1))
        pulls.append(abs(rate / true(v) - 1) / sigma)
    single = [abs(r["rate"] / true(r["abs_v"]) - 1) for r in rows if 0.0056 <= r["abs_v"] <= 0.0090 and r["counts"]]
    check(max(errors) < 0.15 and max(pulls) < 3.0,
          f"the fit recovers a known dark tail within its own uncertainty (errors "
          f"{[f'{e:.1%}' for e in errors]}, pulls {[f'{p:.1f}' for p in pulls]})")
    check(sum(errors) / len(errors) < sum(single) / len(single),
          f"and more closely than single thresholds do ({sum(errors) / len(errors):.1%} against "
          f"{sum(single) / len(single):.1%} mean error)")
    check(st._smooth_dark_rate(rows, 0.0130) is not None,
          "it still gives a background on the coarse 2 mV tail, by widening its window")
    # Tightened 2026-11-11, when the fit learned to follow curvature: on a tail with none, it must
    # keep the straight line's noise reduction, not trade it for flexibility it does not need.
    line = [abs(_straight_line_dark_rate(st, rows, v) / true(v) - 1)
            for v in (0.0056, 0.0064, 0.0072, 0.0080, 0.0090)]
    check(sum(errors) <= 1.25 * sum(line),
          f"and on a tail with no curvature it does no worse than the straight line it replaced "
          f"({sum(errors) / len(errors):.1%} against {sum(line) / len(line):.1%} mean error)")

    # --- on the real scans: the band is no longer one level wide -------------------------------
    real = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
                        "docs", "real_data", "2026-11-10")
    _, dp = st.read_scan_csv(os.path.join(real, "SR400_threshold_scan_dark_2026-11-10_132008.csv"))
    _, lp = st.read_scan_csv(os.path.join(real, "SR400_threshold_scan_light_2026-11-10_135935.csv"))
    result = st.analyse_light(lp, st.analyse_dark(dp))
    lo, hi = result["optimum_band_v"]
    check(abs(result["optimum_v"] - 0.0068) < 1e-9 and hi - lo >= 0.0008 - 1e-9,
          f"on the real 2026-11-10 scans the optimum stays at 6.8 mV and the 5 % band now spans "
          f"{lo * 1e3:.1f}-{hi * 1e3:.1f} mV (it was 6.8-6.8)")


def _straight_line_dark_rate(st, rows, v):
    """The background fit as it was until 2026-11-11: log-linear over +-1 mV, widened in 1 mV
    steps until it holds 3 thresholds and 20 counts. Kept here as the baseline the fix must beat."""
    half = 0.001
    while True:
        window = [r for r in rows if abs(r["abs_v"] - v) <= half + 1e-9 and r["live_s"] > 0]
        if (len(window) >= 3 and sum(r["counts"] for r in window) >= 20) or half >= 0.004 - 1e-9:
            break
        half += 0.001
    if len(window) < 2 or sum(r["counts"] for r in window) < 20:
        return None
    fit = st._poisson_logpoly(window, v, 1)
    return fit[0] if fit else None


def _held_out_ratio(rows, predict, lo_v, hi_v):
    """Leave each threshold in [lo_v, hi_v] out, predict it from the rest: sum(predicted) / sum(observed)."""
    predicted = observed = 0.0
    for r in rows:
        if lo_v - 1e-9 <= r["abs_v"] <= hi_v + 1e-9:
            others = [o for o in rows if o is not r]
            predicted += predict(others, r["abs_v"]) * r["live_s"]
            observed += r["counts"]
    return predicted / observed


def test_curved_background_and_valley_floor(driver):
    print("\n[23h] the background fit follows the curve's bend; S/sqrt(B) is not scored below the valley")

    import random

    st = driver.selftest

    # --- a synthetic dark curve WITH curvature: noise roll-off, a bend, then the dark tail ------
    # Shaped like the real 13:20 scan (741 cps at 3.0 mV, 57 at 4.0, 6.8 at 5.2, 2.5 at 6.0) and
    # sampled as the driver samples: DARK_TARGET_COUNTS per threshold, at most DARK_MAX_SECONDS.
    def truth(v):
        mv = v * 1e3
        return (3e4 * math.exp(-((mv - 2.0) / 0.45) ** 2) + 180.0 * math.exp(-(mv - 3.4) / 0.5)
                + 1.5 * math.exp(-(mv - 6.0) / 3.0))

    rng = random.Random(11)

    def poisson(lam):
        limit, k, p = math.exp(-lam), 0, 1.0
        while True:
            p *= rng.random()
            if p <= limit:
                return k
            k += 1

    new_err, old_err, single_err = {}, {}, {}
    for _ in range(20):
        points = []
        for v in st.threshold_grid():
            if v > 0.0152 + 1e-9:
                break
            live = min(st.DARK_MAX_SECONDS, max(0.01, round(st.DARK_TARGET_COUNTS / truth(v), 2)))
            points.append({"abs_v": v, "level_v": -v, "counts": poisson(truth(v) * live), "live_s": live, "t": 0.0})
        rows = st.analyse_dark(points)["rows"]
        for r in rows:
            band = ("bend" if 0.0038 - 1e-9 <= r["abs_v"] <= 0.0060 + 1e-9 else
                    "roll-off" if 0.0022 - 1e-9 <= r["abs_v"] <= 0.0036 + 1e-9 else None)
            if band is None:
                continue
            new_err.setdefault(band, []).append(st._smooth_dark_rate(rows, r["abs_v"])[0] / truth(r["abs_v"]) - 1)
            old_err.setdefault(band, []).append(_straight_line_dark_rate(st, rows, r["abs_v"]) / truth(r["abs_v"]) - 1)
            single_err.setdefault(band, []).append(r["rate"] / truth(r["abs_v"]) - 1)

    def bias(errs):
        return sum(errs) / len(errs)

    def rms(errs):
        return math.sqrt(sum(e * e for e in errs) / len(errs))

    check(abs(bias(new_err["bend"])) < 0.025 and bias(old_err["bend"]) > 0.05,
          f"on a synthetic curve with a bend at 3.8-6 mV the fit's bias is {bias(new_err['bend']):+.1%}; "
          f"the straight line it replaced read {bias(old_err['bend']):+.1%}")
    check(rms(new_err["bend"]) < rms(single_err["bend"]),
          f"and it is still closer than single thresholds there ({rms(new_err['bend']):.1%} against "
          f"{rms(single_err['bend']):.1%} rms)")
    check(rms(new_err["roll-off"]) < 0.10 and rms(old_err["roll-off"]) > 0.3,
          f"on the steep roll-off (2.2-3.6 mV) its rms error is {rms(new_err['roll-off']):.1%}, "
          f"against {rms(old_err['roll-off']):.0%} for the straight line")

    # --- the real dark scans, held out threshold by threshold ---------------------------------
    real = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
                        "docs", "real_data", "2026-11-10")
    _, dp = st.read_scan_csv(os.path.join(real, "SR400_threshold_scan_dark_2026-11-10_132008.csv"))
    dark = st.analyse_dark(dp)
    rows = dark["rows"]

    def fitted(others, v):
        return st._smooth_dark_rate(others, v)[0]

    def straight(others, v):
        return _straight_line_dark_rate(st, others, v)

    for lo_v, hi_v, tol in ((0.0038, 0.0060, 0.03), (0.0022, 0.0036, 0.05)):
        new, old = _held_out_ratio(rows, fitted, lo_v, hi_v), _held_out_ratio(rows, straight, lo_v, hi_v)
        check(abs(new - 1) < tol and abs(old - 1) > 2 * tol,
              f"the real 13:20 dark scan, each threshold in {lo_v * 1e3:.1f}-{hi_v * 1e3:.1f} mV left out "
              f"and predicted from the rest: predicted/observed {new:.3f} (the straight line: {old:.3f})")
    dark2_csv = os.path.join(real, "SR400_threshold_scan_dark_2026-11-10_163608.csv")
    if os.path.exists(dark2_csv):
        rows2 = st.analyse_dark(st.read_scan_csv(dark2_csv)[1])["rows"]
        new2, old2 = _held_out_ratio(rows2, fitted, 0.0038, 0.0060), _held_out_ratio(rows2, straight, 0.0038, 0.0060)
        check(abs(new2 - 1) < 0.03 and abs(old2 - 1) > 0.06,
              f"the real 16:36 dark scan, 3.8-6.0 mV held out: predicted/observed {new2:.3f} "
              f"(the straight line: {old2:.3f})")
        tail2 = [r["abs_v"] for r in rows2 if r["abs_v"] >= 0.0062 - 1e-9]
        pairs2 = [(st._smooth_dark_rate(rows2, v), _straight_line_dark_rate(st, rows2, v)) for v in tail2]
        scored2 = [(a[0], b) for a, b in pairs2 if a is not None and b is not None]
        check(scored2 and all(abs(a / b - 1) < 1e-9 for a, b in scored2),
              f"and in its thin tail the fit is the straight line, unchanged ({len(scored2)} thresholds)")
    tail = [r["abs_v"] for r in rows if r["abs_v"] >= 0.0062 - 1e-9]
    pairs = [(st._smooth_dark_rate(rows, v), _straight_line_dark_rate(st, rows, v)) for v in tail]
    scored = [(new[0], old) for new, old in pairs if new is not None and old is not None]
    check(all((new is None) == (old is None) for new, old in pairs)
          and all(abs(new / old - 1) < 1e-9 for new, old in scored),
          f"in its thin tail (all {len(tail)} thresholds from 6.2 mV, {len(scored)} with enough counts to "
          f"fit) the fit is the straight line, unchanged")

    # --- below the valley: not scored, and said so ----------------------------------------------
    _, passes = st.read_scan_csv(os.path.join(real, "SR400_threshold_scan_light_2026-11-10_135935.csv"))
    result = st.analyse_light(passes, dark)
    ref = result["reference_v"]
    check(result["fom"] and abs(result["fom"][0]["abs_v"] - ref) < 1e-9 and result["fom_floor_v"] == ref,
          f"S/sqrt(B) is scored from the reference level ({ref * 1e3:.1f} mV) up, not below it")
    excess = result["subvalley_excess"]
    check(excess is not None and abs(excess[0] - 0.0022) < 1e-9 and 0.30 < excess[1] < 0.50,
          f"below the valley the real light-minus-dark exceeds the reference rate by "
          f"{excess[1]:.0%} at {excess[0] * 1e3:.1f} mV, which is recorded rather than scored")
    check(not result["optimum_at_floor"] and not result["band_at_floor"],
          "the real weak-signal optimum (6.8 mV) and its band stay clear of the floor")
    band_n, best_n = result["floor_band_from_n"], result["floor_best_from_n"]
    check(band_n is not None and best_n is not None and 300 < band_n < best_n < 2e4,
          f"and it says from which signal rate the floor limits the answer: the band reaches the valley "
          f"from ~{band_n:.0f}, the best level from ~{best_n:.0f} counts/s at the reference")
    findings = " ".join(st._light_findings(result, dark))
    check("scored from the reference level" in findings and "cannot say whether a lower level" in findings,
          "the findings under the figure state both")
    best = st._absolute_snr(result, dark)
    check(best is not None and best[1] >= ref - 1e-9,
          f"hv-compare's absolute S/sqrt(B) is scored from the reference up too (best at {best[1] * 1e3:.1f} mV)")
    published = open(os.path.join(real, "SR400_threshold_scan_light_2026-11-10_135935.svg"), encoding="utf-8").read()
    check("not scored" in published and "scored from the reference level" in published,
          "the committed real light figure shades the unscored region and says why")

    # --- a background with no roll-off: the optimum lands on the floor and the driver says so -----
    # A flat 5 counts/s dark rate makes S/sqrt(B) follow the photon fraction, which is largest at
    # the lowest scored level. The driver must flag that, not present the floor as an optimum.
    flat = st.analyse_dark([{"abs_v": r["abs_v"], "level_v": -r["abs_v"], "counts": 500, "live_s": 100.0, "t": 0.0}
                            for r in result["rows"]])
    floor = st.analyse_light(passes, flat)
    check(floor["optimum_at_floor"] and abs(floor["optimum_v"] - floor["reference_v"]) < 1e-9,
          f"with a flat background the optimum is the reference level itself ({floor['optimum_v'] * 1e3:.1f} mV) "
          f"and is flagged as at the floor")
    check("AT the reference level" in floor["recommended_basis"],
          "the recommendation's basis says it is at the lowest level scored")
    lines = st._light_findings(floor, flat)
    check(any(line.startswith("!The S/sqrt(B) optimum is AT the reference level") for line in lines),
          "the findings say so in red")
    svg = st.plot_light(floor, passes, flat, {"when": "test", "kind": "light"})
    check("OPTIMUM AT THE LOWEST SCORED LEVEL" in svg, "and panel (d) says so where the optimum is drawn")


def test_threshold_scans(driver):
    print("\n[24] discriminator threshold scans, dark and light, on a simulated R8486")

    import tempfile

    st = driver.selftest
    tmpdir = tempfile.mkdtemp(prefix="sr400_scan_")

    for name in ("run_threshold_scan_dark", "run_threshold_scan_light"):
        check(name in driver.Device.actions, f"{name} is declared as an action")

    # --- pure helpers ----------------------------------------------------------
    grid = st.threshold_grid()
    check(grid == sorted(grid), "the threshold grid is ascending")
    check(grid[0] == 0.0004 and grid[-1] == 0.040, f"it spans 0.4 to 40 mV (got {grid[0]}..{grid[-1]})")
    check(
        all(abs(v / 0.0002 - round(v / 0.0002)) < 1e-6 for v in grid),
        "every level is a multiple of the discriminator's 0.2 mV step",
    )
    probe = driver.Device()
    for request in (0.01, 0.013, 0.25, 1.0, 2.5, 7.7):
        ct = st._ceil_count_time(probe, request)
        cycles = ct * 1e7
        exponent = math.floor(math.log10(cycles))
        mantissa = cycles / 10**exponent
        check(
            ct >= request - 1e-12 and abs(mantissa - round(mantissa)) < 1e-6 and round(mantissa) <= 9,
            f"{request:g} s rounds UP to the settable {ct:g} s",
        )

    # --- dark, happy path --------------------------------------------------------
    sr400 = VirtualSR400(pmt={}, time_scale=1e5)
    device, log = _scan_device(driver, sr400, tmpdir)
    before = _instrument_snapshot(sr400)
    device.run_threshold_scan_dark()
    check(len(log["blocking"]) == 1 and "Cover the R8486" in log["blocking"][0],
          "the dark scan first shows a BLOCKING 'cover the PMT' prompt")
    check("no light" in log["blocking"][0].lower() if log["blocking"] else False,
          "and it says to ensure no light")
    summary = log["boxes"][-1] if log["boxes"] else ""
    check("lower bound" in summary, f"the summary carries the lower bound: {summary[:90]}")
    dark = getattr(device, "_dark_threshold_scan", None)
    check(dark is not None, "a valid dark scan is kept for the light scan to use")
    if dark:
        check(dark["noise_edge_v"] is not None and 0.004 <= dark["noise_edge_v"] <= 0.007,
              f"the noise edge is found where simulated noise meets 8 cps ({dark['noise_edge_v']})")
        check(dark["vanish_v"] is not None and dark["vanish_v"] > dark["noise_edge_v"] + 0.005,
              f"dark counts vanish well above the noise edge ({dark['vanish_v']})")
        check(dark["oscillating_below_v"] is not None,
              "the >1 Mcps region near 0 V is labelled noise/pickup, not dark counts")
        plateau = [r for r in dark["rows"] if r["counts"] >= st.DARK_TARGET_COUNTS * 0.9]
        check(bool(plateau), "adaptive timing reached the count target where the rate allowed")
        capped = [r for r in dark["rows"] if r["live_s"] > st.DARK_MAX_SECONDS + 1.0]
        check(not capped, f"no threshold ran past its time cap (got {[r['abs_v'] for r in capped]})")
    after = _instrument_snapshot(sr400)
    differing = {k: (before[k], after[k]) for k in before if before[k] != after[k]}
    check(not differing, f"the dark scan restored every setting (differing: {differing})")
    for command in ("SE", "ST", "RC"):
        offenders = [c for c in sr400.log if c.split()[0].upper() == command]
        check(not offenders, f"the dark scan never sent {command}")

    # --- progress in the debug log: one line per threshold ----------------------
    # Reported 2026-11-10: a 20-minute dark scan gave no visible sign of life.
    import contextlib
    import io

    sr400_p = VirtualSR400(pmt={}, time_scale=1e5)
    device_p, _ = _scan_device(driver, sr400_p, tmpdir)
    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        device_p.run_threshold_scan_dark()
    lines = [line for line in buffer.getvalue().splitlines() if "SR400 dark scan:" in line]
    measured = [line for line in lines if " at -" in line and "counts in" in line]
    dark_p = getattr(device_p, "_dark_threshold_scan", None) or {"rows": []}
    check(lines and "at most" in lines[0] and "min" in lines[0],
          f"the dark scan prints its worst-case duration first (got {lines[:1]})")
    check(len(measured) >= len(dark_p["rows"]) > 0,
          f"and one debug-log line per threshold ({len(measured)} lines, {len(dark_p['rows'])} thresholds)")
    check(measured and "Elapsed" in measured[-1] and "left" in measured[-1],
          f"each with elapsed and remaining time (last: {measured[-1] if measured else None})")
    check(any("threshold scan dark: findings" in line for line in buffer.getvalue().splitlines()),
          "and every report section is echoed to the debug log too")

    # --- the real tube's noise hump, simulated: the scan's new rules end to end ----------
    sr400_h = VirtualSR400(pmt={"noise_peak_v": 0.0012}, time_scale=1e5)
    device_h, log_h = _scan_device(driver, sr400_h, tmpdir)
    device_h.run_threshold_scan_dark()
    dark_h = getattr(device_h, "_dark_threshold_scan", None)
    check(dark_h is not None and dark_h["noise_edge_v"] is not None
          and dark_h["noise_edge_v"] > 0.0012 + 0.001,
          f"with a noise hump the edge is found above it, not at 0.4 mV "
          f"(got {dark_h and dark_h['noise_edge_v']})")
    if dark_h:
        rows_h = dark_h["rows"]
        fast = [r for r in rows_h if r["rate"] * st.DARK_FAST_SECONDS > st.DARK_FAST_TARGET_COUNTS * 1.2]
        check(fast and all(r["counts"] >= st.DARK_FAST_TARGET_COUNTS for r in fast),
              f"where 500 counts take under 10 s, a threshold counts to 500 "
              f"(short: {[(r['abs_v'], r['counts']) for r in fast if r['counts'] < 500]})")
        slow = [r for r in rows_h if 0 < r["rate"] * st.DARK_FAST_SECONDS < st.DARK_FAST_TARGET_COUNTS * 0.8
                and r["live_s"] < st.DARK_MAX_SECONDS * 0.999]
        check(all(r["counts"] < st.DARK_FAST_TARGET_COUNTS for r in slow),
              "and a slow one still stops at 200, not 500")
        steps = [b["abs_v"] - a["abs_v"] for a, b in zip(rows_h, rows_h[1:])]
        slow_from = next((i for i in range(1, len(rows_h))
                          if rows_h[i]["rate"] < 1.0 and rows_h[i - 1]["rate"] < 1.0), None)
        check(slow_from is not None and all(step >= 0.002 - 1e-9 for step in steps[slow_from:]),
              f"after two thresholds below 1 cps, the scan steps 2 mV at a time "
              f"(steps from there: {[round(x * 1e3, 1) for x in steps[slow_from or 0:]]})")
        last = rows_h[-st.DARK_STOP_AFTER:]
        earlier = rows_h[:-st.DARK_STOP_AFTER]
        check(all(r["rate"] < st.DARK_STOP_BELOW_CPS for r in last)
              and not (earlier and earlier[-1]["rate"] < st.DARK_STOP_BELOW_CPS
                       and all(r["rate"] < st.DARK_STOP_BELOW_CPS for r in rows_h[-st.DARK_STOP_AFTER - 1:-1])),
              f"it stops at the third threshold in a row below 0.5 cps, not later "
              f"(last rates {[round(r['rate'], 3) for r in rows_h[-4:]]})")
        check(rows_h[-1]["abs_v"] < 0.040 - 1e-9, f"so short of the grid's 40 mV end "
                                                  f"(stopped at {rows_h[-1]['abs_v'] * 1e3:.1f} mV)")
        texts = [f for f in os.listdir(_report_dir(tmpdir)) if f.startswith("SR400_threshold_scan_dark") and f.endswith(".txt")]
        newest = open(os.path.join(_report_dir(tmpdir), sorted(texts)[-1])).read() if texts else ""
        check("thresholds in a row below 0.5 cps" in newest and "is not measured" in newest,
              "and the report says why it stopped, and that the vanish level is not measured")

    # --- a quiet tube: below 1 cps early, yet fine steps and no stop until 10 mV -------------
    # The real 16:36 dark scan went coarse at 7.2 mV, inside the S/sqrt(B) optimum region.
    # Its own folder: the checks below read the newest dark row of tmpdir's test log.
    sr400_q = VirtualSR400(pmt={"dark_rate": 1.0}, time_scale=1e5)
    device_q, _ = _scan_device(driver, sr400_q, tempfile.mkdtemp(prefix="sr400_quiet_"))
    device_q.run_threshold_scan_dark()
    dark_q = getattr(device_q, "_dark_threshold_scan", None)
    if dark_q:
        rows_q = dark_q["rows"]
        below_1 = [r["abs_v"] for r in rows_q if r["rate"] < 1.0 and r["abs_v"] > 0.003]
        steps_below_floor = [round((b["abs_v"] - a["abs_v"]) * 1e3, 1) for a, b in zip(rows_q, rows_q[1:])
                             if b["abs_v"] <= st.DARK_TAIL_FROM_V + 1e-9]
        check(below_1 and min(below_1) < st.DARK_TAIL_FROM_V,
              f"the quiet tube is below 1 cps well under 10 mV (from {min(below_1) * 1e3 if below_1 else None} mV)")
        check(max(steps_below_floor) <= 0.4 + 1e-9,
              f"but the scan keeps its fine grid up to 10 mV (largest step there "
              f"{max(steps_below_floor)} mV)")
        check(rows_q[-1]["abs_v"] >= st.DARK_TAIL_FROM_V - 1e-9,
              f"and does not stop before 10 mV (stopped at {rows_q[-1]['abs_v'] * 1e3:.1f} mV)")
        in_region = [r for r in rows_q if 0.006 - 1e-9 <= r["abs_v"] <= 0.010 + 1e-9]
        check(len(in_region) >= 10, f"so 6-10 mV, where the background fit works, has {len(in_region)} thresholds")

    # --- light, with the dark scan in hand --------------------------------------
    sr400.pmt["light_rate"] = 5.0e4
    log["boxes"].clear(); log["blocking"].clear()
    before = _instrument_snapshot(sr400)
    device.run_threshold_scan_light()
    check(len(log["blocking"]) == 1 and "gentle" in log["blocking"][0].lower(),
          "the light scan first shows a BLOCKING 'gentle light' prompt")
    summary = log["boxes"][-1] if log["boxes"] else ""
    check("recommended A DISC LVL" in summary, f"a level is recommended: {summary[:140]}")
    reports = sorted(f for f in os.listdir(_report_dir(tmpdir)) if f.startswith("SR400_threshold_scan_light"))
    text = open(os.path.join(_report_dir(tmpdir), reports[-1])).read() if reports else ""
    check("S/sqrt(B)" in text, "with a dark scan, the optimum comes from S/sqrt(B)")
    m = re.search(r"RECOMMENDED A DISC LVL: -([0-9.]+) mV", text)
    rec = float(m.group(1)) / 1e3 if m else None
    if dark and rec is not None:
        check(dark["noise_edge_v"] <= rec < dark["vanish_v"],
              f"the optimum ({rec * 1e3:.1f} mV) sits above the noise edge and below where dark "
              f"counts vanish")
    check("fewer photons" in text, "the report prices the level where dark counts vanish")
    m = re.search(r"counts ([0-9.]+)% fewer photons", text)
    check(m is not None and float(m.group(1)) > 50.0,
          f"and it is a large loss -- the proof that zero dark counts is not optimal ({m.group(1) if m else '?'} %)")
    check("valley:" in text, "a valley is resolved in the simulated tube")
    check("EMPTY at this gain" in text,
          "the strict noise-edge-to-1 %-loss window is reported empty, as expected unamplified")
    after = _instrument_snapshot(sr400)
    differing = {k: (before[k], after[k]) for k in before if before[k] != after[k]}
    check(not differing, f"the light scan restored every setting (differing: {differing})")

    # --- the test log carries the thresholds as numbers, signed as typed into the GUI ---
    import csv

    with open(os.path.join(_report_dir(tmpdir), st.Report.LOG_NAME), newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    dark_rows = [r for r in rows if r["test"] == "threshold scan dark"]
    light_rows = [r for r in rows if r["test"] == "threshold scan light"]
    dark_row = dark_rows[-1] if dark_rows else {}
    light_row = light_rows[-1] if light_rows else {}
    if dark:
        check(
            dark_row.get("lower_bound_V") == str(round(-dark["lower_bound_v"], 4))
            and dark_row.get("dark_counts_vanish_V") == str(round(-dark["vanish_v"], 4)),
            f"the dark row logs its lower bound and vanish level in GUI volts (got {dark_row})",
        )
    if rec is not None:
        check(
            light_row.get("recommended_disc_A_level_V") == str(round(-rec, 4)),
            f"the light row logs the recommended level, ready to type in (got "
            f"{light_row.get('recommended_disc_A_level_V')!r}, report says -{rec * 1e3:.1f} mV)",
        )
    fraction = light_row.get("photons_counted_at_recommended", "")
    check(fraction != "" and 0.0 < float(fraction) <= 1.0,
          f"and the fraction of photons counted there (got {fraction!r})")
    check(light_row.get("upper_bound_1pct_loss_V", "") != "",
          f"and the 1 %-loss upper bound (got {light_row.get('upper_bound_1pct_loss_V')!r})")

    # --- light in a later session: the dark scan is loaded from its CSV on disk ----
    # Reported 2026-11-10: after a SweepMe! restart the light scan had no dark scan, so panel
    # (d) was empty, although the dark scan's CSV was in the same folder.
    sr400 = VirtualSR400(pmt={"light_rate": 5.0e4}, time_scale=1e5)
    device, log = _scan_device(driver, sr400, tmpdir)  # a fresh instance: nothing in memory
    check(getattr(device, "_dark_threshold_scan", None) is None, "a fresh instance holds no dark scan")
    device.run_threshold_scan_light()
    reports = sorted(f for f in os.listdir(_report_dir(tmpdir)) if f.startswith("SR400_threshold_scan_light"))
    text = open(os.path.join(_report_dir(tmpdir), reports[-1])).read() if reports else ""
    check("loaded SR400_threshold_scan_dark_" in text and "from disk" in text,
          "with no dark scan in memory, the newest same-port dark CSV is loaded from disk, and the report says so")
    check("S/sqrt(B)" in text and "run the dark scan for the optimum" not in text,
          "so the S/sqrt(B) optimum, panel (d), is computed after all")
    light_csvs = sorted(f for f in os.listdir(_report_dir(tmpdir))
                        if f.startswith("SR400_threshold_scan_light") and f.endswith(".csv"))
    head = open(os.path.join(_report_dir(tmpdir), light_csvs[-1]), encoding="utf-8").read(600) if light_csvs else ""
    check("# dark_csv: SR400_threshold_scan_dark_" in head,
          "and the light CSV names that dark file, so a regenerated plot finds it too")

    sr400 = VirtualSR400(pmt={"light_rate": 5.0e4}, time_scale=1e5)
    device, log = _scan_device(driver, sr400, tmpdir)
    device.port_string = "GPIB0::5::INSTR"  # another instrument: its dark scan does not apply
    device.run_threshold_scan_light()
    reports = sorted(f for f in os.listdir(_report_dir(tmpdir)) if f.startswith("SR400_threshold_scan_light"))
    text = open(os.path.join(_report_dir(tmpdir), reports[-1])).read() if reports else ""
    check("from disk" not in text, "a dark scan from a different port is never loaded")

    # --- light with no dark scan anywhere: still recommends, says why it is weaker --------
    lonely = tempfile.mkdtemp(prefix="sr400_scan_nodark_")
    sr400 = VirtualSR400(pmt={"light_rate": 5.0e4}, time_scale=1e5)
    device, log = _scan_device(driver, sr400, lonely)
    device.run_threshold_scan_light()
    summary = log["boxes"][-1] if log["boxes"] else ""
    check("recommended A DISC LVL" in summary, f"without a dark scan it still recommends: {summary[:100]}")
    reports = sorted(f for f in os.listdir(_report_dir(lonely)) if f.startswith("SR400_threshold_scan_light"))
    text = open(os.path.join(_report_dir(lonely), reports[-1])).read() if reports else ""
    check("run the dark scan for the optimum" in text, "and says the dark scan would give the optimum")

    # --- light refused at the probe ----------------------------------------------
    for label, rate, needle in (("no light", 0.0, "no usable light"),
                                ("too bright", 5.0e6, "too bright")):
        sr400 = VirtualSR400(pmt={"light_rate": rate}, time_scale=1e5)
        device, log = _scan_device(driver, sr400, tmpdir)
        before_traffic = len(sr400.log)
        device.run_threshold_scan_light()
        summary = log["boxes"][-1] if log["boxes"] else ""
        check(needle in summary, f"{label}: the light scan stops at the probe ({summary[:80]})")
        # Writes only (a query has no comma): the probe level, then the restore. Nothing else.
        sweeps = sum(1 for c in sr400.log[before_traffic:] if c.startswith("DL 0,"))
        check(sweeps <= 2, f"{label}: and does not go on to sweep ({sweeps} DL level writes)")

    # --- dark refused: light leak, and nothing connected ---------------------------
    sr400 = VirtualSR400(pmt={"light_rate": 5.0e4}, time_scale=1e5)
    device, log = _scan_device(driver, sr400, tmpdir)
    device.run_threshold_scan_dark()
    summary = log["boxes"][-1] if log["boxes"] else ""
    check("no lower bound" in summary and "Light is reaching the tube" in summary,
          f"an uncovered tube is caught by the data, whatever was acknowledged ({summary[:110]})")
    check(getattr(device, "_dark_threshold_scan", None) is None,
          "and the invalid dark scan is not kept")

    sr400 = VirtualSR400(pmt={"dark_rate": 0.0, "noise_rate": 0.0}, time_scale=1e5)
    device, log = _scan_device(driver, sr400, tmpdir)
    device.run_threshold_scan_dark()
    summary = log["boxes"][-1] if log["boxes"] else ""
    check("nothing is reaching SIGNAL INPUT 1" in summary,
          f"no signal at all is diagnosed as a cabling/HV problem ({summary[:110]})")

    # --- drift between passes is flagged, and blocks the recommendation ----------
    sr400 = VirtualSR400(pmt={"light_rate": 5.0e4}, time_scale=1e5)
    device, log = _scan_device(driver, sr400, tmpdir)

    def brighten_after_each_pass(message, _log=log["info"], _sr=sr400):
        _log.append(message)
        if "done" in message:
            _sr.pmt["light_rate"] *= 1.05  # 5 % brighter every pass

    device.message_info = brighten_after_each_pass
    device.run_threshold_scan_light()
    summary = log["boxes"][-1] if log["boxes"] else ""
    check("no recommendation" in summary and "light level changed" in summary,
          f"a source brightening 5 % per pass is flagged as drift ({summary[:120]})")

    # --- hysteresis is measured as a shift, in mV -----------------------------------
    sr400 = VirtualSR400(pmt={"light_rate": 5.0e4, "hysteresis_v": 0.0006}, time_scale=1e5)
    device, log = _scan_device(driver, sr400, tmpdir)
    device.run_threshold_scan_light()
    reports = sorted(f for f in os.listdir(_report_dir(tmpdir)) if f.startswith("SR400_threshold_scan_light"))
    text = open(os.path.join(_report_dir(tmpdir), reports[-1])).read() if reports else ""
    m = re.search(r"up-minus-down shift ([+-][0-9.]+) \+- ([0-9.]+) mV", text)
    shift = float(m.group(1)) if m else None
    check(shift is not None and 0.4 <= shift <= 0.8,
          f"0.6 mV of injected hysteresis is measured as {shift} mV")
    check("FAIL  no discriminator hysteresis" in text, "and flagged as a failed check")

    # --- refuses while counting ----------------------------------------------------
    sr400 = VirtualSR400(pmt={}, time_scale=1e5)
    device, log = _scan_device(driver, sr400, tmpdir)
    sr400.secondary |= 1 << 2
    device.run_threshold_scan_dark()
    check(not log["blocking"], "while counting, the scan refuses BEFORE prompting")
    check(any("counting" in str(b) for b in log["boxes"]), "and says the SR400 is counting")


def _newest(folder, prefix, suffix):
    found = sorted(f for f in os.listdir(folder) if f.startswith(prefix) and f.endswith(suffix)) \
        if os.path.isdir(folder) else []
    return os.path.join(folder, found[-1]) if found else None


def test_scan_records_and_plots(driver):
    print("\n[25] both scans record raw data and write a plot, regenerable from the data alone")

    import subprocess
    import tempfile
    import xml.etree.ElementTree as ET

    st = driver.selftest

    # --- a normal session: dark, then light -----------------------------------------
    tmpdir = tempfile.mkdtemp(prefix="sr400_plots_")
    folder = _report_dir(tmpdir)
    sr400 = VirtualSR400(pmt={}, time_scale=1e5)
    device, log = _scan_device(driver, sr400, tmpdir)
    device.run_threshold_scan_dark()
    dark_summary = log["boxes"][-1] if log["boxes"] else ""
    sr400.pmt["light_rate"] = 5.0e4
    device.run_threshold_scan_light()
    light_summary = log["boxes"][-1] if log["boxes"] else ""

    for kind, summary in (("dark", dark_summary), ("light", light_summary)):
        stem = f"SR400_threshold_scan_{kind}"
        txt, csv, svg = (_newest(folder, stem, x) for x in (".txt", ".csv", ".svg"))
        check(all((txt, csv, svg)), f"the {kind} scan wrote a report, a CSV and an SVG side by side")
        if not all((txt, csv, svg)):
            continue
        check(os.path.splitext(txt)[0] == os.path.splitext(csv)[0] == os.path.splitext(svg)[0],
              f"the three {kind} files share one stem, so they are always found together")
        check("Plot (opens in any web browser)" in summary and svg in summary,
              f"the {kind} closing message gives the plot's path")
        check("Raw data" in summary and csv in summary, f"and the CSV's path")
        try:
            root = ET.parse(svg).getroot()
            check(root.tag.endswith("svg"), f"the {kind} SVG is well-formed XML with an <svg> root")
        except ET.ParseError as exc:
            check(False, f"the {kind} SVG is well-formed XML ({exc})")
        header = open(csv, encoding="utf-8").read().splitlines()
        columns = next(line for line in header if not line.startswith("#"))
        check("counts" in columns and "live_s" in columns and "rate" not in columns,
              f"the {kind} CSV holds raw counts and live time, not derived rates ({columns})")

    # --- regenerable: the analysis from the CSV alone matches the live one ------------------
    dark_csv = _newest(folder, "SR400_threshold_scan_dark", ".csv")
    light_csv = _newest(folder, "SR400_threshold_scan_light", ".csv")
    if dark_csv and light_csv:
        live = device._dark_threshold_scan
        meta, points = st.read_scan_csv(dark_csv)
        again = st.analyse_dark(points)
        check(meta.get("kind") == "dark" and len(points) == len(live["rows"]),
              f"the dark CSV round-trips every threshold ({len(points)} of {len(live['rows'])})")
        for key in ("noise_edge_v", "vanish_v", "lower_bound_v"):
            check(again[key] == live[key], f"re-analysis from the CSV gives the same {key}")

        meta, passes = st.read_scan_csv(light_csv)
        check(meta.get("dark_csv") == os.path.basename(dark_csv),
              "the light CSV names the dark CSV it was scored against")
        check(len(passes) == 2 * st.LIGHT_REPEATS, f"it round-trips every pass ({len(passes)})")
        live_light = st.analyse_light(passes, again)
        text = open(_newest(folder, "SR400_threshold_scan_light", ".txt")).read()
        m = re.search(r"RECOMMENDED A DISC LVL: -([0-9.]+) mV", text)
        check(m is not None and live_light["recommended_v"] is not None
              and abs(live_light["recommended_v"] * 1e3 - float(m.group(1))) < 1e-9,
              "re-analysis of the light CSV with the dark CSV gives the same recommendation")

        # The command line regenerates the figure on a machine with nothing but Python.
        regenerated = os.path.join(tmpdir, "copy.csv")
        with open(light_csv, encoding="utf-8") as src, open(regenerated, "w", encoding="utf-8") as dst:
            dst.write(src.read())
        import shutil
        shutil.copy(dark_csv, os.path.join(tmpdir, os.path.basename(dark_csv)))
        script = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "selftest.py")
        run = subprocess.run([sys.executable, script, "plot", regenerated], capture_output=True, text=True)
        out_svg = os.path.splitext(regenerated)[0] + ".svg"
        check(run.returncode == 0 and os.path.exists(out_svg),
              f"'python selftest.py plot <csv>' regenerates the figure ({run.returncode}, {run.stderr[-120:]})")
        if os.path.exists(out_svg):
            body = open(out_svg, encoding="utf-8").read()
            check("RECOMMENDED A DISC LVL" in body and "S/sqrt(B), relative" in body,
                  "and the regenerated light figure found the dark CSV and scored S/sqrt(B)")

    # --- the figures refuse what the data cannot support --------------------------------
    tmpdir = tempfile.mkdtemp(prefix="sr400_plots_")
    folder = _report_dir(tmpdir)
    sr400 = VirtualSR400(pmt={"light_rate": 5.0e4}, time_scale=1e5)  # lit: invalid dark scan
    device, log = _scan_device(driver, sr400, tmpdir)
    device.run_threshold_scan_dark()
    svg = _newest(folder, "SR400_threshold_scan_dark", ".svg")
    body = open(svg, encoding="utf-8").read() if svg else ""
    check("INVALID" in body, "an invalid dark scan is plotted, and says INVALID on the figure")
    check(re.search(r"lower bound \d", body) is None,
          "and offers NO lower bound anywhere on it -- not readable off as an operating level")
    check("diagnostic only" in body, "its noise edge is labelled a diagnostic, not a bound")
    check(_newest(folder, "SR400_threshold_scan_dark", ".csv") is not None,
          "the invalid scan's raw data is still recorded")

    tmpdir = tempfile.mkdtemp(prefix="sr400_plots_")
    folder = _report_dir(tmpdir)
    sr400 = VirtualSR400(pmt={"light_rate": 5.0e4}, time_scale=1e5)
    device, log = _scan_device(driver, sr400, tmpdir)

    def brighten(message, _sr=sr400):
        if "done" in message:
            _sr.pmt["light_rate"] *= 1.05

    device.message_info = brighten
    device.run_threshold_scan_light()
    svg = _newest(folder, "SR400_threshold_scan_light", ".svg")
    body = open(svg, encoding="utf-8").read() if svg else ""
    check("NO RECOMMENDATION" in body, "a drifting light scan is plotted with NO RECOMMENDATION")
    check("UNRELIABLE under drift" in body, "and its loss levels are labelled unreliable, not stated as fact")
    check("NOT SHOWN" in body, "and S/sqrt(B) is marked NOT SHOWN, with its reason, without a dark scan")

    # --- early exits still report the restore (the report was once written before it) ----
    tmpdir = tempfile.mkdtemp(prefix="sr400_plots_")
    folder = _report_dir(tmpdir)
    sr400 = VirtualSR400(pmt={"light_rate": 0.0}, time_scale=1e5)
    device, log = _scan_device(driver, sr400, tmpdir)
    device.run_threshold_scan_light()
    txt = _newest(folder, "SR400_threshold_scan_light", ".txt")
    text = open(txt).read() if txt else ""
    check("== restore" in text and "every changed setting was restored" in text,
          "a light scan refused at the probe still reports the restore")
    check(_newest(folder, "SR400_threshold_scan_light", ".svg") is None,
          "and writes no plot: there was no sweep to plot")

    sr400 = VirtualSR400()
    sr400.rate["INPUT 2"] = 0.0
    device = make_device(driver, sr400, **{"Counter A input": "10 MHz"})
    device.get_folder = lambda identifier: tmpdir
    device.message_box = lambda message, blocking=False: None
    device.message_info = lambda message: None
    device.run_self_test_loopback()
    txt = _newest(folder, "SR400_self_test_tier_2", ".txt")
    text = open(txt).read() if txt else ""
    check("== restore" in text, "a tier-2 run stopped at the cable probe still reports the restore")


def test_guide_example_figures(driver):
    print("\n[26] the guide's example figures match what the plotting code makes from their CSVs")

    import shutil
    import tempfile

    st = driver.selftest
    images = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
                          "docs", "images")
    names = ("example_threshold_scan_dark", "example_threshold_scan_light")
    for name in names:
        for suffix in (".csv", ".svg"):
            check(os.path.exists(os.path.join(images, name + suffix)),
                  f"docs/images/{name}{suffix} is committed")

    # Regenerate in a scratch folder, never in docs/: the test must not rewrite what it checks.
    work = tempfile.mkdtemp(prefix="sr400_examples_")
    for name in names:
        if os.path.exists(os.path.join(images, name + ".csv")):
            shutil.copy(os.path.join(images, name + ".csv"), work)
    for name in names:
        csv_path = os.path.join(work, name + ".csv")
        committed = os.path.join(images, name + ".svg")
        if not (os.path.exists(csv_path) and os.path.exists(committed)):
            continue
        fresh = open(st.plot_csv(csv_path), encoding="utf-8").read()
        published = open(committed, encoding="utf-8").read()
        # A mismatch means the plotting code changed and the guide shows an old figure.
        # Regenerate with: python Logger-Stanford_SR400/selftest.py plot docs/images/<name>.csv
        check(fresh == published,
              f"{name}.svg is exactly what selftest.py plot makes from its CSV -- if not, regenerate it")
        check("SIMULATED EXAMPLE" in published,
              f"{name}.svg says on the figure that it is simulated")

    text = open(os.path.join(images, "example_threshold_scan_light.csv"), encoding="utf-8").read()
    check("# dark_csv: example_threshold_scan_dark.csv" in text,
          "the light example is scored against the dark example, by name")
    check("S/sqrt(B), relative" in open(os.path.join(images, "example_threshold_scan_light.svg"),
                                        encoding="utf-8").read(),
          "so the light example shows the S/sqrt(B) panel the guide describes")


def main() -> int:
    driver_path = Path(__file__).resolve().parent.parent / "main.py"
    driver = load_driver(driver_path)

    print("Virtual test bench for the SweepMe! SR400 driver")
    print("=" * 70)

    for test in (
        test_single_point,
        test_multiple_periods,
        test_external_dwell,
        test_gate_delay_configuration,
        test_count_time_and_rounding,
        test_discriminator_and_port_configuration,
        test_b_preset_mode,
        test_parameter_validation,
        test_instrument_error_reporting,
        test_timeout,
        test_echo_detection,
        test_wrapped_command_layer,
        test_front_panel_lock_lifecycle,
        test_gpib_specifics,
        test_reset_at_start,
        test_ported_gui_options,
        test_measurement_modes,
        test_latency_detection,
        test_latency_actions,
        test_batched_readout,
        test_count_time_planner,
        test_auto_split_mode,
        test_self_test_actions,
        test_end_of_run_tests,
        test_gpib_drain,
        test_real_dark_scan,
        test_real_scans_in_repo,
        test_settling_and_hv,
        test_log_migration_and_smooth_background,
        test_curved_background_and_valley_floor,
        test_threshold_scans,
        test_scan_records_and_plots,
        test_guide_example_figures,
    ):
        test(driver)

    print("\n" + "=" * 70)
    print(f"{CHECKS - len(FAILURES)}/{CHECKS} checks passed")
    for failure in FAILURES:
        print(f"  FAILED: {failure}")

    return 1 if FAILURES else 0


if __name__ == "__main__":
    sys.exit(main())
