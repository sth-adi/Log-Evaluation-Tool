import { useEffect, useState } from "react";
import { useStore, type Source } from "../store";

/** "2025-11-19 11-53-32 plus 0h00m00s F88#12357 Dyno run final ALL" -> "F88#12357 Dyno run final" */
export function shortLabel(label: string): string {
  const s = label
    .replace(/^\d{4}-\d{2}-\d{2}[ T]\d{2}[-:]\d{2}[-:]\d{2}( plus \d+h\d+m\d+s)? ?/, "")
    .replace(/ ALL$/, "")
    .trim();
  return s || label;
}

const clock = (s: Source) => (s.started_at ? s.started_at.slice(11, 19) : "No start time");
const fmtDur = (s: number) => (s >= 60 ? `${Math.floor(s / 60)} min ${Math.round(s % 60)} s` : `${s.toFixed(1)} s`);

export function LogRail() {
  const sources = useStore((s) => s.sources);
  const view = useStore((s) => s.view);
  const setView = useStore((s) => s.setView);
  const arrange = useStore((s) => s.arrange);
  const setManaging = useStore((s) => s.setManaging);

  if (!sources.length) return null;
  const ordered = [...sources].sort((a, b) => a.offset_s - b.offset_s);
  const longest = Math.max(...ordered.map((s) => s.duration_s), 1);
  const day = ordered.find((s) => s.started_at)?.started_at?.slice(0, 10);
  const here = (s: Source) =>
    view != null && Math.abs(view[0] - s.offset_s) < 0.05 && Math.abs(view[1] - (s.offset_s + s.duration_s)) < 0.05;

  return (
    <nav className="rail" aria-label="Logs">
      <div className="rail-head">
        <h2>Logs</h2>
        {day && <span className="muted">{day}</span>}
      </div>

      <ol className="logs">
        {ordered.map((s) => (
          <li key={s.id}>
            <div className={`log${here(s) ? " on" : ""}`}>
              <button
                className="log-main"
                onClick={() => {
                  setView([s.offset_s, s.offset_s + s.duration_s]);
                }}
                title="Zoom the plots to this log"
              >
                <span className="log-time">{clock(s)}</span>
                <span className="log-name">{shortLabel(s.label)}</span>
                <span className="log-dur">{fmtDur(s.duration_s)}</span>
                <span className="log-bar" aria-hidden>
                  <i style={{ width: `${Math.max((s.duration_s / longest) * 100, 6)}%` }} />
                </span>
              </button>
              <button className="icon-btn log-manage" onClick={() => setManaging(s.id)} aria-label={`Manage ${shortLabel(s.label)}`} title="Manage this log">
                <svg width="16" height="16" viewBox="0 0 16 16" aria-hidden>
                  <circle cx="3.5" cy="8" r="1.3" />
                  <circle cx="8" cy="8" r="1.3" />
                  <circle cx="12.5" cy="8" r="1.3" />
                </svg>
              </button>
            </div>
          </li>
        ))}
      </ol>

      <div className="rail-foot">
        <button className="btn ghost" onClick={() => setView(null)}>
          Show all logs
        </button>
        {sources.length > 1 && <p className="muted small">Lay the logs out</p>}
        {sources.length > 1 && (
          <div className="seg stretch" role="group" aria-label="How logs are laid out">
            <button onClick={() => arrange("sequential")} title="Lay the logs end to end, earliest first">
              Back to back
            </button>
            <button onClick={() => arrange("real")} title="Keep the real time gaps between sessions">
              Real time
            </button>
          </div>
        )}
      </div>
    </nav>
  );
}

/** Everything about one log that is not needed all the time. */
export function LogDrawer() {
  const id = useStore((s) => s.managing);
  const sources = useStore((s) => s.sources);
  const setManaging = useStore((s) => s.setManaging);
  const setOffset = useStore((s) => s.setOffset);
  const setKind = useStore((s) => s.setKind);
  const removeSource = useStore((s) => s.removeSource);
  const addDerivedAll = useStore((s) => s.addDerivedAll);
  const removeDerivedAll = useStore((s) => s.removeDerivedAll);
  const src = sources.find((s) => s.id === id);

  const [name, setName] = useState("");
  const [expr, setExpr] = useState("");
  const [unit, setUnit] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (!id) return;
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && setManaging(null);
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [id, setManaging]);

  if (!src) return null;
  const math = src.channels.filter((c) => c.derived);
  const submit = async () => {
    if (!name.trim() || !expr.trim() || busy) return;
    setBusy(true);
    const ok = await addDerivedAll(name.trim(), expr.trim(), unit.trim());
    setBusy(false);
    if (ok) {
      setName("");
      setExpr("");
      setUnit("");
    }
  };

  return (
    <div className="scrim" onMouseDown={(e) => e.target === e.currentTarget && setManaging(null)}>
      <aside className="drawer" role="dialog" aria-modal="true" aria-label={`Manage ${shortLabel(src.label)}`}>
        <header className="drawer-head">
          <div>
            <h2>{shortLabel(src.label)}</h2>
            <p className="muted">
              {src.started_at ? `Started ${src.started_at.replace("T", " ")}` : "No start time in the file name"}
              {` · ${src.rows.toLocaleString()} samples at ${src.sample_rate_hz ?? "?"} Hz`}
            </p>
          </div>
          <button className="icon-btn" onClick={() => setManaging(null)} aria-label="Close">
            <svg width="16" height="16" viewBox="0 0 16 16" aria-hidden>
              <path d="M3.5 3.5l9 9M12.5 3.5l-9 9" />
            </svg>
          </button>
        </header>

        <section className="drawer-sec">
          <h3>Position on the timeline</h3>
          <div className="row">
            <label>
              Start offset (s)
              <input
                type="number"
                step="0.01"
                defaultValue={src.offset_s}
                key={`${src.id}-${src.offset_s}`}
                onBlur={(e) => {
                  const v = parseFloat(e.target.value);
                  if (Number.isFinite(v) && v !== src.offset_s) void setOffset(src.id, v);
                }}
                onKeyDown={(e) => e.key === "Enter" && (e.target as HTMLInputElement).blur()}
              />
            </label>
            <label>
              Source
              <select value={src.kind} onChange={(e) => void setKind(src.id, e.target.value as Source["kind"])}>
                <option value="ecu">ECU</option>
                <option value="hcu">HCU</option>
                <option value="other">Other</option>
              </select>
            </label>
          </div>
          <p className="hint">Use this to line up logs from different units, such as ECU and HCU.</p>
        </section>

        <section className="drawer-sec">
          <h3>Calculated channels</h3>
          {math.length > 0 && (
            <ul className="calc">
              {math.map((c) => (
                <li key={c.name}>
                  <div>
                    <strong>{c.name}</strong>
                    <code>{c.expr}</code>
                  </div>
                  <button className="btn ghost sm" onClick={() => void removeDerivedAll(c.name)}>
                    Remove
                  </button>
                </li>
              ))}
            </ul>
          )}
          <div className="calc-form">
            <div className="row">
              <label>
                Name
                <input value={name} onChange={(e) => setName(e.target.value)} placeholder="power_kW" />
              </label>
              <label>
                Unit
                <input value={unit} onChange={(e) => setUnit(e.target.value)} placeholder="kW" />
              </label>
            </div>
            <label>
              Formula
              <input
                value={expr}
                onChange={(e) => setExpr(e.target.value)}
                onKeyDown={(e) => e.key === "Enter" && void submit()}
                placeholder="rpm * 2 * pi / 60"
                spellCheck={false}
                className="mono"
              />
            </label>
            <p className="hint">
              Use channel names, plus pi, t, abs, sqrt, clip, where(c, a, b), deriv(x), integ(x), smooth(x, seconds)
              and lag(x, seconds). For names with symbols write ch("name").
            </p>
            <button className="btn primary" onClick={() => void submit()} disabled={busy || !name.trim() || !expr.trim()}>
              {sources.length > 1 ? `Add to all ${sources.length} logs` : "Add channel"}
            </button>
          </div>
        </section>

        <section className="drawer-sec">
          <details>
            <summary>
              Import notes
              {src.warnings.length ? ` (${src.warnings.length} warning${src.warnings.length > 1 ? "s" : ""})` : ""}
            </summary>
            <ul className="notes">
              {src.assumptions.map((a) => (
                <li key={a}>{a}</li>
              ))}
              {src.warnings.map((w) => (
                <li key={w} className="warn">
                  {w}
                </li>
              ))}
            </ul>
          </details>
        </section>

        <footer className="drawer-foot">
          <button
            className="btn danger"
            onClick={() => {
              void removeSource(src.id);
              setManaging(null);
            }}
          >
            Remove this log
          </button>
        </footer>
      </aside>
    </div>
  );
}
