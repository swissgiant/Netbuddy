import { useEffect, useMemo, useState } from "react";
import type { Site, StorageDevice } from "../api";
import {
  deleteStorageDevice,
  fetchSites,
  fetchStorageDevices,
  updateStorageDevice,
} from "../api";
import { Th, useSort } from "../sort";

const TYPES = ["enterprise_array", "nas", "backup_target", "san_switch", "unknown"];
const HW = ["ok", "warning", "critical", "unknown"];
const HW_ICON: Record<string, string> = { ok: "🟢", warning: "🟡", critical: "🔴", unknown: "⚪" };
const tb = (g: number | null) => (g == null ? "" : g >= 1024 ? `${(g / 1024).toFixed(1)} TB` : `${g} GB`);

export function StorageDevicesView() {
  const [rows, setRows] = useState<StorageDevice[]>([]);
  const [sites, setSites] = useState<Site[]>([]);
  const [q, setQ] = useState("");
  const [siteFilter, setSiteFilter] = useState("");
  const [typeFilter, setTypeFilter] = useState("");
  const [hwFilter, setHwFilter] = useState("");
  const [err, setErr] = useState<string | null>(null);

  const reload = () => {
    fetchStorageDevices().then(setRows).catch((e) => setErr(String(e)));
    fetchSites().then(setSites).catch(() => {});
  };
  useEffect(reload, []);

  const filtered = useMemo(() => {
    const needle = q.trim().toLowerCase();
    return rows.filter((r) => {
      if (siteFilter && r.site_id !== siteFilter) return false;
      if (typeFilter && r.storage_type !== typeFilter) return false;
      if (hwFilter && r.hardware_status !== hwFilter) return false;
      if (!needle) return true;
      const hay = [
        r.name, r.dns_name, r.site_name, r.vendor, r.model, r.service_tag, r.firmware,
        r.mgmt_ip, r.source, r.notes, r.ip_addresses.join(" "), r.protocols.join(" "),
      ].join(" ").toLowerCase();
      return hay.includes(needle);
    });
  }, [rows, q, siteFilter, typeFilter, hwFilter]);

  const { sorted, sort, toggle } = useSort(filtered, {
    site: (r) => r.site_name,
    usable: (r) => r.capacity_usable_gb,
    used: (r) => r.capacity_used_gb,
    protocols: (r) => r.protocols.join(","),
  });

  const pct = (r: StorageDevice) =>
    r.capacity_usable_gb && r.capacity_used_gb
      ? Math.round((r.capacity_used_gb / r.capacity_usable_gb) * 100)
      : null;

  return (
    <div>
      <h2>💾 Storage <span className="badge">{filtered.length}/{rows.length}</span></h2>
      {err && <p className="error">{err}</p>}
      <div className="toolbar" style={{ display: "flex", gap: 8, flexWrap: "wrap", marginBottom: 8 }}>
        <input placeholder="Suche…" value={q} onChange={(e) => setQ(e.target.value)} />
        <select value={siteFilter} onChange={(e) => setSiteFilter(e.target.value)}>
          <option value="">Alle Standorte</option>
          {sites.map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}
        </select>
        <select value={typeFilter} onChange={(e) => setTypeFilter(e.target.value)}>
          <option value="">Alle Typen</option>
          {TYPES.map((t) => <option key={t} value={t}>{t}</option>)}
        </select>
        <select value={hwFilter} onChange={(e) => setHwFilter(e.target.value)}>
          <option value="">HW: alle</option>
          {HW.map((h) => <option key={h} value={h}>{h}</option>)}
        </select>
      </div>
      <table>
        <thead>
          <tr>
            <Th k="name" sort={sort} onSort={toggle}>Name</Th>
            <Th k="site" sort={sort} onSort={toggle}>Standort</Th>
            <Th k="storage_type" sort={sort} onSort={toggle}>Typ</Th>
            <Th k="vendor" sort={sort} onSort={toggle}>Hersteller</Th>
            <Th k="model" sort={sort} onSort={toggle}>Modell</Th>
            <Th k="service_tag" sort={sort} onSort={toggle}>Service-Tag</Th>
            <Th k="disk_count" sort={sort} onSort={toggle}>Disks</Th>
            <Th k="usable" sort={sort} onSort={toggle}>Nutzbar</Th>
            <Th k="used" sort={sort} onSort={toggle}>Belegt</Th>
            <Th k="protocols" sort={sort} onSort={toggle}>Anbindung</Th>
            <Th k="mgmt_ip" sort={sort} onSort={toggle}>Mgmt-IP</Th>
            <Th k="hardware_status" sort={sort} onSort={toggle}>HW</Th>
            <th></th>
          </tr>
        </thead>
        <tbody>
          {sorted.map((r) => {
            const p = pct(r);
            return (
              <tr key={r.id}>
                <td>{r.name}</td>
                <td>{r.site_name ?? <span className="muted">—</span>}</td>
                <td><span className="badge">{r.storage_type}</span></td>
                <td>{r.vendor}</td>
                <td>{r.model}</td>
                <td>{r.service_tag}</td>
                <td>{r.disk_count}</td>
                <td>{tb(r.capacity_usable_gb)}</td>
                <td className={p != null && p >= 90 ? "error" : ""}>{tb(r.capacity_used_gb)}{p != null && <span className="muted"> ({p}%)</span>}</td>
                <td className="muted" style={{ fontSize: 12 }}>{r.protocols.join(", ")}</td>
                <td>{r.mgmt_ip}</td>
                <td title={r.hardware_detail ?? ""}>
                  <select value={r.hardware_status} onChange={(e) => updateStorageDevice(r.id, { hardware_status: e.target.value as StorageDevice["hardware_status"] }).then(reload)}>
                    {HW.map((h) => <option key={h} value={h}>{HW_ICON[h]} {h}</option>)}
                  </select>
                </td>
                <td><button onClick={() => confirm(`${r.name} löschen?`) && deleteStorageDevice(r.id).then(reload)}>🗑️</button></td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
