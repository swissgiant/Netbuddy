import { useState } from "react";
import type { PwImportSummary, PwPreviewRow } from "../api";
import { importPasswordstate, previewPasswordstate } from "../api";

/** Einträge einer Passwordstate-Liste als NetBuddy-Credentials übernehmen (Vorschau → Import). */
export function PasswordstateImport({ onImported }: { onImported: () => void }) {
  const [listId, setListId] = useState("");
  const [rows, setRows] = useState<PwPreviewRow[] | null>(null);
  const [summary, setSummary] = useState<PwImportSummary | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const run = async (key: string, fn: () => Promise<void>) => {
    setBusy(key);
    setError(null);
    try {
      await fn();
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(null);
    }
  };

  const doPreview = () =>
    run("preview", async () => {
      setSummary(null);
      setRows(await previewPasswordstate(listId.trim()));
    });
  const doImport = () =>
    run("import", async () => {
      const s = await importPasswordstate(listId.trim(), false);
      setSummary(s);
      setRows(null);
      onImported();
    });

  const counts = rows
    ? rows.reduce<Record<string, number>>((acc, r) => ({ ...acc, [r.action]: (acc[r.action] ?? 0) + 1 }), {})
    : {};

  return (
    <div className="card" style={{ marginTop: 16 }}>
      <h3>Aus Passwordstate importieren</h3>
      <p className="muted" style={{ fontSize: 12 }}>
        Braucht eine API-Credential „Passwordstate" (base_url des Servers, api_token = API-Key der
        Passwortliste, optional extra.list_ids). Titel wird Credential-Name, Einträge mit Host/IP werden
        passenden Geräten als SSH-Zugang zugeordnet. Passwörter erscheinen nie im Browser.
      </p>
      <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
        <input placeholder="PasswordListID (leer = extra.list_ids)" value={listId} onChange={(e) => setListId(e.target.value)} />
        <button onClick={doPreview} disabled={busy !== null}>{busy === "preview" ? "Lade…" : "👁 Vorschau"}</button>
        <button
          onClick={() => { if (confirm("Einträge jetzt als Credentials anlegen/aktualisieren?")) void doImport(); }}
          disabled={busy !== null || !rows || rows.length === 0}
        >
          {busy === "import" ? "Importiere…" : "⬇ Importieren"}
        </button>
        {rows && (
          <span className="muted">
            {rows.length} Einträge: {Object.entries(counts).map(([k, v]) => `${v} ${k}`).join(", ")}
          </span>
        )}
      </div>
      {error && <p className="error">{error}</p>}
      {summary && (
        <ul>
          <li>Angelegt ({summary.created.length}): {summary.created.join(", ") || "—"}</li>
          <li>Aktualisiert ({summary.updated.length}): {summary.updated.join(", ") || "—"}</li>
          <li>Geräte verknüpft ({summary.linked.length}): {summary.linked.join("; ") || "—"}</li>
          {summary.skipped.length > 0 && <li className="muted">Übersprungen: {summary.skipped.join(", ")}</li>}
        </ul>
      )}
      {rows && rows.length > 0 && (
        <table style={{ marginTop: 8 }}>
          <thead>
            <tr><th>Aktion</th><th>Titel → Credential</th><th>User</th><th>Host / URL</th><th>Beschreibung</th><th>Geräte</th></tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.password_id} style={{ opacity: r.action === "überspringen" ? 0.5 : 1 }}>
                <td><span className="badge">{r.action}</span></td>
                <td>{r.title}{r.credential_name !== r.title ? ` → ${r.credential_name}` : ""}</td>
                <td>{r.username ?? "—"}{r.has_password ? "" : " (kein Passwort)"}</td>
                <td className="muted">{r.hostname ?? r.url ?? "—"}</td>
                <td className="muted">{r.description ?? ""}</td>
                <td>{r.devices.join(", ") || <span className="muted">—</span>}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}
