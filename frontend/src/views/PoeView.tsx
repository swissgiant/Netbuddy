import { useEffect, useState } from "react";
import type {
  ApLocationInfo,
  ClientLocation,
  PoeEventRow,
  RecoverResult,
  StuckCandidate,
} from "../api";
import {
  fetchApLocations,
  fetchClients,
  fetchPoeEvents,
  fetchStuck,
  recoverAllStuck,
  recoverPort,
} from "../api";

function statusBadge(status: string) {
  const color =
    status === "online" ? "var(--ok, green)" : status === "offline" ? "var(--err, #c0392b)" : "gray";
  return <span style={{ color }}>{status}</span>;
}

export function PoeView() {
  const [aps, setAps] = useState<ApLocationInfo[]>([]);
  const [clients, setClients] = useState<ClientLocation[]>([]);
  const [stuck, setStuck] = useState<StuckCandidate[] | null>(null);
  const [events, setEvents] = useState<PoeEventRow[]>([]);
  const [busy, setBusy] = useState<string | null>(null);
  const [msg, setMsg] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  // Initial: sticky DB-Stand (ms-schnell). Live-Refresh (Cloud + 4 Controller, dauert
  // Sekunden) nur auf expliziten Klick.
  const loadAps = (refresh = false) =>
    fetchApLocations(refresh)
      .then(setAps)
      .catch((e) => setError(String(e)));
  const loadEvents = () =>
    fetchPoeEvents()
      .then(setEvents)
      .catch((e) => setError(String(e)));

  useEffect(() => {
    void loadAps();
    void loadEvents();
    // Client-Detection braucht den lokalen Controller — still ignorieren, falls nicht da.
    fetchClients()
      .then(setClients)
      .catch(() => setClients([]));
  }, []);

  const scanStuck = async () => {
    setBusy("scan");
    setMsg(null);
    setError(null);
    try {
      const s = await fetchStuck(true);
      setStuck(s);
      setMsg(`${s.length} hängende AP-Port(s) gefunden.`);
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(null);
    }
  };

  const summarize = (results: RecoverResult[]) => {
    const ok = results.filter((r) => r.action === "recovered").length;
    const rl = results.filter((r) => r.action === "skipped_ratelimit").length;
    setMsg(
      `Recovery: ${ok} erholt, ${results.length - ok - rl} ohne Änderung, ` +
        `${rl} per Rate-Limit übersprungen.`,
    );
  };

  const recoverAll = async () => {
    setBusy("recover");
    setMsg(null);
    setError(null);
    try {
      summarize(await recoverAllStuck());
      await scanStuck();
      await loadEvents();
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(null);
    }
  };

  const recoverOne = async (c: StuckCandidate) => {
    setBusy(`${c.device_id}:${c.port}`);
    setMsg(null);
    setError(null);
    try {
      const r = await recoverPort(c.device_id, c.port);
      setMsg(`${c.hostname} ${c.port}: ${r.action} (${r.status_before} → ${r.status_after ?? "?"})`);
      await scanStuck();
      await loadEvents();
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(null);
    }
  };

  return (
    <div style={{ maxWidth: 960 }}>
      <h2>🔌 PoE / AP-Recovery</h2>
      <p className="muted">
        APs verlieren auf Dell-PoE-Switches manchmal die Speisung (PoE <code>Fault</code>, Link down,
        in UniFi offline). „Stuck-Ports suchen" scannt die PoE-Switches live und kreuzt sie mit der
        AP-Karte. <strong>Erholen</strong> bouncet den Port (shut/no shut) — rate-limitiert &amp;
        Audit-geloggt. Selbst-versorgte Geräte mit Link bleiben unangetastet.
      </p>

      {msg && <p style={{ color: "var(--ok, green)" }}>{msg}</p>}
      {error && <p className="error">{error}</p>}

      <div style={{ display: "flex", gap: 8, marginBottom: 12 }}>
        <button onClick={scanStuck} disabled={busy !== null}>
          {busy === "scan" ? "Scanne…" : "🔍 Stuck-Ports suchen (Live)"}
        </button>
        <button
          onClick={recoverAll}
          disabled={busy !== null || !stuck || stuck.length === 0}
        >
          {busy === "recover" ? "Erhole…" : "⚡ Alle hängenden erholen"}
        </button>
      </div>

      {stuck !== null && (
        <table>
          <thead>
            <tr>
              <th>Switch</th>
              <th>Port</th>
              <th>PoE</th>
              <th>Link</th>
              <th>AP</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            {stuck.map((c) => (
              <tr key={`${c.device_id}:${c.port}`}>
                <td>{c.hostname}</td>
                <td>{c.port}</td>
                <td>{c.poe_status}</td>
                <td>{c.link_up ? "up" : "down"}</td>
                <td>{c.ap_name ?? c.ap_mac}</td>
                <td>
                  <button
                    onClick={() => recoverOne(c)}
                    disabled={busy !== null}
                  >
                    {busy === `${c.device_id}:${c.port}` ? "…" : "Erholen"}
                  </button>
                </td>
              </tr>
            ))}
            {stuck.length === 0 && (
              <tr>
                <td colSpan={6} className="muted">
                  Keine hängenden AP-Ports — alles gut. 🎉
                </td>
              </tr>
            )}
          </tbody>
        </table>
      )}

      <h3 style={{ marginTop: 24 }}>
        📍 AP-Verortung{" "}
        <button className="ghost" onClick={() => void loadAps(true)}
          title="Live von UniFi-Cloud + lokalen Controllern neu aufbauen (dauert einige Sekunden)">
          ↻ live aktualisieren
        </button>
      </h3>
      <p className="muted">
        Welcher AP hängt an welchem Switch-Port (UniFi-Cloud × LLDP/MAC). <strong>Mesh</strong> =
        Verdacht auf Wireless-Uplink (online ohne Wired-Port oder mehrere APs an einem Port).
      </p>
      <table>
        <thead>
          <tr>
            <th>AP</th>
            <th>Modell</th>
            <th>Status</th>
            <th>Switch / Port</th>
            <th>Mesh</th>
          </tr>
        </thead>
        <tbody>
          {aps.map((a) => (
            <tr key={a.ap_mac}>
              <td>{a.ap_name || a.ap_mac}</td>
              <td>{a.ap_model ?? ""}</td>
              <td>{statusBadge(a.status)}</td>
              <td>{a.device_hostname ? `${a.device_hostname} / ${a.port}` : "—"}</td>
              <td title={a.mesh_reason ?? ""}>{a.mesh ? "⚠️ mesh" : ""}</td>
            </tr>
          ))}
          {aps.length === 0 && (
            <tr>
              <td colSpan={5} className="muted">
                Keine AP-Daten — UniFi-Cloud-Credential nötig + Discovery für LLDP/MAC.
              </td>
            </tr>
          )}
        </tbody>
      </table>

      {clients.length > 0 && (
        <>
          <h3 style={{ marginTop: 24 }}>🔗 Clients ({clients.length})</h3>
          <p className="muted">
            Welcher Client hängt wo (lokaler UniFi-Controller): wired am Switch-Port, wireless am AP.
          </p>
          <table>
            <thead>
              <tr>
                <th>Client</th>
                <th>IP</th>
                <th>Typ</th>
                <th>hängt an</th>
                <th>Standort</th>
              </tr>
            </thead>
            <tbody>
              {clients.map((c) => (
                <tr key={c.mac}>
                  <td>{c.hostname || c.mac}</td>
                  <td>{c.ip ?? ""}</td>
                  <td>{c.kind === "wired" ? "🔌 wired" : "📶 wireless"}</td>
                  <td>
                    {c.via_device ?? "?"}
                    {c.port != null ? ` / Port ${c.port}` : ""}
                  </td>
                  <td>{c.site}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </>
      )}

      <h3 style={{ marginTop: 24 }}>🧾 Recovery-Historie</h3>
      <table>
        <thead>
          <tr>
            <th>Zeit</th>
            <th>Port</th>
            <th>AP</th>
            <th>Aktion</th>
            <th>vorher → nachher</th>
            <th>von</th>
          </tr>
        </thead>
        <tbody>
          {events.map((e, i) => (
            <tr key={i}>
              <td>{new Date(e.created_at).toLocaleString()}</td>
              <td>{e.port}</td>
              <td>{e.ap_name ?? ""}</td>
              <td>{e.action}</td>
              <td>
                {e.status_before ?? "?"} → {e.status_after ?? "?"}
              </td>
              <td>{e.actor ?? ""}</td>
            </tr>
          ))}
          {events.length === 0 && (
            <tr>
              <td colSpan={6} className="muted">
                Noch keine Recovery-Ereignisse.
              </td>
            </tr>
          )}
        </tbody>
      </table>
    </div>
  );
}
