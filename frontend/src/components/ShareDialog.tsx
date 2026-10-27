import QRCode from "qrcode";
import { useCallback, useEffect, useMemo, useState } from "react";
import { api, type ShareInfo } from "../api";
import { useStore } from "../store";

/** A QR code drawn from its modules, one square each, so no page style can thicken or blur it. */
function Code({ text }: { text: string }) {
  const code = useMemo(() => {
    try {
      const { size, data } = QRCode.create(text, { errorCorrectionLevel: "M" }).modules;
      let d = "";
      for (let y = 0; y < size; y++) for (let x = 0; x < size; x++) if (data[y * size + x]) d += `M${x + 4} ${y + 4}h1v1h-1z`;
      return { size: size + 8, d }; // four empty modules around it, as the standard asks
    } catch {
      return null; // too long to encode: the link below still works
    }
  }, [text]);
  if (!code) return null;
  return (
    <div className="qr">
      <svg viewBox={`0 0 ${code.size} ${code.size}`} role="img" aria-label="QR code for the phone link" shapeRendering="crispEdges">
        <rect width={code.size} height={code.size} fill="#fff" />
        <path d={code.d} fill="#0a0b0d" stroke="none" />
      </svg>
    </div>
  );
}

/** Shows the link and QR code that open the tool on a phone on the same Wi-Fi. Only the PC can see this. */
export function ShareDialog() {
  const open = useStore((s) => s.shareOpen);
  const setOpen = useStore((s) => s.setShareOpen);
  const [info, setInfo] = useState<ShareInfo | null>(null);
  const [error, setError] = useState("");
  const [pick, setPick] = useState(0);
  const [copied, setCopied] = useState(false);

  const load = useCallback(async () => {
    setError("");
    try {
      setInfo(await api.share());
    } catch (e) {
      setError((e as Error).message);
    }
  }, []);

  useEffect(() => {
    if (!open) return;
    setInfo(null);
    setPick(0);
    setCopied(false);
    void load();
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && setOpen(false);
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, load, setOpen]);

  if (!open) return null;
  const urls = info?.enabled ? info.urls : [];
  const url = urls[Math.min(pick, urls.length - 1)];

  const reset = async () => {
    try {
      setInfo(await api.resetShare());
      setCopied(false);
    } catch (e) {
      setError((e as Error).message);
    }
  };
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(url);
      setCopied(true);
    } catch {
      /* the link is shown below to copy by hand */
    }
  };

  return (
    <div className="scrim top" onMouseDown={(e) => e.target === e.currentTarget && setOpen(false)}>
      <div className="dialog share" role="dialog" aria-modal="true" aria-label="Open on phone">
        <header>
          <h2>Open on phone</h2>
          <p className="muted">Your phone and this PC need to be on the same Wi-Fi. Logs never leave this network.</p>
        </header>

        {error && (
          <div className="callout" role="alert">
            {error}
          </div>
        )}

        {info && !info.enabled && (
          <div className="callout" role="status">
            <strong>Phone access is off.</strong> Close this window, then start the tool with{" "}
            <code>Log Evaluation Tool (phone).bat</code> instead of the usual one.
          </div>
        )}

        {info?.enabled && urls.length === 0 && (
          <div className="callout" role="alert">
            This PC does not seem to be on a network. Connect to Wi-Fi or a hotspot and check again.
          </div>
        )}

        {url && (
          <>
            <Code text={url} />
            <p className="muted small center">Scan with the phone camera, then open the link it shows.</p>
            {urls.length > 1 && (
              <label className="field">
                <span className="muted small">Network</span>
                <select value={pick} onChange={(e) => setPick(Number(e.target.value))}>
                  {urls.map((u, i) => (
                    <option key={u} value={i}>
                      {new URL(u).hostname}
                    </option>
                  ))}
                </select>
              </label>
            )}
            <div className="share-link">
              <code>{url}</code>
              <button className="btn sm" onClick={() => void copy()}>
                {copied ? "Copied" : "Copy"}
              </button>
            </div>
            <details className="small muted">
              <summary>Nothing loads on the phone?</summary>
              <ul>
                <li>Windows asks once whether to allow Python on the network. Choose Private networks.</li>
                <li>Hotel, campus and guest Wi-Fi often stop devices seeing each other. A phone hotspot works.</li>
                <li>Use the link as shown. It carries a key, so only people you give it to can open the tool.</li>
              </ul>
            </details>
          </>
        )}

        <footer>
          {info?.enabled && (
            <button className="btn ghost" onClick={() => void reset()} title="Signs out every phone that used the old link">
              New link
            </button>
          )}
          <button className="btn primary" onClick={() => setOpen(false)}>
            Done
          </button>
        </footer>
      </div>
    </div>
  );
}
