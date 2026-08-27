# The latency + batching plan, rebased

[`IMPLEMENTATION_PLAN_as_written.md`](IMPLEMENTATION_PLAN_as_written.md) is kept **verbatim**. Its
"Documentation — what to write, and why" section is the reason: the rationales there (label numbers
as measured/derived/unknown; cross-reference gotchas from the exception text, not only the README;
document absent behaviours so they are not "improved" back in) outlived the tasks and are worth
more than the task list.

All three tiers are implemented. What follows is the rebase — what the plan assumed, what was
actually true, and where each task landed.

## What the plan was written against

The plan predates three commits and assumed a layout that no longer exists:

| Plan says | Actually |
|---|---|
| `Switch-Stanford_SR400/` | `Logger-Stanford_SR400/` |
| `Switch` module, `apply()` in the traffic | Logger; there is no `apply()` |
| `test_sr400_virtual.py` at the repo root | `Logger-Stanford_SR400/tests/test_sr400_virtual.py` |
| "90/90 must never regress" | 125/125 at the start of this work, **187/187** after |
| New gotchas **14** and **15** | **15** and **16**; 14 was already taken by the front-panel-change gotcha |
| "Renumber the existing §8 Open items" | Open items is **§7**, so §8 was free and no renumbering was needed |
| `"Fast readout"` next to `Timeout in s` | Still next to `Timeout in s`, but the layout is now grouped under headings |

One assumption the plan makes that the mode split changed: batching was pitched as scaling with
`Periods per point`. That is still true, but `Periods per point` now only applies in
`Scan of N periods`. In the default `Single count period` mode a point issues about four reads and
batching saves at most one, so **fast readout is effectively a scan-mode feature**. The README says
so.

## Where each task landed

| Task | Status | Notes |
|---|---|---|
| T3.6 simulator hardening | done, first | `COMMAND_LINE_ERROR_CHARS` (240) truncates the rest of the line and sets bit 7; `_answer()` clears the whole buffer past 256 chars; `in_waiting()` and `inject_stale_response()` added as test hooks |
| T1.1 `_get_com_latency_timer()` | done | `winreg` imported inside the function; FTDIBUS then `VID_0403` under USB; depth-bounded walk matching `PortName`; sysfs on Linux; cannot raise |
| T1.2 warn once in `connect()` | done | After the `CM` check, so a latency note never competes with a real connection error |
| T1.3 bench coverage | done | Test [18] |
| T2.1–T2.3 actions | done | `.reg` fallback on refused writes, exactly as specified |
| T2.4 bench coverage | done | Test [19], including the I4 assertion that neither action writes to the instrument |
| T3.1 buffer constants | done | With the manual citations |
| T3.2 GUI parameter | done | Off by default |
| T3.3 `_query_batch` | done | Named `_query_batch`; `_query_batched` chunks a whole query list into batches |
| T3.4 chunked readout | done | One parser (`_parse_scan_point`), two transports, as the plan asked |
| T3.5 failure handling | done | Drain → validated `CM` → one unbatched retry → disable for the run. Never `CL` |
| T3.7 bench coverage | done | Test [20] |
| Documentation | done | Gotchas 15/16, §5.2 step 3, §6.2 batched table, new §8 Actions, §7.1 item 4, `CHANGELOG.md` |

## Two deviations, both deliberate

**The plan's I3 guard was placed one level higher than specified.** T1.3 asks that a
`_get_com_latency_timer()` monkeypatched to raise still leaves `connect()` working. As written, the
`try/except` lived only *inside* that method, so replacing the method wholesale bypassed the guard
and `connect()` did break. `_warn_about_com_latency()` now has its own guard too. It is redundant
today — and the comment says so — but `connect()` is the measurement path, and a host-side
convenience must not be able to stop a run however the lookup is rewritten later.

**The bench now stubs the latency lookup by default.** `make_device()` sets
`_get_com_latency_timer` to return `None`, because the real lookup reads the host registry and the
development machine genuinely has an FTDI adapter on `COM3` with the factory-default 16 ms timer.
Left live, the suite's output would depend on which machine ran it — which is invariant I1 in
spirit even though the plan only worded it as "must run without FTDI hardware". Tests that care
about the timer override the stub themselves.

## Not done, and not part of this plan

The plan's Tier 3 note about landing per-period statistics (mean, sample standard deviation, Fano
factor) after T3 still stands, and is not implemented. `_read_scan_buffer()` sums the per-period
values as it goes rather than keeping the list, so whoever adds statistics should return the list
from there instead of a running total — the collection loop is in the right place, it just discards
what statistics would need.
