# Choosing the discriminator threshold — a step-by-step guide

For the **R8486 photomultiplier on SIGNAL INPUT 1** of the SR400. You need to know what the
discriminator threshold *is*: the smallest pulse the SR400 will count. This guide covers how to
choose it, using the driver's two threshold-scan actions.

The technical reference is §9.7 of [README.md](README.md). You don't need it to follow this.

---

## 1. What you are looking for

Every pulse coming out of the PMT is a different size. Most are single photons, which for this
tube at 1000 V average about **10 mV**, and some are much smaller. Mixed in with them is
**electronic noise**: lots of tiny pulses, mostly under a few mV, that are not photons at all.

The threshold decides which of these get counted:

- **Too low** and you count the noise. Your background goes up, sometimes by orders of magnitude.
- **Too high** and you throw away real photons. Your signal goes down, silently.

There is no level that is perfect at both, so you are looking for the best compromise. It usually
sits just above the point where the noise dies away.

**The trap this guide exists to stop.** The tempting choice is "raise the threshold until the dark
counts go to zero". It is wrong. Dark counts from a PMT are mostly real single-photoelectron pulses
(thermal electrons from the photocathode). They are the same size as your signal photons, so any
level that removes them removes your signal too. Somewhere near the noise edge is right. Zero dark
counts is not.

## 2. Why there are two scans

| Scan | Light on the PMT | What it finds |
|---|---|---|
| **Dark** — `run_threshold_scan_dark` | none: PMT covered | where the noise stops, i.e. the **lowest** sensible level |
| **Light** — `run_threshold_scan_light` | gentle and steady | where you start losing real photons, i.e. the **highest** sensible level |

Run the **dark scan first**, then the light scan straight afterwards. The light scan uses the
dark scan's result to compute the best level, so together they give one recommended number.

Neither scan changes your settings. Each one restores every setting it touched when it finishes.
The recommended level is **advice for you to enter**, not something the scan applies.

---

## 3. Before you start

- [ ] **SweepMe! 1.5.8** with the driver installed: the `Logger-Stanford_SR400` folder is in
      `C:\Users\Public\Documents\SweepMe!\CustomDevices\`.
- [ ] A **Logger** module with the SR400 selected, and the port chosen (GPIB address or COM port).
- [ ] The PMT **anode cable on SIGNAL INPUT 1**, with no attenuator.
- [ ] **No other cable** on the SR400's DISC outputs or SIGNAL INPUT 2 (remove any self-test
      loopback cable).
- [ ] The INPUT 1 cable **routed away from the DISC output connectors**. The SR400 manual warns
      that below 10 mV the DISC output pulses can be picked up by the signal cable, which makes
      the discriminator count itself. This tube's best threshold is likely below 10 mV, so this
      matters. Once the scans are done, **don't move the cables**.
- [ ] PMT **high voltage on** at its normal value (1000 V for the R8486), and left on for a few
      minutes so the dark rate settles.
- [ ] **No measurement running.** The scans refuse to start while the SR400 is counting.

> **Safety.** Never expose the PMT to room light while the high voltage is on. It can damage the
> tube. Turn the HV off before uncovering it, or use only the gentle light described in step 5.

---

## 4. Step 1 — the dark scan

1. **Cover the PMT** completely. No light at all.
2. In SweepMe!, click the **`run_threshold_scan_dark`** action button.
3. A message appears: *"Cover the R8486 and make sure NO light can reach it…"*. Check, then
   press **OK**.
4. Wait. This takes **about 15–20 minutes**. A covered R8486 gives only ~8 counts per second, so
   each threshold needs up to 30 s to collect enough counts to be meaningful. Progress messages
   appear in SweepMe!'s General tab. **Don't touch the bench or uncover the PMT.**
5. A final message gives a one-line result, for example *"lower bound 6.2 mV, dark counts vanish
   from 20.0 mV"*, and the paths of three files.

### Reading the dark result

Open the **`.svg`** file. It opens in any web browser (double-click, or drag it onto a browser
window).

**Panel (a)** is the count rate at each threshold. The vertical axis is logarithmic, so each
gridline is ten times the one below. Reading from left to right:

1. **A steep fall** from millions of counts per second. That's electronic noise. The grey
   shaded strip at the far left marks where it's so high it can't be dark counts at all.
2. **An elbow**, marked by the orange dashed line, **noise edge**. This is where the noise has
   died away.
3. **A long gentle slope** at a few counts per second. These are the real dark counts.
4. **Red hollow triangles** at the right: thresholds where nothing was counted in 30 s. These
   are drawn as "less than" limits, not as zero, because a short wait can't prove zero.

The green line, **lower bound**, sits just above the noise edge. **Don't go below it.** The red
dashed line, **dark counts vanish**, is labelled *NOT the optimum* — that's the trap from §1.

**Panel (b)** shows how long each threshold took. Green dots reached their count target. Hollow
red ones hit the 30 s limit, so they have fewer counts and wider error bars. Seeing lots of red
on the right is normal.

**If the top of the figure says INVALID in red,** the scan doesn't give a lower bound. The
message says why:

| It says | It means | Do this |
|---|---|---|
| *Light is reaching the tube* | far too many counts for a covered PMT | check the cover for leaks, and that the HV is at its normal value; run it again |
| *nothing is reaching SIGNAL INPUT 1* | no counts at all, not even noise | check the PMT cable is on INPUT 1 and the HV is on |

---

## 5. Step 2 — the light scan

Do this **straight after the dark scan**, without closing SweepMe! or changing the selected
instrument, so the light scan can find the dark result.

1. **Set up a gentle, steady light** on the PMT. A dim, stable source, well attenuated. Aim for
   roughly **10,000 to 100,000 counts per second**. If you don't know what your source gives,
   just try it. The scan measures the light level first and tells you if it's wrong (step 3).
2. Click **`run_threshold_scan_light`**. A message appears: *"Ensure gentle, STEADY light on the
   R8486…"*. Press **OK**.
3. The scan first **checks the light level**. It stops immediately, with nothing else changed,
   if the light is:
   - **too dim** (*"no usable light"*): there's not enough light to see the effect. Increase it a
     little and click again.
   - **too bright** (*"too bright"*): above about a million counts per second the SR400 starts
     missing pulses, which distorts the result. Reduce it and click again.
4. If the light level is fine, the scan sweeps the threshold **up and down three times**, six
   passes in all. This takes **about 5 minutes at ~40,000 counts per second**, and longer when the
   light is dimmer. **Keep the light exactly as it is until it finishes.** Comparing the passes is
   how the scan detects whether the light or the discriminator drifted.
5. The final message gives the recommendation, for example *"recommended A DISC LVL −6.4 mV,
   counting 90 % of photons…"*.

### Reading the light result

Open the light scan's **`.svg`**. The top line, in green, states the recommended level and how it
was chosen. Then four panels:

**(a) Every pass.** All six passes plotted on top of each other. **They should overlap so
closely that they look like one line.** If they visibly fan apart, the light changed during the
scan. The figure will then say NO RECOMMENDATION, and you should steady the source and repeat.

**(b) Zoomed in.** The same data scaled so that the count rate at the *reference level* (the
purple line, normally the valley from panel (c)) is 1.0. The curve drops as the threshold rises,
because it is cutting into real photon pulses. The grey dashed lines mark 1 %,
2 %, 5 % and 10 % loss. The green line is the recommended level. Where it crosses the curve
tells you what fraction of photons you keep.

**(c) Pulse sizes.** This shows how many pulses there are of each size. Look for a **dip**
(purple line, *valley*) followed by a **hump** (*single-PE peak*, near 10 mV). The hump is your
single photons, and the dip is the gap between noise and photons. If there's no hump, the noise
and the photons overlap at this gain. The figure will say so, and that's a sign the tube needs a
preamplifier.

**(d) Signal against background.** This is how the recommendation is made. It combines the two
scans into one score, signal divided by the square root of background (S/√B), for every
threshold. It rises as the noise is cut away, peaks, then falls slowly as photons are lost.

- The **shaded band** is every level within 5 % of the best. Anything in it is a good choice.
- The **green line** is the best one: the recommendation.
- The **red dashed line** far to the right is where the dark counts vanished. The curve there is
  well below its peak, which is the proof that zero dark counts is not the optimum.

If panel (d) says **NOT SHOWN**, the light scan couldn't find this session's dark scan. Its
recommendation then comes from panel (c) alone. Run both scans again, back to back, or send both
CSV files (see §8).

---

## 6. Choosing and setting the threshold

**Normally, use the recommended level.** Anywhere in panel (d)'s shaded band is also fine.

- **Weak signal** (your experiment's real signal is comparable to or smaller than the dark
  counts): use the recommendation. This is the case it is built for.
- **Strong signal** (much more than the dark counts): you can go towards the **lower** end of the
  band and keep slightly more photons. Background matters less when the signal is big.

**To set it**, enter it in the SweepMe! Logger module's GUI:

| Field | Enter | Example |
|---|---|---|
| `Discriminator A slope` | `Fall` | `Fall` |
| `Discriminator A level in V` | the recommended level, **negative**, **in volts** | −6.4 mV → **`-0.0064`** |
| `Counter A input` | `INPUT 1` | `INPUT 1` |

> **Watch the units.** The field is in **volts**, and the scans report **millivolts**. −6.4 mV is
> `-0.0064`, not `-6.4`. The level is negative because the PMT's pulses are negative. The SR400
> accepts levels in 0.2 mV steps, and every level the scans recommend is already one of them.

The level is sent to the SR400 when the measurement starts.

### Messages you might see in the recommendation

- **"strict window empty — preamp would help."** No level is both fully clear of the noise and
  keeps 99 % of the photons. That's expected for this tube at 1000 V without a preamplifier. The
  recommendation is still the best available compromise, and the figure tells you what fraction
  of photons it keeps.
- **"hysteresis"** (marked as a failed check). The discriminator's real level depends slightly on
  whether you approached it from above or below. When you set the level, always come from the
  same direction, or allow the margin the report gives.
- **"below 10 mV: valid only with the cables exactly as they were".** Because of the pickup
  effect in §3. If you move the cables, repeat the scans.

---

## 7. When to repeat the scans

Repeat both scans, dark then light, after you:

- change the PMT **high voltage**: pulse sizes scale with it, so the best level moves;
- **move or replace cables** near the SR400's inputs or DISC outputs;
- change the PMT, or add an amplifier or attenuator;

and occasionally anyway, for example monthly, as a check that nothing has changed.

---

## 8. Where the results are

Each scan writes three files with the same name into

```
C:\Users\Public\Documents\SweepMe!\DataDevices\Logger-Stanford_SR400\
```

| File | What it is |
|---|---|
| `SR400_threshold_scan_dark_<date_time>.txt` | the report, with every number |
| `SR400_threshold_scan_dark_<date_time>.csv` | the raw measurements |
| `SR400_threshold_scan_dark_<date_time>.svg` | the figure, which opens in any web browser |

and the same three for the light scan. The final message of each scan gives the exact paths.

**To get help with a result, send all six files.** The CSV files hold the raw data, so anyone can
redraw the figures from them. On a machine with Python, put both CSV files in one folder and run:

```bash
python selftest.py plot SR400_threshold_scan_light_<date_time>.csv
```

`selftest.py` is in the driver folder. This also restores panel (d) if the two scans weren't run
in the same session.

---

## 9. If a scan won't start

| Message | Do this |
|---|---|
| *select a port first* | choose the SR400's port in the Logger module |
| *the SR400 is counting* | stop the measurement, or press STOP on the SR400, then click again |
| *the SR400 did not answer a status query* | check the instrument is on and connected, and the port and GPIB address are right |
| *the self-test module could not be loaded* | `selftest.py` is missing from the driver folder: copy the whole folder again |
