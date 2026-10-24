"""Export the log currently open in LifeView to a full-channel CSV, hands-free.

Usage (venv python with pywin32 + pillow + psutil):
    python lv_export_csv.py [--force] [--outname NAME]

Drives LifeView's own File > export To > Text File (CSV) flow.  The filename edit only
accepts keys while the real cursor is over it, so it briefly moves the mouse and
types real key events; everything else is done by window messages.  The CSV is
written to LifeView's working folder (the folder picker is left on its default).
"""
import ctypes
import glob
import os
import re
import sys
import time

import psutil
import win32api
import win32con
import win32gui
import win32process

TMP_NAME = 'x'   # any non-empty name works: the new file is renamed afterwards
u = ctypes.windll.user32
u.SetProcessDPIAware()
DIALOG = 'ATL:006F2048'


def lifeview_pids():
    return [p.pid for p in psutil.process_iter(['name']) if p.info['name'] == 'LifeView.exe']


def tops():
    out, pids = [], lifeview_pids()
    win32gui.EnumWindows(lambda h, _: out.append(h) if win32process.GetWindowThreadProcessId(h)[1] in pids
                         and win32gui.IsWindowVisible(h) else None, None)
    return out


def children(h, cls):
    out = []
    win32gui.EnumChildWindows(h, lambda c, _: out.append(c) if win32gui.GetClassName(c) == cls else None, None)
    return out


def wait_new(before, cls, timeout=8):
    t = time.time()
    while time.time() - t < timeout:
        for h in tops():
            if h not in before and win32gui.GetClassName(h) == cls:
                return h
        time.sleep(0.04)
    raise RuntimeError('timed out waiting for new ' + cls)


def msg_click(h, x=10, y=8):
    lp = win32api.MAKELONG(x, y)
    win32gui.PostMessage(h, win32con.WM_LBUTTONDOWN, win32con.MK_LBUTTON, lp)
    win32gui.PostMessage(h, win32con.WM_LBUTTONUP, 0, lp)
    time.sleep(0.1)


def front(h):
    tid = win32process.GetWindowThreadProcessId(h)[0]
    fg = win32process.GetWindowThreadProcessId(u.GetForegroundWindow())[0]
    u.keybd_event(0x12, 0, 0, 0)
    u.keybd_event(0x12, 0, 2, 0)
    u.AttachThreadInput(fg, tid, True)
    u.BringWindowToTop(h)
    u.SetForegroundWindow(h)
    u.AttachThreadInput(fg, tid, False)
    time.sleep(0.15)
    if u.GetForegroundWindow() != h:
        raise RuntimeError('could not foreground the filename dialog; not typing')


def real_click(h):
    l, t, r, b = win32gui.GetWindowRect(h)
    u.SetCursorPos((l + r) // 2, (t + b) // 2)
    time.sleep(0.1)
    u.mouse_event(2, 0, 0, 0, 0)
    time.sleep(0.04)
    u.mouse_event(4, 0, 0, 0, 0)
    time.sleep(0.1)


def tap(vk):
    sc = u.MapVirtualKeyW(vk, 0)
    u.keybd_event(vk, sc, 0, 0)
    time.sleep(0.05)
    u.keybd_event(vk, sc, 2, 0)
    time.sleep(0.05)


VK_SHIFT = 0x10
SPECIAL = {' ': (0x20, False), '-': (0xBD, False), '_': (0xBD, True), '#': (0x33, True),
           '.': (0xBE, False)}


def type_text(s):
    for c in s:
        if c.isalnum():
            shift = c.isupper()
            vk = ord(c.upper())
        elif c in SPECIAL:
            vk, shift = SPECIAL[c]
        else:
            raise ValueError('cannot type %r' % c)
        if shift:
            u.keybd_event(VK_SHIFT, 0, 0, 0)
        tap(vk)
        if shift:
            u.keybd_event(VK_SHIFT, 0, 2, 0)


def current_log():
    top = [h for h in tops() if win32gui.GetClassName(h) == 'LifeViewWnd'][0]
    m = re.search(r'([A-Za-z]:\\.*\.LRD)', win32gui.GetWindowText(top), re.I)
    return m.group(1) if m else None


def activate_all(top=None):
    """Channel > Add > All: switches on every channel in one go (LifeView only exports active ones)."""
    top = top or [h for h in tops() if win32gui.GetClassName(h) == 'LifeViewWnd'][0]
    chan_btn = sorted(children(top, 'LRButton'), key=lambda h: win32gui.GetWindowRect(h)[0])[4]  # 5th: Channel
    before = set(tops())
    msg_click(chan_btn)
    menu = wait_new(before, 'TLRListBox')
    before = set(tops())
    msg_click(menu, 60, 14)                               # "Add"
    dlg = wait_new(before, DIALOG)                        # "Select channels"
    all_btn = max(children(dlg, 'LRButton'), key=lambda h: win32gui.GetWindowRect(h)[0])  # "All - F10"
    msg_click(all_btn)                                    # adds everything and closes the dialog
    t = time.time()
    while dlg in tops() and time.time() - t < 5:
        time.sleep(0.04)


def export(outname):
    top = [h for h in tops() if win32gui.GetClassName(h) == 'LifeViewWnd'][0]
    file_btn = min(children(top, 'LRButton'),
                   key=lambda h: win32gui.GetWindowRect(h)[0])      # File is the leftmost
    before = set(tops())
    msg_click(file_btn)
    menu = wait_new(before, 'TLRListBox')
    before = set(tops())
    msg_click(menu, 60, 165)                              # "export To"
    dlg = wait_new(before, DIALOG)
    lb = children(dlg, 'TLRListBox')[0]
    btns = children(dlg, 'LRButton')
    msg_click(lb, 40, 47)                                 # Text File (CSV)
    before = set(tops())
    msg_click(btns[0])                                    # OK
    dlg2 = wait_new(before, DIALOG)
    ed = children(dlg2, 'LREdit')[0]
    front(dlg2)
    real_click(ed)
    type_text(outname)
    before = set(tops())
    msg_click(children(dlg2, 'LRButton')[0])              # OK
    picker = wait_new(before, 'TLRListBox')               # folder picker, default folder
    before = set(tops())
    msg_click(picker, 100, 12)                            # SELECT
    rate = wait_new(before, DIALOG)                       # sample-rate dialog, Auto
    msg_click(children(rate, 'LRButton')[0])              # OK


def main(force=None, outname=None, log=None):
    """Export the log open in LifeView. Pass ``log`` (its .LRD path) to skip reading it from the title."""
    force = ('--force' in sys.argv) if force is None else force
    log = log or current_log()
    if not log:
        sys.exit('no .LRD open in LifeView')
    folder = os.path.dirname(log)
    if outname is None:
        outname = (sys.argv[sys.argv.index('--outname') + 1] if '--outname' in sys.argv
                   else os.path.splitext(os.path.basename(log))[0] + ' ALL')
    target = os.path.join(folder, outname + '.csv')
    if os.path.exists(target) and not force:
        print('exists, skipping:', target)
        return
    # Type a short temporary name (typing is slow and needs the cursor to stay over the box, so a
    # long name can get cut off), then rename whatever new CSV appears to the real name.
    started = time.time() - 1
    export(TMP_NAME)
    last, t0, found = -1, time.time(), None
    while time.time() - t0 < 180:                         # wait until the new file stops growing
        time.sleep(0.4)
        new = [p for p in glob.glob(os.path.join(folder, '*.csv'))
               if os.path.getmtime(p) >= started and os.path.abspath(p) != os.path.abspath(target)]
        found = max(new, key=os.path.getmtime) if new else None
        sz = os.path.getsize(found) if found else -1
        if sz > 0 and sz == last:
            os.replace(found, target)
            print('exported', target, sz, 'bytes')
            return
        last = sz
    sys.exit('export did not finish in ' + folder)


if __name__ == '__main__':
    main()
