import { create } from "zustand";
import { api, type Dbc, type Finding, type LapParams, type Limit, type Review, type ReviewOcc } from "./api";
import { readJson, writeJson } from "./storage";

export type Channel = {
  name: string;
  unit: string;
  min: number;
  max: number;
  states?: Record<string, string>; // text channels: value (index) to label
  derived?: boolean; // a math channel
  expr?: string;
  native_hz?: number; // estimated readings per second, when slower than the log's sample rate
};

export type Source = {
  id: string;
  label: string;
  kind: "ecu" | "hcu" | "other";
  filename: string;
  offset_s: number;
  started_at: string | null; // wall-clock session start, from the log name
  duration_s: number;
  sample_rate_hz: number | null;
  rows: number;
  gaps: number;
  channels: Channel[];
  assumptions: string[];
  warnings: string[];
  rules?: Rule[];
  open?: boolean;
  reused?: boolean; // the same data was already in the library
};

export type LibraryEntry = {
  id: string;
  label: string;
  filename: string;
  started_at: string | null;
  imported_at: string;
  duration_s: number;
  rows: number;
  channels: number;
  open: boolean;
  from_lrd: boolean;
  size_bytes: number;
};

export type ConvertStatus = { available: boolean; reason: string; lifeview_open: boolean };
export type ConvertItem = { name: string; state: string; stage: string; error: string; source_id: string; csv: string };
export type ConvertJob = { id: string; state: "running" | "done" | "cancelled"; items: ConvertItem[]; imported: number };
export type ConvertView = {
  phase: "ready" | "running" | "finished";
  files: File[];
  status?: ConvertStatus;
  job?: ConvertJob;
  error?: string;
};

export type Rule = { name: string; expr: string; min_duration_s: number; merge_gap_s: number };

/** What a saved view remembers. It names channels, not logs, so it fits whichever logs are open. */
/** Everything under Analyse. */
export type ToolId = "statistics" | "histogram" | "spectrum" | "scatter" | "heatmap" | "summary" | "events" | "pulls" | "laps";
const TOOLS: ToolId[] = ["statistics", "histogram", "spectrum", "scatter", "heatmap", "summary", "events", "pulls", "laps"];
export const isTool = (v: unknown): v is ToolId => typeof v === "string" && (TOOLS as string[]).includes(v);

export type Metric = { id: string; name: string; expr: string; agg: string; where: string; unit: string };

export type ViewPayload = {
  v: 1;
  summary?: Metric[];
  mode: "plots" | "analyse";
  tool?: ToolId;
  lanes: string[][];
  lap: { params: LapParams; axis: "distance" | "time" };
};
export type SavedView = { id: string; name: string; saved_at: string; payload: ViewPayload; auto?: boolean };

export type LaneSeries = { sourceId: string; channel: string };
export type Lane = { id: number; series: LaneSeries[] };

type State = {
  sources: Source[];
  lanes: Lane[];
  library: LibraryEntry[];
  libraryOpen: boolean;
  /** Whether this browser is on the PC that runs the tool, and whether phone access is on. Assume the PC until known. */
  access: { local: boolean; sharing: boolean };
  loadAccess: () => Promise<void>;
  shareOpen: boolean;
  setShareOpen: (open: boolean) => void;
  /** On a phone the log list slides over the plots instead of sitting beside them. */
  railOpen: boolean;
  setRailOpen: (open: boolean) => void;
  setLibraryOpen: (open: boolean) => void;
  loadLibrary: () => Promise<void>;
  addFromLibrary: (ids: string[]) => Promise<void>;
  closeLog: (id: string) => Promise<void>;
  deleteForever: (id: string) => Promise<void>;
  openLibraryFolder: () => Promise<void>;
  convert: ConvertView | null;
  openConvert: (files: File[]) => Promise<void>;
  startConvert: () => Promise<void>;
  cancelConvert: () => Promise<void>;
  closeConvert: () => void;
  paletteOpen: boolean;
  setPalette: (open: boolean) => void;
  managing: string | null; // id of the log whose drawer is open
  setManaging: (id: string | null) => void;
  recent: string[]; // channels plotted lately, newest first
  addDerivedAll: (name: string, expr: string, unit: string) => Promise<boolean>;
  removeDerivedAll: (name: string) => Promise<void>;
  canFiles: File[] | null; // CAN logs waiting to be told which DBC file decodes them
  dbcs: Dbc[];
  closeCan: () => void;
  addDbc: (file: File) => Promise<string | null>;
  deleteDbc: (id: string) => Promise<void>;
  importCan: (dbcIds: string[]) => Promise<void>;
  metrics: Metric[];
  setMetrics: (m: Metric[]) => void;
  lapParams: LapParams;
  setLapParams: (p: LapParams) => void;
  lapAxis: "distance" | "time";
  setLapAxis: (a: "distance" | "time") => void;
  views: SavedView[];
  viewsOpen: boolean;
  setViewsOpen: (open: boolean) => void;
  loadViews: () => Promise<void>;
  saveView: (name: string) => Promise<boolean>;
  openView: (v: SavedView) => void;
  setViewAuto: (id: string, on: boolean) => Promise<void>;
  deleteView: (id: string) => Promise<void>;
  importViewFile: (file: File) => Promise<void>;
  mode: "plots" | "review" | "analyse" | "live";
  setMode: (m: "plots" | "review" | "analyse" | "live") => void;
  review: Review | null;
  loadReview: () => Promise<void>;
  muteFinding: (key: string) => Promise<void>;
  restoreFinding: (key: string) => Promise<void>;
  saveLimits: (limits: Limit[]) => Promise<boolean>;
  openFinding: (f: Finding, o: ReviewOcc) => void;
  focus: [number, number] | null; // the stretch a finding points at, shaded on every plot
  tool: ToolId | null; // the open tool under Analyse, or null for the list of tools
  setTool: (t: ToolId | null) => void;
  view: [number, number] | null; // null = full extent
  rev: number; // bumped when data on the server changes (offset edits)
  message: { kind: "error" | "warn" | "info"; text: string } | null;
  refresh: () => Promise<void>;
  importFiles: (files: File[], dbcIds?: string[]) => Promise<void>;
  setOffset: (id: string, offset: number) => Promise<void>;
  setKind: (id: string, kind: Source["kind"]) => Promise<void>;
  arrange: (mode: "sequential" | "real") => Promise<void>;
  addDerived: (id: string, name: string, expr: string, unit: string) => Promise<boolean>;
  removeDerived: (id: string, name: string) => Promise<void>;
  removeSource: (id: string) => Promise<void>;
  addLane: (s: LaneSeries, overlay: boolean) => void;
  addChannelAll: (channel: string, overlay: boolean) => void;
  removeLane: (id: number) => void;
  setView: (v: [number, number] | null) => void;
  clearMessage: () => void;
};

let laneId = 1;

/** Keep every plot in step with the logs in view: add a log that joined, drop one that left. */
function syncLanes(lanes: Lane[], sources: Source[]): Lane[] {
  const ids = new Set(sources.map((s) => s.id));
  return lanes
    .map((l) => {
      const kept = l.series.filter((x) => ids.has(x.sourceId));
      const have = new Set(kept.map((x) => `${x.sourceId}|${x.channel}`));
      const add: LaneSeries[] = [];
      for (const ch of new Set(l.series.map((x) => x.channel)))
        for (const src of [...sources].sort((a, b) => a.offset_s - b.offset_s))
          if (src.channels.some((c) => c.name === ch) && !have.has(`${src.id}|${ch}`)) add.push({ sourceId: src.id, channel: ch });
      return add.length || kept.length !== l.series.length ? { ...l, series: [...kept, ...add] } : l;
    })
    .filter((l) => l.series.length > 0);
}

const RECENT_KEY = "let.recent";
const loadRecent = () => readJson<string[]>(RECENT_KEY, [], (v): v is string[] => Array.isArray(v) && v.every((x) => typeof x === "string")).slice(0, 6);
const saveRecent = (r: string[]) => writeJson(RECENT_KEY, r);

const guessKind = (name: string): Source["kind"] =>
  /hcu/i.test(name) ? "hcu" : /ecu|f88/i.test(name) ? "ecu" : "other";

const METRICS_KEY = "let.metrics";
const isMetric = (m: unknown): m is Metric => !!m && typeof (m as Metric).name === "string" && typeof (m as Metric).expr === "string";
const loadMetrics = () => readJson<Metric[]>(METRICS_KEY, [], (v): v is Metric[] => Array.isArray(v) && v.every(isMetric));

const isCan = (f: File) => /\.(asc|blf|trc)$/i.test(f.name);

export const useStore = create<State>((set, get) => ({
  canFiles: null,
  dbcs: [],
  closeCan: () => set({ canFiles: null }),
  addDbc: async (file) => {
    try {
      const d = await api.addDbc(file);
      set({ dbcs: await api.dbcs() });
      return d.id;
    } catch (e) {
      set({ message: { kind: "error", text: `Could not use ${file.name}. ${(e as Error).message}` } });
      return null;
    }
  },
  deleteDbc: async (id) => {
    try {
      await api.deleteDbc(id);
      set({ dbcs: await api.dbcs() });
    } catch (e) {
      set({ message: { kind: "error", text: `Could not remove the DBC file. ${(e as Error).message}` } });
    }
  },
  importCan: async (dbcIds) => {
    const files = get().canFiles ?? [];
    set({ canFiles: null });
    await get().importFiles(files, dbcIds);
  },
  metrics: loadMetrics(),
  setMetrics: (metrics) => {
    set({ metrics });
    writeJson(METRICS_KEY, metrics);
  },
  lapParams: { method: "auto" },
  setLapParams: (lapParams) => set({ lapParams }),
  lapAxis: "distance",
  setLapAxis: (lapAxis) => set({ lapAxis }),
  views: [],
  viewsOpen: false,
  setViewsOpen: (viewsOpen) => {
    set({ viewsOpen });
    if (viewsOpen) void get().loadViews();
  },
  loadViews: async () => {
    try {
      set({ views: await api.views() });
    } catch (e) {
      set({ message: { kind: "error", text: `Could not load your saved views. ${(e as Error).message}` } });
    }
  },
  saveView: async (name) => {
    const s = get();
    const payload: ViewPayload = {
      v: 1,
      mode: s.mode === "analyse" ? "analyse" : "plots", // a live screen is not something to come back to
      ...(s.mode === "analyse" && s.tool ? { tool: s.tool } : {}),
      lanes: s.lanes.map((l) => [...new Set(l.series.map((x) => x.channel))]),
      lap: { params: s.lapParams, axis: s.lapAxis },
      ...(s.metrics.length ? { summary: s.metrics } : {}),
    };
    try {
      const rec = await api.saveView(name, payload);
      await get().loadViews();
      set({ message: { kind: "info", text: `Saved the view "${rec.name}".` } });
      return true;
    } catch (e) {
      set({ message: { kind: "error", text: `Could not save the view. ${(e as Error).message}` } });
      return false;
    }
  },
  openView: (v) => {
    const p = v.payload;
    const known = new Set(get().sources.flatMap((s) => s.channels.map((c) => c.name)));
    const lanes = Array.isArray(p?.lanes) ? p.lanes.map((l) => (Array.isArray(l) ? l.filter((c) => typeof c === "string") : [])) : [];
    set({ lanes: [], view: null });
    let missing = 0;
    for (const lane of lanes) {
      const here = lane.filter((c) => known.has(c));
      missing += lane.length - here.length;
      here.forEach((c, i) => get().addChannelAll(c, i > 0));
    }
    if (Array.isArray(p?.summary)) get().setMetrics(p.summary.filter(isMetric));
    // views saved before the tools were gathered under Analyse used "analysis", "laps" and "pulls" as modes
    const old: Record<string, ToolId> = { analysis: "statistics", laps: "laps", pulls: "pulls" };
    const savedMode = String(p?.mode);
    const toTool = savedMode === "analyse" ? (isTool(p?.tool) ? p.tool : null) : (old[savedMode] ?? null);
    const mode = savedMode === "analyse" || savedMode in old ? "analyse" : "plots";
    set({
      mode,
      tool: toTool,
      viewsOpen: false,
      ...(p?.lap?.params?.method ? { lapParams: p.lap.params } : {}),
      ...(p?.lap?.axis === "time" || p?.lap?.axis === "distance" ? { lapAxis: p.lap.axis } : {}),
      message: {
        kind: "info",
        text: missing ? `Opened "${v.name}". ${missing} channel${missing > 1 ? "s were" : " was"} not in these logs and left out.` : `Opened "${v.name}".`,
      },
    });
  },
  setViewAuto: async (id, on) => {
    try {
      await api.setViewAuto(id, on);
      await get().loadViews();
    } catch (e) {
      set({ message: { kind: "error", text: (e as Error).message } });
    }
  },
  deleteView: async (id) => {
    try {
      await api.deleteView(id);
      await get().loadViews();
    } catch (e) {
      set({ message: { kind: "error", text: (e as Error).message } });
    }
  },
  importViewFile: async (file) => {
    try {
      const j = JSON.parse(await file.text());
      if (!j || typeof j.name !== "string" || typeof j.payload !== "object" || j.payload?.v !== 1) throw new Error("This is not a view file.");
      const rec = await api.saveView(j.name, j.payload);
      await get().loadViews();
      get().openView(rec);
    } catch (e) {
      set({ message: { kind: "error", text: `Could not open that file. ${(e as Error).message}` } });
    }
  },
  sources: [],
  lanes: [],
  view: null,
  mode: "plots",
  setMode: (mode) => set({ mode }),
  review: null,
  loadReview: async () => {
    if (!get().sources.length) {
      set({ review: null });
      return;
    }
    try {
      set({ review: await api.review() });
    } catch (e) {
      set({ message: { kind: "error", text: `Could not check the logs. ${(e as Error).message}` } });
    }
  },
  muteFinding: async (key) => {
    try {
      set({ review: await api.muteFinding(key) });
    } catch (e) {
      set({ message: { kind: "error", text: `Could not mark that as normal. ${(e as Error).message}` } });
    }
  },
  restoreFinding: async (key) => {
    try {
      set({ review: await api.restoreFinding(key) });
    } catch (e) {
      set({ message: { kind: "error", text: `Could not bring that back. ${(e as Error).message}` } });
    }
  },
  saveLimits: async (limits) => {
    try {
      set({ review: await api.setLimits(limits) });
      return true;
    } catch (e) {
      set({ message: { kind: "error", text: `Limits not saved. ${(e as Error).message}` } });
      return false;
    }
  },
  // Show a finding where it happened: plot the channels it is about and zoom to that moment.
  openFinding: (f, o) => {
    const src = get().sources.find((s) => s.id === o.log_id);
    if (!src) return;
    for (const ch of f.channels.slice(0, 3)) {
      const plotted = get().lanes.some((l) => l.series.some((x) => x.channel === ch));
      if (!plotted && src.channels.some((c) => c.name === ch)) get().addChannelAll(ch, false);
    }
    const pad = Math.max(1.5, (o.t1 - o.t0) * 0.5);
    set({
      mode: "plots",
      focus: [src.offset_s + o.t0, src.offset_s + Math.max(o.t1, o.t0)],
      view: [src.offset_s + Math.max(o.t0 - pad, 0), src.offset_s + Math.min(o.t1 + pad, src.duration_s)],
    });
  },
  focus: null,
  tool: null,
  setTool: (tool) => set({ tool, mode: "analyse" }),
  library: [],
  libraryOpen: false,
  access: { local: true, sharing: false },
  loadAccess: async () => {
    try {
      set({ access: await api.health() });
    } catch {
      /* the first real request reports a missing backend */
    }
  },
  shareOpen: false,
  setShareOpen: (shareOpen) => set({ shareOpen }),
  railOpen: false,
  setRailOpen: (railOpen) => set({ railOpen }),
  setLibraryOpen: (libraryOpen) => {
    set({ libraryOpen });
    if (libraryOpen) void get().loadLibrary();
  },
  loadLibrary: async () => {
    try {
      set({ library: await api.library() });
    } catch (e) {
      set({ message: { kind: "error", text: `Could not load the library. ${(e as Error).message}` } });
    }
  },
  addFromLibrary: async (ids) => {
    try {
      for (const id of ids) await api.libraryOpen(id);
      await get().refresh();
      if (get().sources.length > 1) await get().arrange("sequential");
      await get().loadLibrary();
      set({
        libraryOpen: false,
        message: { kind: "info", text: `Added ${ids.length} log${ids.length > 1 ? "s" : ""} from the library.` },
      });
    } catch (e) {
      set({ message: { kind: "error", text: `Could not add from the library. ${(e as Error).message}` } });
    }
  },
  closeLog: async (id) => {
    try {
      await api.libraryClose(id);
      set((s) => ({
        lanes: s.lanes
          .map((l) => ({ ...l, series: l.series.filter((x) => x.sourceId !== id) }))
          .filter((l) => l.series.length > 0),
        view: null,
      }));
      await get().refresh();
      await get().loadLibrary();
    } catch (e) {
      set({ message: { kind: "error", text: (e as Error).message } });
    }
  },
  deleteForever: async (id) => {
    await get().removeSource(id);
    await get().loadLibrary();
  },
  openLibraryFolder: async () => {
    try {
      await api.libraryFolder();
    } catch (e) {
      set({ message: { kind: "error", text: `Could not open the folder. ${(e as Error).message}` } });
    }
  },

  convert: null,

  openConvert: async (files) => {
    try {
      const status = await api.convertStatus();
      set({ convert: { phase: "ready", files, status } });
    } catch (e) {
      set({ convert: { phase: "ready", files, error: `Could not reach the backend. ${(e as Error).message}` } });
    }
  },

  startConvert: async () => {
    const c = get().convert;
    if (!c) return;
    try {
      let job = await api.convert(c.files);
      set({ convert: { ...c, phase: "running", job, error: undefined } });
      while (job.state === "running") {
        await new Promise((r) => setTimeout(r, 700));
        job = await api.convertJob(job.id);
        set((s) => (s.convert ? { convert: { ...s.convert, job } } : s));
      }
      await get().refresh();
      void get().loadLibrary();
      if (get().sources.length > 1 && job.imported > 0) await get().arrange("sequential");
      set((s) => (s.convert ? { convert: { ...s.convert, phase: "finished", job } } : s));
    } catch (e) {
      set((s) => (s.convert ? { convert: { ...s.convert, phase: "ready", error: (e as Error).message } } : s));
    }
  },

  cancelConvert: async () => {
    const job = get().convert?.job;
    if (!job) return;
    try {
      await api.convertCancel(job.id);
    } catch (e) {
      set({ message: { kind: "error", text: `Could not stop the conversion. ${(e as Error).message}` } });
    }
  },

  closeConvert: () => set({ convert: null }),

  paletteOpen: false,
  setPalette: (paletteOpen) => set({ paletteOpen }),
  managing: null,
  setManaging: (managing) => set({ managing }),
  recent: loadRecent(),

  addDerivedAll: async (name, expr, unit) => {
    const srcs = get().sources;
    let done = 0;
    let firstErr = "";
    for (const s of srcs) {
      try {
        await api.addDerived(s.id, { name, expr, unit });
        done += 1;
      } catch (e) {
        if (!firstErr) firstErr = (e as Error).message;
      }
    }
    await get().refresh();
    if (done === 0) {
      set({ message: { kind: "error", text: `Calculated channel not added. ${firstErr}` } });
      return false;
    }
    set({
      message: {
        kind: "info",
        text: done === srcs.length ? `Added ${name}.` : `Added ${name} to ${done} of ${srcs.length} logs. ${firstErr}`,
      },
    });
    return true;
  },

  removeDerivedAll: async (name) => {
    for (const s of get().sources) {
      if (!s.channels.some((c) => c.name === name && c.derived)) continue;
      try {
        await api.removeDerived(s.id, name);
      } catch (e) {
        set({ message: { kind: "error", text: (e as Error).message } });
      }
    }
    set((st) => ({
      lanes: st.lanes
        .map((l) => ({ ...l, series: l.series.filter((x) => x.channel !== name) }))
        .filter((l) => l.series.length > 0),
    }));
    await get().refresh();
  },
  rev: 0,
  message: null,

  refresh: async () => {
    try {
      const sources = await api.sources();
      set((s) => ({ sources, lanes: syncLanes(s.lanes, sources) }));
      void get().loadReview();
    } catch (e) {
      set({ message: { kind: "error", text: `Could not reach the backend: ${(e as Error).message}` } });
    }
  },

  importFiles: async (all, dbcIds = []) => {
    const lrd = all.filter((f) => /\.lrd$/i.test(f.name));
    const waiting = dbcIds.length === 0 ? all.filter(isCan) : [];
    const files = all.filter((f) => !/\.lrd$/i.test(f.name) && !waiting.includes(f));
    if (lrd.length) await get().openConvert(lrd);
    if (waiting.length) {
      try {
        set({ dbcs: await api.dbcs() });
      } catch (e) {
        set({ message: { kind: "error", text: `Could not load your DBC files. ${(e as Error).message}` } });
      }
      set({ canFiles: waiting });
    }
    for (const f of files) {
      try {
        const src = await api.importFile(f, guessKind(f.name), dbcIds);
        const notes = src.reused ? [] : src.warnings;
        set({
          message: {
            // a guess the importer had to make can change what every plot means, so it stays until dismissed
            kind: notes.length ? "warn" : "info",
            text: src.reused
              ? `${f.name} was already in your library, so that log was opened instead of copied.`
              : `Imported ${f.name}: ${src.rows.toLocaleString()} rows, ${src.channels.length} channels.` +
                (notes.length ? ` Check this: ${notes[0]}${notes.length > 1 ? ` (and ${notes.length - 1} more under Manage, Import notes)` : ""}` : ""),
          },
        });
      } catch (e) {
        set({ message: { kind: "error", text: `Could not import ${f.name}. ${(e as Error).message}` } });
      }
    }
    await get().refresh();
    // a new log on an empty screen opens in the view marked to open by itself
    if (files.length && get().lanes.length === 0) {
      try {
        const auto = (await api.views()).find((v) => v.auto);
        if (auto) get().openView(auto);
      } catch {
        /* the log is open either way; the views list reports its own errors */
      }
    }
  },

  setOffset: async (id, offset) => {
    try {
      await api.patch(id, { offset_s: offset });
      await get().refresh();
      set((s) => ({ rev: s.rev + 1 }));
    } catch (e) {
      set({ message: { kind: "error", text: `Could not set the offset. ${(e as Error).message}` } });
    }
  },

  setKind: async (id, kind) => {
    try {
      await api.patch(id, { kind });
      await get().refresh();
    } catch (e) {
      set({ message: { kind: "error", text: (e as Error).message } });
    }
  },

  arrange: async (mode) => {
    try {
      await api.arrange(mode);
      await get().refresh();
      set((s) => ({ rev: s.rev + 1, view: null }));
    } catch (e) {
      set({ message: { kind: "error", text: `Could not arrange the logs. ${(e as Error).message}` } });
    }
  },

  addDerived: async (id, name, expr, unit) => {
    try {
      await api.addDerived(id, { name, expr, unit });
      await get().refresh();
      set({ message: { kind: "info", text: `Added math channel ${name}.` } });
      return true;
    } catch (e) {
      set({ message: { kind: "error", text: `Math channel not added. ${(e as Error).message}` } });
      return false;
    }
  },

  removeDerived: async (id, name) => {
    try {
      await api.removeDerived(id, name);
      set((s) => ({
        lanes: s.lanes
          .map((l) => ({ ...l, series: l.series.filter((x) => !(x.sourceId === id && x.channel === name)) }))
          .filter((l) => l.series.length > 0),
      }));
      await get().refresh();
    } catch (e) {
      set({ message: { kind: "error", text: (e as Error).message } });
    }
  },

  removeSource: async (id) => {
    try {
      await api.remove(id);
      set((s) => ({
        lanes: s.lanes
          .map((l) => ({ ...l, series: l.series.filter((x) => x.sourceId !== id) }))
          .filter((l) => l.series.length > 0),
      }));
      await get().refresh();
    } catch (e) {
      set({ message: { kind: "error", text: (e as Error).message } });
    }
  },

  addLane: (series, overlay) =>
    set((s) => {
      const last = s.lanes[s.lanes.length - 1];
      if (overlay && last) {
        if (last.series.some((x) => x.sourceId === series.sourceId && x.channel === series.channel)) return s;
        return { lanes: [...s.lanes.slice(0, -1), { ...last, series: [...last.series, series] }] };
      }
      return { lanes: [...s.lanes, { id: laneId++, series: [series] }] };
    }),

  addChannelAll: (channel, overlay) =>
    set((s) => {
      // one trace group across every log that has the channel, in timeline order
      const list: LaneSeries[] = [...s.sources]
        .filter((src) => src.channels.some((c) => c.name === channel))
        .sort((a, b) => a.offset_s - b.offset_s)
        .map((src) => ({ sourceId: src.id, channel }));
      if (!list.length) return s;
      const recent = [channel, ...s.recent.filter((x) => x !== channel)].slice(0, 6);
      saveRecent(recent);
      const last = s.lanes[s.lanes.length - 1];
      if (overlay && last) {
        const fresh = list.filter((n) => !last.series.some((x) => x.sourceId === n.sourceId && x.channel === n.channel));
        return { recent, lanes: [...s.lanes.slice(0, -1), { ...last, series: [...last.series, ...fresh] }] };
      }
      return { recent, lanes: [...s.lanes, { id: laneId++, series: list }] };
    }),

  removeLane: (id) => set((s) => ({ lanes: s.lanes.filter((l) => l.id !== id) })),
  setView: (view) => set(view ? { view } : { view, focus: null }),
  clearMessage: () => set({ message: null }),
}));

/** Full time extent across all sources, including their alignment offsets. */
export function extentOf(sources: Source[]): [number, number] {
  if (!sources.length) return [0, 1];
  const lo = Math.min(...sources.map((s) => s.offset_s));
  const hi = Math.max(...sources.map((s) => s.offset_s + s.duration_s));
  return [Math.min(lo, 0), Math.max(hi, lo + 1)];
}
