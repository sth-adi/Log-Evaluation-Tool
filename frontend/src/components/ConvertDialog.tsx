import { useEffect } from "react";
import { useStore } from "../store";

const kb = (n: number) => (n >= 1e6 ? `${(n / 1e6).toFixed(1)} MB` : `${Math.max(1, Math.round(n / 1e3))} KB`);

export function ConvertDialog() {
  const c = useStore((s) => s.convert);
  const start = useStore((s) => s.startConvert);
  const stop = useStore((s) => s.cancelConvert);
  const close = useStore((s) => s.closeConvert);
  const recheck = useStore((s) => s.openConvert);

  useEffect(() => {
    if (!c) return;
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && c.phase !== "running" && close();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [c, close]);

  if (!c) return null;
  const items = c.job?.items ?? c.files.map((f) => ({ name: f.name, state: "waiting", stage: "", error: "" }));
  const total = items.length;
  const done = items.filter((i) => i.state === "done").length;
  const finished = items.filter((i) => i.state !== "waiting" && i.state !== "working").length;
  const blocked = c.status && (!c.status.available || c.status.lifeview_open);

  return (
    <div className="scrim top">
      <div className="dialog" role="dialog" aria-modal="true" aria-label="Convert LifeView logs">
        <header>
          <h2>Convert LifeView logs</h2>
          <p className="muted">
            .LRD logs can only be opened by LifeView, so it will do the export for you and the tool imports the result.
          </p>
        </header>

        {c.phase === "ready" && blocked && (
          <div className="callout" role="alert">
            {!c.status!.available ? c.status!.reason : "LifeView is open. Close it, then check again."}
          </div>
        )}

        {c.phase === "running" && (
          <div className="callout warn" role="status">
            <strong>Keep your hands off the mouse and keyboard.</strong> LifeView opens and closes on its own for each log
            and the cursor moves for a few seconds. About 10 seconds per log.
          </div>
        )}

        {c.error && (
          <div className="callout" role="alert">
            {c.error}
          </div>
        )}

        <ul className="convert-list">
          {items.map((i) => (
            <li key={i.name} className={i.state}>
              <span className="c-name">{i.name}</span>
              <span className="c-state">
                {i.state === "waiting" && (c.phase === "ready" ? kb(c.files.find((f) => f.name === i.name)?.size ?? 0) : "Waiting")}
                {i.state === "working" && (i.stage || "Working")}
                {i.state === "done" && "Imported"}
                {i.state === "skipped" && "Skipped"}
                {i.state === "failed" && "Failed"}
              </span>
              {i.state === "failed" && <span className="c-err">{i.error}</span>}
            </li>
          ))}
        </ul>

        {c.phase !== "ready" && (
          <div className="meter" role="progressbar" aria-valuemin={0} aria-valuemax={total} aria-valuenow={finished} aria-label="Logs converted">
            <i style={{ width: `${(finished / Math.max(total, 1)) * 100}%` }} />
          </div>
        )}

        {c.phase === "finished" && (
          <p className="summary">
            {done === total ? `Imported all ${total} log${total > 1 ? "s" : ""}.` : `Imported ${done} of ${total} logs.`}
            {done > 1 ? " They are laid out back to back in start-time order." : ""} CSV copies are kept in the data folder
            under exports.
          </p>
        )}

        <footer>
          {c.phase === "ready" && (
            <>
              <button className="btn" onClick={close}>
                Cancel
              </button>
              {blocked ? (
                <button className="btn primary" onClick={() => void recheck(c.files)}>
                  Check again
                </button>
              ) : (
                <button className="btn primary" onClick={() => void start()}>
                  Convert {total} log{total > 1 ? "s" : ""}
                </button>
              )}
            </>
          )}
          {c.phase === "running" && (
            <button className="btn" onClick={() => void stop()} disabled={c.job?.state !== "running"}>
              Stop after this log
            </button>
          )}
          {c.phase === "finished" && (
            <button className="btn primary" onClick={close}>
              Done
            </button>
          )}
        </footer>
      </div>
    </div>
  );
}
