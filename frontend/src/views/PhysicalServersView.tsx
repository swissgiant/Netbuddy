import { useEffect, useMemo, useState } from "react";
import type { PhysicalServer, Site } from "../api";
import {
  deletePhysicalServer,
  fetchPhysicalServers,
  fetchSites,
  updatePhysicalServer,
} from "../api";
import { Th, useSort } from "../sort";

const ROLES = ["esxi_host", "hyperv_host", "bare_metal", "appliance", "unknown"];
const HW = ["ok", "warning", "critical", "unknown"];
const HW_ICON: Record<string, string> = { ok: "🟢", warning: "🟡", critical: "🔴", unknown: "⚪" };
const gb = (mb: number | null) => (mb == null ? "" : `${Math.round(mb / 1024)} GB`);

export function PhysicalServersView() {
  const [rows, setRows] = useState<PhysicalServer[]>([]);
  const [sites, setSites] = useState<Site[]>([]);
  const [q, setQ] = useState("");
  const [siteFilter, setSiteFilter] = useState<string>("");
  const [roleFilter, setRoleFilter] = useState<string>("");
  const [hwFilter, setHwFilter] = useState<string>("");
  const [err, setErr] = useState<string | null>(null);

  const reload = () => {
    fetchPhysicalServers().then(setRows).catch((e) => setErr(String(e)));
    fetchSites().then(setSites).catch(() => {});
  };
  useEffect(reload, []);

  const filtered = useMemo(() => {
    const needle = q.trim().toLowerCase();
    return rows.filter((r) => {
      if (siteFilter && r.site_id !== siteFilter) return false;
      if (roleFilter && r.server_role !== roleFilter) return false;
      if (hwFilter && r.hardware_status !== hwFilter) return false;
      if (!needle) return true;
      const hay = [
        r.hostname, r.dns_name, r.site_name, r.vendor, r.model, r.service_tag,
        r.cpu_model, r.os_name, r.mgmt_ip, r.reachable_ip, r.source, r.notes, r.ip_addresses.join(" "),
      ].join(" ").toLowerCase();
      return hay.includes(needle);
    });
  }, [rows, q, siteFilter, roleFilter, hwFilter]);

  const { sorted, sort, toggle } = useSort(filtered, {
    site: (r) => r.site_name,
    ram: (r) => r.ram_mb,
    warranty: (r) => r.warranty_end,
  });

  const patch = (id: string, body: Partial<PhysicalServer>) =>
    updatePhysicalServer(id, body).then(reload).catch((e) => setErr(String(e)));

  return (
    <div>
      <h2>🖥️ Physische Server <span className="badge">{filtered.length}/{rows.length}</span></h2>
      {err && <p className="error">{err}</p>}
      <div className="toolbar" style={{ display: "flex", gap: 8, flexWrap: "wrap", marginBottom: 8 }}>
        <input placeholder="Suche…" value={q} onChange={(e) => setQ(e.target.value)} />
        <select value={siteFilter} onChange={(e) => setSiteFilter(e.target.value)}>
          <option value="">Alle Standorte</option>
          {sites.map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}
        </select>
        <select value={roleFilter} onChange={(e) => setRoleFilter(e.target.value)}>
          <option value="">Alle Rollen</option>
          {ROLES.map((r) => <option key={r} value={r}>{r}</option>)}
        </select>
        <select value={hwFilter} onChange={(e) => setHwFilter(e.target.value)}>
          <option value="">HW: alle</option>
          {HW.map((h) => <option key={h} value={h}>{h}</option>)}
        </select>
      </div>
      <div className="scrolltable">
<table>
        <thead>
          <tr>
            <Th k="hostname" sort={sort} onSort={toggle}>Hostname</Th>
            <Th k="site" sort={sort} onSort={toggle}>Standort</Th>
            <Th k="server_role" sort={sort} onSort={toggle}>Rolle</Th>
            <Th k="vendor" sort={sort} onSort={toggle}>Hersteller</Th>
            <Th k="model" sort={sort} onSort={toggle}>Modell</Th>
            <Th k="service_tag" sort={sort} onSort={toggle}>Service-Tag</Th>
            <Th k="cpu_cores" sort={sort} onSort={toggle}>Cores</Th>
            <Th k="ram" sort={sort} onSort={toggle}>RAM</Th>
            <Th k="mgmt_ip" sort={sort} onSort={toggle}>Mgmt-IP</Th>
            <Th k="reachable_ip" sort={sort} onSort={toggle}>Cato-IP</Th>
            <Th k="hardware_status" sort={sort} onSort={toggle}>HW</Th>
            <Th k="warranty" sort={sort} onSort={toggle}>Service bis</Th>
            <Th k="source" sort={sort} onSort={toggle}>Quelle</Th>
            <th></th>
          </tr>
        </thead>
        <tbody>
          {sorted.map((r) => (
            <tr key={r.id}>
              <td>{r.hostname}{r.dns_name && r.dns_name !== r.hostname && <span className="muted"> ({r.dns_name})</span>}</td>
              <td>{r.site_name ?? <span className="muted">—</span>}</td>
              <td><span className="badge">{r.server_role}</span></td>
              <td>{r.vendor}</td>
              <td>{r.model}</td>
              <td>{r.service_tag}</td>
              <td>{r.cpu_cores}{r.cpu_sockets ? <span className="muted"> /{r.cpu_sockets}S</span> : ""}</td>
              <td>{gb(r.ram_mb)}</td>
              <td>{r.mgmt_ip}{r.ilo_ip && (
                <div className="muted" style={{ fontSize: "0.85em" }}>
                  🔧 <a href={`https://${r.ilo_ip}`} target="_blank" rel="noreferrer">{r.ilo_ip}</a>
                  {r.oob_type ? ` (${r.oob_type})` : ""}
                </div>
              )}</td>
              <td className="muted">{r.reachable_ip ?? ""}</td>
              <td title={r.hardware_detail ?? ""}>
                <select value={r.hardware_status} onChange={(e) => patch(r.id, { hardware_status: e.target.value as PhysicalServer["hardware_status"] })}>
                  {HW.map((h) => <option key={h} value={h}>{HW_ICON[h]} {h}</option>)}
                </select>
                {r.hardware_status !== "ok" && (
                  <button className="ghost" title="Grund anzeigen" style={{ marginLeft: 4 }}
                    onClick={() => alert(r.hardware_detail || "Kein Detail hinterlegt (noch keine HW-Diagnose/SNMP-Health)")}>ℹ️</button>
                )}
              </td>
              <td className={r.warranty_status === "expired" ? "error" : ""}>{r.warranty_end ?? <span className="muted">—</span>}</td>
              <td><span className="muted">{r.source}</span></td>
              <td><button onClick={() => confirm(`${r.hostname} löschen?`) && deletePhysicalServer(r.id).then(reload)}>🗑️</button></td>
            </tr>
          ))}
        </tbody>
      </table>
</div>
    </div>
  );
}
