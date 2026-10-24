import { useEffect, useMemo, useRef, useState } from "react";
import uPlot from "uplot";
import { api, type LapCompare, type LapStats, type LapParams, type LapRow, type LapTable as LapTableData, type Track } from "../api";
import { useStore, type Source } from "../store";
import { spansDays, stamp } from "../time";
import { Chart, axis, useFetched } from "./Analysis";
import { formatValue } from "./Lane";

const LAP_COLOURS = ["#38c8f0", "#ffb020", "#3ddc84", "#b79bff", "#ff8fb1", "#e8e8e8", "#7fa6ff", "#d6e34a"];
const REF_COLOUR = "#ff3b47";
const RAMP = ["#2f6df0", "#38c8f0", "#3ddc84", "#ffb020", "#ff3b47"];
const ALL = "__all__";

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

type Row = LapRow & { id: string; log: string };
type Group = { src: Source; table: LapTableData; rows: Row[] };

export function Laps() {
  const sources = useStore((s) => s.sources);
  const [sid, setSid] = useState("");
  const single = sources.find((x) => x.id === sid);
  const all = sources.length > 1 && (sid === ALL || (!single && sid === ""));
  const srcs = all ? sources : [single ?? sources[0]];
  // keyed by the choice, so switching logs starts from clean lap, channel and reference choices
  return <LapsView key={all ? ALL : srcs[0].id} srcs={srcs} sources={sources} choice={all ? ALL : srcs[0].id} onPick={setSid} />;
}

function LapsView({ srcs, sources, choice, onPick }: { srcs: Source[]; sources: Source[]; choice: string; onPick: (id: string) => void }) {
  const rev = useStore((s) => s.rev);
  const multi = srcs.length > 1;
  const withDate = spansDays(srcs);
  const tag = (s: Source) => (s.started_at ? stamp(s.started_at, withDate) : s.label);

  const params = useStore((s) => s.lapParams);
  const setParams = useStore((s) => s.setLapParams);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const axisKind = useStore((s) => s.lapAxis);
  const setAxisKind = useStore((s) => s.setLapAxis);
  const [picked, setPicked] = useState<string[]>([]);
  const [sel, setSel] = useState<string[] | null>(null);
  const [ref, setRef] = useState<string | null>(null);
  const [colourBy, setColourBy] = useState("");
  const [mirror, setMirror] = useState(false);
  const [lapMode, setLapMode] = useState<"charts" | "numbers">("charts");

  const key = JSON.stringify(params);
  const found = useFetched(async () => {
    const r = await Promise.all(
      srcs.map((s) => api.laps(s.id, params).then((t) => ({ s, t }), (e: Error) => ({ s, err: e.message }))),
    );
    const groups: Group[] = [];
    const errors: { label: string; message: string }[] = [];
    for (const x of r) {
      if ("t" in x) groups.push({ src: x.s, table: x.t, rows: x.t.laps.map((l) => ({ ...l, id: `${x.s.id}:${l.n}`, log: x.s.id })) });
      else errors.push({ label: x.s.label, message: x.err });
    }
    return { groups, errors };
  }, [srcs.map((s) => s.id).join(","), key, rev]);

  const groups = useMemo(() => found.data?.groups.filter((g) => g.rows.length) ?? [], [found.data]);
  const rows = useMemo(() => groups.flatMap((g) => g.rows), [groups]);
  const noLaps = !!found.data && rows.length === 0;
  const firstError = found.error ?? found.data?.errors[0]?.message ?? null;

  // the lap everything is compared against: the quickest valid lap across the chosen logs, unless one was clicked
  const bestRow = useMemo(() => {
    const pool = rows.filter((r) => r.valid);
    return (pool.length ? pool : rows).reduce<Row | null>((b, r) => (!b || r.duration_s < b.duration_s ? r : b), null);
  }, [rows]);
  const selected = sel ?? rows.filter((r) => r.valid).map((r) => r.id);
  const refId = ref && rows.some((r) => r.id === ref) ? ref : (bestRow?.id ?? null);
  const refLog = refId ? refId.slice(0, refId.indexOf(":")) : srcs[0].id;
  const refGroup = groups.find((g) => g.src.id === refLog) ?? groups[0];

  const names = useMemo(() => [...new Set(groups.flatMap((g) => g.src.channels.map((c) => c.name)))], [groups]);
  const speed = refGroup?.table.speed_channel ?? null;
  const defaults = useMemo(() => {
    const find = (re: RegExp) => names.find((n) => re.test(n));
    return [speed, find(/^(tps1?|throttle)$/i), find(/^rpm$/i)].filter(Boolean) as string[];
  }, [names, speed]);
  const channels = picked.length ? picked : defaults;
  const hasDistance = groups.length > 0 && groups.every((g) => g.table.speed_channel);
  const axisUsed = hasDistance ? axisKind : "time";

  const colourOf = useMemo(() => {
    const order = rows.filter((r) => selected.includes(r.id)).map((r) => r.id);
    return (id: string) => (id === refId ? REF_COLOUR : LAP_COLOURS[Math.max(order.indexOf(id), 0) % LAP_COLOURS.length]);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [rows, selected.join(","), refId]);

  const view = useFetched(
    async () =>
      groups.length && channels.length
        ? api.lapCompare(groups.map((g) => g.src.id), params, channels, selected, refId, axisUsed)
        : null,
    [groups.map((g) => g.src.id).join(","), key, channels.join(","), selected.join(","), refId, axisUsed, rev],
  );

  const colour = colourBy || speed || "";
  const track = useFetched(() => api.track(refLog, params, colour || undefined, mirror), [refLog, key, colour, mirror, rev]);

  const apply = (p: LapParams) => {
    setParams(p);
    setSel(null);
    setRef(null);
  };
  const toggle = (id: string) => setSel((cur) => ((cur ?? selected).includes(id) ? (cur ?? selected).filter((x) => x !== id) : [...(cur ?? selected), id]));
  const lapCount = rows.length;

  return (
    <section className="analysis laps" aria-label="Laps">
      <div className="analysis-bar">
        {sources.length > 1 && (
          <label className="inline">
            Log
            <select value={choice} onChange={(e) => onPick(e.target.value)}>
              <option value={ALL}>All logs (compare)</option>
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
        <div className="seg" role="tablist" aria-label="Lap view">
          <button role="tab" aria-selected={lapMode === "charts"} className={lapMode === "charts" ? "on" : undefined} onClick={() => setLapMode("charts")}>
            Charts
          </button>
          <button role="tab" aria-selected={lapMode === "numbers"} className={lapMode === "numbers" ? "on" : undefined} onClick={() => setLapMode("numbers")}>
            Numbers
          </button>
        </div>
        {found.data && !noLaps && (
          <span className="muted small">
            {lapCount} lap{lapCount === 1 ? "" : "s"}
            {multi ? ` across ${groups.length} log${groups.length === 1 ? "" : "s"}` : ""} found from {groups[0].table.found_by}.
          </span>
        )}
        <div className="spacer" />
        <button className="btn sm" onClick={() => setSettingsOpen((o) => !o)} aria-expanded={settingsOpen}>
          How laps are found
        </button>
      </div>

      {(settingsOpen || noLaps) && <LapSettings names={names.length ? names : srcs.flatMap((s) => s.channels.map((c) => c.name))} value={params} onApply={apply} error={noLaps ? firstError : null} />}

      <div className="laps-body">
        <aside className="laps-side">
          {groups.length > 0 && (
            <LapTable groups={groups} sel={selected} refId={refId} bestId={bestRow?.id ?? null} onToggle={toggle} onRef={setRef} hasSpeed={hasDistance} label={tag} multi={multi} colourOf={colourOf} />
          )}
          {multi && (found.data?.errors.length ?? 0) > 0 && groups.length > 0 && (
            <p className="muted small lap-note">No laps in: {found.data!.errors.map((e) => e.label).join(", ")}.</p>
          )}
          {refGroup && (
            <TrackCard
              show={groups.length > 0 || track.data?.source === "gps"}
              track={track.data}
              error={track.error}
              names={refGroup.src.channels.map((c) => c.name)}
              colour={colour}
              onColour={setColourBy}
              mirror={mirror}
              onMirror={setMirror}
              title={multi ? `Track · ${tag(refGroup.src).replace(/:\d\d$/, "")}` : "Track"}
            />
          )}
        </aside>

        <div className="laps-main">
          {!found.data && !found.error && <p className="muted pad">Finding laps</p>}
          {found.error && <p className="muted pad">{found.error}</p>}
          {noLaps && (
            <div className="laps-empty">
              <h2>No laps found {multi ? "in these logs" : "in this log"}</h2>
              <p>{firstError}</p>
              <p className="muted">
                Dyno and bench runs have no start/finish line, so that is normal for them. Track logs usually carry a lap timer or beacon channel; choose it under
                "How laps are found".
              </p>
            </div>
          )}
          {groups.length > 0 && (
            <>
              <div className="chips">
                {channels.map((c) => (
                  <button key={c} className="chip on" onClick={() => setPicked(channels.filter((x) => x !== c))} title="Remove from the overlay">
                    {c} <span aria-hidden>×</span>
                  </button>
                ))}
                {channels.length < 6 && (
                  <select className="chip-add" value="" aria-label="Add a channel to the overlay" onChange={(e) => e.target.value && setPicked([...channels, e.target.value])}>
                    <option value="">Add channel</option>
                    {names.filter((n) => !channels.includes(n)).map((n) => (
                      <option key={n} value={n}>{n}</option>
                    ))}
                  </select>
                )}
              </div>
              {lapMode === "charts" ? (
                <>
                  {view.error && <p className="muted pad">{view.error}</p>}
                  {view.data && <Overlay view={view.data} channels={channels} colourOf={colourOf} refId={refId} groups={groups} label={tag} multi={multi} />}
                </>
              ) : (
                <LapNumbers groups={groups} selected={selected} channels={channels} params={params} multi={multi} label={tag} />
              )}
            </>
          )}
        </div>
      </div>
    </section>
  );
}

const mmss = (s: number) => fmtLap(s);

function LapNumbers(props: { groups: Group[]; selected: string[]; channels: string[]; params: LapParams; multi: boolean; label: (s: Source) => string }) {
  const [n, setN] = useState(3);
  const [metric, setMetric] = useState<"max" | "min" | "mean">("max");
  const ids = props.groups.map((g) => g.src.id);
  const { data, error } = useFetched(
    () => api.lapStats(ids, props.params, props.channels, props.selected, n),
    [ids.join(","), JSON.stringify(props.params), props.channels.join(","), props.selected.join(","), n],
  );
  if (!data) return <p className="muted pad">{error ?? "Working out the numbers"}</p>;
  const nameOf = (log: string, lapN: number) => {
    const s = props.groups.find((g) => g.src.id === log)?.src;
    return `${props.multi && s ? `${props.label(s).replace(/:\d\d$/, "")} · ` : ""}Lap ${lapN}`;
  };
  const bestReal = data.laps.filter((l) => l.valid).reduce<number | null>((b, l) => (b == null || l.duration_s < b ? l.duration_s : b), null);
  const isBest = (i: number, l: LapStats["laps"][number]) => data.best_sectors[i]?.log === l.log && data.best_sectors[i]?.n === l.n;
  const withSectors = data.laps.filter((l) => l.sectors);
  return (
    <div className="lap-numbers">
      {withSectors.length > 0 && (
        <section>
          <div className="numbers-head">
            <h3>Sector times</h3>
            <label className="inline">
              Sectors
              <select value={n} onChange={(e) => setN(Number(e.target.value))}>
                {[2, 3, 4, 5, 6, 8].map((k) => (
                  <option key={k} value={k}>{k}</option>
                ))}
              </select>
            </label>
          </div>
          <p className="muted small">Each lap is split into equal distances. Red is the quickest anyone went through that sector.</p>
          <table className="stats">
            <thead>
              <tr>
                <th scope="col">Lap</th>
                {Array.from({ length: data.sectors }, (_, i) => (
                  <th key={i} scope="col" className="num">S{i + 1}</th>
                ))}
                <th scope="col" className="num">Lap time</th>
              </tr>
            </thead>
            <tbody>
              {withSectors.map((l) => (
                <tr key={`${l.log}:${l.n}`} className={l.valid ? undefined : "off"}>
                  <th scope="row">{nameOf(l.log, l.n)}{!l.valid && <small className="log-tag">In/out</small>}</th>
                  {l.sectors!.map((t, i) => (
                    <td key={i} className={`num${isBest(i, l) ? " best-cell" : ""}`}>{t.toFixed(3)}</td>
                  ))}
                  <td className="num">{mmss(l.duration_s)}</td>
                </tr>
              ))}
              {data.ideal_s != null && (
                <tr className="ideal">
                  <th scope="row">Ideal lap</th>
                  {data.best_sectors.map((b, i) => (
                    <td key={i} className="num">{b.time_s.toFixed(3)}</td>
                  ))}
                  <td className="num">{mmss(data.ideal_s)}</td>
                </tr>
              )}
            </tbody>
          </table>
          {data.ideal_s != null && bestReal != null && (
            <p className="ideal-note">
              {bestReal - data.ideal_s < 0.0005
                ? `The best lap (${mmss(bestReal)}) was already the quickest through every sector, so there is nothing left to string together.`
                : `Stringing the best of every sector together gives ${mmss(data.ideal_s)}, which is ${(bestReal - data.ideal_s).toFixed(3)} s quicker than the best lap actually driven (${mmss(bestReal)}).`}
            </p>
          )}
        </section>
      )}

      <section>
        <div className="numbers-head">
          <h3>Channel values by lap</h3>
          <div className="seg" role="tablist" aria-label="Value shown">
            {([["max", "Highest"], ["min", "Lowest"], ["mean", "Average"]] as const).map(([k, label]) => (
              <button key={k} role="tab" aria-selected={metric === k} className={metric === k ? "on" : undefined} onClick={() => setMetric(k)}>
                {label}
              </button>
            ))}
          </div>
        </div>
        {props.channels.length === 0 ? (
          <p className="muted small">Add a channel above to see its values for each lap.</p>
        ) : (
          <table className="stats">
            <thead>
              <tr>
                <th scope="col">Lap</th>
                {props.channels.map((c) => (
                  <th key={c} scope="col" className="num">
                    {c}
                    {data.units[c] ? ` (${data.units[c]})` : ""}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {data.laps.map((l) => (
                <tr key={`${l.log}:${l.n}`} className={l.valid ? undefined : "off"}>
                  <th scope="row">{nameOf(l.log, l.n)}</th>
                  {props.channels.map((c) => (
                    <td key={c} className="num">{l.metrics[c] ? formatValue(l.metrics[c]![metric]) : "–"}</td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>
    </div>
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
  groups: Group[];
  sel: string[];
  refId: string | null;
  bestId: string | null;
  hasSpeed: boolean;
  multi: boolean;
  label: (s: Source) => string;
  colourOf: (id: string) => string;
  onToggle: (id: string) => void;
  onRef: (id: string) => void;
}) {
  const rows = props.groups.flatMap((g) => g.rows);
  const best = rows.find((l) => l.id === props.bestId);
  const valid = rows.filter((l) => l.valid);
  const avg = valid.length ? valid.reduce((a, l) => a + l.duration_s, 0) / valid.length : null;
  const refRow = rows.find((l) => l.id === props.refId);
  const refDur = refRow?.duration_s ?? best?.duration_s ?? 0;
  const cols = props.hasSpeed ? 5 : 4;
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
            <th scope="col" className="num">{refRow && refRow.id !== props.bestId ? "Δ ref" : "Δ best"}</th>
            {props.hasSpeed && <th scope="col" className="num">Top km/h</th>}
          </tr>
        </thead>
        <tbody>
          {props.groups.map((g) => (
            <LapGroup key={g.src.id} g={g} cols={cols} refDur={refDur} {...props} />
          ))}
        </tbody>
      </table>
      <p className="muted small lap-note">Click a lap number to make it the reference the others are compared against.</p>
    </div>
  );
}

function LapGroup(props: Parameters<typeof LapTable>[0] & { g: Group; cols: number; refDur: number }) {
  const { g } = props;
  return (
    <>
      {props.multi && (
        <tr className="group">
          <th colSpan={props.cols} scope="colgroup">
            {props.label(g.src)} <small>{g.src.label}</small>
          </th>
        </tr>
      )}
      {g.rows.map((l) => {
        const on = props.sel.includes(l.id);
        const isRef = l.id === props.refId;
        return (
          <tr key={l.id} className={on ? undefined : "off"}>
            <td>
              <input type="checkbox" checked={on} onChange={() => props.onToggle(l.id)} aria-label={`Show lap ${l.n}`} />
            </td>
            <th scope="row">
              <button className="lap-name" onClick={() => props.onRef(l.id)} title="Compare the other laps against this one">
                <span className="swatch" style={{ background: props.colourOf(l.id) }} aria-hidden />
                {l.n}
              </button>
              {l.id === props.bestId && <small className="log-tag best">Best</small>}
              {!l.valid && <small className="log-tag">In/out</small>}
            </th>
            <td className="num">{fmtLap(l.duration_s)}</td>
            <td className="num">{isRef ? "–" : fmtDelta(l.duration_s - props.refDur)}</td>
            {props.hasSpeed && <td className="num">{l.max_kmh != null ? l.max_kmh.toFixed(1) : "–"}</td>}
          </tr>
        );
      })}
    </>
  );
}

type Line = { id: string; label: string; ys: (number | null)[] };

function Overlay(props: {
  view: LapCompare;
  channels: string[];
  colourOf: (id: string) => string;
  refId: string | null;
  groups: Group[];
  label: (s: Source) => string;
  multi: boolean;
}) {
  const { view } = props;
  const isDist = view.axis === "distance";
  const xLabel = isDist ? "Distance into the lap (m)" : "Time into the lap (s)";
  const name = (log: string, n: number) => {
    const s = props.groups.find((g) => g.src.id === log)?.src;
    return props.multi && s ? `${props.label(s).replace(/:\d\d$/, "")} L${n}` : `Lap ${n}`;
  };
  const delta = useMemo<Line[]>(
    () => (isDist ? view.laps.filter((l) => l.delta_s).map((l) => ({ id: `${l.log}:${l.n}`, label: name(l.log, l.n), ys: l.delta_s! })) : []),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [view, isDist],
  );
  return (
    <div className="lap-charts">
      {delta.length > 0 && (
        <LapChart title="Time ahead (−) or behind (+) the reference lap" unit="s" x={view.x} xLabel={xLabel} laps={delta} refId={props.refId} colourOf={props.colourOf} height={210} signed />
      )}
      {props.channels.map((c, i) => (
        <OverlayChannel key={c} view={view} channel={c} xLabel={xLabel} last={i === props.channels.length - 1} name={name} refId={props.refId} colourOf={props.colourOf} />
      ))}
    </div>
  );
}

function OverlayChannel(props: {
  view: LapCompare;
  channel: string;
  xLabel: string;
  last: boolean;
  name: (log: string, n: number) => string;
  refId: string | null;
  colourOf: (id: string) => string;
}) {
  const { view, channel } = props;
  const lines = useMemo<Line[]>(
    () => view.laps.filter((l) => l.channels[channel]).map((l) => ({ id: `${l.log}:${l.n}`, label: props.name(l.log, l.n), ys: l.channels[channel] })),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [view, channel],
  );
  return <LapChart title={channel} unit={view.units[channel] ?? ""} x={view.x} xLabel={props.xLabel} laps={lines} refId={props.refId} colourOf={props.colourOf} height={240} last={props.last} />;
}

function LapChart(props: {
  title: string;
  unit: string;
  x: number[];
  xLabel: string;
  laps: Line[];
  refId: string | null;
  colourOf: (id: string) => string;
  height: number;
  signed?: boolean;
  last?: boolean;
}) {
  const data = useMemo(() => [props.x, ...props.laps.map((l) => l.ys)] as unknown as uPlot.AlignedData, [props.x, props.laps]);
  const dist = props.xLabel.startsWith("Dist");
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
            { label: dist ? "Distance (m)" : "Time (s)", value: (_u, v) => (v == null ? "–" : v.toFixed(dist ? 0 : 1)) },
            ...props.laps.map((l) => ({
              label: l.label,
              stroke: props.colourOf(l.id),
              width: l.id === props.refId ? 2.5 : 1.5,
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
  title: string;
}) {
  if (!props.show) return null;
  const t = props.track;
  const unit = t?.color_unit ?? "";
  return (
    <div className="track-card">
      <div className="track-head">
        <h3>{props.title}</h3>
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
