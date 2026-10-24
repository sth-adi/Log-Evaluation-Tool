import type { Source, ToolId } from "./store";

export type Tool = {
  id: ToolId;
  title: string;
  /** One plain sentence on what it is for. */
  blurb: string;
  group: string;
  /** Why the tool cannot be used with the logs that are open, or null if it can. */
  blocked?: (c: Context) => string | null;
  /** A heads-up that does not stop the tool from opening. */
  hint?: (c: Context) => string | null;
};

export type Context = { sources: Source[]; plotted: number };

const has = (sources: Source[], test: (name: string) => boolean) => sources.some((s) => s.channels.some((c) => test(c.name)));
// a channel that is zero throughout (an unused input) is present but carries nothing
const hasData = (sources: Source[], test: (name: string) => boolean) =>
  sources.some((s) => s.channels.some((c) => test(c.name) && c.max > c.min));

const LAP_CHANNEL = /^(lapTime|lastLapTime|lapCount|lap)$/i;

export const GROUPS = ["One channel", "Two channels", "Compare runs", "Find problems"] as const;

export const TOOLS: Tool[] = [
  {
    id: "statistics",
    group: "One channel",
    title: "Statistics",
    blurb: "Highest, lowest, average and spread of the channels you have plotted.",
    hint: (c) => (c.plotted === 0 ? "Plot a channel first" : null),
  },
  { id: "histogram", group: "One channel", title: "Histogram", blurb: "How a channel's values are spread, to see where it spends its time." },
  { id: "spectrum", group: "One channel", title: "Spectrum", blurb: "Which frequencies a channel contains, for finding vibration or noise." },
  { id: "scatter", group: "Two channels", title: "Scatter", blurb: "One channel against another, to see how they relate." },
  {
    id: "heatmap",
    group: "Two channels",
    title: "Heatmap",
    blurb: "Where the engine spends its time, or what a channel averages, across two others. For example lambda by RPM and throttle.",
  },
  { id: "summary", group: "Compare runs", title: "Summary", blurb: "One number per log, side by side: peak RPM, average lambda at full throttle, and so on." },
  {
    id: "pulls",
    group: "Compare runs",
    title: "Pulls",
    blurb: "Dyno or engine sweeps laid over each other against RPM, with an estimated power curve.",
    blocked: (c) => (has(c.sources, (n) => /^rpm$/i.test(n)) ? null : "Needs an rpm channel"),
  },
  {
    id: "laps",
    group: "Compare runs",
    title: "Laps",
    blurb: "Lap times, and laps drawn on top of each other.",
    hint: (c) => (hasData(c.sources, (n) => LAP_CHANNEL.test(n)) ? null : "No lap timer data in these logs"),
  },
  { id: "events", group: "Find problems", title: "Events", blurb: "Stretches where something you describe is true, such as RPM above the limiter." },
];

export const toolById = (id: ToolId): Tool => TOOLS.find((t) => t.id === id)!;
