import { useEffect, useMemo, useState } from "react";
import type { AdapterInfo, LocateResult, Topology } from "../api";
import { fetchAdapters, fetchTopology, resolveHosts, searchEndpoints } from "../api";
import type { EndpointHighlight } from "../TopologyGraph";
import { clearSavedPositions, TopologyGraph } from "../TopologyGraph";
import { VlanSurveyPanel } from "./VlanSurveyPanel";

const NODE_LAYERS = ["switch", "firewall", "router", "ap", "unknown", "other"] as const;
const EDGE_LAYERS = ["lldp", "uplink", "wireless", "vpn"] as const;
const EDGE_LABEL: Record<string, string> = {
  lldp: "LLDP (Backbone)",
  uplink: "AP-/Switch-Uplinks",
  wireless: "Mesh (drahtlos)",
  vpn: "VPN-Tunnel (Site↔Site)",
};

export function TopologyView({ theme }: { theme: "dark" | "light" }) {
  const [topology, setTopology] = useState<Topology | null>(null);
  const [adapters, setAdapters] = useState<AdapterInfo[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [nodeLayers, setNodeLayers] = useState<Set<string>>(new Set(NODE_LAYERS));
  const [edgeLayers, setEdgeLayers] = useState<Set<string>>(new Set(EDGE_LAYERS));
  // Standorte standardmäßig alle sichtbar; hier nur die AUSGEBLENDETEN merken.
  const [excludedSites, setExcludedSites] = useState<Set<string>>(new Set());
  const [fontSize, setFontSize] = useState(10);
  const [edgeWidth, setEdgeWidth] = useState(2);
  const [edgeColor, setEdgeColor] = useState("#94a3b8");
  const [query, setQuery] = useState("");
  const [hits, setHits] = useState<LocateResult[]>([]);
  const [searched, setSearched] = useState(false);
  const [resolveMsg, setResolveMsg] = useState<string | null>(null);
  const [layoutNonce, setLayoutNonce] = useState(0);

  const tidyLayout = () => {
    clearSavedPositions();
    setLayoutNonce((n) => n + 1);
  };

  const reload = () => {
    fetchTopology().then(setTopology).catch((e) => setError(String(e)));
    fetchAdapters().then(setAdapters).catch(() => {});
  };
  useEffect(reload, []);

  const counts = useMemo(() => {
    const c: Record<string, number> = {};
    topology?.nodes.forEach((n) => (c[n.type] = (c[n.type] ?? 0) + 1));
    return c;
  }, [topology]);

  // Standort-Container (type === "site") für den Standort-Filter.
  const sites = useMemo(
    () => topology?.nodes.filter((n) => n.type === "site").map((n) => ({ id: n.id, label: n.label })) ?? [],
    [topology],
  );

  // Topologie nach Standort-Auswahl filtern (Geräte folgen ihrem Standort-Container).
  const shown = useMemo<Topology | null>(() => {
    if (!topology) return null;
    const visible = (siteId: string | null) => siteId == null || !excludedSites.has(siteId);
    const nodes = topology.nodes.filter((n) =>
      n.type === "site" ? !excludedSites.has(n.id) : visible(n.parent),
    );
    const ids = new Set(nodes.map((n) => n.id));
    const edges = topology.edges.filter((e) => ids.has(e.source) && ids.has(e.target));
    return { nodes, edges };
  }, [topology, excludedSites]);

  const runSearch = async () => {
    if (!query.trim()) return;
    setSearched(true);
    try {
      setHits(await searchEndpoints(query.trim()));
    } catch (e) {
      setError(String(e));
    }
  };
  const clearSearch = () => {
    setQuery("");
    setHits([]);
    setSearched(false);
  };
  const runResolve = async () => {
    setResolveMsg("Löse Namen auf…");
    try {
      const r = await resolveHosts();
      setResolveMsg(`${r.resolved}/${r.hosts} Hosts mit Namen aufgelöst`);
    } catch (e) {
      setResolveMsg(String(e));
    }
  };

  // Such-Treffer → ephemere Endgerät-Knoten (eindeutig je Switch+Port+Match).
  // Memoisiert: sonst neue Array-Identität bei JEDEM Render (jeder Tastendruck/Slider-Tick)
  // → der Cytoscape-Highlight-Effekt liefe ständig neu (graph-weites removeClass/redraw).
  const endpoints: EndpointHighlight[] = useMemo(
    () =>
      hits.map((h, i) => ({
        id: `ep:${i}`,
        label: h.name || h.system_name || h.mac || h.match,
        deviceId: h.device_id,
        port: h.port,
      })),
    [hits],
  );

  const toggle = (set: Set<string>, setter: (s: Set<string>) => void, key: string) => {
    const next = new Set(set);
    if (next.has(key)) next.delete(key);
    else next.add(key);
    setter(next);
  };

  const toggleExcluded = (id: string) =>
    setExcludedSites((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });

  return (
    <div className="topo">
      <aside className="controls">
        <div style={{ display: "flex", gap: 6 }}>
          <button className="ghost" onClick={reload}>↻ Neu laden</button>
          <button className="ghost" onClick={tidyLayout} title="Knoten neu strukturiert anordnen">
            🧹 Layout aufräumen
          </button>
        </div>
        {error && <p className="error">{error}</p>}

        <h3>Suche (Gerät / MAC / IP)</h3>
        <div style={{ display: "flex", gap: 4 }}>
          <input
            placeholder="z.B. Name, aa:bb:cc, 10.x"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && runSearch()}
            style={{ flex: 1, minWidth: 0 }}
          />
          <button onClick={runSearch}>🔍</button>
        </div>
        <div className="row" style={{ marginTop: 4, justifyContent: "space-between" }}>
          <button className="ghost" onClick={runResolve} title="ARP→IP→DNS korrelieren">
            Namen auflösen
          </button>
          {resolveMsg && <span className="muted" style={{ fontSize: 11 }}>{resolveMsg}</span>}
        </div>
        {searched && (
          <div style={{ fontSize: 12, marginTop: 6 }}>
            <div className="row" style={{ justifyContent: "space-between" }}>
              <span className="muted">{hits.length} Treffer</span>
              <a style={{ cursor: "pointer" }} onClick={clearSearch}>ausblenden ✕</a>
            </div>
            {hits.map((h, i) => (
              <div key={i} style={{ marginTop: 4 }}>
                <strong>{h.name || h.system_name || h.mac || h.match}</strong>
                {h.kind === "host" && <span className="muted"> · aufgelöst</span>}
                <br />
                <span className="muted">
                  {h.device_hostname} / {h.port}
                  {h.ip_address ? ` · ${h.ip_address}` : ""}
                  {h.vlan != null ? ` · VLAN ${h.vlan}` : ""}
                </span>
              </div>
            ))}
          </div>
        )}

        <h3>Layer — Geräte</h3>
        {NODE_LAYERS.map((t) => (
          <label key={t} style={{ display: "block" }}>
            <input type="checkbox" checked={nodeLayers.has(t)} onChange={() => toggle(nodeLayers, setNodeLayers, t)} />{" "}
            {t} {counts[t] ? `(${counts[t]})` : ""}
          </label>
        ))}

        {sites.length > 0 && (
          <>
            <h3>Standorte</h3>
            {sites.map((s) => (
              <label key={s.id} style={{ display: "block" }}>
                <input
                  type="checkbox"
                  checked={!excludedSites.has(s.id)}
                  onChange={() => toggleExcluded(s.id)}
                />{" "}
                {s.label}
              </label>
            ))}
          </>
        )}

        <h3>Layer — Verbindungen</h3>
        {EDGE_LAYERS.map((t) => (
          <label key={t} style={{ display: "block" }}>
            <input type="checkbox" checked={edgeLayers.has(t)} onChange={() => toggle(edgeLayers, setEdgeLayers, t)} />{" "}
            {EDGE_LABEL[t] ?? t}
          </label>
        ))}

        <h3>Darstellung</h3>
        <label style={{ display: "block", fontSize: 12 }}>
          Schriftgröße: {fontSize}px
          <input type="range" min={6} max={28} value={fontSize}
            onChange={(e) => setFontSize(Number(e.target.value))} style={{ width: "100%" }} />
        </label>
        <label style={{ display: "block", fontSize: 12 }}>
          Linien-Breite: {edgeWidth}px
          <input type="range" min={1} max={10} value={edgeWidth}
            onChange={(e) => setEdgeWidth(Number(e.target.value))} style={{ width: "100%" }} />
        </label>
        <label style={{ display: "block", fontSize: 12 }}>
          Linien-Farbe{" "}
          <input type="color" value={edgeColor} onChange={(e) => setEdgeColor(e.target.value)} />
        </label>

        <h3>Adapter-Status</h3>
        {adapters.map((a) => (
          <div key={a.adapter_id} style={{ fontSize: 12, marginBottom: 6 }}>
            <strong>{a.adapter_id}</strong>
            <br />
            {a.capabilities.map((c) => (
              <span key={c.capability} title={`${c.capability}: ${c.validated ? "validiert" : "offen"}`}>
                {c.validated ? "✅" : "⬜"}
              </span>
            ))}
          </div>
        ))}
      </aside>

      <div className="graph" style={{ overflowY: "auto" }}>
        <div style={{ height: "70vh", minHeight: 420 }}>
          {shown ? (
            <TopologyGraph
              topology={shown}
              visibleNodeTypes={nodeLayers}
              visibleEdgeTypes={edgeLayers}
              theme={theme}
              fontSize={fontSize}
              edgeWidth={edgeWidth}
              edgeColor={edgeColor}
              endpoints={endpoints}
              layoutNonce={layoutNonce}
            />
          ) : (
            <p style={{ padding: 16 }}>Lade Topologie…</p>
          )}
        </div>
        <div style={{ padding: "0 14px 14px" }}>
          <VlanSurveyPanel />
        </div>
      </div>
    </div>
  );
}
