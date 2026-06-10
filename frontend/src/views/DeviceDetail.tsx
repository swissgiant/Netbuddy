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
  VpnTunnel,
} from "../api";
import {
  backupDevice,
  discoverDevice,
  enableLldp,
  fetchArp,
  fetchInterfaces,
  fetchLldpNeighbors,
  fetchMacTable,
  fetchVpnTunnels,
  lldpStatus,
  updateVpnTunnel,
  validateDevice,
} from "../api";
import { DeviceIcon } from "../icons";

type Tab = "ports" | "mac" | "lldp" | "arp" | "vpn" | "validation";

// Logische/virtuelle Interfaces gehören nicht aufs Faceplate.
const LOGICAL = /^(vlan|vl|lo|loopback|po|port-?channel|null|tun|mgmt|stack|cpu|bundle)/i;
const isPhysical = (name: string) => !LOGICAL.test(name.trim());
// Kurzlabel fürs Port-Kästchen: Präfix-Buchstaben weg → "1/1/1".
const shortLabel = (name: string) => name.replace(/^[A-Za-z ]+/, "").trim() || name;

function portClass(iface: Interface): string {
  if (iface.oper_status === "up") return "port up";
  if (iface.admin_status === "down") return "port admin-down";
  return "port down";
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

  const loadInventory = useCallback(async () => {
    const [i, m, l, a, v] = await Promise.all([
      fetchInterfaces(device.id),
      fetchMacTable(device.id),
      fetchLldpNeighbors(device.id),
      fetchArp(device.id),
      fetchVpnTunnels(device.id).catch(() => []),
    ]);
    setInterfaces(i);
    setMacs(m);
    setLldp(l);
    setArp(a);
    setTunnels(v);
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

  const macCount = (ifaceId: string) => macs.filter((m) => m.interface_id === ifaceId).length;
  const neighbor = (ifaceId: string) =>
    lldp.find((n) => n.local_interface_id === ifaceId)?.remote_system_name ?? null;
  const ifaceName = (id: string) => interfaces.find((i) => i.id === id)?.name ?? "—";

  const physical = interfaces.filter((i) => isPhysical(i.name));
  const logical = interfaces.filter((i) => !isPhysical(i.name));
  const upCount = physical.filter((i) => i.oper_status === "up").length;

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

      {error && <p className={error.startsWith("Backup") ? "muted" : "error"}>{error}</p>}
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

      {tab === "ports" && (
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
                      i.speed_mbps ? `${i.speed_mbps} Mbps` : null,
                      nb ? `↔ ${nb}` : null,
                      macs_ ? `${macs_} MAC(s)` : null,
                    ].filter(Boolean).join("\n");
                    return (
                      <div key={i.id} className={portClass(i) + (nb ? " has-neighbor" : "")} title={title}>
                        {shortLabel(i.name)}
                        {nb && <span className="uplink" />}
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
              </div>
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
          <thead><tr><th>MAC</th><th>Port</th><th>VLAN</th><th>Typ</th></tr></thead>
          <tbody>
            {macs.map((m) => (
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
              <th>lokaler Port</th><th>Nachbar</th><th>Hostname (DNS)</th><th>IP (ARP/Mgmt)</th>
              <th>Hersteller (MAC)</th><th>Remote-Port</th><th>Chassis</th>
            </tr>
          </thead>
          <tbody>
            {lldp.map((n) => (
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
          <thead><tr><th>IP</th><th>MAC</th><th>VLAN</th></tr></thead>
          <tbody>
            {arp.map((a) => (
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
                <th>Tunnel</th><th>Status</th><th>Remote-Gateway</th>
                <th>Remote-Subnetze</th><th>berücksichtigen</th>
              </tr>
            </thead>
            <tbody>
              {tunnels.map((t) => (
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
            <thead><tr><th>Capability</th><th>Status</th><th>Zeilen</th><th>Feld-Abdeckung</th></tr></thead>
            <tbody>
              {validation.capabilities.map((c) => (
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
