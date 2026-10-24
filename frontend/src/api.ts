import type { ConvertJob, ConvertStatus, LibraryEntry, Source } from "./store";

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

export const api = {
  sources: () => fetch("/api/sources").then((r) => parse<Source[]>(r)),

  importFile: (file: File, kind: string) => {
    const form = new FormData();
    form.append("file", file);
    form.append("kind", kind);
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
      samples: number;
    }>(`/api/sources/${id}/spectrum`, { channel, t0, t1 }),

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
