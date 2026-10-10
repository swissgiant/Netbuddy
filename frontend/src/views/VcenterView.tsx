import { useEffect, useMemo, useState } from "react";
import type { Vcenter, VirtualServer } from "../api";
import { fetchVcenters, fetchVirtualServers, syncVcenters } from "../api";

interface HostEntry {
  datacenter: string;
  name: string;
  cluster: string | null;
  model?: string | null;
  cpu_cores?: number | null;
  ram_mb?: number | null;
  status?: string | null;
  vm_count?: number | null;
}

const STATUS_ICON: Record<string, string> = { green: "🟢", yellow: "🟡", red: "🔴", gray: "⚪" };
const POWER_ICON: Record<string, string> = { on: "🟢", off: "⚫", suspended: "🟡", unknown: "⚪" };
const gb = (mb: number | null | undefined) => (mb == null ? "" : `${Math.round(mb / 1024)} GB`);

function Row({ depth, id, open, onToggle, leaf, children }: {
  depth: number; id: string; open: boolean; onToggle: (id: string) => void;
  leaf?: boolean; children: React.ReactNode;
}) {
  return (
    <div
      onClick={leaf ? undefined : () => onToggle(id)}
      style={{
        paddingLeft: 8 + depth * 20, cursor: leaf ? "default" : "pointer",
        lineHeight: "26px", whiteSpace: "nowrap", userSelect: "none",
      }}
    >
      <span className="muted" style={{ display: "inline-block", width: 14 }}>
        {leaf ? "" : open ? "▼" : "▶"}
      </span>
      {children}
    </div>
  );
}

export function VcenterView() {
  const [rows, setRows] = useState<Vcenter[]>([]);
  const [vms, setVms] = useState<VirtualServer[]>([]);
  const [exp, setExp] = useState<Set<string>>(new Set());
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  const reload = () => {
    fetchVcenters().then(setRows).catch((e) => setErr(String(e)));
    fetchVirtualServers().then(setVms).catch(() => {});
  };
  useEffect(reload, []);

  const vmsByHost = useMemo(() => {
    const m = new Map<string, VirtualServer[]>();
    for (const v of vms) {
      if (!v.esxi_host) continue;
      const arr = m.get(v.esxi_host) ?? [];
      arr.push(v);
      m.set(v.esxi_host, arr);
    }
    return m;
  }, [vms]);

  const toggle = (id: string) =>
    setExp((s) => {
      const n = new Set(s);
      n.has(id) ? n.delete(id) : n.add(id);
      return n;
    });

  const sync = () => {
    setBusy(true);
    setErr(null);
    syncVcenters().then(reload).catch((e) => setErr(String(e))).finally(() => setBusy(false));
  };

  return (
    <div>
      <h2>
        ☁️ vCenter <span className="badge">{rows.length}</span>
        <button style={{ marginLeft: 12 }} disabled={busy} onClick={sync}>
          {busy ? "Sync läuft…" : "🔄 Sync"}
        </button>
      </h2>
      {err && <p className="error">{err}</p>}
      <div style={{ fontFamily: "monospace", fontSize: 13, overflow: "auto", maxHeight: "calc(100vh - 180px)", border: "1px solid var(--border)", borderRadius: 8, padding: 8 }}>
        {rows.map((vc) => {
          const hosts = (vc.hosts as unknown as HostEntry[]) ?? [];
          const vcId = vc.id;
          return (
            <div key={vc.id} style={{ borderBottom: "1px solid var(--border, #333)", paddingBottom: 6, marginBottom: 6 }}>
              <Row depth={0} id={vcId} open={exp.has(vcId)} onToggle={toggle}>
                ☁️ <b>{vc.name}</b> <span className="muted">{vc.host} · {vc.version} · {vc.host_count} Hosts · {vc.vm_count} VMs</span>
              </Row>
              {exp.has(vcId) &&
                vc.datacenters.map((dc) => {
                  const dcId = `${vcId}:${dc}`;
                  const dcClusters = vc.clusters.filter((c) => (c.datacenter as string) === dc);
                  const dcStandalone = hosts.filter((h) => h.datacenter === dc && !h.cluster);
                  return (
                    <div key={dcId}>
                      <Row depth={1} id={dcId} open={exp.has(dcId)} onToggle={toggle}>
                        🏢 {dc} <span className="muted">({dcClusters.length} Cluster, {hosts.filter((h) => h.datacenter === dc).length} Hosts)</span>
                      </Row>
                      {exp.has(dcId) && (
                        <>
                          {dcClusters.map((c) => {
                            const cId = `${dcId}:${c.name}`;
                            const cHosts = hosts.filter((h) => h.datacenter === dc && h.cluster === c.name);
                            return (
                              <div key={cId}>
                                <Row depth={2} id={cId} open={exp.has(cId)} onToggle={toggle}>
                                  🧱 {String(c.name)} <span className="muted">({c.host_count as number} Hosts, {c.vm_count as number} VMs)</span>
                                </Row>
                                {exp.has(cId) && cHosts.map((h) => <HostNode key={h.name} h={h} depth={3} exp={exp} toggle={toggle} vmsByHost={vmsByHost} base={cId} />)}
                              </div>
                            );
                          })}
                          {dcStandalone.map((h) => <HostNode key={h.name} h={h} depth={2} exp={exp} toggle={toggle} vmsByHost={vmsByHost} base={dcId} />)}
                        </>
                      )}
                    </div>
                  );
                })}
            </div>
          );
        })}
      </div>
    </div>
  );
}

function HostNode({ h, depth, exp, toggle, vmsByHost, base }: {
  h: HostEntry; depth: number; exp: Set<string>; toggle: (id: string) => void;
  vmsByHost: Map<string, VirtualServer[]>; base: string;
}) {
  const hId = `${base}:${h.name}`;
  const hostVms = vmsByHost.get(h.name) ?? [];
  return (
    <div>
      <Row depth={depth} id={hId} open={exp.has(hId)} onToggle={toggle}>
        {STATUS_ICON[h.status ?? "gray"] ?? "⚪"} 🖥️ {h.name}{" "}
        <span className="muted">{h.model} · {h.cpu_cores} Cores · {gb(h.ram_mb)} · {hostVms.length} VMs</span>
      </Row>
      {exp.has(hId) &&
        hostVms.map((v) => (
          <Row key={v.id} depth={depth + 1} id={v.id} open={false} onToggle={() => {}} leaf>
            {POWER_ICON[v.power_state] ?? "⚪"} 🧩 {v.name}{" "}
            <span className="muted">{v.vcpu} vCPU · {gb(v.ram_mb)}{v.ip_addresses.length ? ` · ${v.ip_addresses.join(", ")}` : ""}</span>
          </Row>
        ))}
    </div>
  );
}
