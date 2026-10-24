import { useState } from "react";
import { useStore, type Source } from "../store";

export function Sidebar() {
  const sources = useStore((s) => s.sources);
  const addLane = useStore((s) => s.addLane);
  const setOffset = useStore((s) => s.setOffset);
  const setKind = useStore((s) => s.setKind);
  const removeSource = useStore((s) => s.removeSource);
  const arrange = useStore((s) => s.arrange);
  const addDerived = useStore((s) => s.addDerived);
  const addChannelAll = useStore((s) => s.addChannelAll);
  const removeDerived = useStore((s) => s.removeDerived);

  if (!sources.length) {
    return (
      <nav className="sidebar" aria-label="Sources">
        <p className="muted pad">No logs imported yet.</p>
      </nav>
    );
  }

  return (
    <nav className="sidebar" aria-label="Sources and channels">
      <p className="muted pad hint">Click a channel to plot it. Shift-click overlays it on the last plot.</p>
      {sources.length > 1 && (
        <div className="pad arrange">
          <span className="muted small">Order logs by session start:</span>
          <button onClick={() => arrange("sequential")} title="Lay the logs end to end, earliest first">
            Back to back
          </button>
          <button onClick={() => arrange("real")} title="Keep the real time gaps between sessions">
            Real time
          </button>
        </div>
      )}
      {sources.length > 1 && <AllLogs onPick={addChannelAll} />}
      {sources.map((src) => (
        <SourceBlock
          key={src.id}
          src={src}
          onPick={(channel, overlay) => addLane({ sourceId: src.id, channel }, overlay)}
          onOffset={(v) => setOffset(src.id, v)}
          onKind={(k) => setKind(src.id, k)}
          onRemove={() => removeSource(src.id)}
          onAddDerived={(n, e, u) => addDerived(src.id, n, e, u)}
          onRemoveDerived={(n) => removeDerived(src.id, n)}
        />
      ))}
    </nav>
  );
}

function SourceBlock(props: {
  src: Source;
  onPick: (channel: string, overlay: boolean) => void;
  onOffset: (v: number) => void;
  onKind: (k: Source["kind"]) => void;
  onRemove: () => void;
  onAddDerived: (name: string, expr: string, unit: string) => Promise<boolean>;
  onRemoveDerived: (name: string) => void;
}) {
  const { src } = props;
  return (
    <section className="source">
      <header className="source-head">
        <h3>{src.label}</h3>
        <button className="link" onClick={props.onRemove} aria-label={`Remove ${src.label}`}>
          Remove
        </button>
      </header>
      <p className="muted small">
        {src.filename}: {src.rows.toLocaleString()} rows, {src.sample_rate_hz ?? "?"} Hz,{" "}
        {src.duration_s.toFixed(1)} s{src.started_at ? `, started ${src.started_at.replace("T", " ")}` : ""}{src.gaps ? `, ${src.gaps} gap${src.gaps > 1 ? "s" : ""}` : ""}
      </p>

      <div className="fields">
        <label>
          Type
          <select value={src.kind} onChange={(e) => props.onKind(e.target.value as Source["kind"])}>
            <option value="ecu">ECU</option>
            <option value="hcu">HCU</option>
            <option value="other">Other</option>
          </select>
        </label>
        <label>
          Time offset (s)
          <input
            type="number"
            step="0.01"
            defaultValue={src.offset_s}
            key={`${src.id}-${src.offset_s}`}
            onBlur={(e) => {
              const v = parseFloat(e.target.value);
              if (Number.isFinite(v) && v !== src.offset_s) props.onOffset(v);
            }}
            onKeyDown={(e) => e.key === "Enter" && (e.target as HTMLInputElement).blur()}
          />
        </label>
      </div>

      <MathForm onAdd={props.onAddDerived} />

      <ul className="channels">
        {src.channels.map((c) => (
          <li key={c.name} className={c.derived ? "derived" : undefined}>
            <button
              className="channel"
              onClick={(e) => props.onPick(c.name, e.shiftKey)}
              title={`${c.name}: ${c.min} to ${c.max} ${c.unit}`}
            >
              <span>{c.derived ? `ƒ ${c.name}` : c.name}</span>
              <span className="muted">{c.unit}</span>
            </button>
            {c.derived && (
              <button
                className="link"
                onClick={() => props.onRemoveDerived(c.name)}
                aria-label={`Remove math channel ${c.name}`}
                title={`= ${c.expr}`}
              >
                ×
              </button>
            )}
          </li>
        ))}
      </ul>

      <details className="assumptions">
        <summary>What the importer assumed{src.warnings.length ? ` (${src.warnings.length} warning${src.warnings.length > 1 ? "s" : ""})` : ""}</summary>
        <ul>
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
  );
}

function MathForm({ onAdd }: { onAdd: (name: string, expr: string, unit: string) => Promise<boolean> }) {
  const [name, setName] = useState("");
  const [expr, setExpr] = useState("");
  const [unit, setUnit] = useState("");
  const [busy, setBusy] = useState(false);
  const submit = async () => {
    if (!name.trim() || !expr.trim() || busy) return;
    setBusy(true);
    const ok = await onAdd(name, expr, unit);
    setBusy(false);
    if (ok) {
      setName("");
      setExpr("");
      setUnit("");
    }
  };
  return (
    <details className="mathform">
      <summary>Add math channel</summary>
      <div className="fields">
        <label>
          Name
          <input value={name} onChange={(e) => setName(e.target.value)} placeholder="power_kW" />
        </label>
        <label>
          Unit
          <input value={unit} onChange={(e) => setUnit(e.target.value)} placeholder="kW" />
        </label>
      </div>
      <label className="formula">
        Formula
        <input
          value={expr}
          onChange={(e) => setExpr(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && submit()}
          placeholder="rpm * 2 * pi / 60"
          spellCheck={false}
        />
      </label>
      <p className="muted small">
        Channels by name, plus pi, t, abs sqrt sin cos log, clip, where(c,a,b), deriv(x), integ(x),
        smooth(x, seconds), lag(x, seconds). Use ch("name") for names with symbols.
      </p>
      <button className="primary" onClick={submit} disabled={busy}>
        Add
      </button>
    </details>
  );
}

/** Channels found in any log; picking one plots it across every log that has it, on one timeline. */
function AllLogs({ onPick }: { onPick: (channel: string, overlay: boolean) => void }) {
  const sources = useStore((s) => s.sources);
  const [filter, setFilter] = useState("");
  const channels = new Map<string, { unit: string; logs: number }>();
  for (const src of sources)
    for (const c of src.channels) {
      const e = channels.get(c.name);
      if (e) e.logs += 1;
      else channels.set(c.name, { unit: c.unit, logs: 1 });
    }
  const shown = [...channels].filter(([n]) => n.toLowerCase().includes(filter.toLowerCase()));
  return (
    <section className="source all-logs">
      <header className="source-head">
        <h3>All logs</h3>
      </header>
      <p className="muted small">
        {sources.length} logs on one timeline. Click a channel to plot it across all of them.
      </p>
      <input
        className="filter"
        type="search"
        value={filter}
        onChange={(e) => setFilter(e.target.value)}
        placeholder="Find a channel"
        aria-label="Find a channel"
      />
      <ul className="channels all">
        {shown.map(([name, c]) => (
          <li key={name}>
            <button className="channel" onClick={(e) => onPick(name, e.shiftKey)} title={`${name}: in ${c.logs} of ${sources.length} logs`}>
              <span>{name}</span>
              <span className="muted">{c.logs < sources.length ? `${c.logs}/${sources.length} ` : ""}{c.unit}</span>
            </button>
          </li>
        ))}
      </ul>
    </section>
  );
}
