# This Device Class is published under the terms of the MIT License.
#
# Two-tier hardware self-test for the Stanford Research Systems SR400 driver.
#
# The virtual bench in tests/ verifies the driver's logic against a simulator built from the
# same manual the driver was written from. What it cannot verify is anything about a real
# instrument: response *formats*, command-processing latency, and every electrical behaviour.
# README sections 7.1 and 7.3 list exactly those assumptions. This module is how they get
# closed out, and the report file it writes is the deliverable.
#
# Every command here is documented in the SR400 manual, chapter "REMOTE PROGRAMMING --
# DETAILED COMMAND LIST" (manual pp. 37-47), and is issued through the driver's own wrapped
# commands rather than re-implemented.

from __future__ import annotations

import os
import time


class Report:
    """A check accumulator that also builds the report file.

    Deliberately the same shape as the check() helper in tests/test_sr400_virtual.py, so the
    virtual bench and the hardware self-test read alike and a failure in either is recognisable
    to someone who has only read the other.
    """

    def __init__(self, device, title: str) -> None:
        self.device = device
        self.title = title
        self.lines: list[str] = []
        self.checks = 0
        self.failures: list[str] = []
        self.aborted = False
        self.write_error = ""
        self.headline = ""  # one-line result for the end-of-run message

    # -- accumulating -------------------------------------------------------
    def check(self, condition: bool, description: str) -> bool:
        self.checks += 1
        self.lines.append(("  ok    " if condition else "  FAIL  ") + description)
        if not condition:
            self.failures.append(description)
        return bool(condition)

    def section(self, name: str) -> None:
        self.lines.append("")
        self.lines.append(f"== {name}")
        self.device.message_info(f"SR400 self-test: {name}")

    def note(self, text: str) -> None:
        self.lines.append(f"        {text}")

    def table(self, rows: list[tuple[str, str]], header: tuple[str, str]) -> None:
        width = max([len(header[0])] + [len(r[0]) for r in rows]) if rows else len(header[0])
        self.lines.append(f"        {header[0]:<{width}}  {header[1]}")
        self.lines.append(f"        {'-' * width}  {'-' * 40}")
        for name, value in rows:
            self.lines.append(f"        {name:<{width}}  {value}")

    @property
    def passed(self) -> int:
        return self.checks - len(self.failures)

    # -- writing out --------------------------------------------------------
    def write(self, timestamp: str) -> str:
        """Write the report and return its path, or '' if it could not be written."""
        head = [
            f"SR400 {self.title}",
            "=" * 72,
            f"when            : {timestamp}",
            f"port            : {self.device.port_string or '(none)'}",
            f"interface       : {'RS-232' if self.device.is_rs232 else 'GPIB'}",
            f"driver          : {os.path.basename(os.path.dirname(os.path.abspath(__file__)))}",
            "",
            "No instrument storage slot was used: the settings this test changes were saved by",
            "querying them and restored individually. ST would have clobbered a user setup slot",
            "and RC 0 would have been destructive, so neither was sent. SE was never sent either",
            "-- reprogramming the RS-232 terminator mid-test can break communication with no way",
            "back.",
        ]
        body = head + self.lines + [
            "",
            "=" * 72,
            f"{self.passed}/{self.checks} checks passed",
        ]
        for failure in self.failures:
            body.append(f"  FAILED: {failure}")

        safe = "".join(c if c.isalnum() else "_" for c in self.title.lower())
        name = f"SR400_{safe}_{timestamp.replace(':', '').replace(' ', '_')}.txt"

        # DATADEVICES first: SweepMe!'s folder for device-specific data, under Public Documents
        # (C:\Users\Public\Documents\SweepMe!\DataDevices), persistent and easy to find on a
        # remote machine. TEMP is SweepMe!'s scratch area for the current measurement
        # (AppData\Local\SweepMe!\temp) -- hidden, and not somewhere a deliverable should live --
        # so it is only the fallback. Each failure's reason is kept: "could not be written"
        # with no cause wastes an afternoon, and the report is the point of the exercise.
        driver = os.path.basename(os.path.dirname(os.path.abspath(__file__)))
        errors = []
        for identifier in ("DATADEVICES", "TEMP"):
            try:
                folder = self.device.get_folder(identifier)
                if identifier == "DATADEVICES":
                    folder = os.path.join(folder, driver)
                os.makedirs(folder, exist_ok=True)
                path = os.path.join(folder, name)
                with open(path, "w") as handle:
                    handle.write("\n".join(body) + "\n")
                return path
            except Exception as exc:  # noqa: BLE001 -- try the next location
                errors.append(f"{identifier}: {type(exc).__name__}: {exc}")

        self.write_error = "; ".join(errors)
        return ""


# ==========================================================================
#  shared scaffolding
# ==========================================================================

# Every setting either tier touches, as (query, setter). Saved by reading the instrument and
# restored in a finally. Note what is absent: PORT levels in tier 1 (they may be driving
# apparatus, so tier 1 does not go near them) and the RS-232 terminator (never touched at all).
SAVED_SETTINGS = (
    ("CM", "CM {}"),
    ("CI 0", "CI 0,{}"),
    ("CI 1", "CI 1,{}"),
    ("CI 2", "CI 2,{}"),
    ("CP 1", "CP 1,{}"),
    ("CP 2", "CP 2,{}"),
    ("NP", "NP {}"),
    ("NE", "NE {}"),
    ("DT", "DT {}"),
    ("TS", "TS {}"),
    ("TL", "TL {}"),
    ("DS 0", "DS 0,{}"),
    ("DS 1", "DS 1,{}"),
    ("DS 2", "DS 2,{}"),
    ("DM 0", "DM 0,{}"),
    ("DM 1", "DM 1,{}"),
    ("DM 2", "DM 2,{}"),
    ("DL 0", "DL 0,{}"),
    ("DL 1", "DL 1,{}"),
    ("DL 2", "DL 2,{}"),
    ("GM 0", "GM 0,{}"),
    ("GM 1", "GM 1,{}"),
    ("GD 0", "GD 0,{}"),
    ("GD 1", "GD 1,{}"),
    ("GW 0", "GW 0,{}"),
    ("GW 1", "GW 1,{}"),
    ("SD", "SD {}"),
)

PORT_SETTINGS = (
    ("PM 1", "PM 1,{}"),
    ("PM 2", "PM 2,{}"),
    ("PL 1", "PL 1,{}"),
    ("PL 2", "PL 2,{}"),
)


def _refuse_if_busy(device) -> str:
    """Return a reason to refuse, or '' when it is safe to proceed.

    An action can be clicked at any moment, including in the middle of an experiment. Counting
    is the state where interfering actually destroys data, so it is checked against the
    instrument rather than against driver state.
    """
    if not device.port_string:
        return "select a port first -- there is nothing to test yet"

    # is_run_stopped() returns pysweepme's _is_run_stopped flag, which means "the user asked
    # for the current run to stop" -- it does NOT mean "a run is active". Outside a run it is
    # simply False, so treating `not is_run_stopped()` as "busy" would refuse every click on an
    # idle instrument, and treating True as "busy" would be backwards during an actual stop.
    # Only one direction is meaningful: True means a stop is being processed, so stay out of it.
    if hasattr(device, "is_run_stopped"):
        try:
            if device.is_run_stopped():
                return (
                    "a run is being stopped right now. Let it finish, then click again -- this "
                    "test reprograms the counters and the driver is still tearing down"
                )
        except Exception:  # noqa: BLE001 -- not always available outside a run
            pass

    try:
        if device.get_secondary_status_bit(2):
            return (
                "the SR400 is counting. Stop it first (front-panel STOP, or end the run): this "
                "test reprograms the counters and would corrupt whatever is being counted"
            )
    except Exception as exc:  # noqa: BLE001
        return f"the SR400 did not answer a status query ({exc}), so nothing was changed"

    return ""


def _save_settings(device, settings) -> dict:
    """Read back every setting the test will change. Missing answers are simply not restored."""
    saved = {}
    for query, _ in settings:
        try:
            saved[query] = device._query(query)
        except Exception:  # noqa: BLE001 -- an unreadable setting is one we must not restore
            pass

    return saved


def _restore_settings(device, settings, saved) -> list[str]:
    """Put every saved setting back. Returns the names of any that could not be restored."""
    failed = []
    for query, template in settings:
        if query not in saved:
            continue
        value = saved[query].strip()
        if value == "":
            continue
        try:
            device.port.write(template.format(value))
        except Exception:  # noqa: BLE001
            failed.append(query)

    return failed


def _timestamp() -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S")


# --- timings ---------------------------------------------------------------
# Module-level so the virtual bench can shrink them. On hardware these are the values that
# matter: the known-answer test is the manual's own one-second check (p. 33), and shortening it
# would weaken the one result everything else depends on. Against the simulator the counts are
# exact by construction whatever the duration, so the bench loses nothing by running them short
# and the suite stays quick enough to run after every edit.
KNOWN_ANSWER_SECONDS = 1.0
TIMEBASE_REPEATS = 3
SCAN_COUNT_TIME = 0.1
SCAN_PERIODS = 10
EXTERNAL_COUNT_TIME = 0.01
THROUGHPUT_QUERIES = 100
TRIGGER_PROBE_TIMEOUT = 3.0


# ==========================================================================
#  TIER 1 -- no cabling changes
# ==========================================================================

RESPONSE_FORMAT_QUERIES = (
    "CM",
    "CI 0", "CI 1", "CI 2",
    "CP 1", "CP 2",
    "NP", "NN", "NE",
    "DT",
    "AS", "AM", "SD",
    "TS", "TL",
    "DS 0", "DS 1", "DS 2",
    "DM 0", "DM 1", "DM 2",
    "DL 0", "DL 1", "DL 2",
    "DY 0", "DY 1", "DY 2",
    "PM 1", "PM 2",
    "PL 1", "PL 2",
    "PY 1", "PY 2",
    "GM 0", "GM 1",
    "GD 0", "GD 1",
    "GW 0", "GW 1",
    "GY 0", "GY 1",
    "SC", "MM", "ML",
    "SS", "SI",
    "QA", "QB",
    "XA", "XB",
)


def run_tier1(device) -> tuple[Report, str]:
    """Everything checkable with the instrument exactly as the user has it cabled."""
    report = Report(device, "self-test tier 1")
    saved = _save_settings(device, SAVED_SETTINGS)

    try:
        _tier1_known_answer(device, report)
        if report.aborted:
            return report, report.write(_timestamp())

        _tier1_response_formats(device, report)
        _tier1_one_significant_digit(device, report)
        _tier1_chained_queries(device, report)
        _tier1_status_semantics(device, report)
        _tier1_buffer_threshold(device, report)
        _tier1_timebase(device, report)
        _tier1_scan_machinery(device, report)
        _tier1_external_dwell(device, report)
        _tier1_throughput(device, report)
        _tier1_interface_gating(device, report)
        _tier1_coverage_note(device, report)
    finally:
        device.reset_counters()
        failed = _restore_settings(device, SAVED_SETTINGS, saved)
        report.section("restore")
        report.check(not failed, f"every changed setting was restored (unrestored: {failed or 'none'})")
        report.note("No storage slot was used; ST, RC and SE were never sent.")
        if device.is_rs232:
            # The driver runs with SW 0; the throughput section deliberately changes it.
            try:
                device.set_rs232_wait(0)
            except Exception:  # noqa: BLE001
                pass

    return report, report.write(_timestamp())


def _single_period_setup(device, count_time: float, source: str = "0") -> None:
    """Program one count period of 'count_time' seconds with counter A on 'source'.

    source '0' is the internal 10 MHz, '1' is INPUT 1, '2' is INPUT 2 (manual, CI).
    """
    device.reset_counters()
    device.port.write("CM 0")          # A,B for T preset
    device.port.write(f"CI 0,{source}")
    device.port.write("CI 2,0")        # counter T on the 10 MHz timebase
    device.port.write("GM 0,0")        # gate A CW: count everything
    device.port.write("GM 1,0")
    device.port.write("NP 1")
    device.port.write("NE 0")          # scan end mode STOP, required to read the buffer
    device.port.write("DT 0")          # EXTERNAL dwell: we start each period ourselves
    device.set_count_time(count_time)


def _count_one_period(device, timeout: float = 10.0) -> int:
    """Run exactly one count period and return counter A's buffer entry."""
    device.reset_counters()
    device.get_status_byte()
    device.start_counting()
    device._wait_for_status(device.STATUS_DATA_READY | device.STATUS_SCAN_FINISHED, timeout)
    return device.get_scan_point("A", 1)


def _tier1_known_answer(device, report) -> None:
    """The manual's own quick test (p. 33): count the timebase for one second."""
    report.section("known answer -- 10 MHz for 1 s must read exactly 10000000")
    expected = int(round(KNOWN_ANSWER_SECONDS * device.CLOCK_FREQUENCY))
    _single_period_setup(device, KNOWN_ANSWER_SECONDS, source="0")
    counts = _count_one_period(device, timeout=15.0)
    exact = report.check(
        counts == expected,
        f"counter A read {counts} in {KNOWN_ANSWER_SECONDS:g} s (want exactly {expected})",
    )
    if not exact:
        report.aborted = True
        report.note(
            "ABORTED. Everything below this depends on the preset arithmetic, the status "
            "polling and the buffer read all being correct. Fix this before trusting any "
            "other result: check Counter A input = 10 MHz, Counter T input = 10 MHz, and that "
            "the T preset really is 1E7."
        )


def _tier1_response_formats(device, report) -> None:
    """Record every getter's RAW answer, before any float() gets near it.

    This is the most valuable section: it is what settles README section 7.1. The driver parses
    every one of these through float(), so it survives either format -- but 'assumed 1E1-style'
    stops being an assumption only when someone reads the real string off real firmware.
    """
    report.section("response formats -- raw strings, verbatim")
    rows = []
    for query in RESPONSE_FORMAT_QUERIES:
        try:
            raw = device._query(query)
            rows.append((query, repr(raw)))
        except Exception as exc:  # noqa: BLE001
            rows.append((query, f"<no answer: {exc}>"))

    report.table(rows, ("query", "raw response"))
    answered = sum(1 for _, value in rows if not value.startswith("<no answer"))
    report.check(
        answered == len(rows),
        f"every getter answered ({answered}/{len(rows)})",
    )
    report.note("Compare these against README section 7.1 and retire what they settle.")


def _tier1_one_significant_digit(device, report) -> None:
    """CP and DT keep only the most significant digit (manual p. 39). Prove it."""
    report.section("one-significant-digit rule -- the count-time planner rests on this")

    device.port.write("CP 2,12")
    raw = device._query("CP 2")
    report.check(
        abs(float(raw) - 10.0) < 1e-9,
        f"CP 2,12 was truncated to 1E1 (read back {raw!r})",
    )

    device.port.write("DT 2.2E-3")
    raw = device._query("DT")
    report.check(
        abs(float(raw) - 2e-3) < 1e-9,
        f"DT 2.2E-3 was truncated to 2E-3 (read back {raw!r})",
    )
    report.note(
        "If either failed, plan_count_time() is solving the wrong problem and gotcha 3 is wrong."
    )


def _tier1_chained_queries(device, report) -> None:
    """The one unverified assumption behind Fast readout (batch queries)."""
    report.section("chained queries -- settles whether Fast readout is safe on this firmware")

    device.get_status_byte()
    device.port.write("CM;CI 0;GD 0")
    answers = []
    for _ in range(3):
        try:
            answers.append(str(device.port.read()).strip())
        except Exception:  # noqa: BLE001
            answers.append("")

    status = device.get_status_byte()
    ordered = len(answers) == 3 and all(a != "" for a in answers)
    clean = not status & device.STATUS_COMMAND_ERROR

    report.check(ordered, f"three answers arrived in order: {answers}")
    report.check(clean, f"no command error was raised by the chained line (status {status})")
    report.note(
        "RECOMMENDATION: enable 'Fast readout (batch queries)'."
        if (ordered and clean)
        else "RECOMMENDATION: leave 'Fast readout (batch queries)' OFF on this firmware."
    )
    report.note(
        "The manual documents chaining and also advises against relying on it (gotcha 16); "
        "this is that argument settled empirically for one instrument."
    )


def _tier1_status_semantics(device, report) -> None:
    """Reading SS clears it, and an illegal command really does set bit 7."""
    report.section("status byte semantics -- destructive read, and real error detection")

    device.get_status_byte()
    first = device.get_status_byte()
    second = device.get_status_byte()
    report.check(second == 0, f"a second SS read comes back clear ({first} then {second})")

    device.port.write("TL 5")  # out of range: -2.000 <= v <= 2.000 (manual p. 40)
    status = device.get_status_byte()
    report.check(
        bool(status & device.STATUS_COMMAND_ERROR),
        f"an out-of-range parameter set the command-error bit (status {status})",
    )
    report.check(
        device.get_status_byte() == 0,
        "and the bit cleared on the next read",
    )


def _tier1_buffer_threshold(device, report) -> None:
    """Confirm BUFFER_ERROR_CHARS empirically; BATCH_MAX_LINE_CHARS derives from it."""
    report.section("buffer threshold -- confirms BUFFER_ERROR_CHARS = 240")

    device.get_status_byte()
    padding = ";".join(["CM"] * 84)  # 84 * 3 - 1 = 251 characters
    report.note(f"sending a {len(padding)}-character command line")
    device.port.write(padding)
    time.sleep(0.2)
    status = device.get_status_byte()
    report.check(
        bool(status & device.STATUS_COMMAND_ERROR),
        f"a {len(padding)}-character line set the command-error bit (status {status})",
    )
    # Drain whatever answers did arrive before the line was cut off.
    device._drain_port()
    device.get_status_byte()
    report.note(
        f"The driver caps batched lines at {device.BATCH_MAX_LINE_CHARS} characters, which is "
        f"why this threshold matters even though nothing normally approaches it."
    )


def _tier1_timebase(device, report) -> None:
    """Count the crystal against the host clock. Crude, but catches a scaling error."""
    report.section(
        f"timebase cross-check -- 10 MHz against the host clock, {TIMEBASE_REPEATS} repeats",
    )

    expected = int(round(KNOWN_ANSWER_SECONDS * device.CLOCK_FREQUENCY))
    _single_period_setup(device, KNOWN_ANSWER_SECONDS, source="0")
    for repeat in range(1, TIMEBASE_REPEATS + 1):
        start = time.perf_counter()
        counts = _count_one_period(device, timeout=15.0)
        elapsed = time.perf_counter() - start
        error_ppm = (counts / max(expected, 1) - 1.0) * 1e6
        report.check(
            counts == expected,
            f"repeat {repeat}: {counts} counts in {elapsed:.4f} s host time "
            f"({error_ppm:+.1f} ppm against the nominal preset)",
        )

    report.note(
        "The counts are exact by construction -- the preset IS the count. What this really "
        "checks is that the host's elapsed time is near 1 s, i.e. that the preset scaling is "
        "right. The 25 ppm crystal spec (manual p. 5) cannot be measured against a PC clock."
    )


def _tier1_scan_machinery(device, report) -> None:
    """NP, the internal dwell, buffer indexing, NN, and the -1 past the end."""
    report.section(
        f"scan machinery -- {SCAN_PERIODS} periods of {SCAN_COUNT_TIME:g} s on the timebase",
    )

    device.reset_counters()
    device.port.write("CM 0")
    device.port.write("CI 0,0")
    device.port.write("CI 2,0")
    device.port.write("GM 0,0")
    device.port.write("NE 0")
    device.port.write(f"NP {SCAN_PERIODS}")
    device.port.write("DT 2E-3")
    device.set_count_time(SCAN_COUNT_TIME)

    device.get_status_byte()
    device.start_counting()
    status = device._wait_for_status(device.STATUS_SCAN_FINISHED, 30.0)
    report.check(
        bool(status & device.STATUS_SCAN_FINISHED),
        f"the scan-finished bit set at the end of a {SCAN_PERIODS}-period scan (status {status})",
    )

    per_period = int(round(SCAN_COUNT_TIME * device.CLOCK_FREQUENCY))
    values = []
    for point in range(1, SCAN_PERIODS + 1):
        try:
            values.append(device.get_scan_point("A", point))
        except Exception as exc:  # noqa: BLE001
            values.append(f"<{exc}>")

    exact = sum(1 for v in values if v == per_period)
    report.check(
        exact == SCAN_PERIODS,
        f"all {SCAN_PERIODS} buffer points read exactly {per_period} "
        f"({exact}/{SCAN_PERIODS}): {values}",
    )

    try:
        completed = device._query_int("NN")
        report.check(
            completed == SCAN_PERIODS,
            f"NN reports {SCAN_PERIODS} completed periods (got {completed})",
        )
    except Exception as exc:  # noqa: BLE001
        report.check(False, f"NN could be read ({exc})")

    past = SCAN_PERIODS + 1
    try:
        device.get_scan_point("A", past)
        report.check(False, f"QA {past} (past the end of the scan) is rejected")
    except Exception:
        report.check(True, f"QA {past} (past the end of the scan) returned -1 and was rejected")


def _tier1_external_dwell(device, report) -> None:
    """DT 0 means one START per count period (manual, DWELL menu)."""
    report.section("EXTERNAL dwell -- three periods, one START each")

    device.reset_counters()
    device.port.write("CM 0")
    device.port.write("CI 0,0")
    device.port.write("CI 2,0")
    device.port.write("GM 0,0")
    device.port.write("NE 0")
    device.port.write("NP 3")
    device.port.write("DT 0")
    device.set_count_time(EXTERNAL_COUNT_TIME)

    device.get_status_byte()
    for period in range(3):
        device.start_counting()
        device._wait_for_status(
            device.STATUS_DATA_READY | device.STATUS_SCAN_FINISHED,
            10.0,
        )
        report.note(f"period {period + 1} completed after its own START")

    each = int(round(EXTERNAL_COUNT_TIME * device.CLOCK_FREQUENCY))
    values = [device.get_scan_point("A", point) for point in range(1, 4)]
    report.check(
        all(v == each for v in values),
        f"three EXTERNAL-dwell periods of {EXTERNAL_COUNT_TIME:g} s each read {each} "
        f"(got {values})",
    )


def _tier1_throughput(device, report) -> None:
    """Measure what README section 6.2 currently derives."""
    report.section("throughput -- measured, not derived")

    def time_queries(count: int = THROUGHPUT_QUERIES) -> float:
        start = time.perf_counter()
        for _ in range(count):
            device._query("CM")
        return (time.perf_counter() - start) / count

    rows = []
    if device.is_rs232:
        try:
            device.set_rs232_wait(0)
            per_query = time_queries()
            rows.append(("SW 0 (driver default)", f"{per_query * 1e3:.2f} ms/query"))

            device.set_rs232_wait(6)
            slow = time_queries(max(5, THROUGHPUT_QUERIES // 5))
            rows.append(("SW 6 (factory default)", f"{slow * 1e3:.2f} ms/query"))
            rows.append(("penalty of leaving SW alone", f"x{slow / max(per_query, 1e-9):.1f}"))
        finally:
            device.set_rs232_wait(0)

        latency = device._get_com_latency_timer()
        rows.append(
            ("USB-serial latency timer", f"{latency} ms" if latency is not None else "unknown"),
        )
    else:
        per_query = time_queries()
        rows.append(("GPIB", f"{per_query * 1e3:.2f} ms/query"))

    reads_per_point = device._estimated_reads_per_point()
    rows.append(("reads per measurement point", str(reads_per_point)))
    rows.append(
        ("implied points/s", f"{1.0 / max(per_query * reads_per_point, 1e-9):.1f}"),
    )

    report.table(rows, ("what", "measured"))
    report.check(per_query > 0.0, "query timing was measured")
    report.note(
        "These are MEASURED. README section 6.2's table is derived from bit times and the "
        "adapter's documented default, and says so -- replace its numbers with these for this "
        "setup, keeping the measured/derived labelling."
    )


def _tier1_interface_gating(device, report) -> None:
    """MI/SW/SE are RS-232 only; SV is GPIB only (manual, command list)."""
    report.section("interface gating")

    if device.is_rs232:
        try:
            device.set_srq_mask(4)
            report.check(False, "the GPIB-only SV command is refused on RS-232")
        except Exception:
            report.check(True, "the GPIB-only SV command is refused on RS-232")
        try:
            device.set_rs232_wait(0)
            report.check(True, "SW is accepted on RS-232")
        except Exception as exc:  # noqa: BLE001
            report.check(False, f"SW is accepted on RS-232 ({exc})")
    else:
        before = None
        try:
            device.set_srq_mask(4)
            before = device._query_int("SV")
            report.check(before == 4, f"SV was accepted on GPIB (read back {before})")
        except Exception as exc:  # noqa: BLE001
            report.check(False, f"SV was accepted on GPIB ({exc})")
        finally:
            if before is not None:
                try:
                    device.set_srq_mask(0)
                except Exception:  # noqa: BLE001
                    pass

        # The driver's own gating: these must not be sent, and it must be the driver refusing.
        for name, call in (("SW", lambda: device.set_rs232_wait(0)),
                           ("MI", lambda: device.set_front_panel_mode("Remote"))):
            try:
                call()
                report.check(True, f"{name} was skipped on GPIB rather than sent")
            except Exception as exc:  # noqa: BLE001
                report.check(False, f"{name} handling on GPIB raised ({exc})")

        report.note(
            "OPTIONAL and not attempted here: SV 4, run a scan, then read the status byte with "
            "self.port.port.read_stb() to confirm a real SRQ. That reaches past the pysweepme "
            "port abstraction to the VISA session, so it is left to a human."
        )


def _tier1_coverage_note(device, report) -> None:
    report.section("what tier 1 cannot reach")
    report.note(
        "Counter B is untestable here. Counter A can count the internal 10 MHz timebase, but "
        "counter B accepts only INPUT 1 or INPUT 2 (manual, CI), so with no cable there is no "
        "known pulse train to give it. That asymmetry is the entire reason tier 2 exists: one "
        "BNC from the A DISC output to SIGNAL INPUT 2 turns the timebase into a signal that "
        "counters B and T can see."
    )
    report.note(
        "Also unreachable without instruments: absolute PORT output voltage (no ADC in the "
        "SR400 -- PL readback proves only the register), gate timing to nanosecond accuracy, "
        "signal-input linearity and offset, and real photon-counting behaviour."
    )


# ==========================================================================
#  TIER 2 -- one core cable, two optional
# ==========================================================================

CABLE_1 = "the A DISC output to SIGNAL INPUT 2"
CABLE_2 = "the PORT1 output to the INHIBIT input"
CABLE_3 = "the DWELL output to the TRIGGER input"


def run_tier2(device) -> tuple[Report, str]:
    """Everything that needs a known pulse train, i.e. a loopback cable."""
    report = Report(device, "self-test tier 2 loopback")
    saved = _save_settings(device, SAVED_SETTINGS + PORT_SETTINGS)

    try:
        if not _tier2_probe_cable1(device, report):
            return report, report.write(_timestamp())

        _tier2_counter_b(device, report)
        _tier2_discriminators(device, report)
        _tier2_arithmetic_modes(device, report)
        _tier2_b_preset_mode(device, report)

        has_inhibit = _tier2_probe_cable2(device, report)
        if has_inhibit:
            _tier2_inhibit(device, report)

        has_trigger = _tier2_probe_cable3(device, report)
        if has_trigger:
            _tier2_trigger(device, report)
            _tier2_gate_width_calibration(device, report)

        _tier2_coverage_note(device, report)
    finally:
        device.reset_counters()
        failed = _restore_settings(device, SAVED_SETTINGS + PORT_SETTINGS, saved)
        report.section("restore")
        report.check(
            not failed,
            f"every changed setting was restored, PORT levels included (unrestored: {failed or 'none'})",
        )
        report.note("No storage slot was used; ST, RC and SE were never sent.")


    return report, report.write(_timestamp())


def _looped_setup(device, count_time: float) -> None:
    """Counter A on the timebase, counter B on INPUT 2 which is fed by the DISC output.

    The A DISC output emits one NIM pulse per count A registers, including when A is counting
    the internal 10 MHz -- so this cable hands counters B and T an exact, known pulse train.
    The discriminator is set to FALL at -100 mV: the DISC pulse is about -0.7 V, and the manual
    warns that thresholds near 10 mV can pick up the DISC output itself and oscillate.
    """
    device.reset_counters()
    device.port.write("CM 0")
    device.port.write("CI 0,0")        # A on 10 MHz
    device.port.write("CI 1,2")        # B on INPUT 2
    device.port.write("CI 2,0")        # T on 10 MHz
    device.port.write("DM 1,0")        # B discriminator FIXED
    device.port.write("DS 1,1")        # FALL
    device.port.write("DL 1,-0.1000")  # -100 mV
    device.port.write("GM 0,0")
    device.port.write("GM 1,0")
    device.port.write("NP 1")
    device.port.write("NE 0")
    device.port.write("DT 0")
    device.set_count_time(count_time)


def _count_both(device, timeout: float = 10.0) -> tuple[int, int]:
    device.reset_counters()
    device.get_status_byte()
    device.start_counting()
    device._wait_for_status(device.STATUS_DATA_READY | device.STATUS_SCAN_FINISHED, timeout)
    return device.get_scan_point("A", 1), device.get_scan_point("B", 1)


def _tier2_probe_cable1(device, report) -> bool:
    """Probe for the core cable rather than asking. A count of zero is a reliable answer."""
    report.section(f"probing for cable 1 -- {CABLE_1}")
    _looped_setup(device, 1e-3)
    counts_a, counts_b = _count_both(device)
    report.note(f"counter A (10 MHz, 1 ms) = {counts_a}, counter B (INPUT 2) = {counts_b}")

    if counts_b < counts_a // 10:
        report.check(False, f"cable 1 is present (counter B saw {counts_b} of {counts_a})")
        report.note(
            f"STOPPED, and nothing else was changed. Connect {CABLE_1} with a BNC cable and "
            f"click the action again. The DISC output is NIM into 50 ohm and the signal inputs "
            f"are internally 50 ohm terminated, so no terminator or attenuator is needed."
        )
        device.message_box(
            f"SR400 self-test tier 2: no signal on INPUT 2, so the loopback cable is not "
            f"connected. Join {CABLE_1} and click 'run_self_test_loopback' again.\n\n"
            f"Nothing was changed. Counter B saw {counts_b} counts where about {counts_a} were "
            f"expected.",
        )
        return False

    report.check(True, f"cable 1 is present (counter B saw {counts_b} of {counts_a})")
    return True


def _tier2_counter_b(device, report) -> None:
    """Counter B against an exact reference, which tier 1 cannot do at all."""
    report.section("counter B against the looped-back timebase")
    for count_time, expected in ((1e-3, 10_000), (1e-2, 100_000)):
        _looped_setup(device, count_time)
        counts_a, counts_b = _count_both(device)
        error = abs(counts_b - expected) / expected
        report.check(
            error < 0.01,
            f"{count_time * 1e3:g} ms: counter B read {counts_b}, expected {expected} "
            f"({error:.3%} off); counter A read {counts_a}",
        )

    report.note(
        "A small deficit is expected and is not a fault: the DISC output has finite rise time "
        "and the input discriminator has its own pulse-pair resolution (5 ns, manual p. 5), so "
        "at 10 MHz the loop is near the edge of what it can resolve."
    )


def _tier2_discriminators(device, report) -> None:
    """Slope and threshold, against a pulse of known polarity and amplitude."""
    report.section("B discriminator -- slope and threshold against a known -0.7 V pulse")

    _looped_setup(device, 1e-3)
    _, baseline = _count_both(device)
    report.check(baseline > 0, f"FALL at -100 mV counts the negative DISC pulse ({baseline})")

    device.port.write("DS 1,0")  # RISE: wrong polarity for a negative pulse
    _, wrong_slope = _count_both(device)
    report.check(
        wrong_slope < baseline // 10,
        f"RISE on a negative pulse counts far less ({wrong_slope} against {baseline})",
    )

    device.port.write("DS 1,1")
    device.port.write("DL 1,-0.3000")  # below the -0.7 V pulse amplitude: still fires
    _, deep = _count_both(device)
    report.check(deep > 0, f"FALL at -300 mV still counts a -0.7 V pulse ({deep})")

    device.port.write("DL 1,0.2000")  # a positive threshold: the pulse never crosses upward
    _, positive = _count_both(device)
    report.check(
        positive < baseline // 10 or positive > 0,
        f"a +200 mV threshold on a negative pulse gives {positive} "
        f"(recorded rather than asserted: behaviour at the wrong-side threshold is not specified)",
    )

    device.port.write("DL 1,-0.1000")
    device.port.write("DS 1,1")


def _tier2_arithmetic_modes(device, report) -> None:
    """A-B and A+B, where both counters see the same train so the answers are forced."""
    report.section("counting modes A-B and A+B -- both counters on the same pulse train")

    _looped_setup(device, 1e-3)
    _, reference = _count_both(device)

    device.port.write("CM 1")  # A-B for T preset
    device.reset_counters()
    device.get_status_byte()
    device.start_counting()
    device._wait_for_status(device.STATUS_DATA_READY | device.STATUS_SCAN_FINISHED, 10.0)
    difference = device.get_scan_point("A", 1)
    report.check(
        abs(difference) <= max(100, reference // 100),
        f"A-B is near zero when both count the same train ({difference}, reference {reference})",
    )

    device.port.write("CM 2")  # A+B for T preset
    device.reset_counters()
    device.get_status_byte()
    device.start_counting()
    device._wait_for_status(device.STATUS_DATA_READY | device.STATUS_SCAN_FINISHED, 10.0)
    total = device.get_scan_point("A", 1)
    report.check(
        abs(total - 2 * reference) <= max(200, reference // 50),
        f"A+B is near twice one counter ({total}, expected about {2 * reference})",
    )

    device.port.write("CM 0")


def _tier2_b_preset_mode(device, report) -> None:
    """'A for B preset': B is the preset counter, so QB returns -1 by design (manual p. 45)."""
    report.section("counting mode 'A for B preset' -- the documented -1 from QB")

    _looped_setup(device, 1e-3)
    device.port.write("CM 3")
    device.port.write("CP 1,1E4")   # B preset: 10000 looped-back pulses = 1 ms of counting
    device.reset_counters()
    device.get_status_byte()
    device.start_counting()
    device._wait_for_status(device.STATUS_DATA_READY | device.STATUS_SCAN_FINISHED, 15.0)

    counts_a = device.get_scan_point("A", 1)
    report.check(
        abs(counts_a - 10_000) < 2_000,
        f"counter A read {counts_a} while B counted to its 1E4 preset (expected about 10000)",
    )

    raw = device._query("QB 1")
    report.check(
        raw.strip().startswith("-1"),
        f"QB returns -1 when counter B is the preset counter (raw {raw!r})",
    )
    report.note(
        "This is the behaviour the driver reports as NaN, and the one an earlier draft treated "
        "as an error -- which made this whole counting mode unusable. Confirmed on hardware."
    )
    device.port.write("CM 0")


def _tier2_probe_cable2(device, report) -> bool:
    """PORT1 to INHIBIT. Probe by driving it and seeing whether counting actually stops."""
    report.section(f"probing for cable 2 -- {CABLE_2}")
    _looped_setup(device, 1e-3)

    device.port.write("PM 1,0")      # PORT1 FIXED
    device.port.write("PL 1,5.000")  # +5 V. Never the +-10 V range into a TTL input.
    counts_a, _ = _count_both(device)
    report.note(f"with PORT1 at +5 V, counter A read {counts_a}")

    device.port.write("PL 1,0.000")
    if counts_a > 1000:
        report.note(
            f"cable 2 is absent or the INHIBIT input ignored it; skipping the inhibit test. "
            f"To include it, join {CABLE_2}."
        )
        return False

    report.check(True, "cable 2 is present: +5 V on PORT1 stopped the counters")
    return True


def _tier2_inhibit(device, report) -> None:
    """The only check that proves the D/A makes real voltage, not just a register value."""
    report.section("INHIBIT driven by PORT1 -- proves the D/A produces actual voltage")

    _looped_setup(device, 1e-3)
    device.port.write("PM 1,0")

    device.port.write("PL 1,0.000")
    running, _ = _count_both(device)
    report.check(running > 1000, f"PORT1 at 0 V lets counting proceed ({running})")

    device.port.write("PL 1,5.000")
    inhibited, _ = _count_both(device)
    report.check(inhibited < running // 10, f"PORT1 at +5 V inhibits counting ({inhibited})")

    device.port.write("PL 1,0.000")
    report.note(
        "The SR400 has no ADC, so PL readback only proves the register was written. This is "
        "the one test that shows the analog output actually swings. It does NOT measure the "
        "voltage: absolute D/A accuracy still needs a DVM."
    )


def _tier2_probe_cable3(device, report) -> bool:
    """DWELL to TRIGGER. Probe by presetting T on TRIG and seeing whether it ever finishes."""
    report.section(f"probing for cable 3 -- {CABLE_3}")

    device.reset_counters()
    device.port.write("CM 0")
    device.port.write("CI 0,0")
    device.port.write("CI 2,3")     # counter T on TRIG
    device.port.write("TS 0")       # rising edge; the DWELL output is TTL
    device.port.write("TL 1.500")   # about +1.5 V, mid-TTL
    device.port.write("GM 0,0")
    device.port.write("NP 1")
    device.port.write("NE 0")
    device.port.write("DT 2E-3")
    device.port.write("CP 2,1E1")   # 10 triggers

    device.get_status_byte()
    device.start_counting()
    try:
        device._wait_for_status(
            device.STATUS_DATA_READY | device.STATUS_SCAN_FINISHED,
            TRIGGER_PROBE_TIMEOUT,
        )
    except Exception:  # noqa: BLE001 -- a timeout here just means no trigger arrived
        device.pause_counting()
        report.note(
            f"no triggers arrived within {TRIGGER_PROBE_TIMEOUT:g} s, so cable 3 is absent; "
            f"skipping the trigger and "
            f"gate-width tests. To include them, join {CABLE_3}."
        )
        return False

    report.check(True, "cable 3 is present: the DWELL output is triggering the SR400")
    return True


def _tier2_trigger(device, report) -> None:
    report.section("trigger discriminator and the secondary status byte")
    try:
        triggered = device.get_secondary_status_bit(0)
        report.check(
            triggered in (0, 1),
            f"secondary status bit 0 (triggered) reads {triggered}",
        )
    except Exception as exc:  # noqa: BLE001
        report.check(False, f"the secondary status byte could be read ({exc})")


def _tier2_gate_width_calibration(device, report) -> None:
    """Measure the gate generator against the crystal.

    With a real trigger and the timebase looped into INPUT 2, counting the loop through a gate
    of width W for N gates gives about 1e7 * N * W counts -- so counts / (1e7 * N) is the
    effective gate width. That is the gate generator measured against the crystal, which is the
    closest thing to a scope this instrument can do to itself.
    """
    report.section("gate width calibration -- measured width against requested")

    device.reset_counters()
    device.port.write("CM 0")
    device.port.write("CI 0,2")     # counter A on INPUT 2: the looped-back 10 MHz
    device.port.write("CI 2,3")     # counter T on TRIG: preset counts gates
    device.port.write("DM 0,0")
    device.port.write("DS 0,1")
    device.port.write("DL 0,-0.1000")
    device.port.write("TS 0")
    device.port.write("TL 1.500")
    device.port.write("GM 0,1")     # gate A FIXED
    device.port.write("GD 0,0")
    device.port.write("NP 1")
    device.port.write("NE 0")
    device.port.write("DT 2E-3")

    gates = 100
    device.port.write(f"CP 2,{gates}")

    rows = []
    # Widths chosen to straddle the resolution bands of gotcha 4.
    for requested in (1e-6, 2e-6, 5e-6, 1e-5, 2e-5, 5e-5, 1e-4):
        try:
            device.set_gate_width("A", requested)
            applied = device._query_float("GW 0")
            device.reset_counters()
            device.get_status_byte()
            device.start_counting()
            device._wait_for_status(
                device.STATUS_DATA_READY | device.STATUS_SCAN_FINISHED,
                20.0,
            )
            counts = device.get_scan_point("A", 1)
            measured = counts / (1e7 * gates)
            rows.append(
                (
                    f"{requested:.3g}",
                    f"applied {applied:.6g}  measured {measured:.6g}  "
                    f"({(measured / requested - 1) * 100:+.1f}% of requested, {counts} counts)",
                ),
            )
        except Exception as exc:  # noqa: BLE001
            rows.append((f"{requested:.3g}", f"<failed: {exc}>"))

    report.table(rows, ("requested width", "result"))
    measured_any = sum(1 for _, value in rows if not value.startswith("<failed"))
    report.check(measured_any > 0, f"gate widths were measured ({measured_any}/{len(rows)})")
    report.note(
        "Compare 'applied' against 'requested' to see the resolution bands of gotcha 4, and "
        "'measured' against 'applied' to see the gate generator's real accuracy. A systematic "
        "deficit at short widths is expected: the gate edges are not infinitely sharp and one "
        "clock edge in ten at 100 ns is a 10% effect."
    )
    device.port.write("GM 0,0")


def _tier2_coverage_note(device, report) -> None:
    report.section("what neither tier verifies")
    report.note("Absolute PORT output voltage -- needs a DVM. Tier 2 shows only that it swings.")
    report.note("Gate timing to nanosecond accuracy -- needs an oscilloscope.")
    report.note("Signal-input linearity, offset and bandwidth -- needs a calibrated source.")
    report.note(
        "Real photon-counting behaviour: PMT pulse-height distribution, dark counts, dead-time "
        "losses and afterpulsing. A discriminator plateau on a real PMT is the only test for "
        "that, and it is an experiment rather than a self-test."
    )


# ==========================================================================
#  Discriminator threshold scans -- for the R8486 bare tube on SIGNAL INPUT 1
# ==========================================================================
#
# A threshold scan measures the INTEGRAL pulse-height distribution: the count rate above each
# discriminator level. Read from low to high |level| it shows three things in order -- a steep
# noise edge, a valley, and the single-photoelectron shoulder -- and the operating threshold
# belongs between the first and the third.
#
# Two actions, because the two halves of that answer need different light:
#
#   dark   -- PMT covered. Finds the noise edge, i.e. the LOWEST usable level, and where dark
#             counts vanish. Vanishing dark counts are tempting and wrong: a level that kills
#             every dark count is above most single-photoelectron pulses too, so it throws signal
#             away. The light scan is what proves that, by measuring the loss at that level.
#   light  -- gentle, steady light. Finds where the counts start falling because the threshold
#             is cutting into real single-PE pulses, i.e. the HIGHEST usable level. Swept up and
#             down, several times: up-versus-down disagreement is hysteresis, pass-to-pass
#             disagreement is drift, and the two have different signatures so they are estimated
#             separately rather than lumped together.
#
# Bench numbers for this tube (pmt-gain-noise-budget inventory, unit test sheet): gain 5.1e6 at
# 1000 V, anode dark current 0.07 nA, mean single-PE amplitude ~10 mV into 50 ohm, valley
# threshold ~3 mV. Measured dark rate ~8 cps at 1000 V at the lab's hand-tuned threshold; the
# 0.07 nA / (5.1e6 * 1.602e-19 C) ~ 86 cps implied by dark current is only an upper bound, since
# not all dark current arrives as countable pulses. The manual
# (p. 22) warns that below 10 mV the 0.7 V DISC output pulses can be picked up by the signal
# cables and make the discriminators oscillate -- squarely in this tube's valley region.

import math as _math

SCAN_COUNTER = "A"   # counter A, so discriminator A (manual: each counter has its own)
SCAN_INPUT = "1"     # CI 0,1 -- SIGNAL INPUT 1
SCAN_SLOPE = "Fall"  # a bare PMT anode pulse is negative

DARK_TARGET_COUNTS = 200      # ~7 % Poisson per threshold
DARK_MAX_SECONDS = 30.0       # per threshold: 200 counts at the measured ~8 cps is 25 s
DARK_STOP_AFTER_ZEROS = 3     # consecutive zero-count thresholds: past the distribution, stop
LIGHT_TARGET_COUNTS = 10_000  # 1 % Poisson per threshold per pass
LIGHT_MAX_SECONDS = 5.0
LIGHT_REPEATS = 3             # each repeat is one up pass and one down pass
LIGHT_GRID_CUTOFF = 0.02      # first pass stops once the rate falls below 2 % of the probe
MIN_PERIOD_SECONDS = 0.01
MAX_PERIOD_SECONDS = 10.0     # one count period; longer points are accumulated

DARK_RATE_CEILING_CPS = 500.0   # ~60x the measured ~8 cps at 1000 V; above it the tube is not dark
OSCILLATION_RATE_CPS = 1e6      # no covered PMT does this; it is noise, pickup or oscillation
LIGHT_FLOOR_CPS = 2000.0        # below this there is no usable light on the tube
LIGHT_WARN_CPS = 2e5            # 0.1 % loss at the SR400's 5 ns pulse-pair resolution
LIGHT_CEILING_CPS = 1e6         # 0.5 % loss, and threshold-dependent: would bend the curve

NOISE_SLOPE_PER_MV = 0.5        # log-slope below which the curve has stopped being noise
SLOPE_WINDOW_V = 0.001          # slope over 1 mV, not one 0.2 mV step: Poisson noise
DIFF_WINDOW_V = 0.0005          # half-width of the differential stencil
VALLEY_PV_RATIO = 1.2           # single-PE peak must stand this far above the valley
DRIFT_TOLERANCE = 0.02          # pass-to-pass scale change worth flagging
HYSTERESIS_RESOLUTION_V = 0.0002  # the discriminator's own 0.2 mV step
PICKUP_SAFE_V = 0.010           # manual p. 22
LOSS_LEVELS = (0.01, 0.02, 0.05, 0.10)
FOM_MIN_DARK_COUNTS = 20        # below this sqrt(B) is too uncertain to divide by (> 11 %)
FOM_BAND = 0.95                 # levels within 5 % of the best S/sqrt(B) are reported as a band

PROMPT_DARK = (
    "SR400 threshold scan, DARK.\n\n"
    "1. Cover the R8486 and make sure NO light can reach it.\n"
    "2. PMT high voltage on, at its operating value, and settled for a few minutes.\n"
    "3. PMT anode on SIGNAL INPUT 1, 50 ohm, no attenuator.\n"
    "4. Remove any loopback cable. Route the INPUT 1 cable away from the DISC output cables: "
    "below 10 mV their pulses can be picked up and make the discriminator oscillate (manual "
    "p. 22).\n\n"
    "Never expose the PMT to room light with the high voltage on.\n\n"
    "Takes roughly 15-20 minutes: at ~8 dark counts/s each threshold needs up to 30 s for "
    "adequate statistics. Press OK to start."
)

PROMPT_LIGHT = (
    "SR400 threshold scan, LIGHT.\n\n"
    "1. Ensure gentle, STEADY light on the R8486 -- aim for roughly 1e4 to 1e5 counts/s. "
    "Keep it unchanged for the whole scan.\n"
    "2. Same high voltage and cabling as the dark scan (anode on SIGNAL INPUT 1).\n"
    "3. Run the dark scan first in this session if you want the report to show what the "
    "dark-optimised level would cost.\n\n"
    "Never expose the PMT to room light with the high voltage on. Too much light distorts the "
    "result and is refused.\n\n"
    "Press OK to start."
)


def threshold_grid() -> list:
    """|threshold| in volts: fine where the noise edge and valley live, coarser after.

    0.2 mV steps to 6 mV (the discriminator's own resolution, over this tube's ~3 mV valley),
    0.4 mV to 15.2 mV (through the ~10 mV single-PE mean), 2 mV to 40 mV (the tail). Every
    level is a multiple of 0.2 mV: anything else would be rounded by the instrument, and the
    table would then report a level the discriminator never applied.
    """
    levels = []
    for start, stop, step in ((0.0004, 0.0060, 0.0002),
                              (0.0064, 0.0152, 0.0004),
                              (0.0160, 0.0400, 0.0020)):
        count = int(round((stop - start) / step)) + 1
        levels.extend(round(start + i * step, 4) for i in range(count))
    return levels


def _rate_row(point: dict) -> dict:
    """Derived numbers for one measured point. Raw counts and live time stay alongside."""
    counts, live = point["counts"], point["live_s"]
    row = dict(point)
    row["rate"] = counts / live if live > 0 else float("nan")
    row["sigma"] = _math.sqrt(counts) / live if live > 0 else float("nan")
    # Zero counts is an upper limit, not a rate: 3/T is the 95 % Poisson bound.
    row["upper95"] = 3.0 / live if counts == 0 and live > 0 else None
    return row


def _value_at(rows: list, abs_v: float):
    """The row whose |level| is nearest abs_v."""
    return min(rows, key=lambda r: abs(r["abs_v"] - abs_v)) if rows else None


def _noise_edge(rows: list):
    """First |level| at which the curve stops falling like noise.

    Log-slope is taken across a 1 mV baseline rather than between neighbouring 0.2 mV points:
    at 200 counts a single step's slope carries ~0.7 /mV of Poisson noise, which would swamp a
    0.5 /mV threshold. Heuristic, labelled as such in the report, and refuses (returns None)
    rather than guessing when the curve never flattens.
    """
    slopes = []
    for i, row in enumerate(rows):
        if row["counts"] <= 0:
            slopes.append(None)
            continue
        far = next((r for r in rows[i + 1:]
                    if r["abs_v"] >= row["abs_v"] + SLOPE_WINDOW_V - 1e-9 and r["counts"] > 0),
                   None)
        if far is None:
            slopes.append(None)
            continue
        span_mv = (far["abs_v"] - row["abs_v"]) * 1e3
        slopes.append(_math.log(row["rate"] / far["rate"]) / span_mv)

    for i in range(len(slopes) - 1):
        a, b = slopes[i], slopes[i + 1]
        if a is not None and b is not None and a < NOISE_SLOPE_PER_MV and b < NOISE_SLOPE_PER_MV:
            return rows[i]["abs_v"], slopes
    return None, slopes


def analyse_dark(points: list) -> dict:
    """Pure analysis of a covered-PMT scan. Returns findings; never raises on thin data."""
    rows = sorted((_rate_row(p) for p in points), key=lambda r: r["abs_v"])
    result = {"rows": rows, "valid": True, "reasons": [], "noise_edge_v": None,
              "vanish_v": None, "oscillating_below_v": None, "lower_bound_v": None}
    if not rows:
        result["valid"] = False
        result["reasons"].append("no thresholds were measured")
        return result

    if rows[0]["counts"] == 0:
        result["valid"] = False
        result["reasons"].append(
            "no counts at all, even at the lowest threshold where electronic noise alone "
            "should register: nothing is reaching SIGNAL INPUT 1. Check the PMT cable, the "
            "high voltage, and that the anode is on INPUT 1",
        )
        return result

    near_10 = _value_at(rows, PICKUP_SAFE_V)
    if near_10 and near_10["abs_v"] >= PICKUP_SAFE_V - 1e-9 and near_10["rate"] > DARK_RATE_CEILING_CPS:
        result["valid"] = False
        result["reasons"].append(
            f"{near_10['rate']:.4g} cps at {near_10['abs_v'] * 1e3:.1f} mV, where a covered "
            f"R8486 gives ~8 cps (measured at 1000 V). Light is "
            f"reaching the tube: check the cover, or the HV is far above its test-sheet value",
        )

    noisy = [r for r in rows if r["rate"] > OSCILLATION_RATE_CPS]
    if noisy:
        result["oscillating_below_v"] = max(r["abs_v"] for r in noisy)

    edge, slopes = _noise_edge(rows)
    for row, slope in zip(rows, slopes):
        row["log_slope_per_mv"] = slope
    result["noise_edge_v"] = edge
    if edge is None:
        result["reasons"].append(
            "the curve never flattens: noise and single-PE pulses are not separated at any "
            "scanned level. That is the evidence for the Stage 2 preamp",
        )
    else:
        # A margin of 0.5 mV, rounded up to the discriminator's 0.2 mV step.
        result["lower_bound_v"] = _math.ceil((edge + 0.0005) / 0.0002 - 1e-9) * 0.0002

    # Dark counts vanish where every threshold from here up reads zero.
    for i, row in enumerate(rows):
        if row["counts"] == 0 and all(r["counts"] == 0 for r in rows[i:]):
            result["vanish_v"] = row["abs_v"]
            break

    return result


def _least_squares(design: list, y: list):
    """Ordinary least squares by the normal equations. None if the system is singular.

    Three unknowns at most, so Gaussian elimination by hand rather than a numpy dependency
    the SweepMe! environment may not have.
    """
    n = len(design[0])
    ata = [[sum(row[i] * row[j] for row in design) for j in range(n)] for i in range(n)]
    aty = [sum(row[i] * value for row, value in zip(design, y)) for i in range(n)]
    for col in range(n):
        pivot = max(range(col, n), key=lambda r: abs(ata[r][col]))
        if abs(ata[pivot][col]) < 1e-12:
            return None
        ata[col], ata[pivot] = ata[pivot], ata[col]
        aty[col], aty[pivot] = aty[pivot], aty[col]
        for r in range(n):
            if r != col:
                k = ata[r][col] / ata[col][col]
                ata[r] = [x - k * yv for x, yv in zip(ata[r], ata[col])]
                aty[r] -= k * aty[col]
    return [aty[i] / ata[i][i] for i in range(n)]


def _differential(rows: list) -> list:
    """-dR/dV in cps/mV by a centred stencil of +-0.5 mV: the pulse-height density."""
    out = []
    for row in rows:
        lo = _value_at(rows, row["abs_v"] - DIFF_WINDOW_V)
        hi = _value_at(rows, row["abs_v"] + DIFF_WINDOW_V)
        span_mv = (hi["abs_v"] - lo["abs_v"]) * 1e3
        out.append((lo["rate"] - hi["rate"]) / span_mv if span_mv > 0 else float("nan"))
    return out


def _crossing(rows: list, values: list, target: float, start_v: float):
    """First |level| >= start_v where values falls to target, linearly interpolated."""
    previous = None
    for row, value in zip(rows, values):
        if row["abs_v"] < start_v - 1e-12:
            continue
        if previous is not None and value <= target < previous[1]:
            v0, y0 = previous
            return v0 + (row["abs_v"] - v0) * (y0 - target) / (y0 - value)
        if value <= target and previous is None:
            return row["abs_v"]
        previous = (row["abs_v"], value)
    return None


def analyse_light(passes: list, dark: dict | None = None) -> dict:
    """Pure analysis of repeated up/down light scans.

    passes: [{"direction": "up"|"down", "repeat": k, "points": [...]}, ...] in time order.
    """
    result = {"valid": True, "reasons": [], "rows": [], "valley_v": None, "peak_v": None,
              "pv_ratio": None, "plateau_rate": None, "reference_v": None, "loss_v": {},
              "pass_factors": [], "drift": None, "drift_flagged": False,
              "hysteresis_v": None, "hysteresis_se_v": None, "hysteresis_flagged": False,
              "recommended_v": None, "recommended_basis": "", "recommended_loss": None,
              "window_v": None, "window_empty": False, "dark_vanish_loss": None,
              "noise_edge_v": None, "fom": [], "optimum_v": None, "optimum_band_v": None}
    if not passes:
        result["valid"] = False
        result["reasons"].append("no passes were measured")
        return result

    by_pass = [{round(p["abs_v"], 5): p for p in ps["points"]} for ps in passes]
    common = sorted(set.intersection(*(set(d) for d in by_pass)))
    if len(common) < 5:
        result["valid"] = False
        result["reasons"].append("too few thresholds were common to every pass")
        return result

    rows = []
    for v in common:
        counts = sum(d[v]["counts"] for d in by_pass)
        live = sum(d[v]["live_s"] for d in by_pass)
        rows.append(_rate_row({"abs_v": v, "level_v": -v, "counts": counts, "live_s": live}))
    result["rows"] = rows

    edge, _ = _noise_edge(rows)
    dark_edge = dark.get("noise_edge_v") if dark else None
    result["noise_edge_v"] = dark_edge if dark_edge is not None else edge

    diff = _differential(rows)
    for row, d in zip(rows, diff):
        row["density"] = d

    # Valley. The first local minimum of the density only proves a valley exists: on a flat
    # bottom, ties and the +-0.5 mV stencil stop it early. The valley itself is the lowest
    # density between that minimum and the single-PE peak.
    for i in range(1, len(rows) - 1):
        if diff[i] <= diff[i - 1] and diff[i] <= diff[i + 1] and diff[i] > 0:
            later = diff[i + 1:]
            peak = max(later)
            peak_index = i + 1 + later.index(peak)
            j = min(range(i, peak_index), key=lambda k: diff[k])
            if peak >= VALLEY_PV_RATIO * diff[j]:
                result["valley_v"] = rows[j]["abs_v"]
                result["peak_v"] = rows[peak_index]["abs_v"]
                result["pv_ratio"] = peak / diff[j]
                break

    reference = result["valley_v"]
    if reference is None:
        reference = result["noise_edge_v"]
        result["reasons"].append(
            "no resolved valley between the noise and the single-PE peak: the single-PE "
            "distribution is not separated from noise at this gain. That is the evidence for "
            "the Stage 2 preamp" if reference is not None else
            "neither a valley nor a noise edge was found, so there is no reference level",
        )
    if reference is None:
        result["valid"] = False
        return result

    result["reference_v"] = reference
    plateau = _value_at(rows, reference)["rate"]
    result["plateau_rate"] = plateau
    if plateau < LIGHT_FLOOR_CPS:
        result["valid"] = False
        result["reasons"].append(
            f"{plateau:.4g} cps at the reference level: too little light to locate a knee",
        )

    fractions = [r["rate"] / plateau for r in rows]
    for loss in LOSS_LEVELS:
        result["loss_v"][loss] = _crossing(rows, fractions, 1.0 - loss, reference)

    # --- drift and hysteresis, separated by their signatures ------------------------------
    # Each pass gets a light-level factor from the near-flat region. That region is not truly
    # flat, so a hysteresis shift leaks into it as an up/down offset -- and normalising passes
    # by those raw factors would cancel about half the hysteresis signal, and could pass large
    # hysteresis off as drift. The two have different signatures: drift follows TIME,
    # hysteresis follows sweep DIRECTION. So the factors are fitted as
    #     f = c + a * (t - t_mean) + eta * direction
    # and only the time term is divided out. Drift is a * (scan span) / c; what is left after
    # the fit is unsteadiness the linear model cannot explain.
    flat_hi = result["loss_v"].get(0.02) or (reference + 0.002)
    flat = [v for v in common if reference - 1e-12 <= v <= flat_hi + 1e-12]
    merged = {r["abs_v"]: r["rate"] for r in rows}
    factors = []
    for ps, d in zip(passes, by_pass):
        expected = sum(merged[v] * d[v]["live_s"] for v in flat)
        observed = sum(d[v]["counts"] for v in flat)
        times = [d[v]["t"] for v in flat if "t" in d[v]]
        factors.append({
            "direction": ps["direction"], "repeat": ps["repeat"],
            "factor": observed / expected if expected > 0 else float("nan"),
            "sigma": 1.0 / _math.sqrt(observed) if observed > 0 else float("inf"),
            "t": sum(times) / len(times) if times else float(len(factors)),
        })
    result["pass_factors"] = factors

    usable = [f for f in factors if _math.isfinite(f["factor"])]
    drift_only = [1.0] * len(factors)
    if len(usable) >= 3:
        t_mean = sum(f["t"] for f in usable) / len(usable)
        rows_x = [(1.0, f["t"] - t_mean, 1.0 if f["direction"] == "up" else -1.0) for f in usable]
        coeffs = _least_squares(rows_x, [f["factor"] for f in usable])
        if coeffs is not None:
            c, a, eta = coeffs
            span = max(f["t"] for f in usable) - min(f["t"] for f in usable)
            drift = abs(a) * span / c if c > 0 else float("nan")
            residual = max(abs(f["factor"] - (c + a * (f["t"] - t_mean)
                                              + eta * (1.0 if f["direction"] == "up" else -1.0))) / c
                           for f in usable)
            noise = max(f["sigma"] for f in usable)
            result["drift"] = drift
            result["unsteadiness"] = residual
            result["direction_offset"] = eta / c if c > 0 else None
            result["drift_flagged"] = (drift > max(DRIFT_TOLERANCE, 3.0 * noise)
                                       or residual > max(DRIFT_TOLERANCE, 3.0 * noise))
            drift_only = [(c + a * (f["t"] - t_mean)) / c for f in factors]
            if result["drift_flagged"]:
                result["reasons"].append(
                    f"the light level changed between passes -- {drift:.1%} trend over the scan, "
                    f"{residual:.1%} unexplained by a linear trend -- against a "
                    f"{DRIFT_TOLERANCE:.0%} tolerance: the knee position is not trustworthy. "
                    f"Steady the source and repeat",
                )

    # --- hysteresis: a SIDEWAYS shift between up and down curves, on the steep shoulder ----
    lo = result["loss_v"].get(0.05)
    shoulder = [r for r, f in zip(rows, fractions)
                if lo is not None and r["abs_v"] >= lo and 0.40 <= f <= 0.95 and r["density"] > 0]
    shifts = []
    for k in sorted({ps["repeat"] for ps in passes}):
        up = next((i for i, ps in enumerate(passes) if ps["repeat"] == k and ps["direction"] == "up"), None)
        down = next((i for i, ps in enumerate(passes) if ps["repeat"] == k and ps["direction"] == "down"), None)
        if up is None or down is None:
            continue
        for r in shoulder:
            pu, pd = by_pass[up][r["abs_v"]], by_pass[down][r["abs_v"]]
            ru = pu["counts"] / pu["live_s"] / drift_only[up]
            rd = pd["counts"] / pd["live_s"] / drift_only[down]
            # R_up - R_down ~ density * shift, with density in cps/mV.
            shifts.append((ru - rd) / r["density"] * 1e-3)
    if len(shifts) >= 2:
        mean = sum(shifts) / len(shifts)
        var = sum((x - mean) ** 2 for x in shifts) / (len(shifts) - 1)
        se = _math.sqrt(var / len(shifts))
        result["hysteresis_v"] = mean
        result["hysteresis_se_v"] = se
        result["hysteresis_flagged"] = (abs(mean) > 3.0 * se
                                        and abs(mean) > HYSTERESIS_RESOLUTION_V)

    # --- what the dark-optimised level would cost --------------------------------------
    if dark and dark.get("vanish_v") is not None:
        at = _value_at(rows, dark["vanish_v"])
        if at is not None and abs(at["abs_v"] - dark["vanish_v"]) < 0.0011:
            result["dark_vanish_loss"] = 1.0 - at["rate"] / plateau

    # --- background-limited optimum, when this session has a dark scan ----------------------
    # For a weak signal the counting SNR goes as S / sqrt(B). Raising the threshold strips
    # electronic noise much faster than it removes photons -- until the remaining dark counts
    # are themselves single-PE pulses. Those share the signal's amplitude distribution, so from
    # there S and B fall together and S / sqrt(B) only drops. The optimum is therefore just
    # above the noise edge and NOT where dark counts vanish; this computes it rather than
    # asserting it. Levels with too few dark counts are not scored: a near-zero background
    # estimate makes any SNR look enormous, which is exactly the trap being guarded against.
    if dark:
        dark_rows = {round(r["abs_v"], 5): r for r in dark["rows"]}
        for r in rows:
            d = dark_rows.get(round(r["abs_v"], 5))
            if d is None or d["counts"] < FOM_MIN_DARK_COUNTS:
                continue
            efficiency = max(r["rate"] - d["rate"], 0.0) / plateau
            result["fom"].append({"abs_v": r["abs_v"], "efficiency": efficiency,
                                  "dark_rate": d["rate"], "dark_counts": d["counts"],
                                  "fom": efficiency / _math.sqrt(d["rate"])})
        if result["fom"]:
            best = max(result["fom"], key=lambda f: f["fom"])
            for f in result["fom"]:
                f["relative"] = f["fom"] / best["fom"]
            result["optimum_v"] = best["abs_v"]
            band = [f["abs_v"] for f in result["fom"] if f["relative"] >= FOM_BAND]
            result["optimum_band_v"] = (min(band), max(band))

    # --- recommendation --------------------------------------------------------------------
    upper = result["loss_v"].get(0.01)
    lower = result["noise_edge_v"]
    if lower is not None and upper is not None:
        result["window_v"] = (lower, upper)
        if lower > upper:
            # Informational, not a refusal: it is the expected state for this tube unamplified.
            result["window_empty"] = True
            result["reasons"].append(
                f"no level is both above the noise edge ({lower * 1e3:.1f} mV) and below 1 % "
                f"photon loss ({upper * 1e3:.1f} mV): at this gain the SR400 cannot fully "
                f"separate electronic noise from single-PE pulses. Expected for the R8486 at "
                f"1000 V without a preamp (bench inventory, Stage 2)",
            )

    if result["valid"] and not result["drift_flagged"]:
        if result["optimum_v"] is not None:
            result["recommended_v"] = result["optimum_v"]
            result["recommended_basis"] = (
                "background-limited optimum: the level maximising S/sqrt(B), from this "
                "session's dark and light scans together"
            )
        elif result["valley_v"] is not None:
            result["recommended_v"] = result["valley_v"]
            result["recommended_basis"] = (
                "valley of the pulse-height density. No dark scan this session, so noise was "
                "judged only against this light level -- run the dark scan for the optimum"
            )
        elif lower is not None:
            result["recommended_v"] = lower + 0.0005
            result["recommended_basis"] = "noise edge + 0.5 mV (no valley was resolved)"
        if result["recommended_v"] is not None:
            at = _value_at(rows, result["recommended_v"])
            result["recommended_loss"] = 1.0 - at["rate"] / plateau
    return result


# --------------------------------------------------------------------- acquisition

def _ceil_count_time(device, seconds: float) -> float:
    """Smallest settable count time >= seconds. CP keeps one significant digit (manual p. 39)."""
    cycles = max(seconds * device.CLOCK_FREQUENCY, 1.0)
    exponent = _math.floor(_math.log10(cycles))
    mantissa = _math.ceil(cycles / 10.0**exponent - 1e-9)
    if mantissa >= 10:
        mantissa, exponent = 1, exponent + 1
    return mantissa * 10.0**exponent / device.CLOCK_FREQUENCY


def _scan_setup(device) -> None:
    """Counter A on SIGNAL INPUT 1 through discriminator A, gates open, one period at a time."""
    _single_period_setup(device, MIN_PERIOD_SECONDS, source=SCAN_INPUT)
    device.set_discriminator_mode(SCAN_COUNTER, "Fixed")
    device.set_discriminator_slope(SCAN_COUNTER, SCAN_SLOPE)


def _measure_point(device, abs_v: float, target_counts: int, max_seconds: float) -> dict:
    """Count at one threshold until target_counts or max_seconds, whichever first.

    The next period is sized from the rate measured so far, so a noisy low threshold takes
    10 ms and a quiet high one takes up to max_seconds. Every period length is first rounded
    UP to a settable value and then read back, so the live time is what the instrument used.
    """
    level = -abs_v if SCAN_SLOPE == "Fall" else abs_v
    device.set_discriminator_level(SCAN_COUNTER, level)

    counts, live, period = 0, 0.0, MIN_PERIOD_SECONDS
    while True:
        period = min(_ceil_count_time(device, period), MAX_PERIOD_SECONDS)
        device.set_count_time(period)
        actual = device.get_counter_preset("T") / device.CLOCK_FREQUENCY
        counts += _count_one_period(device, timeout=actual + 10.0)
        live += actual
        if counts >= target_counts or live >= max_seconds - 1e-9:
            break
        remaining = max_seconds - live
        needed = (target_counts - counts) * live / counts if counts > 0 else period * 10.0
        period = max(MIN_PERIOD_SECONDS, min(needed * 1.1, remaining))

    return {"abs_v": abs_v, "level_v": level, "counts": counts, "live_s": live,
            "t": time.monotonic()}


def _scan_conditions_note(report) -> None:
    report.note(
        f"Counter {SCAN_COUNTER} on SIGNAL INPUT {SCAN_INPUT} through discriminator "
        f"{SCAN_COUNTER}, slope {SCAN_SLOPE.upper()}, gates CW, one count period at a time "
        f"(NP 1, EXTERNAL dwell). Count time adapts per threshold. Every count time is "
        f"rounded up to a settable value and read back, so 'live' is what the SR400 counted.",
    )


def _rows_table(report, rows: list, extra=None) -> None:
    table = []
    for r in rows:
        if r["counts"] == 0:
            rate = f"< {r['upper95']:.3g} cps (95 %)"
        else:
            rate = f"{r['rate']:.4g} +- {r['sigma']:.2g} cps"
        line = f"{r['counts']:>9d} counts in {r['live_s']:>8.3f} s   {rate}"
        if extra:
            line += extra(r)
        table.append((f"{r['abs_v'] * 1e3:6.1f} mV", line))
    report.table(table, ("|level|", "raw counts, live time, rate"))


def _mv(v) -> str:
    return "none" if v is None else f"{v * 1e3:.1f} mV"


# ------------------------------------------------------------------ dark action

def run_threshold_scan_dark(device) -> tuple:
    report = Report(device, "threshold scan dark")
    saved = _save_settings(device, SAVED_SETTINGS)
    points = []
    try:
        report.section("conditions -- covered R8486")
        _scan_conditions_note(report)
        report.note(
            f"Target {DARK_TARGET_COUNTS} counts per threshold (~"
            f"{100 / _math.sqrt(DARK_TARGET_COUNTS):.0f} % Poisson), at most "
            f"{DARK_MAX_SECONDS:g} s each. Stops after {DARK_STOP_AFTER_ZEROS} thresholds in a "
            f"row read zero at the maximum time.",
        )
        _scan_setup(device)

        report.section("scan, low to high |level|")
        zeros = 0
        leak_checked = False
        grid = threshold_grid()
        for index, abs_v in enumerate(grid):
            point = _measure_point(device, abs_v, DARK_TARGET_COUNTS, DARK_MAX_SECONDS)
            points.append(point)

            if index == 0 and point["counts"] == 0:
                break  # nothing on the input at all; analyse_dark says so

            if not leak_checked and abs_v >= PICKUP_SAFE_V - 1e-9:
                leak_checked = True
                if point["counts"] / point["live_s"] > DARK_RATE_CEILING_CPS:
                    report.note("STOPPED at 10 mV: far too many counts for a covered tube.")
                    break

            zero_at_max = point["counts"] == 0 and point["live_s"] >= DARK_MAX_SECONDS * 0.999
            zeros = zeros + 1 if zero_at_max else 0
            if zeros >= DARK_STOP_AFTER_ZEROS:
                report.note(f"stopped at {abs_v * 1e3:.1f} mV: {zeros} zero-count thresholds "
                            f"in a row, so the scan is past the dark distribution.")
                break
            if index % 10 == 9:
                device.message_info(f"SR400 dark scan: {index + 1}/{len(grid)} thresholds, "
                                    f"now at {abs_v * 1e3:.1f} mV")

        result = analyse_dark(points)
        _rows_table(report, result["rows"],
                    extra=lambda r: (f"   log-slope {r['log_slope_per_mv']:.2f}/mV"
                                     if r.get("log_slope_per_mv") is not None else ""))

        report.section("findings")
        report.check(result["valid"], "the scan is a valid covered-PMT measurement"
                     + ("" if result["valid"] else f": {'; '.join(result['reasons'])}"))
        if result["oscillating_below_v"] is not None:
            report.note(
                f"Above {OSCILLATION_RATE_CPS:.0e} cps up to {_mv(result['oscillating_below_v'])}: "
                f"that is electronic noise, DISC-output pickup or oscillation, not dark counts. "
                f"If it persists with the HV off, it is pickup -- rearrange the cables.",
            )
        report.note(f"noise edge (heuristic, log-slope < {NOISE_SLOPE_PER_MV}/mV over 1 mV): "
                    f"{_mv(result['noise_edge_v'])}")
        report.note(f"dark counts vanish (zero at {DARK_MAX_SECONDS:g} s) from: {_mv(result['vanish_v'])}")
        if result["lower_bound_v"] is not None:
            report.note(f"LOWER BOUND for the operating threshold: {_mv(result['lower_bound_v'])} "
                        f"(noise edge + 0.5 mV).")
            if result["lower_bound_v"] < PICKUP_SAFE_V:
                report.note("That is below 10 mV, where the manual warns of DISC pickup. This "
                            "scan shows whether it happened in THIS cabling; keep the cables "
                            "where they are.")
        for reason in result["reasons"]:
            report.note(reason)
        report.note(
            "Do NOT choose the level where dark counts vanish. It is above most single-PE "
            "pulses too, so it throws signal away. Run run_threshold_scan_light to measure "
            "how much: its report gives the loss at that level, and the upper bound.",
        )

        report.headline = (
            f"lower bound {_mv(result['lower_bound_v'])}, dark counts vanish from "
            f"{_mv(result['vanish_v'])}" if result["valid"] and result["lower_bound_v"] is not None
            else "no lower bound: " + ("; ".join(result["reasons"]) or "see the report")
        )
        if result["valid"]:
            device._dark_threshold_scan = result
    finally:
        device.reset_counters()
        failed = _restore_settings(device, SAVED_SETTINGS, saved)
        report.section("restore")
        report.check(not failed, f"every changed setting was restored (unrestored: {failed or 'none'})")
        report.note("No storage slot was used; ST, RC and SE were never sent.")

    return report, report.write(_timestamp())


# ----------------------------------------------------------------- light action

def run_threshold_scan_light(device) -> tuple:
    report = Report(device, "threshold scan light")
    saved = _save_settings(device, SAVED_SETTINGS)
    passes = []
    try:
        report.section("conditions -- gentle, steady light on the R8486")
        _scan_conditions_note(report)
        report.note(
            f"{LIGHT_REPEATS} repeats of an up pass then a down pass, target "
            f"{LIGHT_TARGET_COUNTS} counts per threshold per pass (~1 % Poisson). Up versus "
            f"down measures hysteresis; pass to pass measures drift.",
        )
        _scan_setup(device)

        # Probe before committing minutes to a scan the light level cannot support.
        report.section("probe")
        probe = _measure_point(device, 0.006, LIGHT_TARGET_COUNTS, LIGHT_MAX_SECONDS)
        probe_rate = probe["counts"] / probe["live_s"]
        dark = getattr(device, "_dark_threshold_scan", None)
        dark_at = _value_at(dark["rows"], 0.006)["rate"] if dark else None
        report.note(f"{probe['counts']} counts in {probe['live_s']:.3f} s at 6.0 mV = "
                    f"{probe_rate:.4g} cps" + (f" (dark scan: {dark_at:.4g} cps)" if dark_at else ""))
        floor = max(LIGHT_FLOOR_CPS, 20.0 * dark_at) if dark_at else LIGHT_FLOOR_CPS
        if probe_rate < floor:
            report.check(False, f"there is light on the PMT ({probe_rate:.4g} cps, need >= {floor:.4g})")
            report.headline = (f"no usable light: {probe_rate:.4g} cps at 6 mV. Ensure gentle "
                               f"light on the PMT and run it again")
            return report, report.write(_timestamp())
        if probe_rate > LIGHT_CEILING_CPS:
            report.check(False, f"the light is gentle ({probe_rate:.4g} cps, limit {LIGHT_CEILING_CPS:.0e})")
            report.headline = (f"too bright: {probe_rate:.4g} cps at 6 mV. Dead-time losses "
                               f"would bend the curve; reduce to 1e4-1e5 cps and run it again")
            return report, report.write(_timestamp())
        report.check(True, f"there is light, and it is gentle enough ({probe_rate:.4g} cps)")
        if probe_rate > LIGHT_WARN_CPS:
            report.note(f"Above {LIGHT_WARN_CPS:.0e} cps: dead-time loss is no longer negligible "
                        f"at the 1 % level this scan resolves. Dimmer is better.")

        grid = threshold_grid()
        for repeat in range(1, LIGHT_REPEATS + 1):
            for direction in ("up", "down"):
                report.section(f"repeat {repeat}, {direction}")
                levels = grid if direction == "up" else list(reversed(grid))
                points = []
                for abs_v in levels:
                    point = _measure_point(device, abs_v, LIGHT_TARGET_COUNTS, LIGHT_MAX_SECONDS)
                    points.append(point)
                    # The first pass also sets the grid: past 2 % of the probe there is nothing
                    # left that bears on the operating point, and every further pass would pay
                    # the full per-threshold maximum for it.
                    if repeat == 1 and direction == "up" and \
                            point["counts"] / point["live_s"] < LIGHT_GRID_CUTOFF * probe_rate:
                        grid = [v for v in grid if v <= abs_v + 1e-12]
                        break
                passes.append({"direction": direction, "repeat": repeat, "points": points})
                device.message_info(f"SR400 light scan: repeat {repeat} {direction} done "
                                    f"({len(points)} thresholds)")

        result = analyse_light(passes, dark)
        _rows_table(report, result["rows"],
                    extra=lambda r: f"   density {r['density']:.4g} cps/mV")

        report.section("findings")
        report.check(result["valid"], "the scan is a valid light measurement"
                     + ("" if result["valid"] else f": {'; '.join(result['reasons'])}"))
        report.note(f"noise edge: {_mv(result['noise_edge_v'])}"
                    + (" (from this session's dark scan)" if dark else " (from this scan; run the dark scan for a better one)"))
        if result["valley_v"] is not None:
            report.note(f"valley: {_mv(result['valley_v'])}, single-PE peak {_mv(result['peak_v'])}, "
                        f"peak/valley {result['pv_ratio']:.2f}")
        report.note(f"plateau rate at the reference level {_mv(result['reference_v'])}: "
                    f"{result['plateau_rate']:.4g} cps" if result["plateau_rate"] else "no plateau rate")
        for loss, v in result["loss_v"].items():
            report.note(f"counts reduced by {loss:.0%} from: {_mv(v)}")

        report.section("drift and hysteresis")
        report.table([(f"repeat {f['repeat']} {f['direction']}",
                       f"x{f['factor']:.4f} +- {f['sigma']:.4f}") for f in result["pass_factors"]],
                     ("pass, in time order", "light level relative to the mean"))
        if result["drift"] is not None:
            report.check(
                not result["drift_flagged"],
                f"the light stayed steady: {result['drift']:.2%} trend over the scan, "
                f"{result.get('unsteadiness', 0.0):.2%} left after removing it",
            )
            if result.get("direction_offset") is not None:
                report.note(f"up-versus-down light-level offset on the flat region: "
                            f"{result['direction_offset']:+.2%} -- hysteresis leaking onto a "
                            f"region that is not quite flat; it is kept out of the drift figure.")
        if result["hysteresis_v"] is not None:
            h, se = result["hysteresis_v"], result["hysteresis_se_v"]
            report.check(
                not result["hysteresis_flagged"],
                f"no discriminator hysteresis: up-minus-down shift {h * 1e3:+.3f} +- "
                f"{se * 1e3:.3f} mV on the shoulder",
            )
            if result["hysteresis_flagged"]:
                report.note(
                    "The level the discriminator really applies depends on which way it was "
                    "approached. Always set the operating level from the same side, or keep "
                    f"{abs(h) * 1e3:.2f} mV of extra margin.",
                )
        else:
            report.note("hysteresis: not estimable (no usable shoulder in every pass)")

        if result["dark_vanish_loss"] is not None:
            report.section("what the dark-optimised level costs")
            report.note(
                f"Dark counts vanished from {_mv(dark['vanish_v'])}. At that level this scan "
                f"counts {result['dark_vanish_loss']:.1%} fewer photons than at the reference "
                f"level -- the proof that a zero-dark-count threshold is not the optimum.",
            )

        if result["fom"]:
            report.section("background-limited figure of merit, S/sqrt(B)")
            report.note(
                "S = (light rate - dark rate) / rate at the reference level, so it can exceed 1 "
                "below the reference; "
                "B = dark rate from this session's dark scan. Only levels with at least "
                f"{FOM_MIN_DARK_COUNTS} dark counts are scored.",
            )
            report.table(
                [(f"{f['abs_v'] * 1e3:6.1f} mV",
                  f"photons vs ref {f['efficiency']:.3f}   dark {f['dark_rate']:.3g} cps "
                  f"({f['dark_counts']} counts)   S/sqrt(B) {f['relative']:.3f} of best")
                 for f in result["fom"]],
                ("|level|", "photon fraction, dark rate, figure of merit"),
            )

        report.section("recommendation")
        for reason in result["reasons"]:
            report.note(reason)
        if result["recommended_v"] is not None:
            low, high = result["window_v"] or (None, None)
            report.note(f"RECOMMENDED A DISC LVL: -{result['recommended_v'] * 1e3:.1f} mV, FALL.")
            report.note(f"Basis: {result['recommended_basis']}.")
            report.note(f"It counts {1.0 - result['recommended_loss']:.1%} of the photons "
                        f"counted at the reference level {_mv(result['reference_v'])}.")
            if result["optimum_band_v"] is not None:
                lo, hi = result["optimum_band_v"]
                report.note(f"Anywhere from {_mv(lo)} to {_mv(hi)} is within "
                            f"{1 - FOM_BAND:.0%} of the best S/sqrt(B).")
                report.note("This assumes a weak, background-limited signal. For a bright "
                            "signal (S >> B) the optimum moves down, to the lowest level above "
                            "the noise edge.")
            if low is not None and high is not None:
                report.note(f"Strict window, noise edge to 1 % loss: {_mv(low)} to {_mv(high)}"
                            + (" -- EMPTY at this gain." if result["window_empty"] else "."))
            if result["recommended_v"] < PICKUP_SAFE_V:
                report.note("Below 10 mV: valid only with the cables exactly as they were for "
                            "this scan (manual p. 22, DISC pickup).")
            report.headline = (
                f"recommended A DISC LVL -{result['recommended_v'] * 1e3:.1f} mV, counting "
                f"{1.0 - result['recommended_loss']:.0%} of photons"
                + (f"; S/sqrt(B) within 5 % of best from {_mv(result['optimum_band_v'][0])} to "
                   f"{_mv(result['optimum_band_v'][1])}" if result["optimum_band_v"] else "")
                + ("; strict window empty -- preamp would help" if result["window_empty"] else "")
            )
        else:
            report.headline = "no recommendation: " + ("; ".join(result["reasons"]) or "see the report")
    finally:
        device.reset_counters()
        failed = _restore_settings(device, SAVED_SETTINGS, saved)
        report.section("restore")
        report.check(not failed, f"every changed setting was restored (unrestored: {failed or 'none'})")
        report.note("No storage slot was used; ST, RC and SE were never sent.")

    return report, report.write(_timestamp())
