import { useEffect, useState } from "react";
import type { AuthUser } from "../api";
import { authLogin, authSetup, fetchSetupStatus } from "../api";

export function LoginView({ onLogin }: { onLogin: (user: AuthUser) => void }) {
  const [setupNeeded, setSetupNeeded] = useState<boolean | null>(null);
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetchSetupStatus()
      .then((s) => setSetupNeeded(s.setup_needed))
      .catch((e) => setError(String(e)));
  }, []);

  const submit = async () => {
    setError(null);
    try {
      const result = setupNeeded
        ? await authSetup(username, password)
        : await authLogin(username, password);
      onLogin(result.user);
    } catch {
      setError(setupNeeded ? "Setup fehlgeschlagen" : "Login fehlgeschlagen");
    }
  };

  return (
    <div style={{ display: "grid", placeItems: "center", height: "100vh" }}>
      <div className="card" style={{ width: 340 }}>
        <h2 style={{ marginTop: 0 }}>NetBuddy</h2>
        {setupNeeded === null ? (
          <p className="muted">Lade…</p>
        ) : (
          <>
            <p className="muted">
              {setupNeeded ? "Erst-Einrichtung: ersten Admin anlegen" : "Anmelden"}
            </p>
            <div style={{ display: "grid", gap: 8 }}>
              <input
                placeholder="Benutzername"
                value={username}
                onChange={(e) => setUsername(e.target.value)}
                autoFocus
              />
              <input
                placeholder="Passwort"
                type="password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                onKeyDown={(e) => e.key === "Enter" && submit()}
              />
              <button onClick={submit} disabled={!username || !password}>
                {setupNeeded ? "Admin anlegen" : "Anmelden"}
              </button>
              {error && <p className="error">{error}</p>}
            </div>
          </>
        )}
      </div>
    </div>
  );
}
