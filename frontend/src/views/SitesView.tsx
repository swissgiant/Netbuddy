import { useEffect, useState } from "react";
import type { Device, Site } from "../api";
import {
  addSubnet,
  createSite,
  deleteSite,
  deleteSubnet,
  fetchDevices,
  fetchSites,
  updateSite,
} from "../api";

export function SitesView() {
  const [sites, setSites] = useState<Site[]>([]);
  const [devices, setDevices] = useState<Device[]>([]);
  const [form, setForm] = useState({ name: "", code: "", description: "", template: "" });
  const [newCidr, setNewCidr] = useState<Record<string, string>>({});
  const [error, setError] = useState<string | null>(null);

  const reload = () => {
    fetchSites().then(setSites).catch((e) => setError(String(e)));
    fetchDevices().then(setDevices).catch(() => {});
  };
  useEffect(reload, []);

  const deviceCount = (siteId: string) => devices.filter((d) => d.site_id === siteId).length;

  const submit = async () => {
    setError(null);
    try {
      await createSite({
        name: form.name,
        code: form.code || undefined,
        description: form.description || undefined,
        mgmt_ip_template: form.template || undefined,
      });
      setForm({ name: "", code: "", description: "", template: "" });
      reload();
    } catch (e) {
      setError(String(e));
    }
  };

  const remove = async (s: Site) => {
    if (!confirm(`Standort „${s.name}" entfernen?`)) return;
    setError(null);
    try {
      await deleteSite(s.id);
      reload();
    } catch (e) {
      setError(String(e));
    }
  };

  const saveTemplate = async (s: Site, value: string) => {
    setError(null);
    try {
      await updateSite(s.id, { mgmt_ip_template: value || null });
      reload();
    } catch (e) {
      setError(String(e));
    }
  };

  const addCidr = async (s: Site) => {
    const cidr = (newCidr[s.id] ?? "").trim();
    if (!cidr) return;
    setError(null);
    try {
      await addSubnet(s.id, cidr);
      setNewCidr({ ...newCidr, [s.id]: "" });
      reload();
    } catch (e) {
      setError(String(e));
    }
  };

  const removeCidr = async (s: Site, subnetId: string) => {
    setError(null);
    try {
      await deleteSubnet(s.id, subnetId);
      reload();
    } catch (e) {
      setError(String(e));
    }
  };

  return (
    <div className="content">
      <h2>Standorte</h2>
      {error && <p className="error">{error}</p>}

      <div className="card">
        <h3>Standort anlegen</h3>
        <div className="row">
          <input placeholder="Name (z.B. Sulgen)" value={form.name}
            onChange={(e) => setForm({ ...form, name: e.target.value })} />
          <input placeholder="Code (opt.)" style={{ width: 120 }} value={form.code}
            onChange={(e) => setForm({ ...form, code: e.target.value })} />
          <input placeholder="Beschreibung (opt.)" value={form.description}
            onChange={(e) => setForm({ ...form, description: e.target.value })} />
          <input placeholder="Namens-Regel (opt., z.B. 10.120.10.{n})" style={{ width: 220 }}
            value={form.template}
            onChange={(e) => setForm({ ...form, template: e.target.value })} />
          <button onClick={submit} disabled={!form.name}>Anlegen</button>
        </div>
        <p className="muted" style={{ fontSize: 12 }}>
          IP-Segmente (z.B. 10.120.0.0/16) fügst du nach dem Anlegen direkt am Standort hinzu —
          Geräte werden darüber automatisch dem richtigen Standort zugeordnet.
        </p>
      </div>

      {sites.map((s) => (
        <div className="card" key={s.id}>
          <div className="row" style={{ justifyContent: "space-between" }}>
            <h3 style={{ margin: 0 }}>
              📍 {s.name} {s.code && <span className="badge">{s.code}</span>}{" "}
              <span className="badge">{deviceCount(s.id)} Geräte</span>
            </h3>
            <button className="danger" onClick={() => remove(s)} disabled={deviceCount(s.id) > 0}
              title={deviceCount(s.id) > 0 ? "Erst Geräte umhängen/entfernen" : "Standort entfernen"}>
              entfernen
            </button>
          </div>

          <div className="row" style={{ marginTop: 8, alignItems: "flex-start", gap: 32 }}>
            <div>
              <strong style={{ fontSize: 13 }}>IP-Segmente</strong>
              {s.subnets.length === 0 && <p className="muted" style={{ fontSize: 12 }}>noch keine</p>}
              {s.subnets.map((sub) => (
                <div key={sub.id} style={{ fontSize: 13, marginTop: 4 }}>
                  <code>{sub.cidr}</code>{" "}
                  <a style={{ cursor: "pointer", color: "var(--danger)" }}
                    onClick={() => removeCidr(s, sub.id)} title="Segment entfernen">✕</a>
                </div>
              ))}
              <div className="row" style={{ marginTop: 6 }}>
                <input placeholder="z.B. 10.120.0.0/16" style={{ width: 160 }}
                  value={newCidr[s.id] ?? ""}
                  onChange={(e) => setNewCidr({ ...newCidr, [s.id]: e.target.value })}
                  onKeyDown={(e) => e.key === "Enter" && addCidr(s)} />
                <button className="ghost" onClick={() => addCidr(s)}>+ Segment</button>
              </div>
            </div>

            <div>
              <strong style={{ fontSize: 13 }}>Namens→IP-Regel</strong>
              <p className="muted" style={{ fontSize: 12, margin: "2px 0" }}>
                {"{n}"} = Endnummer des Gerätenamens (BLS-SW-51 → …{".51"})
              </p>
              <input placeholder="z.B. 10.120.10.{n} (leer = aus)" style={{ width: 220 }}
                defaultValue={s.mgmt_ip_template ?? ""}
                onBlur={(e) => {
                  if ((e.target.value || null) !== s.mgmt_ip_template) saveTemplate(s, e.target.value);
                }} />
            </div>
          </div>
        </div>
      ))}
      {sites.length === 0 && <p className="muted">Noch keine Standorte angelegt.</p>}
    </div>
  );
}
