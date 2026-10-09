import { useState } from "react";
import type { CatoCandidate, CatoPolicy, CatoSite, CatoSyncSummary } from "../api";
import { createDevice, fetchCatoDevices, fetchCatoHosts, fetchCatoPolicy, fetchCatoSites, syncCato } from "../api";

const POLICY_KINDS: { key: string; label: string; hint: string }[] = [
  { key: "wan", label: "WAN-Firewall", hint: "Site ↔ Site / User ↔ Site über das Cato-WAN" },
  { key: "internet", label: "Internet-Firewall", hint: "Zugriff aus Sites/Usern ins Internet" },
  { key: "lan", label: "Socket-LAN-Firewall", hint: "lokal am Socket zwischen VLANs/Ranges, inkl. NAT" },
  { key: "bypass", label: "Socket-Bypass", hint: "Traffic, der am Cato-Tunnel vorbei direkt aus dem Socket geht" },
  { key: "wan_network", label: "WAN-Network-Regeln", hint: "Routing/Transport/QoS im Cato-WAN" },
];

const ADAPTERS = [
  "cisco_ios",
  "cisco_nxos",
  "dell_os10",
  "dell_os6",
  "aruba_cx",
  "fs_centec",
  "fs_ruijie",
  "tplink_jetstream",
  "fortigate",
  "meraki",
  "unifi",
  "unifi_cloud",
  "watchguard",
];

function fmtTime(iso: string | null): string {
  if (!iso) return "—";
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? iso : d.toLocaleString("de-CH");
}

export function CatoView() {
  const [sites, setSites] = useState<CatoSite[]>([]);
  const [open, setOpen] = useState<Record<string, boolean>>({});
  const [devices, setDevices] = useState<CatoCandidate[] | null>(null);
  const [policyKind, setPolicyKind] = useState("wan");
  const [policy, setPolicy] = useState<CatoPolicy | null>(null);
  const [ruleFilter, setRuleFilter] = useState("");
  const [infraOnly, setInfraOnly] = useState(true);
  const [siteFilter, setSiteFilter] = useState("");
  const [summary, setSummary] = useState<CatoSyncSummary | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [msg, setMsg] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const run = async (key: string, fn: () => Promise<void>) => {
    setBusy(key);
    setMsg(null);
    setError(null);
    try {
      await fn();
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(null);
    }
  };

  const loadSites = () =>
    run("sites", async () => {
      const s = await fetchCatoSites();
      setSites(s);
      setMsg(`${s.length} Cato-Sites geladen, ${s.reduce((n, x) => n + x.ranges.length, 0)} Netzbereiche.`);
    });

  const doSync = (dryRun: boolean) =>
    run(dryRun ? "preview" : "sync", async () => {
      const r = await syncCato(dryRun);
      setSummary(r);
      setMsg(dryRun ? "Vorschau berechnet — nichts geändert." : "Sync übernommen.");
    });

  const loadDevices = () =>
    run("devices", async () => {
      const d = await fetchCatoDevices(infraOnly);
      setDevices(d);
      setMsg(`${d.length} Geräte aus dem Cato-Inventar${infraOnly ? " (nur Infrastruktur-Verdacht)" : ""}.`);
    });

  const loadHosts = () =>
    run("hosts", async () => {
      const d = await fetchCatoHosts(infraOnly);
      setDevices(d);
      setMsg(`${d.length} Known Hosts aus den Cato-Sockets${infraOnly ? " (nur Infrastruktur-Verdacht)" : ""}.`);
    });

  const loadPolicy = () =>
    run("policy", async () => {
      const p = await fetchCatoPolicy(policyKind);
      setPolicy(p);
      setMsg(`${p.rules.length} Regeln (${POLICY_KINDS.find((k) => k.key === p.kind)?.label ?? p.kind}).`);
    });

  const adopt = async (c: CatoCandidate) => {
    if (!c.ip) {
      setError("Kein IP-Eintrag im Cato-Inventar — Gerät manuell anlegen.");
      return;
    }
    const adapter =
      c.guessed_adapter ??
      prompt(`Profil für ${c.name ?? c.ip}? (${ADAPTERS.join(", ")})`, "cisco_ios") ??
      "";
    if (!adapter) return;
    const isFw = adapter === "fortigate" || adapter === "watchguard";
    try {
      await createDevice({
        hostname: c.name || c.ip,
        mgmt_ip: c.ip,
        vendor: (c.manufacturer ?? c.nic_vendor ?? "").toLowerCase() || "unknown",
        model: c.hw_model,
        adapter_id: adapter,
        device_type: isFw ? "firewall" : /access point|wireless|wlan/i.test(c.hw_type ?? "") ? "ap" : "switch",
      });
      setDevices((ds) => (ds ?? []).map((x) => (x.id === c.id ? { ...x, known_device_id: "neu" } : x)));
      setMsg(`${c.name ?? c.ip} als Gerät angelegt (Credential im Geräte-Detail zuordnen).`);
    } catch (e) {
      setError(String(e));
    }
  };

  const siteNames = Array.from(new Set((devices ?? []).map((d) => d.site ?? "—"))).sort();
  const needle = ruleFilter.trim().toLowerCase();
  const shownRules = (policy?.rules ?? []).filter(
    (r) =>
      !needle ||
      [r.name, r.section, r.sites, r.source, r.destination, r.application, r.service, r.extra, r.action, r.description]
        .filter(Boolean)
        .some((x) => String(x).toLowerCase().includes(needle)),
  );
  const shown = (devices ?? []).filter((d) => !siteFilter || (d.site ?? "—") === siteFilter);

  return (
    <div>
      <h2>☁️ Cato Networks</h2>
      <p className="muted">
        Lesend über die Cato-GraphQL-API (Credential mit <code>base_url</code>{" "}
        <code>https://api.catonetworks.com</code>, <code>api_token</code> = API-Key und{" "}
        <code>account_id</code>). „Sites laden" zeigt alle Cato-Standorte mit Sockets und
        Netzbereichen. „Sync" legt daraus NetBuddy-Standorte, Segmente und Socket-Geräte an
        (Vorschau zuerst). „Geräte-Inventar" durchsucht die Cato-Asset-Sicht nach
        Switches/Firewalls/APs, die NetBuddy noch nicht kennt.
      </p>

      <div style={{ display: "flex", gap: 8, marginBottom: 12, flexWrap: "wrap" }}>
        <button onClick={loadSites} disabled={busy !== null}>
          {busy === "sites" ? "Lade…" : "↻ Sites & Netze laden"}
        </button>
        <button onClick={() => doSync(true)} disabled={busy !== null}>
          {busy === "preview" ? "Rechne…" : "👁 Sync-Vorschau"}
        </button>
        <button
          onClick={() => {
            if (confirm("Standorte, Segmente und Socket-Geräte aus Cato jetzt anlegen/aktualisieren?")) void doSync(false);
          }}
          disabled={busy !== null || !summary || !summary.dry_run}
        >
          {busy === "sync" ? "Übernehme…" : "⬇ Sync übernehmen"}
        </button>
        <span style={{ flex: 1 }} />
        <label style={{ display: "flex", gap: 6, alignItems: "center" }}>
          <input type="checkbox" checked={infraOnly} onChange={(e) => setInfraOnly(e.target.checked)} />
          nur Infrastruktur-Verdacht
        </label>
        <button onClick={loadDevices} disabled={busy !== null} title="Cato-Geräte-Inventar (devices-API, Lizenz nötig)">
          {busy === "devices" ? "Lade…" : "🔍 Geräte-Inventar laden"}
        </button>
        <button onClick={loadHosts} disabled={busy !== null} title="Known Hosts je Site (Socket-Sicht: Name/IP/MAC/User/OS, Hersteller per OUI)">
          {busy === "hosts" ? "Lade…" : "🧭 Known-Hosts laden"}
        </button>
      </div>
      <div style={{ display: "flex", gap: 8, marginBottom: 12, flexWrap: "wrap", alignItems: "center" }}>
        <strong>Firewall / Policies:</strong>
        <select value={policyKind} onChange={(e) => setPolicyKind(e.target.value)}>
          {POLICY_KINDS.map((k) => <option key={k.key} value={k.key}>{k.label}</option>)}
        </select>
        <button onClick={loadPolicy} disabled={busy !== null}>{busy === "policy" ? "Lade…" : "📜 Regeln laden"}</button>
        <span className="muted">{POLICY_KINDS.find((k) => k.key === policyKind)?.hint}</span>
      </div>
      {msg && <p style={{ color: "var(--ok, green)" }}>{msg}</p>}
      {error && <p className="error">{error}</p>}

      {summary && (
        <div className="card" style={{ marginBottom: 16 }}>
          <strong>{summary.dry_run ? "Sync-Vorschau" : "Sync-Ergebnis"}</strong>
          <ul>
            <li>Neue Standorte ({summary.sites_created.length}): {summary.sites_created.join(", ") || "—"}</li>
            <li>Zugeordnet ({summary.sites_matched.length}): {summary.sites_matched.join("; ") || "—"}</li>
            {summary.sites_skipped.length > 0 && (
              <li className="muted">Übersprungen (site_map): {summary.sites_skipped.join(", ")}</li>
            )}
            <li>Neue Segmente ({summary.subnets_created.length}), {summary.subnets_existing} schon vorhanden</li>
            {summary.subnets_created.length > 0 && (
              <ul>{summary.subnets_created.map((s) => <li key={s}><code>{s}</code></li>)}</ul>
            )}
            {summary.subnets_conflict.length > 0 && (
              <li style={{ color: "var(--warn, orange)" }}>
                Konflikte: {summary.subnets_conflict.join("; ")}
              </li>
            )}
            <li>
              Sockets: {summary.sockets_created} neu, {summary.sockets_updated} aktualisiert
              {summary.sockets_skipped.length > 0 && ` — übersprungen (ohne LAN-IP/Serial): ${summary.sockets_skipped.join(", ")}`}
            </li>
          </ul>
        </div>
      )}

      {sites.length > 0 && (
        <table style={{ marginBottom: 20 }}>
          <thead>
            <tr>
              <th>Cato-Site</th>
              <th>Typ</th>
              <th>Status</th>
              <th>PoP</th>
              <th>Sockets</th>
              <th>Netze</th>
            </tr>
          </thead>
          <tbody>
            {sites.map((s) => (
              <>
                <tr key={s.id} onClick={() => setOpen((o) => ({ ...o, [s.id]: !o[s.id] }))} style={{ cursor: "pointer" }}>
                  <td>{open[s.id] ? "▾" : "▸"} {s.name}</td>
                  <td className="muted">{s.type ?? "—"} / {s.conn_type ?? "—"}{s.is_ha ? " (HA)" : ""}</td>
                  <td>
                    <span className="badge" style={{ background: s.connectivity === "connected" ? "var(--ok, green)" : "var(--warn, orange)" }}>
                      {s.connectivity ?? "?"}
                    </span>
                  </td>
                  <td className="muted">{s.pop ?? "—"}</td>
                  <td className="muted">
                    {s.sockets.map((k) => `${k.name ?? k.serial ?? "?"}${k.internal_ip ? ` ${k.internal_ip}` : ""}${k.connected === false ? " ⚠" : ""}`).join(", ") || "—"}
                  </td>
                  <td>{s.ranges.length}{s.host_count != null ? ` (${s.host_count} Hosts)` : ""}</td>
                </tr>
                {open[s.id] && (
                  <tr key={`${s.id}-r`}>
                    <td colSpan={7}>
                      <table>
                        <thead>
                          <tr><th>Netzbereich</th><th>Subnetz (innen)</th><th>NAT (von aussen)</th><th>VLAN</th><th>Gateway / Socket-IP</th><th>DHCP</th><th>Typ</th></tr>
                        </thead>
                        <tbody>
                          {s.ranges.map((r) => (
                            <tr key={r.id ?? `${r.subnet}-${r.vlan}`}>
                              <td>{r.name ?? "—"}</td>
                              <td><code>{r.subnet ?? "—"}</code></td>
                              <td>{r.translated_subnet ? <code title="Range-NAT: andere Cato-Sites erreichen dieses Netz nur über diese Adresse">{r.translated_subnet}</code> : <span className="muted">—</span>}</td>
                              <td>{r.vlan ?? "—"}</td>
                              <td className="muted">{r.gateway ?? r.local_ip ?? "—"}</td>
                              <td className="muted">{r.dhcp_type ?? "—"}{r.dhcp_range ? ` ${r.dhcp_range}` : ""}</td>
                              <td className="muted">{r.range_type ?? "—"}{r.internet_only ? " (nur Internet)" : ""}</td>
                            </tr>
                          ))}
                          {s.ranges.length === 0 && <tr><td colSpan={7} className="muted">keine Netzbereiche (IPsec-/Cloud-Site?)</td></tr>}
                        </tbody>
                      </table>
                    </td>
                  </tr>
                )}
              </>
            ))}
          </tbody>
        </table>
      )}

      {policy && (
        <div style={{ marginBottom: 20 }}>
          <div style={{ display: "flex", gap: 8, alignItems: "center", marginBottom: 8, flexWrap: "wrap" }}>
            <strong>{POLICY_KINDS.find((k) => k.key === policy.kind)?.label ?? policy.kind}</strong>
            <span className="muted">
              {policy.enabled === false ? "Policy deaktiviert · " : ""}
              {policy.published_at ? `veröffentlicht ${fmtTime(policy.published_at)}${policy.published_by ? ` von ${policy.published_by}` : ""}` : ""}
            </span>
            <input placeholder="Filter (Name, Quelle, Ziel, Service…)" value={ruleFilter} onChange={(e) => setRuleFilter(e.target.value)} style={{ minWidth: 260 }} />
            <span className="muted">{shownRules.length} / {policy.rules.length}</span>
          </div>
          <table>
            <thead>
              <tr>
                <th>#</th><th>Status</th><th>Aktion</th><th>Name</th><th>Sektion</th><th>Sites</th><th>Quelle</th><th>Ziel</th><th>App</th><th>Service</th><th>Extra</th>
              </tr>
            </thead>
            <tbody>
              {shownRules.map((r) => (
                <tr key={`${r.kind}-${r.index}-${r.name}`} style={{ opacity: r.enabled ? 1 : 0.5 }}>
                  <td>{r.index ?? "—"}</td>
                  <td>{r.enabled ? "an" : "aus"}</td>
                  <td>
                    <span className="badge" style={{ background: /BLOCK/i.test(r.action ?? "") ? "var(--warn, orange)" : /ALLOW|BYPASS/i.test(r.action ?? "") ? "var(--ok, green)" : undefined }}>
                      {r.action ?? "—"}{r.direction ? ` ${r.direction}` : ""}
                    </span>
                  </td>
                  <td title={r.description ?? undefined}>{r.name}</td>
                  <td className="muted">{r.section ?? "—"}</td>
                  <td className="muted">{r.sites ?? "—"}</td>
                  <td><code>{r.source}</code></td>
                  <td><code>{r.destination}</code></td>
                  <td className="muted">{r.application ?? "—"}</td>
                  <td className="muted">{r.service ?? "alle"}</td>
                  <td className="muted">{r.extra ?? ""}</td>
                </tr>
              ))}
              {shownRules.length === 0 && <tr><td colSpan={11} className="muted">keine Regeln</td></tr>}
            </tbody>
          </table>
        </div>
      )}

      {devices && (
        <>
          <div style={{ display: "flex", gap: 8, alignItems: "center", marginBottom: 8 }}>
            <strong>Geräte-Inventar</strong>
            <select value={siteFilter} onChange={(e) => setSiteFilter(e.target.value)}>
              <option value="">alle Sites</option>
              {siteNames.map((n) => <option key={n} value={n}>{n}</option>)}
            </select>
            <span className="muted">{shown.length} Einträge</span>
          </div>
          <table>
            <thead>
              <tr>
                <th>Name</th>
                <th>IP</th>
                <th>MAC / Hersteller</th>
                <th>Typ / Modell</th>
                <th>OS</th>
                <th>Site / Netz</th>
                <th>zuletzt</th>
                <th>Verdacht</th>
                <th>NetBuddy</th>
              </tr>
            </thead>
            <tbody>
              {shown.map((c) => (
                <tr key={c.id ?? `${c.ip}-${c.mac}`}>
                  <td>{c.name ?? "—"}</td>
                  <td><code>{c.ip ?? "—"}</code></td>
                  <td className="muted">{c.mac ?? "—"}<br />{c.manufacturer ?? c.nic_vendor ?? ""}</td>
                  <td className="muted">{c.hw_type ?? c.category ?? "—"}{c.hw_model ? ` / ${c.hw_model}` : ""}</td>
                  <td className="muted">{c.os ?? "—"}</td>
                  <td className="muted">{c.site ?? "—"}<br />{c.network_name ?? c.subnet ?? ""}</td>
                  <td className="muted">{fmtTime(c.last_seen)}</td>
                  <td>
                    <span className="badge">{c.reason}</span>{" "}
                    {c.guessed_adapter && <span className="badge">{c.guessed_adapter}</span>}
                  </td>
                  <td>
                    {c.known_device_id ? (
                      <span className="muted">✓ bekannt</span>
                    ) : (
                      <button onClick={() => adopt(c)} disabled={!c.ip}>+ Gerät anlegen</button>
                    )}
                  </td>
                </tr>
              ))}
              {shown.length === 0 && <tr><td colSpan={9} className="muted">keine Einträge</td></tr>}
            </tbody>
          </table>
        </>
      )}
    </div>
  );
}
