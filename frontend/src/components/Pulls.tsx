import { useMemo, useState } from "react";
import uPlot from "uplot";
import { api, type PullRow, type Pulls as PullsData } from "../api";
import { useStore, type Source } from "../store";
import { spansDays, stamp } from "../time";
import { Chart, axis, useFetched } from "./Analysis";
import { formatValue } from "./Lane";

const COLOURS = ["#38c8f0", "#ffb020", "#3ddc84", "#b79bff", "#ff8fb1", "#e8e8e8", "#7fa6ff", "#d6e34a"];
const REF = "#ff3b47";
const WANTED = [/^lam1$/i, /^ignFinalPri1$/i, /^map1$/i, /^ect1$/i, /^tps1?$/i];

type Row = PullRow & { id: string; log: string };
type Line = { id: string; label: string; ys: (number | null)[] };

/** Engine pulls compared against RPM: the way to see whether a change to the engine or the tune helped. */
export function Pulls() {
  const sources = useStore((s) => s.sources);
  const rev = useStore((s) => s.rev);
  const [slope, setSlope] = useState(150);
  const [span, setSpan] = useState(3000);
  const [bin, setBin] = useState(100);
  const [mass, setMass] = useState("");
  const [picked, setPicked] = useState<string[]>([]);
  const [sel, setSel] = useState<string[] | null>(null);
  const [ref, setRef] = useState<string | null>(null);

  const withDate = spansDays(sources);
  const tag = (s: Source | undefined) => (s ? (s.started_at ? stamp(s.started_at, withDate).replace(/:\d\d$/, "") : s.label) : "");
  const names = useMemo(() => [...new Set(sources.flatMap((s) => s.channels.map((c) => c.name)))], [sources]);
  const defaults = useMemo(() => WANTED.map((re) => names.find((n) => re.test(n))).filter(Boolean) as string[], [names]);
  const channels = picked.length ? picked : defaults;
  const massKg = Number(mass) > 0 ? Number(mass) : undefined;
  const ids = sources.map((s) => s.id);

  const { data, error } = useFetched(
    () => api.pulls(ids, channels, sel ?? [], { slope, span, bin, massKg }),
    [ids.join(","), channels.join(","), (sel ?? []).join(","), slope, span, bin, massKg, rev],
  );

  const rows: Row[] = useMemo(
    () =>
      data ? ids.flatMap((id) => (data.logs[id]?.pulls ?? []).map((p) => ({ ...p, id: `${id}:${p.n}`, log: id }))) : [],
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [data, ids.join(",")],
  );
  const selected = sel ?? rows.filter((r) => r.loaded !== false).map((r) => r.id);
  const peaks = useMemo(() => new Map((data?.compare?.peaks ?? []).map((p) => [`${p.log}:${p.n}`, p])), [data]);
  const best = useMemo(() => {
    let b: string | null = null;
    let top = -Infinity;
    for (const id of selected) {
      const v = peaks.get(id)?.peak_power;
      if (v != null && v > top) {
        top = v;
        b = id;
      }
    }
    return b;
  }, [selected.join(","), peaks]);
  const refId = ref && selected.includes(ref) ? ref : best;
  const colourOf = useMemo(() => {
    const order = rows.filter((r) => selected.includes(r.id)).map((r) => r.id);
    return (id: string) => (id === refId ? REF : COLOURS[Math.max(order.indexOf(id), 0) % COLOURS.length]);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [rows, selected.join(","), refId]);
  const toggle = (id: string) => setSel((cur) => ((cur ?? selected).includes(id) ? (cur ?? selected).filter((x) => x !== id) : [...(cur ?? selected), id]));
  const label = (log: string, n: number) => (sources.length > 1 ? `${tag(sources.find((s) => s.id === log))} #${n}` : `Pull ${n}`);

  const unit = data?.compare?.power_unit === "kW" ? "kW" : "relative";
  const tUnit = data?.compare?.power_unit === "kW" ? "N·m" : "relative";

  const lines = useMemo(() => {
    const c = data?.compare;
    if (!c) return null;
    const get = (key: string): Line[] =>
      c.curves.filter((x) => x.channels[key]).map((x) => ({ id: `${x.log}:${x.n}`, label: label(x.log, x.n), ys: x.channels[key] }));
    const power = get("power");
    const refCurve = power.find((l) => l.id === refId);
    // a percentage of almost nothing is noise, so leave out the part of the sweep where the reference makes under 15% of its peak
    const refTop = refCurve ? Math.max(...refCurve.ys.map((v) => (v == null ? 0 : v))) : 0;
    const delta: Line[] = refCurve
      ? power.map((l) => ({
          id: l.id,
          label: l.label,
          ys: l.ys.map((v, i) => {
            const r = refCurve.ys[i];
            return v == null || r == null || r < 0.15 * refTop ? null : (v / r - 1) * 100;
          }),
        }))
      : [];
    return { power, torque: get("torque"), delta, byChannel: channels.map((ch) => ({ ch, lines: get(ch) })) };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [data, refId, channels.join(","), sources.length]);

  const refPeak = refId ? peaks.get(refId)?.peak_power : undefined;
  const nothing = data && rows.length === 0;

  return (
    <section className="analysis laps pulls" aria-label="Pulls">
      <div className="analysis-bar">
        <label className="inline" title="How steadily RPM must climb to count as a pull">
          Sensitivity
          <select value={slope} onChange={(e) => { setSlope(Number(e.target.value)); setSel(null); }}>
            <option value={400}>Only quick pulls</option>
            <option value={150}>Normal</option>
            <option value={60}>Include slow sweeps</option>
          </select>
        </label>
        <label className="inline">
          Smallest pull
          <select value={span} onChange={(e) => { setSpan(Number(e.target.value)); setSel(null); }}>
            {[2000, 3000, 4000, 5000].map((v) => (
              <option key={v} value={v}>{v.toLocaleString()} rpm</option>
            ))}
          </select>
        </label>
        <label className="inline" title="Width of each RPM step the curves are averaged over">
          Step
          <select value={bin} onChange={(e) => setBin(Number(e.target.value))}>
            {[50, 100, 200, 250, 500].map((v) => (
              <option key={v} value={v}>{v} rpm</option>
            ))}
          </select>
        </label>
        <label className="inline" title="Leave empty for a relative curve. With a mass the curves are in kW and N·m.">
          Effective mass (kg)
          <input type="number" min="1" step="any" value={mass} onChange={(e) => setMass(e.target.value)} placeholder="optional" />
        </label>
        {data && !nothing && (
          <span className="muted small">
            {rows.length} pull{rows.length === 1 ? "" : "s"} found.
          </span>
        )}
      </div>

      <div className="laps-body">
        <aside className="laps-side">
          {data && rows.length > 0 && (
            <div className="lap-table-wrap">
              <table className="stats lap-table">
                <thead>
                  <tr>
                    <th scope="col"><span className="sr">Show</span></th>
                    <th scope="col">Pull</th>
                    <th scope="col" className="num">RPM</th>
                    <th scope="col" className="num">Peak {unit === "kW" ? "kW" : "power"}</th>
                    <th scope="col" className="num">vs ref</th>
                  </tr>
                </thead>
                <tbody>
                  {sources.map((s) => {
                    const mine = rows.filter((r) => r.log === s.id);
                    if (!mine.length) return null;
                    return (
                      <PullGroup key={s.id} title={sources.length > 1 ? tag(s) : ""} sub={s.label} rows={mine} selected={selected} refId={refId} refPeak={refPeak} peaks={peaks} colourOf={colourOf} onToggle={toggle} onRef={setRef} unit={unit} />
                    );
                  })}
                </tbody>
              </table>
              <p className="muted small lap-note">Click a pull number to compare the others against it. "Rev only" pulls did not move the roller, so they have no power and start unticked.</p>
            </div>
          )}
          {data && Object.values(data.logs).some((l) => l.pulls.length === 0) && rows.length > 0 && (
            <p className="muted small lap-note">No pulls in: {sources.filter((s) => !(data.logs[s.id]?.pulls.length)).map((s) => tag(s)).join(", ")}.</p>
          )}
        </aside>

        <div className="laps-main">
          {!data && !error && <p className="muted pad">Looking for pulls</p>}
          {error && <p className="muted pad">{error}</p>}
          {nothing && (
            <div className="laps-empty">
              <h2>No pulls found</h2>
              <p>A pull is a stretch where RPM climbs steadily, like a dyno sweep through the gears.</p>
              <p className="muted">Try "Include slow sweeps" or a smaller pull size. Logs need an rpm channel.</p>
            </div>
          )}
          {data && rows.length > 0 && (
            <>
              <div className="chips">
                {channels.map((c) => (
                  <button key={c} className="chip on" onClick={() => setPicked(channels.filter((x) => x !== c))} title="Remove from the charts">
                    {c} <span aria-hidden>×</span>
                  </button>
                ))}
                {channels.length < 8 && (
                  <select className="chip-add" value="" aria-label="Add a channel" onChange={(e) => e.target.value && setPicked([...channels, e.target.value])}>
                    <option value="">Add channel</option>
                    {names.filter((n) => !channels.includes(n) && !/^rpm$/i.test(n)).map((n) => (
                      <option key={n} value={n}>{n}</option>
                    ))}
                  </select>
                )}
              </div>
              {lines && lines.power.length > 0 ? (
                <div className="lap-charts">
                  {lines.delta.length > 1 && <CurveChart title="Power against the reference pull" unit="%" x={data.compare!.rpm} laps={lines.delta} refId={refId} colourOf={colourOf} signed />}
                  <CurveChart title="Power" unit={unit} note={unit === "relative" ? "relative, the strongest pull = 100" : undefined} x={data.compare!.rpm} laps={lines.power} refId={refId} colourOf={colourOf} />
                  <CurveChart title="Torque" unit={tUnit} x={data.compare!.rpm} laps={lines.torque} refId={refId} colourOf={colourOf} />
                  {lines.byChannel.map((b, i) => (
                    <CurveChart key={b.ch} title={b.ch} unit={data.units[b.ch] ?? ""} x={data.compare!.rpm} laps={b.lines} refId={refId} colourOf={colourOf} last={i === lines.byChannel.length - 1} />
                  ))}
                  <p className="muted small pull-note">
                    Power is worked out from how quickly the roller speeds up (the inertia method). It shows differences between runs well, but it leaves out drag and driveline losses, so it is not a calibrated figure.
                  </p>
                </div>
              ) : (
                <p className="muted pad">Tick at least one pull to compare.</p>
              )}
            </>
          )}
        </div>
      </div>
    </section>
  );
}

function PullGroup(props: {
  title: string;
  sub: string;
  rows: Row[];
  selected: string[];
  refId: string | null;
  refPeak: number | undefined;
  peaks: Map<string, NonNullable<PullsData["compare"]>["peaks"][number]>;
  colourOf: (id: string) => string;
  onToggle: (id: string) => void;
  onRef: (id: string) => void;
  unit: string;
}) {
  return (
    <>
      {props.title && (
        <tr className="group">
          <th colSpan={5} scope="colgroup">
            {props.title} <small>{props.sub}</small>
          </th>
        </tr>
      )}
      {props.rows.map((r) => {
        const on = props.selected.includes(r.id);
        const pk = props.peaks.get(r.id);
        const gain = pk?.peak_power != null && props.refPeak ? (pk.peak_power / props.refPeak - 1) * 100 : null;
        return (
          <tr key={r.id} className={on ? undefined : "off"}>
            <td>
              <input type="checkbox" checked={on} onChange={() => props.onToggle(r.id)} aria-label={`Show pull ${r.n}`} />
            </td>
            <th scope="row">
              <button className="lap-name" onClick={() => props.onRef(r.id)} disabled={!on} title="Compare the other pulls against this one">
                <span className="swatch" style={{ background: props.colourOf(r.id) }} aria-hidden />
                {r.n}
              </button>
              {r.loaded === false && <small className="log-tag">Rev only</small>}
            </th>
            <td className="num">
              {Math.round(r.rpm_start / 100) / 10}–{Math.round(r.rpm_end / 100) / 10}k
            </td>
            <td className="num">{pk?.peak_power != null && on ? formatValue(pk.peak_power) : "–"}</td>
            <td className="num">{r.id === props.refId ? "ref" : gain == null || !on ? "–" : `${gain >= 0 ? "+" : "−"}${Math.abs(gain).toFixed(1)}%`}</td>
          </tr>
        );
      })}
    </>
  );
}

function CurveChart(props: {
  title: string;
  unit: string;
  note?: string;
  x: number[];
  laps: Line[];
  refId: string | null;
  colourOf: (id: string) => string;
  signed?: boolean;
  last?: boolean;
}) {
  const data = useMemo(() => [props.x, ...props.laps.map((l) => l.ys)] as unknown as uPlot.AlignedData, [props.x, props.laps]);
  if (!props.laps.length) return null;
  const fmt = (v: number | null) => (v == null ? "–" : props.signed ? `${v >= 0 ? "+" : "−"}${Math.abs(v).toFixed(1)}` : formatValue(v));
  return (
    <div className="lap-chart" style={{ height: 230 }}>
      <h3>
        {props.title}
        {props.unit && <small> {props.unit}</small>}
        {props.note && <small> · {props.note}</small>}
      </h3>
      <Chart
        data={data}
        build={(w, h) => ({
          width: w,
          height: h - 56,
          legend: { show: true, live: true },
          cursor: { sync: { key: "pulls" }, drag: { x: false, y: false }, points: { show: false } },
          scales: { x: { time: false } },
          axes: [axis("", { size: 28 }), axis("", { size: 56 })],
          series: [
            { label: "RPM", value: (_u, v) => (v == null ? "–" : v.toFixed(0)) },
            ...props.laps.map((l) => ({
              label: l.label,
              stroke: props.colourOf(l.id),
              width: l.id === props.refId ? 2.5 : 1.5,
              points: { show: false },
              spanGaps: false,
              value: (_u: uPlot, v: number | null) => fmt(v),
            })),
          ],
        })}
      />
    </div>
  );
}
