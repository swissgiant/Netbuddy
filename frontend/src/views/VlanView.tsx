import { useEffect, useState } from "react";
import type { Site, Vlan } from "../api";
import {
  createVlan,
  deleteVlan,
  deleteVlanSubnet,
  fetchSites,
  fetchVlans,
  setVlanSubnet,
  updateVlan,
} from "../api";

export function VlanView() {
  const [vlans, setVlans] = useState<Vlan[]>([]);
  const [sites, setSites] = useState<Site[]>([]);
  const [form, setForm] = useState({ vlan_id: "", name: "", description: "" });
  const [sub, setSub] = useState<Record<string, { site_id: string; cidr: string; gateway: string }>>(
    {},
  );
  const [error, setError] = useState<string | null>(null);

  const reload = () => {
    fetchVlans().then(setVlans).catch((e) => setError(String(e)));
    fetchSites().then(setSites).catch(() => {});
  };
  useEffect(reload, []);

  const subFor = (vid: string) => sub[vid] ?? { site_id: "", cidr: "", gateway: "" };

  const submit = async () => {
    setError(null);
    const id = Number(form.vlan_id);
    if (!Number.isInteger(id) || id < 1 || id > 4094) {
      setError("VLAN-ID muss zwischen 1 und 4094 liegen");
      return;
    }
    try {
      await createVlan({ vlan_id: id, name: form.name, description: form.description || undefined });
      setForm({ vlan_id: "", name: "", description: "" });
      reload();
    } catch (e) {
      setError(String(e));
    }
  };

  const removeVlan = async (v: Vlan) => {
    if (!confirm(`VLAN ${v.vlan_id} „${v.name}" samt aller Standort-Subnetze löschen?`)) return;
    setError(null);
    try {
      await deleteVlan(v.id);
      reload();
    } catch (e) {
      setError(String(e));
    }
  };

  const rename = async (v: Vlan, name: string) => {
    if (name.trim() === v.name) return;
    setError(null);
    try {
      await updateVlan(v.id, { name });
      reload();
    } catch (e) {
      setError(String(e));
    }
  };

  const saveComment = async (v: Vlan, comment: string) => {
    if (comment === (v.description ?? "")) return;
    setError(null);
    try {
      await updateVlan(v.id, { description: comment || null });
      reload();
    } catch (e) {
      setError(String(e));
    }
  };

  const addSubnet = async (v: Vlan) => {
    const s = subFor(v.id);
    if (!s.site_id || !s.cidr.trim()) return;
    setError(null);
    try {
      await setVlanSubnet(v.id, {
        site_id: s.site_id,
        cidr: s.cidr.trim(),
        gateway: s.gateway.trim() || undefined,
      });
      setSub({ ...sub, [v.id]: { site_id: "", cidr: "", gateway: "" } });
      reload();
    } catch (e) {
      setError(String(e));
    }
  };

  const removeSubnet = async (v: Vlan, siteId: string) => {
    setError(null);
    try {
      await deleteVlanSubnet(v.id, siteId);
      reload();
    } catch (e) {
      setError(String(e));
    }
  };

  return (
    <div className="content">
      <h2>VLANs</h2>
      <p className="muted" style={{ fontSize: 12, marginTop: -8 }}>
        Zentral definiert: dieselbe VLAN-ID an allen Standorten, je Standort ein eigenes Subnetz +
        Gateway. Grundlage für VLAN-Ausrollen auf Switches, FW-Kopplung und Port-Zuweisung.
      </p>
      {error && <p className="error">{error}</p>}

      <div className="card">
        <h3>VLAN anlegen</h3>
        <div className="row">
          <input
            placeholder="VLAN-ID (1–4094)"
            style={{ width: 130 }}
            value={form.vlan_id}
            onChange={(e) => setForm({ ...form, vlan_id: e.target.value })}
          />
          <input
            placeholder="Name (z.B. Test-Netz 1)"
            value={form.name}
            onChange={(e) => setForm({ ...form, name: e.target.value })}
          />
          <input
            placeholder="Kommentar / Kunde (opt.)"
            value={form.description}
            onChange={(e) => setForm({ ...form, description: e.target.value })}
          />
          <button onClick={submit} disabled={!form.vlan_id || !form.name}>
            Anlegen
          </button>
        </div>
      </div>

      {vlans.map((v) => {
        const usedSites = new Set(v.subnets.map((s) => s.site_id));
        const freeSites = sites.filter((s) => !usedSites.has(s.id));
        const draft = subFor(v.id);
        return (
          <div className="card" key={v.id}>
            <div className="row" style={{ justifyContent: "space-between" }}>
              <h3 style={{ margin: 0 }}>
                <span className="badge">VLAN {v.vlan_id}</span>{" "}
                <input
                  defaultValue={v.name}
                  style={{ fontSize: 15, fontWeight: 600, border: "none", background: "transparent" }}
                  onBlur={(e) => rename(v, e.target.value)}
                  title="Name bearbeiten"
                />
              </h3>
              <div className="row" style={{ alignItems: "center", gap: 8 }}>
                <span className="muted" style={{ fontSize: 12 }}>Kunde:</span>
                <input
                  placeholder="— derzeit frei —"
                  defaultValue={v.description ?? ""}
                  style={{ width: 200, fontSize: 13 }}
                  onBlur={(e) => saveComment(v, e.target.value.trim())}
                  title="Aktueller Kunde / Kommentar"
                />
                <button className="danger" onClick={() => removeVlan(v)}>
                  löschen
                </button>
              </div>
            </div>

            <div style={{ marginTop: 8 }}>
              <strong style={{ fontSize: 13 }}>Subnetze pro Standort</strong>
              {v.subnets.length === 0 && (
                <p className="muted" style={{ fontSize: 12 }}>noch keine — unten zuweisen</p>
              )}
              {v.subnets.map((s) => (
                <div key={s.id} style={{ fontSize: 13, marginTop: 4 }}>
                  <span className="badge">{s.site_name ?? "?"}</span> <code>{s.cidr}</code>
                  {s.gateway && <span className="muted"> · GW {s.gateway}</span>}{" "}
                  <a
                    style={{ cursor: "pointer", color: "var(--danger)" }}
                    onClick={() => removeSubnet(v, s.site_id)}
                    title="Subnetz entfernen"
                  >
                    ✕
                  </a>
                </div>
              ))}

              {freeSites.length > 0 && (
                <div className="row" style={{ marginTop: 8 }}>
                  <select
                    value={draft.site_id}
                    onChange={(e) => setSub({ ...sub, [v.id]: { ...draft, site_id: e.target.value } })}
                  >
                    <option value="">Standort …</option>
                    {freeSites.map((s) => (
                      <option key={s.id} value={s.id}>
                        {s.name}
                      </option>
                    ))}
                  </select>
                  <input
                    placeholder="Subnetz z.B. 10.120.101.0/24"
                    style={{ width: 200 }}
                    value={draft.cidr}
                    onChange={(e) => setSub({ ...sub, [v.id]: { ...draft, cidr: e.target.value } })}
                  />
                  <input
                    placeholder="Gateway (opt.)"
                    style={{ width: 150 }}
                    value={draft.gateway}
                    onChange={(e) => setSub({ ...sub, [v.id]: { ...draft, gateway: e.target.value } })}
                    onKeyDown={(e) => e.key === "Enter" && addSubnet(v)}
                  />
                  <button
                    className="ghost"
                    onClick={() => addSubnet(v)}
                    disabled={!draft.site_id || !draft.cidr}
                  >
                    + zuweisen
                  </button>
                </div>
              )}
            </div>
          </div>
        );
      })}
      {vlans.length === 0 && <p className="muted">Noch keine VLANs angelegt.</p>}
    </div>
  );
}
