import { useMemo, useState } from "react";
import type { SurveyVlan, VlanSurvey } from "../api";
import { Th, useSort } from "../sort";

// Tabellarische VLAN-Sicht über ALLE Standorte (Datenbasis: VLAN-Survey) mit Filtern —
// das Arbeitswerkzeug fürs Aufräumen: suchen, nach Site/DHCP filtern, Auffälligkeiten isolieren.

interface Transition {
  vlan_id: number;
  to: string;
  detail: string | null;
  policy: string | null;
  device: string;
}

interface Row {
  site: string;
  vlan_id: number;
  name: string;
  names: string[];
  gateways: { device: string; ip: string }[];
  dhcp: string; // sortier-/filterbar: server | helper | none
  dhcp_servers: string[];
  dhcp_helpers: { device: string; helpers: string[] }[];
  carriers: number;
  carrier_names: string[];
  access_ports: number;
  transitions: Transition[];
}

export function VlanTableView({ survey }: { survey: VlanSurvey }) {
  const [q, setQ] = useState("");
  const [site, setSite] = useState("");
  const [dhcp, setDhcp] = useState("");
  const [onlyFindings, setOnlyFindings] = useState(false);

  const rows: Row[] = useMemo(() => {
    const transitions =
      (survey.data as { transitions?: Record<string, Transition[]> }).transitions ?? {};
    const out: Row[] = [];
    for (const [siteName, vlans] of Object.entries(survey.data.sites)) {
      for (const v of vlans as SurveyVlan[]) {
        out.push({
          site: siteName,
          vlan_id: v.vlan_id,
          name: v.names[0] ?? "",
          names: v.names,
          gateways: v.gateways,
          dhcp: v.dhcp_helpers.length > 0 ? "helper" : v.dhcp_servers.length > 0 ? "server" : "none",
          dhcp_servers: v.dhcp_servers,
          dhcp_helpers: v.dhcp_helpers,
          carriers: v.carriers.length,
          carrier_names: v.carriers,
          access_ports: v.access_ports,
          transitions: (transitions[siteName] ?? []).filter((t) => t.vlan_id === v.vlan_id),
        });
      }
    }
    return out;
  }, [survey]);

  const sites = useMemo(() => Object.keys(survey.data.sites).sort(), [survey]);

  const filtered = rows.filter((r) => {
    if (site && r.site !== site) return false;
    if (dhcp && r.dhcp !== dhcp) return false;
    if (onlyFindings) {
      const finding =
        r.gateways.length === 0 || r.names.length > 1 || r.dhcp_helpers.length > 0;
      if (!finding) return false;
    }
    if (q.trim()) {
      const hay = [
        String(r.vlan_id),
        ...r.names,
        ...r.gateways.map((g) => `${g.device} ${g.ip}`),
        ...r.carrier_names,
      ]
        .join(" ")
        .toLowerCase();
      if (!hay.includes(q.trim().toLowerCase())) return false;
    }
    return true;
  });

  const { sorted: view, sort, toggle } = useSort(filtered);

  return (
    <div style={{ overflow: "auto", flex: 1 }}>
      <div className="row" style={{ gap: 8, flexWrap: "wrap", margin: "8px 0" }}>
        <input
          placeholder="Suche: VLAN-ID / Name / Gerät / IP"
          value={q}
          onChange={(e) => setQ(e.target.value)}
          style={{ minWidth: 240 }}
        />
        <select value={site} onChange={(e) => setSite(e.target.value)}>
          <option value="">— alle Standorte —</option>
          {sites.map((s) => (
            <option key={s} value={s}>{s}</option>
          ))}
        </select>
        <select value={dhcp} onChange={(e) => setDhcp(e.target.value)}>
          <option value="">— DHCP: alle —</option>
          <option value="server">DHCP-Server</option>
          <option value="helper">DHCP-Helper (Relay)</option>
          <option value="none">kein DHCP</option>
        </select>
        <label className="muted" style={{ display: "flex", alignItems: "center", gap: 4, fontSize: 13 }}>
          <input type="checkbox" checked={onlyFindings} onChange={(e) => setOnlyFindings(e.target.checked)} />
          nur Auffälligkeiten (ohne GW / Namens-Konflikt / Helper)
        </label>
        <span className="badge">{view.length}/{rows.length}</span>
      </div>
      <table>
        <thead>
          <tr>
            <Th k="site" sort={sort} onSort={toggle}>Standort</Th>
            <Th k="vlan_id" sort={sort} onSort={toggle}>VLAN</Th>
            <Th k="name" sort={sort} onSort={toggle}>Name(n)</Th>
            <th>Gateway</th>
            <Th k="dhcp" sort={sort} onSort={toggle}>DHCP</Th>
            <th>Übergänge</th>
            <Th k="carriers" sort={sort} onSort={toggle}>Träger</Th>
            <Th k="access_ports" sort={sort} onSort={toggle}>Access-Ports</Th>
          </tr>
        </thead>
        <tbody>
          {view.map((r) => (
            <tr key={`${r.site}:${r.vlan_id}`}>
              <td className="muted">{r.site}</td>
              <td>{r.vlan_id}</td>
              <td>
                {r.names.length === 0 && <span className="muted">—</span>}
                {r.names.map((n) => (
                  <span key={n} className={"badge" + (r.names.length > 1 ? " warn" : "")} style={{ marginRight: 4 }}>{n}</span>
                ))}
              </td>
              <td style={{ fontSize: 12 }}>
                {r.gateways.length === 0 ? (
                  <span className="muted">kein GW</span>
                ) : (
                  r.gateways.slice(0, 2).map((g) => (
                    <div key={g.device + g.ip}>{g.device} <span className="muted">({g.ip})</span></div>
                  ))
                )}
              </td>
              <td style={{ fontSize: 12 }}>
                {r.dhcp === "server" && <span className="badge ok">{r.dhcp_servers.join(", ")}</span>}
                {r.dhcp === "helper" && (
                  <span className="badge warn" title={r.dhcp_helpers.map((h) => h.device).join(", ")}>
                    Helper → {r.dhcp_helpers.flatMap((h) => h.helpers).join(", ")}
                  </span>
                )}
                {r.dhcp === "none" && <span className="muted">—</span>}
              </td>
              <td style={{ fontSize: 12 }}>
                {r.transitions.length === 0 ? (
                  <span className="muted">isoliert</span>
                ) : (
                  [...new Set(r.transitions.map((t) => (t.to === "vpn" ? "VPN" : t.to)))].join(", ")
                )}
              </td>
              <td title={r.carrier_names.join(", ")}>{r.carriers}</td>
              <td>{r.access_ports || <span className="muted">0</span>}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
