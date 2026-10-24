"""One-file HTML run report: log details, statistics, events and plots as inline SVG.

The page has no scripts, fonts or links, so it opens offline anywhere and prints cleanly.
"""

from __future__ import annotations

import math
from datetime import datetime
from html import escape

import numpy as np

PALETTE = ["#b8650a", "#0b7fa6", "#1d8f50", "#6a4fc4", "#c4457a", "#444444", "#2f5fd0", "#7a8a0a"]
W, H, PAD_L, PAD_R, PAD_T, PAD_B = 920, 150, 58, 8, 8, 22


def _fmt(v: float | None) -> str:
    if v is None or not math.isfinite(v):
        return "–"
    a = abs(v)
    d = 0 if a >= 1000 else 1 if a >= 100 else 2 if a >= 10 else 3
    return f"{v:,.{d}f}"


def _ticks(lo: float, hi: float, n: int = 5) -> list[float]:
    if hi <= lo:
        return [lo]
    raw = (hi - lo) / n
    mag = 10 ** math.floor(math.log10(raw))
    step = min((m * mag for m in (1, 2, 2.5, 5, 10) if m * mag >= raw), default=raw)
    first = math.ceil(lo / step) * step
    out, v = [], first
    while v <= hi + 1e-9:
        out.append(round(v, 10))
        v += step
    return out


def plot_svg(
    series: list[tuple[str, str, np.ndarray, np.ndarray]],
    x0: float,
    x1: float,
    events: list[dict],
    show_x: bool,
) -> str:
    """series = [(name, unit, t, y)]; one shared y scale per plot."""
    ys = np.concatenate([s[3][np.isfinite(s[3])] for s in series]) if series else np.array([])
    lo, hi = (float(ys.min()), float(ys.max())) if ys.size else (0.0, 1.0)
    if lo == hi:
        lo, hi = lo - 1, hi + 1
    pad = (hi - lo) * 0.06
    lo, hi = lo - pad, hi + pad
    pw, ph = W - PAD_L - PAD_R, H - PAD_T - PAD_B
    sx = lambda t: PAD_L + (t - x0) / (x1 - x0) * pw  # noqa: E731
    sy = lambda v: PAD_T + (1 - (v - lo) / (hi - lo)) * ph  # noqa: E731
    out = [
        f'<svg viewBox="0 0 {W} {H}" role="img" xmlns="http://www.w3.org/2000/svg">'
        f'<clipPath id="plotclip"><rect x="{PAD_L}" y="{PAD_T}" width="{pw}" height="{ph}"/></clipPath>'
    ]
    for e in events:
        a, b = max(sx(e["t_start"]), PAD_L), min(sx(max(e["t_end"], e["t_start"] + (x1 - x0) / pw)), PAD_L + pw)
        if b > a:
            out.append(f'<rect x="{a:.1f}" y="{PAD_T}" width="{b - a:.1f}" height="{ph}" fill="#e11d2a" opacity="0.12"/>')
    for v in _ticks(lo, hi, 4):
        y = sy(v)
        out.append(f'<line x1="{PAD_L}" x2="{PAD_L + pw}" y1="{y:.1f}" y2="{y:.1f}" stroke="#ddd"/>')
        out.append(f'<text x="{PAD_L - 6}" y="{y + 3.5:.1f}" text-anchor="end">{escape(_fmt(v))}</text>')
    if show_x:
        for v in _ticks(x0, x1, 8):
            x = sx(v)
            out.append(f'<line x1="{x:.1f}" x2="{x:.1f}" y1="{PAD_T}" y2="{PAD_T + ph}" stroke="#eee"/>')
            out.append(f'<text x="{x:.1f}" y="{H - 6}" text-anchor="middle">{escape(_fmt(v))} s</text>')
    out.append(f'<rect x="{PAD_L}" y="{PAD_T}" width="{pw}" height="{ph}" fill="none" stroke="#999"/>')
    for i, (_name, _unit, t, y) in enumerate(series):
        path, pen = [], False
        for tt, vv in zip(t, y):
            if not math.isfinite(vv):
                pen = False
                continue
            path.append(f"{'L' if pen else 'M'}{sx(tt):.1f},{sy(vv):.1f}")
            pen = True
        out.append(f'<path d="{" ".join(path)}" fill="none" stroke="{PALETTE[i % len(PALETTE)]}" stroke-width="1.2" clip-path="url(#plotclip)"/>')
    out.append("</svg>")
    return "".join(out)


CSS = """
body{font:13px/1.45 "Segoe UI",system-ui,sans-serif;color:#161616;margin:0;padding:28px 36px;max-width:1000px}
h1{font-size:22px;margin:0 0 2px}h2{font-size:15px;margin:26px 0 8px;border-bottom:2px solid #161616;padding-bottom:3px}
.sub{color:#555;margin:0 0 14px}table{border-collapse:collapse;width:100%;font-variant-numeric:tabular-nums}
th,td{padding:4px 8px;border-bottom:1px solid #ddd;text-align:right}th:first-child,td:first-child{text-align:left}
thead th{font-weight:600;color:#444;border-bottom:1px solid #999}.plot{margin:10px 0 2px}.plot h3{font-size:13px;margin:0}
.key{display:inline-block;width:14px;height:3px;margin:0 5px 2px 10px;vertical-align:middle}svg{width:100%;height:auto;font:10px sans-serif;fill:#555}
.meta{display:grid;grid-template-columns:max-content 1fr;gap:2px 16px}.meta dt{color:#555}.meta dd{margin:0}
.note{color:#555;font-size:12px}@media print{body{padding:0}h2{break-after:avoid}.plot{break-inside:avoid}}
"""


def render(
    rec: dict,
    stats: dict[str, dict],
    plots: list[list[tuple[str, str, np.ndarray, np.ndarray]]],
    events: list[dict],
    x0: float,
    x1: float,
) -> str:
    title = escape(rec["label"])
    started = rec.get("started_at") or "unknown"
    rows = []
    for name, s in stats.items():
        unit = next((c["unit"] for c in rec["channels"] if c["name"] == name), "")
        if not s.get("count"):
            rows.append(f"<tr><td>{escape(name)}</td><td colspan='7'>no valid samples</td></tr>")
            continue
        cells = "".join(f"<td>{_fmt(s[k])}</td>" for k in ("min", "max", "mean_time_weighted", "median", "std", "p95"))
        rows.append(
            f"<tr><td>{escape(name)}{f' <span class=note>{escape(unit)}</span>' if unit else ''}</td>{cells}<td>{_fmt(s['t_max'])}</td></tr>"
        )
    ev_rows = "".join(
        f"<tr><td>{escape(e['rule'])}</td><td>{_fmt(e['t_start'])}</td><td>{_fmt(e['t_end'])}</td><td>{_fmt(e['duration_s'])}</td></tr>"
        for e in events
    )
    plot_html = []
    for i, group in enumerate(plots):
        keys = "".join(
            f'<span class="key" style="background:{PALETTE[j % len(PALETTE)]}"></span>{escape(n)}{f" ({escape(u)})" if u else ""}'
            for j, (n, u, _, _) in enumerate(group)
        )
        plot_html.append(
            f'<div class="plot"><h3>{keys}</h3>{plot_svg(group, x0, x1, events, i == len(plots) - 1)}</div>'
        )
    assumptions = "".join(f"<li>{escape(a)}</li>" for a in rec.get("assumptions", []) + rec.get("warnings", []))
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><title>Report: {title}</title>
<meta name="viewport" content="width=device-width,initial-scale=1"><style>{CSS}</style></head><body>
<h1>{title}</h1><p class="sub">Run report generated {datetime.now():%Y-%m-%d %H:%M}. Window {_fmt(x0)} to {_fmt(x1)} s.</p>
<dl class="meta"><dt>Source file</dt><dd>{escape(rec.get('filename', ''))}</dd><dt>Session start</dt><dd>{escape(started)}</dd>
<dt>Samples</dt><dd>{rec['rows']:,} at {rec.get('sample_rate_hz') or '?'} Hz, {_fmt(rec['duration_s'])} s</dd></dl>
<h2>Plots</h2>{''.join(plot_html) or '<p class="note">No channels chosen.</p>'}
<h2>Statistics</h2><table><thead><tr><th>Channel</th><th>Min</th><th>Max</th><th>Mean</th><th>Median</th><th>Std dev</th><th>95th pct</th><th>Max at (s)</th></tr></thead><tbody>{''.join(rows)}</tbody></table>
<p class="note">Mean is time-weighted.</p>
<h2>Events</h2>{f'<table><thead><tr><th>Rule</th><th>Start (s)</th><th>End (s)</th><th>Length (s)</th></tr></thead><tbody>{ev_rows}</tbody></table>' if ev_rows else '<p class="note">No events (no rules defined, or none held long enough).</p>'}
<h2>Import notes</h2><ul class="note">{assumptions}</ul></body></html>"""
