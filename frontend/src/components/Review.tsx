import { useEffect, useMemo, useState } from "react";
import type { Finding, Limit, Severity } from "../api";
import { useStore } from "../store";
import { shortLabel } from "./LogRail";

const SEVERITY: Record<Severity, string> = { high: "Needs attention", medium: "Worth a look", low: "Probably normal" };
const SHOWN = 4;

/** What the checks found in the open logs, without anything having to be set up first. */
export function Review() {
  const review = useStore((s) => s.review);
  if (!review) return <section className="review"><p className="muted">Checking the logs…</p></section>;

  const attention = review.findings.filter((f) => f.severity !== "low");
  const quiet = review.findings.filter((f) => f.severity === "low");
  const { logs, channels } = review.checked;

  return (
    <section className="review" aria-label="Review">
      <header className="review-head">
        <h2>{attention.length === 0 ? "Nothing needs attention" : `${attention.length} thing${attention.length > 1 ? "s" : ""} to look at`}</h2>
        <p className="muted">
          Checked {logs} log{logs > 1 ? "s" : ""} and {channels} channels on their own.
          {attention.length === 0 && " Nothing in them differs from how the car normally behaves."}
        </p>
        {review.notes.map((n) => (
          <p key={n} className="hint">
            {n}
          </p>
        ))}
      </header>

      {attention.map((f) => (
        <FindingCard key={f.key} f={f} />
      ))}

      {quiet.length > 0 && (
        <details className="opts">
          <summary>Probably normal ({quiet.length})</summary>
          <div className="finding-list">
            {quiet.map((f) => (
              <FindingCard key={f.key} f={f} />
            ))}
          </div>
        </details>
      )}

      {review.muted.length > 0 && (
        <details className="opts">
          <summary>Marked as normal ({review.muted.length})</summary>
          <div className="finding-list">
            {review.muted.map((f) => (
              <FindingCard key={f.key} f={f} muted />
            ))}
          </div>
        </details>
      )}

      <Limits />
    </section>
  );
}

function FindingCard({ f, muted }: { f: Finding; muted?: boolean }) {
  const openFinding = useStore((s) => s.openFinding);
  const mute = useStore((s) => s.muteFinding);
  const restore = useStore((s) => s.restoreFinding);
  const [all, setAll] = useState(false);
  const rows = all ? f.occurrences : f.occurrences.slice(0, SHOWN);

  return (
    <article className={`finding ${f.severity}`}>
      <div className="finding-top">
        <span className={`sev ${f.severity}`}>{SEVERITY[f.severity]}</span>
        <h3>{f.title}</h3>
      </div>
      <p className="finding-detail">{f.detail}</p>
      {f.evidence && (
        <p className="hint">
          It followed {f.evidence.followed} of {f.evidence.events} times. By chance alone it would be about {Math.round(f.evidence.chance * 100)}%.
        </p>
      )}
      {rows.length > 0 && (
        <ul className="occ">
          {rows.map((o, i) => (
            <li key={`${o.log_id}-${o.t0}-${i}`}>
              <span className="occ-where">
                {shortLabel(o.label)} · {o.t0.toFixed(1)} s
              </span>
              <span className="occ-note">{o.note}</span>
              {o.fits === false && <span className="tag">does not fit the pattern</span>}
              {o.fits === true && <span className="tag quiet">fits the pattern</span>}
              <button className="btn ghost sm" onClick={() => openFinding(f, o)}>
                Show
              </button>
            </li>
          ))}
        </ul>
      )}
      <div className="finding-foot">
        {f.occurrences.length > SHOWN && (
          <button className="btn ghost sm" onClick={() => setAll(!all)}>
            {all ? "Show fewer" : `Show all ${f.occurrences.length}${f.count > f.occurrences.length ? " (of " + f.count + ")" : ""}`}
          </button>
        )}
        <span className="spacer" />
        {muted ? (
          <button className="btn ghost sm" onClick={() => void restore(f.key)}>
            Bring back
          </button>
        ) : (
          <button className="btn ghost sm" onClick={() => void mute(f.key)} title="Stop flagging this. It stays under Marked as normal.">
            This is normal
          </button>
        )}
      </div>
    </article>
  );
}

const blank = (): Limit => ({ channel: "", op: ">", value: 0, seconds: 0, severity: "high", message: "", running_only: true });

/** Limits for physical things only the team knows, such as oil pressure. Everything else is automatic. */
function Limits() {
  const review = useStore((s) => s.review)!;
  const sources = useStore((s) => s.sources);
  const save = useStore((s) => s.saveLimits);
  const [draft, setDraft] = useState<Limit[]>(review.limits);
  const [busy, setBusy] = useState(false);
  const saved = JSON.stringify(review.limits);
  useEffect(() => setDraft(review.limits), [saved]);
  const names = useMemo(() => [...new Set(sources.flatMap((s) => s.channels.map((c) => c.name)))].sort(), [sources]);
  const set = (i: number, patch: Partial<Limit>) => setDraft((d) => d.map((l, k) => (k === i ? { ...l, ...patch } : l)));
  const dirty = JSON.stringify(draft) !== saved;

  return (
    <details className="opts">
      <summary>Your limits ({review.limits.length})</summary>
      <div className="limits">
        <p className="hint">
          Only for things the logs cannot tell on their own, such as a minimum oil pressure. Everything else is checked automatically.
        </p>
        <datalist id="limit-channels">
          {names.map((n) => (
            <option key={n} value={n} />
          ))}
        </datalist>
        {draft.map((l, i) => (
          <div className="limit" key={l.id ?? `new-${i}`}>
            <input list="limit-channels" value={l.channel} placeholder="Channel" onChange={(e) => set(i, { channel: e.target.value })} aria-label="Channel" />
            <select value={l.op} onChange={(e) => set(i, { op: e.target.value as Limit["op"] })} aria-label="Above or below">
              <option value=">">above</option>
              <option value="<">below</option>
            </select>
            <input type="number" value={l.value} onChange={(e) => set(i, { value: e.target.valueAsNumber })} aria-label="Value" />
            <label className="inline">
              for
              <input type="number" min={0} step="0.1" value={l.seconds} onChange={(e) => set(i, { seconds: e.target.valueAsNumber || 0 })} aria-label="Seconds" />
              s
            </label>
            <select value={l.severity} onChange={(e) => set(i, { severity: e.target.value as Severity })} aria-label="How serious">
              <option value="high">{SEVERITY.high}</option>
              <option value="medium">{SEVERITY.medium}</option>
              <option value="low">{SEVERITY.low}</option>
            </select>
            <input value={l.message} placeholder="What to say (optional)" onChange={(e) => set(i, { message: e.target.value })} aria-label="Message" />
            <label className="inline">
              <input type="checkbox" checked={l.running_only} onChange={(e) => set(i, { running_only: e.target.checked })} />
              engine running only
            </label>
            <button className="btn ghost sm" onClick={() => setDraft((d) => d.filter((_, k) => k !== i))}>
              Remove
            </button>
          </div>
        ))}
        <div className="limit-actions">
          <button className="btn sm" onClick={() => setDraft((d) => [...d, blank()])}>
            Add a limit
          </button>
          <button
            className="btn primary sm"
            disabled={!dirty || busy}
            onClick={async () => {
              setBusy(true);
              await save(draft);
              setBusy(false);
            }}
          >
            Save limits
          </button>
        </div>
      </div>
    </details>
  );
}
