import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import uPlot from "uplot";
import { api, type LiveSourceKind, type LiveStatus } from "../api";
import { useStore } from "../store";
import { TRACE, formatValue } from "./Lane";

const ASH = "#8b919c";
const RULE = "#1d2127";
const FONT = '12px "Geist Variable", system-ui, sans-serif';
const PREFERRED = [/^vehiclespeed$/i, /^rpm$/i, /^tps1?$/i, /^latg$/i, /^lapTime$/i];

type Buf = { t: number[]; v: Record<string, (number | null)[]> };

const SOURCES: { id: LiveSourceKind; label: string; help: string }[] = [
  { id: "simulator", label: "Simulated car", help: "A made-up car lapping a circuit. Try the whole screen with no hardware." },
  { id: "replay", label: "Replay a saved log", help: "Plays a log from your library back at real speed, as if it were arriving now." },
  { id: "udp", label: "UDP port", help: "Listens on this computer for lines of data sent over the network by a bridge or logger." },
  { id: "serial", label: "Serial / USB port", help: "Reads lines of data from a COM port, for example from a radio or microcontroller." },
  { id: "push", label: "Pushed by another program", help: "Waits for a program to send rows to this tool. See the example under Connect your car." },
];

export function Live() {
  const library = useStore((s) => s.library);
  const loadLibrary = useStore((s) => s.loadLibrary);
  const [status, setStatus] = useState<LiveStatus | null>(null);
  const [kind, setKind] = useState<LiveSourceKind>("simulator");
  const [speed, setSpeed] = useState(1);
  const [replayId, setReplayId] = useState("");
  const [loop, setLoop] = useState(false);
  const [port, setPort] = useState("5005");
  const [serialPort, setSerialPort] = useState("");
  const [baud, setBaud] = useState("115200");
  const [ports, setPorts] = useState<{ port: string; description: string }[]>([]);
  const [picked, setPicked] = useState<string[]>([]);
  const [windowS, setWindowS] = useState(30);
  const [error, setError] = useState<string | null>(null);
  const [saveName, setSaveName] = useState("");
  const buf = useRef<Buf>({ t: [], v: {} });
  const chans = useRef<string[]>([]);
  const win = useRef(30);
  win.current = windowS;

  useEffect(() => {
    void loadLibrary();
    const fail = (what: string) => (e: Error) => setError(`${what}. ${e.message}`);
    api.liveStatus().then(setStatus, fail("Could not read the live status"));
    api.livePorts().then(setPorts, fail("Could not list the serial ports"));
  }, [loadLibrary]);

  // choose some channels to show as soon as the first data arrives
  useEffect(() => {
    if (picked.length || !status?.channels.length) return;
    const names = status.channels.map((c) => c.name);
    const first = PREFERRED.map((re) => names.find((n) => re.test(n))).filter(Boolean) as string[];
    setPicked((first.length ? first : names).slice(0, 4));
  }, [status?.channels, picked.length]);
  chans.current = picked;

  // seed the plots with what the hub already holds, so they are not empty when you open the tab or add a channel
  const seeded = useRef("");
  useEffect(() => {
    if (!picked.length) return;
    const key = picked.join(",");
    if (seeded.current === key) return;
    seeded.current = key;
    api.liveWindow(picked, 120).then(
      (w) => {
        buf.current = { t: w.t, v: Object.fromEntries(picked.map((c) => [c, w.v[c] ?? w.t.map(() => null)])) };
      },
      (e: Error) => setError(`Could not load the recent data. ${e.message}`),
    );
  }, [picked]);

  // follow the stream
  useEffect(() => {
    const es = new EventSource(`/api/live/stream?channels=${encodeURIComponent(picked.join(","))}`);
    es.onmessage = (e) => {
      const m = JSON.parse(e.data) as { t?: number[]; v?: Record<string, (number | null)[]>; status?: LiveStatus };
      if (m.status) setStatus(m.status);
      if (!m.t?.length) return;
      const b = buf.current;
      if (b.t.length && m.t[0] < b.t[b.t.length - 1] - 1) buf.current = { t: [], v: {} }; // the session restarted
      const cur = buf.current;
      const had = cur.t.length;
      cur.t.push(...m.t);
      for (const c of chans.current) {
        const col = (cur.v[c] ??= new Array(had).fill(null));
        col.push(...(m.v?.[c] ?? m.t.map(() => null)));
      }
      const keepFrom = cur.t[cur.t.length - 1] - Math.max(win.current * 1.5, 150);
      let cut = 0;
      while (cut < cur.t.length - 2 && cur.t[cut] < keepFrom) cut++;
      if (cut > 500) {
        cur.t.splice(0, cut);
        for (const c of Object.keys(cur.v)) cur.v[c].splice(0, cut);
      }
    };
    return () => es.close();
  }, [picked.join(",")]);

  const run = useCallback(async () => {
    setError(null);
    const options: Record<string, unknown> =
      kind === "simulator" ? { speed }
      : kind === "replay" ? { source_id: replayId, speed, loop, label: library.find((l) => l.id === replayId)?.label }
      : kind === "udp" ? { port: Number(port) }
      : kind === "serial" ? { port: serialPort, baud: Number(baud) }
      : {};
    try {
      buf.current = { t: [], v: {} };
      seeded.current = "";
      setStatus(await api.liveStart(kind, options));
    } catch (e) {
      setError((e as Error).message);
    }
  }, [kind, speed, replayId, loop, port, serialPort, baud, library]);

  const stop = async () => setStatus(await api.liveStop());
  const clear = async () => {
    buf.current = { t: [], v: {} };
    seeded.current = "";
    setPicked([]);
    setStatus(await api.liveClear());
  };
  const save = async () => {
    try {
      const rec = await api.liveSave(saveName);
      await useStore.getState().refresh();
      void useStore.getState().loadLibrary();
      useStore.setState({ message: { kind: "info", text: `Saved "${rec.label}" as a log. Find it in Plots, Laps and the Library.` } });
      setSaveName("");
    } catch (e) {
      setError((e as Error).message);
    }
  };

  const running = status?.state === "running" || status?.source?.kind === "push";
  const stale = (status?.age_s ?? 0) > 3;
  const channels = status?.channels ?? [];
  const src = SOURCES.find((s) => s.id === kind)!;

  return (
    <section className="live" aria-label="Live">
      <div className="live-bar">
        <label className="inline">
          Source
          <select value={kind} onChange={(e) => setKind(e.target.value as LiveSourceKind)} disabled={status?.state === "running"}>
            {SOURCES.map((s) => (
              <option key={s.id} value={s.id}>{s.label}</option>
            ))}
          </select>
        </label>
        {kind === "replay" && (
          <label className="inline">
            Log
            <select value={replayId} onChange={(e) => setReplayId(e.target.value)}>
              <option value="">Choose a log</option>
              {library.map((l) => (
                <option key={l.id} value={l.id}>{l.label}</option>
              ))}
            </select>
          </label>
        )}
        {(kind === "simulator" || kind === "replay") && (
          <label className="inline">
            Speed
            <select value={speed} onChange={(e) => setSpeed(Number(e.target.value))}>
              {[1, 2, 5, 10].map((k) => (
                <option key={k} value={k}>{k}×</option>
              ))}
            </select>
          </label>
        )}
        {kind === "replay" && (
          <label className="inline check">
            <input type="checkbox" checked={loop} onChange={(e) => setLoop(e.target.checked)} /> Repeat
          </label>
        )}
        {kind === "udp" && (
          <label className="inline">
            Port
            <input type="number" min="1" max="65535" value={port} onChange={(e) => setPort(e.target.value)} />
          </label>
        )}
        {kind === "serial" && (
          <>
            <label className="inline">
              Port
              <select value={serialPort} onChange={(e) => setSerialPort(e.target.value)}>
                <option value="">{ports.length ? "Choose a port" : "No ports found"}</option>
                {ports.map((p) => (
                  <option key={p.port} value={p.port}>{p.port} {p.description ? `(${p.description})` : ""}</option>
                ))}
              </select>
            </label>
            <label className="inline">
              Baud
              <input type="number" value={baud} onChange={(e) => setBaud(e.target.value)} />
            </label>
          </>
        )}
        {status?.state === "running" ? (
          <button className="btn" onClick={() => void stop()}>Stop</button>
        ) : (
          <button className="btn primary" onClick={() => void run()} disabled={kind === "replay" && !replayId}>
            {kind === "push" ? "Wait for data" : "Start"}
          </button>
        )}
        <div className="spacer" />
        {status && status.rows > 0 && (
          <>
            <input className="save-name" value={saveName} onChange={(e) => setSaveName(e.target.value)} placeholder="Name this session" aria-label="Name for the saved log" maxLength={80} />
            <button className="btn" onClick={() => void save()} title="Keep what is on screen as a log in your library">Save as log</button>
            <button className="btn ghost" onClick={() => void clear()}>Clear</button>
          </>
        )}
      </div>

      <div className="live-status" role="status">
        <span className={`dot ${status?.state === "running" && !stale ? "on" : stale ? "warn" : ""}`} aria-hidden />
        {status?.error ? (
          <span className="live-error">{status.error}</span>
        ) : status?.state === "running" || (status?.source && status.source.kind === "push") ? (
          <span>
            {status?.source?.label}
            {status?.rate_hz ? ` · ${status.rate_hz.toFixed(0)} rows a second` : ""}
            {status?.rows ? ` · ${status.rows.toLocaleString()} rows` : " · waiting for the first row"}
            {stale ? ` · nothing received for ${Math.round(status?.age_s ?? 0)} s` : ""}
          </span>
        ) : status && status.rows > 0 ? (
          <span>Stopped · {status.rows.toLocaleString()} rows kept. Save them as a log, or start again.</span>
        ) : (
          <span className="muted">{src.help}</span>
        )}
        {status && status.rejected > 0 && (
          <span className="live-error">
            {status.rejected.toLocaleString()} line{status.rejected === 1 ? "" : "s"} could not be read. Last: {status.last_reject}
          </span>
        )}
        {status && status.rows > status.capacity && (
          <span className="muted"> · only the latest {status.capacity.toLocaleString()} rows are kept</span>
        )}
      </div>
      {error && <p className="live-error pad">{error}</p>}

      {channels.length === 0 ? (
        <Connect />
      ) : (
        <div className="live-body">
          <div className="live-main">
            <div className="chips">
              {picked.map((c) => (
                <button key={c} className="chip on" onClick={() => setPicked(picked.filter((x) => x !== c))} title="Remove from the screen">
                  {c} <span aria-hidden>×</span>
                </button>
              ))}
              {picked.length < 8 && (
                <select className="chip-add" value="" aria-label="Add a channel" onChange={(e) => e.target.value && setPicked([...picked, e.target.value])}>
                  <option value="">Add channel</option>
                  {channels.filter((c) => !picked.includes(c.name)).map((c) => (
                    <option key={c.name} value={c.name}>{c.name}</option>
                  ))}
                </select>
              )}
              <div className="spacer" />
              <div className="seg" role="tablist" aria-label="Time shown">
                {[10, 30, 60, 120].map((s) => (
                  <button key={s} role="tab" aria-selected={windowS === s} className={windowS === s ? "on" : undefined} onClick={() => setWindowS(s)}>
                    {s} s
                  </button>
                ))}
              </div>
            </div>
            <div className="live-plots">
              {picked.map((c, i) => (
                <LivePlot key={c} name={c} unit={channels.find((x) => x.name === c)?.unit ?? ""} colour={TRACE[i % TRACE.length]} buf={buf} win={win} last={channels.find((x) => x.name === c)?.last ?? null} />
              ))}
            </div>
          </div>
          {!running && picked.length === 0 && <p className="muted pad">Pick a channel to follow.</p>}
        </div>
      )}
    </section>
  );
}

function Connect() {
  return (
    <div className="live-connect">
      <h2>Connect your car</h2>
      <p>
        Pick a source above and press Start. Until the car side is wired up, <strong>Simulated car</strong> and <strong>Replay a saved log</strong> let you try everything.
      </p>
      <details>
        <summary>Send data from another program</summary>
        <p className="muted small">Post rows to this tool as often as you like. Time is in seconds and optional; channels can appear at any point.</p>
        <pre className="code">{`curl -X POST http://127.0.0.1:8000/api/live/ingest \\
  -H "Content-Type: application/json" \\
  -d '{"rows":[{"t":0.01,"values":{"rpm":8200,"vehicleSpeed":71.5}}],
       "units":{"rpm":"rpm","vehicleSpeed":"km/h"}}'`}</pre>
        <p className="muted small">
          The repository's <code>tools/live_bridge_example.py</code> shows the same thing in Python, ready to adapt to a CAN adapter or a radio.
        </p>
      </details>
      <details>
        <summary>UDP and serial line formats</summary>
        <p className="muted small">One line per sample, in either form:</p>
        <pre className="code">{`{"t": 12.34, "rpm": 8200, "vehicleSpeed": 71.5}

time,rpm,vehicleSpeed      <- a header line names the columns
12.34,8200,71.5`}</pre>
      </details>
    </div>
  );
}

function LivePlot(props: {
  name: string;
  unit: string;
  colour: string;
  buf: React.MutableRefObject<Buf>;
  win: React.MutableRefObject<number>;
  last: number | null;
}) {
  const box = useRef<HTMLDivElement>(null);
  const plot = useRef<uPlot | null>(null);
  const tmax = useRef(0);

  useEffect(() => {
    const el = box.current;
    if (!el) return;
    const make = (w: number) =>
      new uPlot(
        {
          width: w,
          height: 150,
          legend: { show: false },
          cursor: { show: false },
          scales: { x: { time: false, range: () => [tmax.current - props.win.current, tmax.current] } },
          axes: [
            { stroke: ASH, font: FONT, grid: { stroke: RULE, width: 1 }, ticks: { stroke: RULE, width: 1, size: 4 }, values: (_u, v) => v.map((x) => `${Math.round(x - tmax.current)} s`) },
            { stroke: ASH, font: FONT, size: 56, grid: { stroke: RULE, width: 1 }, ticks: { stroke: RULE, width: 1, size: 4 } },
          ],
          series: [{}, { stroke: props.colour, width: 1.75, points: { show: false } }],
        },
        [[], []],
        el,
      );
    plot.current = make(Math.max(el.clientWidth, 200));
    const ro = new ResizeObserver(() => plot.current?.setSize({ width: Math.max(el.clientWidth, 200), height: 150 }));
    ro.observe(el);
    let frame = 0;
    const draw = () => {
      const b = props.buf.current;
      const y = b.v[props.name];
      if (plot.current && y && b.t.length) {
        tmax.current = b.t[b.t.length - 1];
        plot.current.setData([b.t, y], true);
      }
      frame = requestAnimationFrame(draw);
    };
    frame = requestAnimationFrame(draw);
    return () => {
      cancelAnimationFrame(frame);
      ro.disconnect();
      plot.current?.destroy();
      plot.current = null;
    };
  }, [props.name, props.colour]);

  const value = useMemo(() => (props.last == null ? "–" : formatValue(props.last)), [props.last]);
  return (
    <div className="live-plot">
      <div className="live-plot-head">
        <span className="swatch" style={{ background: props.colour }} aria-hidden />
        <strong>{props.name}</strong>
        {props.unit && <small>{props.unit}</small>}
        <span className="live-value num">{value}</span>
      </div>
      <div ref={box} className="live-canvas" />
    </div>
  );
}
