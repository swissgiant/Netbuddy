import { useEffect, useState } from "react";
import type { Device, Site } from "../api";
import { createSite, deleteSite, fetchDevices, fetchSites } from "../api";

export function SitesView() {
  const [sites, setSites] = useState<Site[]>([]);
  const [devices, setDevices] = useState<Device[]>([]);
  const [form, setForm] = useState({ name: "", code: "", description: "" });
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
      });
      setForm({ name: "", code: "", description: "" });
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

  return (
    <div className="content">
      <h2>Standorte</h2>
      {error && <p className="error">{error}</p>}

      <div className="card">
        <h3>Standort anlegen</h3>
        <div className="row">
          <input placeholder="Name (z.B. Werk Süd)" value={form.name}
            onChange={(e) => setForm({ ...form, name: e.target.value })} />
          <input placeholder="Code (opt., z.B. BLS)" style={{ width: 160 }} value={form.code}
            onChange={(e) => setForm({ ...form, code: e.target.value })} />
          <input placeholder="Beschreibung (opt.)" style={{ flex: 1, minWidth: 0 }} value={form.description}
            onChange={(e) => setForm({ ...form, description: e.target.value })} />
          <button onClick={submit} disabled={!form.name}>Anlegen</button>
        </div>
      </div>

      <div className="card">
        <div className="row" style={{ justifyContent: "space-between" }}>
          <h3 style={{ margin: 0 }}>Vorhandene <span className="badge">{sites.length}</span></h3>
          <button className="ghost" onClick={reload}>↻</button>
        </div>
        <table>
          <thead><tr><th>Name</th><th>Code</th><th>Beschreibung</th><th>Geräte</th><th></th></tr></thead>
          <tbody>
            {sites.map((s) => {
              const n = deviceCount(s.id);
              return (
                <tr key={s.id}>
                  <td>{s.name}</td>
                  <td className="muted">{s.code ?? "—"}</td>
                  <td className="muted">{s.description ?? "—"}</td>
                  <td><span className="badge">{n}</span></td>
                  <td>
                    <button className="danger" onClick={() => remove(s)} disabled={n > 0}
                      title={n > 0 ? "Erst Geräte umhängen/entfernen" : "Standort entfernen"}>
                      entfernen
                    </button>
                  </td>
                </tr>
              );
            })}
            {sites.length === 0 && (
              <tr><td colSpan={5} className="muted">Noch keine Standorte angelegt.</td></tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
