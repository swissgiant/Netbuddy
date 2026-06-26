import { useEffect, useState } from "react";
import type { UnifiHost, UnifiImportSummary } from "../api";
import { fetchUnifiHosts, runUnifiImport, syncUnifiHosts, toggleUnifiHost } from "../api";

export function UnifiView() {
  const [hosts, setHosts] = useState<UnifiHost[]>([]);
  const [busy, setBusy] = useState<string | null>(null);
  const [msg, setMsg] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = () =>
    fetchUnifiHosts()
      .then(setHosts)
      .catch((e) => setError(String(e)));

  useEffect(() => {
    void load();
  }, []);

  const sync = async () => {
    setBusy("sync");
    setMsg(null);
    setError(null);
    try {
      setHosts(await syncUnifiHosts());
      setMsg("Hosts aus der Cloud synchronisiert.");
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(null);
    }
  };

  const doImport = async () => {
    setBusy("import");
    setMsg(null);
    setError(null);
    try {
      const s: UnifiImportSummary = await runUnifiImport();
      setMsg(
        `Import: ${s.created} neu, ${s.updated} aktualisiert, ` +
          `${s.skipped_disabled} übersprungen (deaktiviert), ${s.skipped_other} andere.`,
      );
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(null);
    }
  };

  const toggle = async (h: UnifiHost) => {
    try {
      const updated = await toggleUnifiHost(h.host_id, !h.enabled);
      setHosts((hs) => hs.map((x) => (x.host_id === updated.host_id ? updated : x)));
    } catch (e) {
      setError(String(e));
    }
  };

  return (
    <div style={{ maxWidth: 720 }}>
      <h2>📶 UniFi (Cloud)</h2>
      <p className="muted">
        Geräte kommen über die UniFi Site Manager Cloud-API (<code>api.ui.com</code>). Pro
        Konsole/Host ein Schalter — <strong>deaktivierte Hosts werden beim Import übersprungen</strong>{" "}
        (z.B. Standorte ohne Netzanbindung). „Synchronisieren" lädt die Hostliste, „Import" legt
        Switches &amp; APs aktiver Hosts als Geräte an.
      </p>

      <div style={{ display: "flex", gap: 8, marginBottom: 12 }}>
        <button onClick={sync} disabled={busy !== null}>
          {busy === "sync" ? "Synchronisiere…" : "↻ Hosts synchronisieren"}
        </button>
        <button onClick={doImport} disabled={busy !== null}>
          {busy === "import" ? "Importiere…" : "⬇ Switches & APs importieren"}
        </button>
      </div>
      {msg && <p style={{ color: "var(--ok, green)" }}>{msg}</p>}
      {error && <p className="error">{error}</p>}

      <table>
        <thead>
          <tr>
            <th>UniFi-Host / Konsole</th>
            <th>Aktiv</th>
          </tr>
        </thead>
        <tbody>
          {hosts.map((h) => (
            <tr key={h.host_id}>
              <td>{h.name}</td>
              <td>
                <label style={{ display: "flex", gap: 6, alignItems: "center" }}>
                  <input type="checkbox" checked={h.enabled} onChange={() => toggle(h)} />
                  {h.enabled ? "aktiv" : "deaktiviert"}
                </label>
              </td>
            </tr>
          ))}
          {hosts.length === 0 && (
            <tr>
              <td colSpan={2} className="muted">
                Noch keine Hosts — auf „Hosts synchronisieren" klicken.
              </td>
            </tr>
          )}
        </tbody>
      </table>
    </div>
  );
}
