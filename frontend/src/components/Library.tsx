import { useEffect, useMemo, useState } from "react";
import { useStore, type LibraryEntry } from "../store";
import { ImportButton } from "./ImportButton";
import { shortLabel } from "./LogRail";

const day = (e: LibraryEntry) => (e.started_at ?? e.imported_at).slice(0, 10);
const clock = (e: LibraryEntry) => (e.started_at ? e.started_at.slice(11, 19) : "No start time");
const dur = (s: number) => (s >= 60 ? `${Math.floor(s / 60)} min ${Math.round(s % 60)} s` : `${s.toFixed(1)} s`);
const size = (n: number) => (n >= 1e6 ? `${(n / 1e6).toFixed(1)} MB` : `${Math.max(1, Math.round(n / 1e3))} KB`);

/** Every processed log in one place. Pick the ones to look at; nothing is converted twice. */
export function Library() {
  const open = useStore((s) => s.libraryOpen);
  const setOpen = useStore((s) => s.setLibraryOpen);
  const entries = useStore((s) => s.library);
  const addFromLibrary = useStore((s) => s.addFromLibrary);
  const deleteForever = useStore((s) => s.deleteForever);
  const openFolder = useStore((s) => s.openLibraryFolder);
  const local = useStore((s) => s.access.local);
  const [q, setQ] = useState("");
  const [picked, setPicked] = useState<Set<string>>(new Set());
  const [sure, setSure] = useState<string | null>(null);

  useEffect(() => {
    if (!open) return;
    setQ("");
    setPicked(new Set());
    setSure(null);
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && setOpen(false);
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, setOpen]);

  const shown = useMemo(() => {
    const t = q.toLowerCase().trim();
    return entries.filter((e) => !t || `${e.label} ${e.filename} ${day(e)} ${clock(e)}`.toLowerCase().includes(t));
  }, [entries, q]);
  const days = useMemo(() => {
    const m = new Map<string, LibraryEntry[]>();
    for (const e of shown) m.set(day(e), [...(m.get(day(e)) ?? []), e]);
    return [...m];
  }, [shown]);

  if (!open) return null;
  const toggle = (id: string) =>
    setPicked((p) => {
      const n = new Set(p);
      if (n.has(id)) n.delete(id);
      else n.add(id);
      return n;
    });
  const addable = shown.filter((e) => !e.open);
  const add = async (ids: string[]) => {
    await addFromLibrary(ids);
    setPicked(new Set());
  };

  return (
    <div className="scrim top" onMouseDown={(e) => e.target === e.currentTarget && setOpen(false)}>
      <div className="dialog library" role="dialog" aria-modal="true" aria-label="Your logs">
        <header>
          <h2>Your logs</h2>
          <p className="muted">Add files, or choose from the logs you already have. Nothing is converted or stored twice.</p>
        </header>

        <div className="lib-tools">
          <ImportButton className="btn primary">Add files</ImportButton>
          <input type="search" value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search by name, date or time" aria-label="Search the library" />
          {local && (
            <button className="btn ghost" onClick={() => void openFolder()} title="Show the CSV copies in Explorer">
              Open folder
            </button>
          )}
          {addable.length > 0 && (
            <button className="btn ghost" onClick={() => setPicked(new Set(addable.map((e) => e.id)))}>
              Select all not in view
            </button>
          )}
        </div>

        <div className="lib-list">
          {entries.length === 0 && (
            <p className="lib-empty">Nothing here yet. Logs you convert or import are kept here, so you never convert them twice.</p>
          )}
          {entries.length > 0 && shown.length === 0 && <p className="lib-empty">No log matches "{q}".</p>}
          {days.map(([d, list]) => (
            <section key={d}>
              <h3>{d}</h3>
              <ul>
                {list.map((e) => (
                  <li key={e.id} className={e.open ? "in-view" : undefined}>
                    <label className="pick">
                      <input
                        type="checkbox"
                        checked={e.open || picked.has(e.id)}
                        disabled={e.open}
                        onChange={() => toggle(e.id)}
                        aria-label={`Select ${shortLabel(e.label)} at ${clock(e)}`}
                      />
                    </label>
                    <div className="lib-main">
                      <span className="lib-time">{clock(e)}</span>
                      <span className="lib-name">{shortLabel(e.label)}</span>
                    </div>
                    <span className="lib-meta">
                      {dur(e.duration_s)}, {e.channels} channels, {size(e.size_bytes)}
                    </span>
                    <span className="lib-act">
                      {e.open ? (
                        <span className="tag">In view</span>
                      ) : (
                        <button className="btn sm" onClick={() => void add([e.id])}>
                          Add
                        </button>
                      )}
                      {sure === e.id ? (
                        <button
                          className="btn sm danger"
                          onClick={() => {
                            void deleteForever(e.id);
                            setSure(null);
                          }}
                        >
                          Delete for good
                        </button>
                      ) : (
                        <button className="icon-btn" onClick={() => setSure(e.id)} aria-label={`Delete ${shortLabel(e.label)} from the library`} title="Delete from the library">
                          <svg width="16" height="16" viewBox="0 0 16 16" aria-hidden>
                            <path d="M3 4.5h10M6.5 4.5V3h3v1.5M4.5 4.5l.6 8h5.8l.6-8" />
                          </svg>
                        </button>
                      )}
                    </span>
                  </li>
                ))}
              </ul>
            </section>
          ))}
        </div>

        <footer>
          <button className="btn" onClick={() => setOpen(false)}>
            Close
          </button>
          <button className="btn primary" disabled={picked.size === 0} onClick={() => void add([...picked])}>
            {picked.size ? `Add ${picked.size} to view` : "Add to view"}
          </button>
        </footer>
      </div>
    </div>
  );
}
