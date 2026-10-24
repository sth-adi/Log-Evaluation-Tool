import { useMemo } from "react";
import { useStore } from "../store";
import { GROUPS, TOOLS, toolById } from "../tools";
import { useWindow } from "../useWindow";
import { Analysis, EventsPanel } from "./Analysis";
import { HeatmapPanel } from "./Heatmap";
import { Laps } from "./Laps";
import { Pulls } from "./Pulls";
import { SummaryPanel } from "./Summary";

/** Everything you can do with the logs besides looking at plots: pick a tool, then use it. */
export function Analyse() {
  const tool = useStore((s) => s.tool);
  return tool ? <OpenTool /> : <ToolList />;
}

function ToolList() {
  const sources = useStore((s) => s.sources);
  const lanes = useStore((s) => s.lanes);
  const setTool = useStore((s) => s.setTool);
  const ctx = useMemo(() => ({ sources, plotted: lanes.length }), [sources, lanes.length]);

  return (
    <section className="tool-list" aria-label="Analyse">
      <h2>What do you want to find out?</h2>
      {GROUPS.map((g) => (
        <div key={g} className="tool-group">
          <h3>{g}</h3>
          <div className="tool-cards">
            {TOOLS.filter((t) => t.group === g).map((t) => {
              const blocked = t.blocked?.(ctx) ?? null;
              const hint = blocked ?? t.hint?.(ctx) ?? null;
              return (
                <button key={t.id} className={`tool-card${blocked ? " off" : ""}`} onClick={() => setTool(t.id)} disabled={!!blocked}>
                  <strong>{t.title}</strong>
                  <span>{t.blurb}</span>
                  {hint && <small>{hint}</small>}
                </button>
              );
            })}
          </div>
        </div>
      ))}
    </section>
  );
}

function OpenTool() {
  const tool = useStore((s) => s.tool)!;
  const setTool = useStore((s) => s.setTool);
  const w = useWindow();
  const t = toolById(tool);
  return (
    <section className="tool-shell" aria-label={t.title}>
      <header className="tool-head">
        <button className="btn ghost sm" onClick={() => setTool(null)}>
          ← All tools
        </button>
        <h2>{t.title}</h2>
      </header>
      <div className="tool-body">
        {tool === "heatmap" && <HeatmapPanel t0={w.t0} t1={w.t1} rev={w.rev} />}
        {tool === "summary" && <SummaryPanel t0={w.t0} t1={w.t1} rev={w.rev} />}
        {tool === "pulls" && <Pulls />}
        {tool === "laps" && <Laps />}
        {tool === "events" && <EventsPanel />}
        {(tool === "statistics" || tool === "histogram" || tool === "spectrum" || tool === "scatter") && <Analysis kind={tool} />}
      </div>
    </section>
  );
}
