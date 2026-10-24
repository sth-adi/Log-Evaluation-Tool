# LifeView CSV export automation (Windows)

Life Racing `.LRD` logs are encrypted and only LifeView can read them. These scripts drive
LifeView's own CSV export, so the CSVs can then be imported here and shared with people who do
not have LifeView. They do not read or decrypt the `.LRD` files themselves.

```powershell
pip install pywin32 pillow psutil
python tools\lifeview\lv_export_all.py "C:\path\to\logs"        # every log without "<log> ALL.csv"
python tools\lifeview\lv_export_all.py --force "C:\path\to\logs" # redo all
```

For each log it opens a fresh LifeView, accepts the default access prompt (`GENERIC : OK`), switches
every channel on (LifeView only exports active channels), exports `Text File (CSV)` and closes that
LifeView. It will not close a LifeView you already have open unless you pass `--takeover`.

**Keep your hands off the mouse and keyboard while it runs.** The filename box only accepts keys
while the real cursor is over it, so the script moves the mouse for a few seconds per log.

Single steps: `lv_activate_all.py` (switch on every channel, `--dry` to only count) and
`lv_export_csv.py` (export the log that is open now). Tested against LifeView 2.17.14.
