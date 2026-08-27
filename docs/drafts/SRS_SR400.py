# SweepMe! driver for Stanford Research Systems SR400
#
# The SR400 is a gated photon counter with RS-232 and IEEE-488/GPIB
# interfaces. It does not implement SCPI/*IDN?; communication uses the
# two-letter ASCII command set documented in the SR400 manual.
#
# Primary references:
# - SRS SR400 manual, Revision 2.7 (11/2018), Remote Programming
# - SweepMe! EmptyDeviceClass.py
# - SweepMe! driver_template_for_gpt_simple.py
#
# Important:
# - Configure the SR400 RS-232 interface with ECHO=OFF when using a computer.
# - The driver uses CRLF as the command terminator. The SR400 accepts CR,
#   LF, or both for incoming commands.
# - The default measurement architecture uses one SR400 count period per
#   SweepMe! measurement point. N PERIODS is therefore forced to 1.
#
# The SR400's counter preset command (CP) accepts only the most significant
# digit of the supplied preset value. Therefore the T/B preset parameters
# are exposed as strings such as "1E7", matching the instrument manual.

from __future__ import annotations

import time

from pysweepme.EmptyDeviceClass import EmptyDevice


class Device(EmptyDevice):
    """Stanford Research Systems SR400 gated photon counter."""

    # SR400 command mappings from the manual.
    _COUNT_MODES = {
        "A,B FOR T PRESET": 0,
        "A-B FOR T PRESET": 1,
        "A+B FOR T PRESET": 2,
        "A FOR B PRESET": 3,
    }

    _INPUTS = {
        "10 MHz": 0,
        "INPUT 1": 1,
        "INPUT 2": 2,
        "TRIG": 3,
    }

    _GATE_MODES = {
        "CW": 0,
        "FIXED": 1,
        "SCAN": 2,
    }

    _SLOPES = {
        "RISE": 0,
        "FALL": 1,
    }

    _DISC_MODES = {
        "FIXED": 0,
        "SCAN": 1,
    }

    def __init__(self) -> None:
        super().__init__()

        self.variables = ["Count A", "Count B"]
        self.units = ["counts", "counts"]
        self.plottype = [True, True]
        self.savetype = [True, True]

        # Communication is handled by the SweepMe! Port Manager.
        self.port_manager = True
        self.port_types = ["GPIB", "COM"]
        self.port_properties = {
            "timeout": 10,
            "baudrate": 9600,
            "stopbits": 1,
            "parity": "N",
            "EOL": "\r\n",
        }

        self.count_mode = "A,B FOR T PRESET"
        self.a_input = "INPUT 1"
        self.b_input = "INPUT 2"
        self.t_input = "10 MHz"

        # SR400 CP values are counter cycles. For T=10 MHz,
        # 1E7 corresponds to approximately one second.
        self.b_preset = "1E3"
        self.t_preset = "1E7"

        self.a_gate_mode = "CW"
        self.b_gate_mode = "CW"
        self.a_delay = 0.0
        self.a_width = 1.0e-6
        self.b_delay = 0.0
        self.b_width = 1.0e-6

        self.trigger_slope = "RISE"
        self.trigger_level = 2.0

        self.a_disc_slope = "RISE"
        self.a_disc_mode = "FIXED"
        self.a_disc_level = -0.010

        self.b_disc_slope = "RISE"
        self.b_disc_mode = "FIXED"
        self.b_disc_level = -0.010

        self.t_disc_slope = "RISE"
        self.t_disc_mode = "FIXED"
        self.t_disc_level = -0.010

        self.poll_interval = 0.01
        self.measurement_timeout = 15.0

        self.measured_count_a = 0
        self.measured_count_b = 0

    def set_GUIparameter(self) -> dict:
        """Return SweepMe! GUI parameters."""
        return {
            "Count Mode": list(self._COUNT_MODES.keys()),
            "A Input": ["INPUT 1", "10 MHz"],
            "B Input": ["INPUT 2", "INPUT 1"],
            "T Input": ["10 MHz", "INPUT 2", "TRIG"],
            "B Preset": "1E3",
            "T Preset": "1E7",
            "A Gate": ["CW", "FIXED", "SCAN"],
            "A Delay [s]": 0.0,
            "A Width [s]": 1.0e-6,
            "B Gate": ["CW", "FIXED", "SCAN"],
            "B Delay [s]": 0.0,
            "B Width [s]": 1.0e-6,
            "Trigger Slope": ["RISE", "FALL"],
            "Trigger Level [V]": 2.0,
            "A Disc Slope": ["RISE", "FALL"],
            "A Disc Mode": ["FIXED", "SCAN"],
            "A Disc Level [V]": -0.010,
            "B Disc Slope": ["RISE", "FALL"],
            "B Disc Mode": ["FIXED", "SCAN"],
            "B Disc Level [V]": -0.010,
            "T Disc Slope": ["RISE", "FALL"],
            "T Disc Mode": ["FIXED", "SCAN"],
            "T Disc Level [V]": -0.010,
            "Baudrate": ["9600", "19200", "4800", "2400", "1200", "300"],
        }

    def get_GUIparameter(self, parameter: dict) -> None:
        """Store SweepMe! GUI parameters."""
        self.count_mode = parameter["Count Mode"]
        self.a_input = parameter["A Input"]
        self.b_input = parameter["B Input"]
        self.t_input = parameter["T Input"]

        self.b_preset = str(parameter["B Preset"]).strip()
        self.t_preset = str(parameter["T Preset"]).strip()

        self.a_gate_mode = parameter["A Gate"]
        self.a_delay = float(parameter["A Delay [s]"])
        self.a_width = float(parameter["A Width [s]"])

        self.b_gate_mode = parameter["B Gate"]
        self.b_delay = float(parameter["B Delay [s]"])
        self.b_width = float(parameter["B Width [s]"])

        self.trigger_slope = parameter["Trigger Slope"]
        self.trigger_level = float(parameter["Trigger Level [V]"])

        self.a_disc_slope = parameter["A Disc Slope"]
        self.a_disc_mode = parameter["A Disc Mode"]
        self.a_disc_level = float(parameter["A Disc Level [V]"])

        self.b_disc_slope = parameter["B Disc Slope"]
        self.b_disc_mode = parameter["B Disc Mode"]
        self.b_disc_level = float(parameter["B Disc Level [V]"])

        self.t_disc_slope = parameter["T Disc Slope"]
        self.t_disc_mode = parameter["T Disc Mode"]
        self.t_disc_level = float(parameter["T Disc Level [V]"])

        self.port_properties["baudrate"] = int(parameter["Baudrate"])

    def connect(self) -> None:
        """Verify communication and clear any old SR400 status conditions.

        The SR400 has no standard *IDN? command. SS returns the status byte
        and clears it, so it is used as the communication test.
        """
        status = self.get_status_byte()
        if status & 0x80:
            raise RuntimeError(
                f"SR400 reported a command/interface error during connect "
                f"(status byte 0x{status:02X})."
            )

    def configure(self) -> None:
        """Configure one SR400 count period for each SweepMe! point."""
        # Stop/reset before changing timing or counter configuration.
        self.reset()

        self.set_count_mode(self.count_mode)

        self.set_counter_input(0, self.a_input)
        self.set_counter_input(1, self.b_input)
        self.set_counter_input(2, self.t_input)

        # One SR400 count period corresponds to one SweepMe! point.
        self.set_n_periods(1)
        self.set_scan_end_mode("STOP")

        # Internal dwell is not needed because SweepMe! controls the
        # measurement-point sequence.
        self.set_dwell(0.0)

        # Presets. CP accepts counter B (1) and counter T (2).
        self.set_counter_preset(1, self.b_preset)
        self.set_counter_preset(2, self.t_preset)

        self.set_gate_mode(0, self.a_gate_mode)
        self.set_gate_mode(1, self.b_gate_mode)
        self.set_gate_delay(0, self.a_delay)
        self.set_gate_width(0, self.a_width)
        self.set_gate_delay(1, self.b_delay)
        self.set_gate_width(1, self.b_width)

        self.set_trigger_slope(self.trigger_slope)
        self.set_trigger_level(self.trigger_level)

        self.set_discriminator_slope(0, self.a_disc_slope)
        self.set_discriminator_mode(0, self.a_disc_mode)
        self.set_discriminator_level(0, self.a_disc_level)

        self.set_discriminator_slope(1, self.b_disc_slope)
        self.set_discriminator_mode(1, self.b_disc_mode)
        self.set_discriminator_level(1, self.b_disc_level)

        self.set_discriminator_slope(2, self.t_disc_slope)
        self.set_discriminator_mode(2, self.t_disc_mode)
        self.set_discriminator_level(2, self.t_disc_level)

        # Clear all status conditions generated while configuring.
        self.get_status_byte()

    def measure(self) -> None:
        """Run one count period and read the completed A/B count values."""
        # Reset so every SweepMe! point starts from a clean counter state.
        self.reset()
        self.get_status_byte()

        # Start the next count period.
        self.start()

        deadline = time.monotonic() + self.measurement_timeout

        while True:
            if time.monotonic() >= deadline:
                self.stop()
                raise TimeoutError(
                    "Timed out waiting for the SR400 Data Ready status."
                )

            status = self.get_status_byte()

            if status & 0x80:
                raise RuntimeError(
                    f"SR400 command error during measurement "
                    f"(status byte 0x{status:02X})."
                )

            if status & 0x08:
                raise RuntimeError(
                    f"SR400 counter overrun (status byte 0x{status:02X})."
                )

            if status & 0x10:
                raise RuntimeError(
                    f"SR400 rate/gate error (status byte 0x{status:02X})."
                )

            if status & 0x01:
                # Parameter changed from the front panel. It is not fatal,
                # but the configured state may no longer be what was requested.
                self.message_log(
                    "SR400 parameter changed from the front panel during measurement."
                )

            if status & 0x02:
                break

            time.sleep(self.poll_interval)

        self.measured_count_a = self.read_counter_a()
        self.measured_count_b = self.read_counter_b()

    def call(self) -> list[float]:
        """Return measured counter values to SweepMe!."""
        return [
            float(self.measured_count_a),
            float(self.measured_count_b),
        ]

    # ------------------------------------------------------------------
    # SR400 communication helpers
    # ------------------------------------------------------------------

    def _write(self, command: str) -> None:
        """Send one SR400 command."""
        self.port.write(command)

    def _query(self, command: str) -> str:
        """Send one query and return its response without line endings."""
        self.port.write(command)
        return str(self.port.read()).strip()

    # ------------------------------------------------------------------
    # Interface/status
    # ------------------------------------------------------------------

    def get_status_byte(self) -> int:
        """Read and clear the SR400 status byte."""
        response = self._query("SS")
        try:
            return int(response)
        except ValueError as exc:
            raise ValueError(
                f"Invalid SR400 status-byte response: {response!r}"
            ) from exc

    def get_secondary_status_byte(self) -> int:
        """Read and clear the SR400 secondary status byte."""
        response = self._query("SI")
        try:
            return int(response)
        except ValueError as exc:
            raise ValueError(
                f"Invalid SR400 secondary status response: {response!r}"
            ) from exc

    def reset(self) -> None:
        """Reset the SR400 counters and scan state."""
        self._write("CR")

    def start(self) -> None:
        """Start a count period."""
        self._write("CS")

    def stop(self) -> None:
        """Stop/pause the current count operation."""
        self._write("CH")

    # ------------------------------------------------------------------
    # Mode
    # ------------------------------------------------------------------

    def set_count_mode(self, mode: str) -> None:
        """Set the SR400 count/display mode."""
        try:
            value = self._COUNT_MODES[mode]
        except KeyError as exc:
            raise ValueError(f"Unsupported count mode: {mode}") from exc
        self._write(f"CM {value}")

    def get_count_mode(self) -> int:
        """Read the numeric SR400 count mode."""
        return int(self._query("CM"))

    def set_counter_input(self, counter: int, input_name: str) -> None:
        """Set counter A/B/T input."""
        if counter not in (0, 1, 2):
            raise ValueError("Counter must be 0 (A), 1 (B), or 2 (T).")
        try:
            input_number = self._INPUTS[input_name]
        except KeyError as exc:
            raise ValueError(f"Unsupported SR400 input: {input_name}") from exc
        self._write(f"CI {counter},{input_number}")

    def get_counter_input(self, counter: int) -> int:
        """Read the numeric input selection for counter A/B/T."""
        if counter not in (0, 1, 2):
            raise ValueError("Counter must be 0 (A), 1 (B), or 2 (T).")
        return int(self._query(f"CI {counter}"))

    def set_counter_preset(self, counter: int, preset: str) -> None:
        """Set counter B or T preset.

        The SR400 accepts only counter 1 (B) and 2 (T) for CP.
        The manual specifies that only the most significant digit
        of the supplied value is used.
        """
        if counter not in (1, 2):
            raise ValueError("SR400 CP supports counter 1 (B) or 2 (T).")

        preset = str(preset).strip()
        if not preset:
            raise ValueError("Counter preset must not be empty.")

        self._write(f"CP {counter},{preset}")

    def get_counter_preset(self, counter: int) -> str:
        """Read counter B or T preset."""
        if counter not in (1, 2):
            raise ValueError("SR400 CP supports counter 1 (B) or 2 (T).")
        return self._query(f"CP {counter}")

    def set_n_periods(self, periods: int) -> None:
        """Set the SR400 scan length."""
        periods = int(periods)
        if not 1 <= periods <= 2000:
            raise ValueError("N PERIODS must be between 1 and 2000.")
        self._write(f"NP {periods}")

    def get_n_periods(self) -> int:
        """Read the SR400 scan length."""
        return int(self._query("NP"))

    def set_scan_end_mode(self, mode: str) -> None:
        """Set AT N to STOP or START."""
        values = {"STOP": 0, "START": 1}
        try:
            value = values[mode.upper()]
        except KeyError as exc:
            raise ValueError("Scan end mode must be STOP or START.") from exc
        self._write(f"NE {value}")

    def set_dwell(self, dwell_seconds: float) -> None:
        """Set internal dwell time; zero selects EXTERNAL dwell."""
        dwell_seconds = float(dwell_seconds)
        if dwell_seconds == 0:
            self._write("DT 0")
        elif not 2e-3 <= dwell_seconds <= 60.0:
            raise ValueError(
                "SR400 dwell must be 0 (EXTERNAL) or between 2 ms and 60 s."
            )
        else:
            self._write(f"DT {dwell_seconds:g}")

    # ------------------------------------------------------------------
    # Trigger and discriminator levels
    # ------------------------------------------------------------------

    def set_trigger_slope(self, slope: str) -> None:
        try:
            value = self._SLOPES[slope]
        except KeyError as exc:
            raise ValueError(f"Unsupported trigger slope: {slope}") from exc
        self._write(f"TS {value}")

    def set_trigger_level(self, level: float) -> None:
        level = float(level)
        if not -2.0 <= level <= 2.0:
            raise ValueError("Trigger level must be between -2 V and +2 V.")
        self._write(f"TL {level:g}")

    def set_discriminator_slope(self, discriminator: int, slope: str) -> None:
        if discriminator not in (0, 1, 2):
            raise ValueError("Discriminator must be A=0, B=1, or T=2.")
        try:
            value = self._SLOPES[slope]
        except KeyError as exc:
            raise ValueError(f"Unsupported discriminator slope: {slope}") from exc
        self._write(f"DS {discriminator},{value}")

    def set_discriminator_mode(self, discriminator: int, mode: str) -> None:
        if discriminator not in (0, 1, 2):
            raise ValueError("Discriminator must be A=0, B=1, or T=2.")
        try:
            value = self._DISC_MODES[mode]
        except KeyError as exc:
            raise ValueError(f"Unsupported discriminator mode: {mode}") from exc
        self._write(f"DM {discriminator},{value}")

    def set_discriminator_level(self, discriminator: int, level: float) -> None:
        if discriminator not in (0, 1, 2):
            raise ValueError("Discriminator must be A=0, B=1, or T=2.")
        level = float(level)
        if not -0.3000 <= level <= 0.3000:
            raise ValueError(
                "Discriminator level must be between -0.300 V and +0.300 V."
            )
        self._write(f"DL {discriminator},{level:g}")

    # ------------------------------------------------------------------
    # Gates
    # ------------------------------------------------------------------

    def set_gate_mode(self, gate: int, mode: str) -> None:
        """Set A/B gate mode."""
        if gate not in (0, 1):
            raise ValueError("Gate must be A=0 or B=1.")
        try:
            value = self._GATE_MODES[mode]
        except KeyError as exc:
            raise ValueError(f"Unsupported gate mode: {mode}") from exc
        self._write(f"GM {gate},{value}")

    def set_gate_delay(self, gate: int, delay_seconds: float) -> None:
        """Set A/B gate delay in seconds."""
        if gate not in (0, 1):
            raise ValueError("Gate must be A=0 or B=1.")
        delay_seconds = float(delay_seconds)
        if not 0.0 <= delay_seconds <= 999.2e-3:
            raise ValueError("Gate delay must be between 0 and 999.2 ms.")
        self._write(f"GD {gate},{delay_seconds:g}")

    def set_gate_width(self, gate: int, width_seconds: float) -> None:
        """Set A/B gate width in seconds."""
        if gate not in (0, 1):
            raise ValueError("Gate must be A=0 or B=1.")
        width_seconds = float(width_seconds)
        if not 0.005e-6 <= width_seconds <= 999.2e-3:
            raise ValueError(
                "Gate width must be between 5 ns and 999.2 ms."
            )
        self._write(f"GW {gate},{width_seconds:g}")

    # ------------------------------------------------------------------
    # Counter data
    # ------------------------------------------------------------------

    def read_counter_a(self) -> int:
        """Read the most recent complete A count."""
        response = self._query("QA")
        return self._parse_count(response, "A")

    def read_counter_b(self) -> int:
        """Read the most recent complete B count."""
        response = self._query("QB")
        return self._parse_count(response, "B")

    @staticmethod
    def _parse_count(response: str, counter: str) -> int:
        try:
            value = int(response)
        except ValueError as exc:
            raise ValueError(
                f"Invalid SR400 counter {counter} response: {response!r}"
            ) from exc

        if value < 0:
            # -1 is documented as "data not ready" for QA/QB. It should
            # not normally occur here because measure() polls Data Ready.
            raise RuntimeError(
                f"SR400 counter {counter} returned {value}; "
                "the data point was not available."
            )

        return value

    # ------------------------------------------------------------------
    # Additional useful wrapped commands
    # ------------------------------------------------------------------

    def read_counter_a_live(self) -> int:
        """Read the current contents of counter A using XA."""
        return self._parse_count(self._query("XA"), "A")

    def read_counter_b_live(self) -> int:
        """Read the current contents of counter B using XB."""
        return self._parse_count(self._query("XB"), "B")

    def set_port_level(self, port: int, voltage: float) -> None:
        """Set PORT1 or PORT2 fixed output level."""
        if port not in (1, 2):
            raise ValueError("Port must be 1 or 2.")
        voltage = float(voltage)
        if not -10.0 <= voltage <= 10.0:
            raise ValueError("PORT output must be between -10 V and +10 V.")
        self._write(f"PM {port},0")
        self._write(f"PL {port},{voltage:g}")

    def get_port_level(self, port: int) -> float:
        """Read PORT1 or PORT2 starting/fixed output level."""
        if port not in (1, 2):
            raise ValueError("Port must be 1 or 2.")
        return float(self._query(f"PL {port}"))

    def store_setup(self, location: int) -> None:
        """Store instrument settings to SR400 setup memory 1..9."""
        location = int(location)
        if not 1 <= location <= 9:
            raise ValueError("SR400 setup location must be 1..9.")
        self._write(f"ST {location}")

    def recall_setup(self, location: int) -> None:
        """Recall SR400 setup memory 0..9; 0 is the default setup."""
        location = int(location)
        if not 0 <= location <= 9:
            raise ValueError("SR400 setup location must be 0..9.")
        self._write(f"RC {location}")

    def deinitialize(self) -> None:
        """Leave the counters reset when the measurement is finished."""
        self.reset()
