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

## Laps

The **Laps** tab turns a track log into lap times and lap-by-lap comparison.

- **Finding laps.** Automatic if the logger records a lap timer or last-lap-time channel. Otherwise choose a beacon signal, a fixed lap length, a lap counter, or type the line-crossing times. The out-lap and in-lap are shown but flagged and left out of "best".
- **Compare.** Every lap is overlaid on one axis, by distance round the lap or by time into the lap. The top chart shows how far ahead or behind the reference lap (the best, unless you click another lap number) each lap is, at every point of the track. The cursor is shared across charts and the legend shows each lap's live value.
- **Distance** comes from integrating a speed channel (vehicleSpeed first). Each lap is rescaled to the reference lap's length so wheel-speed drift does not slide the laps apart.
- **Track map.** Drawn from GPS latitude/longitude when the log has them. Otherwise it is estimated from speed plus GPS heading, or speed plus sideways g, and labelled as an estimate. Colour it by any channel.

- **Across sessions.** Pick "All logs (compare)" to put laps from different days on one overlay. The quickest lap anywhere is the reference unless you click another.
- **Numbers.** Sector times (2 to 8 equal-distance sectors), the **ideal lap** built from the best of every sector, and the highest, lowest or average of any channel for each lap.
- **Hover a chart** and a marker follows on the track map, so you can see where on the circuit a difference happens.

Dyno and bench logs have no start/finish line, so the tab says so instead of guessing.

## Views and downloads

- **Views** (top bar) saves the plots, tab and lap settings under a name. A view stores channel names, not logs, so it works on whichever logs are open. **Export** writes it to a small `.letview.json` file you can send to a teammate; **Open a view file** loads one.
- **Download the data** (Manage on any log): the whole log, or just the plotted channels in the zoomed window, as CSV or Parquet. Calculated channels are included and time starts at zero.

## Heatmap

Analysis > **Heatmap** puts samples from every open log on an x/y grid, for example RPM across and throttle up.

- **Show** the number of samples (where the engine spends its time) or any other channel summarised in each cell: average, highest, lowest or spread. Average lambda over RPM and throttle is the usual engine-map view.
- **Target** colours cells by how far they are from a value you choose (grey is on target, blue below, red above). **± range** sets how far from the target the colours saturate.
- Cell values are written in the cells when they are big enough. Hover a cell to read its range, value, sample count and roughly how many seconds were spent in it.
- **Hide under N samples** leaves out thin cells, and **Ignore extremes** stops a few outliers (fuel cut reads lambda 3 or more) from washing out the colours.
- The zoomed window from the Plots tab is respected.

## Pulls

The **Pulls** tab is for dyno and engine runs, and needs only an `rpm` channel. It finds each pull (RPM climbing steadily, such as a dyno sweep) in every open log, and plots them against RPM instead of time so runs line up.

- **Power and torque** are worked out from how quickly the roller (or car) speeds up, the inertia method. Without a mass they are relative, with the strongest pull set to 100. Enter the **effective mass** (the roller's inertia expressed as a mass, in kg) to get kW and N·m. It leaves out drag and driveline losses, so use it to compare runs rather than as a calibrated figure.
- **Power against the reference pull** shows, at each RPM, how much stronger or weaker every other pull is. Click a pull number to change the reference. This is the "did the change help?" chart.
- **Any channel against RPM**: lambda, ignition, fuel, MAP, coolant and so on, with the cursor shared across charts and live values for every pull in the legend.
- Pulls where the roller did not speed up are marked **Rev only** and start unticked.
- Engine starts are ignored, and a short dip (a gear change) does not split a pull in two. **Sensitivity** and **Smallest pull** adjust what counts.

## Live telemetry

The **Live** tab follows data as it arrives: a value and a rolling plot for each channel you pick, over the last 10 to 120 seconds. **Save as log** keeps what the tool holds as an ordinary log, so lap analysis, reports and downloads work on a recorded session.

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
