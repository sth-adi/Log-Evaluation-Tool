import { useEffect, useMemo, useRef, useState } from "react";
import uPlot from "uplot";
import { api } from "../api";
import { useStore, type LaneSeries } from "../store";
import { spansDays, stamp } from "../time";
import { useWindow } from "../useWindow";
import { TRACE, channelGroups, formatValue } from "./Lane";

const ASH = "#8b919c";
const RULE = "#1d2127";
const FONT = '12px "Geist Variable", system-ui, sans-serif';

const keyOf = (s: LaneSeries) => `${s.sourceId}|${s.channel}`;
const fromKey = (k: string): LaneSeries => {
  const i = k.indexOf("|");
  return { sourceId: k.slice(0, i), channel: k.slice(i + 1) };
};

export function Analysis({ kind }: { kind: "statistics" | "histogram" | "spectrum" | "scatter" }) {
  const sources = useStore((s) => s.sources);
  const lanes = useStore((s) => s.lanes);
  const { t0, t1, rev, text } = useWindow();

  const plotted = useMemo(() => lanes.flatMap((l) => l.series), [lanes]);
  const [a, setA] = useState<string>("");
  const [b, setB] = useState<string>("");

  const first = plotted[0] ?? (sources[0] ? { sourceId: sources[0].id, channel: sources[0].channels[0]?.name ?? "" } : null);
  const second = plotted[1] ?? first;
  const chosenA = a || (first ? keyOf(first) : "");
  const chosenB = b || (second ? keyOf(second) : "");

  return (
    <section className="analysis" aria-label="Analysis">
      <div className="analysis-bar">
        {kind !== "statistics" && <ChannelSelect label={kind === "scatter" ? "X" : "Channel"} value={chosenA} onChange={setA} />}
        {kind === "scatter" && <ChannelSelect label="Y" value={chosenB} onChange={setB} />}
        <span className="muted small">Using {text}. Zoom a plot to change it.</span>
      </div>

      <div className="analysis-body">
        {kind === "statistics" && <StatsTable series={plotted} t0={t0} t1={t1} rev={rev} />}
        {kind === "histogram" && chosenA && <HistogramChart k={chosenA} t0={t0} t1={t1} rev={rev} />}
        {kind === "spectrum" && chosenA && <SpectrumChart k={chosenA} t0={t0} t1={t1} rev={rev} />}
        {kind === "scatter" && chosenA && chosenB && <ScatterChart kx={chosenA} ky={chosenB} t0={t0} t1={t1} rev={rev} />}
      </div>
    </section>
  );
}

function ChannelSelect(props: { label: string; value: string; onChange: (v: string) => void }) {
  const sources = useStore((s) => s.sources);
  return (
    <label className="inline">
      {props.label}
      <select value={props.value} onChange={(e) => props.onChange(e.target.value)}>
        {sources.map((src) => (
          <optgroup key={src.id} label={src.label}>
            {src.channels.map((c) => (
              <option key={c.name} value={`${src.id}|${c.name}`}>
                {c.derived ? `ƒ ${c.name}` : c.name}
                {c.unit ? ` (${c.unit})` : ""}
              </option>
            ))}
          </optgroup>
        ))}
      </select>
    </label>
  );
}

/** Fetch with cancellation and an error string instead of an exception. */
export function useFetched<T>(load: () => Promise<T>, deps: unknown[]) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    let live = true;
    setError(null);
    load().then(
      (d) => live && setData(d),
      (e: Error) => {
        if (live) {
          setData(null);
          setError(e.message);
        }
      },
    );
    return () => {
      live = false;
    };
  }, deps);
  return { data, error };
}

function Note({ error, empty }: { error: string | null; empty?: string }) {
  return <p className="muted pad">{error ?? empty ?? "Loading"}</p>;
}

function StatsTable({ series, t0, t1, rev }: { series: LaneSeries[]; t0?: number; t1?: number; rev: number }) {
  const sources = useStore((s) => s.sources);
  const { data, error } = useFetched(async () => {
    const ids = [...new Set(series.map((s) => s.sourceId))];
    const out: Record<string, Awaited<ReturnType<typeof api.stats>>["channels"][string]> = {};
    for (const id of ids) {
      const chans = series.filter((s) => s.sourceId === id).map((s) => s.channel);
      const r = await api.stats(id, chans, t0, t1);
      for (const c of chans) out[`${id}|${c}`] = r.channels[c];
    }
    return out;
  }, [series.map(keyOf).join(","), t0, t1, rev]);

  if (!series.length) return <Note error={null} empty="Plot some channels and their statistics appear here." />;
  if (!data) return <Note error={error} />;
  const cols: [string, string][] = [
    ["Min", "min"], ["Max", "max"], ["Mean", "mean_time_weighted"], ["Median", "median"],
    ["Std dev", "std"], ["5th pct", "p5"], ["95th pct", "p95"],
  ];
  return (
    <table className="stats">
      <thead>
        <tr>
          <th scope="col">Channel</th>
          {cols.map(([h]) => (
            <th key={h} scope="col" className="num">{h}</th>
          ))}
          <th scope="col" className="num">Max at (s)</th>
          <th scope="col" className="num">Valid</th>
        </tr>
      </thead>
      <tbody>
        {series.map((s) => {
          const r = data[keyOf(s)];
          const src = sources.find((x) => x.id === s.sourceId);
          const unit = src?.channels.find((c) => c.name === s.channel)?.unit;
          const logTag = sources.length > 1 && src ? (src.started_at ? stamp(src.started_at, spansDays(sources)) : src.label) : "";
          const colour = TRACE[channelGroups(series).indexOf(s.channel) % TRACE.length];
          return (
            <tr key={keyOf(s)}>
              <th scope="row">
                <span className="swatch" style={{ background: colour }} aria-hidden />
                {s.channel}
                {unit && <small> {unit}</small>}
                {logTag && <small className="log-tag">{logTag}</small>}
              </th>
              {cols.map(([h, k]) => (
                <td key={h} className="num">{r?.count ? formatValue(r[k]) : "–"}</td>
              ))}
              <td className="num">{r?.count ? formatValue(r.t_max) : "–"}</td>
              <td className="num">{r ? r.count.toLocaleString() : "–"}</td>
            </tr>
          );
        })}
      </tbody>
    </table>
  );
}

export function Chart(props: { build: (w: number, h: number) => uPlot.Options; data: uPlot.AlignedData; note?: string }) {
  const box = useRef<HTMLDivElement>(null);
  const [size, setSize] = useState<[number, number]>([0, 0]);
  useEffect(() => {
    const el = box.current;
    if (!el) return;
    const ro = new ResizeObserver(() => setSize([Math.floor(el.clientWidth), Math.floor(el.clientHeight)]));
    ro.observe(el);
    return () => ro.disconnect();
  }, []);
  useEffect(() => {
    const el = box.current;
    if (!el || size[0] < 50 || size[1] < 50) return;
    const u = new uPlot(props.build(size[0], size[1]), props.data, el);
    return () => u.destroy();
  }, [props.data, size[0], size[1]]);
  return (
    <div className="chart-wrap">
      <div ref={box} className="chart" />
      {props.note && <p className="chart-note">{props.note}</p>}
    </div>
  );
}

/** x values followed by one y series per line, in the shape uPlot wants. */
export function alignedData(x: number[], ys: (number | null)[][]): uPlot.AlignedData {
  const data: [number[], ...(number | null)[][]] = [x, ...ys];
  return data;
}

export const axis = (label: string, extra: Partial<uPlot.Axis> = {}): uPlot.Axis => ({
  label,
  labelFont: FONT,
  stroke: ASH,
  font: FONT,
  grid: { stroke: RULE, width: 1 },
  ticks: { stroke: RULE, width: 1, size: 4 },
  ...extra,
});

function useChannelInfo(k: string) {
  const sources = useStore((s) => s.sources);
  const s = fromKey(k);
  const ch = sources.find((x) => x.id === s.sourceId)?.channels.find((c) => c.name === s.channel);
  return { ...s, unit: ch?.unit ?? "" };
}

function HistogramChart({ k, t0, t1, rev }: { k: string; t0?: number; t1?: number; rev: number }) {
  const info = useChannelInfo(k);
  const { data, error } = useFetched(() => api.histogram(info.sourceId, info.channel, 40, t0, t1), [k, t0, t1, rev]);
  const plot = useMemo<uPlot.AlignedData | null>(() => {
    if (!data || !data.counts.length) return null;
    const centres = data.counts.map((_, i) => (data.edges[i] + data.edges[i + 1]) / 2);
    return [centres, data.counts];
  }, [data]);
  if (!plot) return <Note error={error} empty={data ? "No valid samples in this window." : undefined} />;
  return (
    <Chart
      data={plot}
      note={`${data!.total.toLocaleString()} samples. Bar height is the number of samples in that value range.`}
      build={(w, h) => ({
        width: w, height: h, legend: { show: false }, cursor: { drag: { x: false, y: false } },
        scales: { x: { time: false } },
        axes: [axis(`${info.channel}${info.unit ? ` (${info.unit})` : ""}`), axis("Samples", { size: 64 })],
        series: [{}, { stroke: TRACE[0], fill: TRACE[0] + "99", paths: uPlot.paths.bars!({ size: [0.92, 100] }), points: { show: false } }],
      })}
    />
  );
}

function SpectrumChart({ k, t0, t1, rev }: { k: string; t0?: number; t1?: number; rev: number }) {
  const info = useChannelInfo(k);
  const { data, error } = useFetched(() => api.spectrum(info.sourceId, info.channel, t0, t1), [k, t0, t1, rev]);
  const plot = useMemo<uPlot.AlignedData | null>(() => (data ? [data.freq_hz, data.amplitude] : null), [data]);
  if (!plot) return <Note error={error} />;
  const peaks = data!.peaks.map((p) => `${p.freq_hz.toFixed(2)} Hz`).join(", ");
  return (
    <Chart
      data={plot}
      note={`Sampled at ${data!.sample_rate_hz.toFixed(1)} Hz, ${data!.samples.toLocaleString()} samples. Strongest peaks: ${peaks || "none"}.`}
      build={(w, h) => ({
        width: w, height: h, legend: { show: false }, cursor: { drag: { x: true, y: false } },
        scales: { x: { time: false, distr: 3 }, y: { range: (_u, _mn, mx) => [0, mx * 1.08 || 1] } }, // log frequency: engine signals live at low Hz
        axes: [axis("Frequency (Hz)"), axis(`Amplitude${info.unit ? ` (${info.unit})` : ""}`, { size: 64 })],
        series: [{}, { stroke: TRACE[1], width: 1.25, points: { show: false } }],
      })}
    />
  );
}

function ScatterChart({ kx, ky, t0, t1, rev }: { kx: string; ky: string; t0?: number; t1?: number; rev: number }) {
  const ix = useChannelInfo(kx);
  const iy = useChannelInfo(ky);
  const { data, error } = useFetched(
    () => (ix.sourceId === iy.sourceId ? api.scatter(ix.sourceId, ix.channel, iy.channel, t0, t1) : Promise.reject(new Error("Pick both channels from the same log."))),
    [kx, ky, t0, t1, rev],
  );
  const plot = useMemo<uPlot.AlignedData | null>(() => {
    if (!data || !data.x.length) return null;
    const order = data.x.map((_, i) => i).sort((p, q) => data.x[p] - data.x[q]);
    return [order.map((i) => data.x[i]), order.map((i) => data.y[i])];
  }, [data]);
  if (!plot) return <Note error={error} empty={data ? "No samples with both channels valid." : undefined} />;
  const corr = data!.correlation == null ? "n/a" : data!.correlation.toFixed(3);
  return (
    <Chart
      data={plot}
      note={`${data!.points.toLocaleString()} samples (drawn: ${data!.x.length.toLocaleString()}). Correlation ${corr}.`}
      build={(w, h) => ({
        width: w, height: h, legend: { show: false }, cursor: { drag: { x: true, y: true } },
        scales: { x: { time: false } },
        axes: [
          axis(`${ix.channel}${ix.unit ? ` (${ix.unit})` : ""}`),
          axis(`${iy.channel}${iy.unit ? ` (${iy.unit})` : ""}`, { size: 64 }),
        ],
        series: [{}, { stroke: TRACE[2], width: 0, paths: () => null, points: { show: true, size: 4, fill: TRACE[2] + "aa", stroke: TRACE[2] } }],
      })}
    />
  );
}

export function EventsPanel() {
  const sources = useStore((s) => s.sources);
  const refresh = useStore((s) => s.refresh);
  const setView = useStore((s) => s.setView);
  const setMode = useStore((s) => s.setMode);

  // A rule applies to every log, so list each rule once.
  const rules = useMemo(() => {
    const m = new Map<string, { name: string; expr: string; min_duration_s: number }>();
    for (const src of sources) for (const r of src.rules ?? []) if (!m.has(r.name)) m.set(r.name, r);
    return [...m.values()];
  }, [sources]);

  const [name, setName] = useState("");
  const [expr, setExpr] = useState("");
  const [minDur, setMinDur] = useState("0.5");
  const [err, setErr] = useState<string | null>(null);
  const [tick, setTick] = useState(0);

  const sig = sources.map((s) => `${s.id}:${s.offset_s}:${(s.rules ?? []).map((r) => r.name + r.expr).join("|")}`).join(";");
  const { data: events, error } = useFetched(async () => {
    const all = await Promise.all(sources.map((src) => api.events(src.id).then((es) => es.map((e) => ({ ...e, src })))));
    return all.flat().sort((x, y) => x.t_start - y.t_start);
  }, [sig, tick]);

  const add = async () => {
    setErr(null);
    let done = 0;
    let first = "";
    for (const src of sources) {
      try {
        await api.addRule(src.id, { name: name.trim(), expr, min_duration_s: parseFloat(minDur) || 0, merge_gap_s: 0 });
        done += 1;
      } catch (e) {
        if (!first) first = (e as Error).message;
      }
    }
    if (done === 0) setErr(first);
    else {
      setName("");
      setExpr("");
      if (first) setErr(`Added to ${done} of ${sources.length} logs. ${first}`);
    }
    await refresh();
    setTick((x) => x + 1);
  };
  const remove = async (n: string) => {
    for (const src of sources) if ((src.rules ?? []).some((r) => r.name === n)) await api.removeRule(src.id, n);
    await refresh();
    setTick((x) => x + 1);
  };
  const show = (a: number, b: number) => {
    const pad = Math.max((b - a) * 0.5, 1);
    setView([a - pad, b + pad]);
    setMode("plots");
  };
  const multiDay = spansDays(sources);
  const clock = (s: { started_at: string | null; label: string }) => (s.started_at ? stamp(s.started_at, multiDay) : s.label);

  return (
    <div className="events">
      <div className="rule-form">
        <label className="inline">
          Rule name
          <input value={name} onChange={(e) => setName(e.target.value)} placeholder="Coolant hot" />
        </label>
        <label className="inline grow">
          Condition
          <input
            value={expr}
            onChange={(e) => setExpr(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && name.trim() && expr.trim() && void add()}
            placeholder="ect1 > 95 and rpm > 3000"
            spellCheck={false}
          />
        </label>
        <label className="inline">
          For at least (s)
          <input type="number" min="0" step="0.1" value={minDur} onChange={(e) => setMinDur(e.target.value)} />
        </label>
        <button className="btn primary" disabled={!name.trim() || !expr.trim() || !sources.length} onClick={() => void add()}>
          {sources.length > 1 ? `Add to all ${sources.length} logs` : "Add rule"}
        </button>
      </div>
      {err && (
        <p className="rule-error" role="alert">
          {err}
        </p>
      )}
      <p className="muted small pad">
        A condition is true or false at each sample, for example <code>rpm &gt; 11500</code> or{" "}
        <code>vehicleSpeed &lt; 1 and rpm &gt; 4000</code>. An event is a stretch where it stays true.
      </p>

      {rules.length > 0 && (
        <ul className="rules">
          {rules.map((r) => (
            <li key={r.name}>
              <strong>{r.name}</strong> <code>{r.expr}</code>
              <span className="muted small"> for at least {r.min_duration_s} s</span>
              <button className="link" onClick={() => void remove(r.name)} aria-label={`Remove rule ${r.name}`}>
                Remove
              </button>
            </li>
          ))}
        </ul>
      )}

      {error ? (
        <p className="rule-error" role="alert">
          {error}
        </p>
      ) : rules.length === 0 ? null : !events ? (
        <p className="muted pad">Loading</p>
      ) : events.length === 0 ? (
        <p className="muted pad">No events: none of the rules held for long enough.</p>
      ) : (
        <table className="stats">
          <thead>
            <tr>
              <th scope="col">Rule</th>
              {sources.length > 1 && <th scope="col">Log</th>}
              <th scope="col" className="num">Start (s)</th>
              <th scope="col" className="num">End (s)</th>
              <th scope="col" className="num">Length (s)</th>
              <th scope="col"><span className="sr">Jump</span></th>
            </tr>
          </thead>
          <tbody>
            {events.map((e, i) => (
              <tr key={i}>
                <th scope="row">{e.rule}</th>
                {sources.length > 1 && <td>{clock(e.src)}</td>}
                <td className="num">{formatValue(e.t_start)}</td>
                <td className="num">{formatValue(e.t_end)}</td>
                <td className="num">{formatValue(e.duration_s)}</td>
                <td>
                  <button className="link" onClick={() => show(e.t_start, e.t_end)}>
                    Show on plots
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}
