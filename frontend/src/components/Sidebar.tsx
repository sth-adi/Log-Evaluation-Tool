import { useStore, type Source } from "../store";

export function Sidebar() {
  const sources = useStore((s) => s.sources);
  const addLane = useStore((s) => s.addLane);
  const setOffset = useStore((s) => s.setOffset);
  const setKind = useStore((s) => s.setKind);
  const removeSource = useStore((s) => s.removeSource);
  const arrange = useStore((s) => s.arrange);

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
      {sources.map((src) => (
        <SourceBlock
          key={src.id}
          src={src}
          onPick={(channel, overlay) => addLane({ sourceId: src.id, channel }, overlay)}
          onOffset={(v) => setOffset(src.id, v)}
          onKind={(k) => setKind(src.id, k)}
          onRemove={() => removeSource(src.id)}
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

      <ul className="channels">
        {src.channels.map((c) => (
          <li key={c.name}>
            <button
              className="channel"
              onClick={(e) => props.onPick(c.name, e.shiftKey)}
              title={`${c.name}: ${c.min} to ${c.max} ${c.unit}`}
            >
              <span>{c.name}</span>
              <span className="muted">{c.unit}</span>
            </button>
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
