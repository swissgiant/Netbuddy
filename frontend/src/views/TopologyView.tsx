import { useEffect, useMemo, useState } from "react";
import type { AdapterInfo, LocateResult, Topology } from "../api";
import { fetchAdapters, fetchTopology, resolveHosts, searchEndpoints } from "../api";
import type { EndpointHighlight } from "../TopologyGraph";
import { TopologyGraph } from "../TopologyGraph";

const NODE_LAYERS = ["switch", "firewall", "router", "ap", "other"] as const;
const EDGE_LAYERS = ["lldp", "vpn"] as const;

export function TopologyView({ theme }: { theme: "dark" | "light" }) {
  const [topology, setTopology] = useState<Topology | null>(null);
  const [adapters, setAdapters] = useState<AdapterInfo[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [nodeLayers, setNodeLayers] = useState<Set<string>>(new Set(NODE_LAYERS));
  const [edgeLayers, setEdgeLayers] = useState<Set<string>>(new Set(EDGE_LAYERS));
  const [fontSize, setFontSize] = useState(10);
  const [edgeWidth, setEdgeWidth] = useState(2);
  const [edgeColor, setEdgeColor] = useState("#94a3b8");
  const [query, setQuery] = useState("");
  const [hits, setHits] = useState<LocateResult[]>([]);
  const [searched, setSearched] = useState(false);
  const [resolveMsg, setResolveMsg] = useState<string | null>(null);

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
  const endpoints: EndpointHighlight[] = hits.map((h, i) => ({
    id: `ep:${i}`,
    label: h.name || h.system_name || h.mac || h.match,
    deviceId: h.device_id,
    port: h.port,
  }));

  const toggle = (set: Set<string>, setter: (s: Set<string>) => void, key: string) => {
    const next = new Set(set);
    if (next.has(key)) next.delete(key);
    else next.add(key);
    setter(next);
  };

  return (
    <div className="topo">
      <aside className="controls">
        <button className="ghost" onClick={reload}>↻ Neu laden</button>
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

        <h3>Layer — Verbindungen</h3>
        {EDGE_LAYERS.map((t) => (
          <label key={t} style={{ display: "block" }}>
            <input type="checkbox" checked={edgeLayers.has(t)} onChange={() => toggle(edgeLayers, setEdgeLayers, t)} />{" "}
            {t === "vpn" ? "VPN-Tunnel (Site↔Site)" : "LLDP-Links"}
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

      <div className="graph">
        {topology ? (
          <TopologyGraph
            topology={topology}
            visibleNodeTypes={nodeLayers}
            visibleEdgeTypes={edgeLayers}
            theme={theme}
            fontSize={fontSize}
            edgeWidth={edgeWidth}
            edgeColor={edgeColor}
            endpoints={endpoints}
          />
        ) : (
          <p style={{ padding: 16 }}>Lade Topologie…</p>
        )}
      </div>
    </div>
  );
}
