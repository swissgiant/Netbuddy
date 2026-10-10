import { useEffect, useMemo, useState } from "react";
import type { Site, VirtualServer } from "../api";
import {
  deleteVirtualServer,
  fetchSites,
  fetchVirtualServers,
  updateVirtualServer,
} from "../api";
import { Th, useSort } from "../sort";

const POWER = ["on", "off", "suspended", "unknown"];
const POWER_ICON: Record<string, string> = { on: "🟢", off: "⚫", suspended: "🟡", unknown: "⚪" };
const gb = (mb: number | null) => (mb == null ? "" : `${Math.round(mb / 1024)} GB`);

export function VirtualServersView() {
  const [rows, setRows] = useState<VirtualServer[]>([]);
  const [sites, setSites] = useState<Site[]>([]);
  const [q, setQ] = useState("");
  const [siteFilter, setSiteFilter] = useState("");
  const [clusterFilter, setClusterFilter] = useState("");
  const [powerFilter, setPowerFilter] = useState("");
  const [err, setErr] = useState<string | null>(null);

  const reload = () => {
    fetchVirtualServers().then(setRows).catch((e) => setErr(String(e)));
    fetchSites().then(setSites).catch(() => {});
  };
  useEffect(reload, []);

  const clusters = useMemo(
    () => [...new Set(rows.map((r) => r.cluster).filter(Boolean))] as string[],
    [rows],
  );

  const filtered = useMemo(() => {
    const needle = q.trim().toLowerCase();
    return rows.filter((r) => {
      if (siteFilter && r.site_id !== siteFilter) return false;
      if (clusterFilter && r.cluster !== clusterFilter) return false;
      if (powerFilter && r.power_state !== powerFilter) return false;
      if (!needle) return true;
      const hay = [
        r.name, r.dns_name, r.site_name, r.cluster, r.esxi_host, r.vcenter, r.guest_os,
        r.source, r.notes, r.ip_addresses.join(" "), r.networks.join(" "), r.datastores.join(" "),
      ].join(" ").toLowerCase();
      return hay.includes(needle);
    });
  }, [rows, q, siteFilter, clusterFilter, powerFilter]);

  const { sorted, sort, toggle } = useSort(filtered, {
    site: (r) => r.site_name,
    ram: (r) => r.ram_mb,
    ips: (r) => r.ip_addresses.join(","),
  });

  return (
    <div>
      <h2>🧩 Virtuelle Server <span className="badge">{filtered.length}/{rows.length}</span></h2>
      {err && <p className="error">{err}</p>}
      <div className="toolbar" style={{ display: "flex", gap: 8, flexWrap: "wrap", marginBottom: 8 }}>
        <input placeholder="Suche…" value={q} onChange={(e) => setQ(e.target.value)} />
        <select value={siteFilter} onChange={(e) => setSiteFilter(e.target.value)}>
          <option value="">Alle Standorte</option>
          {sites.map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}
        </select>
        <select value={clusterFilter} onChange={(e) => setClusterFilter(e.target.value)}>
          <option value="">Alle Cluster</option>
          {clusters.map((c) => <option key={c} value={c}>{c}</option>)}
        </select>
        <select value={powerFilter} onChange={(e) => setPowerFilter(e.target.value)}>
          <option value="">Power: alle</option>
          {POWER.map((p) => <option key={p} value={p}>{p}</option>)}
        </select>
      </div>
      <div className="scrolltable">
<table>
        <thead>
          <tr>
            <Th k="name" sort={sort} onSort={toggle}>Name</Th>
            <Th k="power_state" sort={sort} onSort={toggle}>Power</Th>
            <Th k="site" sort={sort} onSort={toggle}>Standort</Th>
            <Th k="cluster" sort={sort} onSort={toggle}>Cluster</Th>
            <Th k="esxi_host" sort={sort} onSort={toggle}>Host</Th>
            <Th k="vcpu" sort={sort} onSort={toggle}>vCPU</Th>
            <Th k="ram" sort={sort} onSort={toggle}>RAM</Th>
            <Th k="disk_total_gb" sort={sort} onSort={toggle}>Disk</Th>
            <Th k="guest_os" sort={sort} onSort={toggle}>Gast-OS</Th>
            <Th k="ips" sort={sort} onSort={toggle}>IP-Adressen</Th>
            <Th k="vcenter" sort={sort} onSort={toggle}>vCenter</Th>
            <th></th>
          </tr>
        </thead>
        <tbody>
          {sorted.map((r) => (
            <tr key={r.id}>
              <td>{r.name}{r.dns_name && r.dns_name !== r.name && <span className="muted"> ({r.dns_name})</span>}</td>
              <td title={r.power_state}>
                <select value={r.power_state} onChange={(e) => updateVirtualServer(r.id, { power_state: e.target.value as VirtualServer["power_state"] }).then(reload)}>
                  {POWER.map((p) => <option key={p} value={p}>{POWER_ICON[p]} {p}</option>)}
                </select>
              </td>
              <td>{r.site_name ?? <span className="muted">—</span>}</td>
              <td>{r.cluster}</td>
              <td>{r.esxi_host}</td>
              <td>{r.vcpu}</td>
              <td>{gb(r.ram_mb)}</td>
              <td>{r.disk_total_gb != null ? `${r.disk_total_gb} GB` : ""}{r.disk_count ? <span className="muted"> ({r.disk_count})</span> : ""}</td>
              <td>{r.guest_os}</td>
              <td className="muted" style={{ fontSize: 12 }}>{r.ip_addresses.join(", ")}</td>
              <td className="muted">{r.vcenter}</td>
              <td><button onClick={() => confirm(`${r.name} löschen?`) && deleteVirtualServer(r.id).then(reload)}>🗑️</button></td>
            </tr>
          ))}
        </tbody>
      </table>
</div>
    </div>
  );
}
