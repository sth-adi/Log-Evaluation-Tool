"""Automatic review: logic checks over the open logs that need no limits from the user.

Everything here is deterministic: the same logs always give the same findings, and every finding
says which check produced it and shows the numbers behind it. Nothing is learned in a way that
cannot be read back. The checks look for things that do not fit the car's own behaviour, as seen
across the logs, not for values past a limit someone typed in:

* **links**: a switch (a request, a mode, a flag) that is almost always followed by a movement in
  another channel, and the times it was not. The links are found from the data; the misses are the
  findings, with the one condition they have in common when there is one.
* **self-reports**: the ECU's own fault, limp and diagnostic channels, only while the engine runs.
* **ties**: channels that follow each other in every log (two rpm sensors, the cylinders of one
  bank, a base and a final value), and the stretches where one of them stops following. When more
  than two are tied, the one that departs from all its partners is named.
* **stuck sensors**: a channel that moves in other logs but is flat for a whole run.
* **dropouts**: channels or whole logs that go quiet for a while.

Limits for physical things (oil pressure, coolant temperature) are the one thing a person sets;
they are kept in ``review_limits.json`` and checked the same way.

A finding is not a diagnosis. It says "this does not match how the car normally behaves".
"""

from __future__ import annotations

import json
import re
import threading
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

RUN_RPM = 500.0  # above this the engine counts as running
WINDOW_S = 0.5  # how soon after a switch a response must show
SETTLE_S = 1.0  # events this soon after the log starts are start-up transients
MAX_LEVELS = 8  # a channel with this many values or fewer is a switch, not a measurement
MIN_EVENTS = 6  # a link needs this many events, across all the logs, to count
MIN_RATE = 0.6  # ... followed by a response at least this often (an on/off switch)
MIN_RATE_STATE = 0.9  # ... and for a state with several values, which move other things by coincidence
MAX_BASE = 0.3  # ... where chance alone would not respond more than this often
MIN_LIFT = 5.0  # ... and the response is at least this many times likelier than chance
MIN_MISSES = 3  # one or two misses are glitches, unless chance almost never produces the response
SURE_CHANCE = 0.05
MOVE = 0.10  # a "movement" is a change of this fraction of the channel's own range
MIN_REASON_MISSES = 3
CLOCK_LIKE = 0.7  # a channel that mostly follows the time (a warming engine) only says "early in the run"
MAX_OCCURRENCES = 40  # shown per finding; the count still says how many there were

RPM_BIN = 1500.0  # operating points: rpm in bands this wide, and three throttle bands
THROTTLE_EDGES = (25.0, 70.0)
MIN_BIN_S = 1.0  # a log must spend this long in a band for the band to be compared
DRIFT_NOISE = 3.0  # in a single band the change must be this many times the channel's own scatter there
DRIFT_NOISE_MANY = 1.0  # ... but when it shows the same way in this many bands, once the scatter is enough
MANY_BANDS = 3
DRIFT_RANGE = 0.05  # ... and at least this fraction of the channel's range
DRIFT_LEVEL = 0.01  # ... and at least this fraction of the channel's own level, so a tightly regulated
# pressure that moved 0.5% is not a change just because its usual range is tiny
DRIFT_SIGNIFICANT = 0.2  # a change of this fraction of the range is "worth a look", smaller is "probably normal"
MAX_DRIFT = 8
TEMPERATURE = re.compile(r"°\s*C|deg\s*C|^C$", re.I)
GEAR = re.compile(r"^gear$", re.I)
THROTTLE = re.compile(r"^(tps\d?|throttle\w*)$", re.I)

TIE_CORR = 0.97  # two channels are tied when they correlate at least this well, the same way, in every log
TIE_SIGMA = 6.0  # they have stopped following when they differ by this many times their usual scatter ...
TIE_FLOOR = 0.03  # ... and by at least this fraction of the channel's range
TIE_LAG_S = 0.5  # a sensor that lags its partner by up to this long is not a break
TIE_MIN_S = 1.0  # the break lasts at least this long
TIE_MAX_SHARE = 0.10  # a "tie" that fails more than this share of the time is not a tie
MAX_TIES = 400
TIE_ODD = 0.6  # one channel is the odd one out when it breaks with this share of its partners
MAX_TIE_FINDINGS = 8

SELF_REPORT = re.compile(r"fault|fail|limp|warn|alarm|diag", re.I)
SERIOUS = re.compile(r"fault|fail|limp", re.I)
COUNTER = re.compile(r"fail|fault|error", re.I)

BENIGN = re.compile(r"^(none|off|ok|idle|normal|no|disabled|clear(ed)?|inactive|good)$", re.I)
ALWAYS_ON = 0.25  # a "fault" that is on for more than this share of running time is a normal condition

SEVERITIES = ("high", "medium", "low")


@dataclass(eq=False)
class Log:
    id: str
    label: str
    t: np.ndarray
    cols: dict[str, np.ndarray]
    meta: dict[str, dict] = field(default_factory=dict)
    offset_s: float = 0.0
    started_at: str | None = None

    @property
    def n(self) -> int:
        return len(self.t)

    @property
    def rate(self) -> float:
        dt = np.median(np.diff(self.t)) if self.n > 1 else 0.0
        return 1.0 / dt if dt > 0 else 1.0

    def running(self) -> np.ndarray:
        """Samples where the engine is turning. Without an rpm channel the whole log counts."""
        rpm = next((v for k, v in self.cols.items() if k.lower() == "rpm"), None)
        if rpm is None:
            return np.ones(self.n, dtype=bool)
        return np.nan_to_num(rpm, nan=0.0) > RUN_RPM

    def unit(self, ch: str) -> str:
        return self.meta.get(ch, {}).get("unit", "")

    def state_label(self, ch: str, v: float) -> str | None:
        states = self.meta.get(ch, {}).get("states")
        return states.get(str(int(round(v)))) if states else None


# ---------------------------------------------------------------------------------------------
# helpers


def _finite(x: np.ndarray) -> np.ndarray:
    return x[np.isfinite(x)]


def _fill(x: np.ndarray) -> np.ndarray:
    return pd.Series(x).interpolate(limit_direction="both").to_numpy(dtype=float)


def _runs(mask: np.ndarray) -> list[tuple[int, int]]:
    """[start, end) index pairs of the True stretches."""
    if not mask.any():
        return []
    d = np.diff(np.concatenate([[0], mask.astype(np.int8), [0]]))
    return list(zip(np.flatnonzero(d == 1), np.flatnonzero(d == -1)))


def _merge(runs: list[tuple[int, int]], gap: int) -> list[tuple[int, int]]:
    out: list[tuple[int, int]] = []
    for a, b in runs:
        if out and a - out[-1][1] <= gap:
            out[-1] = (out[-1][0], b)
        else:
            out.append((a, b))
    return out


def _num(v: float) -> str:
    return f"{v:.4g}"


def _is_monotonic(x: np.ndarray) -> bool:
    v = _finite(x)
    return v.size > 50 and np.unique(v).size > 50 and bool(np.all(np.diff(v) >= 0) or np.all(np.diff(v) <= 0))


def _accumulates(x: np.ndarray) -> bool:
    """A distance, a timer or a running maximum: it nearly only ever goes one way, so a log that
    starts later or runs longer reads higher without anything having changed."""
    v = _finite(x)
    d = np.diff(v)
    d = d[d != 0]
    if d.size < 5:
        return False
    up = float((d > 0).mean())
    if max(up, 1 - up) >= 0.97:
        return True
    # a timer that is reset now and then: it starts every log at zero and mostly counts up
    return bool(v[0] == 0 and up >= 0.8)


def _is_counter(x: np.ndarray) -> bool:
    """Whole numbers that only ever go up, and do go up: a count of faults or failures."""
    v = _finite(x)
    return bool(v.size > 1 and np.all(v == np.round(v)) and np.all(np.diff(v) >= 0) and v[-1] > v[0])


def _occ(log: Log, i0: int, i1: int, note: str) -> dict:
    return {
        "log_id": log.id,
        "label": log.label,
        "t0": float(log.t[min(i0, log.n - 1)]),
        "t1": float(log.t[min(max(i1 - 1, i0), log.n - 1)]),
        "note": note,
    }


def _finding(key, kind, severity, title, detail, channels, occurrences, count=None, evidence=None) -> dict:
    occurrences = sorted(occurrences, key=lambda o: (o.get("fits", False), o["label"], o["t0"]))
    return {
        "key": key,
        "kind": kind,
        "severity": severity,
        "title": title,
        "detail": detail,
        "channels": channels,
        "count": len(occurrences) if count is None else count,
        "occurrences": occurrences[:MAX_OCCURRENCES],
        **({"evidence": evidence} if evidence else {}),
    }


def _is_switch(logs: list[Log], ch: str) -> bool:
    """A discrete channel that is a state or flag: it has labels, or holds whole numbers only.
    A measurement with a coarse resolution (a steering angle in steps of 0.5) is not one."""
    if not _discrete(logs, ch):
        return False
    if any(l.meta.get(ch, {}).get("states") for l in logs if ch in l.cols):
        return True
    return all(np.all(_finite(l.cols[ch]) == np.round(_finite(l.cols[ch]))) for l in logs if ch in l.cols)


def _discrete(logs: list[Log], ch: str) -> bool:
    """A switch: few values in every log that has it, and it changes somewhere."""
    have = [l for l in logs if ch in l.cols]
    levels: set[float] = set()
    for l in have:
        u = np.unique(_finite(l.cols[ch]))
        if u.size > MAX_LEVELS:
            return False
        levels.update(u.tolist())
    return len(levels) >= 2


# ---------------------------------------------------------------------------------------------
# links: a switch that is usually followed by a movement, and the times it was not


class _Responses:
    """Per log and channel: how far the channel moves within the response window, and how often it
    does by chance. Computed once and shared by every switch that is tested against it."""

    def __init__(self, logs: list[Log]):
        self.logs = logs
        self._memo: dict[tuple[int, str], dict | None] = {}

    def _window(self, log: Log) -> int:
        return max(int(round(WINDOW_S * log.rate)), 2)

    @staticmethod
    def _excursion(y: np.ndarray, starts: np.ndarray, w: int, back: int) -> np.ndarray:
        idx = starts[:, None] + np.arange(w)[None, :]
        ref = y[np.maximum(starts - back, 0)]
        return np.abs(y[idx] - ref[:, None]).max(axis=1)

    def get(self, li: int, ch: str) -> dict | None:
        key = (li, ch)
        if key in self._memo:
            return self._memo[key]
        log = self.logs[li]
        out = None
        x = log.cols.get(ch)
        if x is not None and np.isfinite(x).sum() > 20 and not _is_monotonic(x):
            lo, hi = np.percentile(_finite(x), [1, 99])
            if hi <= lo:
                lo, hi = float(np.nanmin(x)), float(np.nanmax(x))
            if hi > lo:
                w, back = self._window(log), 2
                y = _fill(x)
                starts = np.arange(back, log.n - w, 5)
                if starts.size >= 20:
                    thr = MOVE * (hi - lo)
                    base = float((self._excursion(y, starts, w, back) > thr).mean())
                    clock = float(np.corrcoef(log.t, y)[0, 1]) if np.ptp(y) > 0 else 0.0
                    out = {"y": y, "thr": thr, "base": base, "w": w, "back": back, "clock": abs(clock)}
        self._memo[key] = out
        return out

    def hits(self, li: int, ch: str, events: np.ndarray) -> np.ndarray | None:
        r = self.get(li, ch)
        if r is None or events.size == 0:
            return None
        ok = events + r["w"] <= len(r["y"])
        out = np.zeros(events.size, dtype=bool)
        if ok.any():
            out[ok] = self._excursion(r["y"], events[ok], r["w"], r["back"]) > r["thr"]
        return out


def _events(log: Log, x: np.ndarray, level: float) -> np.ndarray:
    """Sample indices where x becomes `level`, leaving out the start-up settling time."""
    prev = np.concatenate([[np.nan], x[:-1]])
    at = (x == level) & (prev != level) & np.isfinite(prev)
    idx = np.flatnonzero(at)
    return idx[(idx >= int(SETTLE_S * log.rate)) & (idx < log.n - int(WINDOW_S * log.rate) - 2)]


def _triggers(logs: list[Log]) -> list[dict]:
    """Every (switch, level) with enough events, one entry per distinct set of event times."""
    names = sorted({c for l in logs for c in l.cols})
    out, seen = [], set()
    for ch in names:
        if not _is_switch(logs, ch):
            continue
        levels = sorted({v for l in logs if ch in l.cols for v in np.unique(_finite(l.cols[ch])).tolist()})
        if len(levels) == 2:  # a plain on/off: the event is the rarer state starting
            count = {v: sum(int((l.cols[ch] == v).sum()) for l in logs if ch in l.cols) for v in levels}
            levels = [min(levels, key=lambda v: count[v])]
        for v in levels:
            ev = {i: _events(l, l.cols[ch], v) for i, l in enumerate(logs) if ch in l.cols}
            total = sum(e.size for e in ev.values())
            if total < MIN_EVENTS:
                continue
            sig = frozenset((i, int(k)) for i, e in ev.items() for k in e)
            if sig in seen:
                continue
            seen.add(sig)
            out.append({"channel": ch, "level": v, "events": ev, "binary": len(levels) == 1})
    return _dedupe(out, logs)


def _same_episode(a: dict, b: dict, tol: int) -> float | None:
    """If b fires at the same moments as a, how far after a (in samples, on average); else None."""
    lags, total, matched = [], 0, 0
    for li, eb in b["events"].items():
        ea = a["events"].get(li)
        for i in eb:
            total += 1
            if ea is None or ea.size == 0:
                continue
            j = ea[np.argmin(np.abs(ea - i))]
            if abs(int(j) - int(i)) <= tol:
                matched += 1
                lags.append(int(i) - int(j))
    na = sum(e.size for e in a["events"].values())
    if total == 0 or matched / total < 0.8 or not (0.75 <= na / total <= 1.34):
        return None
    return float(np.mean(lags))


def _dedupe(triggers: list[dict], logs: list[Log]) -> list[dict]:
    kept: list[dict] = []
    tol = max(int(0.05 * np.median([l.rate for l in logs])), 2)
    for b in triggers:
        for k, a in enumerate(kept):
            lag = _same_episode(a, b, tol)
            if lag is not None:
                if lag < 0:  # b comes first, so b is the cause
                    kept[k] = b
                break
        else:
            kept.append(b)
    return kept


def _describe_trigger(logs: list[Log], t: dict) -> str:
    ch, v = t["channel"], t["level"]
    lab = next((l.state_label(ch, v) for l in logs if ch in l.cols and l.state_label(ch, v)), None)
    if t["binary"] and lab is None:
        return f"{ch} turns on"
    return f"{ch} becomes {lab or _num(v)}"


def _reason(logs: list[Log], resp: _Responses, hit: dict, miss: dict, skip: set[str], trigger: str) -> dict | None:
    """A condition most of the misses share and none of the hits do, among the measured channels.

    One exception in about seven is allowed: the exceptions are the interesting ones, so they are
    kept apart from the misses the condition explains."""
    n_hit = sum(a.size for a in hit.values())
    n_miss = sum(a.size for a in miss.values())
    if n_miss < MIN_REASON_MISSES or n_hit < MIN_EVENTS - 1:
        return None
    allow = int(0.15 * n_miss)
    names = sorted({c for l in logs for c in l.cols} - {trigger} - skip)
    best = None
    for ch in names:
        if _discrete(logs, ch):
            continue
        pts: list[tuple[float, bool, int, int]] = []
        for li, log in enumerate(logs):
            r = resp.get(li, ch)
            if r is None or r["clock"] > CLOCK_LIKE:
                continue
            before = int(0.1 * log.rate)  # the state of the car just before, not what the event did to it
            for is_miss, ev in ((False, hit.get(li, [])), (True, miss.get(li, []))):
                for i in ev:
                    pts.append((float(r["y"][max(int(i) - before, 0)]), is_miss, li, int(i)))
        if sum(not p[1] for p in pts) < n_hit or sum(p[1] for p in pts) < n_miss:
            continue
        vals = np.array([p[0] for p in pts])
        is_miss = np.array([p[1] for p in pts])
        spread = float(np.std(vals)) or 1.0
        for side, sign in (("below", 1.0), ("above", -1.0)):
            v = sign * vals
            cut = v[~is_miss].min()  # no hit is at or beyond this
            explained = is_miss & (v < cut)
            k = int(explained.sum())
            if k < max(n_miss - allow, MIN_REASON_MISSES):
                continue
            gap = float((cut - v[explained].max()) / spread)
            if gap < 0.1:
                continue
            if best is None or (k, gap) > (best["k"], best["gap"]):
                best = {
                    "k": k, "gap": gap, "channel": ch, "side": side,
                    "cut": float(sign * (cut + v[explained].max()) / 2),
                    "fits": {pts[j][2:] for j in np.flatnonzero(explained)},
                }
    if best is None:
        return None
    unit = next((l.unit(best["channel"]) for l in logs if best["channel"] in l.cols), "")
    text = (
        f"{best['k']} of the {n_miss} misses happened with {best['channel']} {best['side']} "
        f"{_num(best['cut'])}{' ' + unit if unit else ''}; none of the {n_hit} hits did."
    )
    if best["k"] < n_miss:
        rest = n_miss - best["k"]
        text += f" The other {rest} {'does' if rest == 1 else 'do'} not fit that, and {'is the one' if rest == 1 else 'are the ones'} to look at."
    return {**best, "text": text, "all_fit": best["k"] == n_miss}


def _co_responds(resp: _Responses, order: list, ch: str, g: dict) -> bool:
    """True if ch moves at (nearly) the same events as the response group: it is part of the
    response, so it cannot also explain why the response sometimes fails."""
    agree = total = 0
    for li, e in order:
        h = resp.hits(li, ch, e)
        want = g["by_log"].get(li)
        if h is None or want is None:
            continue
        agree += int((h == want).sum())
        total += e.size
    return total > 0 and agree / total >= 0.85


def find_links(logs: list[Log]) -> list[dict]:
    resp = _Responses(logs)
    names = sorted({c for l in logs for c in l.cols})
    findings = []
    for t in _triggers(logs):
        order = [(li, e) for li, e in sorted(t["events"].items()) if e.size]
        groups: dict[tuple, dict] = {}
        for ch in names:
            if ch == t["channel"]:
                continue
            hits, usable, base = {}, 0, []
            for li, e in order:
                h = resp.hits(li, ch, e)
                if h is None:
                    continue
                hits[li] = h
                usable += e.size
                base.append(resp.get(li, ch)["base"])
            if usable < MIN_EVENTS:
                continue
            n_hit = sum(int(h.sum()) for h in hits.values())
            rate, chance = n_hit / usable, float(np.mean(base))
            if usable - n_hit < MIN_MISSES and chance > SURE_CHANCE:
                continue
            if rate < (MIN_RATE if t["binary"] else MIN_RATE_STATE) or rate >= 1.0 or chance > MAX_BASE or rate / max(chance, 0.01) < MIN_LIFT:
                continue
            sig = tuple((li, tuple(h.tolist())) for li, h in sorted(hits.items()))
            g = groups.setdefault(
                sig, {"channels": [], "rate": rate, "n": usable, "hits": n_hit, "by_log": hits, "chance": chance}
            )
            g["channels"].append(ch)
        for g in groups.values():
            hit = {li: t["events"][li][h] for li, h in g["by_log"].items()}
            miss = {li: t["events"][li][~h] for li, h in g["by_log"].items()}
            co = {ch for ch in names if ch != t["channel"] and _co_responds(resp, order, ch, g)}
            reason = _reason(logs, resp, hit, miss, co | set(g["channels"]), t["channel"])
            trig = _describe_trigger(logs, t)
            chans = sorted(g["channels"], key=lambda c: (len(c), c))
            shown = ", ".join(chans[:3]) + (f" and {len(chans) - 3} more" if len(chans) > 3 else "")
            occs = []
            for li, ev in miss.items():
                for i in ev:
                    o = _occ(logs[li], int(i), int(i) + int(WINDOW_S * logs[li].rate), f"no movement in {chans[0]} within {WINDOW_S:g} s")
                    if reason:
                        o["fits"] = (li, int(i)) in reason["fits"]
                    occs.append(o)
            findings.append(
                _finding(
                    key=f"link:{t['channel']}={_num(t['level'])}:{chans[0]}",
                    kind="link",
                    severity="low" if reason and reason["all_fit"] else "medium",
                    title=f"When {trig}, {shown} usually {'moves' if len(chans) == 1 else 'move'}, but not always",
                    detail=(
                        f"It moved within {WINDOW_S:g} s after {g['hits']} of {g['n']} events and not after {g['n'] - g['hits']}. "
                        + (reason["text"] if reason else "The misses have no condition in common that the other channels show.")
                    ),
                    channels=[t["channel"], *chans[:3]],
                    occurrences=occs,
                    evidence={"events": g["n"], "followed": g["hits"], "chance": round(g["chance"], 3)},
                )
            )
    return _one_per_observation(findings)


def _one_per_observation(findings: list[dict]) -> list[dict]:
    """Different phases of one event (a request, then its state changes) miss at the same moments.
    Keep the finding with the most misses for each response and drop the echoes."""
    kept: list[dict] = []
    for f in sorted(findings, key=lambda f: -f["count"]):
        mine = [(o["log_id"], o["t0"]) for o in f["occurrences"]]
        echo = False
        for k in kept:
            if k["channels"][1] != f["channels"][1]:
                continue
            theirs = [(o["log_id"], o["t0"]) for o in k["occurrences"]]
            near = sum(any(a == b and abs(s - u) <= 1.0 for b, u in theirs) for a, s in mine)
            if mine and near / len(mine) >= 0.6:
                echo = True
                break
        if not echo:
            kept.append(f)
    return kept


# ---------------------------------------------------------------------------------------------
# the ECU's own fault channels


def find_self_reports(logs: list[Log]) -> list[dict]:
    findings = []
    names = sorted({c for l in logs for c in l.cols if SELF_REPORT.search(c) or COUNTER.search(c)})
    for ch in names:
        have = [l for l in logs if ch in l.cols]
        counter = COUNTER.search(ch) and any(_is_counter(l.cols[ch]) for l in have)
        if not counter and _discrete(logs, ch) and SELF_REPORT.search(ch):
            run_vals = np.concatenate([_finite(l.cols[ch][l.running() & np.isfinite(l.cols[ch])]) for l in have])
            if run_vals.size == 0:
                continue
            vals, counts = np.unique(run_vals, return_counts=True)
            benign = [v for v in vals if any(BENIGN.match(l.state_label(ch, v) or "") for l in have)]
            normal_set = set(benign) if benign else {vals[np.argmax(counts)]}
            normal = benign[0] if benign else vals[np.argmax(counts)]
            share = float(counts[[v not in normal_set for v in vals]].sum() / counts.sum())
            occs, labels = [], set()
            for l in have:
                x = l.cols[ch]
                bad = l.running() & np.isfinite(x) & ~np.isin(x, list(normal_set))
                for a, b in _merge(_runs(bad), int(0.2 * l.rate)):
                    if b - a < int(0.1 * l.rate):
                        continue
                    seg = x[a:b][bad[a:b]]
                    vv, cc = np.unique(seg, return_counts=True)
                    v = float(vv[np.argmax(cc)])
                    what = l.state_label(ch, v) or _num(v)
                    labels.add(what)
                    occs.append(_occ(l, a, b, what))
            if occs:
                norm_lab = next((l.state_label(ch, normal) for l in have if l.state_label(ch, normal)), None) or _num(normal)
                always = share > ALWAYS_ON
                findings.append(
                    _finding(
                        key=f"report:{ch}",
                        kind="report",
                        severity="low" if always else ("high" if SERIOUS.search(ch) else "medium"),
                        title=f"{ch} reported {', '.join(sorted(labels)[:3])} while the engine was running",
                        detail=(
                            f"This is the case for {share:.0%} of all running time, so it is probably how this ECU "
                            f"normally reads, not a fault. The quiet value is {norm_lab}."
                            if always
                            else f"The usual value is {norm_lab}. Only samples with the engine running count."
                        ),
                        channels=[ch],
                        occurrences=occs,
                    )
                )
        elif counter:
            occs = []
            for l in have:
                x = l.cols[ch]
                if not _is_counter(x):
                    continue
                f = _fill(x)
                for i in np.flatnonzero(np.diff(f) > 0) + 1:
                    occs.append(_occ(l, int(i), int(i) + 1, f"count rose to {_num(f[i])}"))
            if occs:
                findings.append(
                    _finding(
                        key=f"report:{ch}",
                        kind="report",
                        severity="high" if SERIOUS.search(ch) else "medium",
                        title=f"{ch} counted up",
                        detail="A fault or error counter increased during the run.",
                        channels=[ch],
                        occurrences=occs,
                    )
                )
    return findings


# ---------------------------------------------------------------------------------------------
# stuck sensors, channels that never change, dropouts


def find_stuck(logs: list[Log]) -> list[dict]:
    findings = []
    if not logs:
        return findings
    names = sorted({c for l in logs for c in l.cols})
    for ch in names:
        have = [l for l in logs if ch in l.cols]
        moves = [l for l in have if np.unique(_finite(l.cols[ch])).size > MAX_LEVELS]
        if not moves or _discrete(logs, ch):
            continue
        occs = []
        for l in have:
            if any(l is m for m in moves):
                continue
            x = l.cols[ch]
            run = l.running() & np.isfinite(x)
            if run.sum() < int(3 * l.rate) or np.ptp(x[run]) != 0:
                continue
            idx = np.flatnonzero(run)
            occs.append(_occ(l, int(idx[0]), int(idx[-1]) + 1, f"stuck at {_num(float(x[idx[0]]))}"))
        if occs:
            findings.append(
                _finding(
                    key=f"stuck:{ch}",
                    kind="stuck",
                    severity="medium",
                    title=f"{ch} did not move at all in {len(occs)} run{'s' if len(occs) > 1 else ''}",
                    detail=f"It moves in {len(moves)} other log{'s' if len(moves) > 1 else ''}, so a flat line here points to a dead or disconnected sensor.",
                    channels=[ch],
                    occurrences=occs,
                )
            )
    return findings


def find_unused(logs: list[Log]) -> list[dict]:
    names = sorted({c for l in logs for c in l.cols})
    flat = [c for c in names if all(np.ptp(_finite(l.cols[c])) == 0 for l in logs if c in l.cols and np.isfinite(l.cols[c]).any())]
    if not flat:
        return []
    return [
        _finding(
            key="unused",
            kind="unused",
            severity="low",
            title=f"{len(flat)} channel{'s' if len(flat) > 1 else ''} never change in any log",
            detail="Unused inputs, or sensors that are not connected: " + ", ".join(flat[:60]) + (" …" if len(flat) > 60 else ""),
            channels=flat[:60],
            occurrences=[],
            count=len(flat),
        )
    ]


def find_dropouts(logs: list[Log]) -> list[dict]:
    findings = []
    quiet = 0.5
    for l in logs:
        gap = max(5 * np.median(np.diff(l.t)), quiet) if l.n > 1 else quiet
        for i in np.flatnonzero(np.diff(l.t) > gap):
            findings.append(
                _finding(
                    key="gap",
                    kind="gap",
                    severity="medium",
                    title="Samples are missing from a log",
                    detail="The log jumps forward in time with no samples in between.",
                    channels=[],
                    occurrences=[_occ(l, int(i), int(i) + 2, f"{l.t[i + 1] - l.t[i]:.2f} s without samples")],
                )
            )
    merged: dict[str, dict] = {}
    for f in findings:
        m = merged.setdefault(f["key"], {**f, "occurrences": [], "count": 0})
        m["occurrences"] += f["occurrences"]
        m["count"] += f["count"]
    out = list(merged.values())
    for l in logs:
        wide = np.mean([~np.isfinite(v) for v in l.cols.values()], axis=0) if l.cols else np.zeros(l.n)
        whole = _runs(wide > 0.5)
        for ch, x in l.cols.items():
            bad = ~np.isfinite(x) & (wide <= 0.5)
            for a, b in _runs(bad):
                if l.t[min(b, l.n - 1)] - l.t[a] >= quiet and l.running()[a:b].mean() >= 0.5:
                    out.append(
                        _finding(
                            key=f"dropout:{ch}",
                            kind="dropout",
                            severity="medium",
                            title=f"{ch} had no value for a while",
                            detail="The channel went blank while the others kept logging.",
                            channels=[ch],
                            occurrences=[_occ(l, a, b, f"{l.t[min(b, l.n - 1)] - l.t[a]:.2f} s with no value")],
                        )
                    )
        for a, b in whole:
            if l.t[min(b, l.n - 1)] - l.t[a] >= quiet:
                out.append(
                    _finding(
                        key="blank",
                        kind="gap",
                        severity="medium",
                        title="Most channels went blank together",
                        detail="Logging probably stopped or the logger lost its link.",
                        channels=[],
                        occurrences=[_occ(l, a, b, f"{l.t[min(b, l.n - 1)] - l.t[a]:.2f} s")],
                    )
                )
    return _combine(out)


def _combine(findings: list[dict]) -> list[dict]:
    """One finding per key: occurrences from several logs join up."""
    by: dict[str, dict] = {}
    for f in findings:
        g = by.get(f["key"])
        if g is None:
            by[f["key"]] = {**f, "occurrences": list(f["occurrences"])}
        else:
            g["occurrences"] += f["occurrences"]
            g["count"] += f["count"]
    for g in by.values():
        g["occurrences"] = sorted(g["occurrences"], key=lambda o: (o.get("fits", False), o["label"], o["t0"]))[:MAX_OCCURRENCES]
    return list(by.values())


# ---------------------------------------------------------------------------------------------
# limits set by the user


def find_limit_breaches(logs: list[Log], limits: list[dict]) -> tuple[list[dict], list[str]]:
    findings, notes = [], []
    for lim in limits:
        ch, op, value = lim["channel"], lim["op"], float(lim["value"])
        have = [l for l in logs if ch in l.cols]
        if not have:
            notes.append(f"Limit on {ch} not checked: no open log has that channel.")
            continue
        occs = []
        for l in have:
            x = l.cols[ch]
            over = np.isfinite(x) & ((x > value) if op == ">" else (x < value))
            if lim.get("running_only", True):
                over &= l.running()
            for a, b in _runs(over):
                if l.t[min(b, l.n - 1)] - l.t[a] >= float(lim.get("seconds", 0)):
                    peak = float(np.nanmax(x[a:b]) if op == ">" else np.nanmin(x[a:b]))
                    occs.append(_occ(l, a, b, f"{'peak' if op == '>' else 'low'} {_num(peak)}"))
        if occs:
            unit = next((l.unit(ch) for l in have if l.unit(ch)), "")
            findings.append(
                _finding(
                    key=f"limit:{lim['id']}",
                    kind="limit",
                    severity=lim.get("severity", "high") if lim.get("severity") in SEVERITIES else "high",
                    title=lim.get("message") or f"{ch} {'above' if op == '>' else 'below'} {_num(value)}{' ' + unit if unit else ''}",
                    detail=f"Your limit: {ch} {op} {_num(value)}{' ' + unit if unit else ''}"
                    + (f" for {lim['seconds']:g} s or more" if lim.get("seconds") else "")
                    + (", engine running." if lim.get("running_only", True) else "."),
                    channels=[ch],
                    occurrences=occs,
                )
            )
    return findings, notes


# ---------------------------------------------------------------------------------------------
# a channel that reads differently than in earlier runs, at the same load


def _op_points(log: Log) -> tuple[np.ndarray, np.ndarray | None]:
    """Operating point of every sample (rpm band, throttle band and gear), -1 where the engine is
    not pulling. None when there is no rpm channel."""
    rpm = next((v for k, v in log.cols.items() if k.lower() == "rpm"), None)
    if rpm is None:
        return np.full(log.n, -1), None
    thr = next((v for k, v in log.cols.items() if THROTTLE.match(k)), None)
    band = np.floor(np.nan_to_num(rpm, nan=0.0) / RPM_BIN).astype(int)
    point = band * 10
    if thr is not None:
        point = point + np.digitize(np.nan_to_num(thr, nan=0.0), THROTTLE_EDGES)
    gear = next((v for k, v in log.cols.items() if GEAR.match(k)), None)
    if gear is not None:  # the same rpm in another gear is a different speed and a different load
        point = point * 10 + np.mod(np.nan_to_num(gear, nan=0.0).astype(int), 10)
    point = np.where(log.running() & (band >= 1), point, -1)
    return point, rpm


def find_drift(logs: list[Log]) -> list[dict]:
    """Compare each log with the ones before it, only where the engine was at the same rpm and
    throttle. Temperatures warming up and the load changing do not count; what is left is the car
    behaving differently than it did, which is what a change to the car or a failing part looks like."""
    ordered = sorted(logs, key=lambda l: l.started_at or "")
    if len(ordered) < 2:
        return []
    points = {l.id: _op_points(l)[0] for l in ordered}
    if all((p < 0).all() for p in points.values()):
        return []
    skip = {k for l in ordered for k in l.cols if k.lower() == "rpm" or THROTTLE.match(k) or GEAR.match(k)}
    names = sorted({c for l in ordered for c in l.cols} - skip)
    found: dict[str, dict] = {}
    for ch in names:
        have = [l for l in ordered if ch in l.cols]
        if len(have) < 2 or _discrete(ordered, ch) or any(_accumulates(l.cols[ch]) for l in have):
            continue
        pooled = np.concatenate([_finite(l.cols[ch][points[l.id] >= 0]) for l in have])
        if pooled.size < 50:
            continue
        lo, hi = np.percentile(pooled, [1, 99])
        span = float(hi - lo)
        if span <= 0:
            continue
        stats: dict[str, dict[int, tuple[float, float, int, int, int]]] = {}
        for l in have:
            x, pt = l.cols[ch], points[l.id]
            per: dict[int, tuple[float, float, int, int, int]] = {}
            for b in np.unique(pt[pt >= 0]):
                idx = np.flatnonzero((pt == b) & np.isfinite(x))
                if idx.size >= MIN_BIN_S * l.rate:
                    per[int(b)] = (float(np.median(x[idx])), float(np.std(x[idx])), idx.size, int(idx[0]), int(idx[-1]))
            stats[l.id] = per
        for k, l in enumerate(have):
            deltas, noises, refs, vals, span_i = [], [], [], [], [0, 0]
            for b, (m, sd, n, i0, i1) in stats[l.id].items():
                before = [stats[e.id][b] for e in have[:k] if b in stats[e.id]]
                if not before:
                    continue
                ref = float(np.median([r[0] for r in before]))
                deltas.append(m - ref)
                noises.append(float(np.mean([sd, *[r[1] for r in before]])))
                refs.append(ref)
                vals.append(m)
                span_i = [min(span_i[0] or i0, i0), max(span_i[1], i1)]
            if not deltas:
                continue
            d = float(np.median(deltas))
            if np.mean(np.sign(deltas) == np.sign(d)) < 0.7:
                continue  # up in some bands and down in others is not a drift
            noise = max(float(np.median(noises)), 1e-9)
            need = DRIFT_NOISE_MANY if len(deltas) >= MANY_BANDS else DRIFT_NOISE
            ref, val = float(np.median(refs)), float(np.median(vals))
            if abs(d) < need * noise or abs(d) < DRIFT_RANGE * span or abs(d) < DRIFT_LEVEL * abs(ref):
                continue
            unit = l.unit(ch)
            g = found.setdefault(ch, {"occ": [], "size": 0.0, "unit": unit})
            g["size"] = max(g["size"], abs(d) / span)
            g["occ"].append(
                _occ(l, span_i[0], span_i[1] + 1, f"{_num(ref)} → {_num(val)}{' ' + unit if unit else ''} at the same load ({len(deltas)} band{'s' if len(deltas) > 1 else ''})")
                | {"delta": d}
            )
    findings = []
    for ch, g in sorted(found.items(), key=lambda kv: -kv[1]["size"])[:MAX_DRIFT]:
        up = sum(o["delta"] > 0 for o in g["occ"]) >= len(g["occ"]) / 2
        big = g["size"] >= DRIFT_SIGNIFICANT
        findings.append(
            _finding(
                key=f"drift:{ch}",
                kind="drift",
                severity="medium" if big else "low",
                title=f"{ch} reads {'higher' if up else 'lower'} than in earlier runs at the same load",
                detail=(
                    "Compared only where the engine was at the same rpm and throttle, so changes of load do not count. "
                    "That can be a deliberate change to the car or the tune, or something wearing."
                    + (
                        " Runs close together also start warmer, which raises temperatures without anything being wrong."
                        if TEMPERATURE.search(g["unit"] or "")
                        else ""
                    )
                ),
                channels=[ch],
                occurrences=[{k: v for k, v in o.items() if k != "delta"} for o in g["occ"]],
            )
        )
    return findings


# ---------------------------------------------------------------------------------------------
# ties: channels that follow each other, and the stretches where one stops


def _settled(log: Log) -> np.ndarray:
    """Running samples without the first second of each run: cranking and the log's own start-up
    move everything at once and say nothing about whether two channels agree."""
    ok = log.running() & (log.t - log.t[0] >= SETTLE_S)
    out = ok.copy()
    k = max(1, int(round(log.rate)))
    for a, b in _runs(ok):
        out[a : min(a + k, b)] = False
    return out


def _tied_pairs(logs: list[Log], names: list[str], ok: dict[str, np.ndarray]) -> list[tuple[int, int]]:
    """Index pairs of ``names`` that correlate at least TIE_CORR, with one sign, in every log that
    has both and in at least two logs. Strongest first."""
    n = len(names)
    stack = np.full((len(logs), n, n), np.nan)
    for li, l in enumerate(logs):
        rows = [i for i, c in enumerate(names) if c in l.cols]
        m = ok[l.id]
        if len(rows) < 2 or m.sum() < 200:
            continue
        mat = np.vstack([_fill(l.cols[names[i]])[m] for i in rows])
        with np.errstate(invalid="ignore", divide="ignore"):
            c = np.corrcoef(mat)
        stack[li][np.ix_(rows, rows)] = c
    have = (~np.isnan(stack)).sum(0)
    lo = np.where(np.isnan(stack), 2.0, stack).min(0)
    hi = np.where(np.isnan(stack), -2.0, stack).max(0)
    strength = np.where(lo >= TIE_CORR, lo, np.where(hi <= -TIE_CORR, -hi, 0.0))
    iu = np.triu_indices(n, 1)
    keep = (strength[iu] > 0) & (have[iu] >= 2)
    pairs = sorted(zip(iu[0][keep], iu[1][keep]), key=lambda ij: -strength[ij])
    return [(int(i), int(j)) for i, j in pairs[:MAX_TIES]]


def find_ties(logs: list[Log]) -> list[dict]:
    """Channels that follow each other in every log, and where one of them stops following.
    Nothing says which pairs to watch: they are the ones that agree almost all the time."""
    if len(logs) < 2:
        return []
    ok = {l.id: _settled(l) for l in logs}
    names = []
    for c in sorted({c for l in logs for c in l.cols}):
        have = [l for l in logs if c in l.cols]
        if len(have) < 2 or _discrete(logs, c) or any(_accumulates(l.cols[c]) for l in have):
            continue
        if all(_finite(l.cols[c][ok[l.id]]).size >= 200 and np.ptp(_finite(l.cols[c][ok[l.id]])) > 0 for l in have):
            names.append(c)
    if len(names) < 2:
        return []

    # rolling extremes of every channel, so a sensor that lags its partner is not a break
    env: dict[tuple[str, str], tuple[np.ndarray, np.ndarray]] = {}

    def envelope(l: Log, c: str) -> tuple[np.ndarray, np.ndarray]:
        e = env.get((l.id, c))
        if e is None:
            w = 2 * max(1, int(TIE_LAG_S * l.rate)) + 1
            r = pd.Series(l.cols[c]).rolling(w, center=True, min_periods=1)
            e = env[(l.id, c)] = (r.min().to_numpy(), r.max().to_numpy())
        return e

    ties: dict[tuple[str, str], dict] = {}
    degree: dict[str, int] = {}
    for i, j in _tied_pairs(logs, names, ok):
        a, b = names[i], names[j]
        both = [l for l in logs if a in l.cols and b in l.cols]
        use = {l.id: ok[l.id] & np.isfinite(l.cols[a]) & np.isfinite(l.cols[b]) for l in both}
        X = np.concatenate([l.cols[a][use[l.id]] for l in both])
        Y = np.concatenate([l.cols[b][use[l.id]] for l in both])
        if X.size < 200:
            continue
        k, c0 = np.polyfit(X, Y, 1)
        for _ in range(3):  # fit the way the two agree, not the way they sometimes do not
            r = np.abs(Y - (k * X + c0))
            keep = r <= np.percentile(r, 95)
            k, c0 = np.polyfit(X[keep], Y[keep], 1)
        r = Y - (k * X + c0)
        sig = 1.4826 * float(np.median(np.abs(r - np.median(r))))
        lo, hi = np.percentile(Y, [1, 99])
        span = float(hi - lo)
        if span <= 0:
            continue
        tol = max(TIE_SIGMA * sig, TIE_FLOOR * span)
        runs, bad_n, all_n = [], 0, 0
        for l in both:
            emin, emax = envelope(l, a)
            lo_y, hi_y = (k * emin + c0, k * emax + c0) if k >= 0 else (k * emax + c0, k * emin + c0)
            y = l.cols[b]
            dist = np.maximum(np.maximum(y - hi_y, lo_y - y), 0.0)
            bad = (dist > tol) & use[l.id]
            bad_n += int(bad.sum())
            all_n += int(use[l.id].sum())
            for s0, s1 in _merge(_runs(bad), int(0.5 * l.rate)):
                if s1 - s0 >= TIE_MIN_S * l.rate:
                    runs.append((l, s0, s1, float(dist[s0:s1].max())))
        if all_n == 0 or bad_n / all_n > TIE_MAX_SHARE:
            continue
        ties[(a, b)] = {"k": float(k), "sig": sig, "span": span, "runs": runs}
        degree[a] = degree.get(a, 0) + 1
        degree[b] = degree.get(b, 0) + 1

    # breaks of different pairs that overlap in time belong together: who is the odd one out?
    events = sorted(
        ((l.id, s0, s1, pair, dist) for pair, t in ties.items() for (l, s0, s1, dist) in t["runs"]),
        key=lambda e: (e[0], e[1]),
    )
    by_log = {l.id: l for l in logs}
    clusters: list[list] = []
    for e in events:
        if clusters and clusters[-1][0][0] == e[0] and e[1] <= max(x[2] for x in clusters[-1]):
            clusters[-1].append(e)
        else:
            clusters.append([e])

    found: dict[str, dict] = {}
    for cl in clusters:
        l = by_log[cl[0][0]]
        pairs = {e[3] for e in cl}
        broken: dict[str, int] = {}
        for x, y in pairs:
            broken[x] = broken.get(x, 0) + 1
            broken[y] = broken.get(y, 0) + 1
        share = sorted(((n / degree[c], c) for c, n in broken.items() if n >= 2), reverse=True)
        # the odd one out breaks with most of the channels it is tied to, and the others do not
        odd = [share[0][1]] if share and share[0][0] >= TIE_ODD and (len(share) < 2 or share[1][0] <= share[0][0] - 0.25) else []
        s0, s1 = min(e[1] for e in cl), max(e[2] for e in cl)
        tight = lambda p: ties[p]["sig"] / ties[p]["span"]  # noqa: E731
        size = max(max(e[4] for e in cl if e[3] == p) / ties[p]["span"] for p in pairs)
        if len(odd) == 1:
            c = odd[0]
            mine = sorted((p for p in pairs if c in p), key=tight)
            best = mine[0]
            partner = best[1] if best[0] == c else best[0]
            worst = max(e[4] for e in cl if e[3] == best)
            gain = abs(ties[best]["k"])
            away = worst if best[1] == c else worst / gain if gain else worst
            unit = l.unit(c)
            key, lead = f"tie:{c}", c
            note = f"{c} was up to {_num(away)}{' ' + unit if unit else ''} away from where {partner} puts it"
            partners = [p[0] if p[1] == c else p[1] for p in mine]  # tightest tie first
            chans = [c, *partners[:2]]
        else:
            best = min(pairs, key=tight)
            a, b = best
            worst = max(e[4] for e in cl if e[3] == best)
            unit = l.unit(b)
            key, lead = f"tie:{a}+{b}", None
            note = f"{a} and {b} differed by up to {_num(worst)}{' ' + unit if unit else ''} from how they usually agree"
            partners, chans = [], [a, b]
        g = found.setdefault(key, {"lead": lead, "chans": chans, "partners": partners, "occ": [], "size": 0.0, "pairs": set()})
        g["size"] = max(g["size"], size)
        g["pairs"] |= pairs
        g["occ"].append(_occ(l, s0, s1, note))
    findings = []
    for key, g in sorted(found.items(), key=lambda kv: -kv[1]["size"])[:MAX_TIE_FINDINGS]:
        if g["lead"]:
            c = g["lead"]
            others = ", ".join(g["partners"][:3]) + (f" and {len(g['partners']) - 3} more" if len(g["partners"]) > 3 else "")
            title = f"{c} stopped following {g['partners'][0]}" + (f" and {len(g['partners']) - 1} other channel{'s' if len(g['partners']) > 2 else ''}" if len(g["partners"]) > 1 else "")
            detail = (
                f"{c} moves with {others} in every log, and for these stretches it did not, while the channels it usually agrees with "
                "kept agreeing with each other. A sensor drifting away from its twin, a value that is clamped, or a mode that changes "
                "how they relate all look like this; the data cannot say which one is wrong."
            )
        else:
            a, b = g["chans"]
            title = f"{a} and {b} stopped agreeing"
            detail = (
                f"{a} and {b} move together in every log, and for these stretches they did not. The data cannot say which of the two is "
                "wrong, or whether something changes how they relate."
            )
        findings.append(
            _finding(
                key=key,
                kind="tie",
                severity="medium" if g["size"] >= 0.1 else "low",
                title=title,
                detail=detail,
                channels=g["chans"],
                occurrences=g["occ"],
            )
        )
    return findings


# ---------------------------------------------------------------------------------------------
# putting it together


def evaluate(logs: list[Log], limits: list[dict] | None = None) -> dict:
    findings: list[dict] = []
    notes: list[str] = []
    if not logs:
        return {"findings": [], "notes": ["No logs are open."], "checked": {"logs": 0, "channels": 0}}
    if not any(k.lower() == "rpm" for l in logs for k in l.cols):
        notes.append("No rpm channel, so every sample counts as engine running.")
    if len(logs) < 2:
        notes.append("Only one log is open. Checks that compare logs (stuck sensors, links) get stronger with more.")
    for check in (find_links, find_self_reports, find_drift, find_ties, find_stuck, find_unused, find_dropouts):
        findings += check(logs)
    lim, lim_notes = find_limit_breaches(logs, limits or [])
    findings += lim
    notes += lim_notes
    findings.sort(key=lambda f: (SEVERITIES.index(f["severity"]), -f["count"], f["key"]))
    return {
        "findings": findings,
        "notes": notes,
        "checked": {"logs": len(logs), "channels": len({c for l in logs for c in l.cols})},
    }


# ---------------------------------------------------------------------------------------------
# what the user keeps: limits and findings marked as normal

_lock = threading.Lock()


def _file(name: str):
    from . import store

    return store.data_dir() / name


def _read(name: str, default):
    p = _file(name)
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else default


def _write(name: str, value) -> None:
    _file(name).write_text(json.dumps(value, indent=1), encoding="utf-8")


def muted() -> list[str]:
    return _read("review_muted.json", [])


def mute(key: str) -> list[str]:
    with _lock:
        keys = muted()
        if key not in keys:
            keys.append(key)
            _write("review_muted.json", keys)
        return keys


def unmute(key: str) -> list[str]:
    with _lock:
        keys = [k for k in muted() if k != key]
        _write("review_muted.json", keys)
        return keys


class LimitError(ValueError):
    pass


def limits() -> list[dict]:
    return _read("review_limits.json", [])


def set_limits(items: list[dict]) -> list[dict]:
    clean = []
    for n, it in enumerate(items):
        ch = str(it.get("channel", "")).strip()
        op = it.get("op")
        if not ch:
            raise LimitError(f"Limit {n + 1} has no channel")
        if op not in (">", "<"):
            raise LimitError(f"Limit {n + 1}: choose above or below")
        try:
            value, seconds = float(it["value"]), float(it.get("seconds", 0) or 0)
        except (KeyError, TypeError, ValueError):
            raise LimitError(f"Limit {n + 1} needs a number for the value and for the seconds") from None
        if not np.isfinite(value) or seconds < 0:
            raise LimitError(f"Limit {n + 1} has a value that cannot be used")
        clean.append(
            {
                "id": str(it.get("id") or f"l{n + 1}-{abs(hash((ch, op, value))) % 10**6}"),
                "channel": ch,
                "op": op,
                "value": value,
                "seconds": seconds,
                "severity": it.get("severity") if it.get("severity") in SEVERITIES else "high",
                "message": str(it.get("message", "")).strip()[:120],
                "running_only": bool(it.get("running_only", True)),
            }
        )
    with _lock:
        _write("review_limits.json", clean)
    return clean


def load_logs(include_closed: bool = False) -> list[Log]:
    """The open logs as arrays. Calculated channels are left out: they only repeat other channels."""
    from . import store

    logs = []
    for rec in store.list_sources(include_closed=include_closed):
        base = [c for c in rec["channels"] if not c.get("derived")]
        df = pd.read_parquet(store.data_dir() / "sources" / rec["id"] / "data.parquet", columns=["time_s", *[c["name"] for c in base]])
        logs.append(
            Log(
                id=rec["id"],
                label=rec["label"],
                t=df["time_s"].to_numpy(dtype=float),
                cols={c["name"]: df[c["name"]].to_numpy(dtype=float) for c in base},
                meta={c["name"]: c for c in base},
                offset_s=float(rec.get("offset_s", 0.0)),
                started_at=rec.get("started_at"),
            )
        )
    return logs


# ---------------------------------------------------------------------------------------------
# what the page asks for

_cache: dict[str, tuple[tuple, dict]] = {}


def run() -> dict:
    """Review the open logs. The result is kept until a log or a limit changes, so the page and the
    badge on the tab can both ask without the checks running twice."""
    from . import store

    recs = store.list_sources()
    cfg = limits()
    sig = (
        tuple(
            (r["id"], (store.data_dir() / "sources" / r["id"] / "data.parquet").stat().st_mtime_ns, r.get("offset_s", 0.0))
            for r in recs
        ),
        json.dumps(cfg, sort_keys=True),
    )
    d = str(store.data_dir())
    hit = _cache.get(d)
    if hit is None or hit[0] != sig:
        _cache[d] = (sig, evaluate(load_logs(), cfg))
    result = _cache[d][1]
    off = {r["id"]: r.get("offset_s", 0.0) for r in recs}
    skip = set(muted())
    return {
        "findings": [f for f in result["findings"] if f["key"] not in skip],
        "muted": [f for f in result["findings"] if f["key"] in skip],
        "notes": result["notes"],
        "checked": result["checked"],
        "offsets": off,
        "limits": cfg,
    }
