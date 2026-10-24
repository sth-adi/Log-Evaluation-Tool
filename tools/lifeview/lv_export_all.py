"""Export every .LRD log in this folder to a full-channel CSV, hands-free.

    python lv_export_all.py [--force] [--takeover] [folder]

For each log without a "<log> ALL.csv" next to it: open the log in a fresh LifeView, accept the
default access prompt, switch every channel on, export CSV through LifeView's own export, and
close that LifeView again. Needs the venv python with pywin32, pillow and psutil.

Hands off the mouse and keyboard while it runs: the filename box only takes keys while the real
cursor is over it. A LifeView that is already open is never closed unless you pass --takeover.
"""
import glob
import os
import sys
import time
import traceback

import psutil
import win32api
import win32con
import win32gui
import win32process

import lv_export_csv as ex


def top_windows(cls):
    return [h for h in ex.tops() if win32gui.GetClassName(h) == cls]


def close_lifeview():
    for h in top_windows('LifeViewWnd'):
        win32gui.PostMessage(h, win32con.WM_CLOSE, 0, 0)
    t = time.time()
    while ex.lifeview_pids() and time.time() - t < 3:
        time.sleep(0.1)
    for pid in ex.lifeview_pids():                      # still open (a save prompt?): end it
        psutil.Process(pid).kill()
    time.sleep(0.2)


def wait_ready(top, timeout=20):
    """The log is loaded once the Channel menu buttons exist and the channel list has been drawn."""
    t = time.time()
    while time.time() - t < timeout:
        if len(ex.children(top, 'LRButton')) >= 12 and ex.children(top, 'TLRListBox'):
            time.sleep(0.4)
            return
        time.sleep(0.1)


def open_log(lrd, timeout=60):
    os.startfile(lrd)
    t = time.time()
    clicked = False
    want = os.path.basename(lrd).lower()
    while time.time() - t < timeout:
        time.sleep(0.15)
        if not clicked:
            for dlg in top_windows(ex.DIALOG):
                buttons = ex.children(dlg, 'LRButton')
                if len(buttons) == 3:                    # "How do you wish to access this file": OK / Cancel / Security
                    ok = min(buttons, key=lambda h: win32gui.GetWindowRect(h)[0])
                    ex.msg_click(ok)                     # default access level, never the Security button
                    clicked = True
        for h in top_windows('LifeViewWnd'):
            if want in win32gui.GetWindowText(h).lower():
                wait_ready(h)
                return
    raise RuntimeError('LifeView did not open ' + os.path.basename(lrd))


def main():
    args = [a for a in sys.argv[1:] if not a.startswith('--')]
    folder = args[0] if args else os.path.dirname(os.path.abspath(__file__))
    force = '--force' in sys.argv
    if ex.lifeview_pids():
        if '--takeover' not in sys.argv:
            sys.exit('LifeView is already open. Close it, or pass --takeover to let this script close it.')
        close_lifeview()
    # Windows paths are case-insensitive, so '*.LRD' and '*.lrd' both match every file: de-duplicate
    logs = sorted({os.path.normcase(p): p for p in glob.glob(os.path.join(folder, '*.[Ll][Rr][Dd]'))}.values())
    todo = [p for p in logs if force or not os.path.exists(os.path.splitext(p)[0] + ' ALL.csv')]
    print(f'{len(logs)} log(s), {len(todo)} to export. Hands off the mouse and keyboard.')
    failed = []
    for lrd in todo:
        name = os.path.basename(lrd)
        try:
            print('opening', name, flush=True)
            t0 = time.perf_counter()
            open_log(lrd)
            t1 = time.perf_counter()
            ex.activate_all()
            t2 = time.perf_counter()
            ex.main(force=True)
            t3 = time.perf_counter()
            print(f'  open {t1 - t0:.1f}s, activate {t2 - t1:.1f}s, export {t3 - t2:.1f}s', flush=True)
        except Exception:                                # keep going with the other logs
            traceback.print_exc()
            failed.append(name)
        finally:
            close_lifeview()
    print('done.', f'{len(todo) - len(failed)} exported' + (f', FAILED: {failed}' if failed else ''))
    sys.exit(1 if failed else 0)


if __name__ == '__main__':
    main()
