import type { ConvertJob, ConvertStatus, LibraryEntry, Metric, SavedView, Source, ViewPayload } from "./store";

async function parse<T>(r: Response): Promise<T> {
  if (!r.ok) {
    let detail = `${r.status} ${r.statusText}`;
    try {
      const body = await r.json();
      if (typeof body.detail === "string") detail = body.detail;
    } catch {
      /* keep the status text */
    }
    throw new Error(detail);
  }
  return (r.status === 204 ? undefined : await r.json()) as T;
}

function getJson<T>(path: string, params: Record<string, string | number | undefined>) {
  const q = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) if (v !== undefined) q.set(k, String(v));
  return fetch(`${path}?${q}`).then((r) => parse<T>(r));
}

export type Severity = "high" | "medium" | "low";
export type ReviewOcc = { log_id: string; label: string; t0: number; t1: number; note: string; fits?: boolean };
export type Finding = {
  key: string;
  kind: "link" | "report" | "stuck" | "unused" | "dropout" | "gap" | "limit";
  severity: Severity;
  title: string;
  detail: string;
  channels: string[];
  count: number;
  occurrences: ReviewOcc[];
  evidence?: { events: number; followed: number; chance: number };
};
export type Limit = {
  id?: string;
  channel: string;
  op: ">" | "<";
  value: number;
  seconds: number;
  severity: Severity;
  message: string;
  running_only: boolean;
};
export type Review = {
  findings: Finding[];
  muted: Finding[];
  notes: string[];
  checked: { logs: number; channels: number };
  limits: Limit[];
};

export type LapParams = {
  method: "auto" | "reset" | "change" | "trigger" | "distance" | "manual";
  channel?: string;
  threshold?: number;
  length_m?: number;
  times?: string;
  min_lap_s?: number;
};
export type LapRow = {
  n: number;
  t_start: number;
  t_end: number;
  duration_s: number;
  distance_m?: number;
  max_kmh?: number;
  avg_kmh?: number;
  valid: boolean;
  best: boolean;
  delta_best_s: number;
};
export type LapTable = {
  found_by: string;
  speed_channel: string | null;
  has_position: boolean;
  boundaries: number[];
  laps: LapRow[];
  best: number | null;
  median_s: number | null;
};
export type LapView = {
  axis: "distance" | "time";
  x: number[];
  reference: number;
  best: number | null;
  units: Record<string, string>;
  laps: { n: number; duration_s: number; channels: Record<string, (number | null)[]>; delta_s?: (number | null)[] }[];
};
export type LapCompare = {
  axis: "distance" | "time";
  x: number[];
  reference: number;
  reference_log: string;
  best: { log: string; n: number };
  units: Record<string, string>;
  logs: Record<string, { label: string; started_at: string | null }>;
  skipped: { id: string; reason: string }[];
  laps: { log: string; n: number; duration_s: number; channels: Record<string, (number | null)[]>; delta_s?: (number | null)[] }[];
};
export type PullRow = {
  n: number;
  t_start: number;
  t_end: number;
  duration_s: number;
  rpm_start: number;
  rpm_end: number;
  rpm_peak: number;
  speed_start_kmh?: number;
  speed_end_kmh?: number;
  loaded?: boolean;
};
export type Pulls = {
  logs: Record<string, { label: string; started_at: string | null; pulls: PullRow[]; speed_channel: string | null; units: Record<string, string> }>;
  skipped: { id: string; reason: string }[];
  units: Record<string, string>;
  compare: {
    rpm: number[];
    power_unit: "kW" | "index";
    peaks: { log: string; n: number; peak_power?: number; rpm_at_peak_power?: number; peak_torque?: number; rpm_at_peak_torque?: number }[];
    curves: { log: string; n: number; channels: Record<string, (number | null)[]> }[];
  } | null;
};

export type Heatmap = {
  xedges: number[];
  yedges: number[];
  counts: number[][];
  values: (number | null)[][];
  vmin: number | null;
  vmax: number | null;
  total: number;
  agg: string;
  logs: string[];
  skipped: { id: string; label: string; reason: string }[];
  dt_s: number;
};

export type SummaryData = {
  metrics: { name: string; expr: string; agg: string; where: string; unit: string }[];
  rows: { id: string; label: string; started_at: string | null; values: Record<string, number | null> }[];
  errors: Record<string, Record<string, string>>;
};

export type Dbc = { id: string; name: string; messages: number; signals: number };

export type LiveChannel = { name: string; unit: string; last: number | null };
export type LiveStatus = {
  state: "running" | "stopped";
  source: { kind: string; label: string; options: Record<string, unknown> } | null;
  error: string | null;
  rejected: number;
  last_reject: string | null;
  rows: number;
  kept: number;
  capacity: number;
  rate_hz: number | null;
  age_s: number | null;
  time_s: number | null;
  channels: LiveChannel[];
};
export type LiveSourceKind = "simulator" | "replay" | "udp" | "serial" | "push";

export type LapStats = {
  sectors: number;
  ideal_s: number | null;
  best_sectors: { time_s: number; log: string; n: number }[];
  units: Record<string, string>;
  laps: {
    log: string;
    n: number;
    duration_s: number;
    valid: boolean;
    metrics: Record<string, { min: number; max: number; mean: number } | null>;
    sectors: number[] | null;
  }[];
};
export type Track = {
  source: "gps" | "course" | "lateral g";
  estimated: boolean;
  t: number[];
  dist?: number[];
  x: (number | null)[];
  y: (number | null)[];
  color?: (number | null)[];
  color_unit?: string;
  boundaries: number[];
  best: number | null;
  laps: { n: number; t_start: number; t_end: number }[];
};

const lapQuery = (p: LapParams) => ({
  method: p.method,
  channel: p.channel || undefined,
  threshold: p.threshold,
  length_m: p.length_m,
  times: p.times || undefined,
  min_lap_s: p.min_lap_s,
});

export const api = {
  dbcs: () => getJson<Dbc[]>("/api/can/dbc", {}),
  addDbc: (file: File) => {
    const form = new FormData();
    form.append("file", file);
    return fetch("/api/can/dbc", { method: "POST", body: form }).then((r) => parse<Dbc>(r));
  },
  deleteDbc: (id: string) => fetch(`/api/can/dbc/${id}`, { method: "DELETE" }).then((r) => parse<void>(r)),

  summary: (ids: string[], metrics: Metric[], t0?: number, t1?: number) =>
    fetch("/api/summary", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ sources: ids, metrics: metrics.map(({ name, expr, agg, where, unit }) => ({ name, expr, agg, where, unit })), t0, t1 }),
    }).then((r) => parse<SummaryData>(r)),

  heatmap: (
    ids: string[],
    o: { x: string; y: string; value?: string; agg: string; nx: number; ny: number; minCount: number; t0?: number; t1?: number },
  ) =>
    getJson<Heatmap>("/api/heatmap", {
      sources: ids.join(","),
      x: o.x,
      y: o.y,
      value: o.value,
      agg: o.agg,
      nx: o.nx,
      ny: o.ny,
      min_count: o.minCount,
      t0: o.t0,
      t1: o.t1,
    }),

  pulls: (ids: string[], channels: string[], selected: string[], o: { slope: number; span: number; bin: number; massKg?: number }) =>
    getJson<Pulls>("/api/pulls", {
      sources: ids.join(","),
      channels: channels.join(","),
      selected: selected.join(",") || undefined,
      slope: o.slope,
      min_span: o.span,
      bin: o.bin,
      mass_kg: o.massKg,
    }),

  liveStatus: () => getJson<LiveStatus>("/api/live/status", {}),
  livePorts: () => getJson<{ port: string; description: string }[]>("/api/live/ports", {}),
  liveStart: (source: LiveSourceKind, options: Record<string, unknown>) =>
    fetch("/api/live/start", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ source, options }),
    }).then((r) => parse<LiveStatus>(r)),
  liveStop: () => fetch("/api/live/stop", { method: "POST" }).then((r) => parse<LiveStatus>(r)),
  liveClear: () => fetch("/api/live/clear", { method: "POST" }).then((r) => parse<LiveStatus>(r)),
  liveSave: (label: string) =>
    fetch("/api/live/save", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ label }),
    }).then((r) => parse<Source>(r)),
  liveWindow: (channels: string[], seconds: number) =>
    getJson<{ t: number[]; v: Record<string, (number | null)[]> }>("/api/live/window", {
      channels: channels.join(","),
      seconds,
      points: 1500,
    }),

  views: () => getJson<SavedView[]>("/api/workspaces", {}),
  saveView: (name: string, payload: ViewPayload) =>
    fetch("/api/workspaces", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name, payload }),
    }).then((r) => parse<SavedView>(r)),
  deleteView: (id: string) => fetch(`/api/workspaces/${id}`, { method: "DELETE" }).then((r) => parse<void>(r)),

  laps: (id: string, p: LapParams) => getJson<LapTable>(`/api/sources/${id}/laps`, lapQuery(p)),

  lapView: (id: string, p: LapParams, channels: string[], selected: number[], ref: number | null, axis: string) =>
    getJson<LapView>(`/api/sources/${id}/lapview`, {
      ...lapQuery(p),
      channels: channels.join(","),
      selected: selected.join(",") || undefined,
      ref: ref ?? undefined,
      axis,
    }),

  lapStats: (ids: string[], p: LapParams, channels: string[], selected: string[], sectors: number) =>
    getJson<LapStats>("/api/lapstats", {
      ...lapQuery(p),
      sources: ids.join(","),
      channels: channels.join(","),
      selected: selected.join(",") || undefined,
      sectors,
    }),

  lapCompare: (ids: string[], p: LapParams, channels: string[], selected: string[], ref: string | null, axis: string) =>
    getJson<LapCompare>("/api/lapcompare", {
      ...lapQuery(p),
      sources: ids.join(","),
      channels: channels.join(","),
      selected: selected.join(",") || undefined,
      ref: ref ?? undefined,
      axis,
    }),

  track: (id: string, p: LapParams, color: string | undefined, mirror: boolean) =>
    getJson<Track>(`/api/sources/${id}/track`, { ...lapQuery(p), color, mirror: mirror ? "true" : undefined }),

  sources: () => fetch("/api/sources").then((r) => parse<Source[]>(r)),

  importFile: (file: File, kind: string, dbcIds: string[] = []) => {
    const form = new FormData();
    form.append("file", file);
    form.append("kind", kind);
    if (dbcIds.length) form.append("dbc", dbcIds.join(","));
    return fetch("/api/sources", { method: "POST", body: form }).then((r) => parse<Source>(r));
  },

  patch: (id: string, body: Partial<Pick<Source, "label" | "kind" | "offset_s">>) =>
    fetch(`/api/sources/${id}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }).then((r) => parse<Source>(r)),

  arrange: (mode: "sequential" | "real") =>
    fetch("/api/arrange", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ mode, gap_s: mode === "sequential" ? 1 : 0 }),
    }).then((r) => parse<Source[]>(r)),

  addDerived: (id: string, body: { name: string; expr: string; unit: string }) =>
    fetch(`/api/sources/${id}/derived`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }).then((r) => parse<Source>(r)),

  removeDerived: (id: string, name: string) =>
    fetch(`/api/sources/${id}/derived/${encodeURIComponent(name)}`, { method: "DELETE" }).then((r) =>
      parse<Source>(r),
    ),

  stats: (id: string, channels: string[], t0?: number, t1?: number) =>
    getJson<{
      t0: number;
      t1: number;
      channels: Record<string, Record<string, number>>;
    }>(`/api/sources/${id}/stats`, { channels: channels.join(","), t0, t1 }),

  histogram: (id: string, channel: string, bins: number, t0?: number, t1?: number) =>
    getJson<{ edges: number[]; counts: number[]; total: number }>(`/api/sources/${id}/histogram`, {
      channel,
      bins,
      t0,
      t1,
    }),

  spectrum: (id: string, channel: string, t0?: number, t1?: number) =>
    getJson<{
      freq_hz: number[];
      amplitude: number[];
      peaks: { freq_hz: number; amplitude: number }[];
      sample_rate_hz: number;
      native_hz: number | null;
      samples: number;
    }>(`/api/sources/${id}/spectrum`, { channel, t0, t1 }),

  review: () => getJson<Review>("/api/review", {}),
  muteFinding: (key: string) =>
    fetch(`/api/review/mute?${new URLSearchParams({ key })}`, { method: "POST" }).then((r) => parse<Review>(r)),
  restoreFinding: (key: string) =>
    fetch(`/api/review/mute?${new URLSearchParams({ key })}`, { method: "DELETE" }).then((r) => parse<Review>(r)),
  setLimits: (limits: Limit[]) =>
    fetch("/api/review/limits", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ limits }),
    }).then((r) => parse<Review>(r)),

  scatter: (id: string, x: string, y: string, t0?: number, t1?: number) =>
    getJson<{ t: number[]; x: number[]; y: number[]; points: number; correlation: number | null }>(
      `/api/sources/${id}/scatter`,
      { x, y, t0, t1 },
    ),

  addRule: (id: string, body: { name: string; expr: string; min_duration_s: number; merge_gap_s: number }) =>
    fetch(`/api/sources/${id}/rules`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }).then((r) => parse<Source>(r)),

  removeRule: (id: string, name: string) =>
    fetch(`/api/sources/${id}/rules/${encodeURIComponent(name)}`, { method: "DELETE" }).then((r) =>
      parse<Source>(r),
    ),

  events: (id: string) =>
    getJson<{ rule: string; t_start: number; t_end: number; duration_s: number; samples: number }[]>(
      `/api/sources/${id}/events`,
      {},
    ),

  library: () => getJson<LibraryEntry[]>("/api/library", {}),
  libraryOpen: (id: string) => fetch(`/api/library/${id}/open`, { method: "POST" }).then((r) => parse<Source>(r)),
  libraryClose: (id: string) => fetch(`/api/library/${id}/close`, { method: "POST" }).then((r) => parse<Source>(r)),
  libraryFolder: () => fetch("/api/library/folder/open", { method: "POST" }).then((r) => parse<{ path: string }>(r)),

  convertStatus: () => getJson<ConvertStatus>("/api/convert/status", {}),

  convert: (files: File[]) => {
    const form = new FormData();
    for (const f of files) form.append("files", f);
    return fetch("/api/convert", { method: "POST", body: form }).then((r) => parse<ConvertJob>(r));
  },

  convertJob: (id: string) => getJson<ConvertJob>(`/api/convert/${id}`, {}),

  convertCancel: (id: string) =>
    fetch(`/api/convert/${id}/cancel`, { method: "POST" }).then((r) => parse<ConvertJob>(r)),

  remove: (id: string) => fetch(`/api/sources/${id}`, { method: "DELETE" }).then((r) => parse<void>(r)),

  signals: (id: string, channels: string[], t0: number, t1: number, px: number) => {
    const q = new URLSearchParams({
      channels: channels.join(","),
      t0: String(t0),
      t1: String(t1),
      px: String(px),
    });
    return fetch(`/api/sources/${id}/signals?${q}`).then((r) =>
      parse<{
        offset_s: number;
        full_resolution: boolean;
        channels: Record<string, { t: number[]; v: number[] }>;
      }>(r),
    );
  },
};
