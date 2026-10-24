import { useCallback, useEffect, useRef, useState } from "react";
import { Analysis } from "./components/Analysis";
import { ConvertDialog } from "./components/ConvertDialog";
import { Lane, channelGroups } from "./components/Lane";
import { Laps } from "./components/Laps";
import { Live } from "./components/Live";
import { Pulls } from "./components/Pulls";
import { Library } from "./components/Library";
import { Views } from "./components/Views";
import { LogDrawer, LogRail } from "./components/LogRail";
import { Palette } from "./components/Palette";
import { extentOf, useStore } from "./store";

const QUICK = ["rpm", "vehicleSpeed", "tps1", "ect1"];

export default function App() {
  const lanes = useStore((s) => s.lanes);
  const sources = useStore((s) => s.sources);
  const message = useStore((s) => s.message);
  const refresh = useStore((s) => s.refresh);
  const mode = useStore((s) => s.mode);
  const setMode = useStore((s) => s.setMode);
  const importFiles = useStore((s) => s.importFiles);
  const clearMessage = useStore((s) => s.clearMessage);
  const setPalette = useStore((s) => s.setPalette);
  const library = useStore((s) => s.library);
  const loadLibrary = useStore((s) => s.loadLibrary);
  const setLibraryOpen = useStore((s) => s.setLibraryOpen);
  const setViewsOpen = useStore((s) => s.setViewsOpen);
  const addChannelAll = useStore((s) => s.addChannelAll);
  const view = useStore((s) => s.view);
  const fileRef = useRef<HTMLInputElement>(null);
  const [dragging, setDragging] = useState(false);

  // Open one report per log that has plotted channels, for the zoomed window if there is one.
  const openReports = () => {
    const [e0, e1] = extentOf(sources);
    const zoomed = view != null && (Math.abs(view[0] - e0) > 1e-6 || Math.abs(view[1] - e1) > 1e-6);
    const bySource = new Map<string, string[]>();
    for (const l of lanes)
      for (const s of l.series) bySource.set(s.sourceId, [...new Set([...(bySource.get(s.sourceId) ?? []), s.channel])]);
    for (const [id, chans] of bySource) {
      const q = new URLSearchParams({ channels: chans.join(",") });
      if (zoomed && view) {
        q.set("t0", String(view[0]));
        q.set("t1", String(view[1]));
      }
      window.open(`/api/sources/${id}/report?${q}`, "_blank", "noopener");
    }
  };

  useEffect(() => {
    void refresh();
    void loadLibrary();
  }, [refresh, loadLibrary]);

  // "/" or Ctrl+K opens the channel search from anywhere that is not a text box.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const t = e.target as HTMLElement | null;
      const typing = !!t && (t.tagName === "INPUT" || t.tagName === "TEXTAREA" || t.tagName === "SELECT" || t.isContentEditable);
      if ((e.key === "k" && (e.ctrlKey || e.metaKey)) || (e.key === "/" && !typing)) {
        if (!useStore.getState().sources.length) return;
        e.preventDefault();
        setPalette(true);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [setPalette]);

  useEffect(() => {
    if (message?.kind !== "info") return;
    const t = setTimeout(clearMessage, 5000);
    return () => clearTimeout(t);
  }, [message, clearMessage]);

  const onDrop = useCallback(
    (e: React.DragEvent) => {
      e.preventDefault();
      setDragging(false);
      const files = [...e.dataTransfer.files].filter((f) => /\.(csv|txt|tsv|lrd)$/i.test(f.name));
      if (files.length) void importFiles(files);
    },
    [importFiles],
  );

  const hasLogs = sources.length > 0;
  const quick = QUICK.filter((n) => sources.some((s) => s.channels.some((c) => c.name === n)));
  let colorOffset = 0;

  return (
    <div
      className={`app${dragging ? " dragging" : ""}${hasLogs && mode !== "live" ? "" : " bare"}`}
      onDragOver={(e) => {
        e.preventDefault();
        setDragging(true);
      }}
      onDragLeave={(e) => e.currentTarget === e.target && setDragging(false)}
      onDrop={onDrop}
    >
      <header className="topbar">
        <h1>Log Evaluation Tool</h1>
        <div className="seg" role="tablist" aria-label="View">
          {hasLogs && (
            <>
            <button role="tab" aria-selected={mode === "plots"} className={mode === "plots" ? "on" : undefined} onClick={() => setMode("plots")}>
              Plots
            </button>
            <button role="tab" aria-selected={mode === "analysis"} className={mode === "analysis" ? "on" : undefined} onClick={() => setMode("analysis")}>
              Analysis
            </button>
            <button role="tab" aria-selected={mode === "laps"} className={mode === "laps" ? "on" : undefined} onClick={() => setMode("laps")}>
              Laps
            </button>
            <button role="tab" aria-selected={mode === "pulls"} className={mode === "pulls" ? "on" : undefined} onClick={() => setMode("pulls")}>
              Pulls
            </button>
            </>
          )}
          <button role="tab" aria-selected={mode === "live"} className={mode === "live" ? "on" : undefined} onClick={() => setMode("live")}>
            Live
          </button>
        </div>
        {hasLogs && mode !== "live" && (
          <button className="search" onClick={() => setPalette(true)}>
            <svg width="16" height="16" viewBox="0 0 18 18" aria-hidden>
              <circle cx="8" cy="8" r="5.2" />
              <path d="M12 12l4 4" />
            </svg>
            <span>Plot a channel</span>
            <kbd>/</kbd>
          </button>
        )}
        <div className="spacer" />
        <button className="btn" onClick={() => setLibraryOpen(true)} title="Every log you have converted or imported">
          Library{library.length > 0 && <span className="count">{library.length}</span>}
        </button>
        {hasLogs && (
          <button className="btn" onClick={() => setViewsOpen(true)} title="Save what you have set up, or open a saved view">
            Views
          </button>
        )}
        {lanes.length > 0 && (
          <button className="btn" onClick={openReports} title="Open a printable report of the plotted channels">
            Report
          </button>
        )}
        <button className="btn" onClick={() => fileRef.current?.click()}>
          Import logs
        </button>
        <input
          ref={fileRef}
          type="file"
          accept=".csv,.txt,.tsv,.lrd"
          multiple
          hidden
          onChange={(e) => {
            const files = [...(e.target.files ?? [])];
            e.target.value = "";
            if (files.length) void importFiles(files);
          }}
        />
      </header>

      {hasLogs && mode !== "live" && <LogRail />}

      <main className="stage">
        {mode === "live" ? (
          <Live />
        ) : !hasLogs ? (
          <div className="empty">
            <h2>Drop your logs here</h2>
            <p>Life Racing .LRD logs, or CSV files exported from LifeView. Everything stays on this computer.</p>
            <button className="btn primary lg" onClick={() => fileRef.current?.click()}>
              Choose files
            </button>
            <button className="btn lg" onClick={() => setMode("live")}>
              Go live
            </button>
            {library.length > 0 && (
              <button className="btn lg" onClick={() => setLibraryOpen(true)}>
                Open from the library ({library.length})
              </button>
            )}
          </div>
        ) : mode === "analysis" ? (
          <Analysis />
        ) : mode === "laps" ? (
          <Laps />
        ) : mode === "pulls" ? (
          <Pulls />
        ) : lanes.length === 0 ? (
          <div className="empty">
            <h2>What do you want to look at?</h2>
            <p>Plot any channel across all {sources.length === 1 ? "of this log" : `${sources.length} logs`}.</p>
            {quick.length > 0 && (
              <div className="quick">
                {quick.map((n) => (
                  <button key={n} className="chip lg" onClick={() => addChannelAll(n, false)}>
                    {n}
                  </button>
                ))}
              </div>
            )}
            <button className="btn lg" onClick={() => setPalette(true)}>
              Search all channels <kbd>/</kbd>
            </button>
          </div>
        ) : (
          <>
            <div className="lanes">
              {lanes.map((lane, i) => {
                const offset = colorOffset;
                colorOffset += channelGroups(lane.series).length;
                return <Lane key={lane.id} lane={lane} colorOffset={offset} isLast={i === lanes.length - 1} />;
              })}
            </div>
            <p className="stage-hint">Drag on a plot to zoom. Double-click to see everything again.</p>
          </>
        )}
      </main>

      <Palette />
      <LogDrawer />
      <ConvertDialog />
      <Library />
      <Views />

      {message && (
        <div className={`toast ${message.kind}`} role={message.kind === "error" ? "alert" : "status"}>
          <span>{message.text}</span>
          <button className="btn ghost sm" onClick={clearMessage}>
            Dismiss
          </button>
        </div>
      )}
      {dragging && <div className="drop-veil">Drop to import</div>}
    </div>
  );
}
