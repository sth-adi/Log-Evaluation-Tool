import { useEffect, useMemo, useRef, useState } from "react";
import { useStore } from "../store";

type Entry = { name: string; unit: string; min: number; max: number; logs: number; group: string; derived: boolean };

const GROUPS: [string, RegExp][] = [
  ["Temperatures", /(^|[^a-z])(ect|act|iat|egt|eot|clt|oilt)|temp/i],
  ["Fuel and lambda", /fuel|^fp\d|inj|lam|afr|cll|pulse/i],
  ["Ignition", /ign|spark|dwell|knock|advance|coil|timing/i],
  ["Speed and traction", /speed|wheel|slip|tfc|launch|gear|clutch|^swa|latg|longg|yaw|brake|bpr|steer/i],
  ["Electrical", /vbat|batt|volt|^an\d|v$|fan\d|relay|sync/i],
  ["Engine", /rpm|tps|^map|^bap|throttle|load|torque|trq|idle|cycle|engine|pedal|^ap|rev|run/i],
];
export const groupOf = (name: string) => GROUPS.find(([, rx]) => rx.test(name))?.[0] ?? "Other";

const SUGGESTED = ["rpm", "vehicleSpeed", "tps1", "ect1", "map1", "lam1", "ignFinalPri1", "vbat"];
const fmt = (v: number) => (Math.abs(v) >= 1000 ? v.toLocaleString("en-GB", { maximumFractionDigits: 0 }) : String(+v.toFixed(2)));

export function Palette() {
  const open = useStore((s) => s.paletteOpen);
  const setOpen = useStore((s) => s.setPalette);
  const sources = useStore((s) => s.sources);
  const recent = useStore((s) => s.recent);
  const addChannelAll = useStore((s) => s.addChannelAll);
  const setMode = useStore((s) => s.setMode);
  const [q, setQ] = useState("");
  const [chip, setChip] = useState("All");
  const [active, setActive] = useState(0);
  const input = useRef<HTMLInputElement>(null);
  const list = useRef<HTMLUListElement>(null);

  const all = useMemo(() => {
    const m = new Map<string, Entry>();
    for (const s of sources)
      for (const c of s.channels) {
        const e = m.get(c.name);
        if (e) {
          e.logs += 1;
          e.min = Math.min(e.min, c.min);
          e.max = Math.max(e.max, c.max);
        } else m.set(c.name, { name: c.name, unit: c.unit, min: c.min, max: c.max, logs: 1, group: groupOf(c.name), derived: !!c.derived });
      }
    return m;
  }, [sources]);

  const chips = useMemo(() => {
    const present = new Set([...all.values()].map((e) => e.group));
    const order = [...GROUPS.map(([g]) => g), "Other"].filter((g) => present.has(g));
    return ["All", ...(all.size && [...all.values()].some((e) => e.derived) ? ["Calculated"] : []), ...order];
  }, [all]);

  const rows: { kind: "head" | "item"; text?: string; e?: Entry }[] = useMemo(() => {
    const terms = q.toLowerCase().split(/\s+/).filter(Boolean);
    const inChip = (e: Entry) => chip === "All" || (chip === "Calculated" ? e.derived : e.group === chip);
    if (!terms.length && chip === "All") {
      const out: { kind: "head" | "item"; text?: string; e?: Entry }[] = [];
      const seen = new Set<string>();
      const add = (title: string, names: string[]) => {
        const es = names.map((n) => all.get(n)).filter((e): e is Entry => !!e && !seen.has(e.name));
        if (!es.length) return;
        out.push({ kind: "head", text: title });
        for (const e of es) {
          seen.add(e.name);
          out.push({ kind: "item", e });
        }
      };
      add("Recently plotted", recent);
      add("Suggested", SUGGESTED);
      return out;
    }
    const scored = [...all.values()]
      .filter(inChip)
      .map((e) => {
        const n = e.name.toLowerCase();
        if (!terms.length) return { e, s: 0 };
        if (!terms.every((t) => n.includes(t) || e.group.toLowerCase().includes(t))) return { e, s: -1 };
        return { e, s: n.startsWith(terms[0]) ? 0 : 1 };
      })
      .filter((x) => x.s >= 0)
      .sort((a, b) => a.s - b.s || a.e.name.localeCompare(b.e.name));
    return scored.map((x) => ({ kind: "item" as const, e: x.e }));
  }, [q, chip, all, recent]);

  const items = rows.filter((r) => r.kind === "item");

  useEffect(() => {
    if (open) {
      setQ("");
      setChip("All");
      setActive(0);
      requestAnimationFrame(() => input.current?.focus());
    }
  }, [open]);
  useEffect(() => setActive(0), [q, chip]);
  useEffect(() => {
    list.current?.querySelector('[aria-selected="true"]')?.scrollIntoView({ block: "nearest" });
  }, [active]);

  if (!open) return null;

  const pick = (e: Entry | undefined, overlay: boolean) => {
    if (!e) return;
    addChannelAll(e.name, overlay);
    setMode("plots");
    if (!overlay) setOpen(false);
  };

  const onKey = (ev: React.KeyboardEvent) => {
    if (ev.key === "Escape") setOpen(false);
    else if (ev.key === "ArrowDown") {
      ev.preventDefault();
      setActive((a) => Math.min(a + 1, items.length - 1));
    } else if (ev.key === "ArrowUp") {
      ev.preventDefault();
      setActive((a) => Math.max(a - 1, 0));
    } else if (ev.key === "Enter") {
      ev.preventDefault();
      pick(items[active]?.e, ev.shiftKey);
    }
  };

  let idx = -1;
  return (
    <div className="scrim top" onMouseDown={(e) => e.target === e.currentTarget && setOpen(false)}>
      <div className="palette" role="dialog" aria-modal="true" aria-label="Plot a channel" onKeyDown={onKey}>
        <div className="palette-search">
          <svg width="18" height="18" viewBox="0 0 18 18" aria-hidden>
            <circle cx="8" cy="8" r="5.2" />
            <path d="M12 12l4 4" />
          </svg>
          <input
            ref={input}
            value={q}
            onChange={(e) => setQ(e.target.value)}
            placeholder={`Search ${all.size} channels`}
            role="combobox"
            aria-expanded="true"
            aria-controls="palette-list"
            aria-label="Search channels"
            spellCheck={false}
          />
          <kbd>Esc</kbd>
        </div>
        <div className="chips" role="group" aria-label="Filter by group">
          {chips.map((c) => (
            <button key={c} className={`chip${chip === c ? " on" : ""}`} aria-pressed={chip === c} onClick={() => setChip(c)}>
              {c}
            </button>
          ))}
        </div>
        <ul className="results" id="palette-list" role="listbox" ref={list}>
          {rows.length === 0 && <li className="none">No channel matches "{q}".</li>}
          {rows.map((r, i) => {
            if (r.kind === "head")
              return (
                <li key={`h${i}`} className="group" role="presentation">
                  {r.text}
                </li>
              );
            idx += 1;
            const my = idx;
            const e = r.e!;
            return (
              <li
                key={e.name}
                role="option"
                aria-selected={my === active}
                className={my === active ? "on" : undefined}
                onMouseMove={() => setActive(my)}
                onClick={(ev) => pick(e, ev.shiftKey)}
              >
                <span className="r-name">{e.derived ? `ƒ ${e.name}` : e.name}</span>
                <span className="r-group">{e.group}</span>
                <span className="r-range">
                  {fmt(e.min)} to {fmt(e.max)} {e.unit}
                </span>
                {sources.length > 1 && e.logs < sources.length && <span className="r-logs">{e.logs} of {sources.length} logs</span>}
              </li>
            );
          })}
        </ul>
        <footer className="palette-foot">
          <span><kbd>↑</kbd> <kbd>↓</kbd> to move</span>
          <span><kbd>Enter</kbd> plots it</span>
          <span><kbd>Shift</kbd> + <kbd>Enter</kbd> adds it to the last plot</span>
        </footer>
      </div>
    </div>
  );
}
