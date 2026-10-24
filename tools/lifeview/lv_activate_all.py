"""Activate every channel in LifeView's channel list via window messages (no focus / mouse needed).

Finds the TLRListBox, scrolls it page by page, and double-clicks rows whose checkbox square is
empty. Row positions come from the real scroll offset (the last page is not a whole number of
rows, so rows are not at fixed y values), and the whole list is re-scanned until a pass finds
nothing left to switch on. Run with the venv python that has pywin32 + pillow.
"""
import ctypes
import math
import sys
import time

import win32api
import win32con
import win32gui
import win32ui
from PIL import Image, ImageChops

ROW_H = 16          # px per row
BOX_X = 8           # x of checkbox centre in list client coords
NAME_X = 60         # x used for the double-click
MAX_PASSES = 5


def find_hwnd(cls, parent=None):
    out = []

    def cb(h, _):
        if win32gui.GetClassName(h) == cls:
            out.append(h)
    if parent:
        win32gui.EnumChildWindows(parent, cb, None)
    else:
        win32gui.EnumWindows(cb, None)
    return out


def shot(h):
    _, _, w, hh = win32gui.GetClientRect(h)
    dc = win32gui.GetWindowDC(h)
    mdc = win32ui.CreateDCFromHandle(dc)
    mem = mdc.CreateCompatibleDC()
    bmp = win32ui.CreateBitmap()
    bmp.CreateCompatibleBitmap(mdc, w, hh)
    mem.SelectObject(bmp)
    ctypes.windll.user32.PrintWindow(h, mem.GetSafeHdc(), 3)
    info = bmp.GetInfo()
    img = Image.frombuffer('RGB', (info['bmWidth'], info['bmHeight']),
                           bmp.GetBitmapBits(True), 'raw', 'BGRX', 0, 1)
    win32gui.ReleaseDC(h, dc)
    return img


def wheel(h, notches):
    delta = (120 if notches > 0 else -120) & 0xFFFF
    for _ in range(abs(notches)):
        win32gui.PostMessage(h, win32con.WM_MOUSEWHEEL, win32api.MAKELONG(0, delta),
                             win32api.MAKELONG(1700, 400))
        time.sleep(0.02)
    time.sleep(0.5)


def dblclick(h, x, y):
    lp = win32api.MAKELONG(x, y)
    win32gui.PostMessage(h, win32con.WM_LBUTTONDOWN, win32con.MK_LBUTTON, lp)
    win32gui.PostMessage(h, win32con.WM_LBUTTONUP, 0, lp)
    win32gui.PostMessage(h, win32con.WM_LBUTTONDBLCLK, win32con.MK_LBUTTON, lp)
    win32gui.PostMessage(h, win32con.WM_LBUTTONUP, 0, lp)
    time.sleep(0.15)


def scroll_shift(a, b, max_shift=130):
    """How many px did content move up between screenshot a and b (0 = no movement)."""
    ga, gb = a.convert('L'), b.convert('L')
    best = None
    for sh in range(0, max_shift):
        ca = ga.crop((18, sh, 140, sh + 300))
        cb = gb.crop((18, 0, 140, 300))
        d = sum(ImageChops.difference(ca, cb).histogram()[8:])
        if best is None or d < best[0]:
            best = (d, sh)
    return best[1]


def is_unchecked(img, cy):
    """True/False for a checkbox centred at cy; None if cy does not look like a box centre."""
    c = img.getpixel((BOX_X, cy))
    if c != (255, 255, 255):
        return False
    up = img.getpixel((BOX_X, max(cy - 4, 0)))
    dn = img.getpixel((BOX_X, min(cy + 4, img.size[1] - 1)))
    return True if up == dn == (255, 255, 255) else None


def one_pass(lb, dry):
    """Scan the list top to bottom once. Returns (rows seen, rows switched on, rows already on, skipped)."""
    wheel(lb, 300)                                   # to the top
    abs_off = 0                                      # px the content is scrolled by
    done = set()
    toggled = already = skipped = 0
    while True:
        img = shot(lb)
        h = img.size[1]
        row = math.ceil(abs_off / ROW_H)
        while True:
            cy = ROW_H * row - abs_off + ROW_H // 2  # centre of this row in the current view
            if cy > h - 6:
                break
            if cy >= 8 and row not in done:
                state = is_unchecked(img, cy)
                if state is None:
                    skipped += 1                     # will be looked at again in the next view
                else:
                    if state:
                        if not dry:
                            dblclick(lb, NAME_X, cy)
                        toggled += 1
                    else:
                        already += 1
                    done.add(row)
            row += 1
        wheel(lb, -1)                                # one notch = 96 px, so the shift is easy to measure
        after = shot(lb)
        sh = scroll_shift(img, after)
        if sh == 0:
            break
        abs_off += sh
    return len(done), toggled, already, skipped


def main(dry=False):
    top = [h for h in find_hwnd('LifeViewWnd')][0]
    lb = find_hwnd('TLRListBox', top)[0]
    for n in range(1, MAX_PASSES + 1):
        seen, toggled, already, skipped = one_pass(lb, dry)
        print(f'pass {n}: rows seen {seen}, switched on {toggled}, already on {already}, unreadable {skipped}')
        if toggled == 0 or dry:
            return
    print('warning: channels still off after', MAX_PASSES, 'passes')


if __name__ == '__main__':
    main(dry='--dry' in sys.argv)
