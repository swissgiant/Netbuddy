import { useEffect, useState } from "react";
import type { AuthUser } from "../api";
import { authLogin, authSetup, fetchOidcStatus, fetchSetupStatus } from "../api";

const SSO_ERRORS: Record<string, string> = {
  token: "Microsoft-Anmeldung fehlgeschlagen.",
  claims: "Microsoft-Konto lieferte keine Kennung.",
  norole: "Dein Konto ist in keiner NetBuddy-Gruppe — kein Zugriff.",
};

export function LoginView({ onLogin }: { onLogin: (user: AuthUser) => void }) {
  const [setupNeeded, setSetupNeeded] = useState<boolean | null>(null);
  const [ssoEnabled, setSsoEnabled] = useState(false);
  const [showLocal, setShowLocal] = useState(false);
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetchSetupStatus()
      .then((s) => setSetupNeeded(s.setup_needed))
      .catch((e) => setError(String(e)));
    fetchOidcStatus()
      .then((s) => setSsoEnabled(s.enabled))
      .catch(() => setSsoEnabled(false));
    const ssoErr = new URLSearchParams(window.location.search).get("sso_error");
    if (ssoErr) setError(SSO_ERRORS[ssoErr] ?? "SSO-Anmeldung fehlgeschlagen.");
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

  const ssoLogin = () => {
    window.location.href = "/auth/login/entra";
  };

  // Lokales Konto: bei aktivem SSO nur Break-Glass (sekundär, eingeklappt),
  // sonst die normale primäre Anmeldung.
  const localForm = (
    <div style={{ display: "grid", gap: 8 }}>
      <input
        placeholder="Benutzername"
        value={username}
        onChange={(e) => setUsername(e.target.value)}
        autoFocus={!ssoEnabled || setupNeeded === true}
      />
      <input
        placeholder="Passwort"
        type="password"
        value={password}
        onChange={(e) => setPassword(e.target.value)}
        onKeyDown={(e) => e.key === "Enter" && submit()}
      />
      <button
        className={ssoEnabled && !setupNeeded ? "ghost" : ""}
        onClick={submit}
        disabled={!username || !password}
      >
        {setupNeeded ? "Admin anlegen" : "Anmelden"}
      </button>
    </div>
  );

  const ssoIsDefault = ssoEnabled && !setupNeeded;

  return (
    <div style={{ display: "grid", placeItems: "center", height: "100vh" }}>
      <div className="card" style={{ width: 340 }}>
        <h2 style={{ marginTop: 0 }}>NetBuddy</h2>
        {setupNeeded === null ? (
          <p className="muted">Lade…</p>
        ) : ssoIsDefault ? (
          <>
            <p className="muted">Anmelden</p>
            <div style={{ display: "grid", gap: 8 }}>
              {/* Microsoft = primäre Standard-Anmeldung */}
              <button onClick={ssoLogin} autoFocus>
                🪟 Mit Microsoft anmelden
              </button>
              {error && <p className="error">{error}</p>}
              {/* Break-Glass: lokales Konto, zurückhaltend hinter einem Link */}
              {showLocal ? (
                <div style={{ marginTop: 4 }}>{localForm}</div>
              ) : (
                <button
                  className="link"
                  style={{
                    background: "none",
                    border: "none",
                    padding: "6px 0 0",
                    fontSize: 12,
                    cursor: "pointer",
                    color: "var(--muted, #888)",
                  }}
                  onClick={() => setShowLocal(true)}
                >
                  Mit lokalem Konto anmelden
                </button>
              )}
            </div>
          </>
        ) : (
          <>
            <p className="muted">
              {setupNeeded ? "Erst-Einrichtung: ersten Admin anlegen" : "Anmelden"}
            </p>
            {localForm}
            {error && <p className="error">{error}</p>}
          </>
        )}
      </div>
    </div>
  );
}
