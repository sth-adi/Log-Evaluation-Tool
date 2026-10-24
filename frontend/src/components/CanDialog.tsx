import { useEffect, useRef, useState } from "react";
import { useStore } from "../store";

/** A CAN log is raw frames; a DBC file says what they mean. Ask which one, and keep it for next time. */
export function CanDialog() {
  const files = useStore((s) => s.canFiles);
  const dbcs = useStore((s) => s.dbcs);
  const closeCan = useStore((s) => s.closeCan);
  const addDbc = useStore((s) => s.addDbc);
  const deleteDbc = useStore((s) => s.deleteDbc);
  const importCan = useStore((s) => s.importCan);
  const [picked, setPicked] = useState<string[]>([]);
  const [busy, setBusy] = useState(false);
  const input = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (!files) return;
    setBusy(false);
    setPicked(dbcs.length === 1 ? [dbcs[0].id] : []);
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && closeCan();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
    // the choice resets when a new set of files arrives, not when the list of saved files changes
  }, [files]);

  if (!files) return null;
  const toggle = (id: string) => setPicked((p) => (p.includes(id) ? p.filter((x) => x !== id) : [...p, id]));

  return (
    <div className="scrim top" onMouseDown={(e) => e.target === e.currentTarget && closeCan()}>
      <div className="dialog" role="dialog" aria-modal="true" aria-label="Decode CAN log">
        <header>
          <h2>Which DBC file describes {files.length === 1 ? files[0].name : `these ${files.length} logs`}?</h2>
          <p className="muted">A CAN log holds raw numbers. The DBC file says which signals are in each frame and how to scale them. Pick one you have used before, or add it once and it is kept.</p>
        </header>

        <ul className="view-list">
          {dbcs.length === 0 && <li className="lib-empty">No DBC files yet.</li>}
          {dbcs.map((d) => (
            <li key={d.id}>
              <label className="pick">
                <input type="checkbox" checked={picked.includes(d.id)} onChange={() => toggle(d.id)} aria-label={`Use ${d.name}`} />
                <span className="lib-main">
                  <span className="lib-name">{d.name}</span>
                  <span className="lib-meta">{d.messages} messages, {d.signals} signals</span>
                </span>
              </label>
              <button className="btn ghost sm" onClick={() => void deleteDbc(d.id)} aria-label={`Forget ${d.name}`}>
                Forget
              </button>
            </li>
          ))}
        </ul>

        <input
          ref={input}
          type="file"
          accept=".dbc"
          hidden
          onChange={async (e) => {
            const f = e.target.files?.[0];
            e.target.value = "";
            const id = f ? await addDbc(f) : null;
            if (id) setPicked((p) => (p.includes(id) ? p : [...p, id]));
          }}
        />
        <footer>
          <button className="btn ghost" onClick={() => input.current?.click()}>
            Add a DBC file
          </button>
          <div className="spacer" />
          <button className="btn" onClick={closeCan}>
            Cancel
          </button>
          <button
            className="btn primary"
            disabled={picked.length === 0 || busy}
            onClick={async () => {
              setBusy(true);
              await importCan(picked);
            }}
          >
            {files.length === 1 ? "Import" : `Import ${files.length} logs`}
          </button>
        </footer>
      </div>
    </div>
  );
}
