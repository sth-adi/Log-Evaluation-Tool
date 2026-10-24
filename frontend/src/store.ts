import { create } from "zustand";
import { api } from "./api";

export type Channel = {
  name: string;
  unit: string;
  min: number;
  max: number;
  states?: Record<string, string>; // text channels: value (index) to label
  derived?: boolean; // a math channel
  expr?: string;
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

export type LaneSeries = { sourceId: string; channel: string };
export type Lane = { id: number; series: LaneSeries[] };

type State = {
  sources: Source[];
  lanes: Lane[];
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
  mode: "plots" | "analysis";
  setMode: (m: "plots" | "analysis") => void;
  view: [number, number] | null; // null = full extent
  rev: number; // bumped when data on the server changes (offset edits)
  message: { kind: "error" | "info"; text: string } | null;
  refresh: () => Promise<void>;
  importFiles: (files: File[]) => Promise<void>;
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

const RECENT_KEY = "let.recent";
function loadRecent(): string[] {
  try {
    const v = JSON.parse(localStorage.getItem(RECENT_KEY) ?? "[]");
    return Array.isArray(v) ? v.filter((x) => typeof x === "string").slice(0, 6) : [];
  } catch {
    return [];
  }
}
function saveRecent(r: string[]) {
  try {
    localStorage.setItem(RECENT_KEY, JSON.stringify(r));
  } catch {
    /* private window or blocked storage: the list just will not persist */
  }
}

const guessKind = (name: string): Source["kind"] =>
  /hcu/i.test(name) ? "hcu" : /ecu|f88/i.test(name) ? "ecu" : "other";

export const useStore = create<State>((set, get) => ({
  sources: [],
  lanes: [],
  view: null,
  mode: "plots",
  setMode: (mode) => set({ mode }),
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
      if (get().sources.length > 1 && job.imported > 0) await get().arrange("sequential");
      set((s) => (s.convert ? { convert: { ...s.convert, phase: "finished", job } } : s));
    } catch (e) {
      set((s) => (s.convert ? { convert: { ...s.convert, phase: "ready", error: (e as Error).message } } : s));
    }
  },

  cancelConvert: async () => {
    const job = get().convert?.job;
    if (job) await api.convertCancel(job.id).catch(() => undefined);
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
      set({ sources: await api.sources() });
    } catch (e) {
      set({ message: { kind: "error", text: `Could not reach the backend: ${(e as Error).message}` } });
    }
  },

  importFiles: async (all) => {
    const lrd = all.filter((f) => /\.lrd$/i.test(f.name));
    const files = all.filter((f) => !/\.lrd$/i.test(f.name));
    if (lrd.length) await get().openConvert(lrd);
    for (const f of files) {
      try {
        const src = await api.importFile(f, guessKind(f.name));
        set({
          message: {
            kind: "info",
            text: `Imported ${f.name}: ${src.rows.toLocaleString()} rows, ${src.channels.length} channels.`,
          },
        });
      } catch (e) {
        set({ message: { kind: "error", text: `Could not import ${f.name}. ${(e as Error).message}` } });
      }
    }
    await get().refresh();
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
  setView: (view) => set({ view }),
  clearMessage: () => set({ message: null }),
}));

/** Full time extent across all sources, including their alignment offsets. */
export function extentOf(sources: Source[]): [number, number] {
  if (!sources.length) return [0, 1];
  const lo = Math.min(...sources.map((s) => s.offset_s));
  const hi = Math.max(...sources.map((s) => s.offset_s + s.duration_s));
  return [Math.min(lo, 0), Math.max(hi, lo + 1)];
}
