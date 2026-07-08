import { useEffect, useState } from "react";
import type { SurveyVlan, VlanSurvey } from "../api";
import { fetchVlanSurvey, startVlanSurvey, vlanSurveyStatus } from "../api";

// VLAN-Ist-Zustand pro Standort (S63): wo geroutet, DHCP-Art, Träger — Basis fürs Konsolidieren.
export function VlanSurveyPanel() {
  const [survey, setSurvey] = useState<VlanSurvey | null>(null);
  const [running, setRunning] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [openSite, setOpenSite] = useState<string | null>(null);

  const load = () => fetchVlanSurvey().then(setSurvey).catch((e) => setError(String(e)));
  useEffect(() => {
    void load();
  }, []);

  // Solange ein Survey läuft: pollen, bis der neue Lauf auftaucht.
  useEffect(() => {
    if (!running) return;
    const t = setInterval(async () => {
      try {
        const st = await vlanSurveyStatus();
        if (!st.running) {
          setRunning(false);
          await load();
        }
      } catch {
        /* Poll-Fehler ignorieren */
      }
    }, 5000);
    return () => clearInterval(t);
  }, [running]);

  const run = async () => {
    setError(null);
    try {
      await startVlanSurvey();
      setRunning(true);
    } catch (e) {
      setError(String(e));
    }
  };

  const dhcpBadge = (v: SurveyVlan) => {
    if (v.dhcp_helpers.length > 0) {
      const ips = v.dhcp_helpers.flatMap((h) => h.helpers).join(", ");
      return <span className="badge warn" title={`DHCP-Relay auf ${v.dhcp_helpers.map((h) => h.device).join(", ")}`}>Helper → {ips}</span>;
    }
    if (v.dhcp_servers.length > 0) {
      return <span className="badge ok">DHCP: {v.dhcp_servers.join(", ")}</span>;
    }
    return <span className="badge muted">kein DHCP</span>;
  };

  const sites = survey?.data.sites ?? {};

  return (
    <div className="card" style={{ marginTop: 16 }}>
      <div className="row" style={{ justifyContent: "space-between", alignItems: "center" }}>
        <h3 style={{ margin: 0 }}>
          VLANs pro Standort{" "}
          {survey && (
            <span className="muted" style={{ fontWeight: 400, fontSize: 12 }}>
              Stand: {new Date(survey.created_at).toLocaleString()}
            </span>
          )}
        </h3>
        <button onClick={run} disabled={running} title="Read-only: liest live Configs/Controller/FW (dauert einige Minuten)">
          {running ? "Survey läuft…" : "⟳ Survey ausführen"}
        </button>
      </div>
      {error && <p className="error">{error}</p>}
      {!survey && !running && (
        <p className="muted">Noch kein Survey — „⟳ Survey ausführen" (read-only, einige Minuten).</p>
      )}

      {Object.entries(sites).map(([site, vlans]) => {
        const open = openSite === site;
        const helpers = vlans.filter((v) => v.dhcp_helpers.length > 0).length;
        const noGw = vlans.filter((v) => v.gateways.length === 0).length;
        const nameConflicts = vlans.filter((v) => v.names.length > 1).length;
        return (
          <div key={site} style={{ marginTop: 8 }}>
            <a style={{ cursor: "pointer", fontWeight: 600 }} onClick={() => setOpenSite(open ? null : site)}>
              {open ? "▾" : "▸"} {site} <span className="badge">{vlans.length} VLANs</span>
              {helpers > 0 && <span className="badge warn" style={{ marginLeft: 6 }}>{helpers}× DHCP-Helper</span>}
              {nameConflicts > 0 && <span className="badge warn" style={{ marginLeft: 6 }}>{nameConflicts}× Namens-Konflikt</span>}
              {noGw > 0 && <span className="badge muted" style={{ marginLeft: 6 }}>{noGw}× ohne Gateway</span>}
            </a>
            {open && (
              <table style={{ marginTop: 6 }}>
                <thead>
                  <tr>
                    <th>VLAN</th>
                    <th>Name(n)</th>
                    <th>Geroutet über (Gateway)</th>
                    <th>DHCP</th>
                    <th>Getragen von</th>
                    <th>Access-Ports</th>
                  </tr>
                </thead>
                <tbody>
                  {vlans.map((v) => (
                    <tr key={v.vlan_id}>
                      <td>{v.vlan_id}</td>
                      <td>
                        {v.names.length === 0 && <span className="muted">—</span>}
                        {v.names.map((n) => (
                          <span key={n} className={v.names.length > 1 ? "badge warn" : ""} style={{ marginRight: 4 }}>
                            {n}
                          </span>
                        ))}
                      </td>
                      <td>
                        {v.gateways.length === 0 ? (
                          <span className="muted">kein L3-Gateway</span>
                        ) : (
                          v.gateways.map((g) => (
                            <div key={g.device + g.ip} style={{ fontSize: 12 }}>
                              {g.device} <span className="muted">({g.ip})</span>
                            </div>
                          ))
                        )}
                      </td>
                      <td>{dhcpBadge(v)}</td>
                      <td className="muted" style={{ fontSize: 12 }} title={v.carriers.join(", ")}>
                        {v.carriers.length} Gerät{v.carriers.length !== 1 ? "e" : ""}
                      </td>
                      <td>{v.access_ports || <span className="muted">0</span>}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>
        );
      })}
      {survey && survey.data.device_errors.length > 0 && (
        <p className="muted" style={{ fontSize: 12, marginTop: 8 }}>
          Nicht erreichbar: {survey.data.device_errors.map((e) => e.device).join(", ")}
        </p>
      )}
    </div>
  );
}
