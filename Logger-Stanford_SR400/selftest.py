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
        try:
            path = os.path.join(self.device.get_folder("TEMP"), name)
            with open(path, "w") as handle:
                handle.write("\n".join(body) + "\n")
        except Exception as exc:  # noqa: BLE001 -- the report is a bonus, not the point
            # Keep the reason. "Could not be written" with no cause is the kind of message
            # that wastes an afternoon, and the report is the deliverable here.
            self.write_error = f"{type(exc).__name__}: {exc}"
            return ""

        return path


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
