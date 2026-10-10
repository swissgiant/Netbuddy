import { useEffect, useMemo, useState } from "react";
import type { Site, StorageDevice, StorageTreeNode } from "../api";
import {
  deleteStorageDevice,
  fetchSites,
  fetchStorageDevices,
  fetchStorageTree,
  updateStorageDevice,
} from "../api";
import { Th, useSort } from "../sort";

const TYPES = ["enterprise_array", "nas", "backup_target", "san_switch", "unknown"];
const HW = ["ok", "warning", "critical", "unknown"];
const HW_ICON: Record<string, string> = { ok: "🟢", warning: "🟡", critical: "🔴", unknown: "⚪" };
const tb = (g: number | null | undefined) =>
  g == null ? "" : g >= 1024 ? `${(g / 1024).toFixed(1)} TB` : `${g} GB`;

export function StorageDevicesView() {
  const [mode, setMode] = useState<"list" | "tree">("list");
  const [rows, setRows] = useState<StorageDevice[]>([]);
  const [tree, setTree] = useState<StorageTreeNode[]>([]);
  const [exp, setExp] = useState<Set<string>>(new Set());
  const [sites, setSites] = useState<Site[]>([]);
  const [q, setQ] = useState("");
  const [siteFilter, setSiteFilter] = useState("");
  const [typeFilter, setTypeFilter] = useState("");
  const [hwFilter, setHwFilter] = useState("");
  const [err, setErr] = useState<string | null>(null);

  const reload = () => {
    fetchStorageDevices().then(setRows).catch((e) => setErr(String(e)));
    fetchStorageTree().then(setTree).catch(() => {});
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
      return [r.name, r.dns_name, r.site_name, r.vendor, r.model, r.service_tag, r.firmware,
        r.mgmt_ip, r.reachable_ip, r.source, r.notes, r.ip_addresses.join(" "), r.protocols.join(" ")]
        .join(" ").toLowerCase().includes(needle);
    });
  }, [rows, q, siteFilter, typeFilter, hwFilter]);

  const { sorted, sort, toggle } = useSort(filtered, {
    site: (r) => r.site_name, usable: (r) => r.capacity_usable_gb,
    used: (r) => r.capacity_used_gb, protocols: (r) => r.protocols.join(","),
  });
  const pct = (u: number | null, used: number | null) =>
    u && used ? Math.round((used / u) * 100) : null;
  const toggleExp = (k: string) =>
    setExp((s) => { const n = new Set(s); n.has(k) ? n.delete(k) : n.add(k); return n; });

  return (
    <div>
      <h2>
        💾 Storage <span className="badge">{mode === "tree" ? tree.length : `${filtered.length}/${rows.length}`}</span>
        <button style={{ marginLeft: 12 }} onClick={() => setMode(mode === "list" ? "tree" : "list")}>
          {mode === "list" ? "🌳 Baum" : "📋 Liste"}
        </button>
      </h2>
      {err && <p className="error">{err}</p>}

      {mode === "list" ? (
        <>
          <div style={{ display: "flex", gap: 8, flexWrap: "wrap", marginBottom: 8 }}>
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
                <Th k="usable" sort={sort} onSort={toggle}>Nutzbar</Th>
                <Th k="used" sort={sort} onSort={toggle}>Belegt</Th>
                <Th k="protocols" sort={sort} onSort={toggle}>Anbindung</Th>
                <Th k="mgmt_ip" sort={sort} onSort={toggle}>Mgmt-IP</Th>
                <Th k="reachable_ip" sort={sort} onSort={toggle}>Cato-IP</Th>
                <Th k="hardware_status" sort={sort} onSort={toggle}>HW</Th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {sorted.map((r) => {
                const p = pct(r.capacity_usable_gb, r.capacity_used_gb);
                return (
                  <tr key={r.id}>
                    <td>{r.name}</td>
                    <td>{r.site_name ?? <span className="muted">—</span>}</td>
                    <td><span className="badge">{r.storage_type}</span></td>
                    <td>{r.vendor}</td>
                    <td>{r.model}</td>
                    <td>{r.service_tag}</td>
                    <td>{tb(r.capacity_usable_gb)}</td>
                    <td className={p != null && p >= 90 ? "error" : ""}>{tb(r.capacity_used_gb)}{p != null && <span className="muted"> ({p}%)</span>}</td>
                    <td className="muted" style={{ fontSize: 12 }}>{r.protocols.join(", ")}</td>
                    <td>{r.mgmt_ip}</td>
                    <td className="muted">{r.reachable_ip ?? ""}</td>
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
        </>
      ) : (
        <div style={{ fontFamily: "monospace", fontSize: 13 }}>
          {tree.map((n) => {
            const p = pct(n.capacity_usable_gb, n.capacity_used_gb);
            const open = exp.has(n.key);
            return (
              <div key={n.key} style={{ borderBottom: "1px solid var(--border,#333)", padding: "2px 0" }}>
                <div onClick={() => n.children.length && toggleExp(n.key)} style={{ cursor: n.children.length ? "pointer" : "default", lineHeight: "26px" }}>
                  <span className="muted" style={{ display: "inline-block", width: 14 }}>{n.children.length ? (open ? "▼" : "▶") : ""}</span>
                  {n.is_group ? "🗄️" : "💾"} <b>{n.name}</b>{" "}
                  <span className="muted">
                    {[n.vendor, n.model, n.site_name, n.mgmt_ip, n.reachable_ip && `→${n.reachable_ip}`, n.service_tag].filter(Boolean).join(" · ")}
                    {n.capacity_usable_gb ? ` · ${tb(n.capacity_used_gb)} / ${tb(n.capacity_usable_gb)}${p != null ? ` (${p}%)` : ""}` : ""}
                    {` · ${n.children.length} LUN/Volume`}
                  </span>
                </div>
                {open && n.children.map((c) => (
                  <div key={c.id + c.name} style={{ paddingLeft: 34, lineHeight: "24px" }}>
                    📦 {c.name} <span className="muted">
                      {c.datastore_type ?? c.storage_type}
                      {c.capacity_usable_gb ? ` · ${tb(c.capacity_used_gb)} / ${tb(c.capacity_usable_gb)}` : ""}
                      {c.attachments.length ? ` · ${c.attachments.length} angebunden` : " · keine Anbindung"}
                    </span>
                    {c.attachments.length > 0 && (
                      <span className="muted" style={{ fontSize: 11 }}>
                        {" — "}{c.attachments.slice(0, 20).map((a) => `${a.kind === "vm" ? "🧩" : "🖥️"}${a.name}`).join(", ")}
                        {c.attachments.length > 20 ? ` +${c.attachments.length - 20}` : ""}
                      </span>
                    )}
                  </div>
                ))}
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
