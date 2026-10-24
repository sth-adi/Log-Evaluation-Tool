import { useEffect, useRef, useState } from "react";

export type MenuItem = { label: string; note?: string; disabled?: boolean; onSelect: () => void };

/** A button that opens a short list of actions. Closes on a pick, a click elsewhere, or Escape. */
export function Menu(props: { label: string; items: MenuItem[] }) {
  const [open, setOpen] = useState(false);
  const box = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const away = (e: MouseEvent) => box.current && !box.current.contains(e.target as Node) && setOpen(false);
    const key = (e: KeyboardEvent) => e.key === "Escape" && setOpen(false);
    document.addEventListener("mousedown", away);
    document.addEventListener("keydown", key);
    return () => {
      document.removeEventListener("mousedown", away);
      document.removeEventListener("keydown", key);
    };
  }, [open]);

  return (
    <div className="menu" ref={box}>
      <button className="btn" aria-haspopup="menu" aria-expanded={open} onClick={() => setOpen((o) => !o)}>
        {props.label}
        <svg width="10" height="10" viewBox="0 0 10 10" aria-hidden className="caret">
          <path d="M2 3.5l3 3 3-3" />
        </svg>
      </button>
      {open && (
        <div className="menu-list" role="menu">
          {props.items.map((it) => (
            <button
              key={it.label}
              role="menuitem"
              className="menu-item"
              disabled={it.disabled}
              onClick={() => {
                setOpen(false);
                it.onSelect();
              }}
            >
              <span>{it.label}</span>
              {it.note && <small>{it.note}</small>}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
