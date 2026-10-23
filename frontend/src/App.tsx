import { useCallback, useEffect, useRef, useState } from "react";
import { Lane, TRACE } from "./components/Lane";
import { Sidebar } from "./components/Sidebar";
import { useStore } from "./store";

export default function App() {
  const lanes = useStore((s) => s.lanes);
  const sources = useStore((s) => s.sources);
  const message = useStore((s) => s.message);
  const refresh = useStore((s) => s.refresh);
  const importFiles = useStore((s) => s.importFiles);
  const clearMessage = useStore((s) => s.clearMessage);
  const fileRef = useRef<HTMLInputElement>(null);
  const [dragging, setDragging] = useState(false);

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
        <span className="muted hint-zoom">Drag on a plot to zoom. Double-click to reset.</span>
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
        {lanes.length === 0 ? (
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
