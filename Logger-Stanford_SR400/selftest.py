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


def _progress(text: str) -> None:
    """One progress line in the SweepMe! debug log, where a driver's print() lands.

    message_info() is easy to miss in SweepMe! 1.5.7.9, and a 15-35 minute scan with no visible
    progress looks exactly like a hung one (reported 2026-11-10). So every step is printed,
    with the wall-clock time, and flushed so it appears as it happens.
    """
    print(f"{time.strftime('%H:%M:%S')}  SR400 {text}", flush=True)


def _minutes(seconds: float) -> str:
    return f"{seconds / 60.0:.1f} min"


def _hv_text(device) -> str:
    """The PMT HV the operator entered, e.g. '1000', or '' when none was entered."""
    hv = getattr(device, "pmt_hv_v", None)
    return f"{hv:g}" if hv else ""


def _gui_volts(magnitude_v):
    """A threshold magnitude as typed into the GUI: negative volts, 0.1 mV resolution; '' if None."""
    return "" if magnitude_v is None else round(-abs(magnitude_v), 4)


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
        self.extra_paths: dict = {}  # suffix -> path of each companion file written
        self.log_path = ""  # the running test log this report was appended to
        # Results worth a column of their own in the test log, keyed by LOG_COLUMNS name.
        self.values: dict = {}
        self.log_error = ""

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
        _progress(f"{self.title}: {name}")

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
    def write(self, timestamp: str, extras: dict | None = None) -> str:
        """Write the report, and any companion files, and return the report's path.

        extras maps a suffix ('.csv', '.svg') to file content. They share the report's stem and
        folder, so a report, its data and its plot are always found together. '' if nothing
        could be written; write_error then says why for each location.
        """
        head = [
            f"SR400 {self.title}",
            "=" * 72,
            f"when            : {timestamp}",
            f"port            : {self.device.port_string or '(none)'}",
            f"interface       : {'RS-232' if self.device.is_rs232 else 'GPIB'}",
            f"PMT HV          : "
            + (f"{_hv_text(self.device)} V (entered by the operator; the driver never sets or reads it)"
               if _hv_text(self.device) else "not recorded (enter it in the GUI field to record it)"),
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
        base_stem = os.path.splitext(name)[0]

        driver = os.path.basename(os.path.dirname(os.path.abspath(__file__)))
        errors = []
        for identifier in ("DATADEVICES", "TEMP"):
            try:
                folder = self.device.get_folder(identifier)
                if identifier == "DATADEVICES":
                    folder = os.path.join(folder, driver)
                os.makedirs(folder, exist_ok=True)
                # Never overwrite a record. Names carry the time to the second, and two tests can
                # finish in the same second: measured on the bench, where one HV's dark scan
                # silently replaced another's. A clash gets _2, _3, ... on every file of the set.
                stem, n = base_stem, 2
                while any(os.path.exists(os.path.join(folder, stem + suffix))
                          for suffix in (".txt", *(extras or {}))):
                    # "_2" sorts after the original name ("-2" would sort before it, since "-"
                    # precedes "."), so newest-by-name stays newest. Seen as flaky tests.
                    stem, n = f"{base_stem}_{n}", n + 1
                lines = list(body)
                if extras:
                    lines += ["", "Companion files, same folder:"]
                    for suffix in extras:
                        kind = {".csv": "raw data, one row per measurement",
                                ".svg": "plot -- opens in any web browser"}.get(suffix, "")
                        lines.append(f"  {stem}{suffix}   {kind}")
                path = os.path.join(folder, stem + ".txt")
                with open(path, "w") as handle:
                    handle.write("\n".join(lines) + "\n")
                self.extra_paths = {}
                for suffix, content in (extras or {}).items():
                    extra = os.path.join(folder, stem + suffix)
                    with open(extra, "w", encoding="utf-8") as handle:
                        handle.write(content)
                    self.extra_paths[suffix] = extra
                self._append_to_log(folder, timestamp, path)
                return path
            except Exception as exc:  # noqa: BLE001 -- try the next location
                errors.append(f"{identifier}: {type(exc).__name__}: {exc}")

        self.write_error = "; ".join(errors)
        return ""

    LOG_NAME = "SR400_test_log.csv"
    # The threshold columns are in volts, signed as typed into 'Discriminator A level in V'
    # (the R8486's pulses are negative, slope FALL): -6.4 mV is -0.0064. Blank when a test does
    # not produce that number, or refused to.
    LOG_COLUMNS = ("when", "test", "result", "pmt_hv_V",
                   "recommended_disc_A_level_V", "photons_counted_at_recommended",
                   "lower_bound_V", "upper_bound_1pct_loss_V", "dark_counts_vanish_V",
                   "settle_minutes", "settled_rate_cps",
                   "headline", "passed", "checks", "port", "interface", "first_failure", "report")

    # Every column layout the log has had, so a row can be placed by its field count. The first
    # is the layout of ffd18ed, when the log was introduced.
    LOG_LAYOUTS = (
        ("when", "test", "result", "recommended_disc_A_level_V", "photons_counted_at_recommended",
         "lower_bound_V", "upper_bound_1pct_loss_V", "dark_counts_vanish_V", "headline", "passed",
         "checks", "port", "interface", "first_failure", "report"),
    )

    def _migrate_log(self) -> None:
        """Rewrite a log whose header is an older layout under the current one, keeping a backup.

        Found 2026-11-10 on the lab PC: a log started by an older driver kept its 15-column header,
        and newer 18-column rows were appended beneath it, so values sat under the wrong headings
        (a lower bound under the 1 %-loss column). Each row is placed by its own field count -- a
        row as long as the current layout is read as the current layout, whatever the header says.
        The original file is kept beside it, renamed, so nothing is lost if this goes wrong.
        """
        import csv  # noqa: PLC0415

        with open(self.log_path, newline="", encoding="utf-8") as handle:
            raw = list(csv.reader(handle))
        if not raw or tuple(raw[0]) == self.LOG_COLUMNS:
            return
        header = tuple(raw[0])
        layouts = {len(layout): layout for layout in (*self.LOG_LAYOUTS, header, self.LOG_COLUMNS)}
        migrated = []
        for fields in raw[1:]:
            if not fields:
                continue
            layout = layouts.get(len(fields), header)
            migrated.append({k: v for k, v in zip(layout, fields) if k in self.LOG_COLUMNS})
        stamp = time.strftime("%Y-%m-%d_%H%M%S")
        backup = os.path.join(os.path.dirname(self.log_path),
                              f"SR400_test_log_before_column_migration_{stamp}.csv")
        os.replace(self.log_path, backup)
        with open(self.log_path, "w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=self.LOG_COLUMNS)
            writer.writeheader()
            for row in migrated:
                writer.writerow(row)
        self.log_migrated_from = backup

    def _append_to_log(self, folder: str, timestamp: str, report_path: str) -> None:
        """Append one row for this test to the running test log beside the reports.

        The reports are one file per test; the log is the index across them, so the history of
        an instrument is one file to open. A log that cannot be written never costs the report,
        which is already on disk: the reason is kept in log_error instead.
        """
        import csv  # noqa: PLC0415

        self.log_path = os.path.join(folder, self.LOG_NAME)
        self.log_error = ""
        if self.aborted:
            result = "ABORTED"
        elif self.failures:
            result = "FAIL"
        else:
            result = "PASS"
        row = {
            "when": timestamp,
            "test": self.title,
            "port": self.device.port_string or "(none)",
            "interface": "RS-232" if self.device.is_rs232 else "GPIB",
            "result": result,
            "pmt_hv_V": _hv_text(self.device),
            "passed": self.passed,
            "checks": self.checks,
            "headline": self.headline,
            "first_failure": self.failures[0] if self.failures else "",
            "report": report_path,
        }
        row.update({key: value for key, value in self.values.items() if key in self.LOG_COLUMNS})
        try:
            if os.path.exists(self.log_path):
                self._migrate_log()
            new = not os.path.exists(self.log_path)
            with open(self.log_path, "a", newline="", encoding="utf-8") as handle:
                writer = csv.DictWriter(handle, fieldnames=self.LOG_COLUMNS)
                if new:
                    writer.writeheader()
                writer.writerow(row)
        except Exception as exc:  # noqa: BLE001
            self.log_error = f"{type(exc).__name__}: {exc}"


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
        if getattr(device, "port", None) is None:
            return (
                "select a port first -- there is nothing to test yet. (Diagnostic: SweepMe! "
                "started this action with no port name and no open port. If a port is already "
                "selected in the Logger module, the action is running on a driver instance "
                "that SweepMe! has not set up, so report how it was started.)"
            )
        return (
            "select a port first -- there is nothing to test yet. (Diagnostic: an open port "
            f"was handed over, but its name could not be read from it: {type(device.port).__name__}.)"
        )

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
            raise _StopScan

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
    except _StopScan:
        pass  # aborted early on purpose; the restore below still runs and is reported
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
        # The wrapped commands refuse by raising from _require_rs232() before anything is
        # written, while the semantic functions skip them, so here a raise of that refusal is
        # the pass and a silent return means the command went out.
        for name, call in (("SW", lambda: device.set_rs232_wait(0)),
                           ("MI", lambda: device.set_front_panel_mode("Remote"))):
            try:
                call()
                report.check(False, f"{name} was sent on GPIB; the driver should have refused it")
            except Exception as exc:  # noqa: BLE001
                refused = "may only be sent via the RS-232" in str(exc)
                report.check(
                    refused,
                    f"{name} is refused by the driver on GPIB rather than sent"
                    + ("" if refused else f" (unexpected error: {exc})"),
                )

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
            raise _StopScan

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
    except _StopScan:
        pass  # no loopback cable; the restore below still runs and is reported
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
            f"connected. Join {CABLE_1} and run tier 2 again (the 'Self-test tier 2' end-of-run test).\n\n"
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

DARK_TARGET_COUNTS = 200      # ~7 % Poisson per threshold, where the rate is slow
DARK_MAX_SECONDS = 30.0       # per threshold: 200 counts at the measured ~8 cps is 25 s
# Where 500 counts take under 10 s, a threshold counts to 500 (~4.5 % Poisson) instead. On the
# first real scan (2026-11-10) that costs about 15 s in all, and firms up the fast rates that
# set the noise roll-off. PROVISIONAL: the operator's rule, not yet measured as a whole scan.
DARK_FAST_TARGET_COUNTS = 500
DARK_FAST_SECONDS = 10.0
# Once the dark rate is below 1 cps at two thresholds in a row, the scan steps 2 mV at a time.
# On the first real scan the fine grid spent most of its 21 minutes at 30 s per threshold on a
# 0-3 count tail that sets no bound. Two in a row, because one 30 s point at 1 cps is +-20 %.
# PROVISIONAL, from that one scan of one tube setup.
DARK_COARSE_BELOW_CPS = 1.0
DARK_COARSE_STEP_V = 0.002
# The scan stops once the rate is below 0.5 cps at three thresholds in a row: the tail beyond
# sets no bound, and on the first real scan (2026-11-10) it cost half the scan's time. On that
# scan's rates, with the 2 mV tail steps, this stops at 14.0 mV after about 10 minutes, instead of
# 36 mV after 21. A zero-count threshold is below 0.5 cps too. The level where dark counts
# vanish is therefore no longer measured, and the report says so. PROVISIONAL, from that one scan.
DARK_STOP_BELOW_CPS = 0.5
DARK_STOP_AFTER = 3
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

# Log-slope below which the curve has stopped being noise. PROVISIONAL, from the first real
# scan (2026-11-10, R8486 covered, GPIB): the noise roll-off fell at 1.2-4.7 /mV and the dark
# tail at 0.3-0.7 /mV, so 1.0 separates them. 0.5, the simulator-era value, put the edge in the
# middle of the dark tail (6.8 mV) once the search started in the right place.
NOISE_SLOPE_PER_MV = 1.0
SLOPE_WINDOW_V = 0.001          # slope over 1 mV, not one 0.2 mV step: Poisson noise
DIFF_WINDOW_V = 0.0005          # half-width of the differential stencil
VALLEY_PV_RATIO = 1.2           # single-PE peak must stand this far above the valley
DRIFT_TOLERANCE = 0.02          # pass-to-pass scale change worth flagging
HYSTERESIS_RESOLUTION_V = 0.0002  # the discriminator's own 0.2 mV step
PICKUP_SAFE_V = 0.010           # manual p. 22
LOSS_LEVELS = (0.001, 0.01, 0.02, 0.05, 0.10)
FOM_MIN_DARK_COUNTS = 20        # below this sqrt(B) is too uncertain to divide by (> 11 %)
# The background B in S/sqrt(B) is a local fit to the dark scan, not the single threshold's rate.
# Measured 2026-11-10: above 6 mV each dark threshold held 16-60 counts, so B was +-13-25 % per
# level, five times the 5 % band, and the "within 5 % of the best" band shrank to one level in
# both light scans. The fit pools the thresholds within +-1 mV (wider where the grid is coarse,
# until it has 3 thresholds) as rate = exp(a + b * (level - here)), by Poisson maximum likelihood
# so that zero-count thresholds count correctly. PROVISIONAL: the window width is a judgement.
DARK_SMOOTH_HALF_WIDTH_V = 0.001
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
    "adequate statistics.\n\n"
    "New to this? Step-by-step guide: docs/THRESHOLD_SCAN_GUIDE.md in the "
    "sr400-sweepme-driver repository.\n\n"
    "Press OK to start."
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
    "New to this? Step-by-step guide: docs/THRESHOLD_SCAN_GUIDE.md in the "
    "sr400-sweepme-driver repository.\n\n"
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

    # Start at the rate maximum. Measured 2026-11-10: below ~1.2 mV the real rate RISES with
    # the threshold (3.9e4 cps at 0.4 mV, 2.3e5 at 1.2 mV). A rising rate has a negative
    # log-slope, which passed "below the limit", so the first level scanned was reported as the
    # noise edge and the lower bound came out at 1.0 mV, deep in the noise.
    peak = max(range(len(rows)), key=lambda i: rows[i]["rate"]) if rows else 0
    for i in range(peak, len(slopes) - 1):
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

    if not result["valid"]:
        # The noise edge stays, as a diagnostic of what was seen. The BOUND goes: a level
        # derived from a lit or disconnected tube must not be readable off the figure as an
        # operating threshold.
        result["lower_bound_v"] = None

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
    """-dR/dV in cps/mV by a centred stencil of +-0.5 mV: the pulse-height density.

    Where the grid is coarser than the stencil (2 mV steps above 15.2 mV), +-0.5 mV finds the row
    itself on both sides and the density would be undefined. Found on the bench, 2026-11-10: at
    higher PMT HV the single-PE peak moves past 15 mV and could then never be found, so it stuck
    at 16 mV whatever the gain. There the stencil falls back to the neighbouring rows. On the fine
    grid, where it finds distinct rows, nothing changes.
    """
    out = []
    for i, row in enumerate(rows):
        lo = _value_at(rows, row["abs_v"] - DIFF_WINDOW_V)
        hi = _value_at(rows, row["abs_v"] + DIFF_WINDOW_V)
        if lo is row and i > 0:
            lo = rows[i - 1]
        if hi is row and i + 1 < len(rows):
            hi = rows[i + 1]
        span_mv = (hi["abs_v"] - lo["abs_v"]) * 1e3
        out.append((lo["rate"] - hi["rate"]) / span_mv if span_mv > 0 else float("nan"))
    return out


def _pct(loss: float) -> str:
    """0.1 % and 1 %, never 0 % for a loss below one percent."""
    return f"{loss * 100:.1f} %" if loss < 0.01 else f"{loss * 100:.0f} %"


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

    # How well each loss level is pinned. A loss is a DIFFERENCE of two Poisson rates, so its
    # relative uncertainty is about sqrt(2/N) with N counts per level. Dividing by the local
    # slope of the normalised curve turns that into mV. A level that sits within its own
    # uncertainty of the reference, or within one 0.2 mV discriminator step, is not separable
    # from it. Measured 2026-11-10: with ~7e4 counts per level the loss is +-0.5 %, so 0.1 %
    # loss cannot be told apart from the reference, and resolving it needs ~8e6 counts per level.
    ref_counts = _value_at(rows, reference)["counts"]
    sigma_loss = _math.sqrt(2.0 / ref_counts) if ref_counts > 0 else float("inf")
    result["loss_sigma"] = sigma_loss
    result["counts_per_level"] = ref_counts
    result["loss_detail"] = {}
    for loss, v in result["loss_v"].items():
        if v is None:
            result["loss_detail"][loss] = None
            continue
        lo, hi = _value_at(rows, v - DIFF_WINDOW_V), _value_at(rows, v + DIFF_WINDOW_V)
        span_mv = (hi["abs_v"] - lo["abs_v"]) * 1e3
        slope = (lo["rate"] - hi["rate"]) / plateau / span_mv if span_mv > 0 else 0.0
        sigma_v = sigma_loss / slope if slope > 0 else float("inf")  # mV
        above_mv = (v - reference) * 1e3
        result["loss_detail"][loss] = {
            "v": v, "sigma_mv": sigma_v,
            "separable": above_mv > sigma_v,
            # The discriminator sets |level| in 0.2 mV steps: report the step the user can set.
            "settable_v": round(v / HYSTERESIS_RESOLUTION_V) * HYSTERESIS_RESOLUTION_V,
            "counts_needed": 8.0 / loss ** 2,  # sqrt(2/N) <= loss/2
        }

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
        top = max((d["abs_v"] for d in dark["rows"]), default=0.0)
        for r in rows:
            if r["abs_v"] > top + 1e-9:
                continue  # beyond the dark scan: the fit would be an extrapolation
            fit = _smooth_dark_rate(dark["rows"], r["abs_v"])
            if fit is None:
                continue
            b_rate, b_sigma, b_counts = fit
            efficiency = max(r["rate"] - b_rate, 0.0) / plateau
            result["fom"].append({"abs_v": r["abs_v"], "efficiency": efficiency,
                                  "dark_rate": b_rate, "dark_counts": b_counts, "dark_sigma": b_sigma,
                                  "fom": efficiency / _math.sqrt(b_rate)})
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


def _measure_point(device, abs_v: float, target_counts: int, max_seconds: float,
                   fast_target: int = 0, fast_seconds: float = 0.0, min_seconds: float = 0.0) -> dict:
    """Count at one threshold until the target or max_seconds, whichever first.

    The target is target_counts, or fast_target where the rate measured so far says fast_target
    counts take under fast_seconds. The next period is sized from that rate, so a noisy low
    threshold takes 10 ms and a quiet high one takes up to max_seconds. Every period length is
    first rounded UP to a settable value and then read back, so the live time is what the
    instrument used.
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
        target = target_counts
        if fast_target > target_counts and counts > 0 and fast_target * live / counts < fast_seconds:
            target = fast_target
        if (counts >= target and live >= min_seconds - 1e-9) or live >= max_seconds - 1e-9:
            break
        remaining = max_seconds - live
        needed = (target - counts) * live / counts if counts > 0 else period * 10.0
        needed = max(needed, min_seconds - live)
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


# ==========================================================================
#  Scan records and plots -- CSV plus dependency-free SVG
# ==========================================================================
#
# The operator chooses the threshold from these, so they must exist on every machine they reach.
# SweepMe! 1.5.8 does bundle matplotlib, but a plain pysweepme environment does not, and a report
# gets sent to machines with neither. So each figure is drawn as plain SVG -- a text file any web
# browser opens --
# and it is drawn FROM the CSV record, by the same analysis the report uses. Any figure can be
# regenerated from its CSV on any machine with a Python interpreter, nothing installed:
#
#     python selftest.py plot <scan>.csv
#
# The CSV holds only raw instrument values per threshold: counts and live time (and, for the
# light scan, which pass). Rates, edges, valleys and the recommendation are all derived on load,
# so a figure cannot disagree with its record.

import html as _html

_SCAN_COLUMNS = {
    "settle": ("block", "abs_v_V", "level_V", "counts", "live_s", "t_s"),
    "dark": ("abs_v_V", "level_V", "counts", "live_s", "t_s"),
    "light": ("repeat", "direction", "abs_v_V", "level_V", "counts", "live_s", "t_s"),
}


class _StopScan(Exception):
    """Leave a run early. Caught before the restore, so the report is still written AFTER it."""


def _scan_meta(device, kind: str, stamp: str, **extra) -> dict:
    meta = {
        "kind": kind,
        "when": stamp,
        "port": device.port_string or "(none)",
        "interface": "RS-232" if device.is_rs232 else "GPIB",
        "driver": os.path.basename(os.path.dirname(os.path.abspath(__file__))),
        "counter": SCAN_COUNTER,
        "input": f"SIGNAL INPUT {SCAN_INPUT}",
        "slope": SCAN_SLOPE.upper(),
        "hv_V": _hv_text(device),
    }
    meta.update({k: str(v) for k, v in extra.items()})
    return meta


def scan_csv(meta: dict, records: list) -> str:
    """A scan record: '#' metadata lines, a header, then one raw row per measurement."""
    columns = _SCAN_COLUMNS[meta["kind"]]
    # Scan times are relative to the first point. A settling record's times are already the
    # elapsed time since the check began, which is what its analysis needs: kept as they are.
    t0 = 0.0 if meta["kind"] == "settle" else min((r["t"] for r in records if "t" in r), default=0.0)
    lines = [f"# {key}: {value}" for key, value in meta.items()]
    lines.append(",".join(columns))
    for r in records:
        values = {
            "repeat": r.get("repeat", ""), "direction": r.get("direction", ""),
            "block": r.get("block", ""),
            "abs_v_V": f"{r['abs_v']:.5f}", "level_V": f"{r['level_v']:.5f}",
            "counts": str(int(r["counts"])), "live_s": f"{r['live_s']:.6f}",
            "t_s": f"{r.get('t', t0) - t0:.3f}",
        }
        lines.append(",".join(str(values[c]) for c in columns))
    return "\n".join(lines) + "\n"


def read_scan_csv(path: str):
    """Inverse of scan_csv. Returns (meta, points) for dark, (meta, passes) for light."""
    meta, header, rows = {}, None, []
    with open(path, encoding="utf-8") as handle:
        for line in handle:
            line = line.rstrip("\r\n")
            if not line:
                continue
            if line.startswith("#"):
                key, _, value = line[1:].partition(":")
                meta[key.strip()] = value.strip()
            elif header is None:
                header = line.split(",")
            else:
                rows.append(dict(zip(header, line.split(","))))

    def point(row):
        return {"abs_v": float(row["abs_v_V"]), "level_v": float(row["level_V"]),
                "counts": int(row["counts"]), "live_s": float(row["live_s"]),
                "t": float(row["t_s"])}

    if meta.get("kind") == "dark":
        return meta, [point(r) for r in rows]
    if meta.get("kind") == "settle":
        return meta, [dict(point(r), block=int(r["block"])) for r in rows]

    passes = []
    for row in rows:
        key = (int(row["repeat"]), row["direction"])
        if not passes or (passes[-1]["repeat"], passes[-1]["direction"]) != key:
            passes.append({"repeat": key[0], "direction": key[1], "points": []})
        passes[-1]["points"].append(point(row))
    return meta, passes


# ------------------------------------------------------------------ SVG drawing

_PASS_COLORS = ("#1f77b4", "#d62728", "#2ca02c", "#9467bd", "#ff7f0e", "#8c564b")
_C = {"edge": "#e67e22", "bound": "#1a9850", "vanish": "#c0392b", "valley": "#8e44ad",
      "rec": "#1a9850", "pickup": "#7f8c8d", "band": "#f39c12", "noise": "#bdc3c7"}


class _Svg:
    def __init__(self, width: int, height: int) -> None:
        self.width, self.height = width, height
        self.parts: list = []
        self._clips = 0

    def text(self, x, y, s, size=12, anchor="start", weight="normal", color="#222",
             rotate=None, italic=False):
        transform = f' transform="rotate({rotate} {x:.1f} {y:.1f})"' if rotate else ""
        style = ' font-style="italic"' if italic else ""
        self.parts.append(
            f'<text x="{x:.1f}" y="{y:.1f}" font-size="{size}" font-family="Arial, sans-serif" '
            f'text-anchor="{anchor}" font-weight="{weight}" fill="{color}"{style}{transform}>'
            f"{_html.escape(str(s))}</text>",
        )

    def line(self, x1, y1, x2, y2, color="#222", width=1.0, dash=None, clip=None):
        extra = (f' stroke-dasharray="{dash}"' if dash else "") + (f' clip-path="url(#{clip})"' if clip else "")
        self.parts.append(f'<line x1="{x1:.1f}" y1="{y1:.1f}" x2="{x2:.1f}" y2="{y2:.1f}" '
                          f'stroke="{color}" stroke-width="{width}"{extra}/>')

    def rect(self, x, y, w, h, fill="none", stroke="none", opacity=1.0, clip=None):
        extra = f' clip-path="url(#{clip})"' if clip else ""
        self.parts.append(f'<rect x="{x:.1f}" y="{y:.1f}" width="{max(w, 0):.1f}" height="{max(h, 0):.1f}" '
                          f'fill="{fill}" stroke="{stroke}" fill-opacity="{opacity}"{extra}/>')

    def polyline(self, points, color, width=1.5, dash=None, clip=None):
        if len(points) < 2:
            return
        extra = (f' stroke-dasharray="{dash}"' if dash else "") + (f' clip-path="url(#{clip})"' if clip else "")
        coords = " ".join(f"{x:.1f},{y:.1f}" for x, y in points)
        self.parts.append(f'<polyline points="{coords}" fill="none" stroke="{color}" '
                          f'stroke-width="{width}"{extra}/>')

    def marker(self, x, y, shape, color, size=3.5, filled=True, clip=None):
        fill = color if filled else "white"
        extra = f' clip-path="url(#{clip})"' if clip else ""
        if shape == "o":
            self.parts.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="{size:.1f}" fill="{fill}" '
                              f'stroke="{color}" stroke-width="1.2"{extra}/>')
        else:
            s = size * 1.3
            pts = ((x, y - s), (x - s, y + s * 0.8), (x + s, y + s * 0.8)) if shape == "^" else \
                  ((x, y + s), (x - s, y - s * 0.8), (x + s, y - s * 0.8))
            coords = " ".join(f"{px:.1f},{py:.1f}" for px, py in pts)
            self.parts.append(f'<polygon points="{coords}" fill="{fill}" stroke="{color}" '
                              f'stroke-width="1.2"{extra}/>')

    def clip_rect(self, x, y, w, h) -> str:
        self._clips += 1
        name = f"clip{self._clips}"
        self.parts.append(f'<clipPath id="{name}"><rect x="{x:.1f}" y="{y:.1f}" '
                          f'width="{w:.1f}" height="{h:.1f}"/></clipPath>')
        return name

    def render(self) -> str:
        return (f'<svg xmlns="http://www.w3.org/2000/svg" width="{self.width}" height="{self.height}" '
                f'viewBox="0 0 {self.width} {self.height}">\n'
                f'<rect x="0" y="0" width="{self.width}" height="{self.height}" fill="white"/>\n'
                + "\n".join(self.parts) + "\n</svg>\n")


def _nice_ticks(lo: float, hi: float, target: int = 7) -> list:
    span = hi - lo
    if span <= 0:
        return [lo]
    raw = span / target
    magnitude = 10.0 ** _math.floor(_math.log10(raw))
    step = min((m * magnitude for m in (1, 2, 5, 10)), key=lambda s: abs(s - raw))
    first = _math.ceil(lo / step - 1e-9) * step
    ticks = []
    value = first
    while value <= hi + 1e-9 * step:
        ticks.append(round(value, 10))
        value += step
    return ticks


def _fmt(v: float) -> str:
    return f"{v:g}" if abs(v) < 1e5 else f"{v:.0e}"


class _Panel:
    """One axes box: data-to-pixel mapping, frame, ticks, and the marks drawn into it."""

    def __init__(self, svg, x, y, w, h, xlim, ylim, log_y=False):
        self.svg, self.x, self.y, self.w, self.h = svg, x, y, w, h
        self.x0, self.x1 = xlim
        self.log_y = log_y
        self.y0, self.y1 = ylim
        if log_y:
            self.y0, self.y1 = max(self.y0, 1e-12), max(self.y1, self.y0 * 10)
        self.clip = svg.clip_rect(x, y, w, h)
        self.legend_items: list = []

    def px(self, v):
        return self.x + (v - self.x0) / (self.x1 - self.x0) * self.w

    def py(self, v):
        if v is None or not _math.isfinite(v):
            return None
        if self.log_y:
            if v <= 0:
                return None
            t = (_math.log10(v) - _math.log10(self.y0)) / (_math.log10(self.y1) - _math.log10(self.y0))
        else:
            t = (v - self.y0) / (self.y1 - self.y0)
        return self.y + self.h - t * self.h

    def frame(self, title, xlabel, ylabel):
        s = self.svg
        for tick in _nice_ticks(self.x0, self.x1):
            X = self.px(tick)
            s.line(X, self.y, X, self.y + self.h, "#eeeeee", 1)
            s.line(X, self.y + self.h, X, self.y + self.h + 4, "#222", 1)
            s.text(X, self.y + self.h + 16, _fmt(tick), 10, "middle")
        if self.log_y:
            for k in range(_math.ceil(_math.log10(self.y0) - 1e-9), _math.floor(_math.log10(self.y1) + 1e-9) + 1):
                Y = self.py(10.0 ** k)
                s.line(self.x, Y, self.x + self.w, Y, "#eeeeee", 1)
                s.line(self.x - 4, Y, self.x, Y, "#222", 1)
                s.text(self.x - 6, Y + 4, f"1e{k}" if k not in (0, 1, 2, 3) else _fmt(10 ** k), 10, "end")
        else:
            for tick in _nice_ticks(self.y0, self.y1, 6):
                Y = self.py(tick)
                s.line(self.x, Y, self.x + self.w, Y, "#eeeeee", 1)
                s.line(self.x - 4, Y, self.x, Y, "#222", 1)
                s.text(self.x - 6, Y + 4, _fmt(tick), 10, "end")
        s.rect(self.x, self.y, self.w, self.h, stroke="#222")
        s.text(self.x, self.y - 8, title, 13, weight="bold")
        s.text(self.x + self.w / 2, self.y + self.h + 34, xlabel, 11, "middle")
        s.text(self.x - 52, self.y + self.h / 2, ylabel, 11, "middle", rotate=-90)

    def series(self, xs, ys, color, marker=None, dash=None, width=1.5, filled=True, label=None, line=True):
        pts = [(self.px(x), self.py(y)) for x, y in zip(xs, ys) if self.py(y) is not None]
        if line:
            self.svg.polyline(pts, color, width, dash, self.clip)
        if marker:
            for X, Y in pts:
                self.svg.marker(X, Y, marker, color, filled=filled, clip=self.clip)
        if label:
            self.legend_items.append((label, color, marker, dash, filled, line))

    def errorbars(self, xs, ys, sigmas, color):
        for x, y, sig in zip(xs, ys, sigmas):
            top, bottom = self.py(y + sig), self.py(y - sig)
            if top is None:
                continue
            bottom = self.y + self.h if bottom is None else bottom
            X = self.px(x)
            self.svg.line(X, top, X, bottom, color, 1, clip=self.clip)

    def vline(self, x, color, label, dash="5,3", slot=0):
        if x is None or not (self.x0 <= x <= self.x1):
            return
        X = self.px(x)
        self.svg.line(X, self.y, X, self.y + self.h, color, 1.5, dash)
        right_side = X > self.x + 0.62 * self.w
        self.svg.text(X - 3 if right_side else X + 3, self.y + 14 + 13 * slot, label, 10,
                      "end" if right_side else "start", color=color)

    def hline(self, y, color, label, dash="4,3", stagger=0, left=False):
        Y = self.py(y)
        if Y is None or not (self.y <= Y <= self.y + self.h):
            return
        self.svg.line(self.x, Y, self.x + self.w, Y, color, 1, dash)
        if left:
            self.svg.text(self.x + 4, Y - 3, label, 9, "start", color=color)
        else:
            self.svg.text(self.x + self.w - 4 - 52 * stagger, Y - 3, label, 9, "end", color=color)

    def band(self, x0, x1, color, label, opacity=0.18):
        a, b = self.px(max(x0, self.x0)), self.px(min(x1, self.x1))
        if b <= a:
            return
        self.svg.rect(a, self.y, b - a, self.h, fill=color, opacity=opacity)
        self.svg.text(a + 3, self.y + self.h - 6, label, 10, color="#555", italic=True)

    def note(self, text, color="#555", line=0, corner="tl"):
        if corner == "br":
            self.svg.text(self.x + self.w - 8, self.y + self.h - 10 - 14 * line, text, 11, "end",
                          color=color, italic=True)
        else:
            self.svg.text(self.x + 8, self.y + 18 + 14 * line, text, 11, color=color, italic=True)

    def legend(self):
        if not self.legend_items:
            return
        width = 12 + 6.2 * max(len(item[0]) for item in self.legend_items) + 30
        x, y = self.x + self.w - width - 6, self.y + 6
        self.svg.rect(x, y, width, 8 + 15 * len(self.legend_items), fill="white", stroke="#cccccc", opacity=0.92)
        for i, (label, color, marker, dash, filled, line) in enumerate(self.legend_items):
            Y = y + 14 + 15 * i
            if line:
                self.svg.line(x + 6, Y - 4, x + 28, Y - 4, color, 1.5, dash)
            if marker:
                self.svg.marker(x + 17, Y - 4, marker, color, filled=filled)
            self.svg.text(x + 34, Y, label, 10)


def _wrapped(text: str, width_chars: int) -> list:
    import textwrap
    return textwrap.wrap(text, width_chars) or [""]


def _text_block(svg, x, y, width_chars, lines, size=12) -> float:
    """Wrapped text, height from content so it can never overprint what follows. Returns end y."""
    import textwrap
    row = size + 4
    for raw in lines:
        color, weight = "#222", "normal"
        if raw.startswith("!"):
            raw, color, weight = raw[1:], "#c0392b", "bold"
        elif raw.startswith("+"):
            raw, color, weight = raw[1:], "#1a7f37", "bold"
        for piece in textwrap.wrap(raw, width_chars) or [""]:
            svg.text(x, y, piece, size, color=color, weight=weight)
            y += row
    return y


def _mv_axis_max(rows) -> float:
    return max((r["abs_v"] for r in rows), default=0.04) * 1e3 * 1.03 + 0.2


def plot_dark(result: dict, meta: dict) -> str:
    rows = result["rows"]
    findings = _dark_findings(result)
    W = 1100
    text_height = 22 + 16 * sum(max(1, len(line) // 150 + 1) for line in findings)
    verdict_lines = 1 if result["valid"] else len(_wrapped("; ".join(result["reasons"]), 150))
    H = 118 + 17 * (verdict_lines - 1) + 420 + 78 + 180 + 70 + text_height
    svg = _Svg(W, int(H))
    svg.text(24, 30, "SR400 threshold scan, DARK -- covered R8486 on SIGNAL INPUT 1, discriminator A, FALL", 17, weight="bold")
    if meta.get("note"):
        # A record can say what it is -- e.g. that it is simulated -- and then the figure must
        # say it too, where no reader can miss it, not only in the CSV header.
        svg.text(W - 24, 30, meta["note"], 14, "end", weight="bold", color="#c0392b")
    svg.text(24, 50, f"{meta.get('when', '')}   port {meta.get('port', '')} ({meta.get('interface', '')})   "
                     f"PMT HV {_meta_hv(meta)}   driver {meta.get('driver', '')}   "
                     f"counts and live time are raw; rate = counts / live time", 11, color="#555")
    verdict = ("+VALID covered-PMT measurement" if result["valid"]
               else "!INVALID -- " + "; ".join(result["reasons"]))
    shift = _text_block(svg, 24, 74, 150, [verdict], 13) - 74 - 17

    xmax = _mv_axis_max(rows)
    positive = [r["rate"] for r in rows if r["counts"] > 0]
    limits = [r["upper95"] for r in rows if r["upper95"]]
    ymin = min(positive + limits, default=0.01) / 3.0
    ymax = max(positive + limits, default=10.0) * 3.0
    a = _Panel(svg, 90, 118 + shift, 980, 420, (0.0, xmax), (ymin, ymax), log_y=True)
    a.frame("(a) dark count rate above each threshold", "|discriminator level|, mV",
            "rate, counts/s (log)")
    if result["oscillating_below_v"] is not None:
        a.band(0.0, result["oscillating_below_v"] * 1e3, _C["noise"],
               f"> {OSCILLATION_RATE_CPS:.0e} counts/s: noise / pickup, not dark counts", 0.35)
    measured = [r for r in rows if r["counts"] > 0]
    xs = [r["abs_v"] * 1e3 for r in measured]
    a.errorbars(xs, [r["rate"] for r in measured], [r["sigma"] for r in measured], "#1f77b4")
    a.series(xs, [r["rate"] for r in measured], "#1f77b4", "o", label="counts > 0, +-1 sigma Poisson")
    zeros = [r for r in rows if r["counts"] == 0]
    a.series([r["abs_v"] * 1e3 for r in zeros], [r["upper95"] for r in zeros], "#c0392b", "v",
             filled=False, line=False, label="0 counts: 95 % upper limit, 3 / live time")
    a.vline(PICKUP_SAFE_V * 1e3, _C["pickup"], "10 mV: DISC pickup risk below (manual p. 22)", "2,3", 3)
    if result["noise_edge_v"] is not None:
        a.vline(result["noise_edge_v"] * 1e3, _C["edge"],
                f"noise edge {result['noise_edge_v'] * 1e3:.1f} mV"
                + ("" if result["valid"] else " -- diagnostic only, scan invalid"), "5,3", 0)
    if result["lower_bound_v"] is not None:
        a.vline(result["lower_bound_v"] * 1e3, _C["bound"], f"lower bound {result['lower_bound_v'] * 1e3:.1f} mV", None, 1)
    if result["vanish_v"] is not None:
        a.vline(result["vanish_v"] * 1e3, _C["vanish"],
                f"dark counts vanish {result['vanish_v'] * 1e3:.1f} mV -- NOT the optimum", "5,3", 4)
        # slot 4, not 2: the legend sits top-right and drew straight over this label's second half
        # -- hiding exactly the "NOT the optimum" warning. Four rows down clears the legend box.
    a.legend()

    b = _Panel(svg, 90, 118 + shift + 420 + 78, 980, 180, (0.0, xmax), (0.0, DARK_MAX_SECONDS * 1.15))
    b.frame("(b) statistics: live time spent per threshold", "|discriminator level|, mV", "live time, s")
    hit = [r for r in rows if r["counts"] >= DARK_TARGET_COUNTS]
    capped = [r for r in rows if r["counts"] < DARK_TARGET_COUNTS]
    b.series([r["abs_v"] * 1e3 for r in hit], [r["live_s"] for r in hit], "#1a7f37", "o", line=False,
             label=f"reached its count target ({DARK_FAST_TARGET_COUNTS} where that took "
                   f"< {DARK_FAST_SECONDS:g} s, else {DARK_TARGET_COUNTS})")
    b.series([r["abs_v"] * 1e3 for r in capped], [r["live_s"] for r in capped], "#c0392b", "o",
             filled=False, line=False, label=f"hit the {DARK_MAX_SECONDS:g} s cap: fewer counts, wider error bar")
    b.hline(DARK_MAX_SECONDS, "#c0392b", f"time cap {DARK_MAX_SECONDS:g} s", left=True)
    b.legend()

    _text_block(svg, 24, 118 + shift + 420 + 78 + 180 + 62, 150, findings)
    return svg.render()


def _meta_hv(meta: dict) -> str:
    return f"{meta['hv_V']} V" if meta.get("hv_V") else "not recorded"


def plot_light(result: dict, passes: list, dark: dict | None, meta: dict) -> str:
    rows = result["rows"]
    findings = _light_findings(result, dark)
    W = 1200
    text_height = 22 + 16 * sum(max(1, len(line) // 160 + 1) for line in findings)
    P = 330
    if result["recommended_v"] is not None:
        headline = (f"+RECOMMENDED A DISC LVL -{result['recommended_v'] * 1e3:.1f} mV, FALL -- counts "
                    f"{1 - result['recommended_loss']:.1%} of photons at the reference level.  Basis: "
                    f"{result['recommended_basis']}.")
    else:
        headline = "!NO RECOMMENDATION -- " + ("; ".join(result["reasons"]) or "see the report")
    top = 118 + 17 * (len(_wrapped(headline.lstrip("+!"), 165)) - 1)
    row2 = top + P + 82
    # Panel (c)'s readout goes under its axes, never over the data: sized from its own lines.
    readout = ([f"Count loss vs the reference {_mv(result['reference_v'])} (raw rates, +- Poisson):"]
               + _loss_lines(result)) if result.get("loss_detail") else []
    readout_h = (10 + 14 * len(readout)) if readout else 0
    H = row2 + P + 70 + readout_h + text_height
    svg = _Svg(W, int(H))
    svg.text(24, 30, "SR400 threshold scan, LIGHT -- R8486 on SIGNAL INPUT 1, discriminator A, FALL", 17, weight="bold")
    if meta.get("note"):
        # A record can say what it is -- e.g. that it is simulated -- and then the figure must
        # say it too, where no reader can miss it, not only in the CSV header.
        svg.text(W - 24, 30, meta["note"], 14, "end", weight="bold", color="#c0392b")
    svg.text(24, 50, f"{meta.get('when', '')}   port {meta.get('port', '')} ({meta.get('interface', '')})   "
                     f"PMT HV {_meta_hv(meta)}   {len(passes)} passes   "
                     f"dark scan used: {meta.get('dark_csv') or 'none this session'}", 11, color="#555")
    _text_block(svg, 24, 74, 165, [headline], 13)

    if not rows:
        svg.text(24, top + 40, "No thresholds common to every pass: nothing to plot.", 14, color="#c0392b")
        return svg.render()

    xmax = _mv_axis_max(rows)
    lx, rx, pw = 90, 690, 480

    # (a) every pass, so drift and hysteresis are visible rather than averaged away
    rates = [p["counts"] / p["live_s"] for ps in passes for p in ps["points"] if p["counts"] > 0]
    a = _Panel(svg, lx, top, pw, P, (0.0, xmax), (min(rates, default=1) / 3, max(rates, default=10) * 3), log_y=True)
    a.frame("(a) count rate, every pass", "|discriminator level|, mV", "rate, counts/s (log)")
    for ps in passes:
        color = _PASS_COLORS[(ps["repeat"] - 1) % len(_PASS_COLORS)]
        pts = sorted(ps["points"], key=lambda p: p["abs_v"])
        a.series([p["abs_v"] * 1e3 for p in pts], [p["counts"] / p["live_s"] for p in pts], color,
                 "^" if ps["direction"] == "up" else "v", None if ps["direction"] == "up" else "4,3", 1.0,
                 label=f"repeat {ps['repeat']} {ps['direction']}")
    a.vline(PICKUP_SAFE_V * 1e3, _C["pickup"], "10 mV pickup risk below", "2,3", 0)
    a.note("where passes agree they overprint; drift or hysteresis separates them", corner="br")
    a.legend()

    # (b) the same data, zoomed and normalised: a 1-5 % knee is invisible on a log axis
    plateau = result["plateau_rate"]
    if plateau:
        ref = result["reference_v"] * 1e3
        tail = next((r["abs_v"] * 1e3 for r in rows if r["abs_v"] * 1e3 > ref and r["rate"] / plateau < 0.4), xmax)
        b = _Panel(svg, rx, top, pw, P, (max(ref - 1.5, 0.0), tail + 0.5), (0.4, 1.08))
        b.frame("(b) counts relative to the reference level, zoomed", "|discriminator level|, mV",
                "rate / rate at reference")
        for ps in passes:
            color = _PASS_COLORS[(ps["repeat"] - 1) % len(_PASS_COLORS)]
            pts = sorted(ps["points"], key=lambda p: p["abs_v"])
            b.series([p["abs_v"] * 1e3 for p in pts], [p["counts"] / p["live_s"] / plateau for p in pts], color,
                     "^" if ps["direction"] == "up" else "v", None if ps["direction"] == "up" else "4,3", 0.8)
        for i, loss in enumerate(LOSS_LEVELS):
            b.hline(1.0 - loss, "#7f8c8d", f"{_pct(loss)}", stagger=i)
        # Slots 6-8 put these labels under the loss lines, which crowd the top of the panel.
        b.vline(ref, _C["valley"], f"reference {ref:.1f} mV", "5,3", 6)
        if result["noise_edge_v"] is not None:
            b.vline(result["noise_edge_v"] * 1e3, _C["edge"], f"noise edge {result['noise_edge_v'] * 1e3:.1f}", "5,3", 7)
        if result["recommended_v"] is not None:
            b.vline(result["recommended_v"] * 1e3, _C["rec"], f"recommended {result['recommended_v'] * 1e3:.1f}", None, 8)
    else:
        svg.text(rx, top + 40, "(b) NOT SHOWN: no reference level, so nothing to normalise to.", 12, color="#c0392b")

    # (c) where the pulses are, light and dark, and what each level costs in counts.
    # Log y, because the light density is ~1e4 times the dark one and a linear axis flattens the
    # dark curve to zero. A negative density -- the rate RISING with the level, as in the noise
    # hump of the real tube (measured 2026-11-10) -- has no meaning as a density, so that region
    # is shaded and named instead of drawn off the bottom of the panel.
    dens = [(r["abs_v"] * 1e3, r["density"]) for r in rows if _math.isfinite(r.get("density", float("nan")))]
    positive = [(v, d) for v, d in dens if d > 0]
    dark_dens = []
    if dark and dark.get("rows"):
        drows = dark["rows"]
        for r, d in zip(drows, _differential(drows)):
            lo = _value_at(drows, r["abs_v"] - DIFF_WINDOW_V)
            hi = _value_at(drows, r["abs_v"] + DIFF_WINDOW_V)
            # Thin tails make a differential of noise: only where both ends had real counts.
            if _math.isfinite(d) and d > 0 and min(lo["counts"], hi["counts"]) >= FOM_MIN_DARK_COUNTS:
                dark_dens.append((r["abs_v"] * 1e3, d))
    values = [d for _, d in positive] + [d for _, d in dark_dens]
    c = _Panel(svg, lx, row2, pw, P, (0.0, xmax),
               (min(values, default=1.0) / 3, max(values, default=10.0) * 30), log_y=True)
    c.frame("(c) pulse-height density, light and dark (log)", "|discriminator level|, mV",
            "counts/s per mV (log)")
    rising = [v for v, d in dens if d <= 0]
    if rising:
        c.band(0.0, max(rising) + 0.1, _C["noise"], "", opacity=0.35)
        c.note(f"shaded: rate rises with level up to {max(rising):.1f} mV (noise hump), "
               f"so no density", corner="br", line=0)
    c.series([v for v, _ in positive], [d for _, d in positive], "#34495e", "o", width=1.0,
             label="light, this scan")
    if dark_dens:
        c.series([v for v, _ in dark_dens], [d for _, d in dark_dens], "#c0392b", "o", width=1.0,
                 filled=False, label="dark scan, covered tube")
    else:
        c.note("dark density NOT SHOWN: no dark scan", "#c0392b", corner="br", line=1)
    slot = 0
    if result["valley_v"] is not None:
        c.vline(result["valley_v"] * 1e3, _C["valley"], f"valley {result['valley_v'] * 1e3:.1f}", "5,3", slot)
        slot += 1
    if result["peak_v"] is not None:
        c.vline(result["peak_v"] * 1e3, "#34495e", f"SPE peak {result['peak_v'] * 1e3:.1f}", "5,3", slot)
        slot += 1
    if dark and dark.get("noise_edge_v") is not None:
        c.vline(dark["noise_edge_v"] * 1e3, _C["edge"], f"dark noise edge {dark['noise_edge_v'] * 1e3:.1f}", "2,3", slot)
        slot += 1
    one = (result.get("loss_detail") or {}).get(0.01)
    if one and one["separable"]:
        c.vline(one["v"] * 1e3, "#7f8c8d", f"1 % loss {one['v'] * 1e3:.1f}", "4,2", slot)
    c.legend()
    # The readout, under the axes: every loss level with its uncertainty and GUI value, or
    # why it is not given. Spans both columns so no line has to wrap.
    if readout:
        by = row2 + P + 48
        svg.rect(lx - 66, by, W - 2 * (lx - 66), readout_h, fill="#fafafa", stroke="#cccccc")
        for k, line in enumerate(readout):
            svg.text(lx - 58, by + 16 + 14 * k, line, 11,
                     color="#c0392b" if "NOT SEPARABLE" in line else "#222",
                     weight="bold" if k == 0 or "NOT SEPARABLE" in line else "normal")

    # (d) the background-limited figure of merit, which is what picks the level
    if result["fom"]:
        d = _Panel(svg, rx, row2, pw, P, (0.0, xmax), (0.0, 1.08))
        d.frame("(d) S/sqrt(B), relative to its best", "|discriminator level|, mV", "S/sqrt(B) / best")
        if result["optimum_band_v"]:
            lo, hi = result["optimum_band_v"]
            d.band(lo * 1e3, hi * 1e3, _C["band"], f"within {1 - FOM_BAND:.0%} of best")
        d.series([f["abs_v"] * 1e3 for f in result["fom"]], [f["relative"] for f in result["fom"]], "#1a7f37", "o", width=1.2)
        if result["recommended_v"] is not None:
            d.vline(result["recommended_v"] * 1e3, _C["rec"], f"recommended {result['recommended_v'] * 1e3:.1f}", None, 0)
        if dark and dark.get("vanish_v") is not None:
            d.vline(dark["vanish_v"] * 1e3, _C["vanish"], f"dark counts vanish {dark['vanish_v'] * 1e3:.1f}", "5,3", 1)
            d.note(f"levels with < {FOM_MIN_DARK_COUNTS} dark counts are not scored", corner="br", line=1)
    else:
        svg.rect(rx, row2, pw, P, stroke="#cccccc")
        svg.text(rx + 12, row2 + 26, "(d) S/sqrt(B): NOT SHOWN", 13, weight="bold")
        _text_block(svg, rx + 12, row2 + 50, 70, [
            "No dark scan from this session, so there is no background curve to divide by.",
            "Run the dark threshold scan first, then this scan again on the same port, "
            "or regenerate this plot from both CSVs: the background-limited optimum needs both.",
        ], 11)

    _text_block(svg, 24, row2 + P + 62 + readout_h, 165, findings)
    return svg.render()


def _seconds(value: float) -> str:
    """0.39 s, 25.2 s, 1001 s -- never '0 s' for a short run nor '1e+03 s' for a long one."""
    return f"{value:.0f} s" if value >= 100 else f"{value:.3g} s"


def _dark_findings(result: dict) -> list:
    out = []
    rows = result["rows"]
    if rows:
        out.append(f"Scanned {len(rows)} thresholds, {rows[0]['abs_v'] * 1e3:.1f} to {rows[-1]['abs_v'] * 1e3:.1f} mV; "
                   f"{sum(r['counts'] for r in rows)} counts in {_seconds(sum(r['live_s'] for r in rows))} of live time.")
    edge = f"Noise edge (heuristic: log-slope < {NOISE_SLOPE_PER_MV} per mV over 1 mV): {_mv(result['noise_edge_v'])}."
    if result["lower_bound_v"] is not None:
        edge += f"  Lower bound for the operating threshold: {_mv(result['lower_bound_v'])} (noise edge + 0.5 mV)."
    else:
        edge += "  NO lower bound is given" + (": the scan is invalid." if not result["valid"] else ".")
    out.append(("" if result["valid"] else "!") + edge)
    if result["vanish_v"] is not None:
        out.append(f"Dark counts vanish (zero counts in {DARK_MAX_SECONDS:g} s) from {_mv(result['vanish_v'])}. "
                   f"Do NOT operate there: it is above most single-PE pulses, so it throws signal away. "
                   f"The light threshold scan measures how much.")
    elif rows:
        out.append(f"Dark counts never reached zero in the scanned range (to {rows[-1]['abs_v'] * 1e3:.1f} mV).")
    for reason in result["reasons"]:
        out.append("!" + reason)
    return out


def _loss_lines(result: dict) -> list:
    """One line per loss level, with its uncertainty and GUI value, or why it is not given."""
    out = []
    ref = result.get("reference_v")
    for loss in LOSS_LEVELS:
        detail = (result.get("loss_detail") or {}).get(loss)
        if detail is None:
            out.append(f"{_pct(loss)} count loss: not reached in the scanned range.")
        elif not detail["separable"]:
            out.append(f"{_pct(loss)} count loss: NOT SEPARABLE from the reference {_mv(ref)} "
                       f"(+-{detail['sigma_mv']:.2f} mV at {result['counts_per_level']:.2g} counts "
                       f"per level; needs ~{detail['counts_needed']:.1g}).")
        else:
            out.append(f"{_pct(loss)} count loss at {detail['settable_v'] * 1e3:.1f} +- "
                       f"{detail['sigma_mv']:.1f} mV (GUI {_gui_volts(detail['settable_v'])}).")
    return out


def _light_findings(result: dict, dark: dict | None) -> list:
    out = []
    if result["valley_v"] is not None:
        out.append(f"Valley {_mv(result['valley_v'])}, single-PE peak {_mv(result['peak_v'])}, peak/valley {result['pv_ratio']:.2f}.  "
                   f"Rate at the reference level {_mv(result['reference_v'])}: {result['plateau_rate']:.4g} counts/s.")
    # The loss levels themselves are in the readout box under panel (c), once. Under drift
    # they are not to be trusted, and that must be said where they are not.
    if result["loss_v"] and result["drift_flagged"]:
        out.append("!UNRELIABLE under drift -- the count-loss levels in the box above.")
    out.append(f"Noise edge {_mv(result['noise_edge_v'])}" + (" (from this session's dark scan)." if dark else
               " (from this scan alone -- judged only against this light level)."))
    if result["drift"] is not None:
        line = (f"Drift: {result['drift']:.2%} trend over the scan, {result.get('unsteadiness', 0.0):.2%} left after removing it "
                f"(tolerance {DRIFT_TOLERANCE:.0%}).")
        out.append(("!" if result["drift_flagged"] else "") + line)
    if result["hysteresis_v"] is not None:
        line = (f"Hysteresis: up-minus-down shift {result['hysteresis_v'] * 1e3:+.3f} +- "
                f"{result['hysteresis_se_v'] * 1e3:.3f} mV on the shoulder.")
        if result["hysteresis_flagged"]:
            line += " Set the operating level from the same direction every time."
        out.append(("!" if result["hysteresis_flagged"] else "") + line)
    if result["dark_vanish_loss"] is not None and dark:
        out.append(f"Where dark counts vanished ({_mv(dark['vanish_v'])}) this scan counts "
                   f"{result['dark_vanish_loss']:.1%} fewer photons than at the reference level.")
    if result["optimum_band_v"]:
        lo, hi = result["optimum_band_v"]
        out.append(f"S/sqrt(B) is within {1 - FOM_BAND:.0%} of its best from {_mv(lo)} to {_mv(hi)}. "
                   f"Assumes a weak, background-limited signal; for a bright one the optimum moves down.")
    for reason in result["reasons"]:
        out.append("!" + reason)
    if result["recommended_v"] is not None and result["recommended_v"] < PICKUP_SAFE_V:
        out.append("Below 10 mV: valid only with the cables exactly as they were for this scan (manual p. 22).")
    return out


def _scan_files(report, meta: dict, records: list, draw) -> dict:
    """The CSV always; the SVG unless drawing fails, in which case the report says why.

    The CSV is the record and is written first and unconditionally. A plotting bug must never
    cost the data, and if it happens the plot can be regenerated from the CSV once fixed.
    """
    files = {".csv": scan_csv(meta, records)}
    try:
        files[".svg"] = draw(meta)
    except Exception as exc:  # noqa: BLE001 -- the data matters more than the picture
        report.note(f"PLOT NOT WRITTEN ({type(exc).__name__}: {exc}). The data is in the CSV; "
                    f"regenerate with: python selftest.py plot <that .csv>")
    return files


def plot_csv(path: str) -> str:
    """Regenerate a scan's SVG from its CSV alone. Returns the path written."""
    meta, data = read_scan_csv(path)
    if meta.get("kind") == "settle":
        svg = plot_settle(analyse_settle(data), meta)
    elif meta.get("kind") == "dark":
        svg = plot_dark(analyse_dark(data), meta)
    else:
        dark = None
        folder = os.path.dirname(os.path.abspath(path))
        dark_path = os.path.join(folder, meta["dark_csv"]) if meta.get("dark_csv") else None
        if dark_path is None or not os.path.exists(dark_path):
            # A light scan recorded without its dark scan (as before the driver loaded it from
            # disk) can still be drawn with one: the newest same-port dark CSV beside it that
            # is not later than the light scan.
            found = None
            for name in sorted(os.listdir(folder), reverse=True):
                if not (name.endswith(".csv") and "dark" in name):
                    continue
                try:
                    dmeta, _ = read_scan_csv(os.path.join(folder, name))
                except Exception:  # noqa: BLE001
                    continue
                if (dmeta.get("kind") == "dark" and dmeta.get("port") == meta.get("port")
                        and dmeta.get("hv_V", "") == meta.get("hv_V", "")
                        and dmeta.get("when", "") <= meta.get("when", "")):
                    found = name
                    break
            if found:
                dark_path = os.path.join(folder, found)
                meta = dict(meta, dark_csv=f"{found} (found beside this file)")
        if dark_path and os.path.exists(dark_path):
            _, dark_points = read_scan_csv(dark_path)
            dark = analyse_dark(dark_points)
        svg = plot_light(analyse_light(data, dark), data, dark, meta)
    out = os.path.splitext(path)[0] + ".svg"
    with open(out, "w", encoding="utf-8") as handle:
        handle.write(svg)
    return out


# ----------------------------------------------------------------- settling check

# How the dark rate is judged settled, after an HV change or light exposure. Rather than a fixed
# wait, the rate at the operating threshold is counted in blocks, and a straight line is fitted
# (weighted by Poisson) through the blocks of the last 5 minutes. Settled means that slope is
# consistent with zero, within 2 sigma. A block lasts at least 60 s, and longer until it holds
# 1000 counts, but at most 3 min.
#
# Why a slope and not block-to-block agreement: on the bench (2026-11-10, simulated 15-min
# transient) blocks of 1000 counts lasted 15 s at 69 cps, each differed from the last by 1.4 %,
# well inside any tolerance, and "settled" was declared while the rate was still falling 6 % per
# minute. A comparison only sees drift that is fast relative to its own window; the 5-minute fit
# sees what a 10-minute dark scan would suffer.
#
# The resolution is set by counting statistics: at a few cps the check can only resolve drifts of
# a few % per minute, and it says so. Below SETTLE_MIN_COUNTS in a window it cannot judge at all,
# and says that instead of NOT SETTLED. PROVISIONAL: no real settling curve of this tube has been
# measured yet.
SETTLE_BLOCK_COUNTS = 1000
SETTLE_BLOCK_MIN_SECONDS = 60.0
SETTLE_BLOCK_MAX_SECONDS = 180.0
SETTLE_WINDOW_SECONDS = 300.0
SETTLE_MAX_SECONDS = 1800.0
SETTLE_DRIFT_TARGET = 0.005  # per minute: 5 % over a 10-minute dark scan
SETTLE_MIN_COUNTS = 100      # in a 5-minute window; fewer and a slope is mostly noise
SETTLE_DEFAULT_V = 0.0058  # if the GUI level is outside 2-40 mV: the first real lower bound

PROMPT_SETTLE = (
    "SR400 dark settling check.\n\n"
    "1. Cover the R8486 and make sure NO light can reach it.\n"
    "2. Set the PMT high voltage, and enter the same value in the GUI field "
    "'PMT high voltage in V' so the records carry it.\n\n"
    "The driver then counts dark pulses at the operating threshold until the rate stops "
    "changing (at most 30 minutes), and reports how long it took. Progress is in the debug log.\n\n"
    "Press OK when the tube is covered."
)


def _settle_slope(rows: list):
    """Weighted straight line rate(t): (relative slope per min, its sigma, mean rate), or None."""
    # A zero-count block is a measurement too: it gets the uncertainty of one count, not dropped.
    pts = [(r["t"] / 60.0, r["rate"], _math.sqrt(max(r["counts"], 1)) / r["live_s"])
           for r in rows if "t" in r and r["live_s"] > 0]
    if len(pts) < 3:
        return None
    w = [1.0 / sig ** 2 for _, _, sig in pts]
    sw = sum(w)
    tm = sum(wi * t for wi, (t, _, _) in zip(w, pts)) / sw
    rm = sum(wi * r for wi, (_, r, _) in zip(w, pts)) / sw
    stt = sum(wi * (t - tm) ** 2 for wi, (t, _, _) in zip(w, pts))
    if stt <= 0 or rm <= 0:
        return None
    slope = sum(wi * (t - tm) * (r - rm) for wi, (t, r, _) in zip(w, pts)) / stt
    return slope / rm, (1.0 / _math.sqrt(stt)) / rm, rm


def analyse_settle(blocks: list) -> dict:
    """Pure analysis of the settling blocks: when the 5-minute slope became consistent with zero."""
    rows = [_rate_row(b) for b in blocks]
    result = {"rows": rows, "settled": False, "settled_after_s": None, "settled_rate": None,
              "trend": None, "drift_per_min": None, "drift_sigma_per_min": None,
              "resolution_per_min": None, "judgeable": False}
    for i, row in enumerate(rows):
        if "t" not in row:
            continue
        # Back from this block until the window spans 5 minutes AND holds 3 blocks: with 3-minute
        # blocks a 5-minute window alone would hold two, and two points have no slope to test.
        window, enough = [], False
        for r in reversed(rows[: i + 1]):
            window.insert(0, r)
            span = row["t"] - (window[0]["t"] - window[0]["live_s"])
            if span >= SETTLE_WINDOW_SECONDS - 1e-6 and len(window) >= 3:
                enough = True
                break
        if not enough or sum(r["counts"] for r in window) < SETTLE_MIN_COUNTS:
            continue
        result["judgeable"] = True
        fit = _settle_slope(window)
        if fit is None:
            continue
        drift, sigma, mean = fit
        row["drift"], row["drift_sigma"] = drift, sigma
        if abs(drift) <= 2.0 * sigma:
            result.update(settled=True, settled_after_s=row["t"], settled_rate=mean,
                          drift_per_min=drift, drift_sigma_per_min=sigma,
                          resolution_per_min=2.0 * sigma, settled_index=i)
            break
        result.update(drift_per_min=drift, drift_sigma_per_min=sigma, resolution_per_min=2.0 * sigma)
    if len(rows) >= 2 and rows[0]["rate"] > 0:
        result["trend"] = rows[-1]["rate"] / rows[0]["rate"] - 1.0
    return result


def run_dark_settling(device) -> tuple:
    report = Report(device, "dark settling check")
    saved = _save_settings(device, SAVED_SETTINGS)
    stamp = _timestamp()
    blocks, extras, result = [], {}, None
    level = abs(device.discriminator_levels.get("A", -SETTLE_DEFAULT_V))
    if not 0.002 <= level <= 0.040:
        report.note(f"The GUI's Discriminator A level ({level * 1e3:.1f} mV) is outside 2-40 mV, "
                    f"so the check uses {SETTLE_DEFAULT_V * 1e3:.1f} mV instead.")
        level = SETTLE_DEFAULT_V
    level = round(level / 0.0002) * 0.0002
    try:
        report.section("conditions -- covered R8486, at the operating threshold")
        _scan_conditions_note(report)
        report.note(
            f"Counts at -{level * 1e3:.1f} mV in blocks of at least {SETTLE_BLOCK_MIN_SECONDS:g} s and "
            f"{SETTLE_BLOCK_COUNTS} counts (at most {SETTLE_BLOCK_MAX_SECONDS:g} s), until a straight line "
            f"through the last {SETTLE_WINDOW_SECONDS / 60:g} min has a slope consistent with zero; gives "
            f"up after {SETTLE_MAX_SECONDS / 60:g} min.",
        )
        _scan_setup(device)
        report.section("blocks, in time order")
        started = time.monotonic()
        live_total = 0.0
        _progress(f"dark settling check at -{level * 1e3:.1f} mV, PMT HV "
                  f"{_hv_text(device) or 'not recorded'}: blocks of at least {SETTLE_BLOCK_MIN_SECONDS:g} s "
                  f"until the {SETTLE_WINDOW_SECONDS / 60:g}-min drift is consistent with zero, "
                  f"at most {SETTLE_MAX_SECONDS / 60:g} min.")
        while True:
            point = _measure_point(device, level, SETTLE_BLOCK_COUNTS, SETTLE_BLOCK_MAX_SECONDS,
                                   min_seconds=SETTLE_BLOCK_MIN_SECONDS)
            point["block"] = len(blocks) + 1
            live_total += point["live_s"]
            # Elapsed time is wall time, but never less than the time spent counting: the two agree
            # on hardware, and a simulator that compresses wall time still gets a true clock.
            point["t"] = max(time.monotonic() - started, live_total)
            blocks.append(point)
            result = analyse_settle(blocks)
            last = result["rows"][-1]
            change = (f", drift over the last {SETTLE_WINDOW_SECONDS / 60:g} min "
                      f"{last['drift']:+.2%} +- {last['drift_sigma']:.2%} per min"
                      if "drift" in last else f", {SETTLE_WINDOW_SECONDS / 60:g} min of blocks not yet collected")
            _progress(f"dark settling: block {len(blocks)}: {point['counts']} counts in "
                      f"{point['live_s']:.1f} s = {last['rate']:.4g} cps{change}. "
                      f"Elapsed {_minutes(point['t'])}.")
            if result["settled"] or point["t"] >= SETTLE_MAX_SECONDS:
                break

        report.table([(f"block {r['block']}", f"{r['counts']} counts in {r['live_s']:.1f} s = "
                       f"{r['rate']:.4g} +- {r['sigma']:.2g} cps at {_minutes(r['t'])}"
                       + (f", 5-min drift {r['drift']:+.2%} +- {r['drift_sigma']:.2%}/min" if "drift" in r else ""))
                      for r in result["rows"]], ("block", "counts, rate, elapsed, 5-min drift"))
        report.section("findings")
        if result["settled"]:
            report.check(True, f"the dark rate settled after {_minutes(result['settled_after_s'])}, "
                               f"at {result['settled_rate']:.4g} cps")
            resolution = result["resolution_per_min"]
            coarse = resolution > SETTLE_DRIFT_TARGET
            report.headline = (f"settled after {_minutes(result['settled_after_s'])} at "
                               f"{result['settled_rate']:.4g} cps (-{level * 1e3:.1f} mV, PMT HV "
                               f"{_hv_text(device) or 'not recorded'})"
                               + (f"; resolves drift only above {resolution:.1%}/min" if coarse else ""))
            report.note(f"Drift over the last {SETTLE_WINDOW_SECONDS / 60:g} min: "
                        f"{result['drift_per_min']:+.2%} +- {result['drift_sigma_per_min']:.2%} per minute, "
                        f"consistent with zero. A drift slower than about {resolution:.1%} per minute would "
                        f"also have passed (over a ~10 min dark scan, up to {10 * resolution:.0%})"
                        + (f", which is coarser than the {SETTLE_DRIFT_TARGET:.1%}/min this check aims for: "
                           f"the count rate at this threshold is too low to resolve it in "
                           f"{SETTLE_WINDOW_SECONDS / 60:g} min." if coarse else "."))
            report.values["settle_minutes"] = round(result["settled_after_s"] / 60.0, 2)
            report.values["settled_rate_cps"] = round(result["settled_rate"], 4)
        elif not result["judgeable"]:
            total = sum(r["counts"] for r in result["rows"])
            report.note(f"Only {total} counts in {_minutes(blocks[-1]['t'])} at -{level * 1e3:.1f} mV: too few "
                        f"to fit a drift (a {SETTLE_WINDOW_SECONDS / 60:g}-min window needs "
                        f"{SETTLE_MIN_COUNTS}). Settling is unknown, not refuted.")
            report.headline = (f"CANNOT JUDGE settling: only {total} counts at -{level * 1e3:.1f} mV in "
                               f"{_minutes(blocks[-1]['t'])}. Use a lower operating threshold for the check, "
                               f"or accept that settling is unknown.")
        else:
            trend = (f"still drifting {result['drift_per_min']:+.1%} +- {result['drift_sigma_per_min']:.1%} per min"
                     if result["drift_per_min"] is not None else
                     f"{result['trend']:+.0%} from the first block to the last" if result["trend"] is not None else "")
            report.check(False, f"the dark rate settled within {SETTLE_MAX_SECONDS / 60:g} min ({trend})")
            report.headline = (f"NOT SETTLED within {SETTLE_MAX_SECONDS / 60:g} min ({trend}). The dark "
                               f"scan that follows will carry the drift.")
        extras = _scan_files(report, _scan_meta(device, "settle", stamp), blocks,
                             lambda meta: plot_settle(result, meta))
    finally:
        device.reset_counters()
        failed = _restore_settings(device, SAVED_SETTINGS, saved)
        report.section("restore")
        report.check(not failed, f"every changed setting was restored (unrestored: {failed or 'none'})")
    return report, report.write(stamp, extras)


def plot_settle(result: dict, meta: dict) -> str:
    """Rate per block against time, with the settled rate, so the transient can be seen."""
    rows = result["rows"]
    W, P = 1200, 360
    svg = _Svg(W, 150 + P + 140)
    svg.text(24, 30, "SR400 dark settling check -- covered R8486 on SIGNAL INPUT 1, discriminator A, FALL",
             17, weight="bold")
    if meta.get("note"):
        svg.text(W - 24, 30, meta["note"], 14, "end", weight="bold", color="#c0392b")
    level = f"-{float(rows[0]['abs_v']) * 1e3:.1f} mV" if rows else "?"
    svg.text(24, 50, f"{meta.get('when', '')}   port {meta.get('port', '')} ({meta.get('interface', '')})   "
                     f"PMT HV {_meta_hv(meta)}   threshold {level}   raw counts and live time per block",
             11, color="#555")
    if result["settled"]:
        head = (f"+SETTLED after {_minutes(result['settled_after_s'])}, at {result['settled_rate']:.4g} counts/s: "
                f"drift over the last {SETTLE_WINDOW_SECONDS / 60:g} min {result['drift_per_min']:+.2%} +- "
                f"{result['drift_sigma_per_min']:.2%}/min, consistent with zero. Drifts below "
                f"~{result['resolution_per_min']:.1%}/min are not resolved at this count rate.")
    elif not result.get("judgeable"):
        head = (f"!CANNOT JUDGE: too few counts ({sum(r['counts'] for r in rows)}) to fit a drift; "
                f"settling is unknown, not refuted.")
    else:
        head = ("!NOT SETTLED within " + f"{SETTLE_MAX_SECONDS / 60:g} min"
                + (f": still drifting {result['drift_per_min']:+.2%} +- {result['drift_sigma_per_min']:.2%}/min."
                   if result["drift_per_min"] is not None else "."))
    _text_block(svg, 24, 76, 165, [head], 13)
    if not rows:
        return svg.render()
    tmax = max(r["t"] for r in rows) / 60.0
    rates = [r["rate"] for r in rows if r["rate"] > 0]
    a = _Panel(svg, 90, 120, 1000, P, (0.0, tmax * 1.05 + 0.1),
               (min(rates, default=0.1) * 0.8, max(rates, default=1.0) * 1.25))
    a.frame("dark count rate per block, +-1 sigma Poisson", "time since the check started, min",
            "rate, counts/s")
    xs = [r["t"] / 60.0 for r in rows]
    a.errorbars(xs, [r["rate"] for r in rows], [r["sigma"] for r in rows], "#1f77b4")
    a.series(xs, [r["rate"] for r in rows], "#1f77b4", "o", width=1.0)
    if result["settled"]:
        a.hline(result["settled_rate"], _C["bound"], f"settled {result['settled_rate']:.4g} counts/s", "5,3")
        a.vline(result["settled_after_s"] / 60.0, _C["bound"], f"settled at {_minutes(result['settled_after_s'])}", None, 0)
    _text_block(svg, 24, 120 + P + 62, 165, [
        f"{len(rows)} blocks, each at least {SETTLE_BLOCK_MIN_SECONDS:g} s and until {SETTLE_BLOCK_COUNTS} counts "
        f"(at most {SETTLE_BLOCK_MAX_SECONDS:g} s). After each block a straight line, weighted by Poisson, is "
        f"fitted through the last {SETTLE_WINDOW_SECONDS / 60:g} min; settled means its slope is within 2 sigma of zero.",
        "The criterion is provisional: the first real settling curve of this tube decides whether it is sensible.",
    ], 11)
    return svg.render()


# ------------------------------------------------------------------ dark action

def run_threshold_scan_dark(device) -> tuple:
    report = Report(device, "threshold scan dark")
    saved = _save_settings(device, SAVED_SETTINGS)
    stamp = _timestamp()
    points = []
    extras = {}
    result = None
    try:
        report.section("conditions -- covered R8486")
        _scan_conditions_note(report)
        report.note(
            f"Target {DARK_TARGET_COUNTS} counts per threshold (~"
            f"{100 / _math.sqrt(DARK_TARGET_COUNTS):.0f} % Poisson), at most "
            f"{DARK_MAX_SECONDS:g} s each. Stops after {DARK_STOP_AFTER} thresholds in a "
            f"row below {DARK_STOP_BELOW_CPS:g} cps.",
        )
        _scan_setup(device)

        report.section("scan, low to high |level|")
        low_in_a_row = 0
        started = time.monotonic()
        _progress(
            f"dark scan: {len(threshold_grid())} thresholds, up to {DARK_MAX_SECONDS:g} s each, "
            f"so at most {_minutes(len(threshold_grid()) * DARK_MAX_SECONDS)}. It usually stops "
            f"sooner, after {DARK_STOP_AFTER} thresholds in a row below {DARK_STOP_BELOW_CPS:g} cps.",
        )
        leak_checked = False
        grid = threshold_grid()
        coarse = False
        slow_in_a_row = 0
        for index, abs_v in enumerate(grid):
            if coarse and abs_v < points[-1]["abs_v"] + DARK_COARSE_STEP_V - 1e-9:
                continue  # in the tail: 2 mV steps, not the fine grid
            point = _measure_point(device, abs_v, DARK_TARGET_COUNTS, DARK_MAX_SECONDS,
                                   DARK_FAST_TARGET_COUNTS, DARK_FAST_SECONDS)
            points.append(point)
            rate = point["counts"] / point["live_s"]
            peak_rate = max(p["counts"] / p["live_s"] for p in points)
            slow_in_a_row = slow_in_a_row + 1 if rate < DARK_COARSE_BELOW_CPS < peak_rate else 0
            if not coarse and slow_in_a_row >= 2:
                coarse = True
                report.note(f"from {abs_v * 1e3:.1f} mV: below {DARK_COARSE_BELOW_CPS:g} cps at two "
                            f"thresholds in a row, so {DARK_COARSE_STEP_V * 1e3:g} mV steps from here.")
                _progress(f"dark scan: below {DARK_COARSE_BELOW_CPS:g} cps twice in a row at "
                          f"-{abs_v * 1e3:.1f} mV; {DARK_COARSE_STEP_V * 1e3:g} mV steps from here.")
            elapsed = time.monotonic() - started
            if coarse:
                steps_left = int((grid[-1] - abs_v) / DARK_COARSE_STEP_V + 1e-9)
            else:
                steps_left = len(grid) - index - 1
            left = steps_left * DARK_MAX_SECONDS
            _progress(
                f"dark scan: {index + 1}/{len(grid)} at -{abs_v * 1e3:.1f} mV: "
                f"{point['counts']} counts in {point['live_s']:.1f} s "
                f"({point['counts'] / point['live_s']:.4g} cps). Elapsed {_minutes(elapsed)}, "
                f"at most {_minutes(left)} left.",
            )

            if index == 0 and point["counts"] == 0:
                break  # nothing on the input at all; analyse_dark says so

            if not leak_checked and abs_v >= PICKUP_SAFE_V - 1e-9:
                leak_checked = True
                if point["counts"] / point["live_s"] > DARK_RATE_CEILING_CPS:
                    report.note("STOPPED at 10 mV: far too many counts for a covered tube.")
                    break

            # Past the noise peak only: the rate there is far above the limit in any case.
            low_in_a_row = low_in_a_row + 1 if rate < DARK_STOP_BELOW_CPS < peak_rate else 0
            if low_in_a_row >= DARK_STOP_AFTER:
                line = (f"stopped at {abs_v * 1e3:.1f} mV: {low_in_a_row} thresholds in a row below "
                        f"{DARK_STOP_BELOW_CPS:g} cps, so the scan is in the dark tail, which sets "
                        f"no bound. Where dark counts vanish entirely is not measured.")
                report.note(line)
                _progress(f"dark scan: {line}")
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
                        f"(noise edge + 0.5 mV). In the GUI: 'Discriminator A level in V' no less "
                        f"negative than {_gui_volts(result['lower_bound_v'])}.")
            if result["lower_bound_v"] < PICKUP_SAFE_V:
                report.note("That is below 10 mV, where the manual warns of DISC pickup. This "
                            "scan shows whether it happened in THIS cabling; keep the cables "
                            "where they are.")
        for reason in result["reasons"]:
            report.note(reason)
        report.note(
            "Do NOT choose the level where dark counts vanish. It is above most single-PE "
            "pulses too, so it throws signal away. Run the light threshold scan to measure "
            "how much: its report gives the loss at that level, and the upper bound.",
        )

        if result["valid"] and result["lower_bound_v"] is not None:
            report.values["lower_bound_V"] = _gui_volts(result["lower_bound_v"])
            report.values["dark_counts_vanish_V"] = _gui_volts(result["vanish_v"])
        report.headline = (
            f"lower bound {_mv(result['lower_bound_v'])} (GUI {_gui_volts(result['lower_bound_v'])}), "
            f"dark counts vanish from "
            f"{_mv(result['vanish_v'])}" if result["valid"] and result["lower_bound_v"] is not None
            else "no lower bound: " + ("; ".join(result["reasons"]) or "see the report")
        )
        extras = _scan_files(report, _scan_meta(device, "dark", stamp), points,
                             lambda meta: plot_dark(result, meta))
    finally:
        device.reset_counters()
        failed = _restore_settings(device, SAVED_SETTINGS, saved)
        report.section("restore")
        report.check(not failed, f"every changed setting was restored (unrestored: {failed or 'none'})")
        report.note("No storage slot was used; ST, RC and SE were never sent.")

    path = report.write(stamp, extras)
    if result is not None and result["valid"]:
        # Kept for the light scan in this session, with its CSV so the light scan's own CSV can
        # name it, and a regenerated light plot can find the background curve again.
        result["csv"] = report.extra_paths.get(".csv")
        result["hv_V"] = _hv_text(device)
        device._dark_threshold_scan = result
    return report, path


# ----------------------------------------------------------------- light action

DARK_FILE_WARN_HOURS = 24.0  # an older dark scan is used, but flagged: HV, cabling or temperature may differ


def _latest_dark_scan_on_disk(device, report):
    """The newest valid dark scan on disk for this port, re-analysed by this code; None if there is none.

    Reported 2026-11-10: the light scan ran without its dark scan, so panel (d) was empty,
    because the dark result lived only in memory and a SweepMe! restart (as after updating the
    driver) loses it. The dark scan's CSV holds every raw count, so it is read back and
    re-analysed with the current analysis, never trusted from an older driver's report. Only a
    scan from the same port is used, the newest first, and the report says which file it was
    and how old.
    """
    driver = os.path.basename(os.path.dirname(os.path.abspath(__file__)))
    candidates = []
    for identifier in ("DATADEVICES", "TEMP"):
        try:
            folder = device.get_folder(identifier)
        except Exception:  # noqa: BLE001 -- not every location exists everywhere
            continue
        if identifier == "DATADEVICES":
            folder = os.path.join(folder, driver)
        if not os.path.isdir(folder):
            continue
        candidates.extend(os.path.join(folder, name) for name in os.listdir(folder)
                          if name.startswith("SR400_threshold_scan_dark_") and name.endswith(".csv"))

    # The file name carries the timestamp (YYYY-MM-DD_HHMMSS), so name order is time order;
    # modification times change when files are copied, the names do not.
    for candidate in sorted(candidates, key=os.path.basename, reverse=True):
        try:
            meta, points = read_scan_csv(candidate)
        except Exception:  # noqa: BLE001 -- an unreadable file is skipped, not fatal
            continue
        if meta.get("kind") != "dark" or meta.get("port") != device.port_string:
            continue
        if meta.get("hv_V", "") != _hv_text(device):
            continue  # another HV, another gain: never the background for this light scan
        result = analyse_dark(points)
        if not result["valid"]:
            continue
        result["csv"] = candidate
        result["hv_V"] = meta.get("hv_V", "")
        age = None
        try:
            age = (time.time() - time.mktime(time.strptime(meta.get("when", ""), "%Y-%m-%d %H:%M:%S"))) / 3600.0
        except (ValueError, OverflowError):
            pass
        line = (f"Dark scan: none in memory, so loaded {os.path.basename(candidate)} from disk "
                f"(taken {meta.get('when', 'at an unknown time')}"
                + (f", {age:.1f} h ago" if age is not None else "") + ") and re-analysed.")
        report.note(line)
        _progress(f"light scan: {line}")
        if age is not None and age > DARK_FILE_WARN_HOURS:
            report.note(f"That dark scan is over {DARK_FILE_WARN_HOURS:g} h old. If the HV, the "
                        f"cabling or the temperature changed since, run the dark scan again.")
        return result
    return None

def run_threshold_scan_light(device) -> tuple:
    report = Report(device, "threshold scan light")
    saved = _save_settings(device, SAVED_SETTINGS)
    stamp = _timestamp()
    passes = []
    extras = {}
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
        if dark is not None and dark.get("hv_V", "") != _hv_text(device):
            # A dark scan at another HV has another gain: pairing them would score this light
            # against the wrong background. Measured risk once HVs are being compared.
            report.note(f"The dark scan in memory was taken at PMT HV {dark.get('hv_V') or 'not recorded'}, "
                        f"this light scan at {_hv_text(device) or 'not recorded'}: not used.")
            dark = None
        if dark is None:
            dark = _latest_dark_scan_on_disk(device, report)
        dark_at = _value_at(dark["rows"], 0.006)["rate"] if dark else None
        report.note(f"{probe['counts']} counts in {probe['live_s']:.3f} s at 6.0 mV = "
                    f"{probe_rate:.4g} cps" + (f" (dark scan: {dark_at:.4g} cps)" if dark_at else ""))
        floor = max(LIGHT_FLOOR_CPS, 20.0 * dark_at) if dark_at else LIGHT_FLOOR_CPS
        if probe_rate < floor:
            report.check(False, f"there is light on the PMT ({probe_rate:.4g} cps, need >= {floor:.4g})")
            report.headline = (f"no usable light: {probe_rate:.4g} cps at 6 mV. Ensure gentle "
                               f"light on the PMT and run it again")
            raise _StopScan
        if probe_rate > LIGHT_CEILING_CPS:
            report.check(False, f"the light is gentle ({probe_rate:.4g} cps, limit {LIGHT_CEILING_CPS:.0e})")
            report.headline = (f"too bright: {probe_rate:.4g} cps at 6 mV. Dead-time losses "
                               f"would bend the curve; reduce to 1e4-1e5 cps and run it again")
            raise _StopScan
        report.check(True, f"there is light, and it is gentle enough ({probe_rate:.4g} cps)")
        if probe_rate > LIGHT_WARN_CPS:
            report.note(f"Above {LIGHT_WARN_CPS:.0e} cps: dead-time loss is no longer negligible "
                        f"at the 1 % level this scan resolves. Dimmer is better.")

        grid = threshold_grid()
        started = time.monotonic()
        total_passes = 2 * LIGHT_REPEATS
        _progress(
            f"light scan: {total_passes} passes over up to {len(grid)} thresholds, up to "
            f"{LIGHT_MAX_SECONDS:g} s each. The first pass usually shortens the grid.",
        )
        for repeat in range(1, LIGHT_REPEATS + 1):
            for direction in ("up", "down"):
                report.section(f"repeat {repeat}, {direction}")
                levels = grid if direction == "up" else list(reversed(grid))
                points = []
                pass_number = 2 * (repeat - 1) + (1 if direction == "up" else 2)
                for step, abs_v in enumerate(levels):
                    point = _measure_point(device, abs_v, LIGHT_TARGET_COUNTS, LIGHT_MAX_SECONDS)
                    points.append(point)
                    elapsed = time.monotonic() - started
                    left = ((len(levels) - step - 1) + (total_passes - pass_number) * len(grid)) \
                        * LIGHT_MAX_SECONDS
                    _progress(
                        f"light scan: pass {pass_number}/{total_passes} ({direction}), "
                        f"{step + 1}/{len(levels)} at -{abs_v * 1e3:.1f} mV: "
                        f"{point['counts']} counts in {point['live_s']:.2f} s "
                        f"({point['counts'] / point['live_s']:.4g} cps). Elapsed "
                        f"{_minutes(elapsed)}, at most {_minutes(left)} left.",
                    )
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
        for line in _loss_lines(result):
            report.note(line)

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
                f"B = the dark rate at that level from a local Poisson fit to the dark scan over "
                f"+-{DARK_SMOOTH_HALF_WIDTH_V * 1e3:g} mV (wider where the grid is coarse), so one "
                f"threshold's counting noise does not set the score. Levels whose window holds fewer "
                f"than {FOM_MIN_DARK_COUNTS} dark counts are not scored.",
            )
            report.table(
                [(f"{f['abs_v'] * 1e3:6.1f} mV",
                  f"photons vs ref {f['efficiency']:.3f}   dark {f['dark_rate']:.3g} +- "
                  f"{f.get('dark_sigma', 0):.0%} cps (fit to {f['dark_counts']} counts)   "
                  f"S/sqrt(B) {f['relative']:.3f} of best")
                 for f in result["fom"]],
                ("|level|", "photon fraction, dark rate, figure of merit"),
            )

        report.section("recommendation")
        for reason in result["reasons"]:
            report.note(reason)
        if result["recommended_v"] is not None:
            low, high = result["window_v"] or (None, None)
            report.note(f"RECOMMENDED A DISC LVL: -{result['recommended_v'] * 1e3:.1f} mV, FALL. "
                        f"In the GUI, type {_gui_volts(result['recommended_v'])} into "
                        f"'Discriminator A level in V' (the field is in volts).")
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
            report.values.update({
                "recommended_disc_A_level_V": _gui_volts(result["recommended_v"]),
                "photons_counted_at_recommended": round(1.0 - result["recommended_loss"], 4),
                # lower_bound_V stays the dark scan's column (noise edge + 0.5 mV); the light
                # scan's own noise edge is in its report, under the strict window.
                "upper_bound_1pct_loss_V": _gui_volts(high),
            })
            report.headline = (
                f"recommended A DISC LVL -{result['recommended_v'] * 1e3:.1f} mV "
                f"(type {_gui_volts(result['recommended_v'])} in the GUI), counting "
                f"{1.0 - result['recommended_loss']:.0%} of photons"
                + (f"; S/sqrt(B) within 5 % of best from {_mv(result['optimum_band_v'][0])} to "
                   f"{_mv(result['optimum_band_v'][1])}" if result["optimum_band_v"] else "")
                + ("; strict window empty -- preamp would help" if result["window_empty"] else "")
            )
        else:
            report.headline = "no recommendation: " + ("; ".join(result["reasons"]) or "see the report")

        records = [dict(p, repeat=ps["repeat"], direction=ps["direction"])
                   for ps in passes for p in ps["points"]]
        dark_csv = os.path.basename(dark["csv"]) if dark and dark.get("csv") else ""
        extras = _scan_files(report, _scan_meta(device, "light", stamp, dark_csv=dark_csv), records,
                             lambda meta: plot_light(result, passes, dark, meta))
    except _StopScan:
        pass  # refused at the probe: no sweep, so nothing to record or plot
    finally:
        device.reset_counters()
        failed = _restore_settings(device, SAVED_SETTINGS, saved)
        report.section("restore")
        report.check(not failed, f"every changed setting was restored (unrestored: {failed or 'none'})")
        report.note("No storage slot was used; ST, RC and SE were never sent.")

    return report, report.write(stamp, extras)


# ----------------------------------------------------------------- HV comparison

# Spread of the photon rate across all scans beyond which S/sqrt(B) is not compared. Each
# replicate's S/sqrt(B) is corrected for its own light level, so this only refuses a gross change
# (a moved source, a different filter), where proportionality itself is in doubt.
HV_LIGHT_CONSISTENCY = 0.5
HV_MIN_FOR_OPTIMUM = 3


def _smooth_dark_rate(dark_rows: list, abs_v: float):
    """(rate, relative sigma, counts in the window) of the dark rate at abs_v from a local fit, or None.

    rate(x) = exp(a + b x), x = level - abs_v, fitted to the thresholds within the window by Poisson
    maximum likelihood (Newton). The window starts at +-DARK_SMOOTH_HALF_WIDTH_V and widens until
    it holds 3 thresholds and FOM_MIN_DARK_COUNTS counts, up to +-4 mV.
    """
    half = DARK_SMOOTH_HALF_WIDTH_V
    while True:
        window = [r for r in dark_rows if abs(r["abs_v"] - abs_v) <= half + 1e-9 and r["live_s"] > 0]
        counts = sum(r["counts"] for r in window)
        if (len(window) >= 3 and counts >= FOM_MIN_DARK_COUNTS) or half >= 0.004 - 1e-9:
            break
        half += 0.001
    if len(window) < 2 or counts < FOM_MIN_DARK_COUNTS:
        return None
    xs = [(r["abs_v"] - abs_v) * 1e3 for r in window]  # mV
    a = _math.log(counts / sum(r["live_s"] for r in window))
    b = 0.0
    for _ in range(50):
        lam = [r["live_s"] * _math.exp(a + b * x) for r, x in zip(window, xs)]
        g0 = sum(r["counts"] - l for r, l in zip(window, lam))
        g1 = sum(x * (r["counts"] - l) for r, l, x in zip(window, lam, xs))
        h00 = sum(lam)
        h01 = sum(x * l for x, l in zip(xs, lam))
        h11 = sum(x * x * l for x, l in zip(xs, lam))
        det = h00 * h11 - h01 * h01
        if det <= 0:
            break
        da = (h11 * g0 - h01 * g1) / det
        db = (h00 * g1 - h01 * g0) / det
        a, b = a + da, max(min(b + db, 20.0), -20.0)
        if abs(da) < 1e-9 and abs(db) < 1e-9:
            break
    lam = [r["live_s"] * _math.exp(a + b * x) for r, x in zip(window, xs)]
    h00, h01, h11 = sum(lam), sum(x * l for x, l in zip(xs, lam)), sum(x * x * l for x, l in zip(xs, lam))
    det = h00 * h11 - h01 * h01
    sigma = _math.sqrt(h11 / det) if det > 0 else 1.0 / _math.sqrt(max(counts, 1))
    return _math.exp(a), sigma, counts


def _absolute_snr(light: dict, dark: dict):
    """Best (S - B)/sqrt(B) in sqrt(counts/s), and its level: comparable across HV for the same light."""
    best = None
    for row in light["rows"]:
        fit = _smooth_dark_rate(dark["rows"], row["abs_v"])
        if fit is None:
            continue
        snr = (row["rate"] - fit[0]) / _math.sqrt(fit[0])
        if best is None or snr > best[0]:
            best = (snr, row["abs_v"])
    return best


def _aggregate_hv(replicates: list) -> list:
    """One row per HV from its replicates: means, and the standard error of S/sqrt(B) when n >= 2."""
    rows = []
    for hv in sorted({r["hv"] for r in replicates}):
        mine = [r for r in replicates if r["hv"] == hv]
        good = [r for r in mine if not r["problem"]]
        if not good:
            rows.append({"hv": hv, "problem": "; ".join(sorted({r["problem"] for r in mine})),
                         "n": 0, "replicates": mine, "light_csv": ";".join(r["light_csv"] for r in mine)})
            continue

        def mean(key):
            vals = [r[key] for r in good if r.get(key) is not None]
            return sum(vals) / len(vals) if vals else None

        snrs = [r["snr_corrected"] for r in good if r.get("snr_corrected") is not None]
        se = None
        if len(snrs) >= 2:
            m = sum(snrs) / len(snrs)
            se = _math.sqrt(sum((x - m) ** 2 for x in snrs) / (len(snrs) - 1) / len(snrs))
        levels = [r["best_snr_v"] for r in good if r.get("best_snr_v") is not None]
        level = round(sum(levels) / len(levels) / 0.0002) * 0.0002 if levels else None
        first = good[0]
        rows.append({
            "hv": hv, "problem": "", "n": len(good), "replicates": mine,
            "valley_v": mean("valley_v"), "peak_v": mean("peak_v"), "pv": mean("pv"),
            "valley_rate": mean("valley_rate"), "photon_rate": mean("photon_rate"),
            "photon_rates": [r["photon_rate"] for r in good if r.get("photon_rate")],
            "half_peak_v": first["half_peak_v"], "dark_at_half": first["dark_at_half"],
            "lower_bound_v": first["lower_bound_v"], "recommended_v": mean("recommended_v"),
            "recommended_loss": mean("recommended_loss"),
            "best_snr": sum(snrs) / len(snrs) if snrs else None, "snr_se": se, "best_snr_v": level,
            "snr_photon_fraction": mean("snr_photon_fraction"),
            # Settling belongs to the dark scan the replicates share; any NOT SETTLED one counts.
            "settled": (False if any(r.get("settled") is False for r in good)
                        else True if any(r.get("settled") for r in good) else None),
            "settle_min": first.get("settle_min"),
            "light_csv": ";".join(r["light_csv"] for r in good), "dark_csv": first["dark_csv"],
            "settle_csv": first["settle_csv"],
        })
    return rows


def _hv_verdict(rows: list) -> tuple:
    """Pure: (verdict lines, optimum row or None, light consistent?) from per-HV rows.

    An optimum is named only when at least three HVs are comparable (valid, not NOT SETTLED), the
    photon rate at the valley agrees across them, and the best S/sqrt(B) lies strictly inside
    the range. The photon fraction counted at the optimum's level is given beside it, and a
    weak-signal optimum that throws most photons away says so.
    """
    usable = [r for r in rows if not r["problem"] and r.get("settled") is not False]
    verdict, optimum = [], None
    rates = [x for r in usable for x in (r.get("photon_rates") or ([r["photon_rate"]] if r.get("photon_rate") else []))]
    consistent = False
    if len(rates) >= 2:
        spread = (max(rates) - min(rates)) / sorted(rates)[len(rates) // 2]
        consistent = spread <= HV_LIGHT_CONSISTENCY
        verdict.append(("" if consistent else "!") + f"Photon rate (light minus dark) at the valley varies by "
                       f"{spread:.0%} across the scans (limit {HV_LIGHT_CONSISTENCY:.0%})" + ("." if consistent else
                       ": the light changed too much for a proportional correction to be trusted, so "
                       "S/sqrt(B) is NOT compared across HV."))
    for r in rows:
        if r["problem"]:
            verdict.append(f"!{r['hv']:g} V left out: {r['problem']}.")
        elif r.get("settled") is False:
            verdict.append(f"!{r['hv']:g} V left out: its dark rate had NOT SETTLED before the dark scan.")
        elif r.get("settled") is None:
            verdict.append(f"{r['hv']:g} V: no settling check that could judge, so settling is unknown.")
    scored = [r for r in usable if r.get("best_snr") is not None]
    if not consistent:
        pass
    elif len(scored) < HV_MIN_FOR_OPTIMUM:
        verdict.append(f"!NO OPTIMUM named: {len(scored)} comparable HVs, at least {HV_MIN_FOR_OPTIMUM} needed.")
    else:
        best = max(scored, key=lambda r: r["best_snr"])
        if best is scored[0] or best is scored[-1]:
            verdict.append(f"!NO OPTIMUM named: the best S/sqrt(B) is at the edge of the range scanned "
                           f"({best['hv']:g} V). Extend the range past it.")
        else:
            optimum = best
            runner = max((r for r in scored if r is not best), key=lambda r: r["best_snr"])
            if best.get("snr_se") is not None and runner.get("snr_se") is not None:
                gap = best["best_snr"] - runner["best_snr"]
                sigma = _math.sqrt(best["snr_se"] ** 2 + runner["snr_se"] ** 2)
                if gap < 2.0 * sigma:
                    verdict.append(f"!{best['hv']:g} V is NOT RESOLVED from {runner['hv']:g} V: the gap "
                                   f"{gap:.3g} is under twice its uncertainty ({sigma:.3g}). Either is as good, "
                                   f"on this evidence; more replicates would separate them.")
            else:
                verdict.append("Single scans at some HVs: no error bar, so whether the optimum beats its "
                               "neighbours is not known. Repeat each HV to find out.")
            kept = best.get("snr_photon_fraction")
            verdict.append(f"+OPTIMUM PMT HV {best['hv']:g} V: best S/sqrt(B) {best['best_snr']:.4g} "
                           f"at -{best['best_snr_v'] * 1e3:.1f} mV (GUI {_gui_volts(best['best_snr_v'])})"
                           + (f", counting {kept:.0%} of the photons there" if kept is not None else "") + ".")
            if kept is not None and kept < 0.5:
                verdict.append("!That optimum is for a weak, background-limited signal and throws away most "
                               "photons. For a bright signal, prefer the HV with the best peak/valley.")
    return verdict, optimum, consistent


def hv_compare(folder: str) -> tuple:
    """Compare threshold scans taken at several PMT HVs. Returns (csv_path, svg_path, lines).

    Every light-scan CSV with a recorded HV is paired with the newest same-port, same-HV dark
    scan not later than it, and with the newest such settling check. Each pair is re-analysed by
    this code. The optimum HV is named only if at least three HVs are comparable, the light level
    was the same at each, and the best S/sqrt(B) turns over inside the range scanned.
    """
    entries = []
    for name in sorted(os.listdir(folder)):
        if name.endswith(".csv"):
            try:
                meta, data = read_scan_csv(os.path.join(folder, name))
            except Exception:  # noqa: BLE001 -- not a scan record
                continue
            if meta.get("hv_V") and meta.get("kind") in ("dark", "light", "settle"):
                entries.append((meta, data, name))

    def newest(kind, port, hv, before):
        found = [e for e in entries if e[0]["kind"] == kind and e[0].get("port") == port
                 and e[0]["hv_V"] == hv and e[0].get("when", "") <= before]
        return max(found, key=lambda e: e[0].get("when", "")) if found else None

    replicates = []
    for meta, passes, name in sorted((e for e in entries if e[0]["kind"] == "light"),
                                     key=lambda e: e[0].get("when", "")):
        hv = meta["hv_V"]
        dark_e = newest("dark", meta.get("port"), hv, meta.get("when", ""))
        if dark_e is None:
            replicates.append({"hv": float(hv), "when": meta.get("when", ""), "problem": "no dark scan at this HV",
                               "light_csv": name})
            continue
        dark = analyse_dark(dark_e[1])
        light = analyse_light(passes, dark)
        settle_e = newest("settle", meta.get("port"), hv, dark_e[0].get("when", ""))
        settle = analyse_settle(settle_e[1]) if settle_e else None
        peak = light["peak_v"]
        half = round(0.5 * peak / 0.0002) * 0.0002 if peak else None
        dark_half = _value_at(dark["rows"], half)["rate"] if half else None
        # Photons at the valley: the light rate there less the dark (and noise) rate. At low HV
        # the valley sits in the noise, so the raw light rate there would not compare the light.
        photon_rate = None
        if light["valley_v"] is not None and light["plateau_rate"]:
            photon_rate = light["plateau_rate"] - _value_at(dark["rows"], light["valley_v"])["rate"]
        best = _absolute_snr(light, dark)
        snr_fraction = None
        if best and photon_rate:
            at = _value_at(light["rows"], best[1])["rate"] - _value_at(dark["rows"], best[1])["rate"]
            snr_fraction = at / photon_rate
        replicates.append({
            "hv": float(hv), "when": meta.get("when", ""),
            "problem": "" if light["valid"] and dark["valid"] else "; ".join(
                light["reasons"] + dark["reasons"]) or "invalid scan",
            "valley_v": light["valley_v"], "peak_v": peak, "pv": light["pv_ratio"],
            "valley_rate": light["plateau_rate"], "photon_rate": photon_rate,
            "half_peak_v": half, "dark_at_half": dark_half,
            "lower_bound_v": dark["lower_bound_v"], "recommended_v": light["recommended_v"],
            "recommended_loss": light["recommended_loss"],
            "best_snr": best[0] if best else None, "best_snr_v": best[1] if best else None,
            "snr_photon_fraction": snr_fraction,
            "settled": None if settle is None or not settle["judgeable"] else settle["settled"],
            "settle_min": (settle["settled_after_s"] / 60.0) if settle and settle["settled"] else None,
            "light_csv": name, "dark_csv": dark_e[2], "settle_csv": settle_e[2] if settle_e else "",
        })

    # Signal scales with the light, background does not: so S/sqrt(B) scales with the light, and
    # each replicate's value is brought to the median photon rate by that ratio. That corrects a
    # drifting or unsteady source exactly, as long as the signal is proportional to the light.
    # Interleaving the HVs over time (900, 950, 1000, 900, ...) is what makes the correction
    # checkable: a source drift then shows as a trend in time, not as a trend in HV.
    good_rates = sorted(r["photon_rate"] for r in replicates if not r["problem"] and r.get("photon_rate"))
    reference = good_rates[len(good_rates) // 2] if good_rates else None
    for r in replicates:
        r["snr_corrected"] = (r["best_snr"] * reference / r["photon_rate"]
                              if r.get("best_snr") is not None and r.get("photon_rate") and reference else None)

    rows = _aggregate_hv(replicates)
    verdict, optimum, consistent = _hv_verdict(rows)
    if reference:
        verdict.insert(1 if verdict else 0, f"S/sqrt(B) is corrected to a common light level, the median photon rate "
                       f"{reference:.4g} counts/s at the valley, replicate by replicate.")

    stamp = _timestamp().replace(":", "").replace(" ", "_")
    columns = ("hv_V", "n_replicates", "valley_mV", "spe_peak_mV", "peak_to_valley", "light_rate_at_valley_cps",
               "photon_rate_at_valley_cps",
               "half_peak_level_mV", "dark_rate_at_half_peak_cps", "lower_bound_V", "recommended_V",
               "photons_counted_at_recommended", "best_abs_snr", "best_abs_snr_se", "best_abs_snr_level_V", "settled",
               "settle_minutes", "light_csv", "dark_csv", "settle_csv", "problem")

    def fmt(v, scale=1.0, digits=4):
        return "" if v is None else f"{v * scale:.{digits}g}"

    lines = [",".join(columns)]
    for r in rows:
        lines.append(",".join([
            f"{r['hv']:g}", str(r.get("n", 0)), fmt(r.get("valley_v"), 1e3), fmt(r.get("peak_v"), 1e3), fmt(r.get("pv")),
            fmt(r.get("valley_rate")), fmt(r.get("photon_rate")),
            fmt(r.get("half_peak_v"), 1e3), fmt(r.get("dark_at_half")),
            "" if r.get("lower_bound_v") is None else str(_gui_volts(r["lower_bound_v"])),
            "" if r.get("recommended_v") is None else str(_gui_volts(r["recommended_v"])),
            "" if r.get("recommended_loss") is None else f"{1 - r['recommended_loss']:.4f}",
            fmt(r.get("best_snr")), fmt(r.get("snr_se")),
            "" if r.get("best_snr_v") is None else str(_gui_volts(r["best_snr_v"])),
            "" if r.get("settled") is None else str(r["settled"]), fmt(r.get("settle_min"), 1.0, 3),
            r.get("light_csv", ""), r.get("dark_csv", ""), r.get("settle_csv", ""),
            r.get("problem", "").replace(",", ";"),
        ]))
    csv_path = os.path.join(folder, f"SR400_hv_compare_{stamp}.csv")
    with open(csv_path, "w", encoding="utf-8") as handle:
        handle.write("\n".join(lines) + "\n")
    rep_lines = ["when,hv_V,photon_rate_at_valley_cps,best_abs_snr,best_abs_snr_corrected,"
                 "best_abs_snr_level_V,light_csv,dark_csv,problem"]
    for r in sorted(replicates, key=lambda r: r["when"]):
        rep_lines.append(",".join([
            r["when"], f"{r['hv']:g}", fmt(r.get("photon_rate")), fmt(r.get("best_snr")),
            fmt(r.get("snr_corrected")),
            "" if r.get("best_snr_v") is None else str(_gui_volts(r["best_snr_v"])),
            r.get("light_csv", ""), r.get("dark_csv", ""), r.get("problem", "").replace(",", ";")]))
    with open(os.path.join(folder, f"SR400_hv_compare_{stamp}_replicates.csv"), "w", encoding="utf-8") as handle:
        handle.write("\n".join(rep_lines) + "\n")
    svg_path = os.path.join(folder, f"SR400_hv_compare_{stamp}.svg")
    with open(svg_path, "w", encoding="utf-8") as handle:
        handle.write(plot_hv_compare(rows, verdict, optimum, consistent, replicates))
    return csv_path, svg_path, verdict


def _hv_summary(r: dict) -> str:
    """One readable line per HV; any metric the scans could not give is 'n/a'."""
    if r["problem"]:
        return f"{r['hv']:g} V: left out: {r['problem']}"
    pv = f"{r['pv']:.2f}" if r.get("pv") is not None else "n/a (no valley resolved)"
    dark = (f"{r['dark_at_half']:.3g} counts/s at -{r['half_peak_v'] * 1e3:.1f} mV (half the peak)"
            if r.get("dark_at_half") is not None and r.get("half_peak_v") else "n/a")
    snr = (f"{r['best_snr']:.4g} at -{r['best_snr_v'] * 1e3:.1f} mV (GUI {_gui_volts(r['best_snr_v'])})"
           if r.get("best_snr") is not None else "not scored")
    settle = (", settled after " + _minutes(r["settle_min"] * 60) if r.get("settle_min") is not None else
              ", NOT SETTLED" if r.get("settled") is False else ", settling unknown")
    return (f"{r['hv']:g} V: valley {_mv(r.get('valley_v'))}, SPE peak {_mv(r.get('peak_v'))}, P/V {pv}, "
            f"dark {dark}, best S/sqrt(B) {snr}{settle}")


def plot_hv_compare(rows: list, verdict: list, optimum, consistent: bool, replicates=None) -> str:
    W, P = 1200, 300
    replicates = replicates or []
    good = [r for r in rows if not r["problem"]]
    summary = [_hv_summary(r) for r in rows]
    text_h = 22 + 16 * sum(max(1, len(t) // 160 + 1) for t in verdict + summary)
    svg = _Svg(W, int(120 + 2 * (P + 82) + (220 + 82) + text_h))
    svg.text(24, 30, "SR400 PMT high-voltage comparison -- threshold scans of the R8486 at each HV", 17, weight="bold")
    svg.text(24, 50, f"{len(rows)} HVs, {len(replicates)} light scans; each paired with the newest same-port, "
                     f"same-HV dark scan and settling check before it; all re-analysed by this code", 11, color="#555")
    if not good:
        _text_block(svg, 24, 80, 165, verdict + summary)
        return svg.render()
    hvs = [r["hv"] for r in good]
    pad = max(10.0, 0.05 * (max(hvs) - min(hvs)))
    xlim = (min(hvs) - pad, max(hvs) + pad)
    top, lx, rx, pw = 90, 90, 690, 480

    def having(key):
        return [r for r in good if r.get(key) is not None]

    a = _Panel(svg, lx, top, pw, P, xlim, (0.0, max((r["peak_v"] for r in having("peak_v")), default=0.01) * 1e3 * 1.3 + 0.5))
    a.frame("(a) gain: valley and single-PE peak", "PMT high voltage, V", "|level|, mV")
    a.series([r["hv"] for r in having("peak_v")], [r["peak_v"] * 1e3 for r in having("peak_v")],
             "#34495e", "o", label="single-PE peak")
    a.series([r["hv"] for r in having("valley_v")], [r["valley_v"] * 1e3 for r in having("valley_v")],
             _C["valley"], "o", "4,3", label="valley")
    a.legend()
    missing = [f"{r['hv']:g}" for r in good if r.get("valley_v") is None]
    if missing:
        a.note(f"no valley resolved at {', '.join(missing)} V", "#c0392b", corner="br")

    b = _Panel(svg, rx, top, pw, P, xlim, (0.0, max((r["pv"] for r in having("pv")), default=1.0) * 1.3 + 0.1))
    b.frame("(b) peak / valley: how cleanly photons separate from noise", "PMT high voltage, V", "peak / valley")
    b.series([r["hv"] for r in having("pv")], [r["pv"] for r in having("pv")], "#1a7f37", "o")

    with_dark = [r for r in good if r.get("dark_at_half")]
    darks = [r["dark_at_half"] for r in with_dark]
    c = _Panel(svg, lx, top + P + 82, pw, P, xlim, (min(darks, default=0.1) / 3, max(darks, default=1) * 3), log_y=True)
    c.frame("(c) dark rate at half the single-PE peak (log)", "PMT high voltage, V", "counts/s (log)")
    c.series([r["hv"] for r in with_dark], darks, "#c0392b", "o")

    scored = [r for r in good if r["best_snr"] is not None]
    if consistent and scored:
        reps = [x for x in replicates if x.get("snr_corrected") is not None and not x["problem"]]
        # Zoomed to the data, not from zero: near the optimum the HVs differ by a few percent,
        # which a zero-based axis flattens into a line. The axis label says it is zoomed.
        highs = [r["best_snr"] + (r.get("snr_se") or 0) for r in scored] + [x["snr_corrected"] for x in reps]
        lows = [r["best_snr"] - (r.get("snr_se") or 0) for r in scored] + [x["snr_corrected"] for x in reps]
        pad = 0.15 * (max(highs) - min(lows)) or 0.05 * max(highs)
        d = _Panel(svg, rx, top + P + 82, pw, P, xlim, (max(min(lows) - pad, 0.0), max(highs) + pad))
        # No legend box: over the top-right it covered the highest HV's point. Named in the title.
        d.frame("(d) best S/sqrt(B), same light: grey = each scan, green = mean +- SE",
                "PMT high voltage, V", "S/sqrt(B), sqrt(counts/s) -- zoomed")
        if reps:
            d.series([x["hv"] for x in reps], [x["snr_corrected"] for x in reps], "#7f8c8d", "o",
                     filled=False, line=False)
        d.errorbars([r["hv"] for r in scored], [r["best_snr"] for r in scored],
                    [r.get("snr_se") or 0 for r in scored], "#1a7f37")
        d.series([r["hv"] for r in scored], [r["best_snr"] for r in scored], "#1a7f37", "o")
        if optimum:
            d.vline(optimum["hv"], _C["rec"], f"optimum {optimum['hv']:g} V", None, 0)
    else:
        svg.rect(rx, top + P + 82, pw, P, stroke="#cccccc")
        svg.text(rx + 12, top + P + 108, "(d) S/sqrt(B) across HV: NOT SHOWN", 13, weight="bold")
        _text_block(svg, rx + 12, top + P + 132, 70, [
            "The light rate differed between HVs, so the background-limited figure of merit cannot "
            "be compared across them. Repeat with the same light source and setting at every HV."
            if not consistent else "No HV had a dark scan with enough counts to score."], 11)
    timed = [x for x in replicates if x.get("photon_rate") and not x["problem"]]
    e_top = top + 2 * (P + 82)
    if timed:
        order = sorted(timed, key=lambda x: x["when"])
        e = _Panel(svg, lx, e_top, rx + pw - lx, 220, (0.5, len(order) + 0.5),
                   (0.0, max(x["photon_rate"] for x in order) * 1.25))
        e.frame("(e) light level of each scan, in the order taken: a trend here is source drift, "
                "and is corrected in (d)", "scan number, in time order", "photons/s at the valley")
        e.series(list(range(1, len(order) + 1)), [x["photon_rate"] for x in order], "#1f77b4", "o", width=1.0)
        for k, x in enumerate(order, start=1):
            svg.text(e.px(k), e.py(x["photon_rate"]) - 8, f"{x['hv']:g}", 9, "middle", color="#555")
    _text_block(svg, 24, e_top + 220 + 62, 165, verdict + summary)
    return svg.render()


if __name__ == "__main__":
    import sys as _sys

    if len(_sys.argv) >= 3 and _sys.argv[1] == "plot":
        for csv_path in _sys.argv[2:]:
            print(plot_csv(csv_path))
    elif len(_sys.argv) == 3 and _sys.argv[1] == "hv-compare":
        table, figure, verdict = hv_compare(_sys.argv[2])
        print(table)
        print(figure)
        for line in verdict:
            print(line.lstrip("+!"))
    else:
        print("usage: python selftest.py plot <scan.csv> [<scan.csv> ...]")
        print("       python selftest.py hv-compare <folder>")
        print("plot regenerates each scan's SVG from its CSV. hv-compare compares the scans in a")
        print("folder taken at different PMT high voltages. Both need nothing beyond Python itself.")
