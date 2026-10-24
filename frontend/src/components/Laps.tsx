import { useEffect, useMemo, useRef, useState } from "react";
import uPlot from "uplot";
import { api, type LapParams, type LapRow, type LapView, type Track } from "../api";
import { useStore, type Source } from "../store";
import { Chart, axis, useFetched } from "./Analysis";
import { formatValue } from "./Lane";

const LAP_COLOURS = ["#38c8f0", "#ffb020", "#3ddc84", "#b79bff", "#ff8fb1", "#e8e8e8", "#7fa6ff", "#d6e34a"];
const REF_COLOUR = "#ff3b47";
const RAMP = ["#2f6df0", "#38c8f0", "#3ddc84", "#ffb020", "#ff3b47"];

const lapColour = (n: number, isRef: boolean) => (isRef ? REF_COLOUR : LAP_COLOURS[n % LAP_COLOURS.length]);

/** 1:12.345 */
export function fmtLap(s: number): string {
  const m = Math.floor(s / 60);
  return `${m}:${(s - m * 60).toFixed(3).padStart(6, "0")}`;
}
const fmtDelta = (s: number) => (s === 0 ? "–" : `${s > 0 ? "+" : "−"}${Math.abs(s).toFixed(3)}`);

const METHODS: { id: LapParams["method"]; label: string; help: string }[] = [
  { id: "auto", label: "Automatic", help: "Looks for a lap timer or last-lap-time channel the logger already records." },
  { id: "reset", label: "Lap timer", help: "A timer that counts up through the lap and drops back to zero at the line." },
  { id: "change", label: "Lap counter", help: "A counter or last-lap-time that takes a new value each time you cross the line." },
  { id: "trigger", label: "Beacon signal", help: "A start/finish signal; a lap starts each time it rises through the level." },
  { id: "distance", label: "Fixed length", help: "A lap every set number of metres. Handy for skidpad and autocross runs." },
  { id: "manual", label: "Times I enter", help: "Type the times, in seconds, that you crossed the line." },
];

export function Laps() {
  const sources = useStore((s) => s.sources);
  const [sid, setSid] = useState("");
  const src = sources.find((x) => x.id === sid) ?? sources[0];
  // keyed by log, so switching logs starts from clean lap, channel and reference choices
  return <LapsView key={src.id} src={src} sources={sources} onPick={setSid} />;
}

function LapsView({ src, sources, onPick }: { src: Source; sources: Source[]; onPick: (id: string) => void }) {
  const rev = useStore((s) => s.rev);

  const [params, setParams] = useState<LapParams>({ method: "auto" });
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [axisKind, setAxisKind] = useState<"distance" | "time">("distance");
  const [picked, setPicked] = useState<string[]>([]);
  const [sel, setSel] = useState<number[] | null>(null);
  const [ref, setRef] = useState<number | null>(null);
  const [colourBy, setColourBy] = useState("");
  const [mirror, setMirror] = useState(false);

  const names = useMemo(() => src.channels.map((c) => c.name), [src]);
  const key = JSON.stringify(params);
  const table = useFetched(() => api.laps(src.id, params), [src.id, key, rev]);
  const laps = table.data?.laps ?? [];

  const defaults = useMemo(() => {
    const find = (re: RegExp) => names.find((n) => re.test(n));
    return [table.data?.speed_channel, find(/^(tps1?|throttle)$/i), find(/^rpm$/i)].filter(Boolean) as string[];
  }, [names, table.data?.speed_channel]);
  const channels = picked.length ? picked : defaults;
  const hasDistance = !!table.data?.speed_channel;
  const axisUsed = hasDistance ? axisKind : "time";
  const selected = sel ?? laps.filter((l) => l.valid).map((l) => l.n);
  const refN = ref ?? table.data?.best ?? null;

  const view = useFetched(
    async () => (laps.length && channels.length ? api.lapView(src.id, params, channels, selected, refN, axisUsed) : null),
    [src.id, key, channels.join(","), selected.join(","), refN, axisUsed, laps.length, rev],
  );

  const colour = colourBy || table.data?.speed_channel || "";
  const track = useFetched(() => api.track(src.id, params, colour || undefined, mirror), [src.id, key, colour, mirror, rev]);

  const apply = (p: LapParams) => {
    setParams(p);
    setSel(null);
    setRef(null);
  };
  const toggle = (n: number) => setSel((cur) => ((cur ?? selected).includes(n) ? (cur ?? selected).filter((x) => x !== n) : [...(cur ?? selected), n]));

  return (
    <section className="analysis laps" aria-label="Laps">
      <div className="analysis-bar">
        {sources.length > 1 && (
          <label className="inline">
            Log
            <select value={src.id} onChange={(e) => onPick(e.target.value)}>
              {sources.map((s) => (
                <option key={s.id} value={s.id}>{s.label}</option>
              ))}
            </select>
          </label>
        )}
        <div className="seg" role="tablist" aria-label="Lap axis">
          <button role="tab" aria-selected={axisUsed === "distance"} className={axisUsed === "distance" ? "on" : undefined} disabled={!hasDistance} onClick={() => setAxisKind("distance")} title={hasDistance ? "Line the laps up by how far round the track you are" : "Needs a speed channel"}>
            Distance
          </button>
          <button role="tab" aria-selected={axisUsed === "time"} className={axisUsed === "time" ? "on" : undefined} onClick={() => setAxisKind("time")}>
            Time in lap
          </button>
        </div>
        {table.data && (
          <span className="muted small">
            {laps.length} lap{laps.length === 1 ? "" : "s"} found from {table.data.found_by}.
          </span>
        )}
        <div className="spacer" />
        <button className="btn sm" onClick={() => setSettingsOpen((o) => !o)} aria-expanded={settingsOpen}>
          How laps are found
        </button>
      </div>

      {(settingsOpen || (table.error && !table.data)) && <LapSettings names={names} value={params} onApply={apply} error={table.data ? null : table.error} />}

      <div className="laps-body">
        <aside className="laps-side">
          {table.data && <LapTable laps={laps} sel={selected} refN={refN} bestN={table.data.best} onToggle={toggle} onRef={setRef} hasSpeed={hasDistance} />}
          <TrackCard
            show={!!table.data || track.data?.source === "gps"}
            track={track.data}
            error={track.error}
            names={names}
            colour={colour}
            onColour={setColourBy}
            mirror={mirror}
            onMirror={setMirror}
            src={src}
          />
        </aside>

        <div className="laps-main">
          {!table.data && !table.error && <p className="muted pad">Finding laps</p>}
          {table.error && !table.data && (
            <div className="laps-empty">
              <h2>No laps found in this log</h2>
              <p>{table.error}</p>
              <p className="muted">
                Dyno and bench runs have no start/finish line, so that is normal for them. Track logs usually carry a lap timer or beacon channel; choose it under
                "How laps are found".
              </p>
            </div>
          )}
          {table.data && (
            <>
              <div className="chips">
                {channels.map((c) => (
                  <button key={c} className="chip on" onClick={() => setPicked(channels.filter((x) => x !== c))} title="Remove from the overlay">
                    {c} <span aria-hidden>×</span>
                  </button>
                ))}
                {channels.length < 6 && (
                  <select
                    className="chip-add"
                    value=""
                    aria-label="Add a channel to the overlay"
                    onChange={(e) => e.target.value && setPicked([...channels, e.target.value])}
                  >
                    <option value="">Add channel</option>
                    {names.filter((n) => !channels.includes(n)).map((n) => (
                      <option key={n} value={n}>{n}</option>
                    ))}
                  </select>
                )}
              </div>
              {view.error && <p className="muted pad">{view.error}</p>}
              {view.data && <Overlay view={view.data} channels={channels} />}
            </>
          )}
        </div>
      </div>
    </section>
  );
}

function LapSettings(props: { names: string[]; value: LapParams; onApply: (p: LapParams) => void; error: string | null }) {
  const [d, setD] = useState<LapParams>(props.value);
  const m = METHODS.find((x) => x.id === d.method)!;
  const needsChannel = d.method === "reset" || d.method === "change" || d.method === "trigger";
  return (
    <form
      className="lap-settings"
      onSubmit={(e) => {
        e.preventDefault();
        props.onApply(d);
      }}
    >
      <label className="inline">
        Find laps by
        <select value={d.method} onChange={(e) => setD({ ...d, method: e.target.value as LapParams["method"] })}>
          {METHODS.map((x) => (
            <option key={x.id} value={x.id}>{x.label}</option>
          ))}
        </select>
      </label>
      {needsChannel && (
        <label className="inline">
          Channel
          <select value={d.channel ?? ""} onChange={(e) => setD({ ...d, channel: e.target.value })}>
            <option value="">Choose</option>
            {props.names.map((n) => (
              <option key={n} value={n}>{n}</option>
            ))}
          </select>
        </label>
      )}
      {d.method === "trigger" && (
        <label className="inline">
          Level
          <input type="number" step="any" value={d.threshold ?? 0.5} onChange={(e) => setD({ ...d, threshold: Number(e.target.value) })} />
        </label>
      )}
      {d.method === "distance" && (
        <label className="inline">
          Lap length (m)
          <input type="number" min="1" step="any" value={d.length_m ?? ""} onChange={(e) => setD({ ...d, length_m: Number(e.target.value) || undefined })} />
        </label>
      )}
      {d.method === "manual" && (
        <label className="inline grow">
          Times (s)
          <input type="text" placeholder="e.g. 12.4, 88.9, 165.2" value={d.times ?? ""} onChange={(e) => setD({ ...d, times: e.target.value })} />
        </label>
      )}
      <label className="inline">
        Shortest lap (s)
        <input type="number" min="0.5" step="any" value={d.min_lap_s ?? 5} onChange={(e) => setD({ ...d, min_lap_s: Number(e.target.value) || 5 })} />
      </label>
      <button className="btn primary sm" type="submit">Find laps</button>
      <p className="muted small lap-help">{props.error ?? m.help}</p>
    </form>
  );
}

function LapTable(props: {
  laps: LapRow[];
  sel: number[];
  refN: number | null;
  bestN: number | null;
  hasSpeed: boolean;
  onToggle: (n: number) => void;
  onRef: (n: number) => void;
}) {
  const { laps } = props;
  if (!laps.length) return <p className="muted pad">The start and finish were found, but no complete lap sits between them.</p>;
  const best = laps.find((l) => l.n === props.bestN);
  const valid = laps.filter((l) => l.valid);
  const avg = valid.length ? valid.reduce((a, l) => a + l.duration_s, 0) / valid.length : null;
  return (
    <div className="lap-table-wrap">
      <div className="lap-summary">
        <div>
          <span className="muted small">Best</span>
          <strong className="num">{best ? fmtLap(best.duration_s) : "–"}</strong>
        </div>
        <div>
          <span className="muted small">Average</span>
          <strong className="num">{avg != null ? fmtLap(avg) : "–"}</strong>
        </div>
        <div>
          <span className="muted small">Spread</span>
          <strong className="num">{valid.length > 1 ? `${(Math.max(...valid.map((l) => l.duration_s)) - Math.min(...valid.map((l) => l.duration_s))).toFixed(3)} s` : "–"}</strong>
        </div>
      </div>
      <table className="stats lap-table">
        <thead>
          <tr>
            <th scope="col"><span className="sr">Show</span></th>
            <th scope="col">Lap</th>
            <th scope="col" className="num">Time</th>
            <th scope="col" className="num">Δ best</th>
            {props.hasSpeed && <th scope="col" className="num">Top km/h</th>}
          </tr>
        </thead>
        <tbody>
          {laps.map((l) => {
            const on = props.sel.includes(l.n);
            const isRef = l.n === props.refN;
            return (
              <tr key={l.n} className={on ? undefined : "off"}>
                <td>
                  <input type="checkbox" checked={on} onChange={() => props.onToggle(l.n)} aria-label={`Show lap ${l.n}`} />
                </td>
                <th scope="row">
                  <button className="lap-name" onClick={() => props.onRef(l.n)} title="Compare the other laps against this one">
                    <span className="swatch" style={{ background: lapColour(l.n, isRef) }} aria-hidden />
                    {l.n}
                  </button>
                  {l.best && <small className="log-tag best">Best</small>}
                  {!l.valid && <small className="log-tag">In/out</small>}
                </th>
                <td className="num">{fmtLap(l.duration_s)}</td>
                <td className="num">{l.best ? "–" : fmtDelta(l.delta_best_s)}</td>
                {props.hasSpeed && <td className="num">{l.max_kmh != null ? l.max_kmh.toFixed(1) : "–"}</td>}
              </tr>
            );
          })}
        </tbody>
      </table>
      <p className="muted small lap-note">Click a lap number to make it the reference the others are compared against.</p>
    </div>
  );
}

function Overlay({ view, channels }: { view: LapView; channels: string[] }) {
  const isDist = view.axis === "distance";
  const xLabel = isDist ? "Distance into the lap (m)" : "Time into the lap (s)";
  const delta = useMemo(
    () => (isDist ? view.laps.filter((l) => l.delta_s).map((l) => ({ n: l.n, ys: l.delta_s! })) : []),
    [view, isDist],
  );
  return (
    <div className="lap-charts">
      {delta.length > 0 && (
        <LapChart title="Time ahead (−) or behind (+) the reference lap" unit="s" x={view.x} xLabel={xLabel} laps={delta} refN={view.reference} height={210} signed />
      )}
      {channels.map((c, i) => (
        <OverlayChannel key={c} view={view} channel={c} xLabel={xLabel} last={i === channels.length - 1} />
      ))}
    </div>
  );
}

function OverlayChannel(props: { view: LapView; channel: string; xLabel: string; last: boolean }) {
  const { view, channel } = props;
  const lines = useMemo(() => view.laps.map((l) => ({ n: l.n, ys: l.channels[channel] ?? [] })), [view, channel]);
  return <LapChart title={channel} unit={view.units[channel] ?? ""} x={view.x} xLabel={props.xLabel} laps={lines} refN={view.reference} height={240} last={props.last} />;
}

function LapChart(props: {
  title: string;
  unit: string;
  x: number[];
  xLabel: string;
  laps: { n: number; ys: (number | null)[] }[];
  refN: number;
  height: number;
  signed?: boolean;
  last?: boolean;
}) {
  const data = useMemo(() => [props.x, ...props.laps.map((l) => l.ys)] as unknown as uPlot.AlignedData, [props.x, props.laps]);
  return (
    <div className="lap-chart" style={{ height: props.height }}>
      <h3>
        {props.title}
        {props.unit && <small> {props.unit}</small>}
      </h3>
      <Chart
        data={data}
        build={(w, h) => ({
          width: w,
          height: h - 56, // the legend (up to two lines of live values) sits under the plot inside this box
          legend: { show: true, live: true },
          cursor: { sync: { key: "laps" }, drag: { x: false, y: false }, points: { show: false } },
          scales: { x: { time: false } },
          axes: [axis(props.last ? props.xLabel : "", { size: props.last ? 44 : 26 }), axis("", { size: 56 })],
          series: [
            { label: props.xLabel.startsWith("Dist") ? "Distance (m)" : "Time (s)", value: (_u, v) => (v == null ? "–" : v.toFixed(props.xLabel.startsWith("Dist") ? 0 : 1)) },
            ...props.laps.map((l) => ({
              label: `Lap ${l.n}`,
              stroke: lapColour(l.n, l.n === props.refN),
              width: l.n === props.refN ? 2.5 : 1.5,
              points: { show: false },
              value: (_u: uPlot, v: number | null) => (v == null ? "–" : props.signed ? fmtDelta(v) : formatValue(v)),
            })),
          ],
        })}
      />
    </div>
  );
}

function ramp(f: number): string {
  const x = Math.min(Math.max(f, 0), 1) * (RAMP.length - 1);
  const i = Math.min(Math.floor(x), RAMP.length - 2);
  const a = RAMP[i], b = RAMP[i + 1], k = x - i;
  const ch = (h: string, o: number) => parseInt(h.slice(1 + o * 2, 3 + o * 2), 16);
  const mix = (o: number) => Math.round(ch(a, o) + (ch(b, o) - ch(a, o)) * k);
  return `rgb(${mix(0)} ${mix(1)} ${mix(2)})`;
}

function TrackCard(props: {
  show: boolean;
  track: Track | null;
  error: string | null;
  names: string[];
  colour: string;
  onColour: (c: string) => void;
  mirror: boolean;
  onMirror: (m: boolean) => void;
  src: Source;
}) {
  if (!props.show) return null;
  const t = props.track;
  const unit = t?.color_unit ?? "";
  return (
    <div className="track-card">
      <div className="track-head">
        <h3>Track</h3>
        <label className="inline">
          Colour by
          <select value={props.colour} onChange={(e) => props.onColour(e.target.value)}>
            {props.names.map((n) => (
              <option key={n} value={n}>{n}</option>
            ))}
          </select>
        </label>
      </div>
      {t ? <TrackCanvas track={t} /> : <p className="muted small pad">{props.error ?? "Drawing the track"}</p>}
      {t && (
        <div className="ramp-row">
          <span className="muted small">low</span>
          <span className="ramp" style={{ background: `linear-gradient(90deg, ${RAMP.join(", ")})` }} aria-hidden />
          <span className="muted small">high{unit ? ` (${unit})` : ""}</span>
        </div>
      )}
      {t?.estimated && (
        <p className="muted small">
          This log has no GPS position, so the shape is estimated from {t.source === "course" ? "speed and GPS heading" : "speed and sideways g"}. It keeps the layout but drifts a little.
          <label className="inline check">
            <input type="checkbox" checked={props.mirror} onChange={(e) => props.onMirror(e.target.checked)} /> Mirror it
          </label>
        </p>
      )}
    </div>
  );
}

function TrackCanvas({ track }: { track: Track }) {
  const box = useRef<HTMLDivElement>(null);
  const cv = useRef<HTMLCanvasElement>(null);
  const [w, setW] = useState(0);
  useEffect(() => {
    const el = box.current;
    if (!el) return;
    const ro = new ResizeObserver(() => setW(Math.floor(el.clientWidth)));
    ro.observe(el);
    return () => ro.disconnect();
  }, []);
  useEffect(() => {
    const c = cv.current;
    if (!c || w < 50) return;
    const dpr = window.devicePixelRatio || 1;
    const h = Math.round(w * 0.78);
    c.width = w * dpr;
    c.height = h * dpr;
    c.style.height = `${h}px`;
    const ctx = c.getContext("2d")!;
    ctx.scale(dpr, dpr);
    const pts = track.x.map((x, i) => ({ x, y: track.y[i], v: track.color?.[i] ?? null, t: track.t[i] })).filter((p): p is { x: number; y: number; v: number | null; t: number } => p.x != null && p.y != null);
    if (pts.length < 2) return;
    const xs = pts.map((p) => p.x), ys = pts.map((p) => p.y);
    const [x0, x1, y0, y1] = [Math.min(...xs), Math.max(...xs), Math.min(...ys), Math.max(...ys)];
    const pad = 18;
    const k = Math.min((w - 2 * pad) / Math.max(x1 - x0, 1), (h - 2 * pad) / Math.max(y1 - y0, 1));
    const ox = (w - k * (x1 - x0)) / 2, oy = (h - k * (y1 - y0)) / 2;
    const px = (x: number) => ox + (x - x0) * k;
    const py = (y: number) => h - (oy + (y - y0) * k);
    const vs = pts.map((p) => p.v).filter((v): v is number => v != null);
    const lo = vs.length ? Math.min(...vs) : 0, hi = vs.length ? Math.max(...vs) : 1;
    ctx.lineWidth = 4;
    ctx.lineCap = "round";
    for (let i = 1; i < pts.length; i++) {
      const v = pts[i].v;
      ctx.strokeStyle = v != null && hi > lo ? ramp((v - lo) / (hi - lo)) : "#5d636e";
      ctx.beginPath();
      ctx.moveTo(px(pts[i - 1].x), py(pts[i - 1].y));
      ctx.lineTo(px(pts[i].x), py(pts[i].y));
      ctx.stroke();
    }
    // start/finish line, drawn square across the direction of travel
    const t0 = track.boundaries[0];
    if (t0 != null) {
      const i = Math.max(1, Math.min(pts.length - 1, pts.findIndex((p) => p.t >= t0)));
      const a = pts[i - 1], b = pts[i];
      const ang = Math.atan2(-(py(b.y) - py(a.y)), px(b.x) - px(a.x)) + Math.PI / 2;
      const cx = px(b.x), cy = py(b.y);
      ctx.strokeStyle = "#ffffff";
      ctx.lineWidth = 2.5;
      ctx.beginPath();
      ctx.moveTo(cx - Math.cos(ang) * 9, cy + Math.sin(ang) * 9);
      ctx.lineTo(cx + Math.cos(ang) * 9, cy - Math.sin(ang) * 9);
      ctx.stroke();
    }
  }, [track, w]);
  return (
    <div ref={box} className="track-canvas">
      <canvas ref={cv} role="img" aria-label="Plan view of the track, coloured by the chosen channel" />
    </div>
  );
}
