import cytoscape from "cytoscape";
import { useEffect, useMemo, useRef, useState } from "react";
import type { VlanSurvey } from "../api";
import { fetchVlanSurvey } from "../api";
import { buildVlanTopoElements } from "../vlanTopoElements";
import { VlanTableView } from "./VlanTableView";

// VLAN-Topologie (S64): NUR die VLAN-Netze + ihre Übergänge (aus FW-Policies) — keine Switches.
// Pro Standort ein Container; Spezialknoten „Internet" und „LAN" je Standort; Cross-Site-Kanten,
// wenn dasselbe VLAN an beiden Standorten per VPN-Policy über Tunnel erlaubt ist.

interface Transition {
  vlan_id: number;
  to: string; // internet | lan | vpn | vlan
  detail: string | null;
  policy: string | null;
  device: string;
}

export function VlanTopologyView({ theme }: { theme: string }) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const [survey, setSurvey] = useState<VlanSurvey | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [selected, setSelected] = useState<{ site: string; vlanId: number } | null>(null);
  const [mode, setMode] = useState<"graph" | "table">("graph");
  const [hiddenSites, setHiddenSites] = useState<Set<string>>(new Set());

  useEffect(() => {
    fetchVlanSurvey().then(setSurvey).catch((e) => setError(String(e)));
  }, []);

  const allSites = survey ? Object.keys(survey.data.sites).sort() : [];
  const toggleSite = (site: string) =>
    setHiddenSites((prev) => {
      const next = new Set(prev);
      if (next.has(site)) next.delete(site);
      else next.add(site);
      return next;
    });

  // Sichtbare Teilmenge des Surveys (wirkt auf Graph UND Tabelle). Memoized — sonst würde
  // jede Objekt-Neuerzeugung den Graph-useEffect (und damit Cytoscape) bei jedem Render neu bauen.
  const visible = useMemo(() => {
    if (!survey) return null;
    const sites = Object.fromEntries(
      Object.entries(survey.data.sites).filter(([s]) => !hiddenSites.has(s)),
    );
    const allT = (survey.data as { transitions?: Record<string, Transition[]> }).transitions ?? {};
    const transitions = Object.fromEntries(
      Object.entries(allT).filter(([s]) => !hiddenSites.has(s)),
    );
    return { ...survey, data: { ...survey.data, sites, transitions } };
  }, [survey, hiddenSites]);

  useEffect(() => {
    if (mode !== "graph" || !containerRef.current || !visible) return;
    const labelColor = theme === "light" ? "#1e293b" : "#e2e8f0";
    const sites = visible.data.sites;
    const transitions = (visible.data as { transitions?: Record<string, Transition[]> })
      .transitions ?? {};

    // Elemente + Positionen kommen aus der getesteten, deterministischen Berechnung.
    const elements = buildVlanTopoElements({
      sites,
      transitions,
    }) as cytoscape.ElementDefinition[];

    const cy = cytoscape({
      container: containerRef.current,
      elements,
      style: [
        {
          selector: "node",
          style: {
            label: "data(label)",
            color: labelColor,
            "font-size": 10,
            "text-wrap": "wrap",
            "text-valign": "center",
            "text-halign": "center",
            shape: "round-rectangle",
            width: 110,
            height: 46,
            "background-opacity": 0.16,
            "border-width": 2,
          },
        },
        {
          selector: 'node[kind = "vlan"]',
          style: {
            "background-color": "data(color)",
            "border-color": "data(color)",
          },
        },
        {
          selector: 'node[kind = "inet"]',
          style: { "background-color": "#22c55e", "border-color": "#22c55e", shape: "ellipse", width: 90, height: 44 },
        },
        {
          selector: 'node[kind = "lan"]',
          style: { "background-color": "#94a3b8", "border-color": "#94a3b8", shape: "ellipse", width: 90, height: 44 },
        },
        {
          selector: "node:parent",
          style: {
            "background-opacity": 0.06,
            "border-width": 2,
            "border-style": "dashed",
            "border-color": "#818cf8",
            label: "data(label)",
            "text-valign": "top",
            "text-halign": "center",
            "font-weight": "bold",
            "font-size": 13,
            padding: "26px",
          },
        },
        {
          selector: "edge",
          style: { width: 2, "curve-style": "bezier", "line-color": "#cbd5e1", "target-arrow-shape": "none" },
        },
        { selector: 'edge[ekind = "inet"]', style: { "line-color": "#22c55e" } },
        { selector: 'edge[ekind = "lan"]', style: { "line-color": "#94a3b8" } },
        { selector: 'edge[ekind = "vlan"]', style: { "line-color": "#3b82f6" } },
        {
          selector: 'edge[ekind = "vpn"]',
          style: {
            "line-color": "#22c55e",
            "line-style": "dashed",
            label: "data(elabel)",
            "font-size": 9,
            color: labelColor,
          },
        },
      ],
      layout: { name: "preset" }, // Positionen sind vorberechnet (deterministisch + getestet)
    });
    cy.fit(undefined, 30);
    // Klick auf VLAN-Knoten → Info-Panel; Klick ins Leere → schließen.
    cy.on("tap", 'node[kind = "vlan"]', (ev) => {
      const [, site, vid] = String(ev.target.id()).split(":");
      setSelected({ site, vlanId: Number(vid) });
    });
    cy.on("tap", (ev) => {
      if (ev.target === cy) setSelected(null);
    });
    return () => cy.destroy();
  }, [visible, theme, mode]);

  const sel = (() => {
    if (!selected || !survey) return null;
    const v = (survey.data.sites[selected.site] ?? []).find((x) => x.vlan_id === selected.vlanId);
    if (!v) return null;
    const ts = (
      (survey.data as { transitions?: Record<string, Transition[]> }).transitions?.[
        selected.site
      ] ?? []
    ).filter((t) => t.vlan_id === selected.vlanId);
    return { v, ts };
  })();

  return (
    <div className="content" style={{ height: "100%", display: "flex", flexDirection: "column" }}>
      <div className="row" style={{ justifyContent: "space-between", alignItems: "center" }}>
        <h2 style={{ margin: "8px 0" }}>
          VLAN-Topologie{" "}
          {survey && (
            <span className="muted" style={{ fontWeight: 400, fontSize: 12 }}>
              Datenstand: {new Date(survey.created_at).toLocaleString()} (Survey)
            </span>
          )}
        </h2>
        <div className="row" style={{ gap: 4 }}>
          <button className={mode === "graph" ? "" : "ghost"} onClick={() => setMode("graph")}>
            🗺️ Graph
          </button>
          <button className={mode === "table" ? "" : "ghost"} onClick={() => setMode("table")}>
            ☰ Tabelle
          </button>
        </div>
        <div className="legend muted" style={{ margin: 0 }}>
          <span><i className="swatch" style={{ background: "#06b6d4" }} /> Testnetz</span>
          <span><i className="swatch" style={{ background: "#a855f7" }} /> Aufsetznetz</span>
          <span><i className="swatch" style={{ background: "#f59e0b" }} /> Gästenetz</span>
          <span><i className="swatch" style={{ background: "#3b82f6" }} /> Prod</span>
          <span><i className="swatch" style={{ background: "#22c55e" }} /> Internet/VPN</span>
        </div>
      </div>
      {error && <p className="error">{error}</p>}
      {!survey && !error && (
        <p className="muted">Kein Survey vorhanden — zuerst unter „Topologie" den VLAN-Survey ausführen.</p>
      )}
      <div style={{ flex: 1, minHeight: 480, display: "flex", gap: 10 }}>
        {survey && (
          <aside style={{ width: 190, flexShrink: 0, overflowY: "auto" }}>
            <h3 style={{ margin: "4px 0 6px" }}>Standorte</h3>
            {allSites.map((s) => (
              <label key={s} style={{ display: "flex", gap: 6, alignItems: "center", fontSize: 13, marginBottom: 4, cursor: "pointer" }}>
                <input type="checkbox" checked={!hiddenSites.has(s)} onChange={() => toggleSite(s)} />
                <span>{s}</span>
                <span className="badge" style={{ marginLeft: "auto" }}>{survey.data.sites[s].length}</span>
              </label>
            ))}
            <div className="row" style={{ gap: 4, marginTop: 6 }}>
              <button className="ghost" onClick={() => setHiddenSites(new Set())}>alle</button>
              <button className="ghost" onClick={() => setHiddenSites(new Set(allSites))}>keine</button>
            </div>
          </aside>
        )}
        <div style={{ flex: 1, minWidth: 0, display: "flex", flexDirection: "column" }}>
          {mode === "table" && visible && <VlanTableView survey={visible} />}
          <div style={{ flex: 1, position: "relative", display: mode === "graph" ? "block" : "none" }}>
            <div ref={containerRef} style={{ position: "absolute", inset: 0 }} />
        {sel && selected && (
          <div className="card" style={{ position: "absolute", top: 8, right: 8, width: 340, maxHeight: "90%", overflow: "auto", zIndex: 5 }}>
            <div className="row" style={{ justifyContent: "space-between", alignItems: "center" }}>
              <h3 style={{ margin: 0 }}>VLAN {sel.v.vlan_id} <span className="muted" style={{ fontSize: 12 }}>@ {selected.site}</span></h3>
              <button className="ghost" onClick={() => setSelected(null)}>✕</button>
            </div>
            <p style={{ margin: "6px 0" }}>
              {sel.v.names.map((n) => (
                <span key={n} className={"badge" + (sel.v.names.length > 1 ? " warn" : "")} style={{ marginRight: 4 }}>{n}</span>
              ))}
              {sel.v.names.length === 0 && <span className="muted">ohne Namen</span>}
            </p>
            <h4 style={{ margin: "8px 0 4px" }}>Routing / Gateway</h4>
            {sel.v.gateways.length === 0 ? (
              <p className="muted" style={{ margin: 0 }}>kein L3-Gateway bekannt</p>
            ) : (
              sel.v.gateways.map((g) => (
                <div key={g.device + g.ip} style={{ fontSize: 13 }}>{g.device} <span className="muted">({g.ip})</span></div>
              ))
            )}
            <h4 style={{ margin: "8px 0 4px" }}>DHCP</h4>
            {sel.v.dhcp_servers.length > 0 && (
              <div style={{ fontSize: 13 }}>Server: {sel.v.dhcp_servers.join(", ")}</div>
            )}
            {sel.v.dhcp_helpers.map((h) => (
              <div key={h.device} style={{ fontSize: 13 }} className="warn-text">
                Helper auf {h.device} → {h.helpers.join(", ")}
              </div>
            ))}
            {sel.v.dhcp_servers.length === 0 && sel.v.dhcp_helpers.length === 0 && (
              <p className="muted" style={{ margin: 0 }}>kein DHCP</p>
            )}
            <h4 style={{ margin: "8px 0 4px" }}>Übergänge (FW-Policies)</h4>
            {sel.ts.length === 0 ? (
              <p className="muted" style={{ margin: 0 }}>keine — isoliert</p>
            ) : (
              sel.ts.map((t, i) => (
                <div key={i} style={{ fontSize: 13 }}>
                  → {t.to === "vpn" ? `VPN ${t.detail}` : t.to === "vlan" ? `VLAN ${t.detail}` : t.to}
                  {t.policy && <span className="muted"> · Policy „{t.policy}"</span>}
                </div>
              ))
            )}
            <h4 style={{ margin: "8px 0 4px" }}>Getragen von ({sel.v.carriers.length})</h4>
            <p className="muted" style={{ fontSize: 12, margin: 0 }}>{sel.v.carriers.join(", ")}</p>
            {sel.v.access_ports > 0 && (
              <p style={{ fontSize: 13, marginTop: 6 }}>Access-Ports: {sel.v.access_ports}</p>
            )}
          </div>
        )}
          </div>
        </div>
      </div>
    </div>
  );
}
