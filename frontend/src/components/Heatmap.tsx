import { useEffect, useMemo, useRef, useState } from "react";
import { api, type Heatmap as HeatmapData } from "../api";
import { useStore } from "../store";
import { formatValue } from "./Lane";

const RAMP = ["#2f6df0", "#38c8f0", "#3ddc84", "#ffb020", "#ff3b47"];
const DIVERGE = ["#2f6df0", "#7fa6e8", "#5b6270", "#e8998f", "#ff3b47"];
const ASH = "#8b919c";
const FONT = '12px "Geist Variable", system-ui, sans-serif';

const CELLS: Record<string, [number, number]> = { Coarse: [20, 14], Medium: [40, 28], Fine: [70, 50] };
const AGGS: [string, string][] = [["mean", "Average"], ["max", "Highest"], ["min", "Lowest"], ["std", "Spread"]];

function mix(stops: string[], f: number): string {
  const x = Math.min(Math.max(f, 0), 1) * (stops.length - 1);
  const i = Math.min(Math.floor(x), stops.length - 2);
  const k = x - i;
  const ch = (h: string, o: number) => parseInt(h.slice(1 + o * 2, 3 + o * 2), 16);
  const m = (o: number) => Math.round(ch(stops[i], o) + (ch(stops[i + 1], o) - ch(stops[i], o)) * k);
  return `rgb(${m(0)} ${m(1)} ${m(2)})`;
}

/** Nice round tick values inside [lo, hi]. */
function ticks(lo: number, hi: number, want: number): number[] {
  const raw = (hi - lo) / Math.max(want, 1);
  const pow = Math.pow(10, Math.floor(Math.log10(raw)));
  const step = [1, 2, 2.5, 5, 10].map((m) => m * pow).find((s) => s >= raw) ?? raw;
  const out: number[] = [];
  for (let v = Math.ceil(lo / step) * step; v <= hi + step * 1e-6; v += step) out.push(Math.round(v / step) * step);
  return out;
}

/** Where the engine spends its time, or what it is doing there: any channel on an x/y grid. */
export function HeatmapPanel({ t0, t1, rev }: { t0?: number; t1?: number; rev: number }) {
  const sources = useStore((s) => s.sources);
  const names = useMemo(() => [...new Set(sources.flatMap((s) => s.channels.map((c) => c.name)))], [sources]);
  const find = (re: RegExp) => names.find((n) => re.test(n));

  const [x, setX] = useState(() => find(/^rpm$/i) ?? names[0] ?? "");
  const [y, setY] = useState(() => find(/^tps1?$/i) ?? find(/^map1?$/i) ?? names[1] ?? names[0] ?? "");
  const [value, setValue] = useState(() => find(/^lam1$/i) ?? "");
  const [agg, setAgg] = useState("mean");
  const [cells, setCells] = useState("Medium");
  const [minCount, setMinCount] = useState(5);
  const [centre, setCentre] = useState("");
  const [clip, setClip] = useState(true);
  const [spread, setSpread] = useState("");

  const [data, setData] = useState<HeatmapData | null>(null);
  const [error, setError] = useState<string | null>(null);
  const ids = sources.map((s) => s.id).join(",");
  const [nx, ny] = CELLS[cells];
  useEffect(() => {
    if (!x || !y) return;
    let live = true;
    api.heatmap(ids.split(","), { x, y, value: value || undefined, agg, nx, ny, minCount, t0, t1 }).then(
      (d) => {
        if (!live) return;
        setData(d);
        setError(null);
      },
      (e: Error) => {
        if (!live) return;
        setData(null);
        setError(e.message);
      },
    );
    return () => {
      live = false;
    };
  }, [ids, x, y, value, agg, nx, ny, minCount, t0, t1, rev]);

  const centreNum = centre.trim() === "" ? null : Number(centre);
  const useCentre = !!value && centreNum != null && Number.isFinite(centreNum);
  const unitOf = (name: string) => sources.flatMap((s) => s.channels).find((c) => c.name === name)?.unit ?? "";
  const what = value ? `${AGGS.find((a) => a[0] === agg)?.[1].toLowerCase()} ${value}` : "samples";

  const [hover, setHover] = useState<[number, number] | null>(null);
  const wrap = useRef<HTMLDivElement>(null);
  const cv = useRef<HTMLCanvasElement>(null);
  const [size, setSize] = useState<[number, number]>([0, 0]);
  useEffect(() => {
    const el = wrap.current;
    if (!el) return;
    const ro = new ResizeObserver(() => setSize([Math.floor(el.clientWidth), Math.floor(el.clientHeight)]));
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  const L = 64, B = 40, T = 8, R = 12;
  const range = useMemo(() => {
    if (!data || data.vmin == null || data.vmax == null) return null;
    // a few extreme cells (fuel cut reads lambda 3+) would flatten everything else, so by default the scale ignores the top and bottom 5%
    const all = (value ? data.values : data.counts.map((r, j) => r.map((n, i) => (data.values[j][i] == null ? null : n)))).flat().filter((v): v is number => v != null).sort((a, b) => a - b);
    const q = (f: number) => all[Math.min(all.length - 1, Math.max(0, Math.round(f * (all.length - 1))))];
    const lo0 = clip && all.length > 20 ? q(0.05) : data.vmin;
    const hi0 = clip && all.length > 20 ? q(0.95) : data.vmax;
    if (useCentre) {
      const devs = all.map((v) => Math.abs(v - centreNum!)).sort((a, b) => a - b);
      const dev = clip && devs.length > 20 ? devs[Math.round(0.95 * (devs.length - 1))] : Math.max(Math.abs(data.vmin - centreNum!), Math.abs(data.vmax - centreNum!));
      const manual = Number(spread);
      const d = manual > 0 ? manual : dev || 1;
      return { lo: centreNum! - d, hi: centreNum! + d };
    }
    return { lo: lo0, hi: hi0 === lo0 ? lo0 + 1 : hi0 };
  }, [data, useCentre, centreNum, clip, value, spread]);

  const colourFor = (v: number): string => {
    if (!range) return "#2a2f38";
    if (!value) return mix(RAMP, Math.sqrt(Math.max(0, (v - range.lo) / (range.hi - range.lo)))); // counts: sqrt lets sparse areas show
    return mix(useCentre ? DIVERGE : RAMP, (v - range.lo) / (range.hi - range.lo));
  };

  useEffect(() => {
    const c = cv.current;
    if (!c || !data || size[0] < 120 || size[1] < 120 || !data.xedges.length) return;
    const dpr = window.devicePixelRatio || 1;
    const [w, h] = size;
    c.width = w * dpr;
    c.height = h * dpr;
    c.style.width = `${w}px`;
    c.style.height = `${h}px`;
    const ctx = c.getContext("2d")!;
    ctx.scale(dpr, dpr);
    const pw = w - L - R, ph = h - B - T;
    const cw = pw / (data.xedges.length - 1), ch = ph / (data.yedges.length - 1);
    const vals = value ? data.values : data.counts.map((row, j) => row.map((n, i) => (data.values[j][i] == null ? null : n)));
    ctx.font = FONT;
    for (let j = 0; j < vals.length; j++)
      for (let i = 0; i < vals[j].length; i++) {
        const v = vals[j][i];
        const px = L + i * cw, py = T + ph - (j + 1) * ch;
        ctx.fillStyle = v == null ? "#101216" : colourFor(v);
        ctx.fillRect(px, py, Math.ceil(cw), Math.ceil(ch));
        if (v != null && cw >= 40 && ch >= 17) {
          ctx.fillStyle = "rgba(10,11,13,0.82)";
          ctx.textAlign = "center";
          ctx.textBaseline = "middle";
          ctx.fillText(value ? formatValue(v) : String(Math.round(v)), px + cw / 2, py + ch / 2);
        }
      }
    // axes
    const x0 = data.xedges[0], x1 = data.xedges[data.xedges.length - 1];
    const y0 = data.yedges[0], y1 = data.yedges[data.yedges.length - 1];
    ctx.fillStyle = ASH;
    ctx.strokeStyle = "#343944";
    ctx.textBaseline = "top";
    ctx.textAlign = "center";
    for (const v of ticks(x0, x1, Math.max(3, Math.floor(pw / 90)))) {
      const px = L + ((v - x0) / (x1 - x0)) * pw;
      ctx.beginPath();
      ctx.moveTo(px, T + ph);
      ctx.lineTo(px, T + ph + 4);
      ctx.stroke();
      ctx.fillText(formatValue(v), px, T + ph + 7);
    }
    ctx.textAlign = "right";
    ctx.textBaseline = "middle";
    for (const v of ticks(y0, y1, Math.max(3, Math.floor(ph / 44)))) {
      const py = T + ph - ((v - y0) / (y1 - y0)) * ph;
      ctx.beginPath();
      ctx.moveTo(L - 4, py);
      ctx.lineTo(L, py);
      ctx.stroke();
      ctx.fillText(formatValue(v), L - 8, py);
    }
    if (hover) {
      ctx.strokeStyle = "#ffffff";
      ctx.lineWidth = 2;
      ctx.strokeRect(L + hover[0] * cw + 1, T + ph - (hover[1] + 1) * ch + 1, cw - 2, ch - 2);
    }
  }, [data, size, hover, range, value, useCentre]);

  const onMove = (e: React.MouseEvent<HTMLCanvasElement>) => {
    if (!data || !data.xedges.length) return;
    const r = e.currentTarget.getBoundingClientRect();
    const pw = size[0] - L - R, ph = size[1] - B - T;
    const px = e.clientX - r.left - L, py = e.clientY - r.top - T;
    if (px < 0 || py < 0 || px >= pw || py >= ph) return setHover(null);
    const nxx = data.xedges.length - 1, nyy = data.yedges.length - 1;
    setHover([Math.floor((px / pw) * nxx), nyy - 1 - Math.floor((py / ph) * nyy)]);
  };

  let readout = "Move over the map to read a cell.";
  if (data && hover && data.xedges.length) {
    const [i, j] = hover;
    const n = data.counts[j]?.[i] ?? 0;
    const v = data.values[j]?.[i];
    const fmtR = (a: number, b: number) => `${formatValue(a)} to ${formatValue(b)}`;
    readout = `${x} ${fmtR(data.xedges[i], data.xedges[i + 1])} · ${y} ${fmtR(data.yedges[j], data.yedges[j + 1])} · ${
      v == null ? (n ? `only ${n} sample${n === 1 ? "" : "s"}, hidden` : "no samples") : value ? `${what} ${formatValue(v)}${unitOf(value) ? ` ${unitOf(value)}` : ""}` : ""
    } · ${n.toLocaleString()} samples${data.dt_s ? ` (about ${(n * data.dt_s).toFixed(1)} s)` : ""}`;
  }

  const Pick = (p: { label: string; v: string; set: (s: string) => void; blank?: string }) => (
    <label className="inline">
      {p.label}
      <select value={p.v} onChange={(e) => p.set(e.target.value)}>
        {p.blank !== undefined && <option value="">{p.blank}</option>}
        {names.map((n) => (
          <option key={n} value={n}>{n}</option>
        ))}
      </select>
    </label>
  );

  return (
    <div className="heat">
      <div className="heat-bar">
        <Pick label="Across" v={x} set={setX} />
        <Pick label="Up" v={y} set={setY} />
        <Pick label="Show" v={value} set={(v) => { setValue(v); if (!v) setCentre(""); }} blank="Number of samples" />
        {value && (
          <label className="inline">
            As
            <select value={agg} onChange={(e) => setAgg(e.target.value)}>
              {AGGS.map(([k, l]) => (
                <option key={k} value={k}>{l}</option>
              ))}
            </select>
          </label>
        )}
        <details className="opts">
          <summary>Options</summary>
          <div className="opts-body">
        {value && (
          <label className="inline" title="Colour cells by how far they are from this value, for example a target lambda">
            Target
            <input type="number" step="any" value={centre} onChange={(e) => setCentre(e.target.value)} placeholder="optional" />
          </label>
        )}
        <label className="inline">
          Cells
          <select value={cells} onChange={(e) => setCells(e.target.value)}>
            {Object.keys(CELLS).map((k) => (
              <option key={k} value={k}>{k}</option>
            ))}
          </select>
        </label>
        {useCentre && (
          <label className="inline" title="How far from the target the colours go all the way to blue or red">
            ± range
            <input type="number" min="0" step="any" value={spread} onChange={(e) => setSpread(e.target.value)} placeholder="auto" />
          </label>
        )}
        <label className="inline check" title="Ignore the most extreme 5% of cells when choosing colours, so a few outliers do not wash out the rest">
          <input type="checkbox" checked={clip} onChange={(e) => setClip(e.target.checked)} /> Ignore extremes
        </label>
        <label className="inline" title="Leave out cells with fewer samples than this, so one stray sample does not colour a cell">
          Hide under
          <input type="number" min="1" value={minCount} onChange={(e) => setMinCount(Math.max(1, Number(e.target.value) || 1))} />
          samples
        </label>
          </div>
        </details>
      </div>
      <p className="heat-read" aria-live="polite">{readout}</p>
      <div ref={wrap} className="heat-canvas">
        {error && <p className="muted pad">{error}</p>}
        <canvas ref={cv} onMouseMove={onMove} onMouseLeave={() => setHover(null)} role="img" aria-label={`Map of ${what} by ${x} and ${y}`} />
      </div>
      {data && range && (
        <div className="heat-scale">
          <span className="muted small">{value ? formatValue(range.lo) : "few"}</span>
          <span className="ramp" style={{ background: `linear-gradient(90deg, ${(useCentre ? DIVERGE : RAMP).join(", ")})` }} aria-hidden />
          <span className="muted small">
            {value ? formatValue(range.hi) : "many"} {value ? unitOf(value) : ""}
          </span>
          <span className="muted small heat-note">
            {data.total.toLocaleString()} samples from {data.logs.length} log{data.logs.length === 1 ? "" : "s"}.
            {useCentre ? ` Grey is ${centreNum}.` : ""}
          </span>
          {data.skipped.length > 0 && (
            <span className="muted small">
              Left out: {data.skipped.map((k) => `${k.label} (${k.reason})`).join(", ")}.
            </span>
          )}
        </div>
      )}
    </div>
  );
}
