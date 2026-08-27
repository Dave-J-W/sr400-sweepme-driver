# Implementation plan — SR400 driver, latency diagnostics + query batching

Target repo layout (already exists):

```
Switch-Stanford_SR400/
    main.py          ~1440 lines, Device(EmptyDevice), Switch module
    README.md        advanced readme, §1-7
test_sr400_virtual.py    SR400 protocol simulator + 90 assertions, currently 90/90
```

Run `python test_sr400_virtual.py` before starting and after every task. **90/90 must never
regress.** Every new behaviour gets bench coverage in the same commit that introduces it.

---

## 0. Invariants — do not break these

| # | Invariant | Why |
|---|---|---|
| I1 | The driver imports and the bench runs on Linux with no FTDI hardware and no Windows registry. | CI and the virtual bench are the only always-available test path. `winreg` must be imported **lazily, inside the function that needs it**, never at module scope. |
| I2 | No new third-party dependencies. | SweepMe! ships a fixed Python env; `winreg`, `pathlib`, `re` are stdlib. |
| I3 | Nothing in the measurement path (`connect` → `call`) requires administrator rights, and nothing in it writes to the OS or registry. | A driver that needs elevation to measure is unusable in a shared lab. |
| I4 | The diagnostic action sends **zero** commands to the instrument. | It must be safe to click at any time, including mid-experiment. |
| I5 | Every instrument command remains traceable to the SR400 manual command list (pp. 37-47). No invented commands. | Handoff §5 source-of-truth hierarchy. |
| I6 | Unbatched (current) behaviour stays the default and stays reachable. | Batching contradicts an explicit manual recommendation — see T3.0. |
| I7 | No silent data of uncertain provenance. Ambiguity raises. | Handoff §21. A count value shifted by one readout is worse than a crash. |

---

## Tier 1 — detect and warn about the USB-serial latency timer

**Problem being solved.** An FTDI/Prolific USB-serial adapter batches inbound bytes and waits for
its latency timer (Windows default **16 ms**) before completing a short read. The SR400 driver makes
~5 query round trips per measurement point, so the default setting costs ~80 ms per point — larger
than the entire bit time at 19200 baud, and larger than the gain from doubling the baud rate. Almost
every occurrence of "the SR400 is slow" is this setting, and nobody knows it exists.

### T1.1 — `_get_com_latency_timer()`

Add a private method returning `int | None` (milliseconds, or `None` when the value cannot be
determined — which is not an error condition).

```python
def _get_com_latency_timer(self) -> int | None:
    """Return the USB-serial latency timer of the selected COM port in ms, or None.

    Only FTDI-based adapters expose this setting. None means 'unknown or not applicable'
    (native UART, non-FTDI adapter, macOS, permission denied), never 'fine'.
    """
```

Platform branches, each individually wrapped so a failure in one cannot mask the others:

- **Windows** — lazily `import winreg`. Walk
  `HKLM\SYSTEM\CurrentControlSet\Enum\FTDIBUS`, and for each instance subkey read
  `Device Parameters\PortName`; when it equals `self.port_string`, read
  `Device Parameters\LatencyTimer` and return it. If FTDIBUS yields nothing, repeat the walk over
  `HKLM\SYSTEM\CurrentControlSet\Enum\USB\VID_0403&PID_*` — driver versions differ in which tree
  carries `Device Parameters`. Read-only access (`KEY_READ`); a `PermissionError` or
  `FileNotFoundError` returns `None`.
- **Linux** — read `/sys/bus/usb-serial/devices/<tty>/latency_timer`, where `<tty>` is
  `Path(self.port_string).name` (handles both `ttyUSB0` and `/dev/ttyUSB0`). Missing file → `None`.
- **Anything else** (incl. macOS, which has no equivalent knob) → `None`.

Wrap the whole body in `try/except Exception: return None`. This method must be incapable of
raising.

### T1.2 — warn once in `connect()`

After the existing `CM` identification check succeeds, and only when `self.is_rs232`:

```python
self._warn_about_com_latency()
```

which reads the timer, and if it is `> LATENCY_TIMER_WARN_MS` (new class constant, value `4`) emits
**one** `message_info` guarded by `self._latency_warning_shown`. Message content, non-negotiable
elements:

- the measured value in ms,
- the estimated cost per measurement point (`≈ 5 × value` ms — state that it is an estimate),
- the exact Windows click path: *Device Manager → the COM port → Port Settings → Advanced →
  Latency Timer → 1*,
- a pointer to the `reduce_com_port_latency` action from T2,
- the fact that a **replug or reboot** is required.

Never warn when the value is `None`. An unknown value must not produce a scary message on a native
RS-232 port where the setting is meaningless.

### T1.3 — bench coverage

New test `test_latency_detection`:

- `_get_com_latency_timer()` returns `None` and does not raise on the bench platform, for port
  strings `"COM3"`, `"/dev/ttyUSB0"`, `"ttyUSB9"`, `"GPIB0::23::INSTR"`, and `""`.
- With `_get_com_latency_timer` monkeypatched to return `16`, `connect()` still succeeds and
  `self._latency_warning_shown` becomes `True`.
- Monkeypatched to `1` → no warning flag set.
- Monkeypatched to raise → `connect()` still succeeds (proves the guard).
- A GPIB port string never triggers the check.

---

## Tier 2 — setup helper as a SweepMe! action

**Mechanism.** `EmptyDevice` declares `actions: list[str] = []` as a class variable: *"a list of
function names that can be used as action"*. SweepMe! renders them as clickable buttons. Confirmed
in use by ~30 official drivers (e.g. `Logger-Kern_Balance`: `actions = ["tare", "zero"]`;
`Switch-Coherent_Chameleon`: `actions = ["close_shutter", "open_shutter", ...]`). Action methods take
**no arguments** beyond `self` and return `None`.

### T2.1 — declare the actions

```python
class Device(EmptyDevice):
    actions = ["report_com_port_latency", "reduce_com_port_latency"]
```

Place immediately after the class docstring, before `description`, matching the official-driver
convention.

### T2.2 — `report_com_port_latency()`

Read-only. Composes a `message_box` containing: the port string; the detected latency timer or an
explanation of why it is unknown; the recommended value (1 ms); the estimated per-point saving; and
the manual-path instructions. Sends nothing to the instrument (**I4**). Must work with no port
open — if `self.port_string` is empty, say "select a port first" rather than raising.

### T2.3 — `reduce_com_port_latency()`

This is the one that needs care, because the write is privileged and does not take effect
immediately.

Sequence:

1. If the port is not a COM port → `message_box` explaining the setting is RS-232/USB-adapter only,
   return.
2. If the current value is already `≤ 2` → say so, return. Do not write.
3. **Attempt the write.**
   - Linux: write `1` to the sysfs `latency_timer` file. This often succeeds for the owning user or
     with a udev rule, and takes effect immediately — a genuinely clean path.
   - Windows: `winreg.SetValueEx(..., "LatencyTimer", 0, winreg.REG_DWORD, 1)` on the key located in
     T1.1, opened `KEY_SET_VALUE`.
4. **On success:** `message_box` confirming the new value and stating whether a replug is required
   (Linux: no; Windows: yes).
5. **On `PermissionError`/`OSError`:** do **not** raise. Instead generate the remedy and hand it
   over:
   - write a `.reg` file into `self.get_folder("TEMP")` containing the single `LatencyTimer` DWORD
     under the resolved key path, named `SR400_set_latency_timer_<COMx>.reg`;
   - `message_box` the absolute path plus: run it as administrator, then unplug and replug the
     adapter.
   - On Linux, emit the equivalent `sudo sh -c 'echo 1 > /sys/bus/usb-serial/devices/.../latency_timer'`
     one-liner and a suggested udev rule for persistence.

This is what makes it a legitimate action rather than a trap: the action does the **diagnosis and
generates the exact remedy** without itself demanding elevation, so **I3** holds — the measurement
path never needs admin, and the action never silently half-succeeds.

Both actions must be incapable of raising. Wrap each body; report failures as message text.

### T2.4 — bench coverage

New test `test_latency_actions`:

- `"report_com_port_latency" in Device.actions` and both names resolve to callables via `getattr`.
- Both actions run without raising for a COM port, a GPIB port, and an empty port string, on the
  bench platform (where every OS lookup fails) — capture `message_box` by monkeypatching
  `Device.message_box` to append to a list, then assert the list is non-empty and mentions the port.
- `reduce_com_port_latency()` sends nothing: assert `len(sr400.log)` is unchanged across the call.
  (Same assertion for the report action — this is the **I4** regression test.)

---

## Tier 3 — opt-in query batching

### T3.0 — the documented conflict, read this first

The SR400 accepts multiple commands per line separated by `;`, **including queries**, and returns
the responses in order. Manual: `CM;CI0;GD0<cr>` → `1<cr>1<cr>1.2E-6<cr>`.

The same manual also says: *"In general, it is good programming practice to receive the response
from one query command before sending another command."*

Both statements are true and this feature lives in the gap between them. Therefore: **default off,
never auto-enabled, and the conflict is documented in the code and the README.** Do not "simplify"
this by making it the default.

Why it is worth having anyway: the latency timer penalises **read transactions**, not bytes. Chained
responses arrive in one USB packet, so the first `read()` pulls the whole packet into the buffer and
subsequent reads return with no latency wait.

| | read transactions / point | latency cost at 16 ms |
|---|---|---|
| current, 1 period | 5 | ~80 ms |
| batched, 1 period | ~3 | ~48 ms |
| current, 10 periods | 23 | ~370 ms |
| batched, 10 periods | ~5 | ~80 ms |

The win scales with `Periods per point`, which is exactly the configuration a user reaches for when
they want throughput.

### T3.1 — hard limits from the manual

New class constants, each with the manual citation as a comment:

```python
COMMAND_BUFFER_CHARS = 256      # command input buffer
OUTPUT_BUFFER_CHARS = 256       # output buffer, per interface
BUFFER_ERROR_CHARS = 240        # exceeding this sets the command-error bit
BATCH_MAX_LINE_CHARS = 180      # self-imposed, safety margin below BUFFER_ERROR_CHARS
BATCH_MAX_RESPONSE_CHARS = 180  # self-imposed, margin below OUTPUT_BUFFER_CHARS
BATCH_MAX_COMMANDS = 10         # → ≤ 10 count values queued, ~100 chars of response
```

A batch that would exceed either character budget must be split, not sent. Overflowing the output
buffer costs the **entire scan** (`DATA BUFFER OVERFLOW`, all buffered data erased).

### T3.2 — GUI parameter

Add to `set_GUIparameter()`, next to `Timeout in s`:

```python
"Fast readout (batch queries)": False,
```

and in `get_GUIparameter()`: `self.batch_queries = bool(parameter.get("Fast readout (batch queries)", False))`.

### T3.3 — `_query_batch(commands: list[str]) -> list[str]`

```python
def _query_batch(self, commands: list[str]) -> list[str]:
    """Send several queries on one line and return their answers in order.

    The SR400 processes commands in the order received and answers each with its terminator
    sequence, so N chained queries produce N answers. Only used when the user enabled the
    fast readout; see README gotcha 14 for the trade-off.
    """
```

Requirements, in order:

1. **Drain check.** If the port exposes `in_waiting()` (COM only — guard with `hasattr`) and it
   reports pending bytes **before** the write, the link was already desynchronised. Drain, then
   raise. Stale bytes are the failure mode that could otherwise produce the right *number* of
   answers with the wrong *pairing* — the one corruption that count-validation alone cannot catch.
2. Assert the joined line length ≤ `BATCH_MAX_LINE_CHARS` and `len(commands) ≤ BATCH_MAX_COMMANDS`.
   Violation is a programming error → raise immediately, before writing.
3. Write `";".join(commands)` as a single `port.write`.
4. Read exactly `len(commands)` responses. Any empty response → raise with the full command line and
   the responses received so far.
5. Return the list.

### T3.4 — chunked buffer readout in `measure()`

Replace the readout loop. Build the query list as interleaved `QA m` / `QB m` (skipping B when
`not self.counter_b_is_readable`), then:

- if `self.batch_queries`: consume in chunks sized by `BATCH_MAX_COMMANDS` **and** the character
  budget, via `_query_batch`, parsing each answer through the existing `-1` check and int
  conversion;
- else: the existing one-at-a-time `get_scan_point()` path, unchanged.

**Do not batch:**

- the status polling loop — each poll must be a fresh read of current state, and batching would
  break the OR-accumulation logic;
- write-only configuration commands — writes do not pay the latency penalty, so there is no gain,
  and a batch discards every remaining command on the line if one errors (manual, "ERRORS/DATA
  WINDOW"). Configuration is where per-command error attribution matters most.

Refactor so the `-1` handling and the "cannot interpret answer" message are shared between the
batched and unbatched paths — one parser, two transports.

### T3.5 — failure handling

On any `_query_batch` failure inside `measure()`:

1. Resync: `_resync_after_batch_failure()` — drain the port (repeated `port.read()` until empty, max
   20 iterations), then a single `CM` query validated as 0-3. **Do not use `CL`** to recover: it
   resets the front-panel setup and would destroy the user's configuration mid-run.
2. Retry the current point **once**, unbatched.
3. If the retry succeeds: `message_info` that fast readout failed and has been disabled, set
   `self.batch_queries = False` for the remainder of the run, continue.
4. If the retry also fails: raise. The link is broken, not merely desynchronised.

Never return a value obtained from a batch whose response count or ordering was in doubt (**I7**).

### T3.6 — simulator hardening (do this before T3.4)

The simulator already splits on `;`, so batching would appear to work even if the driver violated
the buffer limits. Make the simulator enforce what the instrument enforces, so bench passes mean
something:

- in `write()`, if `len(command) + 1 > 240`: set status bit 7 and **discard the rest of the line**
  (manual: on error, *"any commands remaining on the current command line (up to the next `<cr>`) are
  lost"*);
- in `_answer()`, if the pending output would exceed 256 characters: **clear `self.out` entirely**
  and set a new `self.buffer_overflowed` flag, mimicking `DATA BUFFER OVERFLOW`;
- add an `inject_stale_response(text)` test hook that prepends a bogus value to `self.out`, plus an
  `in_waiting()` method returning the pending character count, so T3.3's drain check is testable.

### T3.7 — bench coverage

New test `test_batched_readout`:

- **Equivalence property.** For `Periods per point` in `{1, 2, 10, 17, 33}`, run one point with
  `Fast readout` off and once on, against identically seeded simulators; assert `call()` returns
  identical values. This is the test that actually matters.
- **Chunking.** With 33 periods, assert every command line the simulator received is ≤ 180 chars and
  contained ≤ 10 commands, and that no `DATA BUFFER OVERFLOW` occurred.
- **Round-trip reduction.** Assert the batched run issued strictly fewer `write` calls than the
  unbatched run (the whole point of the feature).
- **Desync detection.** `inject_stale_response("999")` before a batched point → the driver detects
  it, resyncs, retries unbatched, returns correct data, and `self.batch_queries` is now `False`.
- **Hard failure.** A port that returns `""` for every batched read → raises, with the offending
  command line in the message.
- **Config is never batched.** Assert no command line sent during `configure()` contains `";"`.
- **Status polling is never batched.** Same assertion for the poll phase.

---

## Task order

1. **T3.6** simulator hardening — do it first so later tiers are tested against a stricter model.
2. **T1** detection (T1.1 → T1.2 → T1.3).
3. **T2** actions — reuses `_get_com_latency_timer()` from T1.1.
4. **T3** batching (T3.1 → T3.2 → T3.3 → T3.4 → T3.5 → T3.7).
5. **Documentation** (below).

Tier 3 touches `measure()`. If per-period statistics (mean / sample std / Fano factor as extra
output variables, discussed separately) are also wanted, **land T3 first** — the batched readout
already collects the per-period list that the statistics need, so doing it in the other order means
writing the collection loop twice.

---

## Documentation — what to write, and why

The rationale matters as much as the content here, because the next person to touch this file will
either preserve these decisions or "fix" them.

**1. Keep the manual citation on every command.** Handoff §5 sets the manual as the top authority
and §28 asks for comments that explain protocol quirks rather than Python syntax. A bare
`self.port.write("CP 2,1E5")` is unreviewable; with `# CP keeps one significant digit (manual p. 39)`
a reviewer can check the driver against the instrument without owning one. This is the property that
made the existing driver auditable and it must survive the refactor.

**2. Cross-reference gotchas from the exception text, not only the README.** The person debugging at
2 a.m. reads the error message; they do not read the README. So every new raise gets a message that
names the cause and the remedy inline (e.g. *"fast readout desynchronised; disable 'Fast readout
(batch queries)'"*), and the README gotcha carries the long explanation. The README is for planning,
the exception is for recovery. Adding a gotcha without touching the message is half a job.

**3. The latency-timer documentation must state platform, scope, privilege and persistence.**
Specifically: FTDI-only, RS-232-only, Windows needs admin, Windows needs a replug, the setting is
global to that adapter and outlives the SweepMe! run. Omitting "requires a replug" reliably generates
a bug report saying the action does not work. Omitting "global and persistent" means someone changes
a shared lab machine without realising the scope. Documenting privilege requirements is also what
justifies the `.reg`-file design over an in-process write.

**4. Document the batching conflict, verbatim, with the counter-quotation.** The README gotcha and
the `_query_batch` docstring both cite the manual's *"good programming practice to receive the
response from one query command before sending another"* alongside the manual's own working chained
example. Writing down that the two coexist is what makes the opt-in defensible and what stops a
future maintainer from flipping the default to save five lines. An undocumented conservative default
gets removed; a documented one survives.

**5. Label numbers as measured, derived, or unknown.** The existing README §6.2 throughput table
mixes bit-time arithmetic (exact), latency-timer costs (documented defaults), and instrument
command-processing time (**not specified anywhere in the manual** — estimated). Keep those labels
when revising the table with batched figures, and keep the note that the SR400's per-command
processing time is an estimate. A table of confident-looking numbers that silently contains guesses
is worse than no table, because it will be quoted in someone's methods section.

**6. Document what the driver deliberately does not do.** The README already records that PORT levels
are not zeroed on exit and that `CL` is off by default. Add: the latency timer is never changed
without an explicit action click, and batching is never auto-enabled. An absent behaviour is a design
decision, and undocumented design decisions get implemented by the next contributor as "improvements".

### Concrete documentation edits

| Target | Change |
|---|---|
| `README.md` §4 | New gotcha **14 — USB-serial latency timer**: what it is, the 16 ms default, per-point cost, the two actions, platform/admin/replug scope. New gotcha **15 — batch readout**: the manual's two positions, buffer limits, the desync failure mode, why it is opt-in. |
| `README.md` §5.2 | New hardware step between current 2 and 3: run `report_com_port_latency`, record the value, and re-time step 5 with and without fast readout. Give the user the measurement rather than asking them to trust the table. |
| `README.md` §6.2 | Add batched columns; keep the measured/derived/unknown labelling from rationale 5. |
| `README.md` new §8 | **Actions** — what each does, that the diagnostic sends nothing to the instrument, and the privilege/replug caveats. Renumber the existing §8 "Open items". |
| `README.md` §7 | Add: whether chained queries behave as documented on the user's firmware revision is **unverified on hardware** — it is the one new assumption in T3. |
| `main.py` | Docstrings for the two actions and `_query_batch` per rationales 3 and 4; manual citations on the new buffer constants. |
| `CHANGELOG.md` (new) | Three entries, each naming the gotcha number it documents. |

---

## Acceptance criteria

- `python test_sr400_virtual.py` reports **≥ 90 + new checks, zero failures**, on Linux, with no
  hardware, no FTDI, no registry.
- `Device.actions == ["report_com_port_latency", "reduce_com_port_latency"]`; both callable with no
  arguments; neither raises on any platform; neither writes to the instrument.
- `Fast readout` off reproduces today's byte-for-byte command traffic (assert against a recorded
  command log for a fixed configuration — add that recording as a bench fixture).
- `Fast readout` on returns values identical to off, for every period count tested.
- No module-scope `import winreg`.
- `grep -n '";"' main.py` shows batching used only in the readout path.
