import { useCallback, useEffect, useState } from "react";
import { Analyse } from "./components/Analyse";
import { CanDialog } from "./components/CanDialog";
import { ConvertDialog } from "./components/ConvertDialog";
import { ImportButton, isLogFile } from "./components/ImportButton";
import { Lane, channelGroups } from "./components/Lane";
import { Library } from "./components/Library";
import { Live } from "./components/Live";
import { LogDrawer, LogRail } from "./components/LogRail";
import { Menu } from "./components/Menu";
import { Palette } from "./components/Palette";
import { Review } from "./components/Review";
import { Views } from "./components/Views";
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
  const review = useStore((s) => s.review);
  const attention = review ? review.findings.filter((f) => f.severity !== "low").length : 0;
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
        setMode("plots");
        setPalette(true);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [setPalette, setMode]);

  useEffect(() => {
    if (message?.kind !== "info") return;
    const t = setTimeout(clearMessage, 5000);
    return () => clearTimeout(t);
  }, [message, clearMessage]);

  const onDrop = useCallback(
    (e: React.DragEvent) => {
      e.preventDefault();
      setDragging(false);
      const files = [...e.dataTransfer.files].filter(isLogFile);
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
        {hasLogs && (
          <div className="seg" role="tablist" aria-label="View">
            <button role="tab" aria-selected={mode === "plots"} className={mode === "plots" ? "on" : undefined} onClick={() => setMode("plots")}>
              Plots
            </button>
            <button role="tab" aria-selected={mode === "review"} className={mode === "review" ? "on" : undefined} onClick={() => setMode("review")}>
              Review
              {attention > 0 && <span className="tab-count" aria-label={`${attention} to look at`}>{attention}</span>}
            </button>
            <button role="tab" aria-selected={mode === "analyse"} className={mode === "analyse" ? "on" : undefined} onClick={() => setMode("analyse")}>
              Analyse
            </button>
          </div>
        )}
        {hasLogs && mode === "plots" && (
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
        <button className="btn" onClick={() => setLibraryOpen(true)} title="Add logs, or choose from the ones you already have">
          Logs{library.length > 0 && <span className="count">{library.length}</span>}
        </button>
        <Menu
          label="More"
          items={[
            { label: "Saved views", note: "Keep or share a set-up", disabled: !hasLogs, onSelect: () => setViewsOpen(true) },
            { label: "Report", note: "Printable page of the plotted channels", disabled: lanes.length === 0, onSelect: openReports },
            { label: "Live data", note: "Follow a car as it runs", onSelect: () => setMode("live") },
          ]}
        />
      </header>

      {hasLogs && mode !== "live" && <LogRail />}

      <main className="stage">
        {mode === "live" ? (
          <Live />
        ) : !hasLogs ? (
          <div className="empty">
            <h2>Drop your logs here</h2>
            <p>Life Racing .LRD logs, or CSV, Excel, Parquet, MDF (.mf4) and CAN (.asc, .blf) files. Everything stays on this computer.</p>
            <ImportButton className="btn primary lg">Choose files</ImportButton>
            {library.length > 0 && (
              <button className="btn lg" onClick={() => setLibraryOpen(true)}>
                Open from the library ({library.length})
              </button>
            )}
          </div>
        ) : mode === "review" ? (
          <Review />
        ) : mode === "analyse" ? (
          <Analyse />
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
      <CanDialog />
      <Library />
      <Views />

      {message && (
        <div className={`toast ${message.kind}`} role={message.kind === "info" ? "status" : "alert"}>
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
