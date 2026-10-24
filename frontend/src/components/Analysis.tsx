import { useEffect, useMemo, useRef, useState } from "react";
import uPlot from "uplot";
import { api } from "../api";
import { extentOf, useStore, type LaneSeries } from "../store";
import { TRACE, formatValue } from "./Lane";

type Kind = "stats" | "histogram" | "spectrum" | "scatter";
const KINDS: { id: Kind; label: string }[] = [
  { id: "stats", label: "Statistics" },
  { id: "histogram", label: "Histogram" },
  { id: "spectrum", label: "Spectrum" },
  { id: "scatter", label: "Scatter" },
];

const ASH = "#9a9a9a";
const RULE = "#333333";
const FONT = '12px "Barlow Semi Condensed", system-ui, sans-serif';

const keyOf = (s: LaneSeries) => `${s.sourceId}|${s.channel}`;
const fromKey = (k: string): LaneSeries => {
  const i = k.indexOf("|");
  return { sourceId: k.slice(0, i), channel: k.slice(i + 1) };
};

export function Analysis() {
  const sources = useStore((s) => s.sources);
  const lanes = useStore((s) => s.lanes);
  const view = useStore((s) => s.view);
  const rev = useStore((s) => s.rev);

  const plotted = useMemo(() => lanes.flatMap((l) => l.series), [lanes]);
  const [kind, setKind] = useState<Kind>("stats");
  const [a, setA] = useState<string>("");
  const [b, setB] = useState<string>("");

  const first = plotted[0] ?? (sources[0] ? { sourceId: sources[0].id, channel: sources[0].channels[0]?.name ?? "" } : null);
  const second = plotted[1] ?? first;
  const chosenA = a || (first ? keyOf(first) : "");
  const chosenB = b || (second ? keyOf(second) : "");
  const [e0, e1] = extentOf(sources);
  const zoomed = view != null && (Math.abs(view[0] - e0) > 1e-6 || Math.abs(view[1] - e1) > 1e-6);
  const t0 = zoomed ? view[0] : undefined;
  const t1 = zoomed ? view[1] : undefined;
  const windowText = zoomed ? `${view[0].toFixed(2)} to ${view[1].toFixed(2)} s (zoomed window)` : "the whole log";

  return (
    <section className="analysis" aria-label="Analysis">
      <div className="analysis-bar">
        <div className="seg" role="tablist" aria-label="Analysis type">
          {KINDS.map((k) => (
            <button
              key={k.id}
              role="tab"
              aria-selected={kind === k.id}
              className={kind === k.id ? "on" : undefined}
              onClick={() => setKind(k.id)}
            >
              {k.label}
            </button>
          ))}
        </div>
        {kind !== "stats" && (
          <ChannelSelect label={kind === "scatter" ? "X" : "Channel"} value={chosenA} onChange={setA} />
        )}
        {kind === "scatter" && <ChannelSelect label="Y" value={chosenB} onChange={setB} />}
        <span className="muted small">Using {windowText}. Zoom a plot to change it.</span>
      </div>

      <div className="analysis-body">
        {kind === "stats" && <StatsTable series={plotted} t0={t0} t1={t1} rev={rev} />}
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
function useFetched<T>(load: () => Promise<T>, deps: unknown[]) {
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
    // eslint-disable-next-line react-hooks/exhaustive-deps
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
        {series.map((s, i) => {
          const r = data[keyOf(s)] as unknown as Record<string, number> | undefined;
          const unit = sources.find((x) => x.id === s.sourceId)?.channels.find((c) => c.name === s.channel)?.unit;
          return (
            <tr key={keyOf(s)}>
              <th scope="row">
                <span className="swatch" style={{ background: TRACE[i % TRACE.length] }} aria-hidden />
                {s.channel}
                {unit && <small> {unit}</small>}
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

function Chart(props: { build: (w: number, h: number) => uPlot.Options; data: uPlot.AlignedData; note?: string }) {
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
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [props.data, size[0], size[1]]);
  return (
    <div className="chart-wrap">
      <div ref={box} className="chart" />
      {props.note && <p className="chart-note">{props.note}</p>}
    </div>
  );
}

const axis = (label: string, extra: Partial<uPlot.Axis> = {}): uPlot.Axis => ({
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
