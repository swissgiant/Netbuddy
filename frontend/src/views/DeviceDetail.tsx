import { useCallback, useEffect, useState } from "react";
import type {
  ArpEntry,
  Device,
  DiscoveryRunResult,
  Interface,
  LldpNeighborRow,
  LldpStatus,
  MacEntry,
  ValidationReport,
  Vlan,
  VpnTunnel,
} from "../api";
import {
  assignPortVlan,
  backupDevice,
  discoverDevice,
  enableLldp,
  fetchArp,
  fetchInterfaces,
  fetchLldpNeighbors,
  fetchMacTable,
  fetchVlans,
  fetchVpnTunnels,
  lldpStatus,
  updateVpnTunnel,
  validateDevice,
} from "../api";
import { DeviceIcon } from "../icons";
import { Th, useSort } from "../sort";

type Tab = "ports" | "mac" | "lldp" | "arp" | "vpn" | "validation";

// Logische/virtuelle Interfaces gehören nicht aufs Faceplate.
// `po\d` = port-channel (Po1) — NICHT bare "po", sonst würde „Port 5" (UniFi) als logisch gelten.
const LOGICAL = /^(vlan|vl|loopback|lo\d|po\d|port-?channel|null|tun|mgmt|stack|cpu|bundle)/i;
const isPhysical = (name: string) => !LOGICAL.test(name.trim());
// Kurzlabel fürs Port-Kästchen: Präfix-Buchstaben weg → "1/1/1".
const shortLabel = (name: string) => name.replace(/^[A-Za-z ]+/, "").trim() || name;

function portClass(iface: Interface): string {
  if (iface.oper_status === "up") return "port up";
  if (iface.admin_status === "down") return "port admin-down";
  return "port down";
}

// Port-Geschwindigkeit → Farbklasse für den Indikator-Punkt (analog UniFi-Konsole).
const SPEED_TIERS: [number, string, string][] = [
  [100, "s-fe", "100M"],
  [1000, "s-1g", "1G"],
  [2500, "s-2g5", "2.5G"],
  [5000, "s-5g", "5G"],
  [10000, "s-10g", "10G"],
  [25000, "s-25g", "25G"],
  [Infinity, "s-100g", "100G"],
];
function speedTier(mbps: number | null | undefined): [string, string] | null {
  if (!mbps) return null;
  const t = SPEED_TIERS.find(([max]) => mbps <= max)!;
  return [t[1], t[2]];
}

export function DeviceDetail({ device }: { device: Device }) {
  const [tab, setTab] = useState<Tab>("ports");
  const [interfaces, setInterfaces] = useState<Interface[]>([]);
  const [macs, setMacs] = useState<MacEntry[]>([]);
  const [lldp, setLldp] = useState<LldpNeighborRow[]>([]);
  const [arp, setArp] = useState<ArpEntry[]>([]);
  const [validation, setValidation] = useState<ValidationReport | null>(null);
  const [run, setRun] = useState<DiscoveryRunResult | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [lldpCtl, setLldpCtl] = useState<LldpStatus | null>(null);
  const [tunnels, setTunnels] = useState<VpnTunnel[]>([]);
  const [vlans, setVlans] = useState<Vlan[]>([]);
  // Port → VLAN-Zuweisung: angeklickter Port + gewählte VLAN-ID (Panel offen, wenn gesetzt).
  const [portSel, setPortSel] = useState<{ iface: Interface; vlan: number } | null>(null);

  const loadInventory = useCallback(async () => {
    const [i, m, l, a, v, vl] = await Promise.all([
      fetchInterfaces(device.id),
      fetchMacTable(device.id),
      fetchLldpNeighbors(device.id),
      fetchArp(device.id),
      fetchVpnTunnels(device.id).catch(() => []),
      fetchVlans().catch(() => []),
    ]);
    setInterfaces(i);
    setMacs(m);
    setLldp(l);
    setArp(a);
    setTunnels(v);
    setVlans(vl);
  }, [device.id]);

  useEffect(() => {
    loadInventory().catch((e) => setError(String(e)));
  }, [loadInventory]);

  // LLDP-Status beim Aufklappen automatisch live prüfen (still — Fehler lassen den
  // manuellen „prüfen"-Button stehen). So erscheint die „aktivieren?"-Nachfrage von selbst.
  useEffect(() => {
    setLldpCtl(null);
    lldpStatus(device.id)
      .then(setLldpCtl)
      .catch(() => setLldpCtl(null));
  }, [device.id]);

  const act = async (label: string, fn: () => Promise<void>) => {
    setBusy(label);
    setError(null);
    try {
      await fn();
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(null);
    }
  };

  const runDiscover = () =>
    act("discover", async () => {
      setRun(await discoverDevice(device.id));
      await loadInventory();
    });
  const runValidate = () =>
    act("validate", async () => {
      setValidation(await validateDevice(device.id));
      setTab("validation");
    });
  const runBackup = () =>
    act("backup", async () => {
      const r = await backupDevice(device.id);
      setRun(null);
      setError(r.changed ? "Backup gespeichert (geändert)." : "Backup unverändert.");
    });
  const checkLldp = () =>
    act("lldp-status", async () => {
      setLldpCtl(await lldpStatus(device.id));
    });
  const runEnableLldp = () =>
    act("lldp-enable", async () => {
      if (!confirm("LLDP global + auf allen Ports aktivieren? Schreibzugriff (Backup wird angelegt).")) return;
      const r = await enableLldp(device.id);
      setLldpCtl({ supported: true, enabled: r.enabled_after });
      setError(
        r.enabled_after
          ? `LLDP aktiviert (global + ${r.interfaces_configured} Ports, Backup angelegt).`
          : "LLDP-Aktivierung lief, Status weiterhin AUS — bitte am Gerät prüfen.",
      );
    });

  const assignVlan = () => {
    if (!portSel) return;
    const { iface, vlan } = portSel;
    void act("assign-vlan", async () => {
      if (!confirm(`Port ${iface.name} dem VLAN ${vlan} zuweisen? Schreibzugriff (Backup wird angelegt).`))
        return;
      const r = await assignPortVlan(device.id, iface.name, vlan);
      setPortSel(null);
      await loadInventory();
      setError(
        r.verified === false
          ? `Port ${r.interface} auf VLAN ${r.vlan_id} gesetzt, aber Re-Read weicht ab — bitte prüfen.`
          : `Port ${r.interface} → VLAN ${r.vlan_id} zugewiesen (Backup angelegt).`,
      );
    });
  };

  const macCount = (ifaceId: string) => macs.filter((m) => m.interface_id === ifaceId).length;
  const neighbor = (ifaceId: string) =>
    lldp.find((n) => n.local_interface_id === ifaceId)?.remote_system_name ?? null;
  const ifaceName = (id: string) => interfaces.find((i) => i.id === id)?.name ?? "—";

  const macSort = useSort(macs, { port: (m) => ifaceName(m.interface_id) });
  const lldpSort = useSort(lldp, { port: (n) => ifaceName(n.local_interface_id) });
  const arpSort = useSort(arp);
  const vpnSort = useSort(tunnels, { remote: (t) => t.remote_subnets.join(",") || null });
  const valSort = useSort(validation?.capabilities ?? []);

  // Physische Ports in echter Switch-Reihenfolge: nach Portnummer (if_index), sonst natürlich.
  const physical = interfaces
    .filter((i) => isPhysical(i.name))
    .sort(
      (a, b) =>
        (a.if_index ?? 1e9) - (b.if_index ?? 1e9) ||
        a.name.localeCompare(b.name, undefined, { numeric: true }),
    );
  const logical = interfaces.filter((i) => !isPhysical(i.name));
  const upCount = physical.filter((i) => i.oper_status === "up").length;

  // Baumansicht (z.B. FortiGate): VLAN-Interfaces hängen unter ihrem physischen Port.
  const hasTree = interfaces.some((i) => i.parent_name);
  const treeRows: { iface: Interface; depth: number }[] = [];
  if (hasTree) {
    const byParent = new Map<string, Interface[]>();
    interfaces.forEach((i) => {
      if (i.parent_name) {
        byParent.set(i.parent_name, [...(byParent.get(i.parent_name) ?? []), i]);
      }
    });
    const known = new Set(interfaces.map((i) => i.name));
    const roots = interfaces
      .filter((i) => !i.parent_name || !known.has(i.parent_name))
      .sort((a, b) => a.name.localeCompare(b.name, undefined, { numeric: true }));
    const walk = (iface: Interface, depth: number) => {
      treeRows.push({ iface, depth });
      (byParent.get(iface.name) ?? [])
        .sort((a, b) => a.name.localeCompare(b.name, undefined, { numeric: true }))
        .forEach((child) => walk(child, depth + 1));
    };
    roots.forEach((r) => walk(r, 0));
  }

  return (
    <div className="detail">
      <div className="row" style={{ justifyContent: "space-between", alignItems: "center" }}>
        <h3 style={{ margin: 0, display: "flex", alignItems: "center", gap: 8 }}>
          <DeviceIcon type={device.device_type} size={22} />
          {device.hostname}
          <span className="muted" style={{ fontWeight: 400, fontSize: 13 }}>
            {device.mgmt_ip} · {device.adapter_id}
            {device.model ? ` · ${device.model}` : ""}
            {device.os_version ? ` · ${device.os_version}` : ""}
          </span>
        </h3>
        <div className="row" style={{ gap: 6 }}>
          <button onClick={runDiscover} disabled={busy !== null} title="Read-only auslesen → Inventar">
            {busy === "discover" ? "liest…" : "⟳ Discover"}
          </button>
          <button className="ghost" onClick={runValidate} disabled={busy !== null}
            title="Read-only Live-Check der Profil-Befehle">
            {busy === "validate" ? "prüft…" : "✓ Validieren"}
          </button>
          <button className="ghost" onClick={runBackup} disabled={busy !== null}
            title="Read-only Konfig-Backup">
            {busy === "backup" ? "sichert…" : "💾 Backup"}
          </button>
        </div>
      </div>

      {error && <p className={/^(Backup|Port|LLDP)/.test(error) ? "muted" : "error"}>{error}</p>}
      {run && (
        <p className="muted" style={{ fontSize: 13 }}>
          Discovery: <strong>{run.status}</strong>
          {run.errors.length > 0 &&
            ` · Fehler: ${run.errors.map((e) => e.capability ?? "?").join(", ")}`}
        </p>
      )}

      <div className="lldp-bar">
        {lldpCtl === null ? (
          <button className="ghost" onClick={checkLldp} disabled={busy !== null}>
            {busy === "lldp-status" ? "prüft LLDP…" : "LLDP-Status prüfen"}
          </button>
        ) : !lldpCtl.supported ? (
          <span className="muted">LLDP-Steuerung für dieses Profil nicht verfügbar.</span>
        ) : lldpCtl.enabled ? (
          <span className="ok-text">● LLDP ist aktiv</span>
        ) : (
          <span className="row" style={{ gap: 10 }}>
            <span className="warn-text">● LLDP ist AUS — der Switch wird so nicht erkannt.</span>
            <button onClick={runEnableLldp} disabled={busy !== null}
              title="Schreibzugriff: global + alle Ports, mit Backup">
              {busy === "lldp-enable" ? "aktiviert…" : "LLDP aktivieren (Schreibzugriff)"}
            </button>
          </span>
        )}
      </div>

      <div className="tabs">
        {([
          ["ports", `Ports (${physical.length})`],
          ["mac", `MAC (${macs.length})`],
          ["lldp", `LLDP (${lldp.length})`],
          ["arp", `ARP (${arp.length})`],
          ...(device.device_type === "firewall" || tunnels.length > 0
            ? ([["vpn", `VPN (${tunnels.length})`]] as [Tab, string][])
            : []),
          ["validation", "Validierung"],
        ] as [Tab, string][]).map(([k, lbl]) => (
          <button key={k} className={tab === k ? "tab active" : "tab"} onClick={() => setTab(k)}>
            {lbl}
          </button>
        ))}
      </div>

      {tab === "ports" && hasTree && (
        <table>
          <thead>
            <tr><th>Interface</th><th>Typ</th><th>VLAN</th><th>Status</th><th>Beschreibung</th></tr>
          </thead>
          <tbody>
            {treeRows.map(({ iface, depth }) => (
              <tr key={iface.id}>
                <td style={{ paddingLeft: 10 + depth * 22 }}>
                  {depth > 0 && <span className="muted">└ </span>}
                  {iface.name}
                </td>
                <td className="muted">{iface.interface_type ?? "—"}</td>
                <td>{iface.vlan_id ?? <span className="muted">—</span>}</td>
                <td>
                  <span className={`vstat ${iface.oper_status === "up" ? "ok" : "error"}`}>
                    {iface.oper_status}
                  </span>
                </td>
                <td className="muted">{iface.description ?? "—"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

      {tab === "ports" && !hasTree && (
        <>
          {physical.length === 0 ? (
            <p className="muted">Noch keine Interfaces — „⟳ Discover" ausführen.</p>
          ) : (
            <>
              <div className="faceplate">
                <div className="faceplate-label">
                  <DeviceIcon type={device.device_type} size={26} />
                  <span className="muted" style={{ fontSize: 11 }}>{upCount}/{physical.length} up</span>
                </div>
                <div className="ports">
                  {physical.map((i) => {
                    const nb = neighbor(i.id);
                    const macs_ = macCount(i.id);
                    const title = [
                      i.name,
                      i.description ? `„${i.description}"` : null,
                      `oper: ${i.oper_status} / admin: ${i.admin_status}`,
                      i.vlan_id ? `VLAN ${i.vlan_id}` : null,
                      i.speed_mbps ? `${i.speed_mbps} Mbps` : null,
                      nb ? `↔ ${nb}` : null,
                      macs_ ? `${macs_} MAC(s)` : null,
                      "▸ Klick: VLAN zuweisen",
                    ].filter(Boolean).join("\n");
                    const selected = portSel?.iface.id === i.id;
                    const spd = speedTier(i.speed_mbps);
                    return (
                      <div
                        key={i.id}
                        className={portClass(i) + (nb ? " has-neighbor" : "") + (selected ? " selected" : "")}
                        title={spd ? `${title}\nSpeed: ${spd[1]}` : title}
                        style={{ cursor: "pointer" }}
                        onClick={() =>
                          setPortSel({ iface: i, vlan: i.vlan_id ?? vlans[0]?.vlan_id ?? 0 })
                        }
                      >
                        {shortLabel(i.name)}
                        {nb && <span className="uplink" />}
                        {spd && <span className={`speed-dot ${spd[0]}`} />}
                      </div>
                    );
                  })}
                </div>
              </div>
              <div className="legend muted">
                <span><i className="dot up" /> up</span>
                <span><i className="dot down" /> down</span>
                <span><i className="dot admin-down" /> admin-down</span>
                <span><i className="dot has-neighbor" /> LLDP-Nachbar</span>
                <span>▸ Port anklicken zum VLAN-Zuweisen</span>
              </div>
              {(() => {
                const tiers = [
                  ...new Map(
                    physical
                      .map((i) => speedTier(i.speed_mbps))
                      .filter((t): t is [string, string] => t !== null)
                      .map((t) => [t[0], t[1]] as const),
                  ).entries(),
                ];
                return tiers.length ? (
                  <div className="legend muted">
                    <span>Speed:</span>
                    {tiers.map(([cls, lbl]) => (
                      <span key={cls}><i className={`swatch ${cls}`} /> {lbl}</span>
                    ))}
                  </div>
                ) : null;
              })()}
              {portSel && (
                <div className="assign-panel row" style={{ gap: 10, alignItems: "center", marginTop: 8 }}>
                  <strong>{portSel.iface.name}</strong>
                  <span className="muted">aktuell: VLAN {portSel.iface.vlan_id ?? "—"} →</span>
                  {vlans.length === 0 ? (
                    <span className="muted">keine VLANs definiert (zuerst unter „🏷️ VLANs" anlegen)</span>
                  ) : (
                    <>
                      <select
                        value={portSel.vlan}
                        onChange={(e) =>
                          setPortSel({ iface: portSel.iface, vlan: Number(e.target.value) })
                        }
                      >
                        {vlans.map((v) => (
                          <option key={v.id} value={v.vlan_id}>
                            {v.vlan_id} — {v.name}
                          </option>
                        ))}
                      </select>
                      <button onClick={assignVlan} disabled={busy !== null}
                        title="Schreibzugriff: Access-Port auf das VLAN, mit Backup">
                        {busy === "assign-vlan" ? "schreibt…" : "VLAN zuweisen (Schreibzugriff)"}
                      </button>
                    </>
                  )}
                  <button className="ghost" onClick={() => setPortSel(null)}>abbrechen</button>
                </div>
              )}
              {logical.length > 0 && (
                <p className="muted" style={{ fontSize: 12 }}>
                  Logisch: {logical.map((i) => i.name).join(", ")}
                </p>
              )}
            </>
          )}
        </>
      )}

      {tab === "mac" && (
        <table>
          <thead>
            <tr>
              <Th k="mac_address" sort={macSort.sort} onSort={macSort.toggle}>MAC</Th>
              <Th k="port" sort={macSort.sort} onSort={macSort.toggle}>Port</Th>
              <Th k="vlan_id" sort={macSort.sort} onSort={macSort.toggle}>VLAN</Th>
              <Th k="entry_type" sort={macSort.sort} onSort={macSort.toggle}>Typ</Th>
            </tr>
          </thead>
          <tbody>
            {macSort.sorted.map((m) => (
              <tr key={m.id}>
                <td>{m.mac_address}</td><td>{ifaceName(m.interface_id)}</td>
                <td>{m.vlan_id ?? "—"}</td><td className="muted">{m.entry_type}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

      {tab === "lldp" && (
        <table>
          <thead>
            <tr>
              <Th k="port" sort={lldpSort.sort} onSort={lldpSort.toggle}>lokaler Port</Th>
              <Th k="remote_system_name" sort={lldpSort.sort} onSort={lldpSort.toggle}>Nachbar</Th>
              <Th k="resolved_name" sort={lldpSort.sort} onSort={lldpSort.toggle}>Hostname (DNS)</Th>
              <Th k="resolved_ip" sort={lldpSort.sort} onSort={lldpSort.toggle}>IP (ARP/Mgmt)</Th>
              <Th k="guessed_vendor" sort={lldpSort.sort} onSort={lldpSort.toggle}>Hersteller (MAC)</Th>
              <Th k="remote_port_id" sort={lldpSort.sort} onSort={lldpSort.toggle}>Remote-Port</Th>
              <Th k="remote_chassis_id" sort={lldpSort.sort} onSort={lldpSort.toggle}>Chassis</Th>
            </tr>
          </thead>
          <tbody>
            {lldpSort.sorted.map((n) => (
              <tr key={n.id}>
                <td>{ifaceName(n.local_interface_id)}</td>
                <td>{n.remote_system_name ?? <span className="muted">?</span>}</td>
                <td>{n.resolved_name ?? <span className="muted">—</span>}</td>
                <td>{n.resolved_ip ?? <span className="muted">—</span>}</td>
                <td>{n.guessed_vendor ?? <span className="muted">—</span>}</td>
                <td className="muted">{n.remote_port_description ?? n.remote_port_id}</td>
                <td className="muted">{n.remote_chassis_id}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

      {tab === "arp" && (
        <table>
          <thead>
            <tr>
              <Th k="ip_address" sort={arpSort.sort} onSort={arpSort.toggle}>IP</Th>
              <Th k="mac" sort={arpSort.sort} onSort={arpSort.toggle}>MAC</Th>
              <Th k="vlan_id" sort={arpSort.sort} onSort={arpSort.toggle}>VLAN</Th>
            </tr>
          </thead>
          <tbody>
            {arpSort.sorted.map((a) => (
              <tr key={a.id}><td>{a.ip_address}</td><td>{a.mac}</td><td>{a.vlan_id ?? "—"}</td></tr>
            ))}
          </tbody>
        </table>
      )}

      {tab === "vpn" && (
        <>
          <table>
            <thead>
              <tr>
                <Th k="name" sort={vpnSort.sort} onSort={vpnSort.toggle}>Tunnel</Th>
                <Th k="is_up" sort={vpnSort.sort} onSort={vpnSort.toggle}>Status</Th>
                <Th k="remote_gateway" sort={vpnSort.sort} onSort={vpnSort.toggle}>Remote-Gateway</Th>
                <Th k="remote" sort={vpnSort.sort} onSort={vpnSort.toggle}>Remote-Subnetze</Th>
                <Th k="relevant" sort={vpnSort.sort} onSort={vpnSort.toggle}>berücksichtigen</Th>
              </tr>
            </thead>
            <tbody>
              {vpnSort.sorted.map((t) => (
                <tr key={t.id} style={t.relevant ? undefined : { opacity: 0.5 }}>
                  <td>{t.name}</td>
                  <td>
                    <span className={`vstat ${t.is_up ? "ok" : "error"}`}>
                      {t.is_up ? "up" : "down"}
                    </span>
                  </td>
                  <td className="muted">{t.remote_gateway ?? "—"}</td>
                  <td className="muted">{t.remote_subnets.join(", ") || "—"}</td>
                  <td>
                    <input
                      type="checkbox"
                      checked={t.relevant}
                      title="aus = Partner-/Lieferanten-Tunnel, fließt nicht in die Topologie ein"
                      onChange={(e) => {
                        const next = e.target.checked;
                        // optimistisch umschalten; bei Fehler zurückrollen + Meldung zeigen
                        setTunnels((prev) =>
                          prev.map((x) => (x.id === t.id ? { ...x, relevant: next } : x)),
                        );
                        updateVpnTunnel(device.id, t.id, next).catch((err) => {
                          setTunnels((prev) =>
                            prev.map((x) => (x.id === t.id ? { ...x, relevant: !next } : x)),
                          );
                          setError(String(err));
                        });
                      }}
                    />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          <p className="muted" style={{ fontSize: 12 }}>
            Haken raus = Tunnel zu Partnern/Lieferanten — wird in der Topologie (und später bei
            der VLAN-Orchestrierung) nicht berücksichtigt. Die Einstellung überlebt Discovery-Läufe.
          </p>
        </>
      )}

      {tab === "validation" && (
        validation ? (
          <table>
            <thead>
              <tr>
                <Th k="capability" sort={valSort.sort} onSort={valSort.toggle}>Capability</Th>
                <Th k="status" sort={valSort.sort} onSort={valSort.toggle}>Status</Th>
                <Th k="row_count" sort={valSort.sort} onSort={valSort.toggle}>Zeilen</Th>
                <th>Feld-Abdeckung</th>
              </tr>
            </thead>
            <tbody>
              {valSort.sorted.map((c) => (
                <tr key={c.capability}>
                  <td>{c.capability}</td>
                  <td>
                    <span className={`vstat ${c.status}`}>{c.status}</span>
                    {c.message && <span className="muted" title={c.message}> ⓘ</span>}
                  </td>
                  <td>{c.row_count}</td>
                  <td className="muted" style={{ fontSize: 12 }}>
                    {Object.entries(c.coverage)
                      .filter(([, v]) => v > 0)
                      .map(([f, v]) => `${f} ${Math.round(v * 100)}%`)
                      .join(" · ") || "—"}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : (
          <p className="muted">Noch nicht validiert — „✓ Validieren" ausführen (Live-Zugriff).</p>
        )
      )}
    </div>
  );
}
