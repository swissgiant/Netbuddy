import { useEffect, useState } from "react";
import type { CrawlReport, Credential, Device, SuggestedDevice } from "../api";
import {
  createDevice,
  fetchCredentials,
  fetchDevices,
  fetchSuggestions,
  resolveHosts,
  startCrawl,
} from "../api";
import { Th, useSort } from "../sort";

/** Eigene Hauptkategorie: alles, was NEUE Geräte findet (getrennt vom Inventar). */
export function DiscoveryView() {
  const [devices, setDevices] = useState<Device[]>([]);
  const [credentials, setCredentials] = useState<Credential[]>([]);
  const [suggestions, setSuggestions] = useState<SuggestedDevice[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [crawl, setCrawl] = useState({ seed: "", credential: "", depth: 2 });
  const [crawlReport, setCrawlReport] = useState<CrawlReport | null>(null);
  const [crawling, setCrawling] = useState(false);
  const [resolveMsg, setResolveMsg] = useState<string | null>(null);

  const { sorted: sortedSuggestions, sort, toggle } = useSort(suggestions, {
    name: (s) => s.name ?? s.chassis_id ?? s.key,
    sources: (s) => s.sources.join(","),
    seen: (s) => s.seen_on[0] ?? null,
  });

  const reload = () => {
    fetchDevices().then(setDevices).catch((e) => setError(String(e)));
    fetchCredentials().then(setCredentials).catch(() => {});
    fetchSuggestions().then(setSuggestions).catch(() => {});
  };
  useEffect(reload, []);

  const addFromSuggestion = async (s: SuggestedDevice) => {
    setError(null);
    let ip = s.ip_address ?? "";
    if (!ip) {
      ip = prompt(
        `Management-IP für ${s.name ?? s.vendor ?? s.key}? (in keiner Quelle gefunden — LLDP/ARP/DNS)`,
      ) ?? "";
      if (!ip) return;
    }
    try {
      await createDevice({
        hostname: s.name || s.key,
        mgmt_ip: ip,
        vendor: s.vendor ?? "",
        adapter_id: s.guessed_adapter ?? "",
        device_type: s.guessed_adapter === "fortigate" ? "firewall" : "switch",
      });
      reload();
    } catch (e) {
      setError(String(e));
    }
  };

  const runCrawl = async () => {
    if (!crawl.seed || !crawl.credential) return;
    setCrawling(true);
    setCrawlReport(null);
    setError(null);
    try {
      const report = await startCrawl([crawl.seed], crawl.credential, crawl.depth, null);
      setCrawlReport(report);
      reload();
    } catch (e) {
      setError(String(e));
    } finally {
      setCrawling(false);
    }
  };

  const runResolve = async () => {
    setResolveMsg("Löse Namen auf…");
    try {
      const r = await resolveHosts();
      setResolveMsg(`${r.resolved}/${r.hosts} Hosts mit Namen aufgelöst`);
      reload();
    } catch (e) {
      setResolveMsg(String(e));
    }
  };

  return (
    <div className="content">
      <div className="row" style={{ justifyContent: "space-between" }}>
        <h2>Discovery</h2>
        <div className="row" style={{ gap: 8 }}>
          <button className="ghost" onClick={runResolve} title="ARP→IP→DNS korrelieren">
            Namen auflösen
          </button>
          {resolveMsg && <span className="muted" style={{ fontSize: 12 }}>{resolveMsg}</span>}
          <button className="ghost" onClick={reload}>↻</button>
        </div>
      </div>
      {error && <p className="error">{error}</p>}

      <div className="card">
        <h3>Autodiscovery-Crawl <span className="muted" style={{ fontSize: 12 }}>(read-only, über LLDP)</span></h3>
        <div className="row">
          <select value={crawl.seed} onChange={(e) => setCrawl({ ...crawl, seed: e.target.value })}>
            <option value="">Seed-Gerät…</option>
            {devices.map((d) => <option key={d.id} value={d.id}>{d.hostname}</option>)}
          </select>
          <select value={crawl.credential} onChange={(e) => setCrawl({ ...crawl, credential: e.target.value })}>
            <option value="">Discovery-Credential…</option>
            {credentials.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
          </select>
          <label className="muted" style={{ fontSize: 12 }}>
            Tiefe{" "}
            <input type="number" min={0} max={5} value={crawl.depth} style={{ width: 56 }}
              onChange={(e) => setCrawl({ ...crawl, depth: Number(e.target.value) })} />
          </label>
          <button onClick={runCrawl} disabled={!crawl.seed || !crawl.credential || crawling}>
            {crawling ? "läuft…" : "Crawl starten"}
          </button>
        </div>
        {crawlReport && (
          <>
            <p className="muted" style={{ fontSize: 13, marginBottom: 0 }}>
              Ausgelesen: {crawlReport.discovered.length} · Neu aufgenommen: {crawlReport.added.length}
              {crawlReport.added.length > 0 && ` (${crawlReport.added.map((a) => a.hostname).join(", ")})`}
              {crawlReport.errors.length > 0 && ` · Fehler: ${crawlReport.errors.length}`}
            </p>
            {crawlReport.errors.length > 0 && (
              <details style={{ fontSize: 12, marginTop: 6 }}>
                <summary style={{ cursor: "pointer" }} className="error">Fehlerdetails anzeigen</summary>
                <table style={{ marginTop: 4 }}>
                  <thead><tr><th>Gerät</th><th>Fehler</th></tr></thead>
                  <tbody>
                    {crawlReport.errors.map((e, i) => (
                      <tr key={i}>
                        <td>{e.device}</td>
                        <td className="muted" style={{ wordBreak: "break-all" }}>{e.error}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </details>
            )}
          </>
        )}
      </div>

      <div className="card">
        <h3>
          Vorgeschlagene Geräte <span className="badge">{suggestions.length}</span>
          <span className="muted" style={{ fontSize: 12, fontWeight: 400 }}>
            {" "}— aus LLDP + MAC-Tabellen (OUI), zusammengeführt
          </span>
        </h3>
        {suggestions.length === 0 ? (
          <p className="muted">Keine offenen Vorschläge — alles Gefundene ist im Inventar.</p>
        ) : (
          <table>
            <thead>
              <tr>
                <Th k="name" sort={sort} onSort={toggle}>Name</Th>
                <Th k="ip_address" sort={sort} onSort={toggle}>IP</Th>
                <Th k="vendor" sort={sort} onSort={toggle}>Hersteller (MAC)</Th>
                <Th k="guessed_adapter" sort={sort} onSort={toggle}>Profil (geraten)</Th>
                <Th k="sources" sort={sort} onSort={toggle}>Quelle</Th>
                <Th k="seen" sort={sort} onSort={toggle}>gesehen an</Th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {sortedSuggestions.map((s) => (
                <tr key={s.key}>
                  <td>
                    {s.name ?? <span className="muted">{s.chassis_id ?? s.key}</span>}
                    {s.dns_name && s.dns_name.split(".")[0] !== s.name && (
                      <span className="muted"> ({s.dns_name})</span>
                    )}
                  </td>
                  <td className="muted">
                    {s.ip_address ?? "—"}
                    {s.ip_guessed && <span title="aus der Standort-Namensregel geschätzt — prüfen!"> ≈</span>}
                  </td>
                  <td className="muted">{s.vendor ?? "—"}</td>
                  <td>
                    {s.guessed_adapter
                      ? <span className="badge">{s.guessed_adapter}</span>
                      : <span className="muted">?</span>}
                  </td>
                  <td>
                    {s.sources.map((src) => (
                      <span key={src} className="badge" style={{ marginRight: 3 }}>{src}</span>
                    ))}
                  </td>
                  <td className="muted">{s.seen_on.join(", ")}</td>
                  <td>
                    <button onClick={() => addFromSuggestion(s)}
                      title="Als Gerät anlegen (IP aus LLDP/ARP/DNS, Profil geraten)">
                      + Hinzufügen
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
        <p className="muted" style={{ fontSize: 12 }}>
          Quelle „lldp" = Nachbar meldet sich selbst; „mac" = nur am Hersteller-OUI in den
          MAC-Tabellen erkannt (LLDP dort vermutlich aus). ≈ = IP aus der Standort-Namensregel
          geschätzt. Der Standort wird beim Anlegen automatisch aus den IP-Segmenten abgeleitet.
        </p>
      </div>
    </div>
  );
}
