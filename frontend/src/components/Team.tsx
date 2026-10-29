import { useCallback, useEffect, useState } from "react";
import { api, type TeamUser } from "../api";
import { useStore } from "../store";

/** Accounts for the people who open the tool from their own computers. Administrators only. */
export function Team() {
  const open = useStore((s) => s.teamOpen);
  const setOpen = useStore((s) => s.setTeamOpen);
  const [users, setUsers] = useState<TeamUser[]>([]);
  const [error, setError] = useState("");
  const [name, setName] = useState("");
  const [password, setPassword] = useState("");
  const [role, setRole] = useState<TeamUser["role"]>("member");
  const [reset, setReset] = useState<string | null>(null);
  const [fresh, setFresh] = useState("");
  const [sure, setSure] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      setUsers(await api.teamUsers());
      setError("");
    } catch (e) {
      setError((e as Error).message);
    }
  }, []);

  useEffect(() => {
    if (!open) return;
    setName("");
    setPassword("");
    setReset(null);
    setSure(null);
    void load();
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && setOpen(false);
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, load, setOpen]);

  if (!open) return null;

  const run = async (job: () => Promise<unknown>) => {
    try {
      await job();
      await load();
      return true;
    } catch (e) {
      setError((e as Error).message);
      return false;
    }
  };

  return (
    <div className="scrim top" onMouseDown={(e) => e.target === e.currentTarget && setOpen(false)}>
      <div className="dialog views" role="dialog" aria-modal="true" aria-label="Team">
        <header>
          <h2>Team</h2>
          <p className="muted">
            People with an account sign in from their own computer and see the logs, views and findings on this PC. Only you, here, can make accounts.
          </p>
        </header>

        {error && (
          <div className="callout" role="alert">
            {error}
          </div>
        )}

        <form
          className="view-save"
          onSubmit={async (e) => {
            e.preventDefault();
            if (await run(() => api.saveTeamUser(name.trim(), { password, role }))) {
              setName("");
              setPassword("");
            }
          }}
        >
          <input type="text" value={name} onChange={(e) => setName(e.target.value)} placeholder="Name" aria-label="Name" maxLength={32} autoComplete="off" />
          <input type="password" value={password} onChange={(e) => setPassword(e.target.value)} placeholder="Password, 10 or more characters" aria-label="Password" autoComplete="new-password" />
          <select value={role} onChange={(e) => setRole(e.target.value as TeamUser["role"])} aria-label="Role">
            <option value="member">Member</option>
            <option value="admin">Administrator</option>
          </select>
          <button className="btn primary" type="submit" disabled={!name.trim() || password.length < 10}>
            Add account
          </button>
        </form>

        <ul className="view-list">
          {users.length === 0 && <li className="lib-empty">No accounts yet. Until you add one, nobody else can open the tool.</li>}
          {users.map((u) => (
            <li key={u.name}>
              <div className="lib-main">
                <span className="lib-name">{u.name}</span>
                <span className="lib-meta">{u.role === "admin" ? "Administrator" : "Member"}</span>
              </div>
              <span className="lib-act">
                {reset === u.name ? (
                  <form
                    className="inline-form"
                    onSubmit={async (e) => {
                      e.preventDefault();
                      if (await run(() => api.saveTeamUser(u.name, { password: fresh }))) {
                        setReset(null);
                        setFresh("");
                      }
                    }}
                  >
                    <input type="password" value={fresh} onChange={(e) => setFresh(e.target.value)} placeholder="New password" aria-label={`New password for ${u.name}`} autoComplete="new-password" />
                    <button className="btn sm primary" type="submit" disabled={fresh.length < 10}>
                      Save
                    </button>
                  </form>
                ) : (
                  <button className="btn sm ghost" onClick={() => setReset(u.name)} title="Also signs them out everywhere">
                    New password
                  </button>
                )}
                <button
                  className="btn sm ghost"
                  onClick={() => void run(() => api.saveTeamUser(u.name, { role: u.role === "admin" ? "member" : "admin" }))}
                  title={u.role === "admin" ? "Make a member" : "Let them manage accounts"}
                >
                  {u.role === "admin" ? "Make member" : "Make administrator"}
                </button>
                {sure === u.name ? (
                  <button
                    className="btn sm danger"
                    onClick={() => {
                      void run(() => api.deleteTeamUser(u.name));
                      setSure(null);
                    }}
                  >
                    Delete
                  </button>
                ) : (
                  <button className="icon-btn" onClick={() => setSure(u.name)} aria-label={`Delete the account ${u.name}`} title="Delete this account">
                    <svg width="16" height="16" viewBox="0 0 16 16" aria-hidden>
                      <path d="M3 4.5h10M6.5 4.5V3h3v1.5M4.5 4.5l.6 8h5.8l.6-8" />
                    </svg>
                  </button>
                )}
              </span>
            </li>
          ))}
        </ul>

        <details className="small muted">
          <summary>Reaching this PC from outside the building</summary>
          <ul>
            <li>
              Install <strong>Tailscale</strong> (free) on this PC and on each teammate's computer, and sign in to the same Tailscale network. They open the address shown under More, Open on phone.
            </li>
            <li>Sign-ins travel unencrypted on a plain network. Tailscale encrypts them. Do not forward the port on your router.</li>
            <li>Logs they add are stored on this PC, so keep it on and keep its disk backed up.</li>
          </ul>
        </details>

        <footer>
          <div className="spacer" />
          <button className="btn primary" onClick={() => setOpen(false)}>
            Done
          </button>
        </footer>
      </div>
    </div>
  );
}
