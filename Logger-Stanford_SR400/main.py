# This Device Class is published under the terms of the MIT License.
# Required Third Party Libraries, which are included in the Device Class
# package for convenience purposes, may have a different license. You can
# find those in the corresponding folders or contact the maintainer.
#
# MIT License
#
# Copyright (c) 2026 SweepMe! GmbH (sweep-me.net)
#
# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in all
# copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
# SOFTWARE.

# SweepMe! device class
# Type: Logger
# Device: Stanford Research Systems SR400 (gated photon counter)
#
# All instrument commands used below are taken from the SR400 manual,
# chapter "REMOTE PROGRAMMING -- DETAILED COMMAND LIST" (manual pp. 37-47).
# No command is used that is not documented there.

from __future__ import annotations

import math
import time

from pysweepme.EmptyDeviceClass import EmptyDevice


class Device(EmptyDevice):
    """Driver for the Stanford Research Systems SR400 two-channel gated photon counter."""

    description = """
        <h3>Stanford Research Systems SR400</h3>
        <p>Two-channel gated photon counter, in two measurement modes:</p>
        <ul>
        <li><b>Single count period</b> (default) &mdash; one SweepMe! point is one SR400 count
        period. The driver forces NP 1 and an EXTERNAL dwell and starts each period itself, so
        SweepMe! owns the point sequence. Simplest to reason about, fewest round trips.</li>
        <li><b>Scan of N periods</b> &mdash; one SweepMe! point is one SR400 scan of
        "Periods per point" count periods with the instrument's internal dwell. The SR400 runs
        the scan itself and the counts of all periods are summed. "Periods per point" and
        "Dwell time in s" only apply here.</li>
        </ul>

        <h4>Setup</h4>
        <ul>
        <li><b>RS-232:</b> in the SR400 COM menu set BAUD, BITS and PARITY to match the port settings
        (driver default: 9600, 8, none) and set <b>RS-232 ECHO = OFF</b>. With echo ON the SR400 sends
        the command back plus "OK&gt;" prompts and this driver cannot read any value.</li>
        <li>If a previous program changed the RS-232 end-of-record sequence with the SE command,
        enable "Reset instrument at start" once (CL restores the default terminator, a single CR).</li>
        <li><b>GPIB:</b> set the GPIB address (1...30) in the COM menu. Nothing else is needed.</li>
        <li>The SR400 has no *IDN? command. The driver verifies the connection by reading the
        counting mode (CM).</li>
        </ul>

        <h4>Measurement</h4>
        <ul>
        <li>Counter A, B: summed counts of all count periods of one point.</li>
        <li>Count time: gross count period length summed over all periods. It is only known if
        counter T is preset and its input is the internal 10 MHz clock; otherwise NaN is returned.
        The count time is <i>not</i> corrected for the gate duty cycle, so "Rate" is counts per
        gross count time, not per gate-open time.</li>
        <li>Counting mode "A for B preset" presets counter B. The SR400 then returns -1 for QB, so
        Counter B and Rate B are reported as NaN.</li>
        </ul>

        <h4>Instrument resolution limits (manual, command list)</h4>
        <ul>
        <li>Counter presets (CP) and the dwell time (DT) keep <b>only one significant digit</b>.
        The driver rounds to the nearest allowed value and reads the applied value back, so
        "Count time" always reports what the SR400 really used.</li>
        <li>Count time = T preset / 10 MHz, so the shortest count period is 0.1 us and the
        achievable values are 1, 2, ... 9 x 10^k clock cycles.</li>
        <li>Gate delay/width have a variable resolution (1 part in 1000, 1 ns below 1 us);
        the SR400 rounds to the nearest allowed value itself.</li>
        <li>Trigger level 1 mV, discriminator level 0.2 mV, PORT level 5 mV.</li>
        </ul>

        <h4>Error reporting</h4>
        <p>The status byte (SS) is read before and while counting. A command error (illegal command
        or parameter out of range) and a counter overrun (counter reached 1E9-1 counts, i.e. the
        counts are invalid) raise an exception. A rate error (a missed gate: gate delay or width
        exceeds the trigger period minus 1 us) is reported as a message.</p>
        """

    # ---------------------------------------------------------------- constants
    # taken from the SR400 manual, abridged and detailed command lists

    CLOCK_FREQUENCY = 1e7
    """Frequency of the internal timebase in Hz. T preset is given in clock cycles, not seconds."""

    COUNTER_INDICES = {"A": 0, "B": 1, "T": 2}
    GATE_INDICES = {"A": 0, "B": 1}

    COUNTING_MODES = {
        "A, B for T preset": 0,
        "A-B for T preset": 1,
        "A+B for T preset": 2,
        "A for B preset": 3,
    }
    COUNTER_INPUTS = {"10 MHz": 0, "INPUT 1": 1, "INPUT 2": 2, "TRIG": 3}
    ALLOWED_COUNTER_INPUTS = {
        "A": ("10 MHz", "INPUT 1"),
        "B": ("INPUT 1", "INPUT 2"),
        "T": ("10 MHz", "INPUT 2", "TRIG"),
    }
    MEASUREMENT_MODES = ("Single count period", "Scan of N periods")
    """How one SweepMe! point maps onto SR400 count periods. See _apply_measurement_mode()."""

    SLOPES = {"Rise": 0, "Fall": 1}
    DISCRIMINATOR_MODES = {"Fixed": 0, "Scan": 1}
    GATE_MODES = {"CW": 0, "Fixed": 1, "Scan": 2}
    PORT_MODES = {"Fixed": 0, "Scan": 1}
    SCAN_END_MODES = {"Stop": 0, "Start": 1}
    DISPLAY_MODES = {"Continuous": 0, "Hold": 1}
    DAC_SOURCES = {"A": 0, "B": 1, "A-B": 2, "A+B": 3}
    FRONT_PANEL_MODES = {"Local": 0, "Remote": 1, "Locked out": 2}

    PRESET_MIN = 1.0
    PRESET_MAX = 9e11
    PERIODS_MAX = 2000
    DWELL_MIN = 2e-3
    DEFAULT_DWELL_TIME = 2e-3
    DWELL_MAX = 6e1
    TRIGGER_LEVEL_LIMIT = 2.000
    DISCRIMINATOR_LEVEL_LIMIT = 0.3000
    DISCRIMINATOR_STEP_LIMIT = 0.0200
    PORT_LEVEL_LIMIT = 10.000
    PORT_STEP_LIMIT = 0.500
    GATE_DELAY_MAX = 999.2e-3
    GATE_WIDTH_MIN = 0.005e-6
    GATE_WIDTH_MAX = 999.2e-3
    GATE_STEP_MAX = 99.92e-3
    RS232_WAIT_MAX = 25

    # status byte bits (manual, section "STATUS BYTE")
    STATUS_PARAMETER_CHANGED = 1 << 0
    STATUS_DATA_READY = 1 << 1
    STATUS_SCAN_FINISHED = 1 << 2
    STATUS_COUNTER_OVERRUN = 1 << 3
    STATUS_RATE_ERROR = 1 << 4
    STATUS_RECALL_ERROR = 1 << 5
    STATUS_SRQ = 1 << 6
    STATUS_COMMAND_ERROR = 1 << 7

    # secondary status byte bits (manual, section "SECONDARY STATUS BYTE")
    SECONDARY_TRIGGERED = 1 << 0
    SECONDARY_INHIBITED = 1 << 1
    SECONDARY_COUNTING = 1 << 2

    def __init__(self) -> None:
        """Define the driver interface, the output variables and the port properties."""
        super().__init__()

        self.shortname = "SR400"

        self.variables = ["Counter A", "Counter B", "Rate A", "Rate B", "Count time"]
        self.units = ["", "", "1/s", "1/s", "s"]
        self.plottype = [True, True, True, True, True]
        self.savetype = [True, True, True, True, True]

        # --- communication ---------------------------------------------------
        # The SR400 supports RS-232 and GPIB (IEEE-488) only (manual, "REMOTE PROGRAMMING").
        self.port_manager = True
        self.port_types = ["COM", "GPIB"]
        self.port_properties = {
            # A command is terminated by CR (or LF, or both). With RS-232 ECHO = OFF the SR400
            # answers with CR only; with GPIB the terminator is always CR LF.
            "EOL": "\r",
            "GPIB_EOLwrite": "\r",
            "GPIB_EOLread": "\n",
            # SR400 factory default COM settings, see manual "DEFAULT SETUP / POWER ON CLEAR"
            "baudrate": 9600,
            "bytesize": 8,
            "parity": "N",
            "stopbits": 1,
            # Long count periods are handled by polling the status byte, so a single
            # read never has to wait for the measurement to finish.
            "timeout": 5,
        }

        self.port_string: str = ""

        # --- GUI parameters (set in get_GUIparameter) -------------------------
        self.measurement_mode: str = self.MEASUREMENT_MODES[0]
        self.counting_mode: str = "A, B for T preset"
        self.counter_a_input: str = "INPUT 1"
        self.counter_b_input: str = "INPUT 1"
        self.counter_t_input: str = "10 MHz"
        self.count_time: float = 1.0
        self.preset_counts: float = 1e6
        self.periods: int = 1
        self.dwell_time: float = self.DEFAULT_DWELL_TIME
        self.trigger_slope: str = "Rise"
        self.trigger_level: float = 0.0
        self.discriminator_slopes: dict[str, str] = {"A": "Fall", "B": "Fall", "T": "Fall"}
        self.discriminator_levels: dict[str, float] = {"A": -0.010, "B": -0.010, "T": -0.010}
        self.gate_modes: dict[str, str] = {"A": "CW", "B": "CW"}
        self.gate_delays: dict[str, float] = {"A": 0.0, "B": 0.0}
        self.gate_widths: dict[str, float] = {"A": 1e-6, "B": 1e-6}
        self.set_ports: bool = False
        self.port_levels: dict[int, float] = {1: 0.0, 2: 0.0}
        self.extra_timeout: float = 20.0
        self.reset_at_start: bool = False
        self.lock_front_panel: bool = False
        self.print_phase: bool = False

        # --- internal state --------------------------------------------------
        self.is_rs232: bool = True
        self.uses_external_dwell: bool = False
        self.counter_b_is_readable: bool = True
        self.count_time_is_known: bool = True
        self.requested_count_time: float = 1.0
        self.requested_periods: int = 1
        self.requested_dwell_time: float = self.DEFAULT_DWELL_TIME
        self.actual_count_time: float = float("nan")
        self.actual_preset_counts: float = float("nan")
        self.actual_dwell_time: float = 0.0
        self.acquisition_timeout: float = 30.0
        self.poll_interval: float = 0.05
        self.front_panel_was_locked: bool = False

        self.measured_counts: dict[str, float] = {"A": float("nan"), "B": float("nan")}
        self.measured_count_time: float = float("nan")

    # ==================================================================
    #  GUI
    # ==================================================================

    def set_GUIparameter(self) -> dict:  # noqa: N802
        """Return the GUI elements shown in the SweepMe! module."""
        return {
            "Measurement mode": list(self.MEASUREMENT_MODES),
            " ": None,
            "Count mode": list(self.COUNTING_MODES.keys()),
            "Counter A input": list(self.ALLOWED_COUNTER_INPUTS["A"]),
            "Counter B input": list(self.ALLOWED_COUNTER_INPUTS["B"]),
            "Counter T input": list(self.ALLOWED_COUNTER_INPUTS["T"]),
            "Count time in s": 1.0,
            "Preset counts (T or B)": 1e6,
            "Periods per point": 1,
            "Dwell time in s": self.DEFAULT_DWELL_TIME,
            "  ": None,
            "Trigger slope": list(self.SLOPES.keys()),
            "Trigger level in V": 0.0,
            "Discriminator A slope": ["Fall", "Rise"],
            "Discriminator A level in V": -0.010,
            "Discriminator B slope": ["Fall", "Rise"],
            "Discriminator B level in V": -0.010,
            "Discriminator T slope": ["Fall", "Rise"],
            "Discriminator T level in V": -0.010,
            "   ": None,
            "Gate A mode": list(self.GATE_MODES.keys()),
            "Gate A delay in s": 0.0,
            "Gate A width in s": 1e-6,
            "Gate B mode": list(self.GATE_MODES.keys()),
            "Gate B delay in s": 0.0,
            "Gate B width in s": 1e-6,
            "    ": None,
            "Set PORT levels": False,
            "PORT1 level in V": 0.0,
            "PORT2 level in V": 0.0,
            "     ": None,
            "Baudrate": ["9600", "19200", "4800", "2400", "1200", "600", "300"],
            "Timeout in s": 20.0,
            "Reset instrument at start": False,
            "Lock front panel": False,
            "Print SweepMe! phase": False,
        }

    def get_GUIparameter(self, parameter: dict) -> None:  # noqa: N802
        """Take over the values the user has set in the SweepMe! GUI."""
        self.port_string = str(parameter.get("Port", ""))
        # RS-232 only commands (MI, SW, SE) must not be sent via GPIB, see manual command list.
        self.is_rs232 = self.port_string.upper().startswith(("COM", "ASRL"))

        self.measurement_mode = parameter.get("Measurement mode", self.MEASUREMENT_MODES[0])

        self.counting_mode = parameter.get("Count mode", "A, B for T preset")
        self.counter_a_input = parameter.get("Counter A input", "INPUT 1")
        self.counter_b_input = parameter.get("Counter B input", "INPUT 1")
        self.counter_t_input = parameter.get("Counter T input", "10 MHz")

        self.count_time = self._as_float(parameter, "Count time in s", 1.0)
        self.preset_counts = self._as_float(parameter, "Preset counts (T or B)", 1e6)
        self.periods = self._as_int(parameter, "Periods per point", 1)
        self.dwell_time = self._as_float(parameter, "Dwell time in s", self.DEFAULT_DWELL_TIME)

        self.trigger_slope = parameter.get("Trigger slope", "Rise")
        self.trigger_level = self._as_float(parameter, "Trigger level in V", 0.0)

        for discriminator in ("A", "B", "T"):
            self.discriminator_slopes[discriminator] = parameter.get(
                f"Discriminator {discriminator} slope",
                "Fall",
            )
            self.discriminator_levels[discriminator] = self._as_float(
                parameter,
                f"Discriminator {discriminator} level in V",
                -0.010,
            )

        for gate in ("A", "B"):
            self.gate_modes[gate] = parameter.get(f"Gate {gate} mode", "CW")
            self.gate_delays[gate] = self._as_float(parameter, f"Gate {gate} delay in s", 0.0)
            self.gate_widths[gate] = self._as_float(parameter, f"Gate {gate} width in s", 1e-6)

        self.set_ports = bool(parameter.get("Set PORT levels", False))
        self.port_levels[1] = self._as_float(parameter, "PORT1 level in V", 0.0)
        self.port_levels[2] = self._as_float(parameter, "PORT2 level in V", 0.0)

        self.extra_timeout = self._as_float(parameter, "Timeout in s", 20.0)
        self.reset_at_start = bool(parameter.get("Reset instrument at start", False))
        self.lock_front_panel = bool(parameter.get("Lock front panel", False))
        self.print_phase = bool(parameter.get("Print SweepMe! phase", False))

        # Ignored by the port manager for GPIB ports; only the COM branch reads it.
        self.port_properties["baudrate"] = self._as_int(parameter, "Baudrate", 9600)

        self._apply_measurement_mode()

        # Derived flags that only depend on GUI settings
        self.uses_external_dwell = self.dwell_time == 0.0
        self.counter_b_is_readable = self.counting_mode != "A for B preset"
        self.count_time_is_known = (
            self.counting_mode != "A for B preset" and self.counter_t_input == "10 MHz"
        )

    def _apply_measurement_mode(self) -> None:
        """Turn 'Measurement mode' into the NP and DT the rest of the driver works from.

        The two modes differ only in how one SweepMe! point maps onto SR400 count periods:

        - "Single count period" -- NP 1 with an EXTERNAL dwell. The driver starts exactly one
          count period per point and reads one buffer entry. The point sequence belongs to
          SweepMe!, not to the instrument, which makes the timing easy to reason about and the
          round trips per point minimal. This is the simple case and the default.
        - "Scan of N periods" -- NP = 'Periods per point' with the instrument's own internal
          dwell. The SR400 runs the whole scan itself and the driver sums the buffer entries.
          This is the mode that owns the instrument's scan machinery, so it is also where
          gate-delay scanning will land (README section 7.2).

        'Periods per point' and 'Dwell time in s' only govern the scan mode. Rather than let
        them look live in the single-period mode, they are overridden here and the override is
        reported by _check_configuration() when the user had actually changed them.
        """
        if self.measurement_mode not in self.MEASUREMENT_MODES:
            allowed = ", ".join(f"'{mode}'" for mode in self.MEASUREMENT_MODES)
            msg = f"Unknown measurement mode '{self.measurement_mode}'. Allowed: {allowed}."
            raise Exception(msg)

        # Kept for _check_configuration(), which needs to know what was asked for.
        self.requested_periods = self.periods
        self.requested_dwell_time = self.dwell_time

        if self.measurement_mode == "Single count period":
            self.periods = 1
            self.dwell_time = 0.0

    # ==================================================================
    #  SweepMe! semantic functions
    # ==================================================================

    def _phase(self, name: str) -> None:
        """Announce the SweepMe! phase now running, if 'Print SweepMe! phase' is enabled.

        Every semantic function opens with a call to this, so the guard lives here once
        instead of wrapping each call site in an 'if'. Output goes to the SweepMe! debug
        console, which is where a driver's print() lands.
        """
        if self.print_phase:
            print(f"SR400 [{self.port_string or 'no port'}]: {name}")

    def connect(self) -> None:
        """Check that the SR400 really answers on the selected port.

        The SR400 has no identification command, so the counting mode (CM) is read instead.
        """
        self._phase("connect")

        try:
            response = self._query("CM")
        except Exception as exc:
            msg = (
                "No answer from the SR400. Please check the port settings and the SR400 COM menu "
                "(RS-232: BAUD, BITS, PARITY must match the port, ECHO must be OFF; "
                "GPIB: address 1-30)."
            )
            raise Exception(msg) from exc

        if response.upper().startswith("CM") or "OK>" in response or "??>" in response:
            msg = (
                f"The SR400 echoes commands back (answer to 'CM' was {response!r}). "
                "Please set RS-232 ECHO = OFF in the COM menu of the SR400."
            )
            raise Exception(msg)

        try:
            counting_mode = int(float(response))
        except ValueError as exc:
            msg = f"Unexpected answer {response!r} of the SR400 to the command 'CM'."
            raise Exception(msg) from exc

        if counting_mode not in self.COUNTING_MODES.values():
            msg = f"The SR400 returned the invalid counting mode {counting_mode} for command 'CM'."
            raise Exception(msg)

    def initialize(self) -> None:
        """Bring the communication into a defined state."""
        self._phase("initialize")
        if self.reset_at_start:
            # CL restores the default settings, clears the buffers, the SRQ mask and the
            # RS-232 terminator sequence. It must be the only command on its line.
            self.clear_instrument()
            time.sleep(0.5)

        if self.is_rs232:
            # The manual recommends SW 0 at the beginning of a program to speed up the
            # transmission (default wait interval is 6 x 3.3 ms per character).
            self.set_rs232_wait(0)

        # Read the status byte once to clear all conditions that occurred before the run.
        self.get_status_byte()

    def configure(self) -> None:
        """Apply all one-time settings taken from the GUI."""
        self._phase("configure")
        self._check_configuration()

        self.requested_count_time = self.count_time

        # Counting mode first: setting it also resets the counters (manual, CM).
        self.set_counting_mode(self.counting_mode)

        self.set_counter_input("A", self.counter_a_input)
        self.set_counter_input("B", self.counter_b_input)
        self.set_counter_input("T", self.counter_t_input)

        # Only the counter that is actually preset in the selected mode is programmed.
        if self.counting_mode == "A for B preset":
            self.set_counter_preset("B", self.preset_counts)
        elif self.counter_t_input == "10 MHz":
            self.set_count_time(self.count_time)
        else:
            self.set_counter_preset("T", self.preset_counts)

        self.set_number_of_periods(self.periods)
        # "Whenever scan data is to be read, the scan end mode should be STOP" (manual, QA/QB).
        self.set_scan_end_mode("Stop")
        self.set_dwell_time(self.dwell_time)

        self.set_trigger_slope(self.trigger_slope)
        self.set_trigger_level(self.trigger_level)

        for discriminator in ("A", "B", "T"):
            self.set_discriminator_slope(discriminator, self.discriminator_slopes[discriminator])
            self.set_discriminator_mode(discriminator, "Fixed")
            self.set_discriminator_level(discriminator, self.discriminator_levels[discriminator])

        for gate in ("A", "B"):
            self.set_gate_mode(gate, self.gate_modes[gate])
            # Delay and width may be set independently of the gate mode (manual, GD/GW).
            self.set_gate_delay(gate, self.gate_delays[gate])
            self.set_gate_width(gate, self.gate_widths[gate])

        if self.set_ports:
            for port_number in (1, 2):
                self.set_port_mode(port_number, "Fixed")
                self.set_port_level(port_number, self.port_levels[port_number])

        if self.lock_front_panel and self.is_rs232:
            self.set_front_panel_mode("Remote")
            self.front_panel_was_locked = True

        self.reset_counters()

        # Read back what the instrument really applied. Presets and the dwell time keep only
        # one significant digit, so the requested and the applied values can differ.
        self._read_back_timing()

        # A single status byte read reports every problem caused by the commands above.
        self._check_status(self.get_status_byte(), context="configuration")

    def unconfigure(self) -> None:
        """Leave the instrument in a safe, idle state."""
        self._phase("unconfigure")
        self.reset_counters()

        if self.front_panel_was_locked and self.is_rs232:
            self.set_front_panel_mode("Local")
            self.front_panel_was_locked = False

    def measure(self) -> None:
        """Run one scan of 'Periods per point' count periods and read the counts."""
        self._phase("measure")
        self.reset_counters()

        # "the status byte should be cleared before starting a scan and then polled to
        # determine when the scan is finished" (manual, QA/QB section). Reading it also
        # reports any problem left over from the configuration commands.
        self._check_status(self.get_status_byte(), context="measurement start")

        status = 0
        if self.uses_external_dwell:
            # With EXTERNAL dwell every count period has to be started separately
            # (manual, DWELL menu: "the next COUNT PERIOD begins with another START").
            for _ in range(self.periods):
                self.start_counting()
                status |= self._wait_for_status(
                    self.STATUS_DATA_READY | self.STATUS_SCAN_FINISHED,
                    self.acquisition_timeout,
                )
        else:
            self.start_counting()
            wait_mask = self.STATUS_SCAN_FINISHED
            if self.periods == 1:
                # For a single period, data ready and scan finished occur together; accepting
                # both makes the driver independent of the polling order.
                wait_mask |= self.STATUS_DATA_READY
            status |= self._wait_for_status(wait_mask, self.acquisition_timeout)

        self._check_status(status, context="measurement")

        counts_a = 0
        counts_b = 0
        for point in range(1, self.periods + 1):
            counts_a += self.get_scan_point("A", point)
            if self.counter_b_is_readable:
                counts_b += self.get_scan_point("B", point)

        self.measured_counts["A"] = float(counts_a)
        self.measured_counts["B"] = float(counts_b) if self.counter_b_is_readable else float("nan")
        self.measured_count_time = (
            self.actual_count_time * self.periods if self.count_time_is_known else float("nan")
        )

    def call(self) -> list[float]:
        """Hand the measured values over to SweepMe!, in the order of 'self.variables'."""
        self._phase("call")
        count_time = self.measured_count_time
        if count_time > 0.0:
            rate_a = self.measured_counts["A"] / count_time
            rate_b = self.measured_counts["B"] / count_time
        else:
            rate_a = float("nan")
            rate_b = float("nan")

        return [
            self.measured_counts["A"],
            self.measured_counts["B"],
            rate_a,
            rate_b,
            count_time,
        ]

    # ==================================================================
    #  internal helpers
    # ==================================================================

    def _query(self, command: str) -> str:
        """Send a query command and return the stripped answer."""
        self.port.write(command)
        response = self.port.read()

        if response == "":
            msg = (
                f"The SR400 did not answer the query {command!r}. Check timeout, terminator "
                "and the COM menu settings of the instrument."
            )
            raise Exception(msg)

        return response.strip()

    def _query_float(self, command: str) -> float:
        """Send a query command and convert the answer to float."""
        response = self._query(command)
        try:
            return float(response)
        except ValueError as exc:
            msg = f"Cannot interpret the SR400 answer {response!r} to the query {command!r} as a number."
            raise Exception(msg) from exc

    def _query_int(self, command: str) -> int:
        """Send a query command and convert the answer to int.

        Values such as counts are returned as plain integers, presets as e.g. '1E1', therefore
        the conversion goes through float.
        """
        return int(self._query_float(command))

    @staticmethod
    def _as_float(parameter: dict, key: str, default: float) -> float:
        """Read a numeric GUI field. GUI fields arrive as strings."""
        value = parameter.get(key, default)
        try:
            return float(value)
        except (TypeError, ValueError) as exc:
            msg = f"The value {value!r} of the field '{key}' is not a number."
            raise Exception(msg) from exc

    @staticmethod
    def _as_int(parameter: dict, key: str, default: int) -> int:
        """Read an integer GUI field."""
        value = parameter.get(key, default)
        try:
            return int(float(value))
        except (TypeError, ValueError) as exc:
            msg = f"The value {value!r} of the field '{key}' is not an integer."
            raise Exception(msg) from exc

    @staticmethod
    def _one_significant_digit(value: float) -> tuple[int, int]:
        """Round a positive value to one significant digit.

        Returns the mantissa (1...9) and the decimal exponent. Counter presets (CP) and the
        dwell time (DT) of the SR400 keep only the most significant digit, so the driver
        rounds itself and sends an unambiguous 'mEk' string.
        """
        if value <= 0.0 or not math.isfinite(value):
            msg = f"Cannot round the non-positive or non-finite value {value} to one significant digit."
            raise ValueError(msg)

        exponent = math.floor(math.log10(value))
        mantissa = int(round(value / 10.0**exponent))
        if mantissa >= 10:  # e.g. 9.7E6 -> 1E7
            mantissa = 1
            exponent += 1

        return mantissa, exponent

    def _check_configuration(self) -> None:
        """Warn about GUI settings the instrument will silently ignore.

        None of these is an error -- the SR400 accepts every one of them -- but each is a
        setting the user plausibly expected to matter and which does not, given the rest of
        the configuration. Saying so once at configure() time is cheaper than a puzzling
        data set.
        """
        if self.measurement_mode == "Single count period":
            ignored = []
            if self.requested_periods != 1:
                ignored.append(f"'Periods per point' ({self.requested_periods})")
            if self.requested_dwell_time != self.DEFAULT_DWELL_TIME:
                ignored.append(f"'Dwell time in s' ({self.requested_dwell_time:.4g})")
            if ignored:
                # Listed at the end so the sentence reads the same for one field or two.
                self.message_info(
                    f"SR400: the 'Single count period' mode forces NP 1 and an EXTERNAL dwell, "
                    f"because it starts every count period itself. Ignored here, and only used "
                    f"by 'Scan of N periods': {', '.join(ignored)}.",
                )

        for gate in ("A", "B"):
            # In CW mode the gate is held permanently open, so GD and GW never take effect
            # (manual, GATE menu). A nonzero delay is the case where the user clearly meant
            # to gate something.
            if self.gate_modes[gate] == "CW" and self.gate_delays[gate] != 0.0:
                self.message_info(
                    f"SR400: 'Gate {gate} delay in s' is ignored while gate {gate} is in CW "
                    f"mode, because a CW gate is always open. Set 'Gate {gate} mode' to "
                    f"'Fixed' or 'Scan' to use the delay and width.",
                )

        # Counter T on the 10 MHz timebase is the default and the recommended setup, so only
        # say something when the user has actually moved the T discriminator off its default
        # and would otherwise wait for an effect that cannot come.
        if self.counter_t_input == "10 MHz" and self.discriminator_levels["T"] != -0.010:
            self.message_info(
                "SR400: the T discriminator level is not used while counter T counts the "
                "internal 10 MHz timebase.",
            )

        if self.counting_mode == "A for B preset" and self.counter_t_input != "10 MHz":
            self.message_info(
                "SR400: counter T is neither preset nor the timebase in the counting mode "
                "'A for B preset', so 'Counter T input' has no effect on the result.",
            )

    def _read_back_timing(self) -> None:
        """Read the applied preset and dwell time and derive the acquisition timeout."""
        self.actual_dwell_time = self.get_dwell_time()

        if self.count_time_is_known:
            self.actual_count_time = self.get_counter_preset("T") / self.CLOCK_FREQUENCY
            if not math.isclose(self.actual_count_time, self.requested_count_time, rel_tol=0.01):
                self.message_info(
                    f"SR400: the requested count time of {self.requested_count_time:.4g} s was rounded to "
                    f"{self.actual_count_time:.4g} s, because the T preset keeps only one "
                    f"significant digit.",
                )
            period_duration = self.actual_count_time + self.actual_dwell_time
        else:
            self.actual_count_time = float("nan")

            # 'Preset counts (T or B)' is rounded to one significant digit exactly like the
            # count time, but this branch has no Count time column to report it through, so
            # the rounding used to be invisible. Read back what actually stuck.
            preset_counter = "B" if self.counting_mode == "A for B preset" else "T"
            self.actual_preset_counts = self.get_counter_preset(preset_counter)
            if not math.isclose(self.actual_preset_counts, self.preset_counts, rel_tol=0.01):
                self.message_info(
                    f"SR400: the requested preset of {self.preset_counts:.4g} counts was "
                    f"rounded to {self.actual_preset_counts:.4g} on counter {preset_counter}, "
                    f"because CP keeps only one significant digit.",
                )

            # The count period ends when the preset counter reaches its preset value, so its
            # duration depends on the signal and cannot be predicted.
            period_duration = 0.0

        expected_duration = self.periods * period_duration
        self.acquisition_timeout = expected_duration + max(self.extra_timeout, 1.0)
        self.poll_interval = min(0.2, max(0.01, expected_duration / 50.0))

    def _wait_for_status(self, mask: int, timeout: float) -> int:
        """Poll the status byte until one of the bits in 'mask' is set.

        Reading the status byte clears it, so all bytes read during the wait are combined and
        returned. This way error bits are not lost while waiting.
        """
        accumulated = 0
        deadline = time.time() + timeout

        while True:
            accumulated |= self.get_status_byte()

            if accumulated & mask:
                return accumulated

            if self.is_run_stopped():
                self.pause_counting()
                msg = "The measurement was stopped while waiting for the SR400 count data."
                raise Exception(msg)

            if time.time() > deadline:
                # Leave the instrument idle rather than counting into a scan nobody reads.
                self.pause_counting()
                self._check_status(accumulated, context="measurement")
                msg = (
                    f"The SR400 did not finish the count periods within {timeout:.4g} s "
                    f"(status byte {accumulated}). Check the trigger and the preset counter, or "
                    f"increase 'Timeout in s'."
                )
                raise Exception(msg)

            time.sleep(self.poll_interval)

    def _check_status(self, status: int, context: str) -> None:
        """Raise or report the problems reported by the status byte."""
        if status & self.STATUS_COMMAND_ERROR:
            msg = (
                f"The SR400 reported a command error during the {context} (illegal command or "
                f"parameter out of range). The COM menu line 'DATA' of the instrument shows the "
                f"last received characters."
            )
            raise Exception(msg)

        if status & self.STATUS_RECALL_ERROR:
            msg = f"The SR400 reported a recall error during the {context}; the setup was not changed."
            raise Exception(msg)

        if status & self.STATUS_COUNTER_OVERRUN:
            msg = (
                f"A counter of the SR400 overran during the {context} (1E9-1 counts reached), so "
                f"the counts are invalid. Reduce the count time or the count rate."
            )
            raise Exception(msg)

        if status & self.STATUS_RATE_ERROR:
            self.message_info(
                "SR400: rate error, at least one gate was missed. The gate delay or width may "
                "exceed the trigger period minus 1 us.",
            )

        # Bit 0 means someone turned a knob on the front panel. Not fatal, and not something
        # the driver can undo, but the instrument is no longer necessarily in the state
        # configure() left it in -- which is worth knowing before trusting the numbers.
        if status & self.STATUS_PARAMETER_CHANGED:
            self.message_info(
                f"SR400: a parameter was changed from the front panel during the {context}, so "
                f"the instrument may no longer match the configuration. Consider 'Lock front "
                f"panel'.",
            )

    # ==================================================================
    #  wrapped instrument commands -- MODE
    # ==================================================================

    def set_counting_mode(self, mode: str) -> None:
        """Set the counting mode (CM). Also performs a counter reset."""
        self.port.write(f"CM {self._lookup(self.COUNTING_MODES, mode, 'counting mode')}")

    def get_counting_mode(self) -> str:
        """Return the counting mode (CM)."""
        return self._reverse_lookup(self.COUNTING_MODES, self._query_int("CM"))

    def set_counter_input(self, counter: str, source: str) -> None:
        """Set the input of counter 'A', 'B' or 'T' (CI)."""
        counter = self._check_counter(counter)
        if source not in self.ALLOWED_COUNTER_INPUTS[counter]:
            msg = (
                f"'{source}' is not an allowed input for counter {counter}. Allowed: "
                f"{', '.join(self.ALLOWED_COUNTER_INPUTS[counter])}."
            )
            raise ValueError(msg)

        self.port.write(f"CI {self.COUNTER_INDICES[counter]},{self.COUNTER_INPUTS[source]}")

    def get_counter_input(self, counter: str) -> str:
        """Return the input of counter 'A', 'B' or 'T' (CI)."""
        counter = self._check_counter(counter)
        index = self._query_int(f"CI {self.COUNTER_INDICES[counter]}")
        return self._reverse_lookup(self.COUNTER_INPUTS, index)

    def set_counter_preset(self, counter: str, preset: float) -> None:
        """Set the preset of counter 'B' or 'T' in counts (CP).

        The SR400 keeps only the most significant digit, so the value is rounded here and sent
        as an unambiguous 'mEk' string.
        """
        counter = self._check_counter(counter)
        if counter == "A":
            msg = "Counter A cannot be preset; only counter B (CP 1) and counter T (CP 2) can."
            raise ValueError(msg)

        if not self.PRESET_MIN <= preset <= self.PRESET_MAX:
            msg = f"The counter preset {preset} is outside the allowed range 1 ... 9E11 counts."
            raise ValueError(msg)

        mantissa, exponent = self._one_significant_digit(preset)
        self.port.write(f"CP {self.COUNTER_INDICES[counter]},{mantissa}E{exponent}")

    def get_counter_preset(self, counter: str) -> float:
        """Return the preset of counter 'B' or 'T' in counts (CP)."""
        counter = self._check_counter(counter)
        return self._query_float(f"CP {self.COUNTER_INDICES[counter]}")

    def set_count_time(self, count_time: float) -> None:
        """Set the length of one count period in seconds.

        Only possible with counter T preset and its input set to the internal 10 MHz timebase:
        the T preset is the number of clock cycles, so count_time = preset / 10 MHz.
        """
        if count_time <= 0.0:
            msg = f"The count time {count_time} s must be positive."
            raise ValueError(msg)

        self.set_counter_preset("T", count_time * self.CLOCK_FREQUENCY)

    def get_count_time(self) -> float:
        """Return the length of one count period in seconds, derived from the T preset."""
        return self.get_counter_preset("T") / self.CLOCK_FREQUENCY

    def set_number_of_periods(self, periods: int) -> None:
        """Set the number of count periods of a scan (NP)."""
        periods = int(periods)
        if not 1 <= periods <= self.PERIODS_MAX:
            msg = f"The number of periods {periods} is outside the allowed range 1 ... {self.PERIODS_MAX}."
            raise ValueError(msg)

        self.port.write(f"NP {periods}")

    def get_number_of_periods(self) -> int:
        """Return the number of count periods of a scan (NP)."""
        return self._query_int("NP")

    def get_scan_position(self) -> int:
        """Return the number of count periods completed in the current scan (NN, read only)."""
        return self._query_int("NN")

    def set_scan_end_mode(self, mode: str) -> None:
        """Set the behaviour at the end of a scan to 'Stop' or 'Start' (NE)."""
        self.port.write(f"NE {self._lookup(self.SCAN_END_MODES, mode, 'scan end mode')}")

    def get_scan_end_mode(self) -> str:
        """Return the behaviour at the end of a scan (NE)."""
        return self._reverse_lookup(self.SCAN_END_MODES, self._query_int("NE"))

    def set_dwell_time(self, dwell_time: float) -> None:
        """Set the dwell time between count periods in seconds (DT).

        A dwell time of exactly 0 selects the EXTERNAL dwell, where every count period has to
        be started separately. Only the most significant digit is kept by the instrument.
        """
        if dwell_time == 0.0:
            self.port.write("DT 0")
            return

        if not self.DWELL_MIN <= dwell_time <= self.DWELL_MAX:
            msg = (
                f"The dwell time {dwell_time} s is outside the allowed range "
                f"{self.DWELL_MIN} ... {self.DWELL_MAX} s. Use exactly 0 for an EXTERNAL dwell."
            )
            raise ValueError(msg)

        mantissa, exponent = self._one_significant_digit(dwell_time)
        self.port.write(f"DT {mantissa}E{exponent}")

    def get_dwell_time(self) -> float:
        """Return the dwell time in seconds (DT). 0 means EXTERNAL dwell."""
        return self._query_float("DT")

    def set_dac_source(self, source: str) -> None:
        """Set the source of the front panel D/A output (AS).

        Only allowed in the counting mode 'A, B for T preset'; in all other modes the output
        follows the count display.
        """
        self.port.write(f"AS {self._lookup(self.DAC_SOURCES, source, 'D/A source')}")

    def get_dac_source(self) -> str:
        """Return the source of the front panel D/A output (AS)."""
        return self._reverse_lookup(self.DAC_SOURCES, self._query_int("AS"))

    def set_dac_range(self, dac_range: int) -> None:
        """Set the front panel D/A output scale (AM): 0 = log 1 V/decade, 1...7 = linear."""
        dac_range = int(dac_range)
        if not 0 <= dac_range <= 7:
            msg = f"The D/A range {dac_range} is outside the allowed range 0 ... 7."
            raise ValueError(msg)

        self.port.write(f"AM {dac_range}")

    def get_dac_range(self) -> int:
        """Return the front panel D/A output scale (AM)."""
        return self._query_int("AM")

    def set_display_mode(self, mode: str) -> None:
        """Set the count display update mode to 'Continuous' or 'Hold' (SD)."""
        self.port.write(f"SD {self._lookup(self.DISPLAY_MODES, mode, 'display mode')}")

    def get_display_mode(self) -> str:
        """Return the count display update mode (SD)."""
        return self._reverse_lookup(self.DISPLAY_MODES, self._query_int("SD"))

    # ==================================================================
    #  wrapped instrument commands -- LEVELS
    # ==================================================================

    def set_trigger_slope(self, slope: str) -> None:
        """Set the gate trigger slope to 'Rise' or 'Fall' (TS)."""
        self.port.write(f"TS {self._lookup(self.SLOPES, slope, 'trigger slope')}")

    def get_trigger_slope(self) -> str:
        """Return the gate trigger slope (TS)."""
        return self._reverse_lookup(self.SLOPES, self._query_int("TS"))

    def set_trigger_level(self, level: float) -> None:
        """Set the gate trigger level in volts (TL). Range +-2.000 V, resolution 1 mV."""
        self._check_limit(level, self.TRIGGER_LEVEL_LIMIT, "trigger level", "V")
        self.port.write(f"TL {level:.3f}")

    def get_trigger_level(self) -> float:
        """Return the gate trigger level in volts (TL)."""
        return self._query_float("TL")

    def set_discriminator_slope(self, discriminator: str, slope: str) -> None:
        """Set the slope of discriminator 'A', 'B' or 'T' to 'Rise' or 'Fall' (DS)."""
        index = self.COUNTER_INDICES[self._check_counter(discriminator)]
        self.port.write(f"DS {index},{self._lookup(self.SLOPES, slope, 'discriminator slope')}")

    def get_discriminator_slope(self, discriminator: str) -> str:
        """Return the slope of discriminator 'A', 'B' or 'T' (DS)."""
        index = self.COUNTER_INDICES[self._check_counter(discriminator)]
        return self._reverse_lookup(self.SLOPES, self._query_int(f"DS {index}"))

    def set_discriminator_mode(self, discriminator: str, mode: str) -> None:
        """Set discriminator 'A', 'B' or 'T' to 'Fixed' or 'Scan' (DM)."""
        index = self.COUNTER_INDICES[self._check_counter(discriminator)]
        mode_value = self._lookup(self.DISCRIMINATOR_MODES, mode, "discriminator mode")
        self.port.write(f"DM {index},{mode_value}")

    def get_discriminator_mode(self, discriminator: str) -> str:
        """Return the mode of discriminator 'A', 'B' or 'T' (DM)."""
        index = self.COUNTER_INDICES[self._check_counter(discriminator)]
        return self._reverse_lookup(self.DISCRIMINATOR_MODES, self._query_int(f"DM {index}"))

    def set_discriminator_level(self, discriminator: str, level: float) -> None:
        """Set the level of discriminator 'A', 'B' or 'T' in volts (DL).

        Range +-0.3000 V, resolution 0.2 mV. In the SCAN mode this is the start level.
        """
        index = self.COUNTER_INDICES[self._check_counter(discriminator)]
        self._check_limit(level, self.DISCRIMINATOR_LEVEL_LIMIT, "discriminator level", "V")
        self.port.write(f"DL {index},{level:.4f}")

    def get_discriminator_level(self, discriminator: str) -> float:
        """Return the level of discriminator 'A', 'B' or 'T' in volts (DL)."""
        index = self.COUNTER_INDICES[self._check_counter(discriminator)]
        return self._query_float(f"DL {index}")

    def set_discriminator_scan_step(self, discriminator: str, step: float) -> None:
        """Set the scan step of discriminator 'A', 'B' or 'T' in volts (DY). Range +-0.0200 V."""
        index = self.COUNTER_INDICES[self._check_counter(discriminator)]
        self._check_limit(step, self.DISCRIMINATOR_STEP_LIMIT, "discriminator scan step", "V")
        self.port.write(f"DY {index},{step:.4f}")

    def get_discriminator_scan_step(self, discriminator: str) -> float:
        """Return the scan step of discriminator 'A', 'B' or 'T' in volts (DY)."""
        index = self.COUNTER_INDICES[self._check_counter(discriminator)]
        return self._query_float(f"DY {index}")

    def get_discriminator_scan_level(self, discriminator: str) -> float:
        """Return the current level of discriminator 'A', 'B' or 'T' during a scan (DZ, read only)."""
        index = self.COUNTER_INDICES[self._check_counter(discriminator)]
        return self._query_float(f"DZ {index}")

    def set_port_mode(self, port_number: int, mode: str) -> None:
        """Set the rear panel PORT1 or PORT2 D/A output to 'Fixed' or 'Scan' (PM)."""
        port_number = self._check_port_number(port_number)
        self.port.write(f"PM {port_number},{self._lookup(self.PORT_MODES, mode, 'PORT mode')}")

    def get_port_mode(self, port_number: int) -> str:
        """Return the mode of the rear panel PORT1 or PORT2 D/A output (PM)."""
        port_number = self._check_port_number(port_number)
        return self._reverse_lookup(self.PORT_MODES, self._query_int(f"PM {port_number}"))

    def set_port_level(self, port_number: int, level: float) -> None:
        """Set the PORT1 or PORT2 output level in volts (PL). Range +-10.000 V, resolution 5 mV."""
        port_number = self._check_port_number(port_number)
        self._check_limit(level, self.PORT_LEVEL_LIMIT, f"PORT{port_number} level", "V")
        self.port.write(f"PL {port_number},{level:.3f}")

    def get_port_level(self, port_number: int) -> float:
        """Return the PORT1 or PORT2 output level in volts (PL).

        During a scan this returns the start value, not the current level; use
        get_port_scan_level() for the current level.
        """
        port_number = self._check_port_number(port_number)
        return self._query_float(f"PL {port_number}")

    def set_port_scan_step(self, port_number: int, step: float) -> None:
        """Set the PORT1 or PORT2 scan step in volts (PY). Range +-0.500 V."""
        port_number = self._check_port_number(port_number)
        self._check_limit(step, self.PORT_STEP_LIMIT, f"PORT{port_number} scan step", "V")
        self.port.write(f"PY {port_number},{step:.3f}")

    def get_port_scan_step(self, port_number: int) -> float:
        """Return the PORT1 or PORT2 scan step in volts (PY)."""
        port_number = self._check_port_number(port_number)
        return self._query_float(f"PY {port_number}")

    def get_port_scan_level(self, port_number: int) -> float:
        """Return the current PORT1 or PORT2 level during a scan (PZ, read only)."""
        port_number = self._check_port_number(port_number)
        return self._query_float(f"PZ {port_number}")

    # ==================================================================
    #  wrapped instrument commands -- GATES
    # ==================================================================

    def set_gate_mode(self, gate: str, mode: str) -> None:
        """Set gate 'A' or 'B' to 'CW', 'Fixed' or 'Scan' (GM)."""
        index = self._check_gate(gate)
        self.port.write(f"GM {index},{self._lookup(self.GATE_MODES, mode, 'gate mode')}")

    def get_gate_mode(self, gate: str) -> str:
        """Return the mode of gate 'A' or 'B' (GM)."""
        index = self._check_gate(gate)
        return self._reverse_lookup(self.GATE_MODES, self._query_int(f"GM {index}"))

    def set_gate_delay(self, gate: str, delay: float) -> None:
        """Set the delay of gate 'A' or 'B' in seconds (GD).

        Range 0 ... 999.2E-3 s. The resolution is 1 ns below 1 us and 1 part in 1000 above;
        the SR400 rounds to the nearest allowed value itself.
        """
        index = self._check_gate(gate)
        if not 0.0 <= delay <= self.GATE_DELAY_MAX:
            msg = f"The gate delay {delay} s is outside the allowed range 0 ... {self.GATE_DELAY_MAX} s."
            raise ValueError(msg)

        self.port.write(f"GD {index},{delay:.6E}")

    def get_gate_delay(self, gate: str) -> float:
        """Return the delay of gate 'A' or 'B' in seconds (GD).

        During a scan this returns the start delay; use get_gate_scan_delay() for the current one.
        """
        index = self._check_gate(gate)
        return self._query_float(f"GD {index}")

    def set_gate_width(self, gate: str, width: float) -> None:
        """Set the width of gate 'A' or 'B' in seconds (GW). Range 0.005E-6 ... 999.2E-3 s."""
        index = self._check_gate(gate)
        if not self.GATE_WIDTH_MIN <= width <= self.GATE_WIDTH_MAX:
            msg = (
                f"The gate width {width} s is outside the allowed range "
                f"{self.GATE_WIDTH_MIN} ... {self.GATE_WIDTH_MAX} s."
            )
            raise ValueError(msg)

        self.port.write(f"GW {index},{width:.6E}")

    def get_gate_width(self, gate: str) -> float:
        """Return the width of gate 'A' or 'B' in seconds (GW)."""
        index = self._check_gate(gate)
        return self._query_float(f"GW {index}")

    def set_gate_delay_scan_step(self, gate: str, step: float) -> None:
        """Set the gate delay scan step of gate 'A' or 'B' in seconds (GY). Range 0 ... 99.92E-3 s."""
        index = self._check_gate(gate)
        if not 0.0 <= step <= self.GATE_STEP_MAX:
            msg = f"The gate scan step {step} s is outside the allowed range 0 ... {self.GATE_STEP_MAX} s."
            raise ValueError(msg)

        self.port.write(f"GY {index},{step:.6E}")

    def get_gate_delay_scan_step(self, gate: str) -> float:
        """Return the gate delay scan step of gate 'A' or 'B' in seconds (GY)."""
        index = self._check_gate(gate)
        return self._query_float(f"GY {index}")

    def get_gate_scan_delay(self, gate: str) -> float:
        """Return the current gate delay position of gate 'A' or 'B' during a scan (GZ, read only)."""
        index = self._check_gate(gate)
        return self._query_float(f"GZ {index}")

    # ==================================================================
    #  wrapped instrument commands -- FRONT PANEL
    # ==================================================================

    def start_counting(self) -> None:
        """Start or resume counting (CS, same as the START key)."""
        self.port.write("CS")

    def pause_counting(self) -> None:
        """Pause counting, or reset if already paused (CH, same as the STOP key)."""
        self.port.write("CH")

    def reset_counters(self) -> None:
        """Reset the counters and the scan (CR, same as pressing STOP twice).

        Scanned parameters return to their start values and buffered scan data is lost.
        """
        self.port.write("CR")

    def press_key(self, key: int) -> None:
        """Simulate a front panel key press 0 ... 13 (CK)."""
        key = int(key)
        if not 0 <= key <= 13:
            msg = f"The key number {key} is outside the allowed range 0 ... 13."
            raise ValueError(msg)

        self.port.write(f"CK {key}")

    def turn_knob_right(self) -> None:
        """Rotate the front panel knob one step clockwise/up (RR)."""
        self.port.write("RR")

    def turn_knob_left(self) -> None:
        """Rotate the front panel knob one step counter-clockwise/down (RL)."""
        self.port.write("RL")

    def get_cursor_position(self) -> int:
        """Return the cursor position: 0 = left, 1 = right, 2 = inactive (SC, read only)."""
        return self._query_int("SC")

    def set_front_panel_mode(self, mode: str) -> None:
        """Set the front panel to 'Local', 'Remote' or 'Locked out' (MI).

        RS-232 only; via GPIB the front panel state is controlled with REN, LLO and GTL.
        """
        self._require_rs232("MI")
        self.port.write(f"MI {self._lookup(self.FRONT_PANEL_MODES, mode, 'front panel mode')}")

    def set_display_message(self, message: str) -> None:
        """Write up to 24 characters on the menu line of the LCD (MS).

        Spaces are transmitted as underscores, as required by the instrument.
        """
        text = message.strip().replace(" ", "_")
        if len(text) > 24:
            msg = f"The display message {message!r} is longer than the 24 characters of the LCD menu line."
            raise ValueError(msg)

        self.port.write(f"MS {text}" if text else "MS")

    def clear_display_message(self) -> None:
        """Return the LCD menu line to its normal display (MS without argument)."""
        self.port.write("MS")

    def set_menu_display(self, menu: int, line: int) -> None:
        """Show line 'line' of menu 'menu' on the LCD (MD)."""
        self.port.write(f"MD {int(menu)},{int(line)}")

    def get_menu_number(self) -> int:
        """Return the number of the displayed menu (MM, read only)."""
        return self._query_int("MM")

    def get_menu_line(self) -> int:
        """Return the number of the displayed menu line (ML, read only)."""
        return self._query_int("ML")

    # ==================================================================
    #  wrapped instrument commands -- STORE / RECALL
    # ==================================================================

    def store_settings(self, location: int) -> None:
        """Store the instrument settings to location 1 ... 9 (ST). SETUP and COM menus excluded."""
        location = int(location)
        if not 1 <= location <= 9:
            msg = f"The storage location {location} is outside the allowed range 1 ... 9."
            raise ValueError(msg)

        self.port.write(f"ST {location}")

    def recall_settings(self, location: int) -> None:
        """Recall the instrument settings from location 1 ... 9, or the defaults with 0 (RC).

        Also resets the counters. SETUP and COM menus are not altered.
        """
        location = int(location)
        if not 0 <= location <= 9:
            msg = f"The storage location {location} is outside the allowed range 0 ... 9."
            raise ValueError(msg)

        self.port.write(f"RC {location}")

    # ==================================================================
    #  wrapped instrument commands -- INTERFACE / STATUS
    # ==================================================================

    def clear_instrument(self) -> None:
        """Reset the instrument to its default state (CL).

        Clears the communication buffers, the SRQ mask and the RS-232 terminator sequence.
        SETUP and COM menu parameters are not changed. Must be the only command on its line.
        """
        self.port.write("CL")

    def get_status_byte(self) -> int:
        """Return the status byte 0 ... 255 (SS). Reading clears all status bits."""
        status = self._query_int("SS")
        if not 0 <= status <= 255:
            msg = f"The SR400 returned the invalid status byte {status}."
            raise Exception(msg)

        return status

    def get_status_bit(self, bit: int) -> int:
        """Return one bit 0 ... 7 of the status byte (SS j). Reading clears that bit."""
        bit = int(bit)
        if not 0 <= bit <= 7:
            msg = f"The status bit {bit} is outside the allowed range 0 ... 7."
            raise ValueError(msg)

        return self._query_int(f"SS {bit}")

    def get_secondary_status_byte(self) -> int:
        """Return the secondary status byte 0 ... 7 (SI). Reading clears the bits."""
        return self._query_int("SI")

    def get_secondary_status_bit(self, bit: int) -> int:
        """Return one bit 0 ... 2 of the secondary status byte (SI j)."""
        bit = int(bit)
        if not 0 <= bit <= 2:
            msg = f"The secondary status bit {bit} is outside the allowed range 0 ... 2."
            raise ValueError(msg)

        return self._query_int(f"SI {bit}")

    def is_counting(self) -> bool:
        """Return True while a count period is in progress (SI bit 2, samples the counter state)."""
        return bool(self.get_secondary_status_bit(2))

    def set_srq_mask(self, mask: int) -> None:
        """Set the GPIB SRQ mask 0 ... 255 (SV). GPIB only."""
        if self.is_rs232:
            msg = "The command 'SV' (SRQ mask) may only be sent via the GPIB interface."
            raise Exception(msg)

        mask = int(mask)
        if not 0 <= mask <= 255:
            msg = f"The SRQ mask {mask} is outside the allowed range 0 ... 255."
            raise ValueError(msg)

        self.port.write(f"SV {mask}")

    def get_srq_mask(self) -> int:
        """Return the GPIB SRQ mask (SV). GPIB only."""
        if self.is_rs232:
            msg = "The command 'SV' (SRQ mask) may only be sent via the GPIB interface."
            raise Exception(msg)

        return self._query_int("SV")

    def set_rs232_wait(self, wait: int) -> None:
        """Set the RS-232 character wait interval to wait x 3.3 ms, 0 ... 25 (SW). RS-232 only."""
        self._require_rs232("SW")

        wait = int(wait)
        if not 0 <= wait <= self.RS232_WAIT_MAX:
            msg = f"The RS-232 wait interval {wait} is outside the allowed range 0 ... {self.RS232_WAIT_MAX}."
            raise ValueError(msg)

        self.port.write(f"SW {wait}")

    def get_rs232_wait(self) -> int:
        """Return the RS-232 character wait interval (SW). RS-232 only."""
        self._require_rs232("SW")
        return self._query_int("SW")

    def set_rs232_terminator(self, ascii_codes: list[int]) -> None:
        """Set up to four RS-232 end-of-record characters by their ASCII codes (SE). RS-232 only.

        Changing the terminator invalidates the 'EOL' port property of this driver, so it is
        normally only used to restore the default with reset_rs232_terminator().
        """
        self._require_rs232("SE")

        if not 1 <= len(ascii_codes) <= 4:
            msg = "Between one and four RS-232 terminator characters have to be given."
            raise ValueError(msg)

        for code in ascii_codes:
            if not 0 <= int(code) <= 127:
                msg = f"The ASCII code {code} is outside the allowed range 0 ... 127."
                raise ValueError(msg)

        self.port.write("SE " + ",".join(str(int(code)) for code in ascii_codes))

    def reset_rs232_terminator(self) -> None:
        """Restore the default RS-232 end-of-record sequence (SE without argument). RS-232 only."""
        self._require_rs232("SE")
        self.port.write("SE")

    # ==================================================================
    #  wrapped instrument commands -- DATA
    # ==================================================================

    def get_counts(self, counter: str) -> int:
        """Return the most recent complete data point of counter 'A' or 'B' (QA/QB).

        Should only be used after the Data Ready status bit was set; the SR400 returns -1 if no
        data is available or if counter B is preset.
        """
        counter = self._check_data_counter(counter)
        counts = self._query_int(f"Q{counter}")
        if counts < 0:
            msg = (
                f"The SR400 returned -1 for 'Q{counter}': no count data is available yet, or "
                f"counter B is the preset counter."
            )
            raise Exception(msg)

        return counts

    def get_scan_point(self, counter: str, point: int) -> int:
        """Return data point 'point' (1 ... 2000) of the scan buffer of counter 'A' or 'B' (QA/QB m)."""
        counter = self._check_data_counter(counter)
        point = int(point)
        if not 1 <= point <= self.PERIODS_MAX:
            msg = f"The scan point {point} is outside the allowed range 1 ... {self.PERIODS_MAX}."
            raise ValueError(msg)

        counts = self._query_int(f"Q{counter} {point}")
        if counts < 0:
            msg = (
                f"The SR400 returned -1 for 'Q{counter} {point}': the count period is not "
                f"completed yet, or counter B is the preset counter."
            )
            raise Exception(msg)

        return counts

    def get_counter_contents(self, counter: str) -> int:
        """Return the current contents of counter 'A' or 'B' regardless of the count state (XA/XB).

        Returns 0 during the dwell time, while paused and in reset. Only useful for long count
        periods and slow count rates, because at high rates the value can be wrong.
        """
        counter = self._check_data_counter(counter)
        return self._query_int(f"X{counter}")

    def dump_scan_buffer(self, counter: str, number_of_points: int) -> list[int]:
        """Read a complete scan buffer with the E commands (EA/EB).

        May only be used while the counters are paused at the end of a scan. Faster than reading
        the points one by one, but without handshaking: a single lost value desynchronises the
        transfer, therefore the measurement path of this driver uses get_scan_point() instead.
        """
        counter = self._check_data_counter(counter)
        number_of_points = int(number_of_points)
        if not 1 <= number_of_points <= self.PERIODS_MAX:
            msg = f"The number of points {number_of_points} is outside the allowed range 1 ... {self.PERIODS_MAX}."
            raise ValueError(msg)

        self.port.write(f"E{counter}")
        return [int(float(self.port.read())) for _ in range(number_of_points)]

    def start_scan_with_data_transfer(self, counter: str) -> None:
        """Start a new scan and let the SR400 send every data point when it is ready (FA/FB).

        May only be sent while the counters are in reset. The caller has to read exactly
        'number of periods' values; resetting the counters before all points are received
        terminates the transfer.
        """
        counter = self._check_data_counter(counter)
        self.port.write(f"F{counter}")

    # ==================================================================
    #  small validation helpers
    # ==================================================================

    @staticmethod
    def _lookup(table: dict, key: str, description: str) -> int:
        """Translate a GUI string into the numeric command parameter."""
        if key not in table:
            msg = f"'{key}' is not a valid {description}. Allowed: {', '.join(table.keys())}."
            raise ValueError(msg)

        return table[key]

    @staticmethod
    def _reverse_lookup(table: dict, value: int) -> str:
        """Translate a numeric instrument answer back into the readable name."""
        for name, number in table.items():
            if number == value:
                return name

        msg = f"The SR400 returned the unexpected value {value}."
        raise Exception(msg)

    def _check_counter(self, counter: str) -> str:
        """Validate a counter or discriminator identifier 'A', 'B' or 'T'."""
        counter = str(counter).strip().upper()
        if counter not in self.COUNTER_INDICES:
            msg = f"'{counter}' is not a valid counter. Allowed: A, B, T."
            raise ValueError(msg)

        return counter

    def _check_data_counter(self, counter: str) -> str:
        """Validate a data counter identifier: only counters A and B hold count data."""
        counter = self._check_counter(counter)
        if counter == "T":
            msg = "Only the counters A and B provide count data; counter T is the preset counter."
            raise ValueError(msg)

        return counter

    def _check_gate(self, gate: str) -> int:
        """Validate a gate identifier 'A' or 'B' and return its command index."""
        gate = str(gate).strip().upper()
        if gate not in self.GATE_INDICES:
            msg = f"'{gate}' is not a valid gate. Allowed: A, B."
            raise ValueError(msg)

        return self.GATE_INDICES[gate]

    @staticmethod
    def _check_port_number(port_number: int) -> int:
        """Validate a rear panel analog output number, 1 or 2."""
        port_number = int(port_number)
        if port_number not in (1, 2):
            msg = f"'{port_number}' is not a valid PORT number. Allowed: 1, 2."
            raise ValueError(msg)

        return port_number

    @staticmethod
    def _check_limit(value: float, limit: float, description: str, unit: str) -> None:
        """Check a symmetric value range."""
        if not -limit <= value <= limit:
            msg = f"The {description} {value} {unit} is outside the allowed range +-{limit} {unit}."
            raise ValueError(msg)

    def _require_rs232(self, command: str) -> None:
        """Reject commands the SR400 only accepts via the RS-232 interface."""
        if not self.is_rs232:
            msg = f"The command '{command}' may only be sent via the RS-232 interface."
            raise Exception(msg)
