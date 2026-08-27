"""Virtual test bench for the SweepMe! SR400 driver.

Implements a simulator of the SR400 command set (as documented in the SR400 manual, chapter
"REMOTE PROGRAMMING") behind the pysweepme port interface (write/read) and runs the complete
SweepMe! driver lifecycle against it.

Run with:  python tests/test_sr400_virtual.py
"""

from __future__ import annotations

import importlib.util
import math
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


class VirtualSR400:
    """A minimal but faithful SR400 that speaks the documented ASCII protocol."""

    def __init__(self, rate_input1: float = 5.0e4, rate_input2: float = 1.0e3, echo: bool = False):
        self.rate = {"10 MHz": CLOCK, "INPUT 1": rate_input1, "INPUT 2": rate_input2, "TRIG": 1.0e3}
        self.echo = echo

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

    # SR400 buffer limits (manual, "ERRORS/DATA WINDOW" and the interface sections). The
    # simulator enforces them so that a driver which overruns a buffer fails on the bench
    # instead of appearing to work here and losing a scan on real hardware.
    COMMAND_LINE_ERROR_CHARS = 240
    OUTPUT_BUFFER_CHARS = 256

    # ---------------------------------------------------------------- port API
    def write(self, command: str) -> None:
        self.log.append(command)
        if self.echo:  # ECHO = ON returns the command and an OK> prompt
            self.out.append(command)
            self.out.append("OK>")

        # Too long a command line sets the command-error bit and every command still queued on
        # that line is discarded (manual: "any commands remaining on the current command line
        # (up to the next <cr>) are lost").
        if len(command) + 1 > self.COMMAND_LINE_ERROR_CHARS:
            self.status |= 1 << 7
            self.line_overflowed = True
            return

        for single in command.split(";"):
            self._execute(single.strip())

    def read(self) -> str:
        return self.out.pop(0) if self.out else ""

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
            return self.preset[1] / max(self.rate[self._input_name(1)], 1e-12)
        source = self._input_name(2)
        return self.preset[2] / max(self.rate[source], 1e-12)

    def _input_name(self, counter: int) -> str:
        names = {0: "10 MHz", 1: "INPUT 1", 2: "INPUT 2", 3: "TRIG"}
        return names[self.counter_input[counter]]

    def _counts_for_period(self) -> tuple[int, int]:
        duration = self.count_time
        counts_a = int(round(self.rate[self._input_name(0)] * duration))
        counts_b = int(round(self.rate[self._input_name(1)] * duration))
        if self.counting_mode == 3:
            counts_b = -1  # counter B is the preset counter
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

        elapsed = time.time() - self.period_start

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
        self.disc_level[i] = self._limit(float(a[1]), -0.3000, 0.3000)

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
        driver.Device.actions == ["report_com_port_latency", "reduce_com_port_latency"],
        f"both actions are declared (got {driver.Device.actions})",
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
    ):
        test(driver)

    print("\n" + "=" * 70)
    print(f"{CHECKS - len(FAILURES)}/{CHECKS} checks passed")
    for failure in FAILURES:
        print(f"  FAILED: {failure}")

    return 1 if FAILURES else 0


if __name__ == "__main__":
    sys.exit(main())
