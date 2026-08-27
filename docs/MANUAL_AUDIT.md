# Manual audit

Every command, numeric limit and status bit in the driver checked against the **SR400 manual,
Revision 2.7 (11/2018)**, the revision the driver header cites.

The manual is SRS copyright and is **not** committed here. Get it from
[thinkSRS.com](https://www.thinkSRS.com); page numbers below are the manual's own printed numbers.

## Result

Nothing in the driver was wrong. Two documentation defects were found and fixed, one assumption was
promoted to a quotation, and one extraction trap is recorded below so the next person does not fall
into it.

## Confirmed verbatim

| Driver claim | Manual |
|---|---|
| `CP` keeps one significant digit; `1E1`-style readback | p. 39: *"only the most significant digit is used. For example, `CP2,10`, `CP2,1E1`, `CP2,0.1E2`, `CP2,12` all set T SET to 1E1"* … *"In the above example, the string `1E1` is returned"* |
| Preset range 1 … 9E11, in clock cycles not seconds | p. 39: *"n is a value from 1 to 9E11"* … *"n is the number of cycles of the 10 MHz clock, not seconds"* |
| `DT` 2 ms … 60 s, 0 = EXTERNAL, one significant digit | p. 40: *"2E-3 <= x <= 6E1. If x = 0, the dwell is set to EXTERNAL. Only the most significant digit of x is used"* |
| `TL` ±2.000 V, 1 mV resolution | p. 40: *"-2.000 <= v <= 2.000. The resolution is .001 V"* |
| `DL` ±0.3000 V | Abridged list: *"Set DISC i LVL to -0.3000 <= v <= 0.3000 V"* |
| `PL` ±10.000 V | Abridged list: *"Set PORT k (1 or 2) LVL to -10.000 <= v <= 10.000 V"* |
| Gate delay 0 … 999.2 ms | Abridged list: *"Set GATE i DELAY to 0 <= t <= 999.2E-3 s"* |
| Gate width 5 ns … 999.2 ms | Abridged list: *"0.005E-6 <= t <= 999.2E-3 s"* |
| Gate resolution bands (1/2/4/8 in the 4th digit), 1 ns below 1 µs | p. 33 table: `1000-2048 → 1`, `2048-4096 → 2`, `4096-8192 → 4`, `8192-9992 → 8`; *"Below 1.000 µs, the resolution is 1 ns"* |
| `NP` 1 … 2000 | Abridged list and p. 39 |
| Counter overrun at 10⁹−1 | Status bit 3: *"set whenever counter A or B exceeds or equals 10⁹-1 counts"* |
| Rate error = missed gate, delay/width > trigger period − 1 µs | Status bit 4, worded exactly that way |
| Scan-finished bit needs end mode STOP | Status bit 2: *"set at the end of a scan if the scan end mode is STOP"* … *"not set if the scan end mode is START"* |
| SRQ bit always 0 when polled with `SS` | Status bit 6, stated outright |
| `QA`/`QB` return −1 when not ready, and `QB` returns −1 when B is preset | p. 45: *"If data is not ready, the QA and QB commands return -1. If counter B is preset, QB returns -1."* |
| `SW m` = character wait, 0 … 25, ×3.3 ms | Abridged list and p. 37 |
| `SE` = terminator sequence, RS-232 only | Abridged list; p. 37: *"may be changed using the SE command"* |
| `ST` 1…9, `RC` 1…9, `RC 0` = defaults | p. 45 |
| Both buffers 256 characters; overflow erases all buffered data | p. 37: *"a command input buffer of 256 characters"*, *"an output buffer (for each interface) of 256 characters"*, *"all buffered data is erased"* |
| Chained queries answer in order | p. 37–38: *"processes the commands in the order received"*; *"the response to the command string `CM;CI0;GD0<cr>` … would be `1<cr>1<cr>1.2E-6<cr>`"* |
| On an error the rest of the command line is discarded | p. 47: *"any commands remaining on the current command line (up to the next `<cr>`) are lost"* |

## Fixed by this audit

**1. The terminator question was never a hardware question.** `docs/README.md` recorded the two
drafts' disagreement about RS-232 line endings as something only the bench could settle. The manual
states it directly (p. 37):

> The terminating sequence for the GPIB interface is always `<cr><lf>`. The default sequence for
> RS-232 is `<cr>` when the echo mode is off, and `<cr><lf>` when the echo mode is on.

The kept driver's `EOL: "\r"` with `GPIB_EOLread: "\n"` is right, and the alternate draft's uniform
`"\r\n"` would hang on every serial read in the very configuration its own header instructs the user
to select. Recorded as resolved.

**2. `BUFFER_ERROR_CHARS = 240` overclaimed its source.** The docstring said *"Exceeding this on one
command line sets the command-error bit."* What the manual says (p. 37) is that the **ERR LED**
flashes when *"a communication buffer has exceeded 240 characters"*, listed alongside an illegal
command and an out-of-range parameter. Status bit 7 is documented only as *"set when an illegal
command is received"* — the manual never connects 240 characters to that bit. The driver caps
batches at 180 so nothing behavioural changes, but the constant and the simulator comment now
distinguish the quotation from the inference. This matters because the driver's auditability is its
main claim: a reviewer must be able to tell which statements are the manual's.

**3. `CP i` response format promoted from assumption to fact.** It was listed in README §7.1 as
inferred; the manual states it. §7.1 is one item shorter.

Also added: the command-error message now tells the user the `DATA` window holds the last **254**
characters (p. 47) and that the rest of the line was discarded — both actionable while debugging.

## Extraction trap, for whoever reads the PDF next

`pdftotext -layout` mis-pairs the abridged command list. It is a two-column table, and the command
column comes out **shifted one row against the description column**. Read literally it says:

```
SW m        Set RS-232 terminator sequence to j,k,l,m (ASCII codes). RS-232 only.
SE j,k,l,m  Clear RS-232 terminator sequence to defaults. RS-232 only.
```

which would mean `SW` sets the terminator — and a driver that believed it would corrupt the link
every time it tried to speed up the wait interval. The correct pairing shifts back by one:

```
SW m        Set RS-232 character wait interval to m*3.33 ms, 0 <= m <= 25. RS-232 only.
SE j,k,l,m  Set RS-232 terminator sequence to j,k,l,m (ASCII codes). RS-232 only.
SE          Clear RS-232 terminator sequence to defaults. RS-232 only.
```

The same shift affects `SV`/`SS`/`SI` and the `QA`/`QB`/`QA m`/`QB m` block. Check any abridged-list
reading against the detailed command list (pp. 39–47), which extracts cleanly.

One genuine inconsistency in the manual itself, not an extraction artefact: the wait interval is
`m × 3.33 ms` in the abridged list and `wait value times 3.3 ms` on p. 37. The difference is 1 % of
a value the driver sets to zero anyway.

## Still unverified after the audit

See README §7.1. Two of the three are response-format details the driver parses through `float()`
regardless; the third is how deep a chained query a given firmware answers correctly, which the
manual does not bound.
