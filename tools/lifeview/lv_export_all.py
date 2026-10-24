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

import lv_activate_all
import lv_export_csv as ex


def top_windows(cls):
    return [h for h in ex.tops() if win32gui.GetClassName(h) == cls]


def close_lifeview():
    for h in top_windows('LifeViewWnd'):
        win32gui.PostMessage(h, win32con.WM_CLOSE, 0, 0)
    t = time.time()
    while ex.lifeview_pids() and time.time() - t < 5:
        time.sleep(0.5)
    for pid in ex.lifeview_pids():                      # still open (a save prompt?): end it
        psutil.Process(pid).kill()
    time.sleep(1)


def open_log(lrd, timeout=60):
    os.startfile(lrd)
    t = time.time()
    clicked = False
    want = os.path.basename(lrd).lower()
    while time.time() - t < timeout:
        time.sleep(1)
        if not clicked:
            for dlg in top_windows(ex.DIALOG):
                buttons = ex.children(dlg, 'LRButton')
                if len(buttons) == 3:                    # "How do you wish to access this file": OK / Cancel / Security
                    ok = min(buttons, key=lambda h: win32gui.GetWindowRect(h)[0])
                    ex.msg_click(ok)                     # default access level, never the Security button
                    clicked = True
        for h in top_windows('LifeViewWnd'):
            if want in win32gui.GetWindowText(h).lower():
                time.sleep(3)                            # let it finish loading
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
    logs = sorted(glob.glob(os.path.join(folder, '*.LRD')) + glob.glob(os.path.join(folder, '*.lrd')))
    todo = [p for p in logs if force or not os.path.exists(os.path.splitext(p)[0] + ' ALL.csv')]
    print(f'{len(logs)} log(s), {len(todo)} to export. Hands off the mouse and keyboard.')
    failed = []
    for lrd in todo:
        name = os.path.basename(lrd)
        try:
            print('opening', name)
            open_log(lrd)
            lv_activate_all.main()
            ex.main(force=True)
        except Exception:                                # keep going with the other logs
            traceback.print_exc()
            failed.append(name)
        finally:
            close_lifeview()
    print('done.', f'{len(todo) - len(failed)} exported' + (f', FAILED: {failed}' if failed else ''))
    sys.exit(1 if failed else 0)


if __name__ == '__main__':
    main()
