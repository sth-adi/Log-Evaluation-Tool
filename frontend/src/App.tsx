import { useCallback, useEffect, useRef, useState } from "react";
import { Analysis } from "./components/Analysis";
import { Lane, TRACE } from "./components/Lane";
import { Sidebar } from "./components/Sidebar";
import { extentOf, useStore } from "./store";

export default function App() {
  const lanes = useStore((s) => s.lanes);
  const sources = useStore((s) => s.sources);
  const message = useStore((s) => s.message);
  const refresh = useStore((s) => s.refresh);
  const mode = useStore((s) => s.mode);
  const setMode = useStore((s) => s.setMode);
  const importFiles = useStore((s) => s.importFiles);
  const clearMessage = useStore((s) => s.clearMessage);
  const fileRef = useRef<HTMLInputElement>(null);
  const [dragging, setDragging] = useState(false);
  const view = useStore((s) => s.view);

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
  }, [refresh]);

  const onDrop = useCallback(
    (e: React.DragEvent) => {
      e.preventDefault();
      setDragging(false);
      const files = [...e.dataTransfer.files].filter((f) => /\.(csv|txt|tsv)$/i.test(f.name));
      if (files.length) void importFiles(files);
    },
    [importFiles],
  );

  let colorOffset = 0;

  return (
    <div
      className={`app${dragging ? " dragging" : ""}`}
      onDragOver={(e) => {
        e.preventDefault();
        setDragging(true);
      }}
      onDragLeave={(e) => e.currentTarget === e.target && setDragging(false)}
      onDrop={onDrop}
    >
      <header className="topbar">
        <h1>Log Evaluation Tool</h1>
        {sources.length > 0 && (
          <div className="seg" role="tablist" aria-label="View">
            <button role="tab" aria-selected={mode === "plots"} className={mode === "plots" ? "on" : undefined} onClick={() => setMode("plots")}>
              Plots
            </button>
            <button role="tab" aria-selected={mode === "analysis"} className={mode === "analysis" ? "on" : undefined} onClick={() => setMode("analysis")}>
              Analysis
            </button>
          </div>
        )}
        <span className="muted hint-zoom">Drag on a plot to zoom. Double-click to reset.</span>
        {lanes.length > 0 && (
          <button onClick={openReports} title="Open a printable report of the plotted channels (zoomed window if zoomed)">
            Report
          </button>
        )}
        <button className="primary" onClick={() => fileRef.current?.click()}>
          Import logs
        </button>
        <input
          ref={fileRef}
          type="file"
          accept=".csv,.txt,.tsv"
          multiple
          hidden
          onChange={(e) => {
            const files = [...(e.target.files ?? [])];
            e.target.value = "";
            if (files.length) void importFiles(files);
          }}
        />
      </header>

      {message && (
        <div className={`message ${message.kind}`} role={message.kind === "error" ? "alert" : "status"}>
          <span>{message.text}</span>
          <button className="link" onClick={clearMessage}>
            Dismiss
          </button>
        </div>
      )}

      <Sidebar />

      <main className="lanes">
        {mode === "analysis" && sources.length > 0 ? (
          <Analysis />
        ) : lanes.length === 0 ? (
          <div className="empty">
            {sources.length === 0 ? (
              <>
                <h2>Import an ECU or HCU log</h2>
                <p>Choose CSV files, or drop them anywhere in this window. Nothing leaves this computer.</p>
                <button className="primary" onClick={() => fileRef.current?.click()}>
                  Import logs
                </button>
              </>
            ) : (
              <>
                <h2>Pick a channel to plot</h2>
                <p>Select a channel in the list on the left.</p>
              </>
            )}
          </div>
        ) : (
          lanes.map((lane, i) => {
            const offset = colorOffset;
            colorOffset += lane.series.length;
            return <Lane key={lane.id} lane={lane} colorOffset={offset % TRACE.length} isLast={i === lanes.length - 1} />;
          })
        )}
      </main>
    </div>
  );
}
