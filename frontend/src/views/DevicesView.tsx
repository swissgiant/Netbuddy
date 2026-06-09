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

  const reload = () => {
    fetchDevices().then(setDevices).catch((e) => setError(String(e)));
    fetchSites().then(setSites).catch(() => {});
    fetchCredentials().then(setCredentials).catch(() => {});
    fetchAdapters().then((a) => setAdapterIds(a.map((x) => x.adapter_id).sort())).catch(() => {});
    fetchSuggestions().then(setSuggestions).catch(() => {});
    fetchDeviceCredentials().then(setLinks).catch(() => {});
  };
  useEffect(reload, []);

  const siteName = (id: string | null) => sites.find((s) => s.id === id)?.name ?? "—";
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
          <p className="muted" style={{ fontSize: 13, marginBottom: 0 }}>
            Ausgelesen: {crawlReport.discovered.length} · Neu aufgenommen: {crawlReport.added.length}
            {crawlReport.added.length > 0 && ` (${crawlReport.added.map((a) => a.hostname).join(", ")})`}
            {crawlReport.errors.length > 0 && ` · Fehler: ${crawlReport.errors.length}`}
          </p>
        )}
      </div>

      {suggestions.length > 0 && (
        <div className="card">
          <h3>Vorgeschlagen (aus LLDP) <span className="badge">{suggestions.length}</span></h3>
          <table>
            <thead><tr><th>System-Name</th><th>Chassis</th><th>gesehen an</th><th></th></tr></thead>
            <tbody>
              {suggestions.map((s) => (
                <tr key={s.chassis_id}>
                  <td>{s.system_name ?? <span className="muted">unbekannt</span>}</td>
                  <td className="muted">{s.chassis_id}</td>
                  <td className="muted">{s.seen_on.join(", ")}</td>
                  <td>
                    <button className="ghost" onClick={() => setForm({ ...EMPTY, hostname: s.system_name ?? "" })}>
                      ins Formular
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
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
                      <a style={{ cursor: "pointer" }} onClick={() => setSelected(open ? null : d.id)}>
                        {open ? "▾" : "▸"} {d.hostname}
                      </a>
                    </td>
                    <td>{d.mgmt_ip}</td>
                    <td><span className="badge">{d.device_type}</span></td>
                    <td>{d.vendor}</td>
                    <td>{d.adapter_id}</td>
                    <td className="muted">{siteName(d.site_id)}</td>
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
                    <td><button className="danger" onClick={() => remove(d.id)}>entfernen</button></td>
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
