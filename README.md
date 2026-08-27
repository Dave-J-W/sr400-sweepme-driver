# SweepMe! driver — Stanford Research Systems SR400 photon counter

A [SweepMe!](https://sweep-me.net) **Switch** driver for the SRS SR400 gated photon
counter, over RS-232 or GPIB. Every command it sends is documented in the SR400
manual's *Remote Programming – Detailed Command List* (pp. 37–47); the SR400
predates IEEE-488.2, so there is no `*IDN?`, `*RST` or `*CLS`.

Two independent drafts are kept side by side while they are being compared and
merged:

- `From Claude Opus5/`
- `From GPT/`

Each folder holds `main.py`, its own `README.md` with the full command reference
and wiring notes, and `test_sr400_virtual.py` — a virtual-instrument test suite
that runs with no hardware attached.
