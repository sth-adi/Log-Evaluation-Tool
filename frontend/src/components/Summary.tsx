import { useEffect, useMemo, useState } from "react";
import { api, type SummaryData } from "../api";
import { useStore, type Metric } from "../store";
import { spansDays, stamp } from "../time";
import { formatValue } from "./Lane";

const AGGS: [string, string][] = [
  ["max", "Highest"],
  ["min", "Lowest"],
  ["mean", "Average"],
  ["median", "Median"],
  ["p95", "95th percentile"],
  ["std", "Spread (std dev)"],
  ["first", "First value"],
  ["last", "Last value"],
  ["integral", "Total (value x time)"],
  ["seconds", "Seconds the condition holds"],
];
const aggLabel = (a: string) => AGGS.find((x) => x[0] === a)?.[1] ?? a;
const exprFor = (ch: string) => (/^[A-Za-z_]\w*$/.test(ch) ? ch : `ch("${ch.replace(/"/g, "")}")`);
let counter = 1;

/** One number per log for each metric you choose, so runs can be compared at a glance. */
export function SummaryPanel({ t0, t1, rev }: { t0?: number; t1?: number; rev: number }) {
  const sources = useStore((s) => s.sources);
  const metrics = useStore((s) => s.metrics);
  const setMetrics = useStore((s) => s.setMetrics);
  const names = useMemo(() => [...new Set(sources.flatMap((s) => s.channels.map((c) => c.name)))], [sources]);
  const unitOf = (ch: string) => sources.flatMap((s) => s.channels).find((c) => c.name === ch)?.unit ?? "";

  const [channel, setChannel] = useState("");
  const [agg, setAgg] = useState("max");
  const [where, setWhere] = useState("");
  const [ref, setRef] = useState("");
  const [data, setData] = useState<SummaryData | null>(null);
  const [error, setError] = useState<string | null>(null);

  const chosen = channel || names[0] || "";
  const has = (re: RegExp) => names.find((n) => re.test(n));
  const presets = useMemo(() => {
    const rpm = has(/^rpm$/i), tps = has(/^tps1?$/i), lam = has(/^lam1$/i), ect = has(/^ect1$/i), spd = has(/^vehiclespeed$/i), vb = has(/^vbat$/i);
    const p: { label: string; m: Omit<Metric, "id"> }[] = [];
    if (rpm) p.push({ label: `Peak ${rpm}`, m: { name: `Peak ${rpm}`, expr: exprFor(rpm), agg: "max", where: "", unit: unitOf(rpm) } });
    if (spd) p.push({ label: `Top ${spd}`, m: { name: `Top ${spd}`, expr: exprFor(spd), agg: "max", where: "", unit: unitOf(spd) } });
    if (lam && tps) p.push({ label: `Average ${lam} at full throttle`, m: { name: `Average ${lam} at full throttle`, expr: exprFor(lam), agg: "mean", where: `${exprFor(tps)} > 90`, unit: unitOf(lam) } });
    if (tps) p.push({ label: "Time at full throttle", m: { name: "Time at full throttle", expr: exprFor(tps), agg: "seconds", where: `${exprFor(tps)} > 90`, unit: "s" } });
    if (ect) p.push({ label: `Hottest ${ect}`, m: { name: `Hottest ${ect}`, expr: exprFor(ect), agg: "max", where: "", unit: unitOf(ect) } });
    if (vb) p.push({ label: `Lowest ${vb}`, m: { name: `Lowest ${vb}`, expr: exprFor(vb), agg: "min", where: "", unit: unitOf(vb) } });
    return p.filter((x) => !metrics.some((m) => m.name === x.m.name));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [names, metrics]);

  const add = (m: Omit<Metric, "id">) => {
    if (metrics.some((x) => x.name === m.name)) return setError(`There is already a metric called "${m.name}".`);
    setError(null);
    setMetrics([...metrics, { ...m, id: `m${Date.now()}${counter++}` }]);
  };
  const addCustom = () => {
    if (!chosen) return;
    const w = where.trim();
    const name = agg === "seconds" ? `Seconds when ${w || "…"}` : `${aggLabel(agg)} ${chosen}${w ? ` when ${w}` : ""}`;
    if (agg === "seconds" && !w) return setError("Type the condition to time, for example tps1 > 90.");
    add({ name, expr: exprFor(chosen), agg, where: w, unit: agg === "seconds" ? "s" : agg === "integral" ? "" : unitOf(chosen) });
    setWhere("");
  };

  const ids = sources.map((s) => s.id);
  const key = JSON.stringify(metrics.map((m) => [m.name, m.expr, m.agg, m.where]));
  useEffect(() => {
    if (!metrics.length || !ids.length) {
      setData(null);
      return;
    }
    let live = true;
    api.summary(ids, metrics, t0, t1).then(
      (d) => live && (setData(d), setError(null)),
      (e: Error) => live && (setData(null), setError(e.message)),
    );
    return () => {
      live = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [ids.join(","), key, t0, t1, rev]);

  const withDate = spansDays(sources);
  const tag = (id: string) => {
    const s = sources.find((x) => x.id === id);
    return s ? (s.started_at ? stamp(s.started_at, withDate) : s.label) : id;
  };
  const rows = data ? [...data.rows].sort((a, b) => (a.started_at ?? "").localeCompare(b.started_at ?? "")) : [];
  const refRow = rows.find((r) => r.id === ref);
  const colMax = (name: string) => Math.max(...rows.map((r) => Math.abs(r.values[name] ?? 0)), 1e-12);

  return (
    <div className="summary">
      <div className="summary-build">
        <label className="inline">
          Measure
          <select value={chosen} onChange={(e) => setChannel(e.target.value)}>
            {names.map((n) => (
              <option key={n} value={n}>{n}</option>
            ))}
          </select>
        </label>
        <label className="inline">
          As
          <select value={agg} onChange={(e) => setAgg(e.target.value)}>
            {AGGS.map(([k, l]) => (
              <option key={k} value={k}>{l}</option>
            ))}
          </select>
        </label>
        <label className="inline grow" title="Only count samples where this is true. Use channel names, for example tps1 > 90 and rpm > 6000.">
          Only when
          <input value={where} onChange={(e) => setWhere(e.target.value)} onKeyDown={(e) => e.key === "Enter" && addCustom()} placeholder="optional, for example tps1 > 90" spellCheck={false} className="mono" />
        </label>
        <button className="btn primary" onClick={addCustom}>Add</button>
      </div>
      {presets.length > 0 && (
        <div className="chips">
          <span className="muted small">Quick add</span>
          {presets.map((p) => (
            <button key={p.label} className="chip" onClick={() => add(p.m)}>
              {p.label}
            </button>
          ))}
        </div>
      )}
      {error && <p className="live-error pad">{error}</p>}

      {metrics.length === 0 ? (
        <p className="muted pad">Add a metric to compare your logs side by side, for example the highest RPM or the average lambda at full throttle.</p>
      ) : !data ? (
        !error && <p className="muted pad">Working it out</p>
      ) : (
        <>
          <div className="summary-tools">
            <label className="inline">
              Compare to
              <select value={ref} onChange={(e) => setRef(e.target.value)}>
                <option value="">Nothing</option>
                {rows.map((r) => (
                  <option key={r.id} value={r.id}>{tag(r.id)}</option>
                ))}
              </select>
            </label>
            <span className="muted small">{rows.length} log{rows.length === 1 ? "" : "s"}. Bars show each value against the largest in its column.</span>
          </div>
          <div className="summary-scroll">
            <table className="stats summary-table">
              <thead>
                <tr>
                  <th scope="col">Log</th>
                  {metrics.map((m) => (
                    <th key={m.id} scope="col" className="num">
                      <span className="metric-name" title={m.where ? `${aggLabel(m.agg)} of ${m.expr} only when ${m.where}` : `${aggLabel(m.agg)} of ${m.expr}`}>{m.name}</span>
                      {m.unit && <small> {m.unit}</small>}
                      <button className="icon-btn x" onClick={() => setMetrics(metrics.filter((x) => x.id !== m.id))} aria-label={`Remove ${m.name}`}>
                        ×
                      </button>
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {rows.map((r) => (
                  <tr key={r.id} className={r.id === ref ? "ref" : undefined}>
                    <th scope="row">
                      {tag(r.id)} <small>{r.label.length > 34 ? `${r.label.slice(0, 34)}…` : r.label}</small>
                    </th>
                    {metrics.map((m) => {
                      const v = r.values[m.name];
                      const d = refRow && r.id !== ref && v != null && refRow.values[m.name] != null ? v - (refRow.values[m.name] as number) : null;
                      const err = data.errors[m.name]?.[r.id];
                      return (
                        <td key={m.id} className="num bar-cell" style={{ "--w": `${v == null ? 0 : (Math.abs(v) / colMax(m.name)) * 100}%` } as React.CSSProperties} title={err}>
                          <span>{v == null ? "–" : formatValue(v)}</span>
                          {d != null && <small className={d === 0 ? "" : d > 0 ? "up" : "down"}>{d === 0 ? "same" : `${d > 0 ? "+" : "−"}${formatValue(Math.abs(d))}`}</small>}
                        </td>
                      );
                    })}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}
    </div>
  );
}
