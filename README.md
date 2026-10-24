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

## Getting logs in

- **CSV files** exported from LifeView: choose them with **Import logs**, or drop them on the window.
- **Life Racing `.LRD` logs**: choose or drop them the same way. The tool opens each one in LifeView, exports the CSV and imports it, then lays the logs out in start-time order. This needs Windows with LifeView installed and no LifeView window already open, and it takes over the mouse for a few seconds per log (about 10 seconds each), so keep your hands off while it runs. CSV copies are kept in `data/exports`. Machines without LifeView can still import those CSV files. The tool never reads or decrypts `.LRD` files itself; it operates LifeView's own export. See `tools/lifeview/README.md`.

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
