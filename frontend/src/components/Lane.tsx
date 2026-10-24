import { useEffect, useMemo, useRef, useState } from "react";
import uPlot from "uplot";
import { api } from "../api";
import { extentOf, useStore, type Lane as LaneModel } from "../store";
import { spansDays, stamp } from "../time";

export const TRACE = ["#ffb020", "#38c8f0", "#3ddc84", "#b79bff", "#ff8fb1", "#e8e8e8", "#7fa6ff", "#d6e34a"];

const ASH = "#8b919c";
const RULE = "#1d2127";
const FONT = '12px "Geist Variable", system-ui, sans-serif';
const SYNC = { key: "let", setSeries: false, scales: ["x", null] as [string, null] };

/** Channels in a lane, once each: the same channel from several logs is one trace group. */
export function channelGroups(series: { channel: string }[]): string[] {
  return [...new Set(series.map((s) => s.channel))];
}

export function stateLabel(states: Record<string, string> | undefined, v: number | null | undefined) {
  return states && v != null ? states[String(Math.round(v))] : undefined;
}

export function formatValue(v: number | null | undefined): string {
  if (v == null || Number.isNaN(v)) return "–";
  const a = Math.abs(v);
  const d = a >= 1000 ? 0 : a >= 100 ? 1 : a >= 10 ? 2 : 3;
  return v.toLocaleString("en-GB", { minimumFractionDigits: d, maximumFractionDigits: d });
}

type Props = {
  lane: LaneModel;
  colorOffset: number;
  isLast: boolean;
};

export function Lane({ lane, colorOffset, isLast }: Props) {
  const boxRef = useRef<HTMLDivElement>(null);
  const plotRef = useRef<uPlot | null>(null);
  const eventsRef = useRef<{ rule: string; t_start: number; t_end: number }[]>([]);
  const applyingRef = useRef(false); // true while we reload data, so the zoom store is left alone
  const [width, setWidth] = useState(0);
  const [readout, setReadout] = useState<{ t: number | null; v: (number | null)[] }>({ t: null, v: [] });

  const sources = useStore((s) => s.sources);
  const view = useStore((s) => s.view);
  const rev = useStore((s) => s.rev);
  const removeLane = useStore((s) => s.removeLane);

  const seriesKey = lane.series.map((s) => `${s.sourceId}|${s.channel}`).join(",");
  const extent = useMemo(() => extentOf(sources), [sources]);

  const meta = lane.series.map((s) => {
    const src = sources.find((x) => x.id === s.sourceId);
    const ch = src?.channels.find((c) => c.name === s.channel);
    return { name: s.channel, unit: ch?.unit ?? "", source: src?.label ?? "", states: ch?.states };
  });
  const groups = channelGroups(lane.series);
  const gmeta = groups.map((ch) => meta.find((m) => m.name === ch)!);
  const title = gmeta.map((m) => (m.unit ? `${m.name} (${m.unit})` : m.name)).join(", ");

  // Track the container width.
  useEffect(() => {
    const el = boxRef.current;
    if (!el) return;
    const ro = new ResizeObserver(() => setWidth(Math.floor(el.clientWidth)));
    ro.observe(el);
    setWidth(Math.floor(el.clientWidth));
    return () => ro.disconnect();
  }, []);

  // Create the plot when the set of series (or the axis visibility) changes.
  useEffect(() => {
    const el = boxRef.current;
    if (!el || width < 50) return;
    const height = el.clientHeight || 160;
    const n = groups.length;
    const state = useStore.getState();
    const [e0, e1] = extentOf(state.sources);
    const initial = state.view ?? [e0, e1];

    let pending: number | null = null;
    const opts: uPlot.Options = {
      width,
      height,
      padding: [10, 10, 0, 0],
      legend: { show: false },
      cursor: {
        sync: SYNC,
        drag: { x: true, y: false, uni: 30 },
        points: { show: false },
        bind: {
          dblclick: (u) => () => {
            const [a, b] = extentOf(useStore.getState().sources);
            useStore.getState().setView(null);
            u.setScale("x", { min: a, max: b });
            return null;
          },
        },
      },
      scales: {
        x: { time: false },
        y: {
          range: (_u, min, max) => {
            if (!isFinite(min) || !isFinite(max)) return [0, 1];
            if (min === max) return [min - 1, max + 1];
            const p = (max - min) * 0.08;
            return [min - p, max + p];
          },
        },
      },
      axes: [
        {
          show: isLast,
          size: 30,
          stroke: ASH,
          font: FONT,
          grid: { stroke: RULE, width: 1 },
          ticks: { stroke: RULE, width: 1, size: 4 },
          values: (_u, vals) => vals.map((v) => `${+v.toFixed(2)} s`),
        },
        {
          size: 58,
          stroke: ASH,
          font: FONT,
          gap: 4,
          grid: { stroke: RULE, width: 1 },
          ticks: { show: false },
          values: (_u, vals) => vals.map((v) => formatValue(v)),
        },
      ],
      series: [
        {},
        ...lane.series.map((s) => ({
          label: s.channel,
          stroke: TRACE[(colorOffset + groups.indexOf(s.channel)) % TRACE.length],
          width: 1.5,
          spanGaps: true,
          points: { show: false },
        })),
      ],
      hooks: {
        drawClear: [
          (u) => {
            const { ctx } = u;
            const { left, top, width, height } = u.bbox;
            ctx.save();
            ctx.fillStyle = "rgba(242, 242, 242, 0.09)";
            for (const e of eventsRef.current) {
              const a = Math.max(u.valToPos(e.t_start, "x", true), left);
              const b = Math.min(u.valToPos(Math.max(e.t_end, e.t_start), "x", true), left + width);
              if (b < left || a > left + width) continue;
              ctx.fillRect(a, top, Math.max(b - a, 2 * devicePixelRatio), height);
            }
            ctx.restore();
          },
        ],
        draw: [
          (u) => {
            const logs = useStore.getState().sources.filter((s) => lane.series.some((x) => x.sourceId === s.id));
            if (logs.length < 2) return;
            const withDate = spansDays(logs);
            const { ctx } = u;
            const { left, top, width, height } = u.bbox;
            ctx.save();
            ctx.strokeStyle = ASH;
            ctx.fillStyle = ASH;
            ctx.lineWidth = 1;
            ctx.setLineDash([4, 4]);
            ctx.font = FONT.replace("12px", `${12 * devicePixelRatio}px`);
            ctx.textAlign = "left"; // uPlot leaves the last axis alignment set on the context
            ctx.textBaseline = "alphabetic";
            for (const s of logs) {
              const x = u.valToPos(s.offset_s, "x", true);
              if (x < left || x > left + width) continue;
              ctx.beginPath();
              ctx.moveTo(x, top);
              ctx.lineTo(x, top + height);
              ctx.stroke();
              const text = s.started_at ? stamp(s.started_at, withDate) : s.label;
              const pad = 4 * devicePixelRatio;
              const fits = x + pad + ctx.measureText(text).width <= left + width; // else write it left of the line
              ctx.textAlign = fits ? "left" : "right";
              ctx.fillText(text, fits ? x + pad : x - pad, top + 12 * devicePixelRatio);
            }
            ctx.restore();
          },
          (u) => {
            if (!eventsRef.current.length) return;
            const { ctx } = u;
            const { left, top, width } = u.bbox;
            ctx.save();
            ctx.fillStyle = "#f2f2f2";
            ctx.font = FONT.replace("12px", `${11 * devicePixelRatio}px`);
            ctx.textAlign = "left";
            ctx.textBaseline = "alphabetic";
            for (const e of eventsRef.current) {
              const a = u.valToPos(e.t_start, "x", true);
              if (a < left || a > left + width - 20 * devicePixelRatio) continue;
              ctx.fillRect(a, top, 2 * devicePixelRatio, 10 * devicePixelRatio); // marker, not colour alone
              ctx.fillText(e.rule, a + 5 * devicePixelRatio, top + 22 * devicePixelRatio);
            }
            ctx.restore();
          },
        ],
        setScale: [
          (u, key) => {
            if (key !== "x" || applyingRef.current) return;
            const { min, max } = u.scales.x;
            if (min == null || max == null) return;
            const cur = useStore.getState().view;
            if (cur && Math.abs(cur[0] - min) < 1e-9 && Math.abs(cur[1] - max) < 1e-9) return;
            useStore.getState().setView([min, max]);
          },
        ],
        setCursor: [
          (u) => {
            if (pending != null) return;
            pending = requestAnimationFrame(() => {
              pending = null;
              const idx = u.cursor.idx;
              if (idx == null) {
                setReadout({ t: null, v: new Array(n).fill(null) });
                return;
              }
              const idxs = u.cursor.idxs;
              const tc = (u.data[0][idx] as number) ?? null;
              // a log only counts at the cursor if it has a sample close to it (logs sit side by side)
              const span = (u.scales.x.max ?? 0) - (u.scales.x.min ?? 0);
              const tol = (span / Math.max(u.bbox.width / devicePixelRatio, 1)) * 3;
              const vals = groups.map((ch) => {
                let found: number | null = null;
                lane.series.forEach((s, i) => {
                  if (found != null || s.channel !== ch || tc == null) return;
                  const k = idxs?.[i + 1] ?? idx;
                  if (k == null) return;
                  const v = u.data[i + 1][k] as number | null | undefined;
                  if (v != null && Math.abs((u.data[0][k] as number) - tc) <= tol) found = v;
                });
                return found;
              });
              setReadout({ t: tc, v: vals });
            });
          },
        ],
      },
    };

    const empty: uPlot.AlignedData = [
      [initial[0], initial[1]],
      ...lane.series.map(() => [null, null] as (number | null)[]),
    ];
    const u = new uPlot(opts, empty, el);
    u.setScale("x", { min: initial[0], max: initial[1] });
    plotRef.current = u;
    return () => {
      if (pending != null) cancelAnimationFrame(pending);
      u.destroy();
      plotRef.current = null;
    };
  }, [seriesKey, isLast, width > 50]);

  // Event spans from the rules of every log in this lane, drawn as shaded bands.
  const rulesKey = sources
    .filter((s) => lane.series.some((x) => x.sourceId === s.id))
    .map((s) => `${s.id}:${s.offset_s}:${(s.rules ?? []).map((r) => r.name + r.expr + r.min_duration_s).join("|")}`)
    .join(";");
  useEffect(() => {
    let live = true;
    const ids = [...new Set(lane.series.map((s) => s.sourceId))].filter(
      (id) => (sources.find((s) => s.id === id)?.rules ?? []).length > 0,
    );
    Promise.all(ids.map((id) => api.events(id))).then(
      (all) => {
        if (!live) return;
        eventsRef.current = all.flat();
        plotRef.current?.redraw(false);
      },
      (e: Error) => live && useStore.setState({ message: { kind: "error", text: `Could not load events. ${e.message}` } }),
    );
    return () => {
      live = false;
    };
  }, [rulesKey, rev, seriesKey]);

  // Follow the zoom window when it is changed from outside the plot (a log in the rail, an event).
  useEffect(() => {
    const u = plotRef.current;
    if (!u || !view) return;
    const { min, max } = u.scales.x;
    if (min == null || max == null || Math.abs(min - view[0]) > 1e-6 || Math.abs(max - view[1]) > 1e-6) {
      u.setScale("x", { min: view[0], max: view[1] });
    }
  }, [view]);

  // Keep the plot size in step with its container.
  useEffect(() => {
    const u = plotRef.current;
    const el = boxRef.current;
    if (u && el && width >= 50) u.setSize({ width, height: el.clientHeight || 160 });
  }, [width, isLast]);

  // When nothing is zoomed and the extent changes (new import, offset edit), refit.
  useEffect(() => {
    const u = plotRef.current;
    if (u && !view) u.setScale("x", { min: extent[0], max: extent[1] });
  }, [extent, view, seriesKey]);

  // Fetch downsampled data for the visible window.
  const windowKey = (view ?? extent).map((x) => x.toFixed(4)).join(":");
  useEffect(() => {
    if (width < 50) return;
    let cancelled = false;
    const [t0, t1] = view ?? extent;
    const px = Math.max(200, Math.round(width / 50) * 50);
    const timer = setTimeout(async () => {
      try {
        const bySource = new Map<string, string[]>();
        lane.series.forEach((s) => bySource.set(s.sourceId, [...(bySource.get(s.sourceId) ?? []), s.channel]));
        const got = new Map<string, { t: number[]; v: number[] }>();
        await Promise.all(
          [...bySource].map(async ([id, chans]) => {
            const r = await api.signals(id, chans, t0, t1, px);
            chans.forEach((c) => got.set(`${id}|${c}`, r.channels[c]));
          }),
        );
        if (cancelled || !plotRef.current) return;
        const tables = lane.series.map((s) => {
          const g = got.get(`${s.sourceId}|${s.channel}`);
          return [g?.t ?? [], g?.v ?? []] as [number[], number[]];
        });
        const data = uPlot.join(tables);
        const u = plotRef.current;
        // A plain setData(data, false) keeps the zoom but leaves uPlot's visible-index range
        // stuck on the empty placeholder data (only 2 points drawn, y never autoranged). Load
        // the data normally, then restore the x window; y then autoranges to what is in view.
        const { min: x0, max: x1 } = u.scales.x;
        applyingRef.current = true;
        try {
          u.setData(data, true);
          if (x0 != null && x1 != null) u.setScale("x", { min: x0, max: x1 });
        } finally {
          applyingRef.current = false;
        }
      } catch (err) {
        // keep the last good data; log so plotting failures are not silent
        console.error("Lane data update failed", err);
      }
    }, 80);
    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
  }, [seriesKey, windowKey, rev, width > 50, sources.length, isLast]); // isLast: the plot is rebuilt empty when it changes

  const solo = groups.length === 1;

  return (
    <section className={`lane${solo ? " solo" : ""}`} aria-label={`Plot: ${title}`}>
      <header className="lane-head">
        <div className="lane-series">
          {groups.map((ch, i) => {
            const logs = lane.series.filter((s) => s.channel === ch).length;
            const m = gmeta[i];
            return (
              <div className="lane-chip" key={ch}>
                <span className="dot" style={{ background: TRACE[(colorOffset + i) % TRACE.length] }} aria-hidden />
                <span className="chip-name">{ch}</span>
                <span className="chip-unit">
                  {m.states ? "" : m.unit}
                  {logs > 1 ? `${m.unit && !m.states ? ", " : ""}${logs} logs` : ""}
                </span>
                <span className="chip-val">{stateLabel(m.states, readout.v[i]) ?? formatValue(readout.v[i])}</span>
              </div>
            );
          })}
        </div>
        <span className="lane-time">{readout.t == null ? "" : `${readout.t.toFixed(2)} s`}</span>
        <button className="icon-btn" onClick={() => removeLane(lane.id)} aria-label={`Remove plot ${title}`} title="Remove plot">
          <svg width="16" height="16" viewBox="0 0 16 16" aria-hidden>
            <path d="M3.5 3.5l9 9M12.5 3.5l-9 9" />
          </svg>
        </button>
      </header>
      <div className="lane-plot">
        <div ref={boxRef} className="lane-canvas" />
      </div>
    </section>
  );
}
