import type { Source } from "./store";

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
