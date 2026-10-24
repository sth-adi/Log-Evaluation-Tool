import { useEffect, useRef, useState } from "react";
import { useStore, type SavedView } from "../store";

const when = (iso: string) =>
  new Date(iso).toLocaleString("en-GB", { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" });

const summary = (v: SavedView) => {
  const n = v.payload.lanes?.length ?? 0;
  const tab = v.payload.mode === "laps" ? "Laps" : v.payload.mode === "analysis" ? "Analysis" : "Plots";
  return `${tab}${v.payload.mode === "plots" || n ? `, ${n} plot${n === 1 ? "" : "s"}` : ""}`;
};

/** Save what is on screen under a name, open it again later, or hand it to someone as a file. */
export function Views() {
  const open = useStore((s) => s.viewsOpen);
  const setOpen = useStore((s) => s.setViewsOpen);
  const views = useStore((s) => s.views);
  const saveView = useStore((s) => s.saveView);
  const openView = useStore((s) => s.openView);
  const deleteView = useStore((s) => s.deleteView);
  const importViewFile = useStore((s) => s.importViewFile);
  const [name, setName] = useState("");
  const [sure, setSure] = useState<string | null>(null);
  const file = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (!open) return;
    setName("");
    setSure(null);
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && setOpen(false);
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, setOpen]);

  if (!open) return null;

  const save = async () => {
    if (name.trim() && (await saveView(name.trim()))) setName("");
  };
  const download = (v: SavedView) => {
    const blob = new Blob([JSON.stringify({ app: "log-evaluation-tool", name: v.name, payload: v.payload }, null, 2)], { type: "application/json" });
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = `${v.name.replace(/[^\w.-]+/g, "_")}.letview.json`;
    a.click();
    URL.revokeObjectURL(a.href);
  };

  return (
    <div className="scrim top" onMouseDown={(e) => e.target === e.currentTarget && setOpen(false)}>
      <div className="dialog views" role="dialog" aria-modal="true" aria-label="Views">
        <header>
          <h2>Views</h2>
          <p className="muted">
            A view is the plots, tab and lap settings you have set up. Save one to come back to it, or send the file to a teammate. It works with whichever logs are open.
          </p>
        </header>

        <form
          className="view-save"
          onSubmit={(e) => {
            e.preventDefault();
            void save();
          }}
        >
          <input type="text" value={name} onChange={(e) => setName(e.target.value)} placeholder="Name this view, for example Brake test" aria-label="View name" maxLength={80} />
          <button className="btn primary" type="submit" disabled={!name.trim()}>
            Save current view
          </button>
        </form>

        <ul className="view-list">
          {views.length === 0 && <li className="lib-empty">No saved views yet.</li>}
          {views.map((v) => (
            <li key={v.id}>
              <div className="lib-main">
                <span className="lib-name">{v.name}</span>
                <span className="lib-meta">
                  {summary(v)}, saved {when(v.saved_at)}
                </span>
              </div>
              <span className="lib-act">
                <button className="btn sm" onClick={() => openView(v)}>
                  Open
                </button>
                <button className="btn sm ghost" onClick={() => download(v)} title="Save this view as a file to share">
                  Export
                </button>
                {sure === v.id ? (
                  <button
                    className="btn sm danger"
                    onClick={() => {
                      void deleteView(v.id);
                      setSure(null);
                    }}
                  >
                    Delete
                  </button>
                ) : (
                  <button className="icon-btn" onClick={() => setSure(v.id)} aria-label={`Delete the view ${v.name}`} title="Delete this view">
                    <svg width="16" height="16" viewBox="0 0 16 16" aria-hidden>
                      <path d="M3 4.5h10M6.5 4.5V3h3v1.5M4.5 4.5l.6 8h5.8l.6-8" />
                    </svg>
                  </button>
                )}
              </span>
            </li>
          ))}
        </ul>

        <footer>
          <button className="btn ghost" onClick={() => file.current?.click()}>
            Open a view file
          </button>
          <input
            ref={file}
            type="file"
            accept=".json,application/json"
            hidden
            onChange={(e) => {
              const f = e.target.files?.[0];
              e.target.value = "";
              if (f) void importViewFile(f);
            }}
          />
          <div className="spacer" />
          <button className="btn" onClick={() => setOpen(false)}>
            Close
          </button>
        </footer>
      </div>
    </div>
  );
}
