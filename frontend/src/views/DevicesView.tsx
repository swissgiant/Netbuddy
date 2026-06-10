import { Fragment, useEffect, useState } from "react";
import type {
  Credential,
  Device,
  DeviceCreate,
  DeviceCredentialRow,
  Site,
  SuggestedDevice,
} from "../api";
import type { CrawlReport } from "../api";
import {
  createDevice,
  deleteDevice,
  fetchAdapters,
  fetchCredentials,
  fetchDeviceCredentials,
  fetchDevices,
  fetchSites,
  fetchSuggestions,
  linkCredential,
  startCrawl,
  unlinkCredential,
  updateDevice,
} from "../api";
import { DeviceIcon } from "../icons";
import { DeviceDetail } from "./DeviceDetail";

const DEVICE_TYPES = ["switch", "firewall", "router", "ap", "other"];
const EMPTY: DeviceCreate = {
  hostname: "",
  mgmt_ip: "",
  vendor: "",
  adapter_id: "",
  device_type: "switch",
  site_id: null,
  credential_id: null,
};

export function DevicesView() {
  const [devices, setDevices] = useState<Device[]>([]);
  const [sites, setSites] = useState<Site[]>([]);
  const [credentials, setCredentials] = useState<Credential[]>([]);
  const [adapterIds, setAdapterIds] = useState<string[]>([]);
  const [suggestions, setSuggestions] = useState<SuggestedDevice[]>([]);
  const [links, setLinks] = useState<DeviceCredentialRow[]>([]);
  const [form, setForm] = useState<DeviceCreate>(EMPTY);
  const [error, setError] = useState<string | null>(null);
  const [crawl, setCrawl] = useState({ seed: "", credential: "", depth: 2 });
  const [crawlReport, setCrawlReport] = useState<CrawlReport | null>(null);
  const [crawling, setCrawling] = useState(false);
  const [selected, setSelected] = useState<string | null>(null);
  const [edit, setEdit] = useState<{ id: string; hostname: string; mgmt_ip: string } | null>(null);

  const reload = () => {
    fetchDevices().then(setDevices).catch((e) => setError(String(e)));
    fetchSites().then(setSites).catch(() => {});
    fetchCredentials().then(setCredentials).catch(() => {});
    fetchAdapters().then((a) => setAdapterIds(a.map((x) => x.adapter_id).sort())).catch(() => {});
    fetchSuggestions().then(setSuggestions).catch(() => {});
    fetchDeviceCredentials().then(setLinks).catch(() => {});
  };
  useEffect(reload, []);

  const linksFor = (deviceId: string) => links.filter((l) => l.device_id === deviceId);

  const submit = async () => {
    setError(null);
    try {
      await createDevice({ ...form, adapter_id: form.adapter_id || adapterIds[0] || "" });
      setForm(EMPTY);
      reload();
    } catch (e) {
      setError(String(e));
    }
  };

  const remove = async (id: string) => {
    if (!confirm("Gerät wirklich entfernen?")) return;
    await deleteDevice(id);
    reload();
  };

  // 1-Klick-Anlage aus einem Vorschlag: IP aus LLDP/ARP/DNS, Profil geraten; Prompt als Fallback.
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

  // Inline-Update in der Liste (Standort/Adapter/Name/IP) — kein Löschen+Neuanlegen.
  const patch = async (id: string, body: Record<string, string | null>) => {
    setError(null);
    try {
      await updateDevice(id, body);
      reload();
    } catch (e) {
      setError(String(e));
    }
  };
  const saveEdit = async () => {
    if (!edit) return;
    await patch(edit.id, { hostname: edit.hostname, mgmt_ip: edit.mgmt_ip });
    setEdit(null);
  };

  const attach = async (deviceId: string, credentialId: string) => {
    if (!credentialId) return;
    await linkCredential(deviceId, credentialId);
    reload();
  };
  const detach = async (deviceId: string, credentialId: string, protocol: string) => {
    await unlinkCredential(deviceId, credentialId, protocol);
    reload();
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

  const set = (k: keyof DeviceCreate, v: string) => setForm({ ...form, [k]: v || null });

  return (
    <div className="content">
      <h2>Geräte</h2>
      {error && <p className="error">{error}</p>}

      <div className="card">
        <h3>Gerät hinzufügen</h3>
        <div className="row">
          <input placeholder="hostname" value={form.hostname} onChange={(e) => set("hostname", e.target.value)} />
          <input placeholder="mgmt_ip" value={form.mgmt_ip} onChange={(e) => set("mgmt_ip", e.target.value)} />
          <input placeholder="vendor" value={form.vendor} onChange={(e) => set("vendor", e.target.value)} />
          <select value={form.adapter_id} onChange={(e) => set("adapter_id", e.target.value)}>
            <option value="">adapter…</option>
            {adapterIds.map((a) => <option key={a} value={a}>{a}</option>)}
          </select>
          <select value={form.device_type} onChange={(e) => set("device_type", e.target.value)}>
            {DEVICE_TYPES.map((t) => <option key={t} value={t}>{t}</option>)}
          </select>
          <select value={form.site_id ?? ""} onChange={(e) => set("site_id", e.target.value)}>
            <option value="">— Standort —</option>
            {sites.map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}
          </select>
          <select value={form.credential_id ?? ""} onChange={(e) => set("credential_id", e.target.value)}>
            <option value="">— Credential —</option>
            {credentials.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
          </select>
          <button onClick={submit} disabled={!form.hostname || !form.mgmt_ip}>Hinzufügen</button>
        </div>
      </div>

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
                <summary style={{ cursor: "pointer" }} className="error">
                  Fehlerdetails anzeigen
                </summary>
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

      {suggestions.length > 0 && (
        <div className="card">
          <h3>
            Vorgeschlagene Geräte <span className="badge">{suggestions.length}</span>
            <span className="muted" style={{ fontSize: 12, fontWeight: 400 }}>
              {" "}— aus LLDP + MAC-Tabellen (OUI), zusammengeführt
            </span>
          </h3>
          <table>
            <thead>
              <tr>
                <th>Name</th><th>IP</th><th>Hersteller (MAC)</th><th>Profil (geraten)</th>
                <th>Quelle</th><th>gesehen an</th><th></th>
              </tr>
            </thead>
            <tbody>
              {suggestions.map((s) => (
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
          <p className="muted" style={{ fontSize: 12 }}>
            Quelle „lldp" = Nachbar meldet sich selbst; „mac" = nur am Hersteller-OUI in den
            MAC-Tabellen erkannt (LLDP dort vermutlich aus — nach dem Anlegen im Geräte-Detail
            aktivieren). Standort/Adapter/IP sind nach dem Anlegen in der Liste änderbar.
          </p>
        </div>
      )}

      <div className="card">
        <div className="row" style={{ justifyContent: "space-between" }}>
          <h3 style={{ margin: 0 }}>Inventar <span className="badge">{devices.length}</span></h3>
          <button className="ghost" onClick={reload}>↻</button>
        </div>
        <table>
          <thead>
            <tr>
              <th></th><th>Hostname</th><th>IP</th><th>Typ</th><th>Vendor</th><th>Adapter</th>
              <th>Standort</th><th>Credentials</th><th></th>
            </tr>
          </thead>
          <tbody>
            {devices.map((d) => {
              const myLinks = linksFor(d.id);
              const linkedIds = new Set(myLinks.map((l) => l.credential_id));
              const open = selected === d.id;
              return (
                <Fragment key={d.id}>
                  <tr className={open ? "selected" : ""}>
                    <td style={{ color: "var(--muted)" }}>
                      <DeviceIcon type={d.device_type} size={18} title={d.device_type} />
                    </td>
                    <td>
                      {edit?.id === d.id ? (
                        <input value={edit.hostname} style={{ width: 140 }}
                          onChange={(e) => setEdit({ ...edit, hostname: e.target.value })} />
                      ) : (
                        <a style={{ cursor: "pointer" }} onClick={() => setSelected(open ? null : d.id)}>
                          {open ? "▾" : "▸"} {d.hostname}
                        </a>
                      )}
                    </td>
                    <td>
                      {edit?.id === d.id ? (
                        <input value={edit.mgmt_ip} style={{ width: 120 }}
                          onChange={(e) => setEdit({ ...edit, mgmt_ip: e.target.value })} />
                      ) : (
                        d.mgmt_ip
                      )}
                    </td>
                    <td><span className="badge">{d.device_type}</span></td>
                    <td>{d.vendor || <span className="muted">—</span>}</td>
                    <td>
                      <select value={d.adapter_id} onChange={(e) => patch(d.id, { adapter_id: e.target.value })}>
                        <option value="">— Profil —</option>
                        {adapterIds.map((a) => <option key={a} value={a}>{a}</option>)}
                      </select>
                    </td>
                    <td>
                      <select value={d.site_id ?? ""}
                        onChange={(e) => patch(d.id, { site_id: e.target.value || null })}>
                        <option value="">— kein —</option>
                        {sites.map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}
                      </select>
                    </td>
                    <td>
                      {myLinks.map((l) => (
                        <span key={l.credential_id + l.protocol} className="badge" style={{ marginRight: 4 }}>
                          {l.credential_name} ({l.protocol}){" "}
                          <a
                            style={{ cursor: "pointer", color: "var(--danger)" }}
                            onClick={() => detach(d.id, l.credential_id, l.protocol)}
                            title="lösen"
                          >
                            ✕
                          </a>
                        </span>
                      ))}
                      <select value="" onChange={(e) => attach(d.id, e.target.value)} style={{ marginTop: 2 }}>
                        <option value="">+ zuweisen…</option>
                        {credentials.filter((c) => !linkedIds.has(c.id)).map((c) => (
                          <option key={c.id} value={c.id}>{c.name}</option>
                        ))}
                      </select>
                    </td>
                    <td style={{ whiteSpace: "nowrap" }}>
                      {edit?.id === d.id ? (
                        <>
                          <button onClick={saveEdit} title="speichern">✓</button>{" "}
                          <button className="ghost" onClick={() => setEdit(null)} title="abbrechen">✕</button>
                        </>
                      ) : (
                        <>
                          <button className="ghost"
                            onClick={() => setEdit({ id: d.id, hostname: d.hostname, mgmt_ip: d.mgmt_ip })}
                            title="Name/IP bearbeiten">✎</button>{" "}
                          <button className="danger" onClick={() => remove(d.id)}>entfernen</button>
                        </>
                      )}
                    </td>
                  </tr>
                  {open && (
                    <tr className="detail-row">
                      <td colSpan={9}><DeviceDetail device={d} /></td>
                    </tr>
                  )}
                </Fragment>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}
