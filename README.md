# Log Evaluation Tool

A local, offline log evaluation tool for the UWE Formula Student hybrid car. It imports CSV logs from the engine control unit (ECU, Life Racing F88R) and the hybrid control unit (HCU), shows them as stacked plots on a shared time axis, and lets you align the two logs in time. See [PRODUCT.md](PRODUCT.md) for goals and [design/MASTER.md](design/MASTER.md) for the design system.

The tool only reads files you give it. It has no way to talk to the car.

## Status

Early scaffold. Working today: CSV import with sniffing and a record of every assumption, fast downsampled plotting of large logs, synced zoom and cursor, a live readout column, and a manual time offset per log.

Not done yet: automatic ECU/HCU alignment, derived channels (power, energy), the HCU mode timeline, lap analysis, live telemetry.

The channel names in `samples/synthetic` are invented and are not the real F88R or HCU formats. When you have real logs, put them in `samples/` and the importer's assumptions will show what it guessed.

The backend has automated tests. The Windows scripts and the browser UI have not yet been run on a real Windows machine, so expect to fix small things on first use.

## Open it

Double-click **`Log Evaluation Tool.bat`** (there is also a shortcut on the Desktop). It starts the tool, waits until it is ready and opens http://127.0.0.1:8000 in your browser. If it is already running it just opens the page. A minimised window stays in the taskbar while the tool runs; close that window to stop it. Binds to 127.0.0.1 only, so nothing is visible on the network.

## Giving it to someone else

Build a package that runs on any Windows 10/11 PC with nothing installed (no Python, no Node, no admin rights, no internet):

```powershell
.\scripts\build-portable.ps1        # about 2 minutes; writes release\LogEvaluationTool-win64.zip (about 80 MB)
```

Send that zip. The other person unzips it anywhere and double-clicks **`Log Evaluation Tool.bat`**; their browser opens the tool. It carries its own private Python and every package. Their logs and library are kept in `%LOCALAPPDATA%\Log Evaluation Tool`, so unpacking a newer version later keeps them. Converting `.LRD` logs still needs LifeView on that PC (CSV import does not). The zip is built from your working checkout, so run the tests and `npm run build` first.

## The library

Every converted or imported log is kept in the **Library** (top bar). Closing a log in the Manage drawer only takes it off the screen; **Library > Add** brings it back, with no conversion. Logs are recognised by their contents, so importing the same data again (even from another folder, or a new copy of the `.LRD`) opens the existing log and says so, rather than storing a duplicate. **Open folder** shows the CSV copies in Explorer.

## Getting logs in

- **CSV files** exported from LifeView: choose them with **Import logs**, or drop them on the window.
- **Life Racing `.LRD` logs**: choose or drop them the same way. The tool opens each one in LifeView, exports the CSV and imports it, then lays the logs out in start-time order. This needs Windows with LifeView installed and no LifeView window already open, and it takes over the mouse for a few seconds per log (about 10 seconds each), so keep your hands off while it runs. CSV copies are kept in `data/exports`. Machines without LifeView can still import those CSV files. The tool never reads or decrypts `.LRD` files itself; it operates LifeView's own export. See `tools/lifeview/README.md`.

## Finding your way round

The top bar has three modes. **Plots** shows channels over time; **Review** lists what the tool found wrong on its own; **Analyse** opens a list of tools grouped by what you want to find out (one channel, two channels, compare runs, find problems). **Logs** adds files or opens ones you already have, and **More** holds saved views, the report and live data. Settings you rarely change sit behind an **Options** or **Settings** button.

## Review

**Review** checks every open log as soon as it is imported and lists what does not fit. Nothing has to be set up first. A number on the tab says how many things need a look.

The checks, none of which need a limit from you:

- **Switches and what they should cause.** The tool finds switches (a request, a mode, a flag) that are nearly always followed by a movement in some other channel, then reports the times they were not. For example, a gear cut request that is followed by an ignition cut 19 times out of 26. It looks for what the misses have in common (here: six of the seven were at standstill) and puts the one that does not fit first. A state with several values needs a stronger link than an on/off switch, and a single miss is only reported when chance almost never produces the response.
- **The ECU's own fault channels**, only while the engine runs. A fault that reads the same way in most of the running time is shown as "probably normal" (a missing-tooth wheel reporting its long gap, for example), not as an alarm.
- **Reading differently than in earlier runs, at the same load.** Each log is compared with the ones before it, only where the engine was at the same rpm, throttle and gear, so warming up and changes of load do not count. On the F88 logs this shows temperatures and oil pressure moving from run to run (oil pressure falling as the oil warms, for example). A change may be deliberate, a tune or part swap, or wear; the tool only says it changed. Timers, distances and running maximums, which only count up, are skipped, and a shift under about 1% of a channel's own level is ignored.
- **Channels that stop following each other.** The tool finds the channels that move together in every log (two rpm sensors, the three cylinders, a base and a final value) and flags the stretches, a second or longer, where one of them leaves the others. A sensor that only lags its twin by up to half a second is not a break. When one channel breaks with most of its partners while they keep agreeing with each other, that channel is named. On the F88 logs this shows the oil-pressure trip level leaving rpm for about six seconds, twice, in the dyno run, and the base fuel value running past the final one. The tool cannot say which of two channels is wrong, only that they stopped agreeing.
- **Sensors that go flat.** A channel that moves in other logs but does not move at all in one run. A channel that never moves anywhere is listed once as unused.
- **Dropouts**: a channel that goes blank while the others keep logging, and stretches with no samples.

Each finding says what it saw and the numbers behind it, and **Show** jumps to that moment on the plots with the relevant channels. **This is normal** stops a finding being raised again; it stays under *Marked as normal* so you can bring it back. A finding is not a diagnosis: it says the log does not match how the car behaves in your other logs, so it gets stronger as you add logs.

**Your limits** (at the bottom of Review) are the only thing you set by hand, for physical things the logs cannot tell on their own, such as a minimum oil pressure or a maximum coolant temperature: a channel, above or below a value, for how many seconds, and whether it counts only while the engine runs.

All checks are deterministic, so the same logs always give the same findings. The code is `backend/app/review.py`.

**State numbering.** Text channels such as gear are stored as numbers. Each label now keeps one number across every log (the list is `data/state_labels.json`), so a rule or a plot comparing logs always means the same gear. Logs imported earlier were renumbered once.

## Laps

**Analyse > Laps** turns a track log into lap times and lap-by-lap comparison.

- **Finding laps.** Automatic if the logger records a lap timer or last-lap-time channel. Otherwise choose a beacon signal, a fixed lap length, a lap counter, or type the line-crossing times. The out-lap and in-lap are shown but flagged and left out of "best".
- **Compare.** Every lap is overlaid on one axis, by distance round the lap or by time into the lap. The top chart shows how far ahead or behind the reference lap (the best, unless you click another lap number) each lap is, at every point of the track. The cursor is shared across charts and the legend shows each lap's live value.
- **Distance** comes from integrating a speed channel (vehicleSpeed first). Each lap is rescaled to the reference lap's length so wheel-speed drift does not slide the laps apart.
- **Track map.** Drawn from GPS latitude/longitude when the log has them. Otherwise it is estimated from speed plus GPS heading, or speed plus sideways g, and labelled as an estimate. Colour it by any channel.

- **Across sessions.** Pick "All logs (compare)" to put laps from different days on one overlay. The quickest lap anywhere is the reference unless you click another.
- **Numbers.** Sector times (2 to 8 equal-distance sectors), the **ideal lap** built from the best of every sector, and the highest, lowest or average of any channel for each lap.
- **Hover a chart** and a marker follows on the track map, so you can see where on the circuit a difference happens.

Dyno and bench logs have no start/finish line, so the tool says so instead of guessing.

## Views and downloads

- **Views** (top bar) saves the plots, tab and lap settings under a name. A view stores channel names, not logs, so it works on whichever logs are open. **Export** writes it to a small `.letview.json` file you can send to a teammate; **Open a view file** loads one.
- **Channels read at different rates.** A log has one row per sample, but each channel is only measured as often as its sensor reports (on the F88 logs rpm about 125 times a second, throttle 50, coolant and speed 25, against 250 rows a second). The file repeats a slow channel's last value until the next reading. The tool estimates each channel's real rate from when its value changes (hover a channel in the search list to see it), then `deriv()` follows the line through the real readings instead of the steps, and the spectrum stops at half the channel's real rate. The estimate is approximate: a channel that is simply steady cannot be told from a slow one, so it is left alone.
- **State channels** (gear, run mode, flags) draw as coloured bands with their labels instead of a stepped line. A plot switches to bands by itself when every channel in it is a state, and a Line / Bands switch appears in its header whenever both make sense. Two or more state channels in one plot stack as rows. A channel counts as a state if it has labels, or holds only whole numbers across a small range for the whole log, so zooming never changes how it is drawn.
- **Calculated channels** (Manage on any log): write a formula over your channels, or pick a template (acceleration, distance, RPM rise rate, air-fuel ratio and so on). Only templates whose channels exist in that log are offered, and the formula fills in so you can adjust it before adding.
- **Download the data** (Manage on any log): the whole log, or just the plotted channels in the zoomed window, as CSV or Parquet. Calculated channels are included and time starts at zero.

## File formats

Drop or import any of these. Everything ends up as the same kind of log, so every tab works on all of them.

| Format | Notes |
| --- | --- |
| `.LRD` (Life Racing) | Converted through LifeView's own CSV export, see Getting logs in. |
| `.csv`, `.txt`, `.tsv` | Delimiter, header, units row, millisecond time and `####` gaps are detected. |
| `.xlsx` | The first sheet; the first row names the columns, and an optional second row gives units. |
| `.parquet` | Including the files the tool itself downloads. |
| `.mf4`, `.mdf`, `.dat` | MDF measurement files, the usual format from CAN loggers and automotive tools. Channels recorded at different rates are put on one time base at the fastest rate (interpolated), and units are kept. |
| `.asc`, `.blf`, `.trc` | CAN bus logs. A CAN log holds raw frames, so you are asked for the **DBC file** that describes them; it is kept in your library for next time. See below. |

The same file imported twice is recognised and opened rather than stored again.

### CAN logs

Import a `.asc`, `.blf` or `.trc` log and choose the DBC file (add it once, then pick it from the list). Each signal in the DBC becomes a channel with its scaling, unit and, for signals with named values such as gears, state labels.

- Signals arrive at different rates, so they are put on one time base at the fastest message rate (between 2 ms and 1 s), each value held until its next frame. A signal that goes silent for ten of its own periods shows as a gap instead of a flat line.
- Frames whose id is not in the DBC are counted and reported when you import, with the most common ids, so a wrong or incomplete DBC is obvious. The same goes for frames of the wrong length, and error frames.
- A log that matches nothing in the DBC is refused, and the message lists the ids it does contain.
- Decoding uses python-can and cantools. Raw bus logging inside an `.mf4` file is not decoded yet.

## Summary

Analyse > **Summary** gives one row per log and one column per metric, so runs can be compared at a glance. A metric is a channel, an aggregate (highest, lowest, average, median, 95th percentile, spread, first, last, total, or seconds), and an optional **only when** condition written with channel names, for example average `lam1` only when `tps1 > 90`.

- **Quick add** suggests common metrics (peak RPM, top speed, average lambda at full throttle, time at full throttle, hottest coolant, lowest battery voltage) for the channels your logs have.
- **Compare to** picks one log as the baseline and shows how far each other log is from it under every value.
- The zoomed window is respected, so you can compare just one stretch of each run.
- Metrics are remembered in this browser and saved with a view, so a teammate who opens your view file gets the same table.

## Heatmap

Analyse > **Heatmap** puts samples from every open log on an x/y grid, for example RPM across and throttle up.

- **Show** the number of samples (where the engine spends its time) or any other channel summarised in each cell: average, highest, lowest or spread. Average lambda over RPM and throttle is the usual engine-map view.
- **Target** colours cells by how far they are from a value you choose (grey is on target, blue below, red above). **± range** sets how far from the target the colours saturate.
- Cell values are written in the cells when they are big enough. Hover a cell to read its range, value, sample count and roughly how many seconds were spent in it.
- **Hide under N samples** leaves out thin cells, and **Ignore extremes** stops a few outliers (fuel cut reads lambda 3 or more) from washing out the colours.
- The zoomed window from the Plots tab is respected.

## Pulls

**Analyse > Pulls** is for dyno and engine runs, and needs only an `rpm` channel. It finds each pull (RPM climbing steadily, such as a dyno sweep) in every open log, and plots them against RPM instead of time so runs line up.

- **Power and torque** are worked out from how quickly the roller (or car) speeds up, the inertia method. Without a mass they are relative, with the strongest pull set to 100. Enter the **effective mass** (the roller's inertia expressed as a mass, in kg) to get kW and N·m. It leaves out drag and driveline losses, so use it to compare runs rather than as a calibrated figure.
- **Power against the reference pull** shows, at each RPM, how much stronger or weaker every other pull is. Click a pull number to change the reference. This is the "did the change help?" chart.
- **Any channel against RPM**: lambda, ignition, fuel, MAP, coolant and so on, with the cursor shared across charts and live values for every pull in the legend.
- Pulls where the roller did not speed up are marked **Rev only** and start unticked.
- Engine starts are ignored, and a short dip (a gear change) does not split a pull in two. **Sensitivity** and **Smallest pull** adjust what counts.

## Live telemetry

**More > Live data** follows data as it arrives: a value and a rolling plot for each channel you pick, over the last 10 to 120 seconds. **Save as log** keeps what the tool holds as an ordinary log, so lap analysis, reports and downloads work on a recorded session.

Choose where the data comes from:

| Source | What it is |
| --- | --- |
| Simulated car | A made-up car lapping a circuit. Try everything with no hardware. |
| Replay a saved log | Plays a log from the library back in real time, at 1x to 10x. |
| UDP port | Lines of data sent to this computer over the network. |
| Serial / USB port | The same lines read from a COM port (uses pyserial, which is included). |
| Pushed by another program | A bridge posts rows to `POST /api/live/ingest`. See `tools/live_bridge_example.py`. |

A line is JSON, `{"t": 12.34, "rpm": 8200, "vehicleSpeed": 71.5}` (`t` in seconds, optional), or CSV whose first non-numeric line names the columns. Channels can appear at any time.

The tool keeps the latest 200,000 rows in memory (about 33 minutes at 100 rows a second; set `LET_LIVE_ROWS` to change it). Longer sessions lose their start, and the saved log says so.

How the car's data reaches the laptop is the one part that depends on your hardware. Write that as a small bridge that posts rows (the example shows how), and the rest of the screen needs no changes.

## Run it on Windows

Needs Python 3.10+ and, for the first build, Node.js 20+.

```powershell
.\scripts\setup.ps1
.\scripts\run.ps1
```

If PowerShell says running scripts is disabled on your account, run `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned` once and try again.

The tool opens at http://127.0.0.1:8000. Use **Import logs**, or drop CSV files onto the window. To try it without real logs:

```powershell
.\.venv\Scripts\python tools\generate_logs.py --out samples\synthetic
```

then import `synthetic_ecu.csv` and `synthetic_hcu.csv`. The HCU log starts 2.35 s after the ECU log, so set the HCU time offset to `2.35` to line them up.

### On a locked-down laptop (no PyPI or npm)

On any machine with internet, run `scripts\build-release.ps1 -PythonVersion 3.12` (use the Python version installed on the target laptop). Copy the zip it creates to the laptop, unzip it, and run `setup.ps1` then `run.ps1`. Setup uses the bundled wheels and prebuilt frontend and needs no network.

## Develop

```bash
python -m venv .venv && .venv/bin/pip install -r backend/requirements.txt -r backend/requirements-dev.txt
.venv/bin/python -m pytest backend          # backend tests
.venv/bin/python -m uvicorn backend.app.main:app --reload --port 8000
cd frontend && npm install && npm run dev   # http://localhost:5173, proxies /api to :8000
```

## Layout

```
backend/    FastAPI app: importer (CSV sniffing), downsampler, Parquet storage, API
frontend/   React + TypeScript + uPlot UI, design tokens in src/styles/tokens.css
tools/      synthetic ECU + HCU log generator
design/     design system
samples/    sample logs (synthetic for now)
scripts/    Windows setup, run and offline-release scripts
```

Data is stored under `data/` (override with the `LET_DATA_DIR` environment variable).
